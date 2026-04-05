"""Strategy registry and signal generation."""

from __future__ import annotations

import time
import logging
import os
from typing import Any, Dict, Optional

from quantgambit.strategies.disable_rules import (
    disabled_mean_reversion_symbols_from_env,
    disabled_strategies_from_env,
    enabled_strategies_by_symbol_from_env,
    is_mean_reversion_strategy,
    is_strategy_disabled_for_symbol,
)


class StrategyRegistry:
    """Minimal strategy registry interface."""

    def generate_signal(self, profile_id: Optional[str], features: Dict) -> bool:
        return bool(features.get("signal"))

    def generate_signal_with_context(self, symbol: str, profile_id: Optional[str], features: Dict, market_context, account):
        return self.generate_signal(profile_id, features)


class DeepTraderStrategyRegistry(StrategyRegistry):
    """Adapter to deeptrader strategy registry when available."""

    def __init__(self):
        try:
            from quantgambit.deeptrader_core.strategies import registry as dt_registry  # type: ignore
            from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry  # type: ignore
            from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal  # type: ignore

            self._strategies = dt_registry.STRATEGIES
            self._profile_registry = get_profile_registry()
            self._types = {
                "Features": Features,
                "AccountState": AccountState,
                "Profile": Profile,
                "StrategySignal": StrategySignal,
            }
        except Exception:
            self._strategies = None
            self._profile_registry = None
            self._types = None
        self._logger = logging.getLogger(__name__)

    def generate_signal(self, profile_id: Optional[str], features: Dict) -> bool:
        if not self._strategies:
            return super().generate_signal(profile_id, features)
        return bool(features.get("signal"))

    def generate_signal_with_context(self, symbol: str, profile_id: Optional[str], features: Dict, market_context, account):
        if not self._strategies or not self._types:
            return super().generate_signal_with_context(symbol, profile_id, features, market_context, account)
        account_state = _build_account_state(self._types["AccountState"], account, market_context)
        feature_snapshot = _build_features(self._types["Features"], symbol, features, market_context)
        if feature_snapshot is None:
            return super().generate_signal_with_context(symbol, profile_id, features, market_context, account)

        # Check session preferences before generating signal (Requirements 5.4, 5.5).
        # Session is evaluated once and applied consistently across fallback attempts.
        session = _get_attr(market_context, "session") or _get_attr(features, "session") or "us"

        disabled_strategies = disabled_strategies_from_env()
        disabled_mean_rev_symbols = disabled_mean_reversion_symbols_from_env()
        enabled_by_symbol = enabled_strategies_by_symbol_from_env()
        attempts: list[dict] = []
        candidate_confirmation_enabled = _candidate_confirmation_enabled()
        selected_profile_id: Optional[str] = profile_id
        profile_attempts = _select_profile_attempt_ids(profile_id, features, market_context)

        if not profile_attempts:
            profile_attempts = [profile_id] if profile_id else []
        if not profile_attempts:
            return super().generate_signal_with_context(symbol, profile_id, features, market_context, account)

        for candidate_profile_id in profile_attempts:
            if not candidate_profile_id:
                continue

            profile = _build_profile(self._types["Profile"], candidate_profile_id, market_context, features)
            if profile is None:
                attempts.append(
                    {
                        "profile_id": candidate_profile_id,
                        "strategy_id": None,
                        "status": "profile_unavailable",
                    }
                )
                continue

            # Strategy selection is profile-scoped. We try strategies in order and skip disabled ones.
            # This avoids routing into a profile and then immediately vetoing due to DISABLE_* envs.
            strategy_ids = _select_strategy_ids(candidate_profile_id, features, market_context, self._profile_registry)
            if not strategy_ids:
                attempts.append(
                    {
                        "profile_id": candidate_profile_id,
                        "strategy_id": None,
                        "status": "no_strategies_for_profile",
                    }
                )
                continue

            for strategy_id in strategy_ids:
                if not strategy_id:
                    continue

                if is_strategy_disabled_for_symbol(
                    strategy_id,
                    symbol,
                    disabled_strategies=disabled_strategies,
                    disabled_mean_rev_symbols=disabled_mean_rev_symbols,
                    enabled_strategies_by_symbol=enabled_by_symbol,
                ):
                    if _trace_registry():
                        if strategy_id in disabled_strategies:
                            self._logger.info(
                                "[%s] strategy_registry: skipping disabled strategy_id=%s profile_id=%s",
                                symbol,
                                strategy_id,
                                candidate_profile_id,
                            )
                        elif is_mean_reversion_strategy(strategy_id) and symbol and symbol.upper() in disabled_mean_rev_symbols:
                            self._logger.info(
                                "[%s] strategy_registry: skipping mean reversion for symbol strategy_id=%s profile_id=%s",
                                symbol,
                                strategy_id,
                                candidate_profile_id,
                            )
                    attempts.append(
                        {
                            "profile_id": candidate_profile_id,
                            "strategy_id": strategy_id,
                            "status": "skipped_disabled",
                        }
                    )
                    continue

                if not _is_strategy_allowed_in_session(strategy_id, session):
                    if _trace_registry():
                        self._logger.info(
                            "[%s] strategy_registry: skipping strategy not allowed in session strategy_id=%s session=%s profile_id=%s",
                            symbol,
                            strategy_id,
                            session,
                            candidate_profile_id,
                        )
                    attempts.append(
                        {
                            "profile_id": candidate_profile_id,
                            "strategy_id": strategy_id,
                            "status": "skipped_session",
                            "session": session,
                        }
                    )
                    continue

                strategy = self._strategies.get(strategy_id)
                if not strategy:
                    if _trace_registry():
                        self._logger.info(
                            "[%s] strategy_registry: missing strategy_id=%s (skipping) profile_id=%s",
                            symbol,
                            strategy_id,
                            candidate_profile_id,
                        )
                    attempts.append(
                        {
                            "profile_id": candidate_profile_id,
                            "strategy_id": strategy_id,
                            "status": "missing",
                        }
                    )
                    continue

                if _trace_registry():
                    self._logger.info(
                        "[%s] strategy_registry: trying strategy_id=%s profile_id=%s session=%s",
                        symbol,
                        strategy_id,
                        candidate_profile_id,
                        session,
                    )

                params = _strategy_params(candidate_profile_id, strategy_id, self._profile_registry)

                # Inject resolved_params and symbol_characteristics into params (Requirements 4.1, 4.2, 4.3)
                # This allows strategies to access symbol-adaptive parameters.
                resolved_params = _get_attr(features, "resolved_params")
                symbol_characteristics = _get_attr(features, "symbol_characteristics")

                if resolved_params is not None:
                    params["resolved_params"] = resolved_params
                    # Also include original multipliers for debugging (Requirement 4.2)
                    if hasattr(resolved_params, "poc_distance_multiplier"):
                        params["_poc_distance_multiplier"] = resolved_params.poc_distance_multiplier
                    if hasattr(resolved_params, "spread_multiplier"):
                        params["_spread_multiplier"] = resolved_params.spread_multiplier
                    if hasattr(resolved_params, "depth_multiplier"):
                        params["_depth_multiplier"] = resolved_params.depth_multiplier
                    if hasattr(resolved_params, "stop_loss_multiplier"):
                        params["_stop_loss_multiplier"] = resolved_params.stop_loss_multiplier
                    if hasattr(resolved_params, "take_profit_multiplier"):
                        params["_take_profit_multiplier"] = resolved_params.take_profit_multiplier

                if symbol_characteristics is not None:
                    params["symbol_characteristics"] = symbol_characteristics

                candidate = None
                confirmation_reason: Optional[str] = None
                if candidate_confirmation_enabled and hasattr(strategy, "generate_candidate"):
                    try:
                        candidate = strategy.generate_candidate(feature_snapshot, account_state, profile, params)
                    except Exception as exc:
                        attempts.append(
                            {
                                "profile_id": candidate_profile_id,
                                "strategy_id": strategy_id,
                                "status": "candidate_error",
                                "error_type": type(exc).__name__,
                            }
                        )
                        if _trace_registry():
                            self._logger.exception(
                                "[%s] strategy_registry: candidate generation error strategy_id=%s profile_id=%s",
                                symbol,
                                strategy_id,
                                candidate_profile_id,
                            )
                        continue
                    if candidate is not None:
                        confirmed, confirmation_reason = _confirm_candidate(candidate, features, market_context)
                        if not confirmed:
                            attempts.append(
                                {
                                    "profile_id": candidate_profile_id,
                                    "strategy_id": strategy_id,
                                    "status": "candidate_rejected",
                                    "reason": confirmation_reason,
                                }
                            )
                            if _trace_registry():
                                self._logger.info(
                                    "[%s] strategy_registry: candidate rejected strategy_id=%s profile_id=%s reason=%s",
                                    symbol,
                                    strategy_id,
                                    candidate_profile_id,
                                    confirmation_reason,
                                )
                            continue

                try:
                    signal = strategy.generate_signal(feature_snapshot, account_state, profile, params)
                except Exception as exc:
                    # Strategy bugs should not crash the pipeline; record and move on.
                    attempts.append(
                        {
                            "profile_id": candidate_profile_id,
                            "strategy_id": strategy_id,
                            "status": "error",
                            "error_type": type(exc).__name__,
                        }
                    )
                    if _trace_registry():
                        self._logger.exception(
                            "[%s] strategy_registry: error in strategy_id=%s profile_id=%s",
                            symbol,
                            strategy_id,
                            candidate_profile_id,
                        )
                    continue
                if signal is None and candidate is not None:
                    signal = _candidate_to_strategy_signal(candidate, features, market_context, account, params, confirmation_reason)

                if signal is None:
                    if _trace_registry():
                        self._logger.info(
                            "[%s] strategy_registry: no signal from strategy_id=%s profile_id=%s",
                            symbol,
                            strategy_id,
                            candidate_profile_id,
                        )
                    attempts.append(
                        {
                            "profile_id": candidate_profile_id,
                            "strategy_id": strategy_id,
                            "status": "no_signal",
                        }
                    )
                    continue

                attempts.append(
                    {
                        "profile_id": candidate_profile_id,
                        "strategy_id": strategy_id,
                        "status": "signal",
                    }
                )
                selected_profile_id = candidate_profile_id
                signal = _apply_risk_scale(signal, market_context)
                if isinstance(signal, dict):
                    if selected_profile_id:
                        signal.setdefault("profile_id", selected_profile_id)
                elif hasattr(signal, "profile_id") and not signal.profile_id:
                    signal.profile_id = selected_profile_id
                # Enrich signal with time budget parameters from profile
                signal = _enrich_signal_with_time_budget(signal, selected_profile_id, self._profile_registry)
                return signal

            # If this profile produced no signal, continue to next candidate profile.
            if _trace_registry():
                self._logger.info(
                    "[%s] strategy_registry: profile produced no signal, trying fallback profile profile_id=%s",
                    symbol,
                    candidate_profile_id,
                )

        # No strategy produced a signal across all profile attempts; fall back to legacy behavior.
        try:
            if isinstance(features, dict):
                features["_strategy_attempts"] = attempts[:20]
                features["_profile_attempts"] = profile_attempts[:8]
        except Exception:
            pass
        return super().generate_signal_with_context(symbol, profile_id, features, market_context, account)


