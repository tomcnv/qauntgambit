"""ConversationManager — PostgreSQL-backed conversation storage for the Trading Copilot.

Uses asyncpg pool for all database operations against copilot_conversations
and copilot_messages tables.  Full message history is always retained in
PostgreSQL; truncate_to_fit() produces a shortened view for LLM context only.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import asyncpg

from quantgambit.copilot.models import (
    Conversation,
    ConversationSummary,
    Message,
    ToolCallRecord,
)

# Simple token estimation: 4 chars ≈ 1 token
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Estimate token count using the 4-chars-per-token heuristic."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _message_tokens(msg: Message) -> int:
    """Estimate total tokens for a message (content + serialised tool_calls)."""
    total = _estimate_tokens(msg.content)
    if msg.tool_calls:
        total += _estimate_tokens(json.dumps([_tool_call_to_dict(tc) for tc in msg.tool_calls]))
    return total


def _ts_to_dt(ts: float) -> datetime:
    """Convert a UNIX timestamp (float) to a timezone-aware datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _dt_to_ts(dt: datetime) -> float:
    """Convert a datetime to a UNIX timestamp float."""
    return dt.timestamp()


def _tool_calls_to_jsonb(tool_calls: list[ToolCallRecord] | None) -> str | None:
    """Serialise a list of ToolCallRecord to a JSON string for JSONB storage."""
    if not tool_calls:
        return None
    return json.dumps([_tool_call_to_dict(tc) for tc in tool_calls])


def _tool_call_to_dict(tc: ToolCallRecord) -> dict:
    return {
        "id": tc.id,
        "tool_name": tc.tool_name,
        "parameters": tc.parameters,
        "result": tc.result,
        "duration_ms": tc.duration_ms,
        "success": tc.success,
    }


def _jsonb_to_tool_calls(raw: str | list | None) -> list[ToolCallRecord] | None:
    """Deserialise JSONB (string or already-parsed list) into ToolCallRecord list."""
    if raw is None:
        return None
    items = json.loads(raw) if isinstance(raw, str) else raw
    return [
        ToolCallRecord(
            id=item["id"],
            tool_name=item["tool_name"],
            parameters=item.get("parameters", {}),
            result=item.get("result"),
            duration_ms=item.get("duration_ms", 0.0),
            success=item.get("success", True),
        )
        for item in items
    ]


def _row_to_message(row: asyncpg.Record) -> Message:
    """Convert a copilot_messages row into a Message dataclass."""
    return Message(
        role=row["role"],
        content=row["content"],
        tool_calls=_jsonb_to_tool_calls(row["tool_calls"]),
        tool_call_id=row["tool_call_id"],
        timestamp=_dt_to_ts(row["timestamp"]),
    )


def _row_to_conversation(row: asyncpg.Record) -> Conversation:
    """Convert a copilot_conversations row into a Conversation dataclass."""
    return Conversation(
        id=str(row["id"]),
        user_id=row["user_id"],
        created_at=_dt_to_ts(row["created_at"]),
        updated_at=_dt_to_ts(row["updated_at"]),
        title=row["title"],
    )


