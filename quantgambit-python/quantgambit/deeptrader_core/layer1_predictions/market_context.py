"""
MarketContext - Unified market prediction dataclass

This is Layer 1's output: a comprehensive snapshot of all market predictions
at a point in time, used as input for Layer 2 (Signal Generation).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
import time


@dataclass
class MarketContext:
    """
    Complete market context for a symbol at a point in time
    
    This is the unified output of Layer 1 (Predictions) and serves as
    the input to Layer 2 (Signal Generation).
    
    All predictions are consolidated here:
    - Trend predictions (long/short/neutral)
    - Volatility predictions (high/normal/low)
    - Liquidity predictions (deep/normal/thin)
    - Orderflow predictions (buy/sell pressure)
    - Regime predictions (range/breakout/squeeze/chop)
    """
    # Identity
    symbol: str
    timestamp: float
    
    # ═══════════════════════════════════════════════════════════════
    # LAYER 1 PREDICTIONS (Market Context)
    # ═══════════════════════════════════════════════════════════════
    
    # Trend Predictions
    trend_bias: str = "neutral"  # 'long', 'short', 'neutral'
    trend_confidence: float = 0.0  # 0.0-1.0
    trend_strength: float = 0.0  # Absolute strength
    trend_direction: str = "flat"  # 'up', 'down', 'flat' (legacy)
    
    # Volatility Predictions
    volatility_regime: str = "normal"  # 'high', 'normal', 'low'
    volatility_percentile: float = 0.5  # 0.0-1.0
    atr_ratio: float = 1.0  # current ATR / baseline ATR
    
    # Liquidity Predictions
    liquidity_regime: str = "normal"  # 'deep', 'normal', 'thin'
    bid_depth_usd: float = 0.0
    ask_depth_usd: float = 0.0
    spread_bps: float = 0.0
    
    # Order Flow Predictions
    orderflow_imbalance: float = 0.0  # -1.0 (sell pressure) to +1.0 (buy pressure)
    orderflow_confidence: float = 0.0  # 0.0-1.0
    predicted_direction: str = "neutral"  # 'up', 'down', 'neutral'
    predicted_move_bps: float = 0.0  # Expected move in basis points
    
    # Market Regime Predictions
    market_regime: str = "range"  # 'range', 'breakout', 'squeeze', 'chop'
    regime_confidence: float = 0.0  # 0.0-1.0
    
    # ═══════════════════════════════════════════════════════════════
    # RAW FEATURES (from Layer 0)
    # ═══════════════════════════════════════════════════════════════
    
    # Price features
    price: float = 0.0
    price_change_1s: float = 0.0
    price_change_5s: float = 0.0
    price_change_30s: float = 0.0
    price_change_5m: float = 0.0
    
    # HTF indicators (raw)
    ema_fast_15m: float = 0.0
    ema_slow_15m: float = 0.0
    ema_spread_pct: float = 0.0  # (fast - slow) / price
    atr_5m: float = 0.0
    atr_5m_baseline: float = 0.0
    realized_vol_1m: float = 0.0
    
    # AMT features (raw)
    value_area_high: float = 0.0
    value_area_low: float = 0.0
    point_of_control: float = 0.0
    rotation_factor: float = 0.0
    position_in_value: str = "inside"  # 'above', 'below', 'inside'
    distance_to_vah_pct: float = 0.0
    distance_to_val_pct: float = 0.0
    distance_to_poc_pct: float = 0.0
    
    # Orderbook features (raw)
    spread: float = 0.0
    orderbook_imbalance: float = 0.0  # (bid - ask) / (bid + ask)
    bid_pressure_bps: float = 0.0
    ask_pressure_bps: float = 0.0
    
    # Order flow features (raw)
    trades_per_second: float = 0.0
    buy_volume_1m: float = 0.0
    sell_volume_1m: float = 0.0
    volume_imbalance: float = 0.0  # (buy - sell) / (buy + sell)
    aggressive_buy_pct: float = 0.0
    aggressive_sell_pct: float = 0.0
    
    # Session features
    session: str = "us"  # 'asia', 'europe', 'us', 'overnight'
    hour_utc: int = 0
    is_market_hours: bool = True
    
    # Risk features
    daily_pnl: float = 0.0
    risk_mode: str = "normal"  # 'normal', 'protection', 'recovery', 'off'
    open_positions: int = 0
    account_equity: float = 10000.0
    
    # Funding features (if available)
    funding_rate: Optional[float] = None
    funding_extreme: bool = False
    
    # Correlation features (if available)
    correlation_to_btc: Optional[float] = None
    btc_direction: Optional[str] = None
    
    # Data quality
    data_completeness: float = 1.0  # 0.0 to 1.0
    missing_features: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for ML models"""
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            
            # Predictions
            'trend_bias': self.trend_bias,
            'trend_confidence': self.trend_confidence,
            'volatility_regime': self.volatility_regime,
            'liquidity_regime': self.liquidity_regime,
            'orderflow_imbalance': self.orderflow_imbalance,
            'market_regime': self.market_regime,
            
            # Raw features
            'price': self.price,
            'price_change_1s': self.price_change_1s,
            'price_change_5s': self.price_change_5s,
            'price_change_30s': self.price_change_30s,
            'price_change_5m': self.price_change_5m,
            'ema_spread_pct': self.ema_spread_pct,
            'trend_strength': self.trend_strength,
            'atr_ratio': self.atr_ratio,
            'rotation_factor': self.rotation_factor,
            'distance_to_vah_pct': self.distance_to_vah_pct,
            'distance_to_val_pct': self.distance_to_val_pct,
            'distance_to_poc_pct': self.distance_to_poc_pct,
            'spread_bps': self.spread_bps,
            'orderbook_imbalance': self.orderbook_imbalance,
            'trades_per_second': self.trades_per_second,
            'volume_imbalance': self.volume_imbalance,
            'data_completeness': self.data_completeness,
        }
    
    def get_feature_vector(self) -> List[float]:
        """Get numerical feature vector for ML models"""
        return [
            self.price_change_1s,
            self.price_change_5s,
            self.price_change_30s,
            self.price_change_5m,
            self.ema_spread_pct,
            self.trend_strength,
            self.trend_confidence,
            self.atr_ratio,
            self.volatility_percentile,
            self.rotation_factor,
            self.distance_to_vah_pct,
            self.distance_to_val_pct,
            self.distance_to_poc_pct,
            self.spread_bps,
            self.orderbook_imbalance,
            self.orderflow_imbalance,
            self.orderflow_confidence,
            self.bid_pressure_bps,
            self.ask_pressure_bps,
            self.trades_per_second,
            self.volume_imbalance,
            self.regime_confidence,
        ]


