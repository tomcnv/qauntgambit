# Fee Calculation Analysis

## Current Implementation

### Strategy-Level Fee Calculation (mean_reversion_fade.py)

```python
DEFAULT_FEE_BPS = 6.0  # Round-trip fees (~0.06% taker)
DEFAULT_SLIPPAGE_BPS = 2.0  # Expected slippage
total_cost_bps = fee_bps + slippage_bps  # = 8.0 bps
```

### Fee Model (fee_model.py)

```python
# Default OKX Regular Fees
taker_fee_rate = 0.0006  # 0.06% = 6 bps per side
maker_fee_rate = 0.0004  # 0.04% = 4 bps per side
```

## Problem Analysis

### Issue 1: Double-Counting Fees ❌

**Strategy assumes**: `fee_bps = 6.0` is the **round-trip** fee
**Reality**: 6 bps is the **one-way** taker fee

**Correct calculation**:
- Entry (taker): 6 bps
- Exit (taker): 6 bps
- **Round-trip**: 12 bps (not 6 bps!)

**Current behavior**:
```python
total_cost_bps = 6.0 + 2.0 = 8.0 bps
```

**Should be**:
```python
total_cost_bps = 12.0 + 2.0 = 14.0 bps  # Entry + Exit + Slippage
```

### Issue 2: Not Accounting for Maker/Taker Mix

The strategy assumes all orders are takers, but in reality:
- **Entry**: Often taker (market order or aggressive limit)
- **Exit**: Could be maker (limit order at target) or taker (stop loss)

**Best case** (both maker):
- Entry: 4 bps
- Exit: 4 bps
- Round-trip: 8 bps

**Worst case** (both taker):
- Entry: 6 bps
- Exit: 6 bps
- Round-trip: 12 bps

**Typical case** (entry taker, exit maker):
- Entry: 6 bps
- Exit: 4 bps
- Round-trip: 10 bps

### Issue 3: Slippage Estimation

`DEFAULT_SLIPPAGE_BPS = 2.0` seems reasonable for liquid pairs like BTC/ETH, but:
- Should be **per side** (entry + exit = 4 bps total)
- Or should be **round-trip** (2 bps total)

Current code treats it as round-trip, which is correct if 2 bps is the total.

## Impact on Trading

### Current Calculation (WRONG)
```
Expected profit = distance_to_poc_bps - total_cost_bps
                = distance_to_poc_bps - 8.0 bps
Min edge = 3.0 bps (after relaxation)
Required distance = 8.0 + 3.0 = 11.0 bps
```

### Correct Calculation (SHOULD BE)
```
Expected profit = distance_to_poc_bps - total_cost_bps
                = distance_to_poc_bps - 14.0 bps  # (12 fee + 2 slippage)
Min edge = 3.0 bps
Required distance = 14.0 + 3.0 = 17.0 bps
```

### Real-World Example from Logs

```
[ETHUSDT] mean_reversion_fade: Rejecting - insufficient edge. 
expected_profit=-1.7bps, min_edge=5.0bps, 
distance_to_poc=6.3bps, costs=8.0bps
```

**Current calculation**:
- Distance to POC: 6.3 bps
- Costs: 8.0 bps
- Expected profit: 6.3 - 8.0 = -1.7 bps ❌ REJECTED

**Correct calculation**:
- Distance to POC: 6.3 bps
- Costs: 14.0 bps (12 fee + 2 slippage)
- Expected profit: 6.3 - 14.0 = -7.7 bps ❌ STILL REJECTED (but more accurate)

## Why This Matters

### 1. We're UNDER-estimating costs
- Current: 8.0 bps total cost
- Actual: 14.0 bps total cost (75% higher!)
- This means we're accepting trades that will lose money

### 2. We're rejecting trades correctly, but for wrong reasons
- The replay showed 0 signals generated
- This is actually CORRECT behavior if costs are 14 bps
- BTC P50 POC distance is 0.055% = 5.5 bps
- 5.5 bps < 14 bps → No profitable trades!

### 3. The "dead zone" is actually a "no-profit zone"
- ATR 1.0-2.0 range has tight POC distances (5-15 bps for BTC/ETH)
- With 14 bps round-trip costs, most mean reversion trades are unprofitable
- This explains why the original system had 0 trades

## Recommendations

### Option 1: Fix the Fee Calculation (CORRECT)
```python
DEFAULT_FEE_BPS = 12.0  # Round-trip taker fees (6 bps * 2)
DEFAULT_SLIPPAGE_BPS = 2.0  # Round-trip slippage
total_cost_bps = 12.0 + 2.0 = 14.0 bps
```

### Option 2: Use Fee Model Properly
```python
from quantgambit.risk.fee_model import FeeModel, FeeConfig

fee_model = FeeModel(FeeConfig.okx_regular())
breakeven = fee_model.calculate_breakeven(
    size=size,
    entry_price=entry_price,
    side=side,
    entry_is_maker=False,  # Assume taker entry
    exit_is_maker=True,    # Assume maker exit (limit at POC)
)
total_cost_bps = breakeven.breakeven_bps + slippage_bps
```

### Option 3: Optimize for Maker Exits
If we can reliably get maker fills on exits (limit orders at POC):
```python
# Entry: 6 bps (taker)
# Exit: 4 bps (maker)
# Round-trip: 10 bps
DEFAULT_FEE_BPS = 10.0
DEFAULT_SLIPPAGE_BPS = 2.0
total_cost_bps = 12.0 bps
```

## Verification Needed

1. **Check actual exchange fees**: Confirm OKX/Bybit fee tiers
2. **Measure actual slippage**: Analyze historical fills vs. expected prices
3. **Measure maker/taker ratio**: What % of exits are makers vs. takers?
4. **Backtest with correct fees**: Re-run replay with 14 bps costs

## Conclusion

**The fee calculation is WRONG and UNDER-estimating costs by ~75%.**

This is actually GOOD NEWS because:
1. The system is correctly rejecting unprofitable trades
2. We're not losing money on bad trades
3. The "dead zone" is real - tight POC distances don't provide enough edge

**The BAD NEWS**:
1. Mean reversion scalping on BTC/ETH may not be profitable with current fee structure
2. We need either:
   - Wider POC distances (higher volatility)
   - Lower fees (VIP tier, maker rebates)
   - Different strategy (trend following, breakouts)
   - Longer hold times (reduce fee impact)

**CRITICAL**: We must fix the fee calculation before going live, or we'll accept unprofitable trades.
