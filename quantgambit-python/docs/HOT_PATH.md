# Hot Path Documentation

This document details the performance-critical trading pipeline from market data to order execution.

## Hot Path Overview

The hot path is the critical trading pipeline that must execute with minimal latency:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Market Data    │────▶│  Feature        │────▶│  Decision       │
│  Service        │     │  Worker         │     │  Worker         │
│                 │     │                 │     │                 │
│  ~500ms ticks   │     │  ~10-50ms       │     │  ~5-20ms        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Exchange       │◀────│  Execution      │◀────│  Risk           │
│  API            │     │  Worker         │     │  Worker         │
│                 │     │                 │     │                 │
│  ~50-500ms      │     │  ~5-10ms        │     │  ~5-10ms        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Latency Budget

| Stage | Typical | P95 | P99 | Notes |
|-------|---------|-----|-----|-------|
| Market tick emission | - | - | - | ~500ms intervals |
| Redis stream read | 1ms | 3ms | 5ms | Consumer group read |
| Feature computation | 10ms | 30ms | 50ms | Indicators, quality |
| Decision pipeline | 5ms | 15ms | 20ms | 7 stages |
| Risk validation | 5ms | 8ms | 10ms | Position checks |
| Execution logic | 5ms | 8ms | 10ms | Throttle, dedupe |
| Exchange API | 50ms | 200ms | 500ms | Network bound |
| **Total tick-to-order** | **~80ms** | **~270ms** | **~600ms** | Excluding queue wait |

### Queue Wait Times

Each worker blocks on Redis for up to `block_ms` (default 1000ms):

```python
messages = await self.redis.read_group(
    self.config.consumer_group,
    self.config.consumer_name,
    {self.config.source_stream: ">"},
    block_ms=self.config.block_ms,  # 1000ms default
)
```

**Worst case latency** = sum of block times + processing = ~4s (rare, only when queues empty)

## Stage 1: Market Data Ingestion

### Market Data Service (External)

**Location:** `market-data-service/app.py`

The Market Data Service (MDS) runs per-exchange and publishes to Redis:

```python
# Binance MDS publishes to:
events:orderbook_feed:binance  # Orderbook snapshots/deltas
events:trades:binance          # Trade executions  
events:market_data:binance     # Price ticks
```

**Tick interval:** ~500ms (configurable via `SNAPSHOT_INTERVAL_SEC`)

### Market Tick Schema

```json
{
  "event_type": "market_tick",
  "payload": {
    "symbol": "BTCUSDT",
    "timestamp": 1704067200.123,
    "bid": 42150.50,
    "ask": 42151.00,
    "last": 42150.75,
    "volume": 1234.56,
    "source": "orderbook_feed"
  }
}
```

## Stage 2: Feature Worker

**Location:** `quantgambit/signals/feature_worker.py`

### Input/Output

- **Input:** `events:market_data:{exchange}` (market ticks)
- **Input:** `events:candles:{tenant}:{bot}` (aggregated candles)
- **Output:** `events:features:{tenant}:{bot}` (enriched snapshots)

### Processing

```python
async def _build_snapshot(self, symbol: str, tick: dict) -> dict:
    # 1. Price tracking
    price = tick.get("last") or tick.get("price")
    self._update_price_history(symbol, price, timestamp)
    
    # 2. EMA computation
    ema_fast = self._compute_ema(symbol, period=9)
    ema_slow = self._compute_ema(symbol, period=21)
    
    # 3. ATR and volatility
    atr = self._compute_atr(symbol)
    atr_ratio = atr / atr_baseline if atr_baseline else 1.0
    volatility_regime = self._classify_volatility(atr_ratio)
    
    # 4. Value area from orderbook
    vah, val, poc = self._compute_value_area(symbol)
    
    # 5. Orderbook metrics
    orderbook = self.orderbook_cache.get(symbol)
    imbalance = self._compute_imbalance(orderbook)
    
    # 6. Trade flow (if enabled)
    if self.trade_cache:
        trade_stats = self.trade_cache.get_stats(symbol)
    
    # 7. Data quality scoring
    quality = self.quality_tracker.compute_score(symbol)
    
    # 8. Prediction (ML or heuristic)
    prediction = await self._get_prediction(symbol, market_context)
    
    return {
        "symbol": symbol,
        "timestamp": time.time(),
        "market_context": market_context,
        "features": features,
        "prediction": prediction,
        "data_quality_score": quality
    }
```

### Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Price history update | <1ms | Deque operations |
| EMA computation | ~1ms | Incremental |
| ATR computation | ~2ms | Rolling window |
| Value area | ~5ms | Orderbook scan |
| Quality scoring | ~2ms | Multiple checks |
| Prediction | 0-20ms | Depends on provider |
| **Total** | **~10-30ms** | Typical |

### Quality Gating

Feature worker can gate output based on data quality:

```python
# Quality gates (configurable via env vars)
gate_on_orderbook_gap: bool = True    # FEATURE_GATE_ORDERBOOK_GAP
gate_on_orderbook_stale: bool = True  # FEATURE_GATE_ORDERBOOK_STALE
gate_on_trade_stale: bool = True      # FEATURE_GATE_TRADE_STALE
gate_on_candle_stale: bool = True     # FEATURE_GATE_CANDLE_STALE
min_quality_for_prediction: float = 0.6  # FEATURE_MIN_QUALITY
emit_degraded_features: bool = True   # FEATURE_EMIT_DEGRADED
```

## Stage 3: Decision Worker

**Location:** `quantgambit/signals/decision_worker.py`

### Input/Output

- **Input:** `events:features:{tenant}:{bot}` (feature snapshots)
- **Output:** `events:decisions:{tenant}:{bot}` (decision events)

### Warmup Gating

Decisions are blocked until warmup completes:

```python
warmed, stats = self._warmup.record(symbol, timestamp, candle_count)
warmup_ready, warmup_reasons = self._warmup_ready(warmed, market_context, quality_score)

if self.config.warmup_gate_enabled and not warmup_ready:
    log_warning("decision_worker_warmup_wait", ...)
    return  # Skip decision processing
```

**Warmup criteria:**
- Minimum samples: 5 (default)
- Minimum age: 10 seconds (default)
- Minimum quality: 0.4 (if `warmup_require_quality`)

### Decision Pipeline

**Location:** `quantgambit/signals/decision_engine.py`

```python
class DecisionEngine:
    def __init__(self, ...):
        self.orchestrator = Orchestrator(
            stages=[
                DataReadinessStage(),
                ProfileRoutingStage(profile_router),
                PositionEvaluationStage(...),  # Exit signals
                PredictionStage(...),
                SignalStage(strategy_registry),
                RiskStage(risk_validator),
                ExecutionStage(),
            ]
        )
    
    async def decide_with_context(self, decision_input):
        ctx = StageContext(
            symbol=decision_input.symbol,
            data={
                "features": features,
                "market_context": market_context,
                "positions": decision_input.positions,
                # ...
            }
        )
        result = await self.orchestrator.execute(ctx)
        return result == StageResult.COMPLETE, ctx
```

### Pipeline Stages

#### Stage 1: DataReadinessStage

```python
async def run(self, ctx: StageContext) -> StageResult:
    features = ctx.data.get("features") or {}
    if not features:
        ctx.rejection_reason = "no_features"
        return StageResult.REJECT
    return StageResult.CONTINUE
```

#### Stage 2: ProfileRoutingStage

```python
async def run(self, ctx: StageContext) -> StageResult:
    profile_id = self.router.route_with_context(
        ctx.symbol, 
        ctx.data.get("market_context"),
        ctx.data.get("features")
    )
    
    if self.router.require_profile and not profile_id:
        ctx.rejection_reason = "no_eligible_profile"
        return StageResult.REJECT
    
    ctx.profile_id = profile_id
    return StageResult.CONTINUE
```

#### Stage 3: PositionEvaluationStage (Exit Signals)

