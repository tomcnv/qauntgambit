import asyncio
import time

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.ev_gate import CostEstimate, EVGateConfig, EVGateStage


def _ctx(strategy_id: str, p_hat: float) -> StageContext:
    now_ms = time.time() * 1000
    return StageContext(
        symbol="SOLUSDT",
        data={
            "market_context": {
                "price": 100.0,
                "best_bid": 99.99,
                "best_ask": 100.01,
                "timestamp_ms": now_ms,
                "spread_timestamp_ms": now_ms,
                "calibration_reliability": 0.95,
                "n_trades": 500,
            },
            "features": {},
            "prediction": {"confidence": p_hat},
        },
        signal={
            "side": "long",
            "position_effect": "open",
            "entry_price": 100.0,
            "stop_loss": 99.0,
            "take_profit": 101.0,
            "strategy_id": strategy_id,
            "p_hat": p_hat,
        },
    )


def test_ev_gate_allows_mean_reversion_small_pmin_near_miss(monkeypatch):
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")
    stage = EVGateStage(config=EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0))
    stage.cost_estimator.estimate = lambda **_: CostEstimate(0.0, 0.0, 0.0, 0.0, 0.0)
    stage.config.min_slippage_bps = 0.0
    stage.config.adverse_selection_bps = 0.0
    stage.config.min_expected_edge_bps = 0.0
    stage.config.min_expected_edge_bps_by_symbol = {}
    stage.config.min_expected_edge_bps_by_side = {}
    stage.config.min_expected_edge_bps_by_symbol_side = {}
    ctx = _ctx("mean_reversion_fade", 0.495)
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
    assert ctx.data.get("ev_gate_pmin_tolerance_override") is True


def test_ev_gate_keeps_pmin_reject_for_non_mean_reversion(monkeypatch):
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")
    stage = EVGateStage(config=EVGateConfig(mode="enforce", ev_min=0.0, ev_min_floor=0.0))
    stage.cost_estimator.estimate = lambda **_: CostEstimate(0.0, 0.0, 0.0, 0.0, 0.0)
    stage.config.min_slippage_bps = 0.0
    stage.config.adverse_selection_bps = 0.0
    stage.config.min_expected_edge_bps = 0.0
    stage.config.min_expected_edge_bps_by_symbol = {}
    stage.config.min_expected_edge_bps_by_side = {}
    stage.config.min_expected_edge_bps_by_symbol_side = {}
    ctx = _ctx("high_vol_breakout", 0.495)
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_stage == "ev_gate"
    assert ctx.rejection_reason == "P_BELOW_PMIN"
