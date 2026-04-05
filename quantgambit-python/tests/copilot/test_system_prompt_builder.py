"""Unit tests for SystemPromptBuilder."""

import pytest

from quantgambit.copilot.models import ToolDefinition, TradeContext
from quantgambit.copilot.prompt import SystemPromptBuilder
from quantgambit.copilot.tools.registry import ToolRegistry
from quantgambit.docs.loader import DocLoader, PageDoc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _noop_handler(**kwargs):
    return {}


def _make_registry(*tools: tuple[str, str]) -> ToolRegistry:
    """Create a registry with the given (name, description) pairs."""
    reg = ToolRegistry()
    for name, desc in tools:
        reg.register(ToolDefinition(
            name=name,
            description=desc,
            parameters_schema={"type": "object", "properties": {}},
            handler=_noop_handler,
        ))
    return reg


def _sample_trade_context(**overrides) -> TradeContext:
    defaults = dict(
        trade_id="trade-abc-123",
        symbol="BTCUSDT",
        side="BUY",
        entry_price=42000.50,
        exit_price=43100.75,
        pnl=1100.25,
        hold_time_seconds=3600.0,
        decision_trace_id="trace-xyz-789",
    )
    defaults.update(overrides)
    return TradeContext(**defaults)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

PIPELINE_STAGES = [
    "data_readiness",
    "amt_calculator",
    "global_gate",
    "profile_routing",
    "signal_check",
    "arbitration",
    "confirmation",
    "ev_gate",
    "execution_feasibility",
    "execution",
    "position_evaluation",
    "risk_check",
    "prediction_gate",
    "snapshot_builder",
    "candidate_generation",
    "candidate_veto",
    "confidence_gate",
    "confidence_position_sizer",
    "cooldown",
    "cost_data_quality",
    "ev_position_sizer",
    "fee_aware_entry",
    "minimum_hold_time",
    "session_filter",
    "session_risk",
    "strategy_trend_alignment",
    "symbol_characteristics",
]


class TestPipelineStages:
    """Requirement 1.1 – prompt includes all pipeline stages."""

    def test_all_stages_present(self):
        builder = SystemPromptBuilder(_make_registry())
        prompt = builder.build()
        for stage in PIPELINE_STAGES:
            assert stage in prompt, f"Missing pipeline stage: {stage}"

    def test_stages_present_with_trade_context(self):
        builder = SystemPromptBuilder(_make_registry())
        prompt = builder.build(trade_context=_sample_trade_context())
        for stage in PIPELINE_STAGES:
            assert stage in prompt


# ---------------------------------------------------------------------------
# Trading terminology
# ---------------------------------------------------------------------------

TRADING_TERMS = ["PnL", "drawdown", "Sharpe ratio", "win rate", "exposure", "position sizing"]


class TestTradingTerminology:
    """Requirement 10.3 – prompt includes trading domain terminology."""

    def test_all_terms_present(self):
        builder = SystemPromptBuilder(_make_registry())
        prompt = builder.build()
        prompt_lower = prompt.lower()
        for term in TRADING_TERMS:
            assert term.lower() in prompt_lower, f"Missing term: {term}"


# ---------------------------------------------------------------------------
# Behavioral guidelines
# ---------------------------------------------------------------------------

