"""Unit tests for ConversationManager.

Uses a mock asyncpg pool since we can't connect to a real database in tests.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantgambit.copilot.conversation import (
    ConversationManager,
    _CHARS_PER_TOKEN,
    _dt_to_ts,
    _estimate_tokens,
    _jsonb_to_tool_calls,
    _message_tokens,
    _tool_calls_to_jsonb,
    _ts_to_dt,
)
from quantgambit.copilot.models import (
    Conversation,
    ConversationSummary,
    Message,
    ToolCallRecord,
)


# ---------------------------------------------------------------------------
# Helpers — fake asyncpg records and pool
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Dict subclass that supports attribute-style access like asyncpg.Record."""

    def __getitem__(self, key):
        return super().__getitem__(key)


def _make_conv_row(
    conv_id: str | None = None,
    user_id: str = "user-1",
    title: str | None = None,
) -> FakeRecord:
    now = datetime.now(tz=timezone.utc)
    return FakeRecord(
        id=uuid.UUID(conv_id) if conv_id else uuid.uuid4(),
        user_id=user_id,
        title=title,
        created_at=now,
        updated_at=now,
    )


def _make_msg_row(
    role: str = "user",
    content: str = "hello",
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
    ts: datetime | None = None,
) -> FakeRecord:
    return FakeRecord(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        timestamp=ts or datetime.now(tz=timezone.utc),
    )


def _make_summary_row(
    conv_id: str | None = None,
    title: str | None = None,
    message_count: int = 3,
) -> FakeRecord:
    now = datetime.now(tz=timezone.utc)
    return FakeRecord(
        id=uuid.UUID(conv_id) if conv_id else uuid.uuid4(),
        title=title,
        created_at=now,
        updated_at=now,
        message_count=message_count,
    )


class FakeConnection:
    """Fake async context manager mimicking an asyncpg connection."""

    def __init__(self):
        self.execute = AsyncMock()
        self._transaction = MagicMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def transaction(self):
        return self._transaction


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_pool() -> MagicMock:
    """Create a mock asyncpg pool with common methods."""
    pool = MagicMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()

    # For acquire() context manager
    conn = FakeConnection()
    conn._transaction = FakeTransaction()
    pool.acquire = MagicMock(return_value=conn)

    return pool


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_estimate_tokens(self):
        assert _estimate_tokens("") == 1  # min 1
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 8) == 2
        assert _estimate_tokens("a" * 100) == 25

    def test_ts_to_dt_and_back(self):
        ts = 1700000000.0
        dt = _ts_to_dt(ts)
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None
        assert abs(_dt_to_ts(dt) - ts) < 0.001

    def test_tool_calls_to_jsonb_none(self):
        assert _tool_calls_to_jsonb(None) is None
        assert _tool_calls_to_jsonb([]) is None

    def test_tool_calls_round_trip(self):
        tc = ToolCallRecord(
            id="tc-1",
            tool_name="query_trades",
            parameters={"symbol": "BTC"},
            result={"trades": []},
            duration_ms=42.5,
            success=True,
        )
        jsonb = _tool_calls_to_jsonb([tc])
        assert jsonb is not None
        restored = _jsonb_to_tool_calls(jsonb)
        assert len(restored) == 1
        assert restored[0].id == "tc-1"
        assert restored[0].tool_name == "query_trades"
        assert restored[0].parameters == {"symbol": "BTC"}
        assert restored[0].result == {"trades": []}
        assert restored[0].duration_ms == 42.5
        assert restored[0].success is True

    def test_jsonb_to_tool_calls_none(self):
        assert _jsonb_to_tool_calls(None) is None

    def test_jsonb_to_tool_calls_from_list(self):
        """asyncpg may return already-parsed list for JSONB columns."""
        data = [{"id": "x", "tool_name": "t", "parameters": {}}]
        result = _jsonb_to_tool_calls(data)
        assert len(result) == 1
        assert result[0].id == "x"

    def test_message_tokens_content_only(self):
        msg = Message(role="user", content="a" * 100)
        assert _message_tokens(msg) == 25

    def test_message_tokens_with_tool_calls(self):
        tc = ToolCallRecord(id="1", tool_name="t", parameters={"k": "v"})
        msg = Message(role="assistant", content="hi", tool_calls=[tc])
        tokens = _message_tokens(msg)
        assert tokens > _estimate_tokens("hi")


