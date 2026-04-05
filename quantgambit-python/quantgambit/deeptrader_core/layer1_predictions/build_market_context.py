"""
Build Market Context - Aggregate all market data into MarketContext

Builds a comprehensive MarketContext from:
- Layer 0 data (orderbook, trades, AMT, HTF)
- Layer 1 classifiers (trend, volatility, liquidity, regime)

Returns a complete MarketContext ready for Layer 2 (signal generation).
"""

from typing import Optional
import time

from .market_context import MarketContext
from .trend_classifier import classify_trend
from .volatility_classifier import classify_volatility
from .liquidity_classifier import classify_liquidity
from .regime_classifier import classify_regime


def build_market_context(symbol: str, state, config) -> Optional[MarketContext]:
    """
    Build MarketContext from current market data
    
    Args:
        symbol: Trading symbol
        state: StateManager with current market data
        config: FastScalperConfig
        
    Returns:
        MarketContext or None if insufficient data
    """
    # Get orderbook
    orderbook = state.get_orderbook(symbol)
    if not orderbook or not orderbook.bids or not orderbook.asks:
        return None
    
    # Get current price
    price = (orderbook.bids[0][0] + orderbook.asks[0][0]) / 2
    
    # Get HTF indicators
    htf = state.htf_indicators.get(symbol, {})
    if not htf:
        return None
    
    # Get AMT metrics (stored in amt_cache, not amt_metrics)
    amt_obj = state.amt_cache.get(symbol)
    if not amt_obj:
        return None
    
    # Convert AMTMetrics object to normalized floats
    vah = float(amt_obj.value_area_high)
    val = float(amt_obj.value_area_low)
    poc = float(amt_obj.point_of_control)
    rotation_factor = float(amt_obj.rotation_factor)
    position_in_value = str(amt_obj.position_in_value)
    
    # Recent trade metrics (support dict/tuple formats)
    recent_trades = state.get_recent_trades(symbol, count=50)
    trades_per_second = 0.0
    buy_volume = 0.0
    sell_volume = 0.0
    
    def _trade_meta(trade):
        if isinstance(trade, dict):
            return (
                float(trade.get('price', 0.0)),
                float(trade.get('size', 0.0)),
                str(trade.get('side', 'unknown')),
                float(trade.get('timestamp', 0.0))
            )
        if isinstance(trade, (list, tuple)):
            if len(trade) >= 4:
                return float(trade[0]), float(trade[1]), str(trade[2]), float(trade[3])
            if len(trade) == 3:
                return float(trade[0]), float(trade[1]), str(trade[2]), 0.0
        return 0.0, 0.0, 'unknown', 0.0
    
    if len(recent_trades) >= 2:
        first_price, first_size, first_side, first_ts = _trade_meta(recent_trades[0])
        last_price, last_size, last_side, last_ts = _trade_meta(recent_trades[-1])
        time_window = last_ts - first_ts
        if time_window > 0:
            trades_per_second = len(recent_trades) / time_window
        
        for trade in recent_trades:
            price, size, side, _ts = _trade_meta(trade)
            if price <= 0 or size <= 0:
                continue
            notional = price * size
            side_lower = side.lower()
            if side_lower in ("buy", "long", "bid"):
                buy_volume += notional
            elif side_lower in ("sell", "short", "ask"):
                sell_volume += notional
    
    total_volume = buy_volume + sell_volume
    volume_imbalance = ((buy_volume - sell_volume) / total_volume) if total_volume > 0 else 0.0
    
    # Normalize HTF values (support both legacy and new keys)
    ema_fast = float(htf.get('ema_fast_15m', htf.get('ema_fast', 0.0)))
    ema_slow = float(htf.get('ema_slow_15m', htf.get('ema_slow', 0.0)))
    atr_5m = float(htf.get('atr_5m', htf.get('atr', 0.0)))
    atr_baseline = float(htf.get('atr_5m_baseline', htf.get('atr_baseline', 0.0)))
    if atr_baseline <= 0 and atr_5m > 0:
        atr_baseline = atr_5m
    if atr_baseline <= 0:
        atr_baseline = 1.0
    
    ema_spread_pct = ((ema_fast - ema_slow) / price) if price > 0 else 0.0
    
    # Create initial context with raw features
    context = MarketContext(
        symbol=symbol,
        timestamp=time.time(),
        price=price,
        
        # Price features
        price_change_1s=0.0,  # Would need historical prices
        price_change_5s=0.0,
        price_change_30s=0.0,
        price_change_5m=0.0,
        
        # Trend features (from HTF) - ensure float types
        ema_fast_15m=ema_fast,
        ema_slow_15m=ema_slow,
        ema_spread_pct=ema_spread_pct,
        trend_strength=abs(ema_spread_pct),
        trend_direction=str(htf.get('trend', 'flat') or ('up' if ema_fast > ema_slow else 'down' if ema_fast < ema_slow else 'flat')),
        
        # Volatility features - ensure float types
        atr_5m=atr_5m,
        atr_5m_baseline=atr_baseline,
        atr_ratio=atr_5m / atr_baseline if atr_baseline > 0 else 1.0,
        realized_vol_1m=0.0,  # Would need historical prices
        
        # AMT features - ensure float types
        value_area_high=vah,
        value_area_low=val,
        point_of_control=poc,
        rotation_factor=rotation_factor,
        position_in_value=position_in_value or 'inside',
        distance_to_vah_pct=((price - vah) / price * 100) if vah > 0 and price > 0 else 0.0,
        distance_to_val_pct=((price - val) / price * 100) if val > 0 and price > 0 else 0.0,
        distance_to_poc_pct=((price - poc) / price * 100) if poc > 0 and price > 0 else 0.0,
        
        # Orderbook features
        spread=(orderbook.asks[0][0] - orderbook.bids[0][0]),
        spread_bps=(orderbook.asks[0][0] - orderbook.bids[0][0]) / price * 10000,
        bid_depth_usd=sum(bid[0] * bid[1] for bid in orderbook.bids[:10]),
        ask_depth_usd=sum(ask[0] * ask[1] for ask in orderbook.asks[:10]),
        orderbook_imbalance=0.0,  # Will calculate from bid/ask depth
        bid_pressure_bps=0.0,
        ask_pressure_bps=0.0,
        
        # Order flow features
        trades_per_second=trades_per_second,
        buy_volume_1m=buy_volume,
        sell_volume_1m=sell_volume,
        volume_imbalance=volume_imbalance,
        aggressive_buy_pct=0.0,
        aggressive_sell_pct=0.0,
        
        # Session features
        session='us',  # Would determine from time
        hour_utc=int(time.time() / 3600) % 24,
        is_market_hours=True,
        
        # Risk features
        daily_pnl=0.0,  # Would get from account state
        risk_mode='normal',
        open_positions=0,
        account_equity=10000.0,
        
        # Data quality
        data_completeness=1.0,
        missing_features=[],
    )
    
    # Calculate orderbook imbalance
    if context.bid_depth_usd > 0 and context.ask_depth_usd > 0:
        context.orderbook_imbalance = (context.bid_depth_usd - context.ask_depth_usd) / (context.bid_depth_usd + context.ask_depth_usd)
    
    # Calculate orderflow imbalance (same as orderbook for now)
    context.orderflow_imbalance = context.orderbook_imbalance

    # Calculate orderflow confidence from orderbook imbalance
    # This provides a fallback when model confidence is low/unreliable
    imbalance = abs(context.orderbook_imbalance)
    if imbalance >= 0.03:  # Lower threshold for more sensitivity
        # Always use imbalance-based confidence if imbalance is significant
        # This overrides model confidence when orderbook shows clear direction
        context.orderflow_confidence = max(context.orderflow_confidence, min(1.0, imbalance))
        context.predicted_direction = "up" if context.orderbook_imbalance > 0 else "down"
    
    # Run classifiers
    context.trend_bias, context.trend_confidence = classify_trend(
        context.ema_fast_15m,
        context.ema_slow_15m,
        context.price
    )
    context.volatility_regime, context.volatility_percentile = classify_volatility(
        context.atr_ratio,
        context.rotation_factor
    )
    context.liquidity_regime = classify_liquidity(
        context.spread_bps,
        context.bid_depth_usd,
        context.ask_depth_usd
    )
    context.market_regime, context.regime_confidence = classify_regime(
        context.rotation_factor,
        context.atr_ratio,
        context.trend_strength,
        context.spread_bps
    )
    
    # Check for missing features
    missing = []
    if context.ema_fast_15m == 0.0:
        missing.append('ema_fast_15m')
    if context.ema_slow_15m == 0.0:
        missing.append('ema_slow_15m')
    if context.atr_5m == 0.0:
        missing.append('atr_5m')
    if context.value_area_high == 0.0:
        missing.append('value_area_high')
    if context.value_area_low == 0.0:
        missing.append('value_area_low')
    
    context.missing_features = missing
    context.data_completeness = 1.0 - (len(missing) / 10.0)  # Assume 10 critical features
    
    return context