class TestBehavioralGuidelines:
    """Requirements 10.4, 10.5 – use tools, don't fabricate, acknowledge uncertainty."""

    def test_use_tools_guideline(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "use" in prompt.lower() and "tool" in prompt.lower()

    def test_no_fabrication_guideline(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "fabricat" in prompt.lower()

    def test_acknowledge_uncertainty_guideline(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "uncertainty" in prompt.lower()


# ---------------------------------------------------------------------------
# Tool inclusion
# ---------------------------------------------------------------------------

class TestToolInclusion:
    """Requirement 10.2 – prompt includes name and description of every registered tool."""

    def test_empty_registry(self):
        builder = SystemPromptBuilder(_make_registry())
        prompt = builder.build()
        assert "Available Tools" in prompt

    def test_single_tool(self):
        reg = _make_registry(("query_trades", "Query recent trades"))
        prompt = SystemPromptBuilder(reg).build()
        assert "query_trades" in prompt
        assert "Query recent trades" in prompt

    def test_multiple_tools(self):
        reg = _make_registry(
            ("query_trades", "Query recent trades"),
            ("query_positions", "Get open positions"),
            ("query_performance", "Compute performance metrics"),
        )
        prompt = SystemPromptBuilder(reg).build()
        assert "query_trades" in prompt
        assert "query_positions" in prompt
        assert "query_performance" in prompt
        assert "Query recent trades" in prompt
        assert "Get open positions" in prompt
        assert "Compute performance metrics" in prompt


# ---------------------------------------------------------------------------
# Trade context injection
# ---------------------------------------------------------------------------

class TestTradeContextInjection:
    """Requirement 11.2 – inject trade data into prompt when TradeContext provided."""

    def test_no_trade_context(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "Active Trade Context" not in prompt

    def test_trade_context_fields_present(self):
        ctx = _sample_trade_context()
        prompt = SystemPromptBuilder(_make_registry()).build(trade_context=ctx)

        assert ctx.trade_id in prompt
        assert ctx.symbol in prompt
        assert ctx.side in prompt
        assert str(ctx.entry_price) in prompt
        assert str(ctx.exit_price) in prompt
        assert str(ctx.pnl) in prompt
        assert str(ctx.hold_time_seconds) in prompt
        assert ctx.decision_trace_id in prompt

    def test_trade_context_without_trace_id(self):
        ctx = _sample_trade_context(decision_trace_id=None)
        prompt = SystemPromptBuilder(_make_registry()).build(trade_context=ctx)

        assert ctx.trade_id in prompt
        assert ctx.symbol in prompt
        assert "Decision Trace ID" not in prompt

    def test_trade_context_section_header(self):
        ctx = _sample_trade_context()
        prompt = SystemPromptBuilder(_make_registry()).build(trade_context=ctx)
        assert "Active Trade Context" in prompt


# ---------------------------------------------------------------------------
# Prompt structure
# ---------------------------------------------------------------------------

class TestPromptStructure:
    """Verify overall prompt structure and section ordering."""

    def test_contains_platform_overview(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "QuantGambit" in prompt

    def test_contains_decision_pipeline_header(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "Decision Pipeline" in prompt

    def test_contains_guidelines_header(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert "Guidelines" in prompt

    def test_build_returns_string(self):
        prompt = SystemPromptBuilder(_make_registry()).build()
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Helpers for page context tests
# ---------------------------------------------------------------------------

def _make_doc_loader_with_page(page: PageDoc) -> DocLoader:
    """Create a DocLoader pre-loaded with a single PageDoc."""
    loader = DocLoader()
    loader._pages[page.path] = page
    return loader


def _sample_page_doc(**overrides) -> PageDoc:
    defaults = dict(
        path="/live",
        title="Live Trading",
        group="Trading",
        description="Active bot status & controls",
        raw_markdown="",
        sections={
            "_intro": "Real-time execution monitoring and control.",
            "Widgets & Cards": "### Status Strip\n- Shows heartbeat",
            "Actions": "- Start/Pause/Halt bot via RunBar",
        },
        widgets=["Status Strip"],
        modals=[],
        actions=["Start/Pause/Halt bot via RunBar"],
        settings=[],
    )
    defaults.update(overrides)
    return PageDoc(**defaults)


# ---------------------------------------------------------------------------
# Page context injection
# ---------------------------------------------------------------------------

class TestPageContextInjection:
    """Requirements 4.3, 5.6 – SystemPromptBuilder page context section."""

    def test_no_page_path_omits_section(self):
        """build() without page_path does NOT include 'Current Page Context'."""
        builder = SystemPromptBuilder(_make_registry())
        prompt = builder.build()
        assert "Current Page Context" not in prompt

    def test_valid_page_path_includes_section(self):
        """build() with a valid page_path includes 'Current Page Context'."""
        doc = _sample_page_doc()
        loader = _make_doc_loader_with_page(doc)
        builder = SystemPromptBuilder(_make_registry(), doc_loader=loader)
        prompt = builder.build(page_path="/live")
        assert "Current Page Context" in prompt

    def test_valid_page_path_includes_title(self):
        """build() with a valid page_path includes the page title."""
        doc = _sample_page_doc(title="Live Trading")
        loader = _make_doc_loader_with_page(doc)
        builder = SystemPromptBuilder(_make_registry(), doc_loader=loader)
        prompt = builder.build(page_path="/live")
        assert "Live Trading" in prompt

    def test_valid_page_path_includes_description(self):
        """build() with a valid page_path includes the page description."""
        doc = _sample_page_doc(description="Active bot status & controls")
        loader = _make_doc_loader_with_page(doc)
        builder = SystemPromptBuilder(_make_registry(), doc_loader=loader)
        prompt = builder.build(page_path="/live")
        assert "Active bot status & controls" in prompt

    def test_invalid_page_path_omits_section(self):
        """build() with an unknown page_path does NOT include 'Current Page Context'."""
        doc = _sample_page_doc()
        loader = _make_doc_loader_with_page(doc)
        builder = SystemPromptBuilder(_make_registry(), doc_loader=loader)
        prompt = builder.build(page_path="/nonexistent")
        assert "Current Page Context" not in prompt

    def test_no_doc_loader_omits_section(self):
        """build() with page_path but no DocLoader does NOT include 'Current Page Context'."""
        builder = SystemPromptBuilder(_make_registry(), doc_loader=None)
        prompt = builder.build(page_path="/live")
        assert "Current Page Context" not in prompt