# ---------------------------------------------------------------------------
# ConversationManager.create
# ---------------------------------------------------------------------------

class TestCreate:
    @pytest.mark.asyncio
    async def test_create_returns_conversation(self):
        pool = _make_pool()
        row = _make_conv_row(user_id="user-42")
        pool.fetchrow.return_value = row

        mgr = ConversationManager(pool)
        conv = await mgr.create("user-42")

        assert isinstance(conv, Conversation)
        assert conv.user_id == "user-42"
        assert conv.id == str(row["id"])
        pool.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_passes_uuid_and_user_id(self):
        pool = _make_pool()
        pool.fetchrow.return_value = _make_conv_row()

        mgr = ConversationManager(pool)
        await mgr.create("u1")

        args = pool.fetchrow.call_args
        # First positional arg is the SQL, second is the UUID, third is user_id
        assert args[0][2] == "u1"
        assert isinstance(args[0][1], uuid.UUID)


# ---------------------------------------------------------------------------
# ConversationManager.get
# ---------------------------------------------------------------------------

class TestGet:
    @pytest.mark.asyncio
    async def test_get_existing(self):
        pool = _make_pool()
        cid = str(uuid.uuid4())
        pool.fetchrow.return_value = _make_conv_row(conv_id=cid)

        mgr = ConversationManager(pool)
        conv = await mgr.get(cid)

        assert conv is not None
        assert conv.id == cid

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        pool = _make_pool()
        pool.fetchrow.return_value = None

        mgr = ConversationManager(pool)
        conv = await mgr.get(str(uuid.uuid4()))

        assert conv is None


# ---------------------------------------------------------------------------
# ConversationManager.append_message
# ---------------------------------------------------------------------------

class TestAppendMessage:
    @pytest.mark.asyncio
    async def test_append_inserts_and_updates(self):
        pool = _make_pool()
        conn = pool.acquire.return_value

        mgr = ConversationManager(pool)
        msg = Message(role="user", content="hello world", timestamp=1700000000.0)
        cid = str(uuid.uuid4())

        await mgr.append_message(cid, msg)

        # Should have called execute twice: INSERT + UPDATE
        assert conn.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_append_with_tool_calls(self):
        pool = _make_pool()
        conn = pool.acquire.return_value

        tc = ToolCallRecord(id="tc-1", tool_name="query_trades", parameters={"symbol": "BTC"})
        msg = Message(role="assistant", content="result", tool_calls=[tc], timestamp=1700000000.0)

        mgr = ConversationManager(pool)
        await mgr.append_message(str(uuid.uuid4()), msg)

        # Verify the INSERT call includes serialised tool_calls
        insert_call = conn.execute.call_args_list[0]
        tool_calls_arg = insert_call[0][4]  # 5th positional arg (index 4) is tool_calls
        assert tool_calls_arg is not None
        parsed = json.loads(tool_calls_arg)
        assert parsed[0]["tool_name"] == "query_trades"


# ---------------------------------------------------------------------------
# ConversationManager.get_messages
# ---------------------------------------------------------------------------

class TestGetMessages:
    @pytest.mark.asyncio
    async def test_get_messages_returns_ordered_list(self):
        pool = _make_pool()
        ts1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
        pool.fetch.return_value = [
            _make_msg_row(role="user", content="first", ts=ts1),
            _make_msg_row(role="assistant", content="second", ts=ts2),
        ]

        mgr = ConversationManager(pool)
        msgs = await mgr.get_messages(str(uuid.uuid4()))

        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "first"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "second"

    @pytest.mark.asyncio
    async def test_get_messages_empty(self):
        pool = _make_pool()
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        msgs = await mgr.get_messages(str(uuid.uuid4()))

        assert msgs == []

    @pytest.mark.asyncio
    async def test_get_messages_with_tool_calls(self):
        pool = _make_pool()
        tc_json = json.dumps([{"id": "tc-1", "tool_name": "t", "parameters": {}}])
        pool.fetch.return_value = [
            _make_msg_row(role="assistant", content="ok", tool_calls=tc_json),
        ]

        mgr = ConversationManager(pool)
        msgs = await mgr.get_messages(str(uuid.uuid4()))

        assert msgs[0].tool_calls is not None
        assert msgs[0].tool_calls[0].tool_name == "t"


