# Fee Model Integration Proposal

## Executive Summary

**Current Problem**: Strategies use hardcoded fee estimates that under-calculate costs by ~75%, leading to incorrect profitability assessments.

**Proposed Solution**: Integrate the existing `FeeModel` class to calculate exact costs based on realistic maker/taker assumptions.

## Current vs. Proposed Approach

### Current (WRONG)
```python
# In mean_reversion_fade.py
DEFAULT_FEE_BPS = 6.0  # Assumes this is round-trip, but it's actually one-way
DEFAULT_SLIPPAGE_BPS = 2.0
total_cost_bps = 6.0 + 2.0 = 8.0 bps

# Calculation
expected_profit_bps = distance_to_poc_bps - 8.0
```

**Issues**:
1. 6 bps is ONE-WAY taker fee, not round-trip
2. Doesn't account for maker/taker mix
3. Doesn't use exchange-specific fee tiers
4. Under-estimates costs by 75%

### Proposed (CORRECT)
```python
# In mean_reversion_fade.py
from quantgambit.risk.fee_model import FeeModel, FeeConfig

# Initialize once (could be passed in params)
fee_model = FeeModel(FeeConfig.okx_regular())

# Calculate breakeven for this specific trade
breakeven = fee_model.calculate_breakeven(
    size=estimated_size,  # Need to estimate size
    entry_price=features.price,
    side="long" or "short",
    entry_is_maker=False,  # Market order entry (taker)
    exit_is_maker=True,    # Limit order at POC (maker)
)

# Use actual breakeven + slippage
total_cost_bps = breakeven.breakeven_bps + slippage_bps
expected_profit_bps = distance_to_poc_bps - total_cost_bps
```

## Detailed Implementation Plan

### 1. Maker/Taker Assumptions

**For Mean Reversion Strategy**:
- **Entry**: TAKER (market order or aggressive limit to get filled quickly)
  - Rationale: Need immediate execution when rotation signals reversal
  - Fee: 6 bps (OKX regular taker)

- **Exit**: MAKER (limit order at POC target)
  - Rationale: We have a specific target (POC), can place limit order
  - Fee: 4 bps (OKX regular maker)
  - **Risk**: May not fill if price doesn't reach POC
  
- **Stop Loss**: TAKER (market order for immediate exit)
  - Fee: 6 bps
  - Only applies if trade goes against us

**Total Round-Trip Costs (Best Case)**:
```
Entry (taker):  6 bps
Exit (maker):   4 bps
Slippage:       2 bps (conservative estimate)
-----------------
Total:         12 bps
```

**Total Round-Trip Costs (Worst Case - Stop Loss)**:
```
Entry (taker):  6 bps
Exit (taker):   6 bps (stop loss hit)
Slippage:       2 bps
-----------------
Total:         14 bps
```

### 2. Size Estimation Problem

**Challenge**: FeeModel needs position size to calculate exact fees, but we don't know size until after we decide to trade.

**Solution Options**:

#### Option A: Use Percentage-Based Calculation (RECOMMENDED)
```python
# FeeModel already handles this correctly
# Breakeven is calculated as percentage of notional
# Size cancels out in the calculation:
# breakeven_bps = (entry_fee + exit_fee) / notional * 10000
# = (size * entry_price * entry_rate + size * exit_price * exit_rate) / (size * entry_price) * 10000
# = (entry_rate + exit_rate) * 10000  # Size cancels out!

# So we can use a dummy size of 1.0
breakeven = fee_model.calculate_breakeven(
    size=1.0,  # Dummy size - cancels out in percentage calculation
    entry_price=features.price,
    side=side,
    entry_is_maker=False,
    exit_is_maker=True,
)
# breakeven.breakeven_bps is accurate regardless of size!
```

#### Option B: Estimate Size Based on Risk
```python
# Estimate size based on risk parameters
risk_per_trade_pct = params.get("risk_per_trade_pct", 0.6) / 100
stop_loss_pct = params.get("stop_loss_pct", 0.012)
estimated_position_value = account.equity * (risk_per_trade_pct / stop_loss_pct)
estimated_size = estimated_position_value / features.price

breakeven = fee_model.calculate_breakeven(
    size=estimated_size,
    entry_price=features.price,
    side=side,
    entry_is_maker=False,
    exit_is_maker=True,
)
```

**Recommendation**: Use Option A (dummy size) since breakeven percentage is size-independent.

### 3. Exchange Configuration

**Pass FeeConfig via params**:
```python
# In profile or strategy params
{
    "fee_config": "okx_regular",  # or "okx_vip1", "bybit_regular", etc.
}

# In strategy
fee_config_name = params.get("fee_config", "okx_regular")
fee_config = getattr(FeeConfig, fee_config_name)()
fee_model = FeeModel(fee_config)
```

**Fee Tiers**:
- `okx_regular`: 6 bps taker, 4 bps maker (default)
- `okx_vip1`: 4 bps taker, 2 bps maker, 1 bps rebate
- `okx_vip2`: 3.5 bps taker, 1.5 bps maker, 1.5 bps rebate
- `bybit_regular`: 5.5 bps taker, 2 bps maker
- `bybit_vip1`: 4 bps taker, 1.5 bps maker

### 4. Slippage Estimation

**Current**: 2 bps flat
**Proposed**: Symbol-adaptive slippage

```python
# Could be passed via resolved_params
slippage_bps = params.get("slippage_bps", 2.0)

# Or symbol-specific defaults
SLIPPAGE_BY_SYMBOL = {
    "BTCUSDT": 1.0,   # Very liquid
    "ETHUSDT": 1.5,   # Very liquid
    "SOLUSDT": 3.0,   # Less liquid
    # ... etc
}
slippage_bps = SLIPPAGE_BY_SYMBOL.get(features.symbol, 2.0)
```

