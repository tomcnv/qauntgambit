"""Signal confirmation compatibility layer.

Legacy layer2 confirmation now supports an adapter path into the unified
confirmation policy engine. Set `ENABLE_LEGACY_CONFIRMATION_ADAPTER=true`
to evaluate using unified policy while preserving old API shape.
"""

from __future__ import annotations

import os
import warnings
from typing import List, Tuple

from quantgambit.deeptrader_core.layer1_predictions import MarketContext
from quantgambit.signals.confirmation import ConfirmationPolicyEngine

from .trading_signal import SignalType


class SignalConfirmation:
    """Multi-factor signal confirmation with unified-policy adapter support."""

    def __init__(self):
        self.min_trend_confidence = 0.5
        self.min_regime_confidence = 0.5
        self.min_orderflow_confidence = 0.3
        self._use_adapter = os.getenv("ENABLE_LEGACY_CONFIRMATION_ADAPTER", "true").lower() in {"1", "true", "yes"}
        self._policy_engine = ConfirmationPolicyEngine()
        warnings.warn(
            "deeptrader_core.layer2_signals.signal_confirmation is deprecated; use signals.confirmation policy engine",
            DeprecationWarning,
            stacklevel=2,
        )

    def confirm_long_signal(self, context: MarketContext) -> Tuple[List[str], int]:
        if self._use_adapter:
            trend = context.trend_confidence if context.trend_bias == "long" else -context.trend_confidence
            result = self._policy_engine.evaluate_entry(
                side="long",
                flow=float(context.rotation_factor or context.orderflow_imbalance or 0.0),
                trend=float(trend),
                market_context=context.to_dict(),
                strategy_id="legacy_layer2",
                requires_flow_reversal=True,
                required_flow_direction="positive",
                max_adverse_trend=self.min_trend_confidence,
            )
            confirmations = result.passed_evidence or result.decision_reason_codes
            return confirmations, len(confirmations)
        return self._legacy_confirm_long_signal(context)

    def confirm_short_signal(self, context: MarketContext) -> Tuple[List[str], int]:
        if self._use_adapter:
            trend = context.trend_confidence if context.trend_bias == "short" else -context.trend_confidence
            result = self._policy_engine.evaluate_entry(
                side="short",
                flow=float(context.rotation_factor or context.orderflow_imbalance or 0.0),
                trend=float(trend),
                market_context=context.to_dict(),
                strategy_id="legacy_layer2",
                requires_flow_reversal=True,
                required_flow_direction="negative",
                max_adverse_trend=self.min_trend_confidence,
            )
            confirmations = result.passed_evidence or result.decision_reason_codes
            return confirmations, len(confirmations)
        return self._legacy_confirm_short_signal(context)

    def confirm_close_signal(
        self,
        context: MarketContext,
        position_side: str,
        entry_price: float,
    ) -> Tuple[List[str], int]:
        if self._use_adapter:
            current_price = float(context.price)
            if position_side == "long":
                pnl_pct = ((current_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
            else:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
            result = self._policy_engine.evaluate_exit_non_emergency(
                side=position_side,
                pnl_pct=pnl_pct,
                current_price=current_price,
                entry_price=entry_price,
                market_context=context.to_dict(),
                strategy_id="legacy_layer2",
            )
            confirmations = result.passed_evidence or result.decision_reason_codes
            return confirmations, len(confirmations)
        return self._legacy_confirm_close_signal(context, position_side, entry_price)

    def _legacy_confirm_long_signal(self, context: MarketContext) -> Tuple[List[str], int]:
        confirmations = []
        if context.trend_bias == "long" and context.trend_confidence >= self.min_trend_confidence:
            confirmations.append(f"trend_long (conf={context.trend_confidence:.2f})")
        if context.volatility_regime in ["normal", "low"]:
            confirmations.append(f"volatility_{context.volatility_regime}")
        if context.liquidity_regime in ["deep", "normal"]:
            confirmations.append(f"liquidity_{context.liquidity_regime}")
        if context.market_regime in ["breakout", "range"] and context.regime_confidence >= self.min_regime_confidence:
            confirmations.append(f"regime_{context.market_regime} (conf={context.regime_confidence:.2f})")
        if context.orderflow_imbalance > 0 and context.orderflow_confidence >= self.min_orderflow_confidence:
            confirmations.append(f"orderflow_buy (imb={context.orderflow_imbalance:+.2f})")
        if context.position_in_value in ["below", "inside"]:
            confirmations.append(f"price_position_{context.position_in_value}")
        if 0.2 <= context.volatility_percentile <= 0.8:
            confirmations.append(f"volatility_percentile_normal ({context.volatility_percentile:.2f})")
        return confirmations, len(confirmations)

    def _legacy_confirm_short_signal(self, context: MarketContext) -> Tuple[List[str], int]:
        confirmations = []
        if context.trend_bias == "short" and context.trend_confidence >= self.min_trend_confidence:
            confirmations.append(f"trend_short (conf={context.trend_confidence:.2f})")
        if context.volatility_regime in ["normal", "low"]:
            confirmations.append(f"volatility_{context.volatility_regime}")
        if context.liquidity_regime in ["deep", "normal"]:
            confirmations.append(f"liquidity_{context.liquidity_regime}")
        if context.market_regime in ["breakout", "range"] and context.regime_confidence >= self.min_regime_confidence:
            confirmations.append(f"regime_{context.market_regime} (conf={context.regime_confidence:.2f})")
        if context.orderflow_imbalance < 0 and context.orderflow_confidence >= self.min_orderflow_confidence:
            confirmations.append(f"orderflow_sell (imb={context.orderflow_imbalance:+.2f})")
        if context.position_in_value in ["above", "inside"]:
            confirmations.append(f"price_position_{context.position_in_value}")
        if 0.2 <= context.volatility_percentile <= 0.8:
            confirmations.append(f"volatility_percentile_normal ({context.volatility_percentile:.2f})")
        return confirmations, len(confirmations)

    def _legacy_confirm_close_signal(
        self,
        context: MarketContext,
        position_side: str,
        entry_price: float,
    ) -> Tuple[List[str], int]:
        confirmations = []
        current_price = context.price

        if position_side == "long":
            if context.trend_bias == "short" and context.trend_confidence >= self.min_trend_confidence:
                confirmations.append(f"trend_reversal_short (conf={context.trend_confidence:.2f})")
            if context.orderflow_imbalance < -0.3:
                confirmations.append(f"orderflow_reversal (imb={context.orderflow_imbalance:+.2f})")
            if context.distance_to_vah_pct < 0.001:
                confirmations.append("price_at_resistance_vah")
            if context.volatility_regime == "high" and context.volatility_percentile > 0.9:
                confirmations.append(f"volatility_spike (pct={context.volatility_percentile:.2f})")
            if current_price > entry_price:
                pnl_pct = (current_price - entry_price) / entry_price
                if pnl_pct > 0.005:
                    confirmations.append(f"profit_target_reached ({pnl_pct:.2%})")

        elif position_side == "short":
            if context.trend_bias == "long" and context.trend_confidence >= self.min_trend_confidence:
                confirmations.append(f"trend_reversal_long (conf={context.trend_confidence:.2f})")
            if context.orderflow_imbalance > 0.3:
                confirmations.append(f"orderflow_reversal (imb={context.orderflow_imbalance:+.2f})")
            if context.distance_to_val_pct < 0.001:
                confirmations.append("price_at_support_val")
            if context.volatility_regime == "high" and context.volatility_percentile > 0.9:
                confirmations.append(f"volatility_spike (pct={context.volatility_percentile:.2f})")
            if current_price < entry_price:
                pnl_pct = (entry_price - current_price) / entry_price
                if pnl_pct > 0.005:
                    confirmations.append(f"profit_target_reached ({pnl_pct:.2%})")

        return confirmations, len(confirmations)


def confirm_signal(
    signal_type: SignalType,
    context: MarketContext,
    position_side: str = None,
    entry_price: float = None,
) -> Tuple[List[str], int]:
    confirmer = SignalConfirmation()

    if signal_type == SignalType.LONG:
        return confirmer.confirm_long_signal(context)

    if signal_type == SignalType.SHORT:
        return confirmer.confirm_short_signal(context)

    if signal_type in [SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT]:
        if position_side is None or entry_price is None:
            return [], 0
        return confirmer.confirm_close_signal(context, position_side, entry_price)

    return [], 0
