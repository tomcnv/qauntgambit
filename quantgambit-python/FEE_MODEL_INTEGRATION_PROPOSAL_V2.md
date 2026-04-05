# Fee Model Integration Proposal V2

## Executive Summary

**Current Problem**: Strategies use hardcoded fee estimates that miscalculate costs. Current model assumes 8 bps total cost; realistic cost is ~12-14 bps (50-75% higher), leading to incorrect profitability assessments.

**Proposed Solution**: Integrate FeeModel with ExecutionPolicy to calculate exact costs based on realistic execution paths, and move profitability gating to EVGate to avoid duplicate economics checks.

## 1. Precise Cost Statement

**Current Model**:
```python
DEFAULT_FEE_BPS = 6.0  # Incorrectly treated as round-trip
DEFAULT_SLIPPAGE_BPS = 2.0
total_cost_bps = 8.0
```

**Reality**:
- Entry (taker): 6 bps
- Exit (maker, best case): 4 bps  
- Exit (taker, fallback): 6 bps
- Slippage: 2 bps
- **Total**: 12-14 bps depending on execution path

**Impact**: Current model omits round-trip structure and maker/taker mix; typical cost is ~12-14 bps vs current 8 bps (≈50-75% higher).

## 2. Architecture: Separate Geometry Validation from Economics

### Current (WRONG)
```python
# Strategy does both geometry AND economics
if distance_to_poc_bps - total_cost_bps < min_edge_bps:
    return None  # Duplicate gate with EVGate
```

### Proposed (CORRECT)
```python
# Strategy: Geometry validation only
if distance_to_poc_bps < MIN_GEOMETRIC_DISTANCE:
    return None  # Setup hygiene: POC too close for reliable execution

# EVGate: Economics validation (profitability after costs)
# Incorporates TP/SL asymmetry, slippage, adverse selection, probability
```

**Rationale**: 
- Strategies validate setup geometry (is this a valid pattern?)
- EVGate validates economics (is this profitable after all costs?)
- Avoids conflicting gates and ensures consistent cost accounting

## 3. Unit Clarity: Cost Representations

### Two Cost Representations

**A) Notional-Based (bps of position size)**:
```python
fee_bps_roundtrip = 10.0  # 10 basis points of notional
```
Used by: FeeModel, strategies, logging

**B) SL-Normalized (fraction of stop distance)**:
```python
C = total_cost_bps / stop_loss_distance_bps
```
Used by: EVGate for EV calculation

### Mapping Between Representations
```python
# FeeModel returns breakeven_bps as bps of notional
breakeven_bps = fee_model.calculate_breakeven(...).breakeven_bps

# Add other costs
total_cost_bps = breakeven_bps + slippage_bps + adverse_selection_bps + spread_bps

# EVGate consumes as fraction of SL distance
C = total_cost_bps / stop_loss_distance_bps
```

**Critical**: Document this mapping to prevent implementation drift.

## 4. Size-Independence Validation

### Claim
"Breakeven percentage is size-independent because size cancels out in the calculation."

### Validation Required
```python
# Unit test
def test_fee_breakeven_size_independence():
    """Verify breakeven_bps is size-independent for linear fee structures."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    
    sizes = [0.1, 1.0, 10.0, 100.0, 1000.0]
    results = []
    
    for size in sizes:
        breakeven = fee_model.calculate_breakeven(
            size=size,
            entry_price=50000.0,
            side="long",
            entry_is_maker=False,
            exit_is_maker=True,
        )
        results.append(breakeven.breakeven_bps)
    
    # All results should be equal within epsilon
    assert all(abs(r - results[0]) < 0.01 for r in results), \
        f"Breakeven not size-independent: {results}"
```

### Caveats
Size-independence only holds if:
1. Fees are linear % of notional (no min fees, no tier thresholds)
2. Trading linear USDT perpetuals (not inverse contracts)
3. No contract-specific multipliers

**Action**: Add this test and document instrument assumptions.

## 5. Execution Policy Integration

### Problem
Strategies currently hardcode execution assumptions (maker/taker), which will rot over time.

### Solution: ExecutionPolicy Layer

