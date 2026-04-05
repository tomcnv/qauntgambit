# Observability Plan

This document outlines the metrics, logging, and alerting strategy for the
quant-grade scalper system.

## Principles

1. **Determinism-safe**: No logging/metrics on the hot path that could affect timing
2. **Complete**: Every decision (including blocked) is recorded
3. **Actionable**: Alerts have clear runbooks
4. **Efficient**: Async emission, bounded queues, sampling where appropriate

---

## Metrics

### Latency Metrics (Critical)

All latencies in milliseconds, tracked as histograms with p50/p95/p99.

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `tick_to_decision_ms` | Time from book update to decision emit | p99 > 50ms |
| `feature_build_ms` | Feature computation time | p99 > 10ms |
| `model_infer_ms` | Model inference time | p99 > 20ms |
| `calibrate_ms` | Calibration time | p99 > 5ms |
| `edge_transform_ms` | Edge signal computation | p99 > 1ms |
| `vol_estimate_ms` | Volatility estimation | p99 > 5ms |
| `risk_map_ms` | Risk mapping time | p99 > 5ms |
| `exec_policy_ms` | Intent building time | p99 > 5ms |
| `order_send_to_ack_ms` | Order placement to exchange ack | p99 > 200ms |
| `ack_to_fill_ms` | Ack to fill (market orders) | p99 > 100ms |
| `reconciliation_ms` | Reconciliation cycle time | p99 > 5000ms |

### Decision Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `decisions_total` | Counter | Total decisions made |
| `decisions_blocked` | Counter | Blocked decisions (by reason) |
| `intents_emitted` | Counter | Execution intents generated |
| `signal_value` | Histogram | Edge signal distribution |
| `delta_w_value` | Histogram | Position delta distribution |

### Execution Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `orders_placed` | Counter | Orders sent to exchange |
| `orders_filled` | Counter | Orders filled |
| `orders_rejected` | Counter | Orders rejected (by reason) |
| `orders_canceled` | Counter | Orders canceled |
| `fill_slippage_bps` | Histogram | Fill slippage in basis points |
| `fees_paid` | Counter | Cumulative fees |

### Data Integrity Metrics

| Metric | Type | Description | Alert |
|--------|------|-------------|-------|
| `book_resyncs` | Counter | Order book resyncs | > 10/min |
| `sequence_gaps` | Counter | Sequence gap detections | > 5/min |
| `checksum_failures` | Counter | Checksum validation failures | > 1/min |
| `ws_disconnects` | Counter | WebSocket disconnections | > 1/hour |
| `book_staleness_s` | Gauge | Time since last book update | > 2s |
| `private_ws_disconnect_s` | Gauge | Time since private WS disconnect | > 0 |

### Kill Switch Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `kill_switch_active` | Gauge | 1 if kill switch active |
| `kill_switch_triggers` | Counter | Kill switch activations (by reason) |
| `kill_switch_resets` | Counter | Kill switch resets |

### Reconciliation Metrics

| Metric | Type | Description | Alert |
|--------|------|-------------|-------|
| `reconciliation_runs` | Counter | Reconciliation cycles | |
| `discrepancies_found` | Counter | Discrepancies detected (by type) | > 5/run |
| `discrepancies_healed` | Counter | Discrepancies auto-healed | |

### Position Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `position_size` | Gauge | Current position size per symbol |
| `position_pnl` | Gauge | Unrealized PnL per symbol |
| `position_hold_time_s` | Histogram | Position hold duration |

---

## Logging

### Log Levels

| Level | Usage | On Hot Path |
|-------|-------|-------------|
| `DEBUG` | Detailed trace info | No |
| `INFO` | Normal operations | No |
| `WARNING` | Recoverable issues | No |
| `ERROR` | Errors requiring attention | No |
| `CRITICAL` | Kill switch, data integrity | No |

### Structured Logging

All logs use structured JSON format with standard fields:

```json
{
  "timestamp": "2024-01-01T00:00:00.000Z",
  "level": "INFO",
  "logger": "quantgambit.hot_path",
  "message": "Decision emitted",
  "trace_id": "abc123",
  "symbol": "BTCUSDT",
  "signal_s": 0.15,
  "delta_w": 0.03,
  "outcome": "intent_emitted"
}
```

### Key Log Events

| Event | Level | Fields | Frequency |
|-------|-------|--------|-----------|
| `decision.blocked` | INFO | trace_id, symbol, reason | Per blocked decision |
| `decision.emitted` | INFO | trace_id, symbol, intent_id | Per intent |
| `order.placed` | INFO | trace_id, symbol, client_order_id | Per order |
| `order.filled` | INFO | trace_id, symbol, fill_price | Per fill |
| `order.rejected` | WARNING | trace_id, symbol, reason | Per reject |
| `kill_switch.triggered` | CRITICAL | trigger, reason | Per trigger |
| `reconciliation.discrepancy` | WARNING | type, symbol, local, remote | Per discrepancy |
| `book.resync` | WARNING | symbol, reason, gap_size | Per resync |

### Logging Off Hot Path

All logging happens asynchronously via the side channel:

```python
# DON'T do this on hot path
logger.info(f"Decision: {decision}")  # Blocks!

# DO this instead
self._publisher.publish(decision_record.to_event_envelope())  # Non-blocking
```

---

## Alerts

### P1 (Immediate Action)

