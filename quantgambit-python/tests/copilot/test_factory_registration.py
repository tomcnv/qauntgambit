"""Tests for factory registration of new market query tools.

Verifies that ``create_tool_registry`` registers ``query_market_price``,
``query_market_quality``, and ``query_market_context`` alongside the
existing tools.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.tools.factory import create_tool_registry
from quantgambit.copilot.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# The three new market tools that must be present after task 5.1
# ---------------------------------------------------------------------------

NEW_MARKET_TOOLS: set[str] = {
    "query_market_price",
    "query_market_quality",
    "query_market_context",
}

# Total expected count: 12 original + 3 market + 2 candles/trade_flow = 17
EXPECTED_TOTAL_TOOL_COUNT = 17


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


class TestMarketToolRegistration:
    """Verify the three new market tools are registered in the factory."""

    def test_list_definitions_includes_market_price(self, registry: ToolRegistry) -> None:
        names = {d["name"] for d in registry.list_definitions()}
        assert "query_market_price" in names

    def test_list_definitions_includes_market_quality(self, registry: ToolRegistry) -> None:
        names = {d["name"] for d in registry.list_definitions()}
        assert "query_market_quality" in names

    def test_list_definitions_includes_market_context(self, registry: ToolRegistry) -> None:
        names = {d["name"] for d in registry.list_definitions()}
        assert "query_market_context" in names

    def test_all_new_market_tools_present(self, registry: ToolRegistry) -> None:
        names = {d["name"] for d in registry.list_definitions()}
        assert NEW_MARKET_TOOLS.issubset(names)

    def test_tool_count_increased_by_three(self, registry: ToolRegistry) -> None:
        definitions = registry.list_definitions()
        assert len(definitions) == EXPECTED_TOTAL_TOOL_COUNT

    def test_new_tools_retrievable_by_name(self, registry: ToolRegistry) -> None:
        for name in NEW_MARKET_TOOLS:
            tool = registry.get(name)
            assert tool is not None, f"Tool '{name}' not found in registry"
            assert tool.name == name

    def test_new_tools_have_descriptions(self, registry: ToolRegistry) -> None:
        for name in NEW_MARKET_TOOLS:
            tool = registry.get(name)
            assert tool is not None
            assert tool.description, f"Tool '{name}' has no description"

    def test_new_tools_have_parameter_schemas(self, registry: ToolRegistry) -> None:
        for name in NEW_MARKET_TOOLS:
            tool = registry.get(name)
            assert tool is not None
            assert isinstance(tool.parameters_schema, dict), (
                f"Tool '{name}' has no parameter schema"
            )

    def test_new_tools_have_callable_handlers(self, registry: ToolRegistry) -> None:
        for name in NEW_MARKET_TOOLS:
            tool = registry.get(name)
            assert tool is not None
            assert callable(tool.handler), f"Tool '{name}' handler is not callable"
