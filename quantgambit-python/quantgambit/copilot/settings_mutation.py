"""SettingsMutationManager — manages settings changes proposed by the copilot.

Handles the full lifecycle of settings mutations: propose → validate → apply,
plus snapshot listing and revert.  Settings snapshots are persisted in
PostgreSQL (copilot_settings_snapshots) and current settings are read from
Redis.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from quantgambit.copilot.models import SettingsMutation, SettingsSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform safety constraints
# ---------------------------------------------------------------------------

SAFETY_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "max_exposure_usd": {"min": 0, "max": 1_000_000},
    "position_size_pct": {"min": 0.001, "max": 0.5},
    "max_drawdown_pct": {"min": 0.01, "max": 0.5},
    "max_positions": {"min": 1, "max": 100},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts_to_dt(ts: float) -> datetime:
    """Convert a UNIX timestamp to a timezone-aware datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _dt_to_ts(dt: datetime) -> float:
    """Convert a datetime to a UNIX timestamp float."""
    return dt.timestamp()


async def _redis_get_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    """Read a Redis key and parse its JSON value.

    Returns ``None`` when the key does not exist or the value is not valid
    JSON.  Never raises – connection errors are caught and logged.
    """
    try:
        raw = await redis_client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        logger.warning("redis_get_json failed for key=%s", key, exc_info=True)
        return None


async def _redis_set_json(redis_client: Any, key: str, value: dict) -> None:
    """Write a dict as JSON to a Redis key."""
    await redis_client.set(key, json.dumps(value))