```python
@dataclass
class ExecutionPlan:
    """Execution plan for a trade."""
    entry_urgency: str  # "immediate", "patient", "passive"
    exit_urgency: str   # "immediate", "patient", "passive"
    
    # Derived probabilities
    p_entry_maker: float  # Probability of maker fill on entry
    p_exit_maker: float   # Probability of maker fill on exit
    
    # Fallback behavior
    entry_timeout_ms: int
    exit_timeout_ms: int

class ExecutionPolicy:
    """Determines execution approach based on strategy intent."""
    
    def plan_execution(
        self,
        strategy_id: str,
        setup_type: str,  # "mean_reversion", "breakout", etc.
        market_state: MarketState,
    ) -> ExecutionPlan:
        """Create execution plan based on strategy and market conditions."""
        
        if setup_type == "mean_reversion":
            # Mean reversion: patient entry, limit exit at target
            return ExecutionPlan(
                entry_urgency="immediate",  # Need quick fill on reversal
                exit_urgency="patient",     # Limit at POC target
                p_entry_maker=0.1,          # Usually taker
                p_exit_maker=0.6,           # Often fills at limit
                entry_timeout_ms=500,
                exit_timeout_ms=30000,
            )
        elif setup_type == "breakout":
            # Breakout: immediate entry, trailing exit
            return ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="immediate",
                p_entry_maker=0.0,  # Always taker
                p_exit_maker=0.2,   # Usually taker
                entry_timeout_ms=200,
                exit_timeout_ms=1000,
            )
        # ... etc
```

### Expected Fee Calculation with Fill Probabilities

```python
def calculate_expected_fees(
    fee_model: FeeModel,
    execution_plan: ExecutionPlan,
    entry_price: float,
    exit_price: float,
    size: float,
) -> float:
    """Calculate expected fees accounting for maker/taker probabilities."""
    
    # Entry expected fee
    entry_fee_maker = fee_model.calculate_entry_fee(size, entry_price, is_maker=True)
    entry_fee_taker = fee_model.calculate_entry_fee(size, entry_price, is_maker=False)
    expected_entry_fee = (
        execution_plan.p_entry_maker * entry_fee_maker +
        (1 - execution_plan.p_entry_maker) * entry_fee_taker
    )
    
    # Exit expected fee
    exit_fee_maker = fee_model.calculate_exit_fee(size, exit_price, is_maker=True)
    exit_fee_taker = fee_model.calculate_exit_fee(size, exit_price, is_maker=False)
    expected_exit_fee = (
        execution_plan.p_exit_maker * exit_fee_maker +
        (1 - execution_plan.p_exit_maker) * exit_fee_taker
    )
    
    return expected_entry_fee + expected_exit_fee
```

**Critical**: FeeModel inputs SHALL be derived from ExecutionPolicy, not hardcoded per strategy.

## 6. Market-State-Adaptive Slippage

### Problem
Current: `slippage_bps = 2.0` (flat, symbol-only)

### Solution: Multi-Factor Slippage Model

```python
@dataclass
class SlippageModel:
    """Calculate expected slippage based on market state."""
    
    # Symbol-specific floors
    SYMBOL_FLOORS = {
        "BTCUSDT": 0.5,
        "ETHUSDT": 0.8,
        "SOLUSDT": 2.0,
    }
    
    def calculate_slippage_bps(
        self,
        symbol: str,
        spread_bps: float,
        spread_percentile: float,  # 0-100
        book_depth_usd: float,
        order_size_usd: float,
        volatility_regime: str,
        urgency: str,  # from ExecutionPlan
    ) -> float:
        """Calculate expected slippage."""
        
        # Base: symbol floor
        base = self.SYMBOL_FLOORS.get(symbol, 2.0)
        
        # Spread component (tight spread = low slippage)
        spread_factor = max(1.0, spread_bps / 2.0)
        
        # Depth component (size vs depth)
        depth_ratio = order_size_usd / book_depth_usd
        depth_factor = 1.0 + (depth_ratio * 10.0)  # 10% of depth = +1.0 bps
        
        # Volatility multiplier
        vol_multiplier = {
            "low": 0.8,
            "normal": 1.0,
            "high": 1.5,
            "extreme": 2.5,
        }.get(volatility_regime, 1.0)
        
        # Urgency multiplier
        urgency_multiplier = {
            "passive": 0.5,
            "patient": 0.8,
            "immediate": 1.2,
        }.get(urgency, 1.0)
        
        slippage = base * spread_factor * depth_factor * vol_multiplier * urgency_multiplier
        
        return max(base, slippage)  # Never below floor
```

