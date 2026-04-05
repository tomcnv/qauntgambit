from quantgambit.signals.services.calibration_state import (
    CalibrationState,
    evaluate_calibration,
    get_strategy_prior,
)


def test_scalper_strategies_get_the_scalper_prior():
    assert get_strategy_prior("breakout_scalp") == 0.48
    assert get_strategy_prior("poc_magnet_scalp") == 0.48
    assert get_strategy_prior("liquidity_fade_scalp") == 0.48
    assert get_strategy_prior("breakout") == 0.45


def test_cold_scalper_calibration_keeps_more_signal_probability():
    status = evaluate_calibration(
        strategy_id="breakout_scalp",
        n_trades=0,
        p_observed=0.52,
        reliability=0.0,
    )

    assert status.state == CalibrationState.COLD
    assert status.p_prior == 0.48
    assert status.p_effective >= 0.48