# ---------------------------------------------------------------------------
# ConversationManager.delete
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_execute(self):
        pool = _make_pool()
        mgr = ConversationManager(pool)
        cid = str(uuid.uuid4())

        await mgr.delete(cid)

        pool.execute.assert_awaited_once()
        args = pool.execute.call_args[0]
        assert "DELETE" in args[0]
        assert args[1] == uuid.UUID(cid)


# ---------------------------------------------------------------------------
# ConversationManager.list_conversations
# ---------------------------------------------------------------------------

class TestListConversations:
    @pytest.mark.asyncio
    async def test_basic_listing(self):
        pool = _make_pool()
        pool.fetchrow.return_value = FakeRecord(cnt=2)
        pool.fetch.return_value = [
            _make_summary_row(title="Chat 1", message_count=5),
            _make_summary_row(title="Chat 2", message_count=3),
        ]

        mgr = ConversationManager(pool)
        summaries, total = await mgr.list_conversations("user-1")

        assert total == 2
        assert len(summaries) == 2
        assert summaries[0].title == "Chat 1"
        assert summaries[0].message_count == 5

    @pytest.mark.asyncio
    async def test_with_search(self):
        pool = _make_pool()
        pool.fetchrow.return_value = FakeRecord(cnt=1)
        pool.fetch.return_value = [_make_summary_row(title="Found")]

        mgr = ConversationManager(pool)
        summaries, total = await mgr.list_conversations("user-1", search="keyword")

        assert total == 1
        # Verify the SQL includes full-text search
        count_sql = pool.fetchrow.call_args[0][0]
        assert "to_tsvector" in count_sql
        assert "plainto_tsquery" in count_sql

    @pytest.mark.asyncio
    async def test_with_date_range(self):
        pool = _make_pool()
        pool.fetchrow.return_value = FakeRecord(cnt=0)
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        summaries, total = await mgr.list_conversations(
            "user-1", start_date=1700000000.0, end_date=1700100000.0
        )

        assert total == 0
        assert summaries == []
        # Verify date conditions are in the SQL
        count_sql = pool.fetchrow.call_args[0][0]
        assert "m.timestamp >=" in count_sql
        assert "m.timestamp <=" in count_sql

    @pytest.mark.asyncio
    async def test_pagination_params(self):
        pool = _make_pool()
        pool.fetchrow.return_value = FakeRecord(cnt=50)
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        await mgr.list_conversations("user-1", page=3, page_size=10)

        # Verify LIMIT and OFFSET are passed
        fetch_args = pool.fetch.call_args[0]
        # Last two params should be page_size=10 and offset=20
        assert fetch_args[-2] == 10  # page_size
        assert fetch_args[-1] == 20  # offset = (3-1)*10

    @pytest.mark.asyncio
    async def test_empty_result(self):
        pool = _make_pool()
        pool.fetchrow.return_value = FakeRecord(cnt=0)
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        summaries, total = await mgr.list_conversations("user-1")

        assert total == 0
        assert summaries == []


# ---------------------------------------------------------------------------
# ConversationManager.search_messages
# ---------------------------------------------------------------------------

