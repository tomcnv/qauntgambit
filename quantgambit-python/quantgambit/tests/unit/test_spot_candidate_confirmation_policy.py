from quantgambit.deeptrader_core.types import CandidateSignal
from quantgambit.strategies.registry import _confirm_candidate


def _candidate(strategy_id: str) -> CandidateSignal:
    return CandidateSignal(
        symbol="BTCUSDT",
        side="long",
        strategy_id=strategy_id,
        profile_id="spot_profile",
        entry_price=100.0,
        sl_distance_bps=50.0,
        tp_distance_bps=100.0,
    )


def test_spot_mean_reversion_skips_positive_flow_requirement():
    ok, reason = _confirm_candidate(
        _candidate("spot_mean_reversion"),
        {"rotation_factor": -0.4},
        {"trend_bias": 0.0},
    )

    assert ok is True
    assert reason.startswith("candidate_confirmed")


def test_spot_dip_accumulator_skips_positive_flow_requirement():
    ok, reason = _confirm_candidate(
        _candidate("spot_dip_accumulator"),
        {"rotation_factor": -0.4},
        {"trend_bias": 0.0},
    )

    assert ok is True
    assert reason.startswith("candidate_confirmed")
