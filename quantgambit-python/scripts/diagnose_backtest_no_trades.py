#!/usr/bin/env python3
"""Diagnose why backtests aren't generating trades.

This script runs through the backtest pipeline step-by-step and reports
exactly where signals are being blocked.

KEY FIX: Calculates AMT levels (POC, VAH, VAL) from candle data since
decision_events don't store these fields.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

# Add parent to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

import asyncpg

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import register_canonical_profiles
from quantgambit.deeptrader_core.types import MarketSnapshot, Features, AccountState
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.signals.stages.ev_gate import EVGateConfig
from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerConfig
from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService


# AMT calculation settings
AMT_LOOKBACK_CANDLES = 100
AMT_VALUE_AREA_PCT = 68.0


def calculate_volume_profile(
    prices: List[float],
    volumes: List[float],
    bins: int = 20,
) -> Dict[str, float]:
    """Calculate volume profile from price and volume data.
    
    Returns POC, VAH, VAL from volume profile analysis.
    """
    if not prices or not volumes or len(prices) != len(volumes):
        return {}
    
    min_price = min(prices)
    max_price = max(prices)
    
    if min_price == max_price:
        return {
            "point_of_control": min_price,
            "value_area_low": min_price,
            "value_area_high": min_price,
        }
    
    # Create price bins
    bin_size = (max_price - min_price) / bins
    volume_bins = [0.0] * bins
    
    # Distribute volume across bins
    for price, volume in zip(prices, volumes):
        if min_price <= price <= max_price:
            bin_index = min(int((price - min_price) / bin_size), bins - 1)
            volume_bins[bin_index] += volume
    
    # Find Point of Control (POC) - highest volume bin
    max_volume = max(volume_bins)
    poc_bin = volume_bins.index(max_volume)
    point_of_control = min_price + (poc_bin * bin_size) + (bin_size / 2)
    
    # Calculate Value Area (68% of volume around POC)
    total_volume = sum(volume_bins)
    value_area_volume = total_volume * (AMT_VALUE_AREA_PCT / 100)
    
    # Find value area bounds by expanding from POC
    accumulated_volume = volume_bins[poc_bin]
    value_area_start = poc_bin
    value_area_end = poc_bin
    
    while accumulated_volume < value_area_volume:
        expanded = False
        
        if value_area_start > 0:
            value_area_start -= 1
            accumulated_volume += volume_bins[value_area_start]
            expanded = True
        
        if accumulated_volume < value_area_volume and value_area_end < bins - 1:
            value_area_end += 1
            accumulated_volume += volume_bins[value_area_end]
            expanded = True
        
        if not expanded:
            break
    
    value_area_low = min_price + (value_area_start * bin_size)
    value_area_high = min_price + ((value_area_end + 1) * bin_size)
    
    return {
        "point_of_control": point_of_control,
        "value_area_low": value_area_low,
        "value_area_high": value_area_high,
    }


def calculate_amt_levels(
    candles: List[Dict[str, Any]],
    current_ts: datetime,
) -> Dict[str, float]:
    """Calculate real AMT levels (POC, VAH, VAL) from candle data."""
    # Get candles up to current timestamp
    relevant_candles = [c for c in candles if c["ts"] <= current_ts]
    
    # Use last N candles for volume profile
    lookback = min(AMT_LOOKBACK_CANDLES, len(relevant_candles))
    if lookback < 10:
        return {}
    
    recent_candles = relevant_candles[-lookback:]
    
    # Extract price and volume data
    prices = []
    volumes = []
    for candle in recent_candles:
        # Use OHLC average as representative price
        price = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
        prices.append(price)
        volumes.append(candle["volume"])
    
    return calculate_volume_profile(prices, volumes)


async def fetch_candle_data(
    pool: asyncpg.Pool,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
) -> List[Dict[str, Any]]:
    """Fetch candle data for AMT calculations."""
    query = """
        SELECT ts, open, high, low, close, volume
        FROM market_candles
        WHERE symbol = $1 AND timeframe_sec = 300 AND ts >= $2 AND ts <= $3
        ORDER BY ts ASC
    """
    
    rows = await pool.fetch(query, symbol, start_time, end_time)
    
    return [
        {
            "ts": row["ts"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in rows
    ]


async def fetch_decision_events(
    pool: asyncpg.Pool,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    sample_every: int = 50,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Fetch decision events from TimescaleDB.
    
    Only fetches events that have snapshot data with mid_price.
    """
    # Filter for events with actual snapshot data (not just rejection records)
    query = """
        WITH valid_events AS (
            SELECT ts, payload
            FROM decision_events
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
            AND payload->'snapshot'->>'mid_price' IS NOT NULL
        ),
        numbered AS (
            SELECT ts, payload, ROW_NUMBER() OVER (ORDER BY ts) as rn
            FROM valid_events
        )
        SELECT ts, payload
        FROM numbered
        WHERE rn % $4 = 0
        ORDER BY ts
        LIMIT $5
    """
    
    rows = await pool.fetch(query, symbol, start_time, end_time, sample_every, limit)
    
    events = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        events.append({
            "ts": row["ts"],
            "payload": payload,
        })
    
    return events