### Adverse Selection Buffer

```python
def calculate_adverse_selection_bps(
    symbol: str,
    volatility_regime: str,
    hold_time_expected_sec: float,
) -> float:
    """Estimate adverse selection cost."""
    
    # Base adverse selection (informed traders moving against us)
    base_adverse_selection = {
        "BTCUSDT": 1.0,
        "ETHUSDT": 1.2,
        "SOLUSDT": 2.0,
    }.get(symbol, 1.5)
    
    # Volatility increases adverse selection
    vol_multiplier = {
        "low": 0.8,
        "normal": 1.0,
        "high": 1.5,
        "extreme": 2.5,
    }.get(volatility_regime, 1.0)
    
    # Longer holds = more adverse selection
    time_factor = 1.0 + (hold_time_expected_sec / 300.0) * 0.1  # +10% per 5min
    
    return base_adverse_selection * vol_multiplier * time_factor
```

## 7. Total Cost Calculation

### Complete Cost Stack

```python
def calculate_total_costs(
    fee_model: FeeModel,
    execution_plan: ExecutionPlan,
    slippage_model: SlippageModel,
    features: Features,
    signal: StrategySignal,
) -> CostBreakdown:
    """Calculate all costs for a trade."""
    
    # 1. Fees (expected, accounting for maker/taker mix)
    expected_fees_bps = calculate_expected_fees(
        fee_model=fee_model,
        execution_plan=execution_plan,
        entry_price=signal.entry_price,
        exit_price=signal.take_profit,  # Optimistic exit
        size=signal.size,
    )
    
    # 2. Spread cost (half-spread on entry, half on exit)
    spread_bps = features.spread * 10000  # Convert to bps
    
    # 3. Slippage (market-state-adaptive)
    slippage_bps = slippage_model.calculate_slippage_bps(
        symbol=features.symbol,
        spread_bps=spread_bps,
        spread_percentile=features.spread_percentile or 50.0,
        book_depth_usd=min(features.bid_depth_usd, features.ask_depth_usd),
        order_size_usd=signal.size * signal.entry_price,
        volatility_regime=features.volatility_regime,
        urgency=execution_plan.entry_urgency,
    )
    
    # 4. Adverse selection
    adverse_selection_bps = calculate_adverse_selection_bps(
        symbol=features.symbol,
        volatility_regime=features.volatility_regime,
        hold_time_expected_sec=estimate_hold_time(signal),
    )
    
    # Total
    total_cost_bps = (
        expected_fees_bps +
        spread_bps +
        slippage_bps +
        adverse_selection_bps
    )
    
    return CostBreakdown(
        fee_bps=expected_fees_bps,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        adverse_selection_bps=adverse_selection_bps,
        total_bps=total_cost_bps,
    )
```

### Stress Costs for Safety Margins

```python
def calculate_stress_costs(
    normal_costs: CostBreakdown,
    features: Features,
) -> CostBreakdown:
    """Calculate costs under stress conditions (P90 spread/slippage)."""
    
    stress_multiplier = 1.0
    
    # High spread percentile
    if features.spread_percentile and features.spread_percentile > 70:
        stress_multiplier *= 1.5
    
    # High volatility
    if features.volatility_regime in ["high", "extreme"]:
        stress_multiplier *= 1.8
    
    return CostBreakdown(
        fee_bps=normal_costs.fee_bps,  # Fees don't change
        spread_bps=normal_costs.spread_bps * stress_multiplier,
        slippage_bps=normal_costs.slippage_bps * stress_multiplier,
        adverse_selection_bps=normal_costs.adverse_selection_bps * stress_multiplier,
        total_bps=normal_costs.fee_bps + 
                  normal_costs.spread_bps * stress_multiplier +
                  normal_costs.slippage_bps * stress_multiplier +
                  normal_costs.adverse_selection_bps * stress_multiplier,
    )
```

## 8. Integration with EVGate

### Cost Flow