```python
async def run(self, ctx: StageContext) -> StageResult:
    positions = ctx.data.get("positions") or []
    if not positions:
        return StageResult.CONTINUE
    
    position = self._find_position_for_symbol(positions, ctx.symbol)
    if not position:
        return StageResult.CONTINUE
    
    exit_signal = self._evaluate_exit(position, market_context, ctx)
    if exit_signal:
        ctx.signal = exit_signal
        return StageResult.SKIP_TO_EXECUTION  # Bypass entry stages
    
    return StageResult.CONTINUE
```

**Exit conditions evaluated:**
1. Trend reversal against position
2. Orderflow reversal
3. Price at key levels (VAH for longs, VAL for shorts)
4. Volatility spike
5. Underwater position with adverse conditions
6. Time-based degradation (held too long)
7. Risk mode conservative
8. Deeply underwater emergency (-3%)

#### Stage 4: PredictionStage

```python
async def run(self, ctx: StageContext) -> StageResult:
    prediction = ctx.data.get("prediction")
    if not prediction:
        return StageResult.CONTINUE  # No prediction, continue
    
    confidence = prediction.get("confidence", 0)
    direction = prediction.get("direction")
    
    if confidence < self.min_confidence:
        ctx.rejection_reason = "low_prediction_confidence"
        return StageResult.REJECT
    
    if self.allowed_directions and direction not in self.allowed_directions:
        ctx.rejection_reason = "prediction_direction_blocked"
        return StageResult.REJECT
    
    return StageResult.CONTINUE
```

#### Stage 5: SignalStage

```python
async def run(self, ctx: StageContext) -> StageResult:
    signal = self.registry.generate_signal_with_context(
        ctx.symbol,
        ctx.profile_id,
        ctx.data.get("features"),
        ctx.data.get("market_context"),
        ctx.data.get("account")
    )
    
    if signal:
        ctx.signal = signal
        return StageResult.CONTINUE
    
    return StageResult.REJECT  # No signal generated
```

#### Stage 6: RiskStage

```python
async def run(self, ctx: StageContext) -> StageResult:
    if not ctx.data.get("risk_ok"):
        ctx.rejection_reason = "risk_check_failed"
        return StageResult.REJECT
    return StageResult.CONTINUE
```

#### Stage 7: ExecutionStage

```python
async def run(self, ctx: StageContext) -> StageResult:
    if not ctx.signal:
        return StageResult.REJECT
    return StageResult.COMPLETE
```

### Stage Result Types

```python
class StageResult(str, Enum):
    CONTINUE = "CONTINUE"           # Proceed to next stage
    REJECT = "REJECT"               # Stop pipeline, no signal
    COMPLETE = "COMPLETE"           # Pipeline successful
    SKIP_TO_EXECUTION = "SKIP_TO_EXECUTION"  # Skip to execution (exit signals)
```

## Stage 4: Risk Worker

**Location:** `quantgambit/risk/risk_worker.py`

### Input/Output

- **Input:** `events:decisions:{tenant}:{bot}` (decision events)
- **Output:** `events:risk_decisions:{tenant}:{bot}` (sized intents)

### Exit Signal Bypass

Exit signals bypass position count checks:

```python
is_exit_signal = signal.get("is_exit_signal") or signal.get("reduce_only")
if is_exit_signal:
    log_info("risk_worker_exit_bypass", ...)
    await self._publish_risk_decision(symbol, {
        "status": "accepted",
        "signal": signal,
        "exit_passthrough": True,
    })
    return  # Skip position checks
```

### Risk Checks

```python
# Account-level guardrails
if daily_pnl_pct <= -config.max_daily_loss_pct:
    return "max_daily_loss_exceeded"

drawdown_pct = (peak - equity) / peak * 100
if drawdown_pct >= config.max_drawdown_pct:
    return "max_drawdown_exceeded"

# Position checks
if len(positions) >= config.max_positions:
    return "max_positions_exceeded"

if symbol_positions >= config.max_positions_per_symbol:
    return "max_positions_per_symbol_exceeded"

# Exposure checks
if total_exposure_pct >= config.max_total_exposure_pct:
    return "max_total_exposure_exceeded"
```

