"""
Liquidity Classifier - Classify liquidity from orderbook depth

Classifies market liquidity as:
- deep: High liquidity (deep orderbook, tight spreads)
- normal: Average liquidity
- thin: Low liquidity (shallow orderbook, wide spreads)

Used for position sizing and execution quality assessment.
"""


def classify_liquidity(
    bid_depth_usd: float,
    ask_depth_usd: float,
    spread_bps: float
) -> str:
    """
    Classify liquidity regime from orderbook metrics
    
    Args:
        bid_depth_usd: Total bid depth in USD (top 10 levels)
        ask_depth_usd: Total ask depth in USD (top 10 levels)
        spread_bps: Bid-ask spread in basis points
        
    Returns:
        Liquidity regime: 'deep', 'normal', or 'thin'
    """
    # Calculate average depth
    avg_depth_usd = (bid_depth_usd + ask_depth_usd) / 2
    
    # Thresholds (tunable based on symbol)
    DEEP_LIQUIDITY_DEPTH = 50000  # $50k+ = deep liquidity
    THIN_LIQUIDITY_DEPTH = 10000  # <$10k = thin liquidity
    
    TIGHT_SPREAD = 2.0  # <2 bps = tight spread
    WIDE_SPREAD = 10.0  # >10 bps = wide spread
    
    # Score based on depth (0-2 points)
    if avg_depth_usd >= DEEP_LIQUIDITY_DEPTH:
        depth_score = 2
    elif avg_depth_usd >= THIN_LIQUIDITY_DEPTH:
        depth_score = 1
    else:
        depth_score = 0
    
    # Score based on spread (0-2 points)
    if spread_bps <= TIGHT_SPREAD:
        spread_score = 2
    elif spread_bps <= WIDE_SPREAD:
        spread_score = 1
    else:
        spread_score = 0
    
    # Combined score (0-4 points)
    total_score = depth_score + spread_score
    
    # Classify liquidity
    if total_score >= 3:
        return "deep"  # Deep liquidity (high depth + tight spread)
    elif total_score >= 2:
        return "normal"  # Normal liquidity
    else:
        return "thin"  # Thin liquidity (low depth or wide spread)


def get_liquidity_multiplier(liquidity_regime: str) -> float:
    """
    Get position sizing multiplier based on liquidity regime
    
    Args:
        liquidity_regime: 'deep', 'normal', or 'thin'
        
    Returns:
        Multiplier for position sizing (reduce size in thin liquidity)
    """
    if liquidity_regime == "deep":
        return 1.2  # Can increase size by 20% in deep liquidity
    elif liquidity_regime == "thin":
        return 0.5  # Reduce size by 50% in thin liquidity
    else:
        return 1.0  # Normal size


def get_max_slippage_bps(liquidity_regime: str) -> float:
    """
    Get maximum acceptable slippage based on liquidity regime
    
    Args:
        liquidity_regime: 'deep', 'normal', or 'thin'
        
    Returns:
        Maximum acceptable slippage in basis points
    """
    if liquidity_regime == "deep":
        return 5.0  # Accept up to 5 bps slippage in deep liquidity
    elif liquidity_regime == "thin":
        return 20.0  # Accept up to 20 bps slippage in thin liquidity
    else:
        return 10.0  # Accept up to 10 bps slippage in normal liquidity


def should_use_limit_orders(liquidity_regime: str) -> bool:
    """
    Determine if limit orders should be used based on liquidity
    
    Args:
        liquidity_regime: 'deep', 'normal', or 'thin'
        
    Returns:
        True if limit orders recommended, False if market orders preferred
    """
    # In thin liquidity, use limit orders to avoid excessive slippage
    # In deep liquidity, market orders are fine
    return liquidity_regime == "thin"