def build_context_from_event(
    event: Dict[str, Any],
    symbol: str,
    amt_levels: Optional[Dict[str, float]] = None,
) -> Optional[ContextVector]:
    """Build a ContextVector from a decision event with AMT levels."""
    payload = event.get("payload", {})
    snapshot = payload.get("snapshot", {})
    metrics = payload.get("metrics", {})
    
    price = snapshot.get("mid_price") or metrics.get("price")
    if not price:
        return None
    
    ts = event["ts"]
    timestamp = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
    hour_utc = ts.hour if hasattr(ts, "hour") else 12
    
    if 0 <= hour_utc < 8:
        session = "asia"
    elif 8 <= hour_utc < 14:
        session = "europe"
    elif 14 <= hour_utc < 21:
        session = "us"
    else:
        session = "overnight"
    
    spread_bps = snapshot.get("spread_bps", 5.0)
    bid_depth_usd = metrics.get("bid_depth_usd", 50000.0)
    ask_depth_usd = metrics.get("ask_depth_usd", 50000.0)
    trend_direction = snapshot.get("trend_direction", "flat")
    trend_strength = snapshot.get("trend_strength", 0.001)
    vol_regime = snapshot.get("vol_regime", "normal")
    market_regime = snapshot.get("market_regime") or metrics.get("regime_label", "range")
    total_depth = bid_depth_usd + ask_depth_usd
    liquidity_score = min(1.0, total_depth / 200000.0)
    expected_cost_bps = spread_bps / 2 + 5.5
    
    # Calculate position_in_value from AMT levels
    position_in_value = "inside"
    
    # Use stored rotation_factor from snapshot if available (preferred)
    # Only recalculate if not stored
    rotation_factor = snapshot.get("rotation_factor")
    if rotation_factor is None:
        # Fallback: calculate rotation factor from imbalance and trend
        imb_5s = snapshot.get("imb_5s", 0)
        rotation_factor = imb_5s * 5 if imb_5s else 0.0
        if trend_direction == "up":
            rotation_factor += trend_strength * 5
        elif trend_direction == "down":
            rotation_factor -= trend_strength * 5
    
    if amt_levels:
        poc = amt_levels.get("point_of_control")
        vah = amt_levels.get("value_area_high")
        val = amt_levels.get("value_area_low")
        
        if poc and vah and val:
            if price > vah:
                position_in_value = "above"
            elif price < val:
                position_in_value = "below"
            else:
                position_in_value = "inside"
    else:
        position_in_value = snapshot.get("position_in_value", "inside")
    
    return ContextVector(
        symbol=symbol,
        timestamp=timestamp,
        price=price,
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        volatility_regime=vol_regime,
        atr_ratio=snapshot.get("atr_ratio", 1.0),
        position_in_value=position_in_value,
        rotation_factor=rotation_factor,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        trades_per_second=metrics.get("trades_per_second", 1.0),
        session=session,
        hour_utc=hour_utc,
        market_regime=market_regime,
        risk_mode="normal",
        expected_cost_bps=expected_cost_bps,
        liquidity_score=liquidity_score,
        data_completeness=snapshot.get("data_quality_score", 1.0),
        # Set book/trade age to 0 for backtesting
        book_age_ms=0.0,
        trade_age_ms=0.0,
    )