### Position Sizing

```python
def _compute_position_size(self, signal, account_equity, config):
    # Risk-based sizing
    risk_amount = account_equity * (config.risk_per_trade_pct / 100)
    
    # Apply min/max constraints
    size_usd = max(config.min_position_size_usd, risk_amount)
    if config.max_position_size_usd:
        size_usd = min(size_usd, config.max_position_size_usd)
    
    # Convert to contracts
    price = signal.get("entry_price")
    size_contracts = size_usd / price if price else 0
    
    return size_contracts
```

## Stage 5: Execution Worker

**Location:** `quantgambit/execution/execution_worker.py`

### Input/Output

- **Input:** `events:risk_decisions:{tenant}:{bot}` (risk decisions)
- **Output:** Exchange orders (via ExecutionManager)

### Pre-execution Checks

```python
async def _handle_message(self, payload):
    # 1. Validate event
    decision = event.get("payload")
    if decision.get("status") != "accepted":
        return
    
    # 2. Check decision age
    if time.time() - decision_ts > self.config.max_decision_age_sec:
        log_warning("execution_worker_stale_decision", ...)
        return
    
    # 3. Check reference price freshness
    if not self._is_reference_price_fresh(symbol):
        return
    
    # 4. Check orderbook freshness
    if not self._is_orderbook_fresh(symbol):
        return
    
    # 5. Symbol throttling (in-flight check)
    if symbol in self._in_flight_symbols:
        log_warning("execution_worker_symbol_in_flight", ...)
        return
    
    # 6. Minimum interval check
    time_since_last = time.time() - self._last_order_time.get(symbol, 0)
    if time_since_last < self.config.min_order_interval_sec:
        log_warning("execution_worker_throttled", ...)
        return
    
    # 7. Position existence check (for entries only)
    if not is_exit_signal and self.config.block_if_position_exists:
        positions = await self.execution_manager.position_manager.list_open_positions()
        if any(p.symbol == symbol for p in positions):
            return
    
    # 8. Execute
    await self._execute_signal(signal)
```

### Order Execution

```python
async def _execute_signal(self, signal):
    symbol = signal.get("symbol")
    self._in_flight_symbols.add(symbol)  # Mark in-flight
    
    try:
        # Build intent
        intent = ExecutionIntent(
            symbol=symbol,
            side=signal.get("side"),
            size=signal.get("size"),
            entry_price=signal.get("entry_price"),
            stop_loss=signal.get("stop_loss"),
            take_profit=signal.get("take_profit"),
            reduce_only=signal.get("reduce_only", False),
            is_exit_signal=signal.get("is_exit_signal", False),
        )
        
        # Execute with retry
        status = await self._execute_with_retry(intent)
        
        # Update throttle state
        self._last_order_time[symbol] = time.time()
        
    finally:
        self._in_flight_symbols.discard(symbol)
```

### Retry Logic

```python
async def _execute_with_retry(self, intent):
    for attempt in range(self.config.max_retries + 1):
        try:
            status = await self.execution_manager.execute_intent(intent)
            
            if status.status in ("filled", "accepted", "partial"):
                return status
            
            if attempt < self.config.max_retries:
                backoff = self.config.base_backoff_sec * (2 ** attempt)
                await asyncio.sleep(min(backoff, self.config.max_backoff_sec))
                
        except Exception as e:
            if attempt == self.config.max_retries:
                raise
            await asyncio.sleep(self.config.base_backoff_sec)
    
    return status
```

## Stage 6: Exchange Execution

**Location:** `quantgambit/execution/manager.py`

### Execution Manager

```python
async def execute_intent(self, intent: ExecutionIntent) -> OrderStatus:
    # Route based on intent type
    if intent.reduce_only or intent.is_exit_signal:
        return await self._close_position(intent)
    else:
        return await self._open_position(intent)
```

### Guarded Exchange Client

**Location:** `quantgambit/execution/guards.py`

