# Fee Model Integration - Phase 3 Complete

## Summary

Phase 3 (EVGate Integration) has been successfully completed. The EVGate now uses ExecutionPolicy and SlippageModel from Phase 2 for accurate, market-state-adaptive cost estimation.

## Changes Made

### 1. Updated CostEstimator Class

**File**: `quantgambit/signals/stages/ev_gate.py`

**Changes**:
- Added Phase 2 model dependencies (FeeModel, ExecutionPolicy, SlippageModel)
- Completely rewrote `estimate()` method to use Phase 2 models
- Removed old hardcoded fee calculation logic
- Added support for market-state-adaptive slippage
- Added adverse selection cost calculation

**New Signature**:
```python
def estimate(
    self,
    symbol: str,
    strategy_id: str,
    setup_type: str,
    entry_price: float,
    exit_price: float,
    size: float,
    best_bid: float,
    best_ask: float,
    order_size_usd: float,
    volatility_regime: Optional[str] = None,
    spread_percentile: Optional[float] = None,
    bid_depth_usd: Optional[float] = None,
    ask_depth_usd: Optional[float] = None,
    hold_time_expected_sec: float = 300.0,
) -> CostEstimate
```

**Cost Calculation Flow**:
1. Get ExecutionPlan from ExecutionPolicy based on strategy type
2. Calculate expected fees using `calculate_expected_fees_bps()` with maker/taker probabilities
3. Calculate adaptive slippage using SlippageModel with market state
4. Calculate adverse selection using `calculate_adverse_selection_bps()`
5. Sum all components: `total_bps = fee_bps + spread_bps + slippage_bps + adverse_selection_bps`

### 2. Updated EVGate._evaluate() Method

**Changes**:
- Updated cost estimation call to use new CostEstimator signature
- Added strategy info extraction for ExecutionPolicy
- Added market state extraction for SlippageModel
- Added hold time estimation based on strategy type

**New Helper Methods**:
- `_extract_setup_type()`: Extracts setup type from strategy_id or meta_reason
- `_estimate_hold_time()`: Estimates expected hold time based on strategy type

### 3. Enhanced Cost Logging

**File**: `quantgambit/signals/stages/ev_gate.py`

**Changes**:
- Updated `_log_decision()` to log all cost components separately
- Added individual logging for: fee_bps, spread_bps, slippage_bps, adverse_selection_bps
- Maintained total_cost_bps logging
- Added adjustment_factor and adjustment_reason logging

**Log Output Example**:
```python
log_info(
    "ev_gate_decision",
    symbol="BTCUSDT",
    decision="ACCEPT",
    p=0.65,
    p_min=0.55,
    R=2.0,
    C=0.13,
    EV=0.17,
    ev_min=0.02,
    L_bps=100.0,
    G_bps=200.0,
    fee_bps=10.6,           # NEW: Detailed cost breakdown
    spread_bps=0.4,         # NEW
    slippage_bps=1.2,       # NEW
    adverse_selection_bps=1.0,  # NEW
    total_cost_bps=13.2,
    mode="enforce",
)
```

### 4. Added Imports

**File**: `quantgambit/signals/stages/ev_gate.py`

**New Imports**:
```python
from quantgambit.execution.execution_policy import ExecutionPolicy, calculate_expected_fees_bps
from quantgambit.risk.slippage_model import SlippageModel, calculate_adverse_selection_bps
from quantgambit.risk.fee_model import FeeModel, FeeConfig
```

## Test Coverage

**File**: `tests/test_ev_gate_phase3_integration.py`

**Tests Added** (11 tests, all passing):

### CostEstimator Integration Tests:
1. `test_cost_estimator_uses_execution_policy`: Verifies ExecutionPolicy integration
2. `test_cost_estimator_uses_slippage_model`: Verifies SlippageModel integration
3. `test_cost_estimator_includes_adverse_selection`: Verifies adverse selection calculation
4. `test_cost_estimator_different_strategies`: Verifies different strategies get different costs