```
Strategy
  ↓ (generates signal with TP/SL)
ExecutionPolicy
  ↓ (determines execution plan)
CostCalculator
  ↓ (calculates total_cost_bps)
EVGate
  ↓ (C = total_cost_bps / SL_distance_bps)
  ↓ (EV = p*R - (1-p)*(1+C))
Decision (accept/reject)
```

### EVGate Integration

```python
# In EVGate
def evaluate_signal(
    signal: StrategySignal,
    features: Features,
    p_hat: float,  # Win probability
) -> EVGateDecision:
    """Evaluate signal economics."""
    
    # Get execution plan
    execution_plan = execution_policy.plan_execution(
        strategy_id=signal.strategy_id,
        setup_type=signal.meta_reason.split("_")[0],  # "mean_reversion", etc.
        market_state=features,
    )
    
    # Calculate costs
    costs = calculate_total_costs(
        fee_model=fee_model,
        execution_plan=execution_plan,
        slippage_model=slippage_model,
        features=features,
        signal=signal,
    )
    
    # Calculate R (reward/risk ratio)
    sl_distance_bps = abs(signal.entry_price - signal.stop_loss) / signal.entry_price * 10000
    tp_distance_bps = abs(signal.take_profit - signal.entry_price) / signal.entry_price * 10000
    R = tp_distance_bps / sl_distance_bps
    
    # Calculate C (cost ratio)
    C = costs.total_bps / sl_distance_bps
    
    # Calculate EV
    EV = p_hat * R - (1 - p_hat) * (1 + C)
    
    # Decision
    should_accept = EV >= ev_min_threshold
    
    return EVGateDecision(
        should_accept=should_accept,
        ev=EV,
        p_hat=p_hat,
        R=R,
        C=C,
        costs=costs,
        execution_plan=execution_plan,
    )
```

**Critical**: This prevents duplicate cost stacks and ensures consistent economics.

## 9. Configuration and Observability

### Fee Configuration

```python
# Load from config (env/DB), not hardcoded
@dataclass
class TradingConfig:
    exchange: str  # "okx", "bybit"
    fee_tier: str  # "regular", "vip1", "vip2"
    
    def get_fee_config(self) -> FeeConfig:
        """Load fee config for current account."""
        key = f"{self.exchange}_{self.fee_tier}"
        return getattr(FeeConfig, key)()

# Log effective rates
logger.info(
    f"Using fee config: {config.exchange}_{config.fee_tier}, "
    f"taker={fee_config.taker_fee_rate*10000:.1f}bps, "
    f"maker={fee_config.maker_fee_rate*10000:.1f}bps, "
    f"rebate={fee_config.maker_rebate_rate*10000:.1f}bps"
)
```

### Cost Logging

```python
# Log all cost components for every decision
logger.info(
    f"[{symbol}] Cost breakdown: "
    f"fees={costs.fee_bps:.1f}bps, "
    f"spread={costs.spread_bps:.1f}bps, "
    f"slippage={costs.slippage_bps:.1f}bps, "
    f"adverse_sel={costs.adverse_selection_bps:.1f}bps, "
    f"total={costs.total_bps:.1f}bps, "
    f"C={C:.3f}, "
    f"execution_plan={execution_plan.entry_urgency}/{execution_plan.exit_urgency}"
)
```

## 10. Testing Plan

### Unit Tests

```python
# 1. Size independence
def test_fee_breakeven_size_independence():
    """Verify breakeven_bps is size-independent."""
    # (see section 4)

# 2. Maker/taker combinations
@pytest.mark.parametrize("entry_maker,exit_maker,expected_bps", [
    (False, False, 12.0),  # Both taker: 6+6
    (False, True, 10.0),   # Entry taker, exit maker: 6+4
    (True, False, 10.0),   # Entry maker, exit taker: 4+6
    (True, True, 8.0),     # Both maker: 4+4
])
def test_fee_combinations(entry_maker, exit_maker, expected_bps):
    """Test all maker/taker combinations."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    breakeven = fee_model.calculate_breakeven(
        size=1.0,
        entry_price=50000.0,
        side="long",
        entry_is_maker=entry_maker,
        exit_is_maker=exit_maker,
    )
    assert abs(breakeven.breakeven_bps - expected_bps) < 0.1

# 3. Expected fee with probabilities
def test_expected_fee_calculation():
    """Test expected fee with maker/taker probabilities."""
    # p_maker=0.6: 0.6*4 + 0.4*6 = 4.8 bps per side
    # Round trip: 9.6 bps
    pass

# 4. Cost stack completeness
def test_total_cost_includes_all_components():
    """Verify total cost includes fees, spread, slippage, adverse selection."""
    pass
```