def build_decision_input(
    event: Dict[str, Any],
    symbol: str,
    profile_id: str,
    amt_levels: Optional[Dict[str, float]] = None,
) -> Optional[DecisionInput]:
    """Build a DecisionInput from a decision event with AMT levels."""
    payload = event.get("payload", {})
    snapshot = payload.get("snapshot", {})
    metrics = payload.get("metrics", {})
    
    price = snapshot.get("mid_price") or metrics.get("price")
    if not price:
        return None
    
    ts = event["ts"]
    timestamp = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
    
    spread_bps = snapshot.get("spread_bps", 5.0)
    bid_depth_usd = metrics.get("bid_depth_usd", 50000.0)
    ask_depth_usd = metrics.get("ask_depth_usd", 50000.0)
    trend_direction = snapshot.get("trend_direction", "flat")
    trend_strength = snapshot.get("trend_strength", 0.001)
    vol_regime = snapshot.get("vol_regime", "normal")
    
    # Calculate AMT-derived fields
    poc_price = None
    vah_price = None
    val_price = None
    position_in_value = "inside"
    distance_to_val = 0
    distance_to_vah = 0
    distance_to_poc = 0
    
    # Use stored rotation_factor from snapshot if available (preferred)
    # Only recalculate if not stored
    rotation_factor = snapshot.get("rotation_factor")
    if rotation_factor is None:
        # Fallback: calculate rotation factor from imbalance and trend
        imb_5s = snapshot.get("imb_5s", 0)
        rotation_factor = imb_5s * 5 if imb_5s else 0.0
        if trend_direction == "up":
            rotation_factor += trend_strength * 5
        elif trend_direction == "down":
            rotation_factor -= trend_strength * 5
    
    if amt_levels:
        poc_price = amt_levels.get("point_of_control")
        vah_price = amt_levels.get("value_area_high")
        val_price = amt_levels.get("value_area_low")
        
        if poc_price and vah_price and val_price:
            # Calculate position in value
            if price > vah_price:
                position_in_value = "above"
            elif price < val_price:
                position_in_value = "below"
            else:
                position_in_value = "inside"
            
            # Calculate distances
            distance_to_val = price - val_price
            distance_to_vah = vah_price - price
            distance_to_poc = price - poc_price
    
    # Calculate bid/ask from price and spread
    bid = price - (price * spread_bps / 20000)
    ask = price + (price * spread_bps / 20000)
    
    market_context = {
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
        "volatility_regime": vol_regime,
        "position_in_value": position_in_value,
        "spread_bps": spread_bps,
        "bid_depth_usd": bid_depth_usd,
        "ask_depth_usd": ask_depth_usd,
        "vol_shock": snapshot.get("vol_shock", False),
        "mid_price": price,
        "poc_price": poc_price,
        "vah_price": vah_price,
        "val_price": val_price,
        "best_bid": bid,  # Required by EV gate
        "best_ask": ask,  # Required by EV gate
    }
    
    # Calculate depth imbalance
    total_depth = bid_depth_usd + ask_depth_usd
    depth_imbalance = (bid_depth_usd - ask_depth_usd) / total_depth if total_depth > 0 else 0
    
    features = {
        "symbol": symbol,
        "price": price,
        "bid": bid,       # Keep for backwards compatibility
        "ask": ask,       # Keep for backwards compatibility
        "best_bid": bid,  # Required by EV gate
        "best_ask": ask,  # Required by EV gate
        "spread": spread_bps / 10000,
        "rotation_factor": rotation_factor,
        "position_in_value": position_in_value,
        "bid_depth_usd": bid_depth_usd,
        "ask_depth_usd": ask_depth_usd,
        "orderbook_imbalance": depth_imbalance,
        "orderflow_imbalance": depth_imbalance,
        "timestamp": timestamp,
        # AMT fields - CRITICAL for strategies
        "distance_to_val": distance_to_val,
        "distance_to_vah": distance_to_vah,
        "distance_to_poc": distance_to_poc,
        "value_area_low": val_price,
        "value_area_high": vah_price,
        "point_of_control": poc_price,
        # Trend fields
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
    }
    
    account_state = {
        "equity": 10000.0,
        "daily_pnl": 0.0,
        "max_daily_loss": 200.0,
        "open_positions": 0,
    }
    
    # Build prediction dict with default confidence for backtesting
    # The EV gate requires prediction.confidence for EV calculation
    prediction = {
        "confidence": 0.5,  # Default 50% confidence for backtesting
        "direction": "neutral",
        "source": "backtest_default",
    }
    
    return DecisionInput(
        symbol=symbol,
        market_context=market_context,
        features=features,
        account_state=account_state,
        positions=[],
        profile_settings={"profile_id": profile_id},
        risk_ok=True,
        prediction=prediction,
    )


