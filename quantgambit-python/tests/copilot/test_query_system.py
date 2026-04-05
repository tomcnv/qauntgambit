"""Unit tests for the query_system_health and query_risk_config copilot tools."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.system import (
    QUERY_RISK_CONFIG_SCHEMA,
    QUERY_SYSTEM_HEALTH_SCHEMA,
    _query_risk_config_handler,
    _query_system_health_handler,
    _redis_get_json,
    create_query_risk_config_tool,
    create_query_system_health_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis(data: dict[str, str | None] | None = None, ping_ok: bool = True) -> AsyncMock:
    """Return a mock Redis client with configurable key data and ping."""
    redis = AsyncMock()

    stored = data or {}

    async def _get(key: str) -> str | bytes | None:
        val = stored.get(key)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val

    redis.get = AsyncMock(side_effect=_get)
    redis.ping = AsyncMock(return_value=ping_ok)
    return redis


def _make_failing_redis() -> AsyncMock:
    """Return a mock Redis client that raises on every operation."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
    redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))
    return redis


# ---------------------------------------------------------------------------
# _redis_get_json
# ---------------------------------------------------------------------------


class TestRedisGetJson:
    @pytest.mark.asyncio
    async def test_returns_parsed_dict(self):
        redis = _make_redis({"mykey": json.dumps({"foo": "bar"})})
        result = await _redis_get_json(redis, "mykey")
        assert result == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_key(self):
        redis = _make_redis({})
        result = await _redis_get_json(redis, "missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_json(self):
        redis = _make_redis({"bad": "not-json{"})
        result = await _redis_get_json(redis, "bad")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self):
        redis = _make_failing_redis()
        result = await _redis_get_json(redis, "anykey")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_bytes_value(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b'{"x": 1}')
        result = await _redis_get_json(redis, "k")
        assert result == {"x": 1}


# ---------------------------------------------------------------------------
# query_system_health
# ---------------------------------------------------------------------------