```python
class GuardedExchangeClient:
    """Wraps exchange client with rate limiting and circuit breaker."""
    
    def __init__(self, inner: ExchangeClient, config: GuardConfig):
        self._inner = inner
        self._rate_limiter = TokenBucketRateLimiter(config.max_calls_per_sec)
        self._breaker = CircuitBreaker(
            threshold=config.failure_threshold,
            reset_sec=config.reset_after_sec
        )
    
    async def close_position(self, symbol, side, size, client_order_id=None):
        # Rate limit check
        if not self._allow(symbol, "close"):
            return OrderStatus(order_id=None, status="rejected")
        
        # Circuit breaker check
        if self._breaker.is_open:
            return OrderStatus(order_id=None, status="rejected", reason="circuit_open")
        
        try:
            result = await self._inner.close_position(symbol, side, size, client_order_id)
        except Exception as e:
            self._breaker.record_failure()
            raise
        
        self._record_result(result.status)
        return result
```

### Live Adapters

**Location:** `quantgambit/execution/live_adapters.py`

Exchange-specific adapters wrapping ccxt:

```python
class BybitLiveAdapter(ExchangeClient):
    def __init__(self, ccxt_client):
        self._client = ccxt_client
    
    async def close_position(self, symbol, side, size, client_order_id=None):
        order_side = "sell" if side == "long" else "buy"
        
        order = await self._client.create_order(
            symbol=symbol,
            type="market",
            side=order_side,
            amount=size,
            params={
                "reduceOnly": True,
                "clientOrderId": client_order_id,
            }
        )
        
        return self._parse_order_status(order)
    
    async def open_position(self, symbol, side, size, ...):
        order = await self._client.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=size,
            params={
                "clientOrderId": client_order_id,
            }
        )
        
        # Place protective orders (SL/TP) if specified
        if stop_loss or take_profit:
            await self._place_protective_orders(symbol, side, size, stop_loss, take_profit)
        
        return self._parse_order_status(order)
```

## Performance Optimization

### In-Memory State

Position state is kept in memory for fast access:

```python
class InMemoryStateManager:
    def __init__(self):
        self._positions: Dict[str, PositionRecord] = {}  # O(1) lookup
    
    async def list_open_positions(self) -> List[PositionSnapshot]:
        return [
            PositionSnapshot(...)
            for pos in self._positions.values()
            if not pos.closing
        ]
```

### Reference Price Cache

Prices cached for instant slippage calculation:

```python
class ReferencePriceCache:
    def __init__(self):
        self._prices: Dict[str, PriceEntry] = {}
    
    def get_mid_price(self, symbol) -> Optional[float]:
        entry = self._prices.get(symbol)
        if entry and entry.bid and entry.ask:
            return (entry.bid + entry.ask) / 2
        return entry.last if entry else None
```

### Async Redis Operations

All Redis operations are async and non-blocking:

```python
async def publish_event(self, stream: str, event: Event):
    payload = {"data": json.dumps(event)}
    await self.redis.xadd(stream, payload, maxlen=self._max_len, approximate=True)
```

### Consumer Group Batching

Workers consume in batches to reduce round trips:

```python
messages = await self.redis.read_group(
    group, consumer,
    {stream: ">"},
    block_ms=1000,
    count=10  # Batch up to 10 messages
)
```

## Monitoring Hot Path Performance

### Telemetry Points

```python
# Decision latency
decision_payload = {
    "symbol": symbol,
    "timestamp": time.time(),  # Decision time
    "decision": "accepted",
    "latency_ms": (time.time() - feature_ts) * 1000,
    "stage_trace": ctx.stage_trace,
}

# Execution latency
order_payload = {
    "symbol": symbol,
    "order_id": status.order_id,
    "execution_latency_ms": (time.time() - decision_ts) * 1000,
}
```

### Debug Logging

Enable detailed tracing:

```bash
# Position exit evaluation tracing
export POSITION_EXIT_TRACE=1

# Stage trace in decisions
export DECISION_TRACE_ENABLED=1
```

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System overview
- [LAUNCH_FLOW.md](LAUNCH_FLOW.md) - Bot startup sequence
- [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) - Configuration options
