"""
Property-based tests for SettingsMutationManager.

Feature: trading-copilot-agent
Tests correctness properties for:
- Property 27: Settings mutation apply creates snapshot and updates settings
- Property 28: Settings mutation diff completeness
- Property 29: Settings revert restores snapshot state
- Property 30: Settings mutation constraint validation

**Validates: Requirements 14.2, 14.3, 14.4, 14.5, 14.7**
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings, assume, strategies as st

from quantgambit.copilot.models import SettingsMutation, SettingsSnapshot
from quantgambit.copilot.settings_mutation import (
    SAFETY_CONSTRAINTS,
    SettingsMutationManager,
)


# =============================================================================
# Helpers (reused from unit tests)
# =============================================================================


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
    redis._stored = stored
    return redis


class _FakePgPool:
    """Minimal fake asyncpg pool for property tests."""

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


# =============================================================================
# Hypothesis Strategies
# =============================================================================

# Valid values for each constrained setting
_valid_setting_values: dict[str, st.SearchStrategy] = {
    name: st.floats(
        min_value=constraint["min"],
        max_value=constraint["max"],
        allow_nan=False,
        allow_infinity=False,
    )
    for name, constraint in SAFETY_CONSTRAINTS.items()
}

# Unconstrained setting names (not in SAFETY_CONSTRAINTS)
_unconstrained_names = st.sampled_from([
    "custom_param_a",
    "strategy_mode",
    "rebalance_interval",
    "slippage_tolerance",
])

# Arbitrary JSON-safe values for unconstrained settings
_unconstrained_values = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
    st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
)


@st.composite
def valid_changes_strategy(draw: st.DrawFn) -> dict:
    """Generate a non-empty changes dict where all constrained settings are within bounds."""
    changes: dict[str, dict[str, Any]] = {}

    # Optionally include some constrained settings with valid values
    for name, val_st in _valid_setting_values.items():
        if draw(st.booleans()):
            old_val = draw(val_st)
            new_val = draw(val_st)
            changes[name] = {"old": old_val, "new": new_val}

    # Optionally include unconstrained settings
    n_unconstrained = draw(st.integers(min_value=0, max_value=2))
    for _ in range(n_unconstrained):
        name = draw(_unconstrained_names)
        old_val = draw(_unconstrained_values)
        new_val = draw(_unconstrained_values)
        changes[name] = {"old": old_val, "new": new_val}

    assume(len(changes) > 0)
    return changes


@st.composite
def violating_changes_strategy(draw: st.DrawFn) -> dict:
    """Generate a changes dict with at least one constraint violation."""
    setting_name = draw(st.sampled_from(list(SAFETY_CONSTRAINTS.keys())))
    constraint = SAFETY_CONSTRAINTS[setting_name]

    # Choose to violate either min or max
    violate_max = draw(st.booleans())
    if violate_max:
        bad_value = draw(st.floats(
            min_value=constraint["max"] + 0.001,
            max_value=constraint["max"] * 10 + 1,
            allow_nan=False,
            allow_infinity=False,
        ))
    else:
        bad_value = draw(st.floats(
            min_value=constraint["min"] - constraint["max"] - 1,
            max_value=constraint["min"] - 0.0001,
            allow_nan=False,
            allow_infinity=False,
        ))

    return {setting_name: {"old": 0, "new": bad_value}}


@st.composite
def non_numeric_changes_strategy(draw: st.DrawFn) -> dict:
    """Generate a changes dict with a non-numeric value for a constrained setting."""
    setting_name = draw(st.sampled_from(list(SAFETY_CONSTRAINTS.keys())))
    # Only use values that truly fail float() conversion (booleans and "NaN" succeed)
    bad_value = draw(st.sampled_from(["not_a_number", "abc", "", None, "hello", "---", "inf_x"]))
    return {setting_name: {"old": 0, "new": bad_value}}


# =============================================================================
# Property 27: Settings mutation apply creates snapshot and updates settings
# =============================================================================


class TestProperty27ApplyCreatesSnapshotAndUpdates:
    """
    **Validates: Requirements 14.3, 14.4**

    For any valid SettingsMutation, applying the mutation SHALL create a
    SettingsSnapshot containing the pre-mutation settings with a version
    number, timestamp, actor, and conversation ID, and the current settings
    after application SHALL reflect the proposed changes.
    """

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(changes=valid_changes_strategy())
    async def test_apply_creates_snapshot_with_pre_mutation_state(self, changes: dict):
        """Snapshot captures pre-mutation settings and has required metadata."""
        # Set up initial risk data in Redis
        initial_risk = {"max_positions": 10, "max_exposure_usd": 50000}
        mgr, pg, redis = _make_manager(
            redis_data={"quantgambit:t1:b1:risk:sizing": json.dumps(initial_risk)}
        )
        conv_id = str(uuid.uuid4())

        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=conv_id,
            changes=changes,
            rationale="property test",
        )
        assert mutation.status == "proposed"

        snapshot = await mgr.apply_mutation(mutation.id, "u1")

        # Snapshot has required metadata
        assert isinstance(snapshot, SettingsSnapshot)
        assert snapshot.version >= 1
        assert snapshot.created_at > 0
        assert snapshot.actor == "copilot"
        assert snapshot.conversation_id == conv_id
        assert snapshot.user_id == "u1"
        assert snapshot.mutation_id == mutation.id

        # Snapshot captures pre-mutation settings
        assert "risk_parameters" in snapshot.settings
        assert snapshot.settings["risk_parameters"] == initial_risk

        # Current Redis state reflects the proposed changes
        updated_risk = json.loads(redis._stored["quantgambit:t1:b1:risk:sizing"])
        for setting_path, change in changes.items():
            new_val = change.get("new") if isinstance(change, dict) else change
            assert updated_risk[setting_path] == new_val


# =============================================================================
# Property 28: Settings mutation diff completeness
# =============================================================================


class TestProperty28DiffCompleteness:
    """
    **Validates: Requirements 14.2**

    For any SettingsMutation with a non-empty changes dict, the rendered diff
    SHALL contain both the old value and new value for every changed setting
    path.
    """

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(changes=valid_changes_strategy())
    async def test_mutation_changes_contain_old_and_new_for_every_path(self, changes: dict):
        """Every entry in the changes dict has both old and new values."""
        mgr, _, _ = _make_manager()
        conv_id = str(uuid.uuid4())

        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=conv_id,
            changes=changes,
            rationale="diff test",
        )

        # The mutation changes dict should contain every setting path
        for setting_path in changes:
            assert setting_path in mutation.changes
            entry = mutation.changes[setting_path]
            assert isinstance(entry, dict)
            assert "old" in entry, f"Missing 'old' for {setting_path}"
            assert "new" in entry, f"Missing 'new' for {setting_path}"


# =============================================================================
# Property 29: Settings revert restores snapshot state
# =============================================================================


class TestProperty29RevertRestoresSnapshotState:
    """
    **Validates: Requirements 14.5**

    For any sequence of settings mutations producing snapshots, reverting to
    snapshot version N SHALL restore the settings to the exact state captured
    in that snapshot.
    """

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(
        val1=st.integers(min_value=1, max_value=100),
        val2=st.integers(min_value=1, max_value=100),
        val3=st.integers(min_value=1, max_value=100),
    )
    async def test_revert_restores_redis_to_snapshot_state(
        self, val1: int, val2: int, val3: int
    ):
        """After reverting to snapshot N, Redis settings match that snapshot."""
        assume(val1 != val2 or val2 != val3)  # at least one change differs

        initial_risk = {"max_positions": val1}
        mgr, pg, redis = _make_manager(
            redis_data={"quantgambit:t1:b1:risk:sizing": json.dumps(initial_risk)}
        )
        conv_id = str(uuid.uuid4())

        # Apply mutation 1: val1 -> val2
        m1 = await mgr.propose_mutation(
            "u1", conv_id,
            {"max_positions": {"old": val1, "new": val2}},
            "step 1",
        )
        s1 = await mgr.apply_mutation(m1.id, "u1")

        # Apply mutation 2: val2 -> val3
        m2 = await mgr.propose_mutation(
            "u1", conv_id,
            {"max_positions": {"old": val2, "new": val3}},
            "step 2",
        )
        s2 = await mgr.apply_mutation(m2.id, "u1")

        # Revert to s1 — should restore the state captured in s1
        # s1 captured the pre-mutation-1 state (initial_risk)
        await mgr.revert_to_snapshot(s1.id, "u1")

        current_risk = json.loads(redis._stored["quantgambit:t1:b1:risk:sizing"])
        # s1.settings contains the pre-mutation state (risk_parameters)
        assert current_risk == s1.settings["risk_parameters"]


# =============================================================================
# Property 30: Settings mutation constraint validation
# =============================================================================


class TestProperty30ConstraintValidation:
    """
    **Validates: Requirements 14.7**

    For any SettingsMutation whose proposed values exceed platform safety
    constraints (exposure above maximum, risk below minimum threshold), the
    validation SHALL return a non-empty list of constraint violation
    descriptions and the mutation SHALL be rejected.
    """

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(changes=violating_changes_strategy())
    async def test_violating_values_produce_non_empty_violations(self, changes: dict):
        """Values outside constraint bounds produce violation descriptions."""
        mgr, _, _ = _make_manager()

        violations = await mgr.validate_mutation(changes)
        assert len(violations) > 0
        # Each violation should mention the setting name
        for setting_name in changes:
            if setting_name in SAFETY_CONSTRAINTS:
                assert any(setting_name in v for v in violations)

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(changes=violating_changes_strategy())
    async def test_violating_mutation_is_rejected(self, changes: dict):
        """Mutations with constraint violations get status 'rejected'."""
        mgr, _, _ = _make_manager()
        conv_id = str(uuid.uuid4())

        mutation = await mgr.propose_mutation(
            user_id="u1",
            conversation_id=conv_id,
            changes=changes,
            rationale="should be rejected",
        )
        assert mutation.status == "rejected"
        assert len(mutation.constraint_violations) > 0
        assert mutation.id not in mgr._pending_mutations

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(changes=non_numeric_changes_strategy())
    async def test_non_numeric_constrained_values_produce_violations(self, changes: dict):
        """Non-numeric values for constrained settings produce violations."""
        mgr, _, _ = _make_manager()

        violations = await mgr.validate_mutation(changes)
        assert len(violations) > 0
        assert any("not a valid number" in v for v in violations)

    @pytest.mark.asyncio
    @settings(max_examples=100)
    @given(changes=valid_changes_strategy())
    async def test_valid_values_produce_no_violations(self, changes: dict):
        """Values within constraint bounds produce no violations."""
        mgr, _, _ = _make_manager()

        violations = await mgr.validate_mutation(changes)
        assert violations == []
