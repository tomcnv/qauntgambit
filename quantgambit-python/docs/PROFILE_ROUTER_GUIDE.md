# Profile Router Guide

The Profile Router is the core decision engine that selects the appropriate trading profile based on current market conditions. This document explains how it works, what parameters it uses, and how profiles are scored and selected.

## Overview

The Profile Router implements a **context-based profile selection** system that:

1. Aggregates market data into a **ContextVector**
2. Scores all registered profiles against the current context
3. Applies **rule-based filters** (hard constraints)
4. Calculates a **base score** (soft matching)
5. Adjusts scores based on **historical performance**
6. Returns the top-K matching profiles

Each profile maps to specific **strategies** that are appropriate for that market condition.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Market Data                               │
│  (Orderbook, Trades, Candles, HTF Indicators, AMT Metrics)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ContextVector                               │
│  (Aggregated market state: trend, volatility, session, etc.)    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ProfileRouter                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Rule Filters   │→ │  Base Scoring   │→ │ Perf Adjustment │  │
│  │ (Hard Constraints)│ │ (Soft Matching) │  │ (Win Rate, PnL) │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Selected Profile                              │
│  (e.g., "overnight_thin" → strategies: overnight_thin, low_vol) │
└─────────────────────────────────────────────────────────────────┘
```

## ContextVector Parameters

The ContextVector aggregates all market data into a single object for profile scoring.

### Price Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `price` | float | Current mid price |
| `price_change_1s` | float | Price change over 1 second |
| `price_change_5s` | float | Price change over 5 seconds |
| `price_change_30s` | float | Price change over 30 seconds |
| `price_change_1m` | float | Price change over 1 minute |
| `price_change_5m` | float | Price change over 5 minutes |
| `price_change_1h` | float | Price change over 1 hour |

### Trend Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `ema_fast_15m` | float | Fast EMA on 15-minute timeframe |
| `ema_slow_15m` | float | Slow EMA on 15-minute timeframe |
| `ema_spread_pct` | float | (fast - slow) / price |
| `trend_strength` | float | Absolute EMA spread (0.0 to 1.0) |
| `trend_direction` | str | `"up"`, `"down"`, or `"flat"` |

**Trend Direction Classification:**
- `"up"`: EMA spread > 0.1% (10 bps)
- `"down"`: EMA spread < -0.1% (-10 bps)
- `"flat"`: EMA spread between -0.1% and 0.1%

### Volatility Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `atr_5m` | float | 5-minute ATR (Average True Range) |
| `atr_5m_baseline` | float | Historical baseline ATR |
| `atr_ratio` | float | Current ATR / Baseline ATR |
| `volatility_regime` | str | `"low"`, `"normal"`, or `"high"` |
| `realized_vol_1m` | float | 1-minute realized volatility |
| `market_regime` | str | `"range"`, `"breakout"`, `"squeeze"`, `"chop"` |
| `regime_family` | str | `"trend"`, `"mean_revert"`, `"avoid"` |

**Volatility Regime Classification:**
- `"low"`: ATR ratio < 0.7
- `"normal"`: ATR ratio 0.7 to 1.3
- `"high"`: ATR ratio > 1.3

### AMT (Auction Market Theory) Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `value_area_high` | float | VAH price level |
| `value_area_low` | float | VAL price level |
| `point_of_control` | float | POC price level (highest volume) |
| `rotation_factor` | float | Orderflow rotation strength (-10 to +10) |
| `position_in_value` | str | `"above"`, `"below"`, or `"inside"` |
| `distance_to_vah_pct` | float | Distance to VAH as % of price |
| `distance_to_val_pct` | float | Distance to VAL as % of price |
| `distance_to_poc_pct` | float | Distance to POC as % of price |

**Position in Value Classification:**
- `"above"`: Price > VAH
- `"below"`: Price < VAL
- `"inside"`: VAL ≤ Price ≤ VAH

### Orderbook Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `spread` | float | Bid-ask spread as decimal |
| `spread_bps` | float | Bid-ask spread in basis points |
| `bid_depth_usd` | float | Total bid depth in USD |
| `ask_depth_usd` | float | Total ask depth in USD |
| `orderbook_imbalance` | float | (bid - ask) / (bid + ask), range -1 to +1 |

### Order Flow Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `trades_per_second` | float | Trade frequency |
| `buy_volume_1m` | float | Buy volume over 1 minute |
| `sell_volume_1m` | float | Sell volume over 1 minute |
| `volume_imbalance` | float | (buy - sell) / (buy + sell) |

### Session Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `session` | str | `"asia"`, `"europe"`, `"us"`, `"overnight"` |
| `hour_utc` | int | Current hour in UTC (0-23) |
| `is_market_hours` | bool | Whether in active market hours |

**Session Classification (UTC):**
- `"asia"`: 00:00 - 08:00 UTC
- `"europe"`: 08:00 - 14:00 UTC
- `"us"`: 14:00 - 21:00 UTC
- `"overnight"`: 21:00 - 00:00 UTC

### Risk Features

| Parameter | Type | Description |
|-----------|------|-------------|
| `daily_pnl` | float | Current day's P&L |
| `risk_mode` | str | `"normal"`, `"protection"`, `"recovery"`, `"off"` |
| `open_positions` | int | Number of open positions |
| `account_equity` | float | Current account equity |

## Profile Conditions (Rule Filters)

Each profile defines conditions that must be met for selection. These are **hard constraints** - if any condition fails, the profile is rejected.

### Trend Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `required_trend` | str | Must match: `"up"`, `"down"`, or `"flat"` |
| `min_trend_strength` | float | Minimum EMA spread (e.g., 0.002 = 20 bps) |
| `max_trend_strength` | float | Maximum EMA spread |

### Volatility Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `required_volatility` | str | Must match: `"low"`, `"normal"`, or `"high"` |
| `min_volatility` | float | Minimum ATR ratio |
| `max_volatility` | float | Maximum ATR ratio |

### Value Area Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `required_value_location` | str | Must match: `"above"`, `"below"`, or `"inside"` |
| `min_distance_from_vah` | float | Minimum distance from VAH (decimal) |
| `min_distance_from_val` | float | Minimum distance from VAL (decimal) |
| `min_distance_from_poc` | float | Minimum distance from POC (decimal) |

### Session Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `required_session` | str | Must match: `"asia"`, `"europe"`, `"us"`, `"overnight"` |
| `allowed_sessions` | list | List of allowed sessions |

### Microstructure Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `max_spread` | float | Maximum spread (decimal, e.g., 0.0003 = 3 bps) |
| `min_spread` | float | Minimum spread |
| `min_trades_per_second` | float | Minimum trade frequency |
| `min_orderbook_depth` | float | Minimum depth in USD |

### Rotation Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `min_rotation_factor` | float | Minimum rotation (positive = bullish) |
| `max_rotation_factor` | float | Maximum rotation (negative = bearish) |

### Regime Conditions

| Condition | Type | Description |
|-----------|------|-------------|
| `allowed_regimes` | list | Allowed market regimes: `["trend", "mean_revert", "avoid"]` |
| `required_risk_mode` | str | Required risk mode |

## Scoring Algorithm

### Step 1: Rule-Based Filtering

Each profile's conditions are checked against the ContextVector. If any condition fails, the profile is **rejected** with a score of 0.

```python
# Example rejection reasons:
"trend_mismatch: need up, got flat"
"vol_too_low: 0.65 < 0.70"
"session_mismatch: need asia, got us"
"spread_too_wide: 15.0bp > 3.0bp"
```

### Step 2: Base Score Calculation

For profiles that pass all filters, a base score (0.0 to 1.0) is calculated:

```python
score = 0.5  # Start at neutral

