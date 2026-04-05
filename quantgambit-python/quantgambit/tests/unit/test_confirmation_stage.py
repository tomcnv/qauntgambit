"""
Unit tests for ConfirmationStage.

Tests the confirmation stage that validates CandidateSignals using flow
and trend signals.

Requirement 4.6: Validate candidates using flow_rotation and trend bounds
Requirement 4.7: Convert confirmed candidates to StrategySignal
Requirement 4.10: Record predicate-level failures
"""

import pytest
from dataclasses import dataclass, replace
from unittest.mock import MagicMock

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.confirmation_stage import ConfirmationStage, ConfirmationConfig
from quantgambit.deeptrader_core.types import CandidateSignal, StrategySignal


@dataclass
class MockAMTLevels:
    """Mock AMT levels for testing."""
    flow_rotation: float = 0.0
    trend_bias: float = 0.0
    rotation_factor: float = 0.0


@pytest.fixture
def stage():
    """Create ConfirmationStage with default config."""
    return ConfirmationStage()


@pytest.fixture
def stage_with_config():
    """Create ConfirmationStage with custom config."""
    config = ConfirmationConfig(
        min_flow_magnitude=0.3,
        max_adverse_trend=0.5,
        default_size=0.05,
    )
    return ConfirmationStage(config=config)


@pytest.fixture
def ctx():
    """Create a basic StageContext."""
    return StageContext(
        symbol="BTCUSDT",
        data={},
    )


def make_candidate(
    side: str = "long",
    setup_score: float = 0.7,
    requires_flow_reversal: bool = True,
    max_adverse_trend_bias: float = 0.5,
    sl_distance_bps: float = 100.0,
    tp_distance_bps: float = 200.0,
) -> CandidateSignal:
    """Helper to create CandidateSignal."""
    return CandidateSignal(
        symbol="BTCUSDT",
        side=side,
        strategy_id="test_strategy",
        profile_id="default",
        entry_price=50000.0,
        sl_distance_bps=sl_distance_bps,
        tp_distance_bps=tp_distance_bps,
        setup_score=setup_score,
        requires_flow_reversal=requires_flow_reversal,
        max_adverse_trend_bias=max_adverse_trend_bias,
    )


