"""Unit tests for CopilotRouter (``quantgambit/api/copilot_endpoints.py``).

Tests use ``httpx.AsyncClient`` with a minimal FastAPI app that includes the
copilot router.  All external dependencies (database pools, Redis, LLM
provider) are mocked.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 11.1, 12.4, 14.5
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

import httpx

from quantgambit.copilot.models import (
    Conversation,
    ConversationSummary,
    DoneEvent,
    LLMChunk,
    Message,
    SettingsSnapshot,
    TextDelta,
    TradeContext,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Ensure auth is disabled for tests
os.environ.setdefault("AUTH_MODE", "none")


def _make_app(
    conversation_manager=None,
    settings_mutation_manager=None,
    model_chunks=None,
):
    """Build a minimal FastAPI app with the copilot router for testing."""
    from quantgambit.api.copilot_endpoints import create_copilot_router
    from quantgambit.auth.jwt_auth import build_auth_dependency

    app = FastAPI()

    # Mock dependencies as simple callables that return mocks
    mock_pg_pool = MagicMock()
    mock_redis = AsyncMock()
    mock_ts_pool = MagicMock()

    async def pg_dep():
        return mock_pg_pool

    async def redis_dep():
        yield mock_redis

    async def ts_dep():
        return mock_ts_pool

    auth_dep = build_auth_dependency()

    # Patch ConversationManager and SettingsMutationManager at module level
    _cm = conversation_manager or _default_conversation_manager()
    _sm = settings_mutation_manager or _default_settings_mutation_manager()

    # Build a model provider factory that returns a mock
    chunks = model_chunks or [
        LLMChunk(type="text_delta", content="Hello!"),
        LLMChunk(type="done"),
    ]

    class _MockProvider:
        async def chat_completion_stream(self, messages, tools=None, temperature=0.1):
            for c in chunks:
                yield c

    def _provider_factory():
        return _MockProvider()

    router = create_copilot_router(
        dashboard_pool_dep=pg_dep,
        redis_client_dep=redis_dep,
        timescale_pool_dep=ts_dep,
        auth_dep=auth_dep,
        model_provider_factory=_provider_factory,
    )
    app.include_router(router)

    # Store mocks on app for patching in tests
    app.state._test_cm = _cm
    app.state._test_sm = _sm

    return app, _cm, _sm


def _default_conversation_manager():
    """Create a mock ConversationManager with sensible defaults."""
    cm = AsyncMock()
    conv = Conversation(
        id=str(uuid.uuid4()),
        user_id="anonymous",
        created_at=1700000000.0,
        updated_at=1700000000.0,
        title=None,
    )
    cm.create.return_value = conv
    cm.get.return_value = conv
    cm.get_messages.return_value = []
    cm.list_conversations.return_value = ([], 0)
    cm.delete.return_value = None
    cm.append_message.return_value = None
    cm.truncate_to_fit.return_value = []
    return cm


def _default_settings_mutation_manager():
    """Create a mock SettingsMutationManager with sensible defaults."""
    sm = AsyncMock()
    sm.list_snapshots.return_value = []
    sm.revert_to_snapshot.return_value = SettingsSnapshot(
        id=str(uuid.uuid4()),
        user_id="anonymous",
        version=1,
        settings={"risk": {"max_exposure": 0.5}},
        actor="user",
        created_at=1700000000.0,
    )
    return sm


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of JSON event dicts."""
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: "):]
            events.append(json.loads(payload))
    return events