# Alignment bonuses (+0.1 each)
if required_trend == context.trend_direction:
    score += 0.1
if required_volatility == context.volatility_regime:
    score += 0.1
if required_value_location == context.position_in_value:
    score += 0.1
if required_session == context.session:
    score += 0.1

# Rotation strength bonus (up to +0.1)
if rotation_factor > min_rotation_factor:
    score += min(0.1, excess / 10.0)

# Spread tightness bonus (up to +0.1)
if spread_bps < max_spread_bps:
    score += min(0.1, margin / 50.0)
```

### Step 3: Performance Adjustment

Historical performance adjusts the score with a multiplier (0.5 to 1.5):

```python
# Requires at least 10 trades for adjustment
if trades >= 10:
    multiplier = 0.5 + win_rate  # Win rate 0-100% → 0.5-1.5
    
    if avg_pnl > 0:
        multiplier += 0.2  # Bonus for profitable
    
    if recent_losing:
        multiplier *= 0.8  # Penalty for recent losses
```

### Step 4: Final Score

```python
final_score = base_score * performance_multiplier
# Clamped to range [0.0, 1.0]
```

## Example Profiles

### 1. Micro-Range Mean Reversion

**When to use:** Low volatility, tight spreads, price inside value area

```python
ProfileConditions(
    required_volatility="low",
    max_spread=0.0003,  # 3 bps
    required_value_location="inside",
    min_trades_per_second=0.5,
)
strategy_ids=["mean_reversion_fade", "poc_magnet_scalp"]
```

### 2. Early Trend Ignition

**When to use:** Normal volatility, emerging trend, strong rotation

```python
ProfileConditions(
    min_trend_strength=0.002,  # 20 bps EMA spread
    required_volatility="normal",
    min_rotation_factor=3.0,
)
strategy_ids=["trend_pullback", "breakout_scalp"]
```

### 3. Overnight Thin

**When to use:** Overnight session, conservative trading in thin liquidity

```python
ProfileConditions(
    required_session="overnight",
    max_spread=0.001,  # 10 bps
)
strategy_ids=["overnight_thin", "low_vol_grind"]
```

### 4. Breakout Continuation

**When to use:** High volatility, price above value area, strong momentum

```python
ProfileConditions(
    required_value_location="above",
    min_rotation_factor=4.0,
    required_volatility="high",
)
strategy_ids=["breakout_scalp", "high_vol_breakout"]
```

### 5. Asia Range Scalp

**When to use:** Asia session, low volatility, range-bound

```python
ProfileConditions(
    required_session="asia",
    required_volatility="low",
    required_value_location="inside",
)
strategy_ids=["asia_range_scalp", "low_vol_grind"]
```

## Profile-to-Strategy Mapping

Each profile defines which strategies are appropriate for its market conditions:

| Profile | Strategies |
|---------|------------|
| `micro_range_mean_reversion` | `mean_reversion_fade`, `poc_magnet_scalp` |
| `early_trend_ignition` | `trend_pullback`, `breakout_scalp` |
| `late_trend_exhaustion` | `mean_reversion_fade` |
| `breakout_continuation` | `breakout_scalp`, `high_vol_breakout` |
| `overnight_thin` | `overnight_thin`, `low_vol_grind` |
| `asia_range_scalp` | `asia_range_scalp`, `low_vol_grind` |
| `europe_open_vol` | `europe_open_vol`, `opening_range_breakout` |
| `us_open_momentum` | `us_open_momentum`, `trend_pullback` |
| `value_area_rejection` | `amt_value_area_rejection_scalp` |
| `poc_magnet` | `poc_magnet_scalp`, `vwap_reversion` |

## Usage in Backtesting

When running a backtest with `strategy_id: "all"` or `strategy_id: null`, the backtest executor:

1. Builds a ContextVector from historical data
2. Calls `ProfileRouter.select_profiles(context, top_k=1)`
3. Gets the selected profile's `strategy_ids`
4. Only evaluates those specific strategies for signal generation

This ensures backtests accurately reflect live bot behavior.

```python
# Example backtest flow
context = build_context_from_snapshot(snapshot, symbol)
selected_profiles = profile_router.select_profiles(context, top_k=1)

