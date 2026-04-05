import asyncio

from quantgambit.signals.pipeline import StageContext
from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerStage


class _EvGateResult:
    EV = 0.10
    ev_min_adjusted = 0.02
    C = 0.0
    calibration_reliability = 1.0


def test_ev_position_sizer_applies_calibration_multiplier():
    stage = EVPositionSizerStage()
    signal = {"side": "long", "size": 2.0}
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "ev_gate_result": _EvGateResult(),
            "calibration_size_multiplier": 0.5,
        },
        signal=signal,
    )

    asyncio.run(stage.run(ctx))

    # edge = 0.08, k=2 -> ev_mult=1.16; cost=1.0; reliability=1.0; calibration=0.5
    # final_mult = 1.16 * 1.0 * 1.0 * 0.5 = 0.58
    assert abs(signal["size"] - 1.16) < 1e-9
    result = ctx.data.get("ev_sizing_result")
    assert result is not None
    assert abs(result.final_mult - 0.58) < 1e-9
    assert abs(result.calibration_mult - 0.5) < 1e-9
