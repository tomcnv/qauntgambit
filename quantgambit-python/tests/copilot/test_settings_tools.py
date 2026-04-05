"""Unit tests for ``quantgambit.copilot.tools.settings``.

Tests the four settings mutation tool wrappers:
- propose_settings_mutation
- apply_settings_mutation
- list_settings_snapshots
- revert_settings
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from quantgambit.copilot.models import (
    SettingsMutation,
    SettingsSnapshot,
    ToolDefinition,
)
from quantgambit.copilot.tools.settings import (
    APPLY_SETTINGS_MUTATION_SCHEMA,
    LIST_SETTINGS_SNAPSHOTS_SCHEMA,
    PROPOSE_SETTINGS_MUTATION_SCHEMA,
    REVERT_SETTINGS_SCHEMA,
    _mutation_to_dict,
    _snapshot_to_dict,
    create_settings_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_ID = "user-42"
CONVERSATION_ID = "conv-abc"


def _make_mutation(**overrides: Any) -> SettingsMutation:
    defaults: dict[str, Any] = {
        "id": "mut-1",
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "changes": {"max_exposure_usd": {"old": 50000, "new": 75000}},
        "rationale": "Increase exposure for higher returns",
        "status": "proposed",
        "created_at": 1700000000.0,
        "constraint_violations": [],
    }
    defaults.update(overrides)
    return SettingsMutation(**defaults)


def _make_snapshot(**overrides: Any) -> SettingsSnapshot:
    defaults: dict[str, Any] = {
        "id": "snap-1",
        "user_id": USER_ID,
        "version": 1,
        "settings": {"risk_parameters": {"max_exposure_usd": 50000}},
        "actor": "copilot",
        "conversation_id": CONVERSATION_ID,
        "mutation_id": "mut-1",
        "created_at": 1700000000.0,
    }
    defaults.update(overrides)
    return SettingsSnapshot(**defaults)


def _make_manager() -> AsyncMock:
    """Return a mock SettingsMutationManager with sensible defaults."""
    mgr = AsyncMock()
    mgr.propose_mutation.return_value = _make_mutation()
    mgr.validate_mutation.return_value = []
    mgr.apply_mutation.return_value = _make_snapshot()
    mgr.list_snapshots.return_value = [_make_snapshot()]
    mgr.revert_to_snapshot.return_value = _make_snapshot()
    return mgr


def _tools_by_name(tools: list[ToolDefinition]) -> dict[str, ToolDefinition]:
    return {t.name: t for t in tools}


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


class TestMutationToDict:
    def test_returns_dict(self):
        result = _mutation_to_dict(_make_mutation())
        assert isinstance(result, dict)

    def test_contains_all_fields(self):
        result = _mutation_to_dict(_make_mutation())
        assert result["id"] == "mut-1"
        assert result["user_id"] == USER_ID
        assert result["conversation_id"] == CONVERSATION_ID
        assert result["status"] == "proposed"
        assert result["rationale"] == "Increase exposure for higher returns"
        assert result["changes"] == {"max_exposure_usd": {"old": 50000, "new": 75000}}
        assert result["constraint_violations"] == []

    def test_with_violations(self):
        m = _make_mutation(constraint_violations=["too high"])
        result = _mutation_to_dict(m)
        assert result["constraint_violations"] == ["too high"]


class TestSnapshotToDict:
    def test_returns_dict(self):
        result = _snapshot_to_dict(_make_snapshot())
        assert isinstance(result, dict)

    def test_contains_all_fields(self):
        result = _snapshot_to_dict(_make_snapshot())
        assert result["id"] == "snap-1"
        assert result["user_id"] == USER_ID
        assert result["version"] == 1
        assert result["actor"] == "copilot"
        assert result["settings"] == {"risk_parameters": {"max_exposure_usd": 50000}}


# ---------------------------------------------------------------------------
# create_settings_tools
# ---------------------------------------------------------------------------


class TestCreateSettingsTools:
    def test_returns_four_tools(self):
        mgr = _make_manager()
        tools = create_settings_tools(mgr, USER_ID, CONVERSATION_ID)
        assert len(tools) == 4

    def test_tool_names(self):
        mgr = _make_manager()
        tools = create_settings_tools(mgr, USER_ID, CONVERSATION_ID)
        names = {t.name for t in tools}
        assert names == {
            "propose_settings_mutation",
            "apply_settings_mutation",
            "list_settings_snapshots",
            "revert_settings",
        }

    def test_all_have_descriptions(self):
        mgr = _make_manager()
        tools = create_settings_tools(mgr, USER_ID, CONVERSATION_ID)
        for tool in tools:
            assert tool.description, f"{tool.name} has empty description"

    def test_all_have_schemas(self):
        mgr = _make_manager()
        tools = create_settings_tools(mgr, USER_ID, CONVERSATION_ID)
        for tool in tools:
            assert isinstance(tool.parameters_schema, dict)

    def test_all_have_callable_handlers(self):
        mgr = _make_manager()
        tools = create_settings_tools(mgr, USER_ID, CONVERSATION_ID)
        for tool in tools:
            assert callable(tool.handler)


# ---------------------------------------------------------------------------
# propose_settings_mutation handler
# ---------------------------------------------------------------------------


class TestProposeSettingsMutationHandler:
    @pytest.mark.asyncio
    async def test_calls_propose_and_validate(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["propose_settings_mutation"].handler

        changes = {"max_exposure_usd": {"old": 50000, "new": 75000}}
        result = await handler(changes=changes, rationale="test reason")

        mgr.propose_mutation.assert_awaited_once_with(
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            changes=changes,
            rationale="test reason",
        )
        mgr.validate_mutation.assert_awaited_once_with(changes)

    @pytest.mark.asyncio
    async def test_returns_serialisable_dict(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["propose_settings_mutation"].handler

        result = await handler(
            changes={"max_exposure_usd": {"old": 50000, "new": 75000}},
            rationale="test",
        )
        assert isinstance(result, dict)
        assert "id" in result
        assert "status" in result
        assert "constraint_violations" in result

    @pytest.mark.asyncio
    async def test_includes_violations_from_validate(self):
        mgr = _make_manager()
        mgr.validate_mutation.return_value = ["exceeds max exposure"]
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["propose_settings_mutation"].handler

        result = await handler(
            changes={"max_exposure_usd": {"old": 50000, "new": 9999999}},
            rationale="go big",
        )
        assert result["constraint_violations"] == ["exceeds max exposure"]

    @pytest.mark.asyncio
    async def test_binds_user_and_conversation(self):
        mgr = _make_manager()
        tools = _tools_by_name(
            create_settings_tools(mgr, "user-99", "conv-xyz")
        )
        handler = tools["propose_settings_mutation"].handler

        await handler(changes={}, rationale="noop")

        call_kwargs = mgr.propose_mutation.call_args.kwargs
        assert call_kwargs["user_id"] == "user-99"
        assert call_kwargs["conversation_id"] == "conv-xyz"

    def test_schema_requires_changes_and_rationale(self):
        assert "changes" in PROPOSE_SETTINGS_MUTATION_SCHEMA["required"]
        assert "rationale" in PROPOSE_SETTINGS_MUTATION_SCHEMA["required"]


# ---------------------------------------------------------------------------
# apply_settings_mutation handler
# ---------------------------------------------------------------------------


class TestApplySettingsMutationHandler:
    @pytest.mark.asyncio
    async def test_calls_apply_mutation(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["apply_settings_mutation"].handler

        result = await handler(mutation_id="mut-1")

        mgr.apply_mutation.assert_awaited_once_with(
            mutation_id="mut-1",
            user_id=USER_ID,
        )

    @pytest.mark.asyncio
    async def test_returns_snapshot_dict(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["apply_settings_mutation"].handler

        result = await handler(mutation_id="mut-1")
        assert isinstance(result, dict)
        assert "id" in result
        assert "version" in result
        assert "settings" in result

    @pytest.mark.asyncio
    async def test_propagates_error_on_invalid_mutation(self):
        mgr = _make_manager()
        mgr.apply_mutation.side_effect = ValueError("Mutation not found")
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["apply_settings_mutation"].handler

        with pytest.raises(ValueError, match="Mutation not found"):
            await handler(mutation_id="nonexistent")

    def test_schema_requires_mutation_id(self):
        assert "mutation_id" in APPLY_SETTINGS_MUTATION_SCHEMA["required"]


# ---------------------------------------------------------------------------
# list_settings_snapshots handler
# ---------------------------------------------------------------------------


class TestListSettingsSnapshotsHandler:
    @pytest.mark.asyncio
    async def test_calls_list_snapshots(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["list_settings_snapshots"].handler

        result = await handler()

        mgr.list_snapshots.assert_awaited_once_with(user_id=USER_ID)

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self):
        mgr = _make_manager()
        mgr.list_snapshots.return_value = [
            _make_snapshot(id="s1", version=2),
            _make_snapshot(id="s2", version=1),
        ]
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["list_settings_snapshots"].handler

        result = await handler()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "s1"
        assert result[1]["id"] == "s2"

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_snapshots(self):
        mgr = _make_manager()
        mgr.list_snapshots.return_value = []
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["list_settings_snapshots"].handler

        result = await handler()
        assert result == []

    def test_schema_has_no_required_params(self):
        assert "required" not in LIST_SETTINGS_SNAPSHOTS_SCHEMA


# ---------------------------------------------------------------------------
# revert_settings handler
# ---------------------------------------------------------------------------


class TestRevertSettingsHandler:
    @pytest.mark.asyncio
    async def test_calls_revert_to_snapshot(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["revert_settings"].handler

        result = await handler(snapshot_id="snap-1")

        mgr.revert_to_snapshot.assert_awaited_once_with(
            snapshot_id="snap-1",
            user_id=USER_ID,
        )

    @pytest.mark.asyncio
    async def test_returns_snapshot_dict(self):
        mgr = _make_manager()
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["revert_settings"].handler

        result = await handler(snapshot_id="snap-1")
        assert isinstance(result, dict)
        assert "id" in result
        assert "version" in result
        assert "settings" in result

    @pytest.mark.asyncio
    async def test_propagates_error_on_invalid_snapshot(self):
        mgr = _make_manager()
        mgr.revert_to_snapshot.side_effect = ValueError("Snapshot not found")
        tools = _tools_by_name(create_settings_tools(mgr, USER_ID, CONVERSATION_ID))
        handler = tools["revert_settings"].handler

        with pytest.raises(ValueError, match="Snapshot not found"):
            await handler(snapshot_id="nonexistent")

    def test_schema_requires_snapshot_id(self):
        assert "snapshot_id" in REVERT_SETTINGS_SCHEMA["required"]