class TestQuerySystemHealthHandler:
    @pytest.mark.asyncio
    async def test_healthy_system(self):
        data = {
            "quantgambit:t1:b1:kill_switch:state": json.dumps({
                "is_active": False,
                "reason": None,
                "timestamp": 1700000000.0,
            }),
            "quantgambit:t1:b1:control:state": json.dumps({
                "status": "running",
                "trading_mode": "live",
            }),
        }
        redis = _make_redis(data, ping_ok=True)
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["kill_switch"]["active"] is False
        assert result["kill_switch"]["timestamp"] == 1700000000.0
        assert result["control_state"]["status"] == "running"
        assert result["control_state"]["mode"] == "live"
        assert result["services"]["redis"] == "healthy"

    @pytest.mark.asyncio
    async def test_kill_switch_active(self):
        data = {
            "quantgambit:t1:b1:kill_switch:state": json.dumps({
                "is_active": True,
                "reason": "equity_drawdown",
                "timestamp": 1700001000.0,
            }),
        }
        redis = _make_redis(data)
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["kill_switch"]["active"] is True
        assert result["kill_switch"]["reason"] == "equity_drawdown"
        assert result["kill_switch"]["timestamp"] == 1700001000.0

    @pytest.mark.asyncio
    async def test_missing_keys_return_defaults(self):
        redis = _make_redis({})
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["kill_switch"]["active"] is False
        assert result["kill_switch"]["reason"] is None
        assert result["kill_switch"]["timestamp"] is None
        assert result["control_state"]["status"] == "unknown"
        assert result["control_state"]["mode"] is None

    @pytest.mark.asyncio
    async def test_redis_down_returns_unhealthy(self):
        redis = _make_failing_redis()
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["services"]["redis"] == "unhealthy"
        # Kill switch and control state should still have safe defaults
        assert result["kill_switch"]["active"] is False
        assert result["control_state"]["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_alternative_field_names(self):
        """Kill switch data may use 'message' and 'triggered_at' instead."""
        data = {
            "quantgambit:t1:b1:kill_switch:state": json.dumps({
                "is_active": True,
                "message": "manual trigger",
                "triggered_at": 1700002000.0,
            }),
            "quantgambit:t1:b1:control:state": json.dumps({
                "state": "paused",
                "mode": "paper",
            }),
        }
        redis = _make_redis(data)
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["kill_switch"]["reason"] == "manual trigger"
        assert result["kill_switch"]["timestamp"] == 1700002000.0
        assert result["control_state"]["status"] == "paused"
        assert result["control_state"]["mode"] == "paper"

    @pytest.mark.asyncio
    async def test_control_state_derives_status_from_trading_paused(self):
        data = {
            "quantgambit:t1:b1:control:state": json.dumps({
                "trading_paused": False,
                "trading_mode": "live",
                "failover_state": "PRIMARY_ACTIVE",
            }),
        }
        redis = _make_redis(data)
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["control_state"]["status"] == "running"
        assert result["control_state"]["mode"] == "live"
        assert result["control_state"]["failover_state"] == "PRIMARY_ACTIVE"

    @pytest.mark.asyncio
    async def test_output_schema_has_required_keys(self):
        redis = _make_redis({})
        result = await _query_system_health_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert "kill_switch" in result
        assert "control_state" in result
        assert "services" in result
        assert "active" in result["kill_switch"]
        assert "reason" in result["kill_switch"]
        assert "timestamp" in result["kill_switch"]
        assert "status" in result["control_state"]
        assert "mode" in result["control_state"]
        assert "redis" in result["services"]


# ---------------------------------------------------------------------------
# query_risk_config
# ---------------------------------------------------------------------------


class TestQueryRiskConfigHandler:
    @pytest.mark.asyncio
    async def test_returns_risk_sizing_data(self):
        risk_data = {
            "max_exposure_usd": 10000,
            "max_positions": 5,
            "position_size_pct": 0.02,
            "max_drawdown_pct": 0.10,
        }
        data = {
            "quantgambit:t1:b1:risk:sizing": json.dumps(risk_data),
        }
        redis = _make_redis(data)
        result = await _query_risk_config_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result == risk_data

    @pytest.mark.asyncio
    async def test_falls_back_to_risk_latest(self):
        fallback_data = {"max_positions": 3, "status": "active"}
        data = {
            "quantgambit:t1:b1:risk:latest": json.dumps(fallback_data),
        }
        redis = _make_redis(data)
        result = await _query_risk_config_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result == fallback_data

    @pytest.mark.asyncio
    async def test_returns_error_when_no_config(self):
        redis = _make_redis({})
        result = await _query_risk_config_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_redis_failure_returns_error(self):
        redis = _make_failing_redis()
        result = await _query_risk_config_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_prefers_sizing_over_latest(self):
        sizing = {"source": "sizing", "max_positions": 5}
        latest = {"source": "latest", "max_positions": 3}
        data = {
            "quantgambit:t1:b1:risk:sizing": json.dumps(sizing),
            "quantgambit:t1:b1:risk:latest": json.dumps(latest),
        }
        redis = _make_redis(data)
        result = await _query_risk_config_handler(
            redis_client=redis, tenant_id="t1", bot_id="b1",
        )

        assert result["source"] == "sizing"


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


class TestCreateQuerySystemHealthTool:
    def test_returns_tool_definition(self):
        redis = _make_redis({})
        tool = create_query_system_health_tool(redis, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_system_health"

    def test_description_non_empty(self):
        redis = _make_redis({})
        tool = create_query_system_health_tool(redis, "t1", "b1")
        assert len(tool.description) > 0

    def test_schema_is_empty_object(self):
        redis = _make_redis({})
        tool = create_query_system_health_tool(redis, "t1", "b1")
        assert tool.parameters_schema == QUERY_SYSTEM_HEALTH_SCHEMA
        assert tool.parameters_schema["properties"] == {}

    @pytest.mark.asyncio
    async def test_handler_delegates(self):
        data = {
            "quantgambit:t1:b1:kill_switch:state": json.dumps({"is_active": False}),
        }
        redis = _make_redis(data)
        tool = create_query_system_health_tool(redis, "t1", "b1")
        result = await tool.handler()
        assert "kill_switch" in result
        assert "services" in result


class TestCreateQueryRiskConfigTool:
    def test_returns_tool_definition(self):
        redis = _make_redis({})
        tool = create_query_risk_config_tool(redis, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_risk_config"

    def test_description_non_empty(self):
        redis = _make_redis({})
        tool = create_query_risk_config_tool(redis, "t1", "b1")
        assert len(tool.description) > 0

    def test_schema_is_empty_object(self):
        redis = _make_redis({})
        tool = create_query_risk_config_tool(redis, "t1", "b1")
        assert tool.parameters_schema == QUERY_RISK_CONFIG_SCHEMA
        assert tool.parameters_schema["properties"] == {}

    @pytest.mark.asyncio
    async def test_handler_delegates(self):
        risk_data = {"max_positions": 5}
        data = {
            "quantgambit:t1:b1:risk:sizing": json.dumps(risk_data),
        }
        redis = _make_redis(data)
        tool = create_query_risk_config_tool(redis, "t1", "b1")
        result = await tool.handler()
        assert result == risk_data