# ---------------------------------------------------------------------------
# Tests: POST /chat
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    """Tests for POST /api/v1/copilot/chat."""

    @pytest.mark.asyncio
    async def test_chat_creates_new_conversation_and_streams(self):
        """When no conversation_id is provided, a new conversation is created
        and the response is an SSE stream."""
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ), patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=_default_settings_mutation_manager(),
        ), patch(
            "quantgambit.api.copilot_endpoints.create_tool_registry",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={"message": "Hello"},
                )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse_events(resp.text)
        # First event should be conversation_id
        assert events[0]["type"] == "conversation_id"
        assert "conversation_id" in events[0]

    @pytest.mark.asyncio
    async def test_chat_with_existing_conversation(self):
        """When a valid conversation_id is provided, it is reused."""
        conv_id = str(uuid.uuid4())
        cm = _default_conversation_manager()
        conv = Conversation(
            id=conv_id,
            user_id="anonymous",
            created_at=1700000000.0,
            updated_at=1700000000.0,
        )
        cm.get.return_value = conv

        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ), patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=_default_settings_mutation_manager(),
        ), patch(
            "quantgambit.api.copilot_endpoints.create_tool_registry",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={"message": "Hi", "conversation_id": conv_id},
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert events[0]["conversation_id"] == conv_id

    @pytest.mark.asyncio
    async def test_chat_rejects_empty_message(self):
        """Empty or whitespace-only messages return 422."""
        app, _, _ = _make_app()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/copilot/chat",
                json={"message": ""},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_rejects_whitespace_only_message(self):
        """Whitespace-only messages return 422."""
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={"message": "   "},
                )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_rejects_invalid_conversation_id(self):
        """Non-existent conversation_id returns 404."""
        cm = _default_conversation_manager()
        cm.get.return_value = None  # conversation not found

        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={
                        "message": "Hello",
                        "conversation_id": "nonexistent-id",
                    },
                )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_chat_with_trade_context(self):
        """Trade context is accepted and forwarded to the engine."""
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        trade_ctx = {
            "trade_id": "t-123",
            "symbol": "BTC-USDT",
            "side": "buy",
            "entry_price": 50000.0,
            "exit_price": 51000.0,
            "pnl": 100.0,
            "hold_time_seconds": 3600.0,
        }

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ), patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=_default_settings_mutation_manager(),
        ), patch(
            "quantgambit.api.copilot_endpoints.create_tool_registry",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={
                        "message": "Tell me about this trade",
                        "trade_context": trade_ctx,
                    },
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert any(e.get("type") == "conversation_id" for e in events)

    @pytest.mark.asyncio
    async def test_chat_with_page_path(self):
        """When page_path is provided, it is accepted and the request succeeds.

        Validates: Requirements 4.3
        """
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ), patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=_default_settings_mutation_manager(),
        ), patch(
            "quantgambit.api.copilot_endpoints.create_tool_registry",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={
                        "message": "What can I do on this page?",
                        "page_path": "/live",
                    },
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert events[0]["type"] == "conversation_id"

    @pytest.mark.asyncio
    async def test_chat_without_page_path(self):
        """When page_path is omitted, the request still succeeds (backward compatible).

        Validates: Requirements 4.3
        """
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ), patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=_default_settings_mutation_manager(),
        ), patch(
            "quantgambit.api.copilot_endpoints.create_tool_registry",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={"message": "Hello there"},
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert events[0]["type"] == "conversation_id"

    @pytest.mark.asyncio
    async def test_chat_with_page_path_null(self):
        """When page_path is explicitly null, the request still succeeds.

        Validates: Requirements 4.3
        """
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ), patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=_default_settings_mutation_manager(),
        ), patch(
            "quantgambit.api.copilot_endpoints.create_tool_registry",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/chat",
                    json={
                        "message": "Hello",
                        "page_path": None,
                    },
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert events[0]["type"] == "conversation_id"



# ---------------------------------------------------------------------------
# Tests: GET /conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    """Tests for GET /api/v1/copilot/conversations."""

    @pytest.mark.asyncio
    async def test_list_conversations_empty(self):
        cm = _default_conversation_manager()
        cm.list_conversations.return_value = ([], 0)
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/copilot/conversations")

        assert resp.status_code == 200
        body = resp.json()
        assert body["conversations"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_conversations_with_results(self):
        cm = _default_conversation_manager()
        summary = ConversationSummary(
            id="conv-1",
            title="Test conversation",
            created_at=1700000000.0,
            updated_at=1700001000.0,
            message_count=5,
        )
        cm.list_conversations.return_value = ([summary], 1)
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/copilot/conversations",
                    params={"search": "test", "page": 1, "page_size": 10},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["conversations"]) == 1
        assert body["conversations"][0]["id"] == "conv-1"
        assert body["conversations"][0]["title"] == "Test conversation"
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_list_conversations_passes_params(self):
        """Verify search, date range, and pagination params are forwarded."""
        cm = _default_conversation_manager()
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/copilot/conversations",
                    params={
                        "search": "trade",
                        "start_date": 1700000000.0,
                        "end_date": 1700100000.0,
                        "page": 2,
                        "page_size": 5,
                    },
                )

        assert resp.status_code == 200
        cm.list_conversations.assert_called_once()
        call_kwargs = cm.list_conversations.call_args
        assert call_kwargs.kwargs.get("search") == "trade" or call_kwargs[1].get("search") == "trade"