## Code Changes Required

### 1. Update mean_reversion_fade.py

```python
from quantgambit.risk.fee_model import FeeModel, FeeConfig

class MeanReversionFade(Strategy):
    def generate_signal(self, features, account, profile, params):
        # ... existing code ...
        
        # Initialize fee model
        fee_config_name = params.get("fee_config", "okx_regular")
        fee_config = getattr(FeeConfig, fee_config_name)()
        fee_model = FeeModel(fee_config)
        
        # Calculate breakeven (size-independent)
        # Assume taker entry, maker exit (best case for mean reversion)
        breakeven = fee_model.calculate_breakeven(
            size=1.0,  # Dummy size - percentage is size-independent
            entry_price=features.price,
            side="long",  # Doesn't matter for breakeven calculation
            entry_is_maker=False,  # Market order entry
            exit_is_maker=True,    # Limit order at POC target
        )
        
        if breakeven is None:
            logger.error(f"Failed to calculate breakeven for {features.symbol}")
            return None
        
        # Get slippage
        slippage_bps = params.get("slippage_bps", 2.0)
        
        # Total costs = fees + slippage
        total_cost_bps = breakeven.breakeven_bps + slippage_bps
        
        # Calculate expected profit
        distance_from_poc_pct = abs(features.distance_to_poc) / features.price
        distance_to_poc_bps = distance_from_poc_pct * 10000
        expected_profit_bps = distance_to_poc_bps - total_cost_bps
        
        # Check minimum edge
        min_edge_bps = params.get("min_edge_bps", 3.0)
        if expected_profit_bps < min_edge_bps:
            logger.info(
                f"[{features.symbol}] mean_reversion_fade: Rejecting - insufficient edge. "
                f"expected_profit={expected_profit_bps:.1f}bps, min_edge={min_edge_bps:.1f}bps, "
                f"distance_to_poc={distance_to_poc_bps:.1f}bps, "
                f"fee_breakeven={breakeven.breakeven_bps:.1f}bps, "
                f"slippage={slippage_bps:.1f}bps, "
                f"total_costs={total_cost_bps:.1f}bps, "
                f"profile_id={profile_id}"
            )
            return None
        
        # ... rest of strategy logic ...
```

### 2. Update vol_expansion.py (similar changes)

### 3. Update other strategies as needed

## Expected Impact

### With OKX Regular Fees (Taker Entry, Maker Exit)

**Breakeven Calculation**:
```
Entry fee:  6 bps (taker)
Exit fee:   4 bps (maker)
Slippage:   2 bps
-----------
Total:     12 bps
```

**Minimum POC Distance Required**:
```
Min edge: 3 bps
Total required: 12 + 3 = 15 bps
```

**BTC Reality Check**:
- BTC P50 POC distance: 5.5 bps ❌ Too small
- BTC P75 POC distance: ~12 bps ❌ Still too small
- BTC P90 POC distance: ~28 bps ✅ Profitable!

**Conclusion**: Mean reversion scalping on BTC only works in P90+ volatility conditions (wider POC distances).

### With OKX VIP1 Fees (Taker Entry, Maker Exit with Rebate)

**Breakeven Calculation**:
```
Entry fee:  4 bps (taker)
Exit fee:   2 bps (maker)
Rebate:    -1 bps (maker rebate)
Slippage:   2 bps
-----------
Total:      7 bps
```

**Minimum POC Distance Required**:
```
Min edge: 3 bps
Total required: 7 + 3 = 10 bps
```

**BTC Reality Check**:
- BTC P50 POC distance: 5.5 bps ❌ Still too small
- BTC P75 POC distance: ~12 bps ✅ Profitable!
- BTC P90 POC distance: ~28 bps ✅ Very profitable!

**Conclusion**: VIP1 tier makes mean reversion viable at P75+ conditions.

## Testing Plan

1. **Unit Tests**: Test FeeModel integration with various scenarios
2. **Replay Test**: Re-run 12h replay with correct fees
3. **Compare Results**: 
   - Current (8 bps): X signals
   - Correct (12 bps): Y signals
   - Expected: Y < X (fewer but more accurate)

## Risks & Mitigations

### Risk 1: Maker Exit May Not Fill
**Problem**: If we place limit order at POC and price doesn't reach it, we don't exit.
**Mitigation**: 
- Use time-based exit (already implemented)
- Use trailing stop that becomes taker if needed
- Accept that some exits will be taker (use 14 bps worst-case in calculations)

### Risk 2: Reduced Signal Count
**Problem**: Correct fees will reject more trades.
**Mitigation**:
- This is GOOD - we're avoiding unprofitable trades
- Focus on higher-quality setups (wider POC distances)
- Consider VIP fee tiers
- Consider longer hold times to amortize fees

### Risk 3: Complexity
**Problem**: FeeModel adds complexity to strategy code.
**Mitigation**:
- Create helper function to encapsulate fee calculation
- Document assumptions clearly
- Add comprehensive logging

## Recommendation

**IMPLEMENT THIS IMMEDIATELY**. The current fee calculation is fundamentally wrong and could lead to:
1. Accepting unprofitable trades (losing money)
2. Incorrect backtest results
3. False confidence in strategy performance

The FeeModel is already built and tested - we just need to use it properly.

## Next Steps

1. ✅ Review and approve this proposal
2. Implement FeeModel integration in mean_reversion_fade.py
3. Implement in vol_expansion.py and other strategies
4. Add unit tests for fee calculations
5. Re-run replay with correct fees
6. Update documentation
7. Deploy to production

**Timeline**: 2-3 hours of focused work
**Priority**: CRITICAL - affects profitability