### EVGate Integration Tests:
5. `test_ev_gate_calculates_c_correctly`: Verifies C = total_cost_bps / SL_distance_bps
6. `test_ev_gate_logs_all_cost_components`: Verifies all cost components are logged
7. `test_ev_gate_accepts_profitable_signal`: Verifies acceptance with good EV
8. `test_ev_gate_rejects_unprofitable_signal`: Verifies rejection with poor EV
9. `test_ev_gate_cost_increases_with_volatility`: Verifies costs adapt to volatility

### Helper Method Tests:
10. `test_extract_setup_type`: Verifies setup type extraction
11. `test_estimate_hold_time`: Verifies hold time estimation

**Test Results**: ✅ 11/11 passing

## Cost Comparison

### Before Phase 3 (Old CostEstimator):
- Hardcoded execution policy ("taker_only", "maker_first", "hybrid")
- Fixed slippage (min_slippage_bps floor only)
- Fixed adverse selection (config parameter)
- No strategy-specific adaptation

**Example Cost**: ~11-12 bps (fixed)

### After Phase 3 (New CostEstimator):
- Dynamic execution policy based on strategy type
- Market-state-adaptive slippage (spread, depth, volatility)
- Dynamic adverse selection (symbol, volatility, hold time)
- Strategy-specific execution plans

**Example Cost**: ~13-15 bps (adaptive)

### Cost Breakdown Example (Mean Reversion, Normal Volatility):
```
Fee:                10.6 bps  (0.9*6 + 0.1*4 entry + 0.4*6 + 0.6*4 exit)
Spread:              0.4 bps  (2 bps spread / 2 for half-spread)
Slippage:            1.2 bps  (adaptive: BTC floor 0.5 * factors)
Adverse Selection:   1.0 bps  (BTC base 1.0 * normal vol)
---
Total:              13.2 bps
```

## Architecture Improvements

### Separation of Concerns:
- **ExecutionPolicy**: Owns execution assumptions (maker/taker mix, urgency)
- **SlippageModel**: Owns slippage estimation (market-state-adaptive)
- **FeeModel**: Owns fee calculation (exchange-specific rates)
- **CostEstimator**: Orchestrates all cost components
- **EVGate**: Validates economics using C = total_cost / SL_distance

### Benefits:
1. **No Hardcoded Assumptions**: Execution behavior centralized in ExecutionPolicy
2. **Market-State-Adaptive**: Costs adjust to spread, depth, volatility
3. **Strategy-Specific**: Different strategies get appropriate execution plans
4. **Comprehensive Logging**: All cost components visible for debugging
5. **Testable**: Each component can be tested independently

## Integration Points

### EVGate → CostEstimator:
```python
cost_estimate = self.cost_estimator.estimate(
    symbol=ctx.symbol,
    strategy_id=signal.get("strategy_id"),
    setup_type=self._extract_setup_type(...),
    entry_price=entry_price,
    exit_price=take_profit,
    size=size,
    best_bid=best_bid,
    best_ask=best_ask,
    order_size_usd=order_size_usd,
    volatility_regime=volatility_regime,
    spread_percentile=spread_percentile,
    bid_depth_usd=bid_depth_usd,
    ask_depth_usd=ask_depth_usd,
    hold_time_expected_sec=hold_time_expected_sec,
)
```

### CostEstimator → ExecutionPolicy:
```python
execution_plan = self.execution_policy.plan_execution(
    strategy_id=strategy_id,
    setup_type=setup_type,
)
fee_bps = calculate_expected_fees_bps(
    fee_model=self.fee_model,
    execution_plan=execution_plan,
    entry_price=entry_price,
    exit_price=exit_price,
    size=size,
)
```

