"""Copilot API router.

Exposes the conversational copilot endpoints under ``/api/v1/copilot``.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 11.1, 12.4, 14.5
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from quantgambit.copilot.conversation import ConversationManager
from quantgambit.copilot.engine import AgentEngine
from quantgambit.copilot.models import (
    AgentEvent,
    TradeContext,
)
from quantgambit.copilot.prompt import SystemPromptBuilder
from quantgambit.copilot.settings_mutation import SettingsMutationManager
from quantgambit.copilot.tools.factory import create_tool_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TradeContextPayload(BaseModel):
    """Trade context sent from the frontend."""

    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    hold_time_seconds: float
    decision_trace_id: Optional[str] = None
    quantity: Optional[float] = None
    entry_time: Optional[float] = None
    exit_time: Optional[float] = None


class ChatRequest(BaseModel):
    """POST /chat request body."""

    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    trade_context: Optional[TradeContextPayload] = None
    page_path: Optional[str] = None


class ConversationSummaryResponse(BaseModel):
    id: str
    title: Optional[str]
    created_at: float
    updated_at: float
    message_count: int


class ListConversationsResponse(BaseModel):
    conversations: list[ConversationSummaryResponse]
    total: int


class MessageResponse(BaseModel):
    role: str
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None
    timestamp: float


class MessagesResponse(BaseModel):
    messages: list[MessageResponse]


class DeleteConversationResponse(BaseModel):
    success: bool


class SnapshotResponse(BaseModel):
    id: str
    user_id: str
    version: int
    settings: dict
    actor: str
    conversation_id: Optional[str] = None
    mutation_id: Optional[str] = None
    created_at: float


class ListSnapshotsResponse(BaseModel):
    snapshots: list[SnapshotResponse]


class RevertSnapshotResponse(BaseModel):
    snapshot: SnapshotResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_to_sse(event: AgentEvent) -> str:
    """Serialize an AgentEvent to an SSE ``data:`` line."""
    payload = dataclasses.asdict(event)
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _trade_context_from_payload(
    payload: TradeContextPayload | None,
) -> TradeContext | None:
    if payload is None:
        return None
    return TradeContext(
        trade_id=payload.trade_id,
        symbol=payload.symbol,
        side=payload.side,
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        pnl=payload.pnl,
        hold_time_seconds=payload.hold_time_seconds,
        decision_trace_id=payload.decision_trace_id,
        quantity=payload.quantity,
        entry_time=payload.entry_time,
        exit_time=payload.exit_time,
    )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_copilot_router(
    dashboard_pool_dep,
    redis_client_dep,
    timescale_pool_dep,
    auth_dep,
    model_provider_factory=None,
    doc_loader=None,
) -> APIRouter:
    """Create the copilot API router.

    Parameters
    ----------
    dashboard_pool_dep:
        FastAPI dependency yielding an asyncpg pool for the dashboard DB
        (conversations, settings snapshots, backtests).
    redis_client_dep:
        FastAPI dependency yielding an async Redis client.
    timescale_pool_dep:
        FastAPI dependency yielding an asyncpg pool for TimescaleDB.
    auth_dep:
        Authentication dependency (from ``build_auth_dependency``).
    model_provider_factory:
        Optional callable returning a ``ModelProvider``.  When *None* the
        factory from ``quantgambit.copilot.providers.factory`` is used.
    doc_loader:
        Optional ``DocLoader`` instance for page context in the system prompt.
    """
    from quantgambit.auth.jwt_auth import build_auth_dependency_with_claims, UserClaims

    router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])

    default_tenant = os.getenv("DEFAULT_TENANT_ID", "default")
    default_bot = os.getenv("DEFAULT_BOT_ID", "default")

    claims_auth_dep = build_auth_dependency_with_claims()

    # ------------------------------------------------------------------
    # POST /chat — SSE streaming chat
    # ------------------------------------------------------------------

    @router.post("/chat", dependencies=[Depends(auth_dep)])
    async def chat(
        request: ChatRequest,
        claims: UserClaims = Depends(claims_auth_dep),
        pg_pool=Depends(dashboard_pool_dep),
        redis_client=Depends(redis_client_dep),
        ts_pool=Depends(timescale_pool_dep),
    ):
        """Send a message and receive an SSE stream of agent events.

        **Validates: Requirements 9.1, 9.2, 9.3, 9.5, 9.6, 11.1**
        """
        # Validate non-empty message (pydantic min_length handles empty string,
        # but we also reject whitespace-only)
        if not request.message or not request.message.strip():
            raise HTTPException(status_code=422, detail="Message must not be empty")

        user_id = claims.user_id or "anonymous"

        conversation_manager = ConversationManager(pg_pool)

        # Resolve or create conversation
        conversation_id = request.conversation_id
        if conversation_id:
            conv = await conversation_manager.get(conversation_id)
            if conv is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Conversation {conversation_id} not found",
                )
        else:
            conv = await conversation_manager.create(user_id)
            conversation_id = conv.id

        # Build dependencies for this request
        mutation_manager = SettingsMutationManager(
            pg_pool=pg_pool,
            redis_client=redis_client,
            tenant_id=claims.tenant_id or default_tenant,
            bot_id=default_bot,
        )

        tool_registry = create_tool_registry(
            timescale_pool=ts_pool,
            redis_client=redis_client,
            dashboard_pool=pg_pool,
            mutation_manager=mutation_manager,
            tenant_id=claims.tenant_id or default_tenant,
            bot_id=default_bot,
            user_id=user_id,
            conversation_id=conversation_id,
        )

        prompt_builder = SystemPromptBuilder(tool_registry, doc_loader=doc_loader)

        # Create model provider
        if model_provider_factory is not None:
            model_provider = model_provider_factory()
        else:
            from quantgambit.copilot.providers.factory import create_model_provider

            model_provider = create_model_provider()

        engine = AgentEngine(
            model_provider=model_provider,
            tool_registry=tool_registry,
            conversation_manager=conversation_manager,
            system_prompt_builder=prompt_builder,
        )

        trade_context = _trade_context_from_payload(request.trade_context)

        async def _event_generator():
            # First event: send conversation_id so the client knows it
            yield f"data: {json.dumps({'type': 'conversation_id', 'conversation_id': conversation_id})}\n\n"
            async for event in engine.run(
                user_message=request.message,
                conversation_id=conversation_id,
                user_claims={"user_id": user_id, "tenant_id": claims.tenant_id},
                trade_context=trade_context,
                page_path=request.page_path,
            ):
                yield _event_to_sse(event)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


    # ------------------------------------------------------------------
    # GET /conversations — list conversations
    # ------------------------------------------------------------------

    @router.get(
        "/conversations",
        response_model=ListConversationsResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def list_conversations(
        search: Optional[str] = Query(None, description="Keyword search"),
        start_date: Optional[float] = Query(None, description="Start epoch timestamp"),
        end_date: Optional[float] = Query(None, description="End epoch timestamp"),
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Results per page"),
        claims: UserClaims = Depends(claims_auth_dep),
        pg_pool=Depends(dashboard_pool_dep),
    ):
        """List conversations for the authenticated user.

        **Validates: Requirements 12.4**
        """
        user_id = claims.user_id or "anonymous"
        cm = ConversationManager(pg_pool)
        summaries, total = await cm.list_conversations(
            user_id=user_id,
            search=search,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
        return ListConversationsResponse(
            conversations=[
                ConversationSummaryResponse(
                    id=s.id,
                    title=s.title,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    message_count=s.message_count,
                )
                for s in summaries
            ],
            total=total,
        )

    # ------------------------------------------------------------------
    # GET /conversations/{conversation_id}/messages
    # ------------------------------------------------------------------

    @router.get(
        "/conversations/{conversation_id}/messages",
        response_model=MessagesResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def get_conversation_messages(
        conversation_id: str,
        claims: UserClaims = Depends(claims_auth_dep),
        pg_pool=Depends(dashboard_pool_dep),
    ):
        """Get full message history for a conversation.

        **Validates: Requirements 9.1**
        """
        cm = ConversationManager(pg_pool)
        conv = await cm.get(conversation_id)
        if conv is None:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found",
            )
        messages = await cm.get_messages(conversation_id)
        return MessagesResponse(
            messages=[
                MessageResponse(
                    role=m.role,
                    content=m.content,
                    tool_calls=(
                        [
                            {
                                "id": tc.id,
                                "tool_name": tc.tool_name,
                                "parameters": tc.parameters,
                                "result": tc.result,
                                "duration_ms": tc.duration_ms,
                                "success": tc.success,
                            }
                            for tc in m.tool_calls
                        ]
                        if m.tool_calls
                        else None
                    ),
                    tool_call_id=m.tool_call_id,
                    timestamp=m.timestamp,
                )
                for m in messages
            ]
        )

    # ------------------------------------------------------------------
    # DELETE /conversations/{conversation_id}
    # ------------------------------------------------------------------

    @router.delete(
        "/conversations/{conversation_id}",
        response_model=DeleteConversationResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def delete_conversation(
        conversation_id: str,
        claims: UserClaims = Depends(claims_auth_dep),
        pg_pool=Depends(dashboard_pool_dep),
    ):
        """Delete a conversation and all associated messages.

        **Validates: Requirements 12.5**
        """
        cm = ConversationManager(pg_pool)
        conv = await cm.get(conversation_id)
        if conv is None:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found",
            )
        await cm.delete(conversation_id)
        return DeleteConversationResponse(success=True)

    # ------------------------------------------------------------------
    # GET /settings/snapshots
    # ------------------------------------------------------------------

    @router.get(
        "/settings/snapshots",
        response_model=ListSnapshotsResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def list_settings_snapshots(
        claims: UserClaims = Depends(claims_auth_dep),
        pg_pool=Depends(dashboard_pool_dep),
        redis_client=Depends(redis_client_dep),
    ):
        """List settings snapshots for the authenticated user.

        **Validates: Requirements 14.5**
        """
        user_id = claims.user_id or "anonymous"
        sm = SettingsMutationManager(pg_pool=pg_pool, redis_client=redis_client, tenant_id=claims.tenant_id or default_tenant, bot_id=default_bot)
        snapshots = await sm.list_snapshots(user_id)
        return ListSnapshotsResponse(
            snapshots=[
                SnapshotResponse(
                    id=s.id,
                    user_id=s.user_id,
                    version=s.version,
                    settings=s.settings,
                    actor=s.actor,
                    conversation_id=s.conversation_id,
                    mutation_id=s.mutation_id,
                    created_at=s.created_at,
                )
                for s in snapshots
            ]
        )

    # ------------------------------------------------------------------
    # POST /settings/revert/{snapshot_id}
    # ------------------------------------------------------------------

    @router.post(
        "/settings/revert/{snapshot_id}",
        response_model=RevertSnapshotResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def revert_settings(
        snapshot_id: str,
        claims: UserClaims = Depends(claims_auth_dep),
        pg_pool=Depends(dashboard_pool_dep),
        redis_client=Depends(redis_client_dep),
    ):
        """Revert settings to a specific snapshot version.

        **Validates: Requirements 14.5**
        """
        user_id = claims.user_id or "anonymous"
        sm = SettingsMutationManager(pg_pool=pg_pool, redis_client=redis_client, tenant_id=claims.tenant_id or default_tenant, bot_id=default_bot)
        try:
            snapshot = await sm.revert_to_snapshot(snapshot_id, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return RevertSnapshotResponse(
            snapshot=SnapshotResponse(
                id=snapshot.id,
                user_id=snapshot.user_id,
                version=snapshot.version,
                settings=snapshot.settings,
                actor=snapshot.actor,
                conversation_id=snapshot.conversation_id,
                mutation_id=snapshot.mutation_id,
                created_at=snapshot.created_at,
            )
        )

    return router