def build_market_context(state, symbol: str) -> Optional[MarketContext]:
    """
    Build MarketContext from StateManager
    
    This is the main entry point for Layer 1 (Predictions).
    It aggregates all raw features from Layer 0 and applies
    classifiers to generate predictions.
    
    Args:
        state: StateManager instance
        symbol: Trading symbol
        
    Returns:
        MarketContext with all predictions, or None if data incomplete
    """
    try:
        # Import classifiers (avoid circular imports)
        from .trend_classifier import classify_trend
        from .volatility_classifier import classify_volatility
        from .liquidity_classifier import classify_liquidity
        from .regime_classifier import classify_regime
        
        # Get orderbook
        orderbook = state.get_orderbook(symbol)
        if not orderbook or not orderbook.bids or not orderbook.asks:
            return None
        
        # Get AMT metrics
        amt = state.get_amt_metrics(symbol)
        if not amt:
            return None
        
        # Get HTF indicators
        htf = state.get_htf_indicators(symbol)
        if not htf:
            return None
        
        # Calculate mid price
        mid_price = (orderbook.bids[0][0] + orderbook.asks[0][0]) / 2.0
        
        # Calculate spread
        spread = (orderbook.asks[0][0] - orderbook.bids[0][0]) / mid_price
        spread_bps = spread * 10000
        
        # Calculate orderbook depths
        bid_depth_usd = sum(price * size for price, size in orderbook.bids[:10])
        ask_depth_usd = sum(price * size for price, size in orderbook.asks[:10])
        
        # Calculate trades per second
        recent_trades = state.get_recent_trades(symbol, count=10)
        trades_per_second = 0.0
        if len(recent_trades) >= 2:
            # Handle both dict and tuple formats
            if isinstance(recent_trades[0], dict):
                time_window = recent_trades[-1]['timestamp'] - recent_trades[0]['timestamp']
            else:
                time_window = recent_trades[-1][3] - recent_trades[0][3]
            if time_window > 0:
                trades_per_second = len(recent_trades) / time_window
        
        # Calculate EMA spread
        ema_spread_pct = 0.0
        ema_fast = htf.get('ema_fast_15m') or htf.get('ema_fast', 0)
        ema_slow = htf.get('ema_slow_15m') or htf.get('ema_slow', 0)
        if ema_slow > 0:
            ema_spread_pct = (ema_fast - ema_slow) / mid_price
        
        # Calculate ATR ratio
        atr = htf.get('atr_5m') or htf.get('atr', 0)
        atr_baseline = htf.get('atr_5m_baseline') or htf.get('atr_baseline', 0)
        atr_ratio = 1.0
        if atr_baseline > 0:
            atr_ratio = atr / atr_baseline
        
        # Calculate distances to AMT levels
        distance_to_vah_pct = abs(mid_price - amt.value_area_high) / mid_price
        distance_to_val_pct = abs(mid_price - amt.value_area_low) / mid_price
        distance_to_poc_pct = abs(mid_price - amt.point_of_control) / mid_price
        
        # Get session
        from quantgambit.deeptrader_core.profiles.profile_classifier import classify_session
        session = classify_session(time.time())
        
        # Get orderflow prediction (if available)
        predicted_direction = "neutral"
        orderflow_confidence = 0.0
        predicted_move_bps = 0.0
        orderflow_imbalance = 0.0
        
        if hasattr(state, 'orderbook_model') and state.orderbook_model:
            try:
                prediction = state.orderbook_model.predict(orderbook, symbol)
                if prediction:
                    predicted_move_bps = prediction.get('predicted_move_bps', 0.0)
                    orderflow_confidence = prediction.get('confidence', 0.0)
                    if predicted_move_bps > 0.5:
                        predicted_direction = "up"
                    elif predicted_move_bps < -0.5:
                        predicted_direction = "down"
                    orderflow_imbalance = prediction.get('imbalance', 0.0)
            except Exception:
                pass  # Silently fail if prediction not available
        
        # ═══════════════════════════════════════════════════════════════
        # LAYER 1: APPLY CLASSIFIERS
        # ═══════════════════════════════════════════════════════════════
        
        # Classify trend
        trend_bias, trend_confidence = classify_trend(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            price=mid_price
        )
        
        # Classify volatility
        volatility_regime, volatility_percentile = classify_volatility(
            atr_ratio=atr_ratio,
            rotation_factor=amt.rotation_factor
        )
        
        # Classify liquidity
        liquidity_regime = classify_liquidity(
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            spread_bps=spread_bps
        )
        
        # Classify market regime
        market_regime, regime_confidence = classify_regime(
            rotation_factor=amt.rotation_factor,
            atr_ratio=atr_ratio,
            trend_strength=abs(ema_spread_pct),
            spread_bps=spread_bps
        )
        
        # Build MarketContext
        context = MarketContext(
            symbol=symbol,
            timestamp=time.time(),
            
            # Predictions (Layer 1)
            trend_bias=trend_bias,
            trend_confidence=trend_confidence,
            trend_strength=abs(ema_spread_pct),
            trend_direction=trend_bias,  # Legacy compatibility
            volatility_regime=volatility_regime,
            volatility_percentile=volatility_percentile,
            atr_ratio=atr_ratio,
            liquidity_regime=liquidity_regime,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            spread_bps=spread_bps,
            orderflow_imbalance=orderflow_imbalance,
            orderflow_confidence=orderflow_confidence,
            predicted_direction=predicted_direction,
            predicted_move_bps=predicted_move_bps,
            market_regime=market_regime,
            regime_confidence=regime_confidence,
            
            # Raw features (Layer 0)
            price=mid_price,
            ema_fast_15m=ema_fast,
            ema_slow_15m=ema_slow,
            ema_spread_pct=ema_spread_pct,
            atr_5m=atr,
            atr_5m_baseline=atr_baseline,
            value_area_high=amt.value_area_high,
            value_area_low=amt.value_area_low,
            point_of_control=amt.point_of_control,
            rotation_factor=amt.rotation_factor,
            position_in_value=amt.position_in_value,
            distance_to_vah_pct=distance_to_vah_pct,
            distance_to_val_pct=distance_to_val_pct,
            distance_to_poc_pct=distance_to_poc_pct,
            spread=spread,
            trades_per_second=trades_per_second,
            session=session,
            daily_pnl=state.risk_state.daily_pnl,
            open_positions=state.risk_state.position_count,
            account_equity=state.risk_state.account_balance,
        )
        
        return context
        
    except Exception as e:
        print(f"⚠️ Failed to build MarketContext for {symbol}: {e}")
        return None