class TestConfirmationStage:
    """Tests for ConfirmationStage."""
    
    @pytest.mark.asyncio
    async def test_no_candidate(self, stage, ctx):
        """Test stage continues when no candidate available."""
        ctx.data["candidate_signal"] = None
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.signal is None
    
    @pytest.mark.asyncio
    async def test_no_amt_levels(self, stage, ctx):
        """Test stage rejects when AMT levels unavailable."""
        ctx.data["candidate_signal"] = make_candidate()
        ctx.data["amt_levels"] = None
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        assert ctx.rejection_reason == "no_amt_levels_for_confirmation"

    @pytest.mark.asyncio
    async def test_fallback_market_context_materializes_amt_levels(self, stage, ctx):
        """Confirmation should accept fallback AMT-like snapshot data."""
        ctx.data["candidate_signal"] = make_candidate(side="long")
        ctx.data["amt_levels"] = None
        ctx.data["mid_price"] = 50000.0
        ctx.data["features"] = {
            "point_of_control": 49950.0,
            "value_area_high": 50050.0,
            "value_area_low": 49900.0,
            "position_in_value": "inside",
            "distance_to_poc": 50.0,
            "distance_to_vah": 50.0,
            "distance_to_val": 100.0,
            "distance_to_poc_bps": 10.0,
            "distance_to_vah_bps": 10.0,
            "distance_to_val_bps": 20.0,
            "rotation_factor": 1.0,
            "trend_bias": 0.0,
            "timestamp": 1234.5,
        }
        ctx.data["market_context"] = {
            "candle_count": 1,
            "timestamp": 1234.5,
        }

        result = await stage.run(ctx)

        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
        assert ctx.data["amt_levels"] is not None
    
    @pytest.mark.asyncio
    async def test_long_confirmed_positive_flow(self, stage, ctx):
        """Test long candidate confirmed with positive flow."""
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
        assert isinstance(ctx.signal, StrategySignal)
        assert ctx.signal.side == "long"
    
    @pytest.mark.asyncio
    async def test_short_confirmed_negative_flow(self, stage, ctx):
        """Test short candidate confirmed with negative flow."""
        candidate = make_candidate(side="short")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
        assert ctx.signal.side == "short"
    
    @pytest.mark.asyncio
    async def test_long_rejected_negative_flow(self, stage, ctx):
        """Test long candidate rejected with negative flow."""
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.0)
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        assert "flow_not_positive" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_short_rejected_positive_flow(self, stage, ctx):
        """Test short candidate rejected with positive flow."""
        candidate = make_candidate(side="short")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        assert "flow_not_negative" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_long_rejected_bearish_trend(self, stage, ctx):
        """Test long candidate rejected with too bearish trend."""
        candidate = make_candidate(side="long", max_adverse_trend_bias=0.3)
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=-0.5)
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        assert "trend_too_bearish" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_short_rejected_bullish_trend(self, stage, ctx):
        """Test short candidate rejected with too bullish trend."""
        candidate = make_candidate(side="short", max_adverse_trend_bias=0.3)
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.5)
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        assert "trend_too_bullish" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_flow_reversal_not_required(self, stage, ctx):
        """Test candidate without flow reversal requirement."""
        candidate = make_candidate(side="long", requires_flow_reversal=False)
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.0)  # Negative flow
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        # Should pass because flow reversal not required
        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
    
    @pytest.mark.asyncio
    async def test_signal_has_correct_prices(self, stage, ctx):
        """Test confirmed signal has correct SL/TP prices."""
        candidate = make_candidate(
            side="long",
            sl_distance_bps=100.0,  # 1%
            tp_distance_bps=200.0,  # 2%
        )
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        signal = ctx.signal
        # SL: 50000 * (1 - 100/10000) = 49500
        assert signal.stop_loss == pytest.approx(49500.0, rel=1e-6)
        # TP: 50000 * (1 + 200/10000) = 51000
        assert signal.take_profit == pytest.approx(51000.0, rel=1e-6)
    
    @pytest.mark.asyncio
    async def test_signal_meta_reason(self, stage, ctx):
        """Test confirmed signal has correct meta_reason."""
        candidate = make_candidate(side="long")
        candidate = CandidateSignal(
            symbol="BTCUSDT",
            side="long",
            strategy_id="test_strategy",
            profile_id="default",
            entry_price=50000.0,
            sl_distance_bps=100.0,
            tp_distance_bps=200.0,
            setup_reason="poc_distance_35bps",
        )
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.2)
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert "poc_distance_35bps" in ctx.signal.meta_reason
        assert "flow=1.00" in ctx.signal.meta_reason
        assert "trend=0.20" in ctx.signal.meta_reason
    
    @pytest.mark.asyncio
    async def test_uses_rotation_factor_fallback(self, stage, ctx):
        """Test stage uses rotation_factor when flow_rotation unavailable."""
        @dataclass
        class LegacyAMTLevels:
            rotation_factor: float = 2.0  # No flow_rotation
        
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = LegacyAMTLevels()
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        # Should use rotation_factor as fallback
        assert result == StageResult.CONTINUE
        assert ctx.signal is not None
    
    @pytest.mark.asyncio
    async def test_custom_min_flow_magnitude(self, stage_with_config, ctx):
        """Test custom min_flow_magnitude config."""
        # Config has min_flow_magnitude=0.3
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=0.2, trend_bias=0.0)  # Below 0.3
        
        result = await stage_with_config.run(ctx)
        
        assert result == StageResult.REJECT
        assert "flow_not_positive" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_confirmed_signal_stored(self, stage, ctx):
        """Test confirmed signal is stored in ctx.data."""
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data["confirmed_signal"] is ctx.signal
    
    @pytest.mark.asyncio
    async def test_diagnostics_recorded_on_failure(self, ctx):
        """Test diagnostics are recorded on failure."""
        mock_diagnostics = MagicMock()
        stage = ConfirmationStage(diagnostics=mock_diagnostics)
        
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-1.0, trend_bias=0.0)
        
        result = await stage.run(ctx)
        
        assert result == StageResult.REJECT
        mock_diagnostics.record_predicate_failure.assert_called_once_with(
            "test_strategy", "fail_flow"
        )
    
    @pytest.mark.asyncio
    async def test_diagnostics_recorded_on_success(self, ctx):
        """Test diagnostics are recorded on success."""
        mock_diagnostics = MagicMock()
        stage = ConfirmationStage(diagnostics=mock_diagnostics)
        
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        mock_diagnostics.record_confirm.assert_called_once_with("test_strategy")
    
    @pytest.mark.asyncio
    async def test_size_calculation_with_account(self, stage, ctx):
        """Test position size calculation with account state."""
        @dataclass
        class MockAccount:
            equity: float = 100000.0
        
        candidate = make_candidate(side="long", sl_distance_bps=100.0)
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        ctx.data["account_state"] = MockAccount()
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        # Size = (100000 * 0.6/100) / 500 = 600 / 500 = 1.2
        # SL distance = 50000 - 49500 = 500
        assert ctx.signal.size == pytest.approx(1.2, rel=1e-2)
    
    @pytest.mark.asyncio
    async def test_default_size_without_account(self, stage_with_config, ctx):
        """Test default size used when account unavailable."""
        candidate = make_candidate(side="long")
        ctx.data["candidate_signal"] = candidate
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=1.0, trend_bias=0.0)
        ctx.data["mid_price"] = 50000.0
        # No account_state
        
        result = await stage_with_config.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.signal.size == 0.05  # Default from config

    @pytest.mark.asyncio
    async def test_existing_signal_path_rejects_on_flow_mismatch(self, stage, ctx):
        """Live signal path should reject when flow does not match side."""
        ctx.signal = StrategySignal(
            strategy_id="test_strategy",
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
            stop_loss=49500.0,
            take_profit=51000.0,
            meta_reason="test",
            profile_id="default",
        )
        ctx.data["candidate_signal"] = None
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-0.8, trend_bias=0.0)

        result = await stage.run(ctx)

        assert result == StageResult.REJECT
        assert ctx.rejection_stage == "confirmation"
        assert "flow_not_positive_for_long" in (ctx.rejection_reason or "")

    @pytest.mark.asyncio
    async def test_existing_signal_path_passes_with_matching_flow_and_trend(self, stage, ctx):
        """Live signal path should pass with flow/trend confirmation."""
        signal = StrategySignal(
            strategy_id="test_strategy",
            symbol="BTCUSDT",
            side="short",
            size=0.1,
            entry_price=50000.0,
            stop_loss=50500.0,
            take_profit=49000.0,
            meta_reason="test",
            profile_id="default",
        )
        ctx.signal = signal
        ctx.data["candidate_signal"] = None
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-0.9, trend_bias=0.2)

        result = await stage.run(ctx)

        assert result == StageResult.CONTINUE
        assert ctx.signal is signal
        assert getattr(signal, "confirmation_version") is not None
        assert isinstance(getattr(signal, "confirmation_votes"), dict)

    @pytest.mark.asyncio
    async def test_existing_mean_reversion_signal_does_not_require_positive_flow(self, stage, ctx):
        """Mean reversion live signals should not be vetoed by adverse flow alone."""
        ctx.signal = StrategySignal(
            strategy_id="mean_reversion_fade",
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=50000.0,
            stop_loss=49500.0,
            take_profit=51000.0,
            meta_reason="test",
            profile_id="range_market_scalp",
        )
        ctx.data["candidate_signal"] = None
        ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=-2.48, trend_bias=0.0)

        result = await stage.run(ctx)

        assert result == StageResult.CONTINUE
        assert "flow_not_positive_for_long" not in (ctx.rejection_reason or "")


