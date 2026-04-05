import asyncio

from quantgambit.signals.stages.cost_data_quality import CostDataQualityConfig
from quantgambit.signals.stages.ev_gate import EVGateConfig
from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerConfig


def test_deeptrader_pipeline_happy_path(monkeypatch):
    import time
    from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput

    monkeypatch.setenv("ENABLE_CANDIDATE_CONFIRMATION", "true")
    engine = DecisionEngine(
        ev_gate_config=EVGateConfig(mode="shadow", ev_min=0.0, ev_min_floor=0.0),
        ev_position_sizer_config=EVPositionSizerConfig(),
        cost_data_quality_config=CostDataQualityConfig(enabled=False),
    )
    now_sec = time.time()
    now_ms = int(now_sec * 1000)
    market_context = {
        "price": 100.0,
        "profile_id": "range_market_scalp",
        "volatility_regime": "low",
        "position_in_value": "inside",
        "spread_bps": 1.0,
        "trades_per_second": 1.0,
        "rotation_factor": -1.0,
        # Keep POC close to price so snapshot doesn't reject as stale.
        "point_of_control": 99.0,
        "distance_to_poc": 1.0,
        "atr_5m": 1.0,
        "atr_5m_baseline": 2.0,
        "trend_direction": "flat",
        "flow_rotation": -1.2,
        "trend_bias": -0.1,
        "session": "us",
        "risk_mode": "normal",
        "book_timestamp_ms": now_ms,
        "spread_timestamp_ms": now_ms,
        "timestamp_ms": now_ms,
    }
    features = {
        "price": 100.0,
        "bid": 99.99,
        "ask": 100.01,
        "bid_depth_usd": 100000.0,
        "ask_depth_usd": 100000.0,
        "timestamp": now_sec,
        "book_timestamp_ms": now_ms,
        "spread_timestamp_ms": now_ms,
        "timestamp_ms": now_ms,
        "point_of_control": 99.0,
        "distance_to_poc": 1.0,
        "rotation_factor": -1.0,
        "atr_5m": 1.0,
        "atr_5m_baseline": 2.0,
        "spread": 0.0001,
        "position_in_value": "inside",
    }
    decision_input = DecisionInput(
        symbol="BTC",
        market_context=market_context,
        features=features,
        account_state={"equity": 100000.0, "daily_pnl": 0.0},
        positions=[],
            prediction={"direction": "down", "confidence": 0.9, "source": "test"},
    )
    result, ctx = asyncio.run(engine.decide_with_context(decision_input))
    assert result is True, (
        f"rejection_stage={ctx.rejection_stage} "
        f"rejection_reason={ctx.rejection_reason} "
        f"rejection_detail={ctx.rejection_detail}"
    )
    assert ctx.rejection_stage is None
    assert ctx.rejection_reason is None


def test_deeptrader_pipeline_rejects_missing_price():
    from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput

    engine = DecisionEngine(
        ev_gate_config=EVGateConfig(mode="shadow", ev_min=0.0, ev_min_floor=0.0),
        ev_position_sizer_config=EVPositionSizerConfig(),
        cost_data_quality_config=CostDataQualityConfig(enabled=False),
    )
    decision_input = DecisionInput(
        symbol="BTC",
        market_context={},
        features={},
    )
    result = asyncio.run(engine.decide(decision_input))
    assert result is False
