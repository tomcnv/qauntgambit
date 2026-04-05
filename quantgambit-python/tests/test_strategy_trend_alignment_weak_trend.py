import asyncio

from quantgambit.deeptrader_core.types import StrategySignal
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.strategy_trend_alignment import StrategyTrendAlignmentStage


def _signal(strategy_id: str, side: str) -> StrategySignal:
    return StrategySignal(
        strategy_id=strategy_id,
        symbol="BTCUSDT",
        side=side,
        size=0.1,
        entry_price=50_000.0,
        stop_loss=49_500.0,
        take_profit=51_000.0,
        meta_reason="test",
        profile_id="range_market_scalp",
    )


def test_mean_reversion_long_in_weak_downtrend_passes() -> None:
    stage = StrategyTrendAlignmentStage()
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"trend": "down", "trend_strength": 0.0}},
        signal=_signal("mean_reversion_fade", "long"),
    )

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    assert ctx.rejection_reason is None


def test_mean_reversion_long_with_flat_numeric_trend_bias_passes() -> None:
    stage = StrategyTrendAlignmentStage()
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"trend": "down", "trend_bias": -0.0}},
        signal=_signal("mean_reversion_fade", "long"),
    )

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    assert ctx.rejection_reason is None


def test_mean_reversion_long_in_downtrend_passes_alignment_stage() -> None:
    stage = StrategyTrendAlignmentStage()
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"trend": "down"}},
        signal=_signal("mean_reversion_fade", "long"),
    )

    result = asyncio.run(stage.run(ctx))

    assert result == StageResult.CONTINUE
    assert ctx.rejection_reason is None
