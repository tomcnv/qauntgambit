import pytest

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.session_filter import SessionFilterConfig, SessionFilterStage


@pytest.mark.asyncio
async def test_session_filter_disabled_skips_risk_and_strategy_checks():
    stage = SessionFilterStage(
        config=SessionFilterConfig(
            enabled=False,
            enforce_session_preferences=True,
            enforce_strategy_sessions=True,
            apply_position_size_multiplier=True,
        )
    )
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "market_context": {
                "session": "asia",
                "volatility": "low",
                "timestamp": 1774416000,
            }
        },
        signal={"strategy_id": "spot_dip_accumulator"},
    )

    result = await stage.run(ctx)

    assert result == StageResult.CONTINUE
    assert ctx.rejection_reason is None
    assert ctx.data["session_risk"].risk_mode == "normal"
    assert ctx.data["session_risk"].reason == "session_filter_disabled"