def test_confirmation_stage_records_shadow_comparison_metadata():
    stage = ConfirmationStage()
    stage.policy_engine.config = replace(stage.policy_engine.config, mode="shadow")
    ctx = StageContext(symbol="ETHUSDT", data={})

    confirmed, reason = stage._resolve_decision(
        ctx=ctx,
        symbol="ETHUSDT",
        strategy_id="mean_reversion_fade",
        side="long",
        legacy_confirm=True,
        legacy_reason="legacy_reject",
        unified_confirm=False,
        unified_reasons=["flow_not_positive"],
        unified_confidence=0.41,
        decision_context="entry_live_signal",
    )

    assert confirmed is True
    assert reason == ""
    comparisons = ctx.data.get("confirmation_shadow_comparisons")
    assert isinstance(comparisons, list)
    assert comparisons
    latest = comparisons[-1]
    assert latest["source_stage"] == "confirmation"
    assert latest["decision_context"] == "entry_live_signal"
    assert latest["legacy_decision"] is True
    assert latest["unified_decision"] is False
    assert latest["diff"] is True


@pytest.mark.asyncio
async def test_live_spot_signal_can_skip_flow_confirmation_when_strategy_allows():
    stage = ConfirmationStage()
    ctx = StageContext(symbol="ETHUSDT", data={})
    ctx.signal = StrategySignal(
        strategy_id="spot_dip_accumulator",
        symbol="ETHUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=101.0,
        meta_reason="inside_value_area",
        profile_id="spot_accumulation",
    )
    ctx.data["amt_levels"] = MockAMTLevels(flow_rotation=0.0, trend_bias=0.0)

    result = await stage.run(ctx)

    assert result == StageResult.CONTINUE
    assert ctx.signal is not None
    assert getattr(ctx.signal, "confirmation_votes")["flow"] is True