def warmup_symbol_characteristics(
    events: List[Dict[str, Any]],
    symbol: str,
    warmup_count: int = 100,
) -> SymbolCharacteristicsService:
    """Warm up SymbolCharacteristicsService from historical events.
    
    This ensures symbol-adaptive parameters (min_distance_from_poc_pct, etc.) are
    calculated from actual market data, matching live trading behavior.
    Without warmup, the service uses conservative defaults (3% daily range) which
    causes strategies to reject signals for symbols with smaller typical ranges.
    
    Args:
        events: List of decision events with payload containing snapshot/metrics
        symbol: Trading symbol
        warmup_count: Number of events to use for warmup (default 100)
        
    Returns:
        Warmed-up SymbolCharacteristicsService instance
    """
    service = SymbolCharacteristicsService()
    warmup_samples = min(warmup_count, len(events))
    
    # Collect prices to estimate ATR if not available in events
    prices = []
    for event in events[:warmup_samples]:
        payload = event.get("payload", {})
        snapshot = payload.get("snapshot", {})
        metrics = payload.get("metrics", {})
        price = snapshot.get("mid_price") or metrics.get("price") or 0.0
        if price > 0:
            prices.append(price)
    
    # Estimate ATR from price range if we have enough prices
    # ATR is typically ~1-2% of price for BTC in normal conditions
    estimated_atr = 0.0
    if len(prices) >= 10:
        price_range = max(prices) - min(prices)
        avg_price = sum(prices) / len(prices)
        # Use price range as a proxy for ATR (conservative estimate)
        # Scale up since we're only looking at a short window
        estimated_atr = price_range * 2  # Double the observed range as ATR estimate
        if estimated_atr == 0 and avg_price > 0:
            # If no price movement, use 0.5% of price as minimum ATR
            estimated_atr = avg_price * 0.005
    
    for event in events[:warmup_samples]:
        payload = event.get("payload", {})
        snapshot = payload.get("snapshot", {})
        metrics = payload.get("metrics", {})
        
        # Get spread in bps
        spread_bps = snapshot.get("spread_bps")
        if spread_bps is None:
            mid_price = snapshot.get("mid_price") or metrics.get("price")
            bid = snapshot.get("bid") or metrics.get("bid")
            ask = snapshot.get("ask") or metrics.get("ask")
            if mid_price and bid and ask and mid_price > 0:
                spread_bps = (ask - bid) / mid_price * 10000
            else:
                spread_bps = 5.0  # Default
        
        # Get depth
        bid_depth = metrics.get("bid_depth_usd") or 50000.0
        ask_depth = metrics.get("ask_depth_usd") or 50000.0
        min_depth = min(bid_depth, ask_depth)
        
        # Get ATR and price - use estimated ATR if not available
        atr = metrics.get("atr_5m") or snapshot.get("atr_5m") or estimated_atr
        price = snapshot.get("mid_price") or metrics.get("price") or 0.0
        
        # Get volatility regime
        vol_regime = snapshot.get("vol_regime") or "normal"
        
        # Update service if we have valid data
        if price > 0 and spread_bps > 0:
            service.update(
                symbol=symbol,
                spread_bps=spread_bps,
                min_depth_usd=min_depth,
                atr=atr,
                price=price,
                volatility_regime=vol_regime,
            )
    
    return service