| Alert | Condition | Runbook |
|-------|-----------|---------|
| Kill Switch Active | `kill_switch_active == 1` | Check trigger reason, investigate |
| Private WS Down | `private_ws_disconnect_s > 30` | Check connectivity, restart if needed |
| High Reject Rate | `order_reject_rate > 20%` | Check account, pause trading |
| Decision Latency | `tick_to_decision_p99 > 100ms` | Check CPU, reduce symbols |
| Book Stale All | All symbols stale > 5s | Check MDS, restart |

### P2 (Investigate Soon)

| Alert | Condition | Runbook |
|-------|-----------|---------|
| High Resync Rate | `book_resyncs > 10/min` | Check exchange status |
| Reconciliation Discrepancies | `discrepancies > 5/run` | Check for bugs |
| High Fill Slippage | `slippage_p99 > 50bps` | Review execution policy |
| Sequence Gaps | `sequence_gaps > 5/min` | Check WS stability |

### P3 (Trend Monitoring)

| Alert | Condition | Runbook |
|-------|-----------|---------|
| Elevated Latency | `tick_to_decision_p50 > 20ms` | Baseline change |
| Blocked Decision Rate | `blocked_rate > 90%` | Review strategy params |
| Low Signal Variance | `signal_std < 0.01` | Model may need retrain |

---

## Dashboards

### Real-Time Trading Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│ TRADING STATUS: ● ACTIVE                    Kill Switch: OFF    │
├─────────────────────────────────────────────────────────────────┤
│ Latencies (p99)                                                  │
│ ┌─────────┬─────────┬─────────┬─────────┬─────────┐            │
│ │ Tick→Dec│ Feature │ Model   │ Risk    │ Ord→Ack │            │
│ │  12ms   │   3ms   │   8ms   │   2ms   │   45ms  │            │
│ └─────────┴─────────┴─────────┴─────────┴─────────┘            │
├─────────────────────────────────────────────────────────────────┤
│ Decisions (last hour)                                            │
│ Total: 3,600  Blocked: 3,200  Intents: 400                      │
│ Block reasons: Deadband 80%, Churn 15%, Kill 5%                 │
├─────────────────────────────────────────────────────────────────┤
│ Positions                                                        │
│ BTCUSDT: +0.05 @ 43,250 | PnL: +$125                            │
│ ETHUSDT: -0.2  @ 2,350  | PnL: -$45                             │
└─────────────────────────────────────────────────────────────────┘
```

### Data Integrity Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│ BOOK STATUS: BTCUSDT ● | ETHUSDT ● | SOLUSDT ●                  │
├─────────────────────────────────────────────────────────────────┤
│ Symbol    │ Sequence  │ Staleness │ Resyncs/hr │ Status         │
│ BTCUSDT   │ 1,234,567 │ 0.1s      │ 2          │ QUOTEABLE     │
│ ETHUSDT   │ 987,654   │ 0.2s      │ 1          │ QUOTEABLE     │
│ SOLUSDT   │ 555,555   │ 0.3s      │ 0          │ QUOTEABLE     │
├─────────────────────────────────────────────────────────────────┤
│ WS Status                                                        │
│ Public:  ● Connected (uptime: 4h 32m)                           │
│ Private: ● Connected (uptime: 4h 32m)                           │
├─────────────────────────────────────────────────────────────────┤
│ Reconciliation                                                   │
│ Last run: 15s ago  │  Discrepancies: 0  │  Healed: 0            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Replay Drift Detection

When running replay tests, compare decision outputs:

```python
# After replay
diff = ReplayDiffer()
for live_record, replay_record in zip(live_records, replay_records):
    diff_result = diff.diff_decision_records(live_record, replay_record)
    if diff_result:
        logger.warning(f"Replay drift detected: {diff_result}")
        metrics.replay_drift_count.inc()
```

### Acceptable Drift Sources

- Timing fields (`ts_wall`, `ts_mono`) - expected to differ
- Trace IDs - expected to differ
- Float precision (< 1e-6) - acceptable

### Unacceptable Drift

- Signal values differ
- Block reasons differ
- Intent presence differs
- Version IDs differ

---

## Implementation Notes

### Metric Collection

Use Prometheus client with async push to avoid blocking:

```python
from prometheus_client import Counter, Histogram, Gauge

decisions_total = Counter('qg_decisions_total', 'Total decisions')
tick_latency = Histogram(
    'qg_tick_to_decision_ms',
    'Tick to decision latency',
    buckets=[1, 5, 10, 20, 50, 100, 200]
)
```

### Async Metric Push

```python
class AsyncMetricsPusher:
    """Push metrics asynchronously."""
    
    def __init__(self, push_interval_s: float = 1.0):
        self._queue = asyncio.Queue(maxsize=10000)
        self._interval = push_interval_s
    
    def record(self, metric: str, value: float, labels: dict = None):
        """Non-blocking metric record."""
        try:
            self._queue.put_nowait((metric, value, labels))
        except asyncio.QueueFull:
            pass  # Drop if queue full
```

### Log Sampling

For high-frequency events, use sampling:

```python
import random

def should_log(rate: float = 0.01) -> bool:
    """Sample logs at given rate."""
    return random.random() < rate

# Usage
if should_log(0.1):  # 10% sample
    logger.debug(f"Tick processed: {symbol}")
```