def _row_to_snapshot(row: asyncpg.Record) -> SettingsSnapshot:
    """Convert a copilot_settings_snapshots row into a SettingsSnapshot."""
    settings = row["settings"]
    if isinstance(settings, str):
        settings = json.loads(settings)
    return SettingsSnapshot(
        id=str(row["id"]),
        user_id=row["user_id"],
        version=row["version"],
        settings=settings,
        actor=row["actor"],
        conversation_id=str(row["conversation_id"]) if row["conversation_id"] else None,
        mutation_id=row["mutation_id"],
        created_at=_dt_to_ts(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# SettingsMutationManager
# ---------------------------------------------------------------------------


class SettingsMutationManager:
    """Manages settings changes proposed by the copilot.

    Parameters
    ----------
    pg_pool:
        asyncpg connection pool for PostgreSQL operations.
    redis_client:
        Async Redis client for reading/writing current settings.
    tenant_id:
        Tenant identifier for Redis key scoping.
    bot_id:
        Bot identifier for Redis key scoping.
    config_bundle_manager:
        Optional ConfigBundleManager for config bundle operations.
    """

    def __init__(
        self,
        pg_pool: asyncpg.Pool,
        redis_client: Any,
        tenant_id: str,
        bot_id: str,
        config_bundle_manager: Any | None = None,
    ) -> None:
        self._pool = pg_pool
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        self._config_bundle_manager = config_bundle_manager
        # In-memory store for proposed mutations (keyed by mutation ID)
        self._pending_mutations: dict[str, SettingsMutation] = {}

    # ------------------------------------------------------------------
    # Redis key helpers
    # ------------------------------------------------------------------

    def _risk_key(self) -> str:
        return f"quantgambit:{self._tenant_id}:{self._bot_id}:risk:sizing"

    def _config_key(self) -> str:
        return f"quantgambit:{self._tenant_id}:{self._bot_id}:config:latest"

    def _execution_policy_key(self) -> str:
        return f"quantgambit:{self._tenant_id}:{self._bot_id}:execution:policy"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def propose_mutation(
        self,
        user_id: str,
        conversation_id: str,
        changes: dict,
        rationale: str,
    ) -> SettingsMutation:
        """Create a SettingsMutation with the proposed changes and rationale.

        The mutation is validated against platform safety constraints.
        Constraint violations are attached to the mutation but do not prevent
        creation — the caller decides whether to reject.
        """
        mutation_id = str(uuid.uuid4())
        violations = await self.validate_mutation(changes)

        status = "rejected" if violations else "proposed"

        mutation = SettingsMutation(
            id=mutation_id,
            user_id=user_id,
            conversation_id=conversation_id,
            changes=changes,
            rationale=rationale,
            status=status,
            created_at=time.time(),
            constraint_violations=violations,
        )

        if not violations:
            self._pending_mutations[mutation_id] = mutation

        return mutation

    async def validate_mutation(self, changes: dict) -> list[str]:
        """Validate proposed changes against platform safety constraints.

        Returns a list of constraint violation descriptions (empty if valid).
        Each entry in *changes* is expected to be ``{"old": ..., "new": ...}``.
        """
        violations: list[str] = []

        for setting_path, change in changes.items():
            new_value = change.get("new") if isinstance(change, dict) else change

            if setting_path in SAFETY_CONSTRAINTS:
                constraint = SAFETY_CONSTRAINTS[setting_path]
                try:
                    numeric = float(new_value)
                except (TypeError, ValueError):
                    violations.append(
                        f"{setting_path}: value '{new_value}' is not a valid number"
                    )
                    continue

                if numeric < constraint["min"]:
                    violations.append(
                        f"{setting_path}: value {numeric} is below minimum {constraint['min']}"
                    )
                if numeric > constraint["max"]:
                    violations.append(
                        f"{setting_path}: value {numeric} exceeds maximum {constraint['max']}"
                    )

        return violations

    async def apply_mutation(
        self,
        mutation_id: str,
        user_id: str,
    ) -> SettingsSnapshot:
        """Apply a proposed mutation.

        1. Snapshot current settings.
        2. Apply changes to Redis.
        3. Persist snapshot to PostgreSQL.
        4. Return the created snapshot.
        """
        mutation = self._pending_mutations.get(mutation_id)
        if mutation is None:
            raise ValueError(f"Mutation not found or already applied: {mutation_id}")

        if mutation.user_id != user_id:
            raise ValueError("Mutation does not belong to this user")

        # 1. Read current settings
        current = await self.get_current_settings(user_id)

        # 2. Compute next version
        next_version = await self._next_version(user_id)

        # 3. Apply changes to Redis
        risk_data = await _redis_get_json(self._redis, self._risk_key()) or {}
        for setting_path, change in mutation.changes.items():
            new_value = change.get("new") if isinstance(change, dict) else change
            risk_data[setting_path] = new_value
        await _redis_set_json(self._redis, self._risk_key(), risk_data)

        # 4. Persist snapshot to PostgreSQL
        snapshot_id = str(uuid.uuid4())
        now = time.time()

        conv_uuid = None
        if mutation.conversation_id:
            try:
                conv_uuid = uuid.UUID(mutation.conversation_id)
            except ValueError:
                # conversation_id is not a valid UUID — store as None
                pass

        await self._pool.execute(
            """
            INSERT INTO copilot_settings_snapshots
                (id, user_id, version, settings, actor, conversation_id, mutation_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            uuid.UUID(snapshot_id),
            user_id,
            next_version,
            json.dumps(current),
            "copilot",
            conv_uuid,
            mutation_id,
            _ts_to_dt(now),
        )

        # 5. Mark mutation as applied and remove from pending
        mutation.status = "applied"
        del self._pending_mutations[mutation_id]

        return SettingsSnapshot(
            id=snapshot_id,
            user_id=user_id,
            version=next_version,
            settings=current,
            actor="copilot",
            conversation_id=mutation.conversation_id,
            mutation_id=mutation_id,
            created_at=now,
        )

    async def list_snapshots(self, user_id: str) -> list[SettingsSnapshot]:
        """List settings snapshots for a user, ordered by version descending."""
        rows = await self._pool.fetch(
            """
            SELECT id, user_id, version, settings, actor,
                   conversation_id, mutation_id, created_at
            FROM copilot_settings_snapshots
            WHERE user_id = $1
            ORDER BY version DESC
            """,
            user_id,
        )
        return [_row_to_snapshot(r) for r in rows]

    async def revert_to_snapshot(
        self,
        snapshot_id: str,
        user_id: str,
    ) -> SettingsSnapshot:
        """Restore settings from a specific snapshot version.

        1. Load the target snapshot from PostgreSQL.
        2. Write its settings to Redis.
        3. Create a new snapshot recording the revert.
        4. Return the new snapshot.
        """
        # Load target snapshot
        row = await self._pool.fetchrow(
            """
            SELECT id, user_id, version, settings, actor,
                   conversation_id, mutation_id, created_at
            FROM copilot_settings_snapshots
            WHERE id = $1 AND user_id = $2
            """,
            uuid.UUID(snapshot_id),
            user_id,
        )
        if row is None:
            raise ValueError(f"Snapshot not found: {snapshot_id}")

        target = _row_to_snapshot(row)

        # Capture current settings before revert
        current = await self.get_current_settings(user_id)

        # Write target settings to Redis
        target_settings = target.settings
        # If the snapshot has structured settings, write each section to its key
        if "risk_parameters" in target_settings:
            await _redis_set_json(self._redis, self._risk_key(), target_settings["risk_parameters"])
        else:
            # Legacy/flat snapshot — write entire dict to risk key
            await _redis_set_json(self._redis, self._risk_key(), target_settings)

        # Create a new snapshot recording the revert
        next_version = await self._next_version(user_id)
        revert_snapshot_id = str(uuid.uuid4())
        now = time.time()

        await self._pool.execute(
            """
            INSERT INTO copilot_settings_snapshots
                (id, user_id, version, settings, actor, conversation_id, mutation_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            uuid.UUID(revert_snapshot_id),
            user_id,
            next_version,
            json.dumps(current),
            "user",
            None,
            None,
            _ts_to_dt(now),
        )

        return SettingsSnapshot(
            id=revert_snapshot_id,
            user_id=user_id,
            version=next_version,
            settings=current,
            actor="user",
            conversation_id=None,
            mutation_id=None,
            created_at=now,
        )

    async def get_current_settings(self, user_id: str) -> dict:
        """Read current risk params, strategy config, and execution policy from Redis."""
        risk = await _redis_get_json(self._redis, self._risk_key()) or {}
        config = await _redis_get_json(self._redis, self._config_key()) or {}
        execution_policy = await _redis_get_json(self._redis, self._execution_policy_key()) or {}

        return {
            "risk_parameters": risk,
            "strategy_config": config,
            "execution_policy": execution_policy,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _next_version(self, user_id: str) -> int:
        """Return the next snapshot version number for a user (auto-increment)."""
        row = await self._pool.fetchrow(
            """
            SELECT COALESCE(MAX(version), 0) AS max_version
            FROM copilot_settings_snapshots
            WHERE user_id = $1
            """,
            user_id,
        )
        return row["max_version"] + 1