# ---------------------------------------------------------------------------
# Tests: GET /conversations/{conversation_id}/messages
# ---------------------------------------------------------------------------


class TestGetConversationMessages:
    """Tests for GET /api/v1/copilot/conversations/{id}/messages."""

    @pytest.mark.asyncio
    async def test_get_messages_success(self):
        cm = _default_conversation_manager()
        cm.get_messages.return_value = [
            Message(role="user", content="Hello", timestamp=1700000000.0),
            Message(role="assistant", content="Hi there!", timestamp=1700000001.0),
        ]
        conv_id = str(uuid.uuid4())
        cm.get.return_value = Conversation(
            id=conv_id,
            user_id="anonymous",
            created_at=1700000000.0,
            updated_at=1700000001.0,
        )
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    f"/api/v1/copilot/conversations/{conv_id}/messages"
                )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][1]["content"] == "Hi there!"

    @pytest.mark.asyncio
    async def test_get_messages_not_found(self):
        cm = _default_conversation_manager()
        cm.get.return_value = None
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/copilot/conversations/nonexistent/messages"
                )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: DELETE /conversations/{conversation_id}
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    """Tests for DELETE /api/v1/copilot/conversations/{id}."""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        cm = _default_conversation_manager()
        conv_id = str(uuid.uuid4())
        cm.get.return_value = Conversation(
            id=conv_id,
            user_id="anonymous",
            created_at=1700000000.0,
            updated_at=1700000000.0,
        )
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.delete(
                    f"/api/v1/copilot/conversations/{conv_id}"
                )

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        cm.delete.assert_called_once_with(conv_id)

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        cm = _default_conversation_manager()
        cm.get.return_value = None
        app, _, _ = _make_app(conversation_manager=cm)

        with patch(
            "quantgambit.api.copilot_endpoints.ConversationManager",
            return_value=cm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.delete(
                    "/api/v1/copilot/conversations/nonexistent"
                )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /settings/snapshots
# ---------------------------------------------------------------------------


class TestListSettingsSnapshots:
    """Tests for GET /api/v1/copilot/settings/snapshots."""

    @pytest.mark.asyncio
    async def test_list_snapshots_empty(self):
        sm = _default_settings_mutation_manager()
        sm.list_snapshots.return_value = []
        app, _, _ = _make_app(settings_mutation_manager=sm)

        with patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=sm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/copilot/settings/snapshots")

        assert resp.status_code == 200
        assert resp.json()["snapshots"] == []

    @pytest.mark.asyncio
    async def test_list_snapshots_with_results(self):
        sm = _default_settings_mutation_manager()
        snap = SettingsSnapshot(
            id="snap-1",
            user_id="anonymous",
            version=1,
            settings={"risk": {"max_exposure": 0.5}},
            actor="copilot",
            conversation_id="conv-1",
            created_at=1700000000.0,
        )
        sm.list_snapshots.return_value = [snap]
        app, _, _ = _make_app(settings_mutation_manager=sm)

        with patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=sm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/copilot/settings/snapshots")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["snapshots"]) == 1
        assert body["snapshots"][0]["id"] == "snap-1"
        assert body["snapshots"][0]["actor"] == "copilot"


# ---------------------------------------------------------------------------
# Tests: POST /settings/revert/{snapshot_id}
# ---------------------------------------------------------------------------


class TestRevertSettings:
    """Tests for POST /api/v1/copilot/settings/revert/{snapshot_id}."""

    @pytest.mark.asyncio
    async def test_revert_success(self):
        sm = _default_settings_mutation_manager()
        app, _, _ = _make_app(settings_mutation_manager=sm)

        with patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=sm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/settings/revert/snap-1"
                )

        assert resp.status_code == 200
        body = resp.json()
        assert "snapshot" in body
        assert body["snapshot"]["version"] == 1

    @pytest.mark.asyncio
    async def test_revert_not_found(self):
        sm = _default_settings_mutation_manager()
        sm.revert_to_snapshot.side_effect = ValueError("Snapshot not found")
        app, _, _ = _make_app(settings_mutation_manager=sm)

        with patch(
            "quantgambit.api.copilot_endpoints.SettingsMutationManager",
            return_value=sm,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/copilot/settings/revert/nonexistent"
                )

        assert resp.status_code == 404