async def diagnose():
    """Run the diagnostic."""
    print("\n" + "="*70)
    print("BACKTEST NO-TRADES DIAGNOSTIC")
    print("="*70)
    
    # Register canonical profiles
    print("\n[1] Registering canonical profiles...")
    register_canonical_profiles()
    registry = get_profile_registry()
    profile_count = len(registry.list_specs())
    print(f"    Registered {profile_count} profiles")
    
    # Create router with backtesting_mode=True
    print("\n[2] Initializing Profile Router (backtesting_mode=True)...")
    router_config = RouterConfig(backtesting_mode=True)
    router = ProfileRouter(config=router_config)
    
    # Connect to TimescaleDB first (need events for warmup)
    print("\n[3] Connecting to TimescaleDB...")
    db_url = os.getenv("BOT_TIMESCALE_URL", "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot")
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    except Exception as e:
        print(f"    ERROR: Could not connect to database: {e}")
        return 1
    
    # Fetch events first (needed for warmup)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)
    symbol = "BTCUSDT"
    
    print(f"\n[4] Fetching decision events for {symbol}...")
    print(f"    Start: {start_time}")
    print(f"    End: {end_time}")
    
    events = await fetch_decision_events(
        pool=pool,
        symbol=symbol,
        start_time=start_time,
        end_time=end_time,
        sample_every=50,
        limit=500,
    )
    
    print(f"    Fetched {len(events)} events")
    
    if not events:
        print("\n    ERROR: No events found! Check if data exists in decision_events table.")
        await pool.close()
        return 1
    
    # Warm up SymbolCharacteristicsService from historical data
    # This ensures symbol-adaptive parameters are based on actual market data
    print("\n[5] Warming up SymbolCharacteristicsService from historical data...")
    symbol_characteristics_service = warmup_symbol_characteristics(events, symbol, warmup_count=100)
    chars = symbol_characteristics_service.get_characteristics(symbol)
    print(f"    Warmed up with {chars.sample_count} samples:")
    print(f"      typical_spread_bps: {chars.typical_spread_bps:.2f}")
    print(f"      typical_depth_usd: {chars.typical_depth_usd:.0f}")
    print(f"      typical_daily_range_pct: {chars.typical_daily_range_pct:.4f}")
    
    # Create DecisionEngine with backtesting-friendly config AND warmed-up service
    print("\n[6] Initializing DecisionEngine (backtesting_mode=True, with warmed-up characteristics)...")
    decision_engine = DecisionEngine(
        backtesting_mode=True,
        use_gating_system=True,
        # Pass the warmed-up symbol characteristics service
        symbol_characteristics_service=symbol_characteristics_service,
        data_readiness_config=DataReadinessConfig(
            max_trade_age_sec=float('inf'),
            max_orderbook_feed_age_sec=float('inf'),
            min_bid_depth_usd=0,
            min_ask_depth_usd=0,
        ),
        global_gate_config=GlobalGateConfig(
            max_spread_bps=50.0,
            min_depth_per_side_usd=1000.0,
            snapshot_age_block_ms=float('inf'),
            block_on_vol_shock=True,
        ),
        ev_gate_config=EVGateConfig(
            max_book_age_ms=86400000,
            max_spread_age_ms=86400000,
        ),
        ev_position_sizer_config=EVPositionSizerConfig(enabled=True),
    )
    
    # Analyze events
    print("\n" + "-"*70)
    print("STEP-BY-STEP ANALYSIS")
    print("-"*70)
    
    # Fetch candle data for AMT calculations
    # Need to fetch candles from BEFORE start_time to have enough history for AMT lookback
    candle_lookback_start = start_time - timedelta(hours=12)  # Extra 12 hours of candle history
    print("\n[7] Fetching candle data for AMT calculations...")
    candle_data = await fetch_candle_data(pool, symbol, candle_lookback_start, end_time)
    print(f"    Fetched {len(candle_data)} candles (including {AMT_LOOKBACK_CANDLES}-candle lookback buffer)")
    
    if len(candle_data) < 10:
        print("    WARNING: Not enough candle data for AMT calculations!")
        print("    AMT levels will not be calculated, which may cause no signals.")
    
    stats = {
        "total_events": len(events),
        "context_build_failed": 0,
        "profile_selection_failed": 0,
        "profile_selection_success": 0,
        "decision_engine_success": 0,
        "decision_engine_rejected": 0,
        "rejection_stages": defaultdict(int),
        "rejection_reasons": defaultdict(int),
        "profile_rejections": defaultdict(lambda: defaultdict(int)),
        "amt_levels_calculated": 0,
        "position_above": 0,
        "position_below": 0,
        "position_inside": 0,
    }
    
    # Sample a few events for detailed analysis
    sample_events = events[:10]
    
    print(f"\n[8] Analyzing {len(sample_events)} sample events in detail...\n")
    
    # First, check what data is available in the events
    print("=== DATA AVAILABILITY CHECK ===")
    sample_payload = events[0].get("payload", {})
    sample_snapshot = sample_payload.get("snapshot", {})
    sample_metrics = sample_payload.get("metrics", {})
    
    print(f"Snapshot keys: {list(sample_snapshot.keys())}")
    print(f"Metrics keys: {list(sample_metrics.keys())}")
    
    # Check for AMT-related fields
    amt_fields = ["distance_to_val", "distance_to_vah", "distance_to_poc", 
                  "value_area_low", "value_area_high", "point_of_control",
                  "position_in_value", "rotation_factor"]
    print(f"\nAMT-related fields in snapshot (BEFORE fix):")
    for field in amt_fields:
        val = sample_snapshot.get(field)
        print(f"  {field}: {val}")
    
    # Calculate AMT levels for first event to show the fix
    if candle_data:
        sample_amt = calculate_amt_levels(candle_data, events[0]["ts"])
        print(f"\nAMT levels calculated from candles (AFTER fix):")
        for key, val in sample_amt.items():
            print(f"  {key}: {val:.2f}" if val else f"  {key}: None")
    
    print("\n" + "="*50 + "\n")
    
    for i, event in enumerate(sample_events):
        ts = event["ts"]
        print(f"--- Event {i+1} at {ts} ---")
        
        # Calculate AMT levels from candle data
        amt_levels = calculate_amt_levels(candle_data, ts) if candle_data else {}
        if amt_levels:
            stats["amt_levels_calculated"] += 1
        
        # Step A: Build context with AMT levels
        context = build_context_from_event(event, symbol, amt_levels)
        if not context:
            print("  [FAIL] Could not build context (missing price)")
            stats["context_build_failed"] += 1
            continue
        
        # Track position distribution
        if context.position_in_value == "above":
            stats["position_above"] += 1
        elif context.position_in_value == "below":
            stats["position_below"] += 1
        else:
            stats["position_inside"] += 1
        
        print(f"  Context: price={context.price:.2f}, trend={context.trend_direction}, "
              f"vol={context.volatility_regime}, spread={context.spread_bps:.1f}bps, "
              f"position={context.position_in_value}, rotation={context.rotation_factor:.2f}")
        
        # Step B: Profile selection
        profiles = router.select_profiles(context, top_k=3, symbol=symbol)
        
        if not profiles:
            print("  [FAIL] No profiles selected")
            stats["profile_selection_failed"] += 1
            
            # Check why profiles were rejected
            rejections = router.last_rejections.get(symbol, [])
            if rejections:
                print(f"  Profile rejection reasons (top 5):")
                for r in rejections[:5]:
                    print(f"    - {r.profile_id}: {r.reasons}")
                    for reason in r.reasons:
                        stats["profile_rejections"][r.profile_id][reason] += 1
            continue
        
        stats["profile_selection_success"] += 1
        top_profile = profiles[0]
        print(f"  [OK] Profile selected: {top_profile.profile_id} (score={top_profile.score:.3f})")
        
        # Step C: Decision engine with AMT levels
        decision_input = build_decision_input(event, symbol, top_profile.profile_id, amt_levels)
        if not decision_input:
            print("  [FAIL] Could not build decision input")
            continue
        
        success, ctx = await decision_engine.decide_with_context(decision_input)
        
        if success:
            stats["decision_engine_success"] += 1
            print(f"  [OK] Decision engine: TRADE SIGNAL GENERATED")
            if ctx.signal:
                print(f"       Signal: {ctx.signal}")
        else:
            stats["decision_engine_rejected"] += 1
            stage = ctx.rejection_stage or "unknown"
            reason = ctx.rejection_reason or "unknown"
            stats["rejection_stages"][stage] += 1
            stats["rejection_reasons"][reason] += 1
            print(f"  [REJECT] Decision engine rejected at stage: {stage}")
            print(f"           Reason: {reason}")
            if ctx.rejection_detail:
                print(f"           Detail: {ctx.rejection_detail}")
        
        print()
    
    # Now run through all events for statistics
    print("\n[9] Running full analysis on all events...")
    
    for event in events:
        # Calculate AMT levels for each event
        amt_levels = calculate_amt_levels(candle_data, event["ts"]) if candle_data else {}
        if amt_levels:
            stats["amt_levels_calculated"] += 1
        
        context = build_context_from_event(event, symbol, amt_levels)
        if not context:
            stats["context_build_failed"] += 1
            continue
        
        # Track position distribution
        if context.position_in_value == "above":
            stats["position_above"] += 1
        elif context.position_in_value == "below":
            stats["position_below"] += 1
        else:
            stats["position_inside"] += 1
        
        profiles = router.select_profiles(context, top_k=3, symbol=symbol)
        if not profiles:
            stats["profile_selection_failed"] += 1
            continue
        
        stats["profile_selection_success"] += 1
        
        decision_input = build_decision_input(event, symbol, profiles[0].profile_id, amt_levels)
        if not decision_input:
            continue
        
        success, ctx = await decision_engine.decide_with_context(decision_input)
        
        if success:
            stats["decision_engine_success"] += 1
        else:
            stats["decision_engine_rejected"] += 1
            stage = ctx.rejection_stage or "unknown"
            reason = ctx.rejection_reason or "unknown"
            stats["rejection_stages"][stage] += 1
            stats["rejection_reasons"][reason] += 1
    
    await pool.close()
    
    # Summary
    print("\n" + "="*70)
    print("DIAGNOSTIC SUMMARY")
    print("="*70)
    
    print(f"\nTotal Events: {stats['total_events']}")
    print(f"Context Build Failed: {stats['context_build_failed']}")
    print(f"Profile Selection Failed: {stats['profile_selection_failed']}")
    print(f"Profile Selection Success: {stats['profile_selection_success']}")
    print(f"Decision Engine Success (TRADES): {stats['decision_engine_success']}")
    print(f"Decision Engine Rejected: {stats['decision_engine_rejected']}")
    
    # AMT statistics
    print(f"\nAMT Level Statistics:")
    print(f"  AMT Levels Calculated: {stats['amt_levels_calculated']}")
    total_positions = stats['position_above'] + stats['position_below'] + stats['position_inside']
    if total_positions > 0:
        print(f"  Position Above VAH: {stats['position_above']} ({stats['position_above']/total_positions*100:.1f}%)")
        print(f"  Position Below VAL: {stats['position_below']} ({stats['position_below']/total_positions*100:.1f}%)")
        print(f"  Position Inside VA: {stats['position_inside']} ({stats['position_inside']/total_positions*100:.1f}%)")
    
    if stats['rejection_stages']:
        print(f"\nRejection by Stage:")
        for stage, count in sorted(stats['rejection_stages'].items(), key=lambda x: -x[1]):
            pct = count / stats['decision_engine_rejected'] * 100 if stats['decision_engine_rejected'] > 0 else 0
            print(f"  {stage}: {count} ({pct:.1f}%)")
    
    if stats['rejection_reasons']:
        print(f"\nTop Rejection Reasons:")
        for reason, count in sorted(stats['rejection_reasons'].items(), key=lambda x: -x[1])[:10]:
            pct = count / stats['decision_engine_rejected'] * 100 if stats['decision_engine_rejected'] > 0 else 0
            print(f"  {reason}: {count} ({pct:.1f}%)")
    
    # Diagnosis
    print("\n" + "="*70)
    print("DIAGNOSIS")
    print("="*70)
    
    if stats['decision_engine_success'] > 0:
        print(f"\n✓ The pipeline IS generating {stats['decision_engine_success']} trade signals!")
        print("  The issue may be in trade execution or position management.")
    else:
        print("\n✗ NO trade signals are being generated. Root cause analysis:")
        
        # Check if AMT levels are being calculated
        if stats['amt_levels_calculated'] == 0:
            print("\n  PRIMARY ISSUE: AMT levels not calculated")
            print("  - No candle data available for volume profile calculation")
            print("  - Check market_candles table has data for this symbol/timeframe")
        elif stats['position_above'] == 0 and stats['position_below'] == 0:
            print("\n  PRIMARY ISSUE: Price always inside value area")
            print("  - AMT strategies require price to be above VAH or below VAL")
            print("  - This period may not have had value area breakouts")
            print("  - Try a different date range with more volatility")
        elif stats['profile_selection_failed'] > stats['profile_selection_success']:
            print("\n  PRIMARY ISSUE: Profile selection is failing")
            print("  - Check profile conditions vs market data")
            print("  - Check hard filter thresholds in RouterConfig")
        elif stats['rejection_stages']:
            top_stage = max(stats['rejection_stages'].items(), key=lambda x: x[1])[0]
            print(f"\n  PRIMARY ISSUE: Signals blocked at '{top_stage}' stage")
            
            if top_stage == "data_readiness":
                print("  - Data quality checks are failing")
                print("  - Check if features have required fields (price, bid, ask, depth)")
            elif top_stage == "global_gate":
                print("  - Global safety checks are failing")
                print("  - Check spread, depth, and staleness thresholds")
            elif top_stage == "ev_gate":
                print("  - EV calculation is rejecting signals")
                print("  - Check if signals have stop_loss and take_profit")
                print("  - Check if EV threshold is too high")
            elif top_stage == "signal_check":
                print("  - Strategy is not generating signals")
                print("  - Check strategy conditions and entry criteria")
                print("  - AMT strategies need: position_in_value='above'/'below', rotation_factor > threshold")
            elif top_stage == "strategy_trend_alignment":
                print("  - Signals are being rejected for trend mismatch")
                print("  - Check trend_direction calculation")
            else:
                print(f"  - Check the '{top_stage}' stage configuration")
    
    return 0


def main():
    """Main entry point."""
    return asyncio.run(diagnose())


if __name__ == "__main__":
    sys.exit(main())
