from quantgambit.risk.validator import DeepTraderRiskValidator
from quantgambit.deeptrader_core.types import StrategySignal


def _signal():
    return StrategySignal(
        strategy_id="test",
        symbol="BTC",
        side="long",
        size=1.0,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        meta_reason="test",
        profile_id="p1",
    )


def _context(risk_mode: str, risk_scale: float):
    return {
        "market_context": {"risk_mode": risk_mode, "risk_scale": risk_scale},
        "account": {"equity": 1000.0, "daily_pnl": 0.0},
        "positions": [
            {"symbol": "ETH", "size_usd": 100.0},
            {"symbol": "SOL", "size_usd": 100.0},
        ],
        "peak_balance": 1000.0,
        "consecutive_losses": 0,
    }


def test_conservative_risk_caps_positions():
    validator = DeepTraderRiskValidator()
    allowed = validator.allow(_signal(), context=_context("conservative", 0.5))
    assert allowed is False
    assert validator.last_rejection_reason and "max_positions_exceeded" in validator.last_rejection_reason


def test_normal_risk_allows_positions():
    validator = DeepTraderRiskValidator()
    allowed = validator.allow(_signal(), context=_context("normal", 0.5))
    assert allowed is True
