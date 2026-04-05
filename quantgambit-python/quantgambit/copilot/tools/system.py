"""Copilot tools: query_system_health and query_risk_config.

Queries Redis for system health status (kill switch, control state, service
connectivity) and active risk configuration.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schemas exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_SYSTEM_HEALTH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

QUERY_RISK_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# query_system_health handler
# ---------------------------------------------------------------------------

async def _query_system_health_handler(
    *,
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> dict[str, Any]:
    """Return system health including kill switch, control state, and Redis connectivity."""

    # --- Kill switch status ---
    kill_switch: dict[str, Any] = {"active": False, "reason": None, "timestamp": None}
    ks_key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:state"
    try:
        ks_data = await _redis_get_json(redis_client, ks_key)
        if ks_data is not None:
            kill_switch = {
                "active": bool(ks_data.get("is_active", False)),
                "reason": ks_data.get("reason") or ks_data.get("message"),
                "timestamp": ks_data.get("timestamp") or ks_data.get("triggered_at"),
            }
    except Exception:
        logger.warning("query_system_health: kill switch read failed", exc_info=True)

    # --- Control state ---
    control_state: dict[str, Any] = {"status": "unknown", "mode": None}
    ctrl_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
    try:
        ctrl_data = await _redis_get_json(redis_client, ctrl_key)
        if ctrl_data is not None:
            status = ctrl_data.get("status") or ctrl_data.get("state")
            if not status:
                # Backward-compatible normalization for runtime control snapshots.
                if "trading_paused" in ctrl_data:
                    status = "paused" if bool(ctrl_data.get("trading_paused")) else "running"
                elif "trading_active" in ctrl_data:
                    status = "running" if bool(ctrl_data.get("trading_active")) else "paused"
            control_state = {
                "status": status or "unknown",
                "mode": ctrl_data.get("mode") or ctrl_data.get("trading_mode"),
                "failover_state": ctrl_data.get("failover_state"),
            }
    except Exception:
        logger.warning("query_system_health: control state read failed", exc_info=True)

    # --- Service health (Redis connectivity) ---
    services: dict[str, str] = {}
    try:
        pong = await redis_client.ping()
        services["redis"] = "healthy" if pong else "unhealthy"
    except Exception:
        services["redis"] = "unhealthy"

    return {
        "kill_switch": kill_switch,
        "control_state": control_state,
        "services": services,
    }


# ---------------------------------------------------------------------------
# query_risk_config handler
# ---------------------------------------------------------------------------

async def _query_risk_config_handler(
    *,
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> dict[str, Any]:
    """Return the active risk configuration from Redis."""

    # Primary key: risk:sizing contains the live risk snapshot
    risk_key = f"quantgambit:{tenant_id}:{bot_id}:risk:sizing"
    try:
        risk_data = await _redis_get_json(redis_client, risk_key)
        if risk_data is not None:
            return risk_data
    except Exception:
        logger.warning("query_risk_config: risk:sizing read failed", exc_info=True)

    # Fallback: risk:latest
    fallback_key = f"quantgambit:{tenant_id}:{bot_id}:risk:latest"
    try:
        fallback_data = await _redis_get_json(redis_client, fallback_key)
        if fallback_data is not None:
            return fallback_data
    except Exception:
        logger.warning("query_risk_config: risk:latest read failed", exc_info=True)

    return {"error": "No risk configuration found"}


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def create_query_system_health_tool(
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_system_health``."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _query_system_health_handler(
            redis_client=redis_client,
            tenant_id=tenant_id,
            bot_id=bot_id,
        )

    return ToolDefinition(
        name="query_system_health",
        description=(
            "Query the current system health status. "
            "Returns kill switch status (active, reason, timestamp), "
            "control state (status, trading mode), and service health "
            "(Redis connectivity). Takes no parameters."
        ),
        parameters_schema=QUERY_SYSTEM_HEALTH_SCHEMA,
        handler=handler,
    )


def create_query_risk_config_tool(
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_risk_config``."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _query_risk_config_handler(
            redis_client=redis_client,
            tenant_id=tenant_id,
            bot_id=bot_id,
        )

    return ToolDefinition(
        name="query_risk_config",
        description=(
            "Query the active risk configuration. "
            "Returns the current risk parameters including exposure limits, "
            "position sizing settings, and guardrail thresholds. "
            "Takes no parameters."
        ),
        parameters_schema=QUERY_RISK_CONFIG_SCHEMA,
        handler=handler,
    )
