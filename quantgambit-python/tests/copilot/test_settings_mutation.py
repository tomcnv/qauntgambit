"""Unit tests for SettingsMutationManager."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from quantgambit.copilot.models import SettingsMutation, SettingsSnapshot
from quantgambit.copilot.settings_mutation import (
    SAFETY_CONSTRAINTS,
    SettingsMutationManager,
    _redis_get_json,
    _redis_set_json,
    _row_to_snapshot,
)

# Reusable conversation IDs for tests
_CONV_1 = str(uuid.uuid4())
_CONV_2 = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(data: dict[str, str | None] | None = None) -> AsyncMock:
    """Return a mock Redis client with configurable key data."""
    redis = AsyncMock()
    stored: dict[str, str] = {}
    if data:
        stored.update({k: v for k, v in data.items() if v is not None})

    async def _get(key: str) -> bytes | None:
        val = stored.get(key)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val

    async def _set(key: str, value: str) -> None:
        stored[key] = value if isinstance(value, str) else value.decode("utf-8")

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis._stored = stored  # expose for assertions
    return redis


class _FakePgPool:
    """Minimal fake asyncpg pool for unit tests."""

    def __init__(self) -> None:
        self._snapshots: list[dict[str, Any]] = []

    async def execute(self, query: str, *args: Any) -> None:
        if "INSERT INTO copilot_settings_snapshots" in query:
            self._snapshots.append({
                "id": args[0],
                "user_id": args[1],
                "version": args[2],
                "settings": args[3],
                "actor": args[4],
                "conversation_id": args[5],
                "mutation_id": args[6],
                "created_at": args[7],
            })

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "MAX(version)" in query:
            user_id = args[0]
            versions = [s["version"] for s in self._snapshots if s["user_id"] == user_id]
            return {"max_version": max(versions) if versions else 0}

        if "copilot_settings_snapshots" in query and "WHERE id" in query:
            snap_id = args[0]
            user_id = args[1]
            for s in self._snapshots:
                if s["id"] == snap_id and s["user_id"] == user_id:
                    return s
            return None

        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "copilot_settings_snapshots" in query:
            user_id = args[0]
            rows = [s for s in self._snapshots if s["user_id"] == user_id]
            rows.sort(key=lambda r: r["version"], reverse=True)
            return rows
        return []


def _make_manager(
    redis_data: dict[str, str | None] | None = None,
    tenant_id: str = "t1",
    bot_id: str = "b1",
) -> tuple[SettingsMutationManager, _FakePgPool, AsyncMock]:
    """Create a SettingsMutationManager with fake dependencies."""
    pg = _FakePgPool()
    redis = _make_redis(redis_data)
    mgr = SettingsMutationManager(
        pg_pool=pg,  # type: ignore[arg-type]
        redis_client=redis,
        tenant_id=tenant_id,
        bot_id=bot_id,
    )
    return mgr, pg, redis


# ---------------------------------------------------------------------------
# _redis_get_json / _redis_set_json
# ---------------------------------------------------------------------------


class TestRedisHelpers:
    @pytest.mark.asyncio
    async def test_get_json_returns_parsed_dict(self):
        redis = _make_redis({"k": json.dumps({"a": 1})})
        result = await _redis_get_json(redis, "k")
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_json_returns_none_for_missing(self):
        redis = _make_redis()
        result = await _redis_get_json(redis, "missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_json_returns_none_on_error(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("down"))
        result = await _redis_get_json(redis, "k")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_json_writes_value(self):
        redis = _make_redis()
        await _redis_set_json(redis, "k", {"x": 42})
        redis.set.assert_called_once_with("k", json.dumps({"x": 42}))


# ---------------------------------------------------------------------------
# _row_to_snapshot
# ---------------------------------------------------------------------------


class TestRowToSnapshot:
    def test_converts_row(self):
        now = datetime.now(tz=timezone.utc)
        row = {
            "id": uuid.uuid4(),
            "user_id": "u1",
            "version": 3,
            "settings": {"risk": "data"},
            "actor": "copilot",
            "conversation_id": uuid.uuid4(),
            "mutation_id": "mut-1",
            "created_at": now,
        }
        snap = _row_to_snapshot(row)
        assert snap.user_id == "u1"
        assert snap.version == 3
        assert snap.settings == {"risk": "data"}
        assert snap.actor == "copilot"
        assert snap.mutation_id == "mut-1"

    def test_handles_string_settings(self):
        now = datetime.now(tz=timezone.utc)
        row = {
            "id": uuid.uuid4(),
            "user_id": "u1",
            "version": 1,
            "settings": json.dumps({"a": 1}),
            "actor": "user",
            "conversation_id": None,
            "mutation_id": None,
            "created_at": now,
        }
        snap = _row_to_snapshot(row)
        assert snap.settings == {"a": 1}

    def test_none_conversation_id(self):
        now = datetime.now(tz=timezone.utc)
        row = {
            "id": uuid.uuid4(),
            "user_id": "u1",
            "version": 1,
            "settings": {},
            "actor": "user",
            "conversation_id": None,
            "mutation_id": None,
            "created_at": now,
        }
        snap = _row_to_snapshot(row)
        assert snap.conversation_id is None


# ---------------------------------------------------------------------------
# validate_mutation
# ---------------------------------------------------------------------------


class TestValidateMutation:
    @pytest.mark.asyncio
    async def test_valid_changes_return_no_violations(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_exposure_usd": {"old": 100_000, "new": 500_000},
            "position_size_pct": {"old": 0.1, "new": 0.2},
            "max_drawdown_pct": {"old": 0.1, "new": 0.3},
            "max_positions": {"old": 10, "new": 50},
        })
        assert violations == []

    @pytest.mark.asyncio
    async def test_exposure_exceeds_max(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_exposure_usd": {"old": 100_000, "new": 2_000_000},
        })
        assert len(violations) == 1
        assert "max_exposure_usd" in violations[0]
        assert "exceeds maximum" in violations[0]

    @pytest.mark.asyncio
    async def test_position_size_below_min(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "position_size_pct": {"old": 0.1, "new": 0.0001},
        })
        assert len(violations) == 1
        assert "below minimum" in violations[0]

    @pytest.mark.asyncio
    async def test_max_drawdown_below_min(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_drawdown_pct": {"old": 0.1, "new": 0.005},
        })
        assert len(violations) == 1
        assert "below minimum" in violations[0]

    @pytest.mark.asyncio
    async def test_max_positions_exceeds_max(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_positions": {"old": 10, "new": 200},
        })
        assert len(violations) == 1
        assert "exceeds maximum" in violations[0]

    @pytest.mark.asyncio
    async def test_max_positions_below_min(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_positions": {"old": 10, "new": 0},
        })
        assert len(violations) == 1
        assert "below minimum" in violations[0]

    @pytest.mark.asyncio
    async def test_non_numeric_value_rejected(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_exposure_usd": {"old": 100_000, "new": "not_a_number"},
        })
        assert len(violations) == 1
        assert "not a valid number" in violations[0]

    @pytest.mark.asyncio
    async def test_multiple_violations(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_exposure_usd": {"old": 100_000, "new": 2_000_000},
            "position_size_pct": {"old": 0.1, "new": 0.0001},
        })
        assert len(violations) == 2

    @pytest.mark.asyncio
    async def test_unknown_settings_pass_through(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "some_custom_setting": {"old": "a", "new": "b"},
        })
        assert violations == []

    @pytest.mark.asyncio
    async def test_boundary_values_valid(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_exposure_usd": {"old": 0, "new": 1_000_000},
            "position_size_pct": {"old": 0.001, "new": 0.5},
            "max_drawdown_pct": {"old": 0.01, "new": 0.5},
            "max_positions": {"old": 1, "new": 100},
        })
        assert violations == []

    @pytest.mark.asyncio
    async def test_negative_exposure_rejected(self):
        mgr, _, _ = _make_manager()
        violations = await mgr.validate_mutation({
            "max_exposure_usd": {"old": 100_000, "new": -1},
        })
        assert len(violations) == 1
        assert "below minimum" in violations[0]


# ---------------------------------------------------------------------------
# propose_mutation
# ---------------------------------------------------------------------------


class TestProposeMutation:
    @pytest.mark.asyncio
    async def test_creates_mutation_with_valid_changes(self):
        mgr, _, _ = _make_manager()
        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={"max_positions": {"old": 10, "new": 20}},
            rationale="Increase capacity",
        )
        assert isinstance(mutation, SettingsMutation)
        assert mutation.status == "proposed"
        assert mutation.user_id == "u1"
        assert mutation.rationale == "Increase capacity"
        assert mutation.constraint_violations == []
        assert mutation.id in mgr._pending_mutations

    @pytest.mark.asyncio
    async def test_rejects_mutation_with_violations(self):
        mgr, _, _ = _make_manager()
        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={"max_exposure_usd": {"old": 100_000, "new": 5_000_000}},
            rationale="Go big",
        )
        assert mutation.status == "rejected"
        assert len(mutation.constraint_violations) > 0
        assert mutation.id not in mgr._pending_mutations

    @pytest.mark.asyncio
    async def test_mutation_has_uuid_id(self):
        mgr, _, _ = _make_manager()
        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={"max_positions": {"old": 5, "new": 10}},
            rationale="test",
        )
        uuid.UUID(mutation.id)  # Should not raise

    @pytest.mark.asyncio
    async def test_mutation_has_timestamp(self):
        mgr, _, _ = _make_manager()
        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={},
            rationale="test",
        )
        assert mutation.created_at > 0


# ---------------------------------------------------------------------------
# apply_mutation
# ---------------------------------------------------------------------------


class TestApplyMutation:
    @pytest.mark.asyncio
    async def test_applies_mutation_and_creates_snapshot(self):
        risk_data = {"max_positions": 10, "max_exposure_usd": 100_000}
        mgr, pg, redis = _make_manager(
            redis_data={"quantgambit:t1:b1:risk:sizing": json.dumps(risk_data)}
        )

        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={"max_positions": {"old": 10, "new": 20}},
            rationale="Increase capacity",
        )

        snapshot = await mgr.apply_mutation(mutation.id, "u1")

        assert isinstance(snapshot, SettingsSnapshot)
        assert snapshot.user_id == "u1"
        assert snapshot.version == 1
        assert snapshot.actor == "copilot"
        assert snapshot.mutation_id == mutation.id
        # Snapshot captures pre-mutation settings
        assert snapshot.settings["risk_parameters"]["max_positions"] == 10

        # Verify Redis was updated
        updated = json.loads(redis._stored["quantgambit:t1:b1:risk:sizing"])
        assert updated["max_positions"] == 20

    @pytest.mark.asyncio
    async def test_apply_unknown_mutation_raises(self):
        mgr, _, _ = _make_manager()
        with pytest.raises(ValueError, match="Mutation not found"):
            await mgr.apply_mutation("nonexistent", "u1")

    @pytest.mark.asyncio
    async def test_apply_wrong_user_raises(self):
        mgr, _, _ = _make_manager()
        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={"max_positions": {"old": 10, "new": 20}},
            rationale="test",
        )
        with pytest.raises(ValueError, match="does not belong"):
            await mgr.apply_mutation(mutation.id, "u2")

    @pytest.mark.asyncio
    async def test_apply_removes_from_pending(self):
        mgr, _, _ = _make_manager()
        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=_CONV_1,
            changes={"max_positions": {"old": 10, "new": 20}},
            rationale="test",
        )
        await mgr.apply_mutation(mutation.id, "u1")
        assert mutation.id not in mgr._pending_mutations

    @pytest.mark.asyncio
    async def test_version_auto_increments(self):
        mgr, pg, redis = _make_manager()

        m1 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 5, "new": 10}}, "r1")
        s1 = await mgr.apply_mutation(m1.id, "u1")
        assert s1.version == 1

        m2 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 10, "new": 15}}, "r2")
        s2 = await mgr.apply_mutation(m2.id, "u1")
        assert s2.version == 2


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------


class TestListSnapshots:
    @pytest.mark.asyncio
    async def test_returns_empty_for_new_user(self):
        mgr, _, _ = _make_manager()
        snapshots = await mgr.list_snapshots("u1")
        assert snapshots == []

    @pytest.mark.asyncio
    async def test_returns_snapshots_ordered_by_version_desc(self):
        mgr, pg, _ = _make_manager()

        m1 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 5, "new": 10}}, "r1")
        await mgr.apply_mutation(m1.id, "u1")
        m2 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 10, "new": 15}}, "r2")
        await mgr.apply_mutation(m2.id, "u1")

        snapshots = await mgr.list_snapshots("u1")
        assert len(snapshots) == 2
        assert snapshots[0].version > snapshots[1].version

    @pytest.mark.asyncio
    async def test_filters_by_user(self):
        mgr, pg, _ = _make_manager()

        m1 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 5, "new": 10}}, "r1")
        await mgr.apply_mutation(m1.id, "u1")
        m2 = await mgr.propose_mutation("u2", _CONV_2, {"max_positions": {"old": 5, "new": 10}}, "r2")
        await mgr.apply_mutation(m2.id, "u2")

        u1_snaps = await mgr.list_snapshots("u1")
        assert len(u1_snaps) == 1
        assert u1_snaps[0].user_id == "u1"


# ---------------------------------------------------------------------------
# revert_to_snapshot
# ---------------------------------------------------------------------------


class TestRevertToSnapshot:
    @pytest.mark.asyncio
    async def test_reverts_settings_and_creates_new_snapshot(self):
        risk_data = {"max_positions": 10}
        mgr, pg, redis = _make_manager(
            redis_data={"quantgambit:t1:b1:risk:sizing": json.dumps(risk_data)}
        )

        # Apply a mutation (snapshot v1 captures {max_positions: 10})
        m1 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 10, "new": 20}}, "r1")
        s1 = await mgr.apply_mutation(m1.id, "u1")

        # Now Redis has max_positions=20, apply another mutation
        m2 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 20, "new": 30}}, "r2")
        s2 = await mgr.apply_mutation(m2.id, "u1")

        # Revert to s1 (which captured settings before first mutation)
        revert_snap = await mgr.revert_to_snapshot(s1.id, "u1")

        assert revert_snap.actor == "user"
        assert revert_snap.version == 3  # v1, v2, then v3 for revert

        # Redis should now have the s1 snapshot settings
        current_risk = json.loads(redis._stored["quantgambit:t1:b1:risk:sizing"])
        assert current_risk == s1.settings["risk_parameters"]

    @pytest.mark.asyncio
    async def test_revert_nonexistent_snapshot_raises(self):
        mgr, _, _ = _make_manager()
        with pytest.raises(ValueError, match="Snapshot not found"):
            await mgr.revert_to_snapshot(str(uuid.uuid4()), "u1")

    @pytest.mark.asyncio
    async def test_revert_wrong_user_raises(self):
        mgr, pg, _ = _make_manager()
        m1 = await mgr.propose_mutation("u1", _CONV_1, {"max_positions": {"old": 5, "new": 10}}, "r1")
        s1 = await mgr.apply_mutation(m1.id, "u1")
        with pytest.raises(ValueError, match="Snapshot not found"):
            await mgr.revert_to_snapshot(s1.id, "u2")


# ---------------------------------------------------------------------------
# get_current_settings
# ---------------------------------------------------------------------------


class TestGetCurrentSettings:
    @pytest.mark.asyncio
    async def test_reads_all_redis_keys(self):
        mgr, _, _ = _make_manager(redis_data={
            "quantgambit:t1:b1:risk:sizing": json.dumps({"max_positions": 10}),
            "quantgambit:t1:b1:config:latest": json.dumps({"strategy": "momentum"}),
            "quantgambit:t1:b1:execution:policy": json.dumps({"mode": "aggressive"}),
        })

        settings = await mgr.get_current_settings("u1")

        assert settings["risk_parameters"] == {"max_positions": 10}
        assert settings["strategy_config"] == {"strategy": "momentum"}
        assert settings["execution_policy"] == {"mode": "aggressive"}

    @pytest.mark.asyncio
    async def test_returns_empty_dicts_when_keys_missing(self):
        mgr, _, _ = _make_manager()
        settings = await mgr.get_current_settings("u1")
        assert settings == {
            "risk_parameters": {},
            "strategy_config": {},
            "execution_policy": {},
        }

    @pytest.mark.asyncio
    async def test_uses_tenant_and_bot_scoping(self):
        mgr, _, redis = _make_manager(
            redis_data={
                "quantgambit:my_tenant:my_bot:risk:sizing": json.dumps({"x": 1}),
            },
            tenant_id="my_tenant",
            bot_id="my_bot",
        )
        settings = await mgr.get_current_settings("u1")
        assert settings["risk_parameters"] == {"x": 1}