if selected_profiles:
    profile_spec = registry.get_spec(selected_profiles[0].profile_id)
    strategies_to_use = {
        sid: STRATEGIES[sid]
        for sid in profile_spec.strategy_ids
        if sid in STRATEGIES
    }
```

## Observability

The ProfileRouter tracks:

- **Selection History:** Last 20 profile selections per symbol
- **Rejection Reasons:** Why profiles were not selected
- **Performance Stats:** Win rate, PnL, trade count per profile/symbol

Access via `router.get_all_metrics()`:

```python
{
    'total_trades': 150,
    'overall_win_rate': 52.3,
    'total_pnl': 1234.56,
    'active_profiles': 8,
    'registered_profiles': 23,
    'top_profiles': [...],
    'rejection_summary': {...},
    'top_rejection_reasons': [
        ('session_mismatch', 1234),
        ('vol_mismatch', 567),
        ...
    ]
}
```

## Registered Profiles

The system includes 23 canonical profiles covering different market conditions:

1. `micro_range_mean_reversion` - Low vol, tight range scalping
2. `early_trend_ignition` - Catch momentum at trend start
3. `late_trend_exhaustion` - Fade overextended trends
4. `stop_run_fade` - Fade liquidity hunts
5. `breakout_continuation` - Follow confirmed breakouts
6. `vwap_reversion` - Mean reversion to VWAP
7. `spread_compression_scalp` - Ultra-tight spread scalping
8. `vol_expansion_breakout` - Trade volatility breakouts
9. `asia_range_scalp` - Asia session range trading
10. `europe_open_vol` - Europe session volatility
11. `us_open_momentum` - US market open momentum
12. `overnight_thin` - Conservative overnight trading
13. `tight_range_compression` - Ultra-low vol compression
14. `range_breakout_anticipation` - Position for breakouts
15. `value_area_rejection` - Fade VAH/VAL rejections
16. `poc_magnet` - Trade toward POC
17. `trend_continuation_pullback` - Buy dips in uptrend
18. `momentum_breakout` - Ride strong momentum
19. `trend_acceleration` - Scalp in trend direction
20. `opening_range_breakout` - Trade first 30min range
21. `midvol_mean_reversion` - Normal vol mean reversion
22. `midvol_expansion` - Normal vol expansion
23. `range_market_scalp` - Range-bound scalping
