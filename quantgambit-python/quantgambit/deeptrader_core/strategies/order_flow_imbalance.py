"""
Order Flow Imbalance Strategy

Trades extreme bid/ask ratio imbalances that signal exhaustion or momentum.
Real-time order flow reveals institutional positioning and retail panic.

Entry Conditions:
- Extreme imbalance ratio (>70% one-sided)
- Sufficient volume for statistical significance
- Fade exhaustion (buy when sellers exhausted)
- Or follow momentum (buy when buyers dominate)
- Quick execution required

Risk Management:
- Moderate stops (0.5%) - imbalances can persist
- Quick targets (1.0%) - capture the edge
- Moderate position sizing (1.2% risk)

Ideal Market Conditions:
- High volume periods (US open, Europe open)
- Clear imbalance extremes
- Fast-moving markets
- Good liquidity

NOTE: Requires order flow imbalance inputs from trade/market data.
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class OrderFlowImbalance(Strategy):
    strategy_id = "order_flow_imbalance"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for order flow imbalance strategy"""
        
        # Check if longs/shorts are allowed
        if not params.get("allow_longs") and not params.get("allow_shorts"):
            return None

        # Market conditions: High volume preferred for reliable imbalance signals
        if profile.session not in ["us", "europe"]:
            return None
        
        # Check spread
        if features.spread > params.get("max_spread", 0.002):
            log_info(f"OrderFlowImbalance: Spread too wide ({features.spread:.4f}) for {features.symbol}")
            return None
        
        # Check for sufficient volume
        min_volume_threshold = params.get("min_volume_threshold", 5.0)
        if features.trades_per_second < min_volume_threshold:
            log_info(f"OrderFlowImbalance: Insufficient volume ({features.trades_per_second:.1f} tps) for {features.symbol}")
            return None
        
        imbalance_threshold = params.get("imbalance_threshold", 0.1)
        imbalance_value = features.orderflow_imbalance
        if imbalance_value is None:
            log_info(f"OrderFlowImbalance: Missing orderflow imbalance for {features.symbol}")
            return None
        imbalance_strength = abs(imbalance_value) if imbalance_value is not None else 0.0
        
        if imbalance_strength < imbalance_threshold:
            # Imbalance not extreme enough
            return None
        
        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        fade_exhaustion = params.get("fade_exhaustion", True)
        follow_momentum = params.get("follow_momentum", False)

        # Fade exhaustion mode: Counter-trade extreme imbalances
        if fade_exhaustion:
            # Long signal: Extreme selling exhaustion (strong negative rotation)
            if params.get("allow_longs") and (imbalance_value or 0.0) < -imbalance_threshold:
                # Sellers exhausted, fade the selling
                signal_side = "long"
                stop_loss = features.price * (1 - params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.5%)
                take_profit = features.price * (1 + params.get("take_profit_pct", 0.02))  # 2.0% (was 1.0%)
                meta_reason = f"order_flow_fade_long_sell_exhaustion_imb_{imbalance_value:.3f}"

            # Short signal: Extreme buying exhaustion (strong positive rotation)
            elif params.get("allow_shorts") and (imbalance_value or 0.0) > imbalance_threshold:
                # Buyers exhausted, fade the buying
                signal_side = "short"
                stop_loss = features.price * (1 + params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.5%)
                take_profit = features.price * (1 - params.get("take_profit_pct", 0.02))  # 2.0% (was 1.0%)
                meta_reason = f"order_flow_fade_short_buy_exhaustion_imb_{imbalance_value:.3f}"

        # Follow momentum mode: Trade with extreme imbalances
        elif follow_momentum:
            # Long signal: Strong buying momentum (strong positive rotation)
            if params.get("allow_longs") and (imbalance_value or 0.0) > imbalance_threshold:
                # Follow the buyers
                signal_side = "long"
                stop_loss = features.price * (1 - params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.5%)
                take_profit = features.price * (1 + params.get("take_profit_pct", 0.02))  # 2.0% (was 1.0%)
                meta_reason = f"order_flow_follow_long_buy_momentum_imb_{imbalance_value:.3f}"

            # Short signal: Strong selling momentum (strong negative rotation)
            elif params.get("allow_shorts") and (imbalance_value or 0.0) < -imbalance_threshold:
                # Follow the sellers
                signal_side = "short"
                stop_loss = features.price * (1 + params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.5%)
                take_profit = features.price * (1 - params.get("take_profit_pct", 0.02))  # 2.0% (was 1.0%)
                meta_reason = f"order_flow_follow_short_sell_momentum_imb_{imbalance_value:.3f}"

        if signal_side:
            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.012)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"OrderFlowImbalance: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / params.get("stop_loss_pct", 0.012))
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"OrderFlowImbalance: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"OrderFlowImbalance: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. Imbalance: {imbalance_value:.3f}. "
                    f"SL: {stop_loss:.2f}, TP: {take_profit:.2f}. Reason: {meta_reason}")
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side=signal_side,
                size=size,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                meta_reason=meta_reason,
                profile_id=profile.id
            )
        
        return None
