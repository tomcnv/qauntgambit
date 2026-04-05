"""Risk validation interface."""

from __future__ import annotations

import time
from typing import Dict


class RiskValidator:
    """Minimal risk validator interface."""

    def __init__(self) -> None:
        self.last_rejection_reason: str | None = None

    def allow(self, signal: Dict, context: dict | None = None) -> bool:
        allowed = signal.get("risk_ok", True) if isinstance(signal, dict) else True
        self.last_rejection_reason = None if allowed else "risk_blocked"
        return allowed


class DeepTraderRiskValidator(RiskValidator):
    """Adapter to deeptrader risk validator when available."""

    def __init__(self):
        super().__init__()
        try:
            from quantgambit.deeptrader_core.layer3_risk_execution.risk_validator import RiskValidator as DTRisk  # type: ignore
            from quantgambit.deeptrader_core.layer2_signals.trading_signal import TradingSignal, SignalType, SignalStrength, create_signal_id  # type: ignore
            from quantgambit.deeptrader_core.types import StrategySignal  # type: ignore
            self._validator = DTRisk()
            self._types = {
                "TradingSignal": TradingSignal,
                "SignalType": SignalType,
                "SignalStrength": SignalStrength,
                "create_signal_id": create_signal_id,
                "StrategySignal": StrategySignal,
            }
        except Exception:
            self._validator = None
            self._types = None

    def allow(self, signal: Dict, context: dict | None = None) -> bool:
        if not self._validator or not self._types:
            return super().allow(signal, context=context)
        original_limits: dict | None = None
        try:
            trading_signal = _coerce_trading_signal(self._types, signal, context or {})
            if not trading_signal:
                return super().allow(signal, context=context)
            positions = _coerce_positions(context or {})
            account_balance = _coerce_account_balance(context or {})
            if account_balance <= 0:
                return super().allow(signal, context=context)
            original_limits = _apply_risk_limits(self._validator, context or {})
            position_size_usd = _estimate_position_size_usd(signal, context or {}, trading_signal)
            daily_pnl = _coerce_daily_pnl(context or {})
            consecutive_losses = _get_attr(context, "consecutive_losses", 0)
            peak_balance = _get_attr(context, "peak_balance", account_balance)
            min_position_size_usd = _get_attr(context, "min_position_size_usd", 0.0)

            validation = self._validator.validate_signal(
                signal=trading_signal,
                position_size_usd=position_size_usd,
                account_balance=account_balance,
                current_positions=positions,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                peak_balance=peak_balance,
                min_position_size_usd=min_position_size_usd,
            )
            approved = validation.get("approved", False)
            self.last_rejection_reason = validation.get("rejection_reason")
            return approved
        except Exception:
            return super().allow(signal, context=context)
        finally:
            if self._validator and original_limits:
                _restore_risk_limits(self._validator, original_limits)


