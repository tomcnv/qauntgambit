"""Liquidity Fade Scalp Strategy

Theory:
Liquidation cascades and stop-hunts cause rapid price displacement that
overshoots fair value. Once the aggressive flow exhausts, price reverts.
This strategy waits for the exhaustion signal and fades the move.

Entry Logic:
- Rapid price move (>threshold bps in <30 seconds)
- Volume spike confirms the cascade
- Orderflow reversal detected (aggressor exhaustion)
- Enter reversion via limit order

Exit Logic:
- TP: 50% retracement of the rapid move
- SL: new extreme + buffer
- Max hold: 120 seconds

Triggers 2-5 times per day — quality over quantity.
"""

from typing import Optional, Dict, Any
import os

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class LiquidityFadeScalp(Strategy):
    strategy_id = "liquidity_fade_scalp"

    DEFAULT_MIN_MOVE_BPS = 12.0
    DEFAULT_MIN_TRADES_PER_SEC = 3.0
    DEFAULT_REVERSAL_THRESHOLD = 0.2  # imbalance must flip by this much
    DEFAULT_TP_RETRACE_FRACTION = 0.5
    DEFAULT_SL_BUFFER_BPS = 5.0
    DEFAULT_MAX_HOLD_SEC = 120.0
    DEFAULT_MIN_EDGE_BPS = float(os.getenv("STRATEGY_MIN_EDGE_BPS", "6.0"))

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        min_move_bps = params.get("min_move_bps", self.DEFAULT_MIN_MOVE_BPS)
        min_tps = params.get("min_trades_per_sec", self.DEFAULT_MIN_TRADES_PER_SEC)
        reversal_thresh = params.get("reversal_threshold", self.DEFAULT_REVERSAL_THRESHOLD)
        tp_retrace = params.get("tp_retrace_fraction", self.DEFAULT_TP_RETRACE_FRACTION)
        sl_buffer_bps = params.get("sl_buffer_bps", self.DEFAULT_SL_BUFFER_BPS)
        max_hold_sec = params.get("max_hold_sec", self.DEFAULT_MAX_HOLD_SEC)
        min_edge_bps = params.get("min_edge_bps", self.DEFAULT_MIN_EDGE_BPS)
        fee_bps = params.get("fee_bps", 0.0)  # maker entry
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.005)

        if features.price is None or features.price <= 0:
            return None

        # --- detect rapid move ---
        # price_change_30s is the 30-second price change
        move_30s = getattr(features, "price_change_30s", None)
        if move_30s is None:
            return None
        move_bps = abs(move_30s) * 10_000  # convert ratio to bps
        if move_bps < min_move_bps:
            return None  # no cascade

        # --- volume confirmation ---
        tps = getattr(features, "trades_per_second", None)
        if tps is None or tps < min_tps:
            return None  # no volume spike

        # --- orderflow reversal ---
        # imb_1s = very recent flow, imb_30s = flow during the cascade
        imb_1s = getattr(features, "imb_1s", None)
        imb_30s = getattr(features, "imb_30s", None)
        if imb_1s is None or imb_30s is None:
            return None

        # Reversal = recent flow has flipped vs cascade flow
        flow_delta = imb_1s - imb_30s
        if abs(flow_delta) < reversal_thresh:
            return None  # aggressor hasn't exhausted yet

        # --- direction: fade the cascade ---
        # If price dropped (move_30s < 0), cascade was selling → go LONG
        # If price rose (move_30s > 0), cascade was buying → go SHORT
        if move_30s < 0 and flow_delta > reversal_thresh:
            side = "long"
        elif move_30s > 0 and flow_delta < -reversal_thresh:
            side = "short"
        else:
            return None  # flow reversal doesn't match move direction

        # --- entry/exit ---
        move_abs = abs(move_30s) * features.price
        sl_buffer = sl_buffer_bps / 10_000 * features.price

        if side == "long":
            entry = features.price  # limit at current (post-cascade) price
            tp = entry + move_abs * tp_retrace
            sl = entry - move_abs * 0.3 - sl_buffer  # below cascade low + buffer
        else:
            entry = features.price
            tp = entry - move_abs * tp_retrace
            sl = entry + move_abs * 0.3 + sl_buffer

        # --- edge check ---
        profit_bps = abs(tp - entry) / features.price * 10_000
        net_edge = profit_bps - fee_bps
        if net_edge < min_edge_bps:
            return None

        size = risk_per_trade_pct * account.equity / features.price

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=features.symbol,
            side=side,
            size=size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            meta_reason=(
                f"liq_fade: move={move_bps:.0f}bps flow_delta={flow_delta:.2f} "
                f"side={side} edge={net_edge:.1f}bps"
            ),
            profile_id=profile.id if hasattr(profile, "id") else "liquidity_fade_profile",
            expected_horizon_sec=max_hold_sec,
            time_to_work_sec=30.0,
            max_hold_sec=max_hold_sec,
            mfe_min_bps=profit_bps * 0.25,
        )
