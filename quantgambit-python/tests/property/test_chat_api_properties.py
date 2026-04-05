"""
Property-based tests for Chat API endpoints.

Feature: trading-copilot-agent
Tests correctness properties for:
- Property 16: API input validation
- Property 19: User message persistence

**Validates: Requirements 9.3, 9.6, 1.2**
"""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

import httpx
from fastapi import FastAPI

from quantgambit.copilot.models import (
    Conversation,
    DoneEvent,
    LLMChunk,
    Message,
    TextDelta,
)

# Ensure auth is disabled for tests
os.environ.setdefault("AUTH_MODE", "none")


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Whitespace-only strings: spaces, tabs, newlines, etc.
whitespace_only_strings = st.text(
    alphabet=st.sampled_from([" ", "\t", "\n", "\r", "\x0b", "\x0c"]),
    min_size=1,
    max_size=50,
)

# Non-existent conversation IDs — valid UUID4 strings that won't match any mock
nonexistent_conversation_ids = st.uuids(version=4).map(str)

# Valid non-empty, non-whitespace user messages
valid_user_messages = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip())


# =============================================================================
# Helpers
# =============================================================================


def _make_test_app(conversation_manager=None, capture_appended_messages=None):
    """Build a minimal FastAPI app with the copilot router for property testing.

    Parameters
    ----------
    conversation_manager:
        Optional mock ConversationManager. A default is created if None.
    capture_appended_messages:
        Optional list. If provided, append_message calls will append the
        Message to this list for later inspection.
    """
    from quantgambit.api.copilot_endpoints import create_copilot_router
    from quantgambit.auth.jwt_auth import build_auth_dependency

    app = FastAPI()

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

    cm = conversation_manager or _default_cm()

    if capture_appended_messages is not None:
        original_append = cm.append_message

        async def _capturing_append(conv_id, message):
            capture_appended_messages.append(message)

        cm.append_message = AsyncMock(side_effect=_capturing_append)

    chunks = [
        LLMChunk(type="text_delta", content="OK"),
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

    return app, cm


def _default_cm():
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


def _default_sm():
    """Create a mock SettingsMutationManager."""
    sm = AsyncMock()
    sm.list_snapshots.return_value = []
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


# =============================================================================
# Property 16: API input validation
# Feature: trading-copilot-agent, Property 16: API input validation
#
# For any request with an empty or whitespace-only message, the Chat API
# SHALL return a 422 status code. For any request with a non-existent
# conversation ID, the Chat API SHALL return a 404 status code.
#
# **Validates: Requirements 9.3, 9.6**
# =============================================================================


@settings(max_examples=100)
@given(ws=whitespace_only_strings)
@pytest.mark.asyncio
async def test_property_16_whitespace_only_message_returns_422(ws: str):
    """
    Property 16: API input validation — whitespace-only messages.

    For any whitespace-only string submitted as the message field,
    the Chat API SHALL return a 422 status code.

    **Validates: Requirements 9.3, 9.6**
    """
    cm = _default_cm()
    app, _ = _make_test_app(conversation_manager=cm)

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
                json={"message": ws},
            )

    assert resp.status_code == 422, (
        f"Expected 422 for whitespace-only message {ws!r}, got {resp.status_code}"
    )


@settings(max_examples=100)
@given(conv_id=nonexistent_conversation_ids)
@pytest.mark.asyncio
async def test_property_16_nonexistent_conversation_id_returns_404(conv_id: str):
    """
    Property 16: API input validation — non-existent conversation ID.

    For any request with a conversation_id that does not reference an
    existing conversation, the Chat API SHALL return a 404 status code.

    **Validates: Requirements 9.3, 9.6**
    """
    cm = _default_cm()
    cm.get.return_value = None  # conversation not found

    app, _ = _make_test_app(conversation_manager=cm)

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
                json={"message": "Hello", "conversation_id": conv_id},
            )

    assert resp.status_code == 404, (
        f"Expected 404 for non-existent conversation_id {conv_id!r}, got {resp.status_code}"
    )


# =============================================================================
# Property 19: User message persistence
# Feature: trading-copilot-agent, Property 19: User message persistence
#
# For any user message submitted through the Copilot, after submission
# the conversation message list SHALL contain that message with role
# "user" and the original content.
#
# **Validates: Requirements 1.2**
# =============================================================================


@settings(max_examples=100)
@given(msg=valid_user_messages)
@pytest.mark.asyncio
async def test_property_19_user_message_persisted_with_correct_role_and_content(
    msg: str,
):
    """
    Property 19: User message persistence.

    For any valid user message submitted through the Chat API, the
    ConversationManager.append_message SHALL be called with a Message
    having role="user" and content equal to the original message.

    **Validates: Requirements 1.2**
    """
    captured: list[Message] = []
    cm = _default_cm()
    app, cm = _make_test_app(conversation_manager=cm, capture_appended_messages=captured)

    with patch(
        "quantgambit.api.copilot_endpoints.ConversationManager",
        return_value=cm,
    ), patch(
        "quantgambit.api.copilot_endpoints.SettingsMutationManager",
        return_value=_default_sm(),
    ), patch(
        "quantgambit.api.copilot_endpoints.create_tool_registry",
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/copilot/chat",
                json={"message": msg},
            )

    assert resp.status_code == 200, (
        f"Expected 200 for valid message {msg!r}, got {resp.status_code}"
    )

    # The engine appends the user message first. Verify it was captured.
    user_messages = [m for m in captured if m.role == "user"]
    assert len(user_messages) >= 1, (
        f"Expected at least one user message to be persisted, got {len(user_messages)}"
    )
    persisted = user_messages[0]
    assert persisted.role == "user", (
        f"Expected role='user', got {persisted.role!r}"
    )
    assert persisted.content == msg, (
        f"Expected content={msg!r}, got {persisted.content!r}"
    )
