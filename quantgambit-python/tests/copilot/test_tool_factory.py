"""Tests for :func:`create_tool_registry` factory function."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.tools.factory import create_tool_registry
from quantgambit.copilot.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Expected tool names (all 17 tools from the design doc)
# ---------------------------------------------------------------------------

EXPECTED_TOOL_NAMES: set[str] = {
    # Read-only query tools
    "query_trades",
    "query_positions",
    "query_performance",
    "query_decision_traces",
    "query_pipeline_throughput",
    "query_backtests",
    "query_system_health",
    "query_risk_config",
    # Read-only query tools (market data)
    "query_market_price",
    "query_market_quality",
    "query_market_context",
    # Read-only query tools (candles & trade flow)
    "query_candles",
    "query_trade_flow",
    # Settings mutation tools
    "propose_settings_mutation",
    "apply_settings_mutation",
    "list_settings_snapshots",
    "revert_settings",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> ToolRegistry:
    """Create a fully-wired registry using mock dependencies."""
    return create_tool_registry(
        timescale_pool=MagicMock(),
        redis_client=AsyncMock(),
        dashboard_pool=MagicMock(),
        mutation_manager=AsyncMock(),
        tenant_id="test-tenant",
        bot_id="test-bot",
        user_id="test-user",
        conversation_id="test-conv",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateToolRegistry:
    """Tests for the create_tool_registry factory function."""

    def test_returns_tool_registry(self, registry: ToolRegistry) -> None:
        assert isinstance(registry, ToolRegistry)

    def test_registers_all_expected_tools(self, registry: ToolRegistry) -> None:
        definitions = registry.list_definitions()
        registered_names = {d["name"] for d in definitions}
        assert registered_names == EXPECTED_TOOL_NAMES

    def test_tool_count(self, registry: ToolRegistry) -> None:
        definitions = registry.list_definitions()
        assert len(definitions) == len(EXPECTED_TOOL_NAMES)

    def test_all_tools_have_descriptions(self, registry: ToolRegistry) -> None:
        for defn in registry.list_definitions():
            assert defn["description"], f"Tool {defn['name']} has no description"

    def test_all_tools_have_parameter_schemas(self, registry: ToolRegistry) -> None:
        for defn in registry.list_definitions():
            assert isinstance(defn["parameters"], dict), (
                f"Tool {defn['name']} has no parameter schema"
            )

    def test_all_tools_are_retrievable_by_name(self, registry: ToolRegistry) -> None:
        for name in EXPECTED_TOOL_NAMES:
            tool = registry.get(name)
            assert tool is not None, f"Tool '{name}' not found in registry"
            assert tool.name == name

    def test_all_tools_have_callable_handlers(self, registry: ToolRegistry) -> None:
        for name in EXPECTED_TOOL_NAMES:
            tool = registry.get(name)
            assert tool is not None
            assert callable(tool.handler), f"Tool '{name}' handler is not callable"


    class TestInvalidParameterRejection:
        """Verify registry.execute() rejects invalid parameters for candle and trade flow tools.

        Requirements: 8.1, 8.2, 8.5
        """

        @pytest.mark.asyncio
        async def test_query_candles_rejects_missing_symbol(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_candles", {})
            assert result.success is False
            assert result.error is not None
            assert "symbol" in result.error.lower() or "required" in result.error.lower()

        @pytest.mark.asyncio
        async def test_query_candles_rejects_extra_properties(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_candles", {"symbol": "BTCUSDT", "bogus": 42})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_candles_rejects_non_string_symbol(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_candles", {"symbol": 123})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_candles_rejects_limit_above_max(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_candles", {"symbol": "BTCUSDT", "limit": 501})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_candles_rejects_zero_timeframe(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_candles", {"symbol": "BTCUSDT", "timeframe_sec": 0})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_trade_flow_rejects_missing_symbol(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_trade_flow", {})
            assert result.success is False
            assert result.error is not None
            assert "symbol" in result.error.lower() or "required" in result.error.lower()

        @pytest.mark.asyncio
        async def test_query_trade_flow_rejects_extra_properties(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_trade_flow", {"symbol": "BTCUSDT", "bogus": 42})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_trade_flow_rejects_non_string_symbol(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_trade_flow", {"symbol": 123})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_trade_flow_rejects_window_above_max(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_trade_flow", {"symbol": "BTCUSDT", "window_sec": 3601})
            assert result.success is False
            assert result.error is not None

        @pytest.mark.asyncio
        async def test_query_trade_flow_rejects_zero_window(self, registry: ToolRegistry) -> None:
            result = await registry.execute("query_trade_flow", {"symbol": "BTCUSDT", "window_sec": 0})
            assert result.success is False
            assert result.error is not None