def _get_attr(source, key, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _trace_registry() -> bool:
    return os.getenv("DECISION_GATE_TRACE_VERBOSE", "false").lower() in {"1", "true", "yes"}


def _build_features(Features, symbol: str, features: Dict, market_context):
    price = _get_attr(features, "price") or _get_attr(market_context, "price") or _get_attr(features, "last")
    spread = _get_attr(features, "spread") or _get_attr(market_context, "spread")
    if spread is None:
        spread_bps = _get_attr(features, "spread_bps") or _get_attr(market_context, "spread_bps")
        if spread_bps is not None:
            spread = (spread_bps / 10000.0) * price if price else 0.0
    if spread is None:
        spread = 0.0
    rotation_factor = _get_attr(features, "rotation_factor") or _get_attr(market_context, "rotation_factor") or 0.0
    position_in_value = (
        _get_attr(features, "position_in_value")
        or _get_attr(market_context, "position_in_value")
        or "inside"
    )
    if price is None:
        return None
    vwap = _get_attr(features, "vwap") or _get_attr(market_context, "vwap") or 0.0
    point_of_control = _get_attr(features, "point_of_control") or _get_attr(market_context, "point_of_control")
    orderflow_imbalance = _get_attr(features, "orderflow_imbalance")
    if orderflow_imbalance is None:
        orderflow_imbalance = _get_attr(market_context, "orderflow_imbalance")
    return Features(
        symbol=symbol,
        price=price,
        spread=spread,
        rotation_factor=rotation_factor,
        position_in_value=position_in_value,
        timestamp=_get_attr(features, "timestamp") or _get_attr(market_context, "timestamp") or time.time(),
        distance_to_val=_get_attr(features, "distance_to_val")
        or _get_attr(market_context, "distance_to_val")
        or _get_attr(features, "distance_to_val_pct")
        or _get_attr(market_context, "distance_to_val_pct"),
        distance_to_vah=_get_attr(features, "distance_to_vah")
        or _get_attr(market_context, "distance_to_vah")
        or _get_attr(features, "distance_to_vah_pct")
        or _get_attr(market_context, "distance_to_vah_pct"),
        distance_to_poc=_get_attr(features, "distance_to_poc")
        or _get_attr(market_context, "distance_to_poc")
        or _get_attr(features, "distance_to_poc_pct")
        or _get_attr(market_context, "distance_to_poc_pct"),
        value_area_low=_get_attr(features, "value_area_low") or _get_attr(market_context, "value_area_low"),
        value_area_high=_get_attr(features, "value_area_high") or _get_attr(market_context, "value_area_high"),
        point_of_control=point_of_control,
        ema_fast_15m=_get_attr(features, "ema_fast_15m") or _get_attr(market_context, "ema_fast_15m") or 0.0,
        ema_slow_15m=_get_attr(features, "ema_slow_15m") or _get_attr(market_context, "ema_slow_15m") or 0.0,
        atr_5m=_get_attr(features, "atr_5m") or _get_attr(market_context, "atr_5m") or 0.0,
        atr_5m_baseline=_get_attr(features, "atr_5m_baseline") or _get_attr(market_context, "atr_5m_baseline") or 0.0,
        vwap=vwap,
        trades_per_second=_get_attr(features, "trades_per_second")
        or _get_attr(market_context, "trades_per_second")
        or 0.0,
        orderbook_imbalance=_get_attr(features, "orderbook_imbalance")
        or _get_attr(market_context, "orderbook_imbalance")
        or 0.0,
        orderflow_imbalance=orderflow_imbalance,
        bid_depth_usd=_get_attr(features, "bid_depth_usd") or _get_attr(market_context, "bid_depth_usd") or 0.0,
        ask_depth_usd=_get_attr(features, "ask_depth_usd") or _get_attr(market_context, "ask_depth_usd") or 0.0,
    )


def _build_profile(Profile, profile_id: Optional[str], market_context, features: Dict):
    if profile_id is None:
        profile_id = _get_attr(market_context, "profile_id") or _get_attr(features, "profile_id")
    if profile_id is None:
        return None
    return Profile(
        id=profile_id,
        trend=_get_attr(market_context, "trend_direction")
        or _get_attr(features, "trend_direction")
        or "flat",
        volatility=_get_attr(market_context, "volatility_regime")
        or _get_attr(features, "volatility_regime")
        or "normal",
        value_location=_get_attr(market_context, "position_in_value")
        or _get_attr(features, "position_in_value")
        or "inside",
        session=_get_attr(market_context, "session") or _get_attr(features, "session") or "us",
        risk_mode=_get_attr(market_context, "risk_mode") or _get_attr(features, "risk_mode") or "normal",
    )


def _build_account_state(AccountState, account, market_context):
    equity = _get_attr(account, "equity") or _get_attr(account, "account_balance") or _get_attr(market_context, "account_equity") or 0.0
    daily_pnl = _get_attr(account, "daily_pnl") or _get_attr(market_context, "daily_pnl") or 0.0
    max_daily_loss = _get_attr(account, "max_daily_loss") or abs(_get_attr(account, "max_daily_loss_pct") or 0.0)
    open_positions = _get_attr(account, "open_positions") or _get_attr(market_context, "open_positions") or 0
    symbol_open_positions = _get_attr(account, "symbol_open_positions") or 0
    symbol_daily_pnl = _get_attr(account, "symbol_daily_pnl") or 0.0
    return AccountState(
        equity=equity,
        daily_pnl=daily_pnl,
        max_daily_loss=max_daily_loss,
        open_positions=open_positions,
        symbol_open_positions=symbol_open_positions,
        symbol_daily_pnl=symbol_daily_pnl,
    )


def _select_strategy_id(profile_id: Optional[str], features: Dict, market_context, profile_registry):
    strategy_id = _get_attr(features, "strategy_id") or _get_attr(market_context, "strategy_id")
    if strategy_id:
        return strategy_id
    if profile_registry and profile_id:
        spec = profile_registry.get_spec(profile_id)
        if spec and spec.strategy_ids:
            return spec.strategy_ids[0]
    return None


def _candidate_confirmation_enabled() -> bool:
    return os.getenv("ENABLE_CANDIDATE_CONFIRMATION", "false").lower() in {"1", "true", "yes"}


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flow_from_context(features: Dict, market_context) -> float:
    candidates = [
        _get_attr(market_context, "flow_rotation"),
        _get_attr(features, "flow_rotation"),
        _get_attr(market_context, "rotation_factor"),
        _get_attr(features, "rotation_factor"),
        _get_attr(market_context, "orderflow_imbalance"),
        _get_attr(features, "orderflow_imbalance"),
    ]
    for value in candidates:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return 0.0


def _trend_bias_from_context(features: Dict, market_context) -> float:
    bias = _to_float(_get_attr(market_context, "trend_bias"))
    if bias is not None:
        return bias
    bias = _to_float(_get_attr(features, "trend_bias"))
    if bias is not None:
        return bias
    direction = str(
        _get_attr(market_context, "trend_direction")
        or _get_attr(features, "trend_direction")
        or ""
    ).lower()
    strength = _to_float(
        _get_attr(market_context, "trend_strength", _get_attr(features, "trend_strength", 0.0)),
        0.0,
    )
    if direction in {"up", "long", "bullish"}:
        return abs(strength or 0.0)
    if direction in {"down", "short", "bearish"}:
        return -abs(strength or 0.0)
    return 0.0


def _confirm_candidate(candidate: Any, features: Dict, market_context) -> tuple[bool, str]:
    flow = _flow_from_context(features, market_context)
    trend = _trend_bias_from_context(features, market_context)
    min_flow = _to_float(os.getenv("CANDIDATE_CONFIRM_MIN_FLOW_MAGNITUDE", "0.5"), 0.5) or 0.5
    strategy_id = str(getattr(candidate, "strategy_id", "")).lower()
    flow_optional_strategies = {"spot_mean_reversion", "spot_dip_accumulator"}
    flow_check_required = getattr(candidate, "requires_flow_reversal", True)
    if strategy_id in flow_optional_strategies:
        flow_check_required = False

    if flow_check_required:
        flow_required = getattr(candidate, "flow_direction_required", None)
        side = str(getattr(candidate, "side", "")).lower()
        if flow_required == "positive":
            if flow < min_flow:
                return False, f"flow_not_positive (flow={flow:.2f}<{min_flow})"
        elif flow_required == "negative":
            if flow > -min_flow:
                return False, f"flow_not_negative (flow={flow:.2f}>-{min_flow})"
        elif side == "long":
            if flow < min_flow:
                return False, f"flow_not_positive_for_long (flow={flow:.2f}<{min_flow})"
        elif side == "short":
            if flow > -min_flow:
                return False, f"flow_not_negative_for_short (flow={flow:.2f}>-{min_flow})"

    max_adverse = _to_float(getattr(candidate, "max_adverse_trend_bias", 0.5), 0.5) or 0.5
    side = str(getattr(candidate, "side", "")).lower()
    if side == "long" and trend < -max_adverse:
        return False, f"trend_too_bearish (trend={trend:.2f}<-{max_adverse})"
    if side == "short" and trend > max_adverse:
        return False, f"trend_too_bullish (trend={trend:.2f}>{max_adverse})"

    return True, f"candidate_confirmed flow={flow:.2f},trend={trend:.2f}"


def _candidate_to_strategy_signal(
    candidate: Any,
    features: Dict,
    market_context,
    account,
    params: Dict[str, Any],
    confirmation_reason: Optional[str],
):
    mid_price = (
        _to_float(_get_attr(market_context, "mid_price"))
        or _to_float(_get_attr(features, "price"))
        or _to_float(_get_attr(market_context, "price"))
        or _to_float(getattr(candidate, "entry_price", None))
        or 0.0
    )
    try:
        normalized = candidate.normalize(mid_price)
    except Exception:
        return None

    equity = _to_float(_get_attr(account, "equity"), 0.0) or 0.0
    risk_per_trade_pct = _to_float(params.get("risk_per_trade_pct"), 0.01) or 0.01
    stop_price = _to_float(getattr(normalized, "sl_price", None), None)
    entry_price = _to_float(getattr(normalized, "entry_price", None), None)
    stop_distance = abs((entry_price or 0.0) - (stop_price or 0.0))
    if equity > 0 and stop_distance > 0:
        size = (equity * risk_per_trade_pct) / stop_distance
    else:
        size = _to_float(os.getenv("CANDIDATE_CONFIRM_DEFAULT_SIZE", "0.01"), 0.01) or 0.01
    try:
        return normalized.to_strategy_signal(
            size=size,
            confirmation_reason=confirmation_reason or "candidate_confirmed",
        )
    except Exception:
        return None


def _select_strategy_ids(profile_id: Optional[str], features: Dict, market_context, profile_registry):
    """
    Return the ordered strategy candidate list for this decision.

    Rules:
    - If strategy_id is explicitly provided in features/market_context, use only that.
    - Else use profile.spec.strategy_ids in defined order.
    """
    strategy_id = _get_attr(features, "strategy_id") or _get_attr(market_context, "strategy_id")
    if strategy_id:
        return [strategy_id]
    if profile_registry and profile_id:
        spec = profile_registry.get_spec(profile_id)
        if spec and spec.strategy_ids:
            return list(spec.strategy_ids)
    return []


def _select_profile_attempt_ids(profile_id: Optional[str], features: Dict, market_context) -> list[str]:
    """
    Return ordered profile IDs to attempt for signal generation.

    The first profile is always the router-selected profile when available.
    Optional fallback profiles are read from `profile_scores` (router output),
    bounded by PROFILE_SIGNAL_FALLBACK_MAX_PROFILES.
    """
    selected = (profile_id or "").strip()
    try:
        max_profiles = int(os.getenv("PROFILE_SIGNAL_FALLBACK_MAX_PROFILES", "2"))
    except (TypeError, ValueError):
        max_profiles = 2
    if max_profiles < 1:
        max_profiles = 1
    if max_profiles > 5:
        max_profiles = 5

    ordered: list[str] = []
    seen: set[str] = set()

    def _push(pid: Optional[str]) -> None:
        if not pid:
            return
        key = str(pid).strip()
        if not key or key in seen:
            return
        seen.add(key)
        ordered.append(key)

    scores = _get_attr(features, "profile_scores") or _get_attr(market_context, "profile_scores") or []
    score_entries = scores if isinstance(scores, list) else []
    top_scored_selected: Optional[str] = None
    if score_entries:
        first = score_entries[0]
        if isinstance(first, dict):
            top_scored_selected = str(first.get("profile_id") or "").strip() or None
        else:
            top_scored_selected = str(_get_attr(first, "profile_id") or "").strip() or None

    _push(top_scored_selected)
    _push(selected)
    if score_entries:
        for entry in score_entries:
            if len(ordered) >= max_profiles:
                break
            if isinstance(entry, dict):
                pid = entry.get("profile_id")
                eligible = entry.get("eligible", True)
            else:
                pid = _get_attr(entry, "profile_id")
                eligible = _get_attr(entry, "eligible", True)
            if eligible is False:
                continue
            _push(pid)

    return ordered


def _strategy_params(profile_id: Optional[str], strategy_id: str, profile_registry) -> Dict:
    if not profile_registry or not profile_id:
        return {}
    spec = profile_registry.get_spec(profile_id)
    if not spec:
        return {}
    
    # Start with profile's risk parameters as base
    params = {}
    if spec.risk:
        params["risk_per_trade_pct"] = spec.risk.risk_per_trade_pct
        params["max_leverage"] = spec.risk.max_leverage
        params["stop_loss_pct"] = spec.risk.stop_loss_pct
        if spec.risk.take_profit_pct is not None:
            params["take_profit_pct"] = spec.risk.take_profit_pct
        if spec.risk.max_hold_time_seconds is not None:
            params["max_hold_time_seconds"] = spec.risk.max_hold_time_seconds
        if spec.risk.min_hold_time_seconds is not None:
            params["min_hold_time_seconds"] = spec.risk.min_hold_time_seconds
        # Time budget params for MFT scalping
        if spec.risk.time_to_work_sec is not None:
            params["time_to_work_sec"] = spec.risk.time_to_work_sec
        if spec.risk.mfe_min_bps is not None:
            params["mfe_min_bps"] = spec.risk.mfe_min_bps
        if spec.risk.expected_horizon_sec is not None:
            params["expected_horizon_sec"] = spec.risk.expected_horizon_sec

    # Inject profile condition hints into strategy params (soft alignment)
    # This keeps router conditions and strategy thresholds consistent.
    if spec.conditions:
        cond = spec.conditions
        # Spread threshold (decimal, e.g., 0.002 = 20 bps)
        if cond.max_spread is not None and "max_spread" not in params:
            params["max_spread"] = cond.max_spread
        # Rotation threshold alignment
        if cond.min_rotation_factor is not None:
            rotation_threshold_strategies = {
                "breakout_scalp",
                "poc_magnet_scalp",
                "vwap_reversion",
                "asia_range_scalp",
                "europe_open_vol",
                "overnight_thin",
                "amt_value_area_rejection_scalp",
            }
            min_rotation_strategies = {
                "vol_expansion",
                "high_vol_breakout",
                "us_open_momentum",
                "opening_range_breakout",
                "trend_pullback",
                "spread_compression",
                "liquidity_hunt",
            }
            if strategy_id in rotation_threshold_strategies and "rotation_threshold" not in params:
                params["rotation_threshold"] = abs(cond.min_rotation_factor)
            if strategy_id in min_rotation_strategies and "min_rotation_factor" not in params:
                params["min_rotation_factor"] = abs(cond.min_rotation_factor)
    
    # Override with strategy-specific params (if any)
    strategy_specific = spec.strategy_params.get(strategy_id, {})
    params.update(strategy_specific)
    
    return params


def _apply_risk_scale(signal, market_context):
    risk_mode = _get_attr(market_context, "risk_mode")
    if risk_mode != "conservative":
        return signal
    scale = _get_attr(market_context, "risk_scale", 1.0)
    try:
        scale_val = float(scale)
    except (TypeError, ValueError):
        return signal
    if scale_val <= 0:
        return signal
    if isinstance(signal, dict) and "size" in signal:
        try:
            signal["size"] = float(signal["size"]) * scale_val
        except (TypeError, ValueError):
            return signal
        return signal
    if hasattr(signal, "size"):
        try:
            signal.size = float(signal.size) * scale_val
        except (TypeError, ValueError):
            return signal
    return signal


def _enrich_signal_with_time_budget(signal, profile_id: Optional[str], profile_registry):
    """
    Enrich signal with time budget parameters from profile.
    
    This ensures exit evaluation has access to:
    - time_to_work_sec: T_work - time to first progress
    - max_hold_sec: Max hold time before stale exit
    - mfe_min_bps: Min favorable excursion expected quickly
    - expected_horizon_sec: How long signal is expected to be valid
    """
    if not profile_registry or not profile_id:
        return signal
    spec = profile_registry.get_spec(profile_id)
    if not spec or not spec.risk:
        return signal
    
    risk = spec.risk
    
    # Set time budget params on signal if not already set
    # Strategies may return either a dict payload or a StrategySignal object.
    # Exit evaluation relies on these fields being present in either case.
    if isinstance(signal, dict):
        if signal.get("time_to_work_sec") is None and risk.time_to_work_sec is not None:
            signal["time_to_work_sec"] = risk.time_to_work_sec
        if signal.get("max_hold_sec") is None and signal.get("max_hold_time_seconds") is None and risk.max_hold_time_seconds is not None:
            signal["max_hold_sec"] = risk.max_hold_time_seconds
        if signal.get("mfe_min_bps") is None and risk.mfe_min_bps is not None:
            signal["mfe_min_bps"] = risk.mfe_min_bps
        if signal.get("expected_horizon_sec") is None and risk.expected_horizon_sec is not None:
            signal["expected_horizon_sec"] = risk.expected_horizon_sec
        return signal

    if hasattr(signal, "time_to_work_sec") and signal.time_to_work_sec is None:
        if risk.time_to_work_sec is not None:
            signal.time_to_work_sec = risk.time_to_work_sec
    
    if hasattr(signal, "max_hold_sec") and signal.max_hold_sec is None:
        if risk.max_hold_time_seconds is not None:
            signal.max_hold_sec = risk.max_hold_time_seconds
    
    if hasattr(signal, "mfe_min_bps") and signal.mfe_min_bps is None:
        if risk.mfe_min_bps is not None:
            signal.mfe_min_bps = risk.mfe_min_bps
    
    if hasattr(signal, "expected_horizon_sec") and signal.expected_horizon_sec is None:
        if risk.expected_horizon_sec is not None:
            signal.expected_horizon_sec = risk.expected_horizon_sec
    
    return signal


def _is_strategy_allowed_in_session(strategy_id: str, session: str) -> bool:
    """
    Check if a strategy is allowed in the current session.
    
    Uses STRATEGY_SESSION_PREFERENCES from session_risk module.
    If a strategy is not in the preferences dict, it's allowed in all sessions.
    
    Args:
        strategy_id: The strategy identifier
        session: Current trading session ("asia", "europe", "us", "overnight")
    
    Returns:
        True if strategy is allowed, False otherwise
    
    Requirements 5.4, 5.5: Strategies can define preferred_sessions
    and the system checks session match before signal generation.
    """
    try:
        from quantgambit.signals.stages.session_risk import is_strategy_allowed_in_session
        return is_strategy_allowed_in_session(strategy_id, session)
    except ImportError:
        # If session_risk module not available, allow all strategies
        return True