### CostEstimator → SlippageModel:
```python
slippage_bps = self.slippage_model.calculate_slippage_bps(
    symbol=symbol,
    spread_bps=spread_bps,
    spread_percentile=spread_percentile,
    book_depth_usd=min(bid_depth_usd, ask_depth_usd),
    order_size_usd=order_size_usd,
    volatility_regime=volatility_regime,
    urgency=execution_plan.entry_urgency,
)
```

## Verification

### Manual Verification:
```python
# Create EVGate with Phase 3 integration
stage = EVGateStage(config=EVGateConfig(mode="enforce", ev_min=0.02))

# Create test signal
ctx = StageContext(
    symbol="BTCUSDT",
    signal={
        "entry_price": 50000.0,
        "stop_loss": 49500.0,  # L = 100 bps
        "take_profit": 51000.0,  # G = 200 bps, R = 2.0
        "side": "long",
        "strategy_id": "mean_reversion_fade",
        "size": 0.1,
    },
    data={
        "market_context": {
            "best_bid": 49999.0,
            "best_ask": 50001.0,
            "volatility_regime": "normal",
        },
        "prediction": {"confidence": 0.65},
    },
)

# Evaluate
result = stage._evaluate(ctx, ctx.signal)

# Verify cost components
assert result.fee_bps > 0
assert result.spread_bps > 0
assert result.slippage_bps >= 0
assert result.adverse_selection_bps > 0
assert result.total_cost_bps == sum([
    result.fee_bps,
    result.spread_bps,
    result.slippage_bps,
    result.adverse_selection_bps,
])

# Verify C calculation
assert result.C == result.total_cost_bps / result.L_bps

# Verify EV calculation
assert result.EV == result.p_calibrated * result.R - (1 - result.p_calibrated) * 1 - result.C
```

## Next Steps (Phase 4: Validation)

1. **Run Replay with New Costs**:
   - Use replay data to test new cost model
   - Compare decision deltas (old vs new)
   - Analyze cost distributions

2. **Validate Cost Distributions**:
   - Verify costs are in reasonable ranges
   - Check P50, P75, P90 percentiles
   - Identify outliers

3. **Compare with Actual Trade Costs**:
   - Match replay costs with actual execution costs
   - Validate fee calculations against exchange data
   - Tune slippage and adverse selection parameters

4. **Add Golden Tests**:
   - Freeze known-good cost calculations
   - Prevent regression in cost estimation
   - Document expected costs for common scenarios

## Files Modified

1. `quantgambit/signals/stages/ev_gate.py` - Updated CostEstimator and EVGate
2. `tests/test_ev_gate_phase3_integration.py` - Added comprehensive tests

## Files Created

1. `FEE_MODEL_INTEGRATION_PHASE3_COMPLETE.md` - This document

## Dependencies

- Phase 1: ExecutionPolicy (`quantgambit/execution/execution_policy.py`)
- Phase 2: SlippageModel (`quantgambit/risk/slippage_model.py`)
- Phase 2: FeeModel (`quantgambit/risk/fee_model.py`)

## Completion Checklist

- [x] Update CostEstimator to use ExecutionPolicy
- [x] Update CostEstimator to use SlippageModel
- [x] Update CostEstimator to use FeeModel
- [x] Update EVGate._evaluate() to use new CostEstimator
- [x] Add helper methods (_extract_setup_type, _estimate_hold_time)
- [x] Enhance cost logging in _log_decision()
- [x] Add comprehensive integration tests
- [x] Verify all tests pass (11/11)
- [x] Document changes and architecture
- [x] Create completion document

## Status

✅ **Phase 3 (EVGate Integration) COMPLETE**

All requirements from V2 Proposal Section 8 (Integration with EVGate) have been implemented and tested.

---

**Date**: 2026-01-14
**Phase**: 3 of 4
**Test Coverage**: 11 tests, 100% passing
**Integration**: ExecutionPolicy + SlippageModel + FeeModel → EVGate
