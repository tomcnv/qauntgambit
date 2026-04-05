"""Spread Capture Scalp Strategy

Theory:
Instead of predicting direction, fade aggressive orderflow imbalance.
When one side aggressively hits the book, price temporarily displaces
from fair value and reverts within seconds.

Entry Logic:
- Orderflow imbalance spike (|imbalance| > threshold)
- Enter OPPOSITE to the aggressor via limit order at best bid/ask
- Spread must be tight enough to capture the reversion

Exit Logic:
- TP: half-spread reversion (small but high probability)
- SL: 2x spread (cut quickly if displacement persists)
- Max hold: 30 seconds (microstructure edge decays fast)

Why this works:
- Maker entry = zero or negative fees (rebate)
- No directional prediction needed — pure microstructure
- High win rate compensates for small per-trade profit
"""

from typing import Optional, Dict, Any
import os

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class SpreadCaptureScalp(Strategy):
    strategy_id = "spread_capture_scalp"

    # Defaults — overrideable via profile strategy_params
    DEFAULT_MIN_IMBALANCE = 0.55
    DEFAULT_MAX_SPREAD_BPS = 3.0
    DEFAULT_MIN_DEPTH_USD = 5000.0
    DEFAULT_TP_SPREAD_FRACTION = 0.5
    DEFAULT_SL_SPREAD_MULTIPLE = 2.5
    DEFAULT_MAX_HOLD_SEC = 30.0
    DEFAULT_MIN_EDGE_BPS = float(os.getenv("STRATEGY_MIN_EDGE_BPS", "10.0"))

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        # --- params ---
        min_imbalance = params.get("min_imbalance", self.DEFAULT_MIN_IMBALANCE)
        max_spread_bps = params.get("max_spread_bps", self.DEFAULT_MAX_SPREAD_BPS)
        min_depth_usd = params.get("min_depth_usd", self.DEFAULT_MIN_DEPTH_USD)
        tp_frac = params.get("tp_spread_fraction", self.DEFAULT_TP_SPREAD_FRACTION)
        sl_mult = params.get("sl_spread_multiple", self.DEFAULT_SL_SPREAD_MULTIPLE)
        max_hold_sec = params.get("max_hold_sec", self.DEFAULT_MAX_HOLD_SEC)
        min_edge_bps = params.get("min_edge_bps", self.DEFAULT_MIN_EDGE_BPS)
        fee_bps = params.get("fee_bps", 0.0)  # maker = 0 or rebate
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.003)

        # --- fast filters ---
        if features.price is None or features.price <= 0:
            return None
        if features.spread is None or features.spread <= 0:
            return None

        spread_bps = features.spread / features.price * 10_000
        if spread_bps > max_spread_bps:
            return None  # spread too wide — reversion won't cover costs

        # Need orderflow imbalance
        imb = features.orderflow_imbalance
        if imb is None:
            return None
        abs_imb = abs(imb)
        if abs_imb < min_imbalance:
            return None  # no imbalance spike

        # Need sufficient book depth (thin books = no reversion)
        bid_depth = getattr(features, "bid_depth_usd", None) or 0.0
        ask_depth = getattr(features, "ask_depth_usd", None) or 0.0
        if min(bid_depth, ask_depth) < min_depth_usd:
            return None

        # --- direction: fade the aggressor ---
        # Positive imbalance = buy aggression → fade by going SHORT
        # Negative imbalance = sell aggression → fade by going LONG
        side = "short" if imb > 0 else "long"

        # --- entry/exit prices ---
        half_spread = features.spread / 2.0
        if side == "long":
            entry = features.price - half_spread  # limit at best bid
            tp = entry + features.spread * tp_frac
            sl = entry - features.spread * sl_mult
        else:
            entry = features.price + half_spread  # limit at best ask
            tp = entry - features.spread * tp_frac
            sl = entry + features.spread * sl_mult

        # --- edge check ---
        profit_bps = abs(tp - entry) / features.price * 10_000
        cost_bps = fee_bps  # maker entry + maker exit ≈ 0
        net_edge = profit_bps - cost_bps
        if net_edge < min_edge_bps:
            return None

        # --- sizing ---
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
                f"spread_capture: imb={imb:.2f} spread={spread_bps:.1f}bps "
                f"side={side} edge={net_edge:.1f}bps"
            ),
            profile_id=profile.id if hasattr(profile, "id") else "spread_capture_profile",
            expected_horizon_sec=max_hold_sec,
            time_to_work_sec=10.0,
            max_hold_sec=max_hold_sec,
            mfe_min_bps=profit_bps * 0.3,
        )