class TestSearchMessages:
    @pytest.mark.asyncio
    async def test_search_returns_summaries(self):
        pool = _make_pool()
        pool.fetch.return_value = [
            _make_summary_row(title="Match 1", message_count=10),
        ]

        mgr = ConversationManager(pool)
        results = await mgr.search_messages("user-1", "trading")

        assert len(results) == 1
        assert results[0].title == "Match 1"
        assert results[0].message_count == 10

    @pytest.mark.asyncio
    async def test_search_uses_full_text(self):
        pool = _make_pool()
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        await mgr.search_messages("user-1", "performance")

        sql = pool.fetch.call_args[0][0]
        assert "to_tsvector" in sql
        assert "plainto_tsquery" in sql

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        pool = _make_pool()
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        results = await mgr.search_messages("user-1", "nonexistent")

        assert results == []


# ---------------------------------------------------------------------------
# ConversationManager.truncate_to_fit
# ---------------------------------------------------------------------------

class TestTruncateToFit:
    @pytest.mark.asyncio
    async def test_no_messages(self):
        pool = _make_pool()
        pool.fetch.return_value = []

        mgr = ConversationManager(pool)
        result = await mgr.truncate_to_fit(str(uuid.uuid4()), max_tokens=1000)

        assert result == []

    @pytest.mark.asyncio
    async def test_fits_within_budget(self):
        """When all messages fit, return them unchanged."""
        pool = _make_pool()
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        pool.fetch.return_value = [
            _make_msg_row(role="user", content="short", ts=ts),
            _make_msg_row(role="assistant", content="reply", ts=ts),
        ]

        mgr = ConversationManager(pool)
        result = await mgr.truncate_to_fit(str(uuid.uuid4()), max_tokens=10000)

        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_truncates_old_messages(self):
        """When messages exceed budget, older ones are summarised."""
        pool = _make_pool()
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # Create messages where total tokens exceed budget
        # Each message with 400 chars = 100 tokens
        pool.fetch.return_value = [
            _make_msg_row(role="user", content="a" * 400, ts=ts),
            _make_msg_row(role="assistant", content="b" * 400, ts=ts),
            _make_msg_row(role="user", content="c" * 400, ts=ts),
            _make_msg_row(role="assistant", content="d" * 400, ts=ts),
        ]

        mgr = ConversationManager(pool)
        # Budget of 250 tokens — only ~2 messages fit (200 tokens) + summary
        result = await mgr.truncate_to_fit(str(uuid.uuid4()), max_tokens=250)

        # Should have a summary message + the most recent messages that fit
        assert len(result) >= 2
        # First message should be the summary
        assert result[0].role == "system"
        assert "[Earlier conversation summary]" in result[0].content
        # Last messages should be the most recent ones
        assert result[-1].content == "d" * 400

    @pytest.mark.asyncio
    async def test_preserves_most_recent(self):
        """The most recent messages should always be preserved."""
        pool = _make_pool()
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        pool.fetch.return_value = [
            _make_msg_row(role="user", content="old " * 100, ts=ts),
            _make_msg_row(role="assistant", content="older " * 100, ts=ts),
            _make_msg_row(role="user", content="newest", ts=ts),
        ]

        mgr = ConversationManager(pool)
        # Very small budget — only the newest message should fit
        result = await mgr.truncate_to_fit(str(uuid.uuid4()), max_tokens=10)

        # Should have at least the newest message
        non_summary = [m for m in result if m.role != "system"]
        assert len(non_summary) >= 1
        assert non_summary[-1].content == "newest"

    @pytest.mark.asyncio
    async def test_summary_truncated_if_too_large(self):
        """If the summary itself exceeds remaining budget, it gets truncated."""
        pool = _make_pool()
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # Many old messages with long content
        rows = [
            _make_msg_row(role="user", content=f"message {i} " * 50, ts=ts)
            for i in range(20)
        ]
        # Add one short recent message
        rows.append(_make_msg_row(role="user", content="latest", ts=ts))
        pool.fetch.return_value = rows

        mgr = ConversationManager(pool)
        result = await mgr.truncate_to_fit(str(uuid.uuid4()), max_tokens=15)

        # Should still produce a result without error
        assert len(result) >= 1
        # The summary should exist and be truncated
        if result[0].role == "system":
            # Summary should not be excessively long
            summary_tokens = _estimate_tokens(result[0].content)
            assert summary_tokens <= 15