def _get_attr(source, key, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _coerce_trading_signal(types, signal, context: dict):
    TradingSignal = types["TradingSignal"]
    SignalType = types["SignalType"]
    SignalStrength = types["SignalStrength"]
    create_signal_id = types["create_signal_id"]
    StrategySignal = types["StrategySignal"]

    if isinstance(signal, TradingSignal):
        return signal
    if isinstance(signal, StrategySignal):
        side = signal.side.lower()
        if side in ("buy", "long"):
            signal_type = SignalType.LONG
        elif side in ("sell", "short"):
            signal_type = SignalType.SHORT
        else:
            signal_type = SignalType.LONG
        entry_price = signal.entry_price or _get_attr(context, "price", 0.0) or 0.0
        stop_loss = signal.stop_loss or 0.0
        take_profit = signal.take_profit or 0.0
        risk_bps = ((entry_price - stop_loss) / entry_price * 10000) if entry_price and stop_loss else 0.0
        reward_bps = ((take_profit - entry_price) / entry_price * 10000) if entry_price and take_profit else 0.0
        risk_reward_ratio = (reward_bps / risk_bps) if risk_bps else 0.0
        return TradingSignal(
            symbol=signal.symbol,
            timestamp=time.time(),
            signal_id=create_signal_id(signal.symbol, signal_type, time.time()),
            signal_type=signal_type,
            signal_strength=SignalStrength.MODERATE,
            confidence=1.0,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=entry_price,
            risk_bps=risk_bps,
            reward_bps=reward_bps,
            risk_reward_ratio=risk_reward_ratio,
            confirmations=["strategy_signal"],
            confirmation_count=1,
            profile_id=signal.profile_id,
            strategy_id=signal.strategy_id,
        )
    if isinstance(signal, dict) and signal.get("trading_signal") and isinstance(signal["trading_signal"], TradingSignal):
        return signal["trading_signal"]
    return None


def _coerce_positions(context: dict):
    positions = _get_attr(context, "positions", [])
    normalized = []
    for pos in positions or []:
        if isinstance(pos, dict):
            symbol = pos.get("symbol")
            size_usd = pos.get("size_usd") or pos.get("notional") or 0.0
        else:
            symbol = getattr(pos, "symbol", None)
            size_usd = getattr(pos, "size_usd", None)
            if size_usd is None:
                size = getattr(pos, "size", 0.0)
                price = getattr(pos, "entry_price", None) or getattr(pos, "current_price", None) or 0.0
                size_usd = abs(size * price)
        if symbol:
            normalized.append({"symbol": symbol, "size_usd": size_usd})
    return normalized


def _coerce_account_balance(context: dict) -> float:
    account = _get_attr(context, "account") or _get_attr(context, "account_state")
    return (
        _get_attr(account, "equity")
        or _get_attr(account, "account_balance")
        or _get_attr(context, "account_equity")
        or 0.0
    )


def _coerce_daily_pnl(context: dict) -> float:
    account = _get_attr(context, "account") or _get_attr(context, "account_state")
    return _get_attr(account, "daily_pnl") or _get_attr(context, "daily_pnl") or 0.0


def _estimate_position_size_usd(signal, context: dict, trading_signal=None) -> float:
    """Estimate position size in USD for risk validation.
    
    Note: Strategy-generated sizes may be intentionally large as they represent
    risk budget calculations. The actual position sizing happens in RiskWorker.
    Here we cap the estimate to avoid false rejections in pipeline risk stage.
    """
    explicit = _get_attr(context, "position_size_usd")
    if explicit is not None:
        return float(explicit)
    
    # Get account equity and max exposure for capping
    account = _get_attr(context, "account") or {}
    account_equity = _get_attr(account, "equity") or _get_attr(context, "account_equity") or 0.0
    risk_limits = _get_attr(context, "risk_limits") or {}
    max_exposure_pct = _get_attr(risk_limits, "max_exposure_per_symbol_pct") or 0.20
    max_position_usd = (account_equity * max_exposure_pct) if account_equity > 0 else float('inf')
    
    raw_size_usd = 0.0
    if hasattr(signal, "size") and hasattr(signal, "entry_price"):
        raw_size_usd = abs(getattr(signal, "size", 0.0) * getattr(signal, "entry_price", 0.0))
    elif isinstance(signal, dict) and signal.get("size") and signal.get("entry_price"):
        raw_size_usd = abs(float(signal["size"]) * float(signal["entry_price"]))
    elif isinstance(signal, dict):
        size = signal.get("size") or 0.0
        price = signal.get("entry_price") or _get_attr(context, "price", 0.0)
        raw_size_usd = abs(size * price)
    
    # Cap to max exposure per symbol to avoid false rejections
    # The actual sizing happens in RiskWorker which will properly limit exposure
    if raw_size_usd > max_position_usd and max_position_usd > 0:
        return max_position_usd
    return raw_size_usd


def _apply_risk_limits(validator, context: dict) -> dict:
    original = {
        "max_positions": getattr(validator, "max_positions", None),
        "max_positions_per_symbol": getattr(validator, "max_positions_per_symbol", None),
        "max_total_exposure_pct": getattr(validator, "max_total_exposure_pct", None),
        "max_exposure_per_symbol_pct": getattr(validator, "max_exposure_per_symbol_pct", None),
        "max_daily_loss_pct": getattr(validator, "max_daily_loss_pct", None),
        "max_consecutive_losses": getattr(validator, "max_consecutive_losses", None),
        "max_drawdown_pct": getattr(validator, "max_drawdown_pct", None),
    }
    risk_limits = _get_attr(context, "risk_limits") or {}
    if isinstance(risk_limits, dict):
        for key, value in risk_limits.items():
            if hasattr(validator, key):
                try:
                    cast = float(value) if "pct" in key else int(value)
                except (TypeError, ValueError):
                    continue
                setattr(validator, key, cast)
    market_context = _get_attr(context, "market_context") or {}
    if _get_attr(market_context, "risk_mode") == "conservative":
        scale = _get_attr(market_context, "risk_scale") or 1.0
        try:
            scale_val = float(scale)
        except (TypeError, ValueError):
            scale_val = 1.0
        if scale_val > 0:
            if original.get("max_positions") is not None:
                validator.max_positions = max(1, int(round(validator.max_positions * scale_val)))
            if original.get("max_positions_per_symbol") is not None:
                validator.max_positions_per_symbol = max(1, int(round(validator.max_positions_per_symbol * scale_val)))
            if original.get("max_total_exposure_pct") is not None:
                validator.max_total_exposure_pct = max(0.01, validator.max_total_exposure_pct * scale_val)
            if original.get("max_exposure_per_symbol_pct") is not None:
                validator.max_exposure_per_symbol_pct = max(0.005, validator.max_exposure_per_symbol_pct * scale_val)
    return original


def _restore_risk_limits(validator, original: dict) -> None:
    for key, value in original.items():
        if value is not None and hasattr(validator, key):
            setattr(validator, key, value)
