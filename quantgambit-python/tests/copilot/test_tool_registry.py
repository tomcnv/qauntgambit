"""Unit tests for ToolRegistry."""

import pytest

from quantgambit.copilot.models import ToolDefinition, ToolResult
from quantgambit.copilot.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _echo_handler(**kwargs):
    """Simple handler that echoes back its parameters."""
    return kwargs


async def _failing_handler(**kwargs):
    """Handler that always raises."""
    raise RuntimeError("boom")


def _make_tool(name: str = "test_tool", description: str = "A test tool") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["symbol"],
        },
        handler=_echo_handler,
    )


# ---------------------------------------------------------------------------
# register / get
# ---------------------------------------------------------------------------

class TestRegisterAndGet:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = _make_tool()
        reg.register(tool)
        assert reg.get("test_tool") is tool

    def test_get_returns_none_for_unknown(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_register_overwrites(self):
        reg = ToolRegistry()
        tool1 = _make_tool(description="v1")
        tool2 = _make_tool(description="v2")
        reg.register(tool1)
        reg.register(tool2)
        assert reg.get("test_tool").description == "v2"


# ---------------------------------------------------------------------------
# list_definitions
# ---------------------------------------------------------------------------

class TestListDefinitions:
    def test_empty_registry(self):
        reg = ToolRegistry()
        assert reg.list_definitions() == []

    def test_returns_function_calling_format(self):
        reg = ToolRegistry()
        tool = _make_tool()
        reg.register(tool)
        defs = reg.list_definitions()
        assert len(defs) == 1
        d = defs[0]
        assert d["name"] == "test_tool"
        assert d["description"] == "A test tool"
        assert d["parameters"] == tool.parameters_schema

    def test_multiple_tools(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a", "Tool A"))
        reg.register(_make_tool("b", "Tool B"))
        names = {d["name"] for d in reg.list_definitions()}
        assert names == {"a", "b"}


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestExecute:
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        reg = ToolRegistry()
        reg.register(_make_tool())
        result = await reg.execute("test_tool", {"symbol": "BTCUSDT"})
        assert result.success is True
        assert result.data == {"symbol": "BTCUSDT"}
        assert result.duration_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        reg = ToolRegistry()
        result = await reg.execute("missing", {"symbol": "X"})
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_parameter_validation_failure(self):
        reg = ToolRegistry()
        reg.register(_make_tool())
        # 'symbol' is required but missing
        result = await reg.execute("test_tool", {})
        assert result.success is False
        assert "validation" in result.error.lower()

    @pytest.mark.asyncio
    async def test_wrong_parameter_type(self):
        reg = ToolRegistry()
        reg.register(_make_tool())
        # 'limit' should be integer, not string
        result = await reg.execute("test_tool", {"symbol": "BTC", "limit": "not_int"})
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_handler_exception_returns_failure(self):
        reg = ToolRegistry()
        tool = ToolDefinition(
            name="bad",
            description="fails",
            parameters_schema={"type": "object", "properties": {}},
            handler=_failing_handler,
        )
        reg.register(tool)
        result = await reg.execute("bad", {})
        assert result.success is False
        assert "boom" in result.error
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_duration_measured(self):
        reg = ToolRegistry()
        reg.register(_make_tool())
        result = await reg.execute("test_tool", {"symbol": "ETH"})
        assert isinstance(result.duration_ms, float)
        assert result.duration_ms >= 0