### Replay Tests

```python
# 1. Cost distribution analysis
def test_replay_cost_distribution():
    """Analyze cost distribution on replay data."""
    results = run_replay(input_path, use_new_costs=True)
    
    costs = [r["costs"]["total_bps"] for r in results if "costs" in r]
    
    print(f"Cost distribution:")
    print(f"  P50: {np.percentile(costs, 50):.1f} bps")
    print(f"  P75: {np.percentile(costs, 75):.1f} bps")
    print(f"  P90: {np.percentile(costs, 90):.1f} bps")
    
    # Verify costs are in reasonable range
    assert 8.0 < np.median(costs) < 20.0

# 2. Decision delta analysis
def test_replay_decision_changes():
    """Compare old vs new cost model decisions."""
    old_results = run_replay(input_path, use_old_costs=True)
    new_results = run_replay(input_path, use_new_costs=True)
    
    old_accepts = sum(1 for r in old_results if r["decision"] == "accepted")
    new_accepts = sum(1 for r in new_results if r["decision"] == "accepted")
    
    print(f"Decision changes:")
    print(f"  Old accepts: {old_accepts}")
    print(f"  New accepts: {new_accepts}")
    print(f"  Delta: {new_accepts - old_accepts} ({(new_accepts/old_accepts-1)*100:.1f}%)")
    
    # Expect fewer accepts with correct costs
    assert new_accepts <= old_accepts
```

### Golden Tests

```python
# Freeze known-good cost calculations
GOLDEN_TESTS = [
    {
        "symbol": "BTCUSDT",
        "entry_price": 50000.0,
        "size": 0.1,
        "spread_bps": 0.5,
        "volatility": "normal",
        "execution": "taker_entry_maker_exit",
        "expected_total_bps": 12.5,  # 10 fee + 0.5 spread + 1.5 slippage + 0.5 adverse
    },
    # ... more golden tests
]

def test_golden_cost_calculations():
    """Verify cost calculations match golden values."""
    for test in GOLDEN_TESTS:
        costs = calculate_total_costs(...)
        assert abs(costs.total_bps - test["expected_total_bps"]) < 0.5
```

## 11. Implementation Phases

### Phase 1: Foundation (CRITICAL - Do First)
1. Add size-independence unit test
2. Add ExecutionPolicy stub (returns fixed plans)
3. Update FeeModel integration to use ExecutionPolicy
4. Add cost logging
5. Remove strategy-local profitability gates

### Phase 2: Cost Model Enhancement
1. Implement market-state-adaptive slippage
2. Add adverse selection calculation
3. Add stress cost calculation
4. Implement expected fee with probabilities

### Phase 3: EVGate Integration
1. Wire costs into EVGate
2. Implement C = total_cost_bps / SL_distance_bps
3. Update EV formula to use C
4. Add EVGate cost logging

### Phase 4: Validation
1. Run replay with new costs
2. Analyze decision deltas
3. Validate cost distributions
4. Compare with actual trade costs

## Summary of Critical Changes from V1

1. ✅ Fixed "75% under-estimate" language to "50-75% higher"
2. ✅ Removed strategy-local profitability gate (moved to EVGate)
3. ✅ Added unit clarity (notional bps vs SL-normalized C)
4. ✅ Added size-independence validation test
5. ✅ Moved execution assumptions to ExecutionPolicy
6. ✅ Added maker-fill probability to expected costs
7. ✅ Added market-state-adaptive slippage
8. ✅ Added adverse selection buffer
9. ✅ Added stress cost calculation
10. ✅ Added configuration and observability requirements
11. ✅ Added EVGate integration section
12. ✅ Enhanced testing plan with golden tests and replay analysis

**Next Step**: Implement Phase 1 (Foundation) to fix the immediate cost calculation issue while setting up proper architecture for Phases 2-4.