class ConversationManager:
    """PostgreSQL-backed conversation storage for the Trading Copilot."""

    def __init__(self, pg_pool: asyncpg.Pool, max_history: int = 50) -> None:
        self._pool = pg_pool
        self._max_history = max_history

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(self, user_id: str) -> Conversation:
        """Create a new conversation and return it."""
        conv_id = str(uuid.uuid4())
        row = await self._pool.fetchrow(
            """
            INSERT INTO copilot_conversations (id, user_id)
            VALUES ($1, $2)
            RETURNING id, user_id, title, created_at, updated_at
            """,
            uuid.UUID(conv_id),
            user_id,
        )
        return _row_to_conversation(row)

    async def get(self, conversation_id: str) -> Conversation | None:
        """Fetch a conversation by ID, or None if not found."""
        row = await self._pool.fetchrow(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM copilot_conversations
            WHERE id = $1
            """,
            uuid.UUID(conversation_id),
        )
        if row is None:
            return None
        return _row_to_conversation(row)

    async def append_message(self, conversation_id: str, message: Message) -> None:
        """Insert a message and bump the conversation's updated_at."""
        conv_uuid = uuid.UUID(conversation_id)
        tool_calls_json = _tool_calls_to_jsonb(message.tool_calls)
        ts = _ts_to_dt(message.timestamp)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO copilot_messages
                        (conversation_id, role, content, tool_calls, tool_call_id, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    conv_uuid,
                    message.role,
                    message.content,
                    tool_calls_json,
                    message.tool_call_id,
                    ts,
                )
                await conn.execute(
                    """
                    UPDATE copilot_conversations
                    SET updated_at = $2
                    WHERE id = $1
                    """,
                    conv_uuid,
                    ts,
                )

    async def get_messages(self, conversation_id: str) -> list[Message]:
        """Return all messages for a conversation ordered by timestamp."""
        rows = await self._pool.fetch(
            """
            SELECT role, content, tool_calls, tool_call_id, timestamp
            FROM copilot_messages
            WHERE conversation_id = $1
            ORDER BY timestamp ASC
            """,
            uuid.UUID(conversation_id),
        )
        return [_row_to_message(r) for r in rows]

    async def delete(self, conversation_id: str) -> None:
        """Delete a conversation and all its messages (FK cascade)."""
        await self._pool.execute(
            "DELETE FROM copilot_conversations WHERE id = $1",
            uuid.UUID(conversation_id),
        )

    # ------------------------------------------------------------------
    # Listing / search
    # ------------------------------------------------------------------

    async def list_conversations(
        self,
        user_id: str,
        search: str | None = None,
        start_date: float | None = None,
        end_date: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ConversationSummary], int]:
        """List conversations for a user with optional full-text search,
        date-range filtering, and pagination.

        Returns (summaries, total_count).
        """
        conditions = ["c.user_id = $1"]
        params: list = [user_id]
        idx = 2  # next parameter index

        if search:
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1 FROM copilot_messages m
                    WHERE m.conversation_id = c.id
                      AND to_tsvector('english', m.content) @@ plainto_tsquery('english', ${idx})
                )
                """
            )
            params.append(search)
            idx += 1

        if start_date is not None:
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1 FROM copilot_messages m
                    WHERE m.conversation_id = c.id
                      AND m.timestamp >= ${idx}
                )
                """
            )
            params.append(_ts_to_dt(start_date))
            idx += 1

        if end_date is not None:
            conditions.append(
                f"""
                EXISTS (
                    SELECT 1 FROM copilot_messages m
                    WHERE m.conversation_id = c.id
                      AND m.timestamp <= ${idx}
                )
                """
            )
            params.append(_ts_to_dt(end_date))
            idx += 1

        where = " AND ".join(conditions)

        # Total count
        count_row = await self._pool.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM copilot_conversations c WHERE {where}",
            *params,
        )
        total = count_row["cnt"]

        # Paginated results with message count
        offset = (page - 1) * page_size
        params_page = [*params, page_size, offset]
        rows = await self._pool.fetch(
            f"""
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM copilot_messages m WHERE m.conversation_id = c.id) AS message_count
            FROM copilot_conversations c
            WHERE {where}
            ORDER BY c.updated_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params_page,
        )

        summaries = [
            ConversationSummary(
                id=str(r["id"]),
                title=r["title"],
                created_at=_dt_to_ts(r["created_at"]),
                updated_at=_dt_to_ts(r["updated_at"]),
                message_count=r["message_count"],
            )
            for r in rows
        ]
        return summaries, total

    async def search_messages(
        self, user_id: str, query: str
    ) -> list[ConversationSummary]:
        """Full-text search across messages for a user's conversations.

        Returns ConversationSummary objects for conversations that contain
        messages matching the query.
        """
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM copilot_messages m2 WHERE m2.conversation_id = c.id) AS message_count
            FROM copilot_conversations c
            JOIN copilot_messages m ON m.conversation_id = c.id
            WHERE c.user_id = $1
              AND to_tsvector('english', m.content) @@ plainto_tsquery('english', $2)
            ORDER BY c.updated_at DESC
            """,
            user_id,
            query,
        )
        return [
            ConversationSummary(
                id=str(r["id"]),
                title=r["title"],
                created_at=_dt_to_ts(r["created_at"]),
                updated_at=_dt_to_ts(r["updated_at"]),
                message_count=r["message_count"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Context window management
    # ------------------------------------------------------------------

    async def truncate_to_fit(
        self, conversation_id: str, max_tokens: int
    ) -> list[Message]:
        """Return a truncated message list that fits within *max_tokens*.

        Strategy:
        1. Fetch all messages from PostgreSQL (full history is never deleted).
        2. Walk backwards from the most recent message, accumulating tokens.
        3. Once the budget is exhausted, summarise the remaining older messages
           into a single system-level summary message prepended to the list.

        The 4-chars ≈ 1-token heuristic is used for estimation.
        """
        all_messages = await self.get_messages(conversation_id)
        if not all_messages:
            return []

        total_tokens = sum(_message_tokens(m) for m in all_messages)
        if total_tokens <= max_tokens:
            return all_messages

        # Walk from newest to oldest, keeping messages that fit
        kept: list[Message] = []
        budget = max_tokens
        for msg in reversed(all_messages):
            cost = _message_tokens(msg)
            if budget - cost < 0:
                break
            kept.append(msg)
            budget -= cost

        kept.reverse()

        # Determine which messages were dropped
        kept_count = len(kept)
        dropped = all_messages[: len(all_messages) - kept_count]

        if dropped:
            # Build a brief summary of the older messages
            summary_parts: list[str] = []
            for msg in dropped:
                preview = msg.content[:120].replace("\n", " ")
                summary_parts.append(f"[{msg.role}] {preview}")
            summary_text = (
                "[Earlier conversation summary]\n" + "\n".join(summary_parts)
            )
            # Reserve tokens for the summary; if it itself is too large, truncate it
            summary_tokens = _estimate_tokens(summary_text)
            if summary_tokens > budget:
                # Hard-truncate the summary text to fit remaining budget
                max_chars = budget * _CHARS_PER_TOKEN
                summary_text = summary_text[:max_chars]

            summary_msg = Message(
                role="system",
                content=summary_text,
                timestamp=dropped[0].timestamp,
            )
            kept.insert(0, summary_msg)

        return kept
