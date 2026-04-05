# Ordering & Clock Determinism

This document defines the rules for event ordering, clock handling, and
jitter-invariance testing to ensure deterministic replay.

## Clock Architecture

### Clock Types

| Clock | Usage | Determinism |
|-------|-------|-------------|
| `WallClock` | Production time | Non-deterministic |
| `SimClock` | Testing/replay | Deterministic |

### Clock Abstraction

All time-dependent code uses the `Clock` interface:

```python
from quantgambit.core.clock import Clock

class HotPath:
    def __init__(self, clock: Clock):
        self._clock = clock
    
    def process(self):
        now = self._clock.now()  # Uses injected clock
        mono = self._clock.now_mono()
```

### Time Sources

| Source | Usage | Notes |
|--------|-------|-------|
| `clock.now()` | Wall clock time | For logging, timestamps |
| `clock.now_mono()` | Monotonic time | For latency measurement |
| Event `ts_wall` | Event wall time | From exchange or local |
| Event `ts_mono` | Event mono time | For ordering |

---

## Event Ordering Rules

### Primary Ordering

Events are ordered by **monotonic timestamp** (`ts_mono`), not wall time.

```python
def compare_events(e1: EventEnvelope, e2: EventEnvelope) -> int:
    """Compare events for ordering."""
    # Primary: monotonic timestamp
    if e1.ts_mono != e2.ts_mono:
        return -1 if e1.ts_mono < e2.ts_mono else 1
    
    # Secondary: sequence ID (if present)
    if e1.seq is not None and e2.seq is not None:
        return -1 if e1.seq < e2.seq else (1 if e1.seq > e2.seq else 0)
    
    # Tertiary: stable hash for determinism
    h1 = hash_event(e1)
    h2 = hash_event(e2)
    return -1 if h1 < h2 else (1 if h1 > h2 else 0)
```

### Per-Symbol Ordering

Events for a single symbol must maintain strict ordering:

1. Book snapshots before deltas
2. Deltas in sequence order
3. Trades in timestamp order
4. No reordering across symbols

### Cross-Symbol Ordering

Events across symbols are interleaved by monotonic time:

```
BTCUSDT book @mono=1.000
ETHUSDT book @mono=1.001
BTCUSDT trade @mono=1.002
BTCUSDT book @mono=1.003
ETHUSDT book @mono=1.004
```

---

## Ingestion Rules

### Book Updates

1. **Snapshot first**: Must receive snapshot before deltas
2. **Sequence validation**: Check `update_id` continuity
3. **Gap handling**: Request resync on gap > threshold
4. **Staleness**: Ignore updates with old timestamps

```python
def should_apply_update(update: BookUpdate, current_seq: int) -> bool:
    """Determine if book update should be applied."""
    # Skip old updates
    if update.sequence_id <= current_seq:
        return False
    
    # Check for gap
    if update.sequence_id > current_seq + MAX_GAP:
        raise SequenceGapError(current_seq, update.sequence_id)
    
    return True
```

### Trade Updates

1. **Deduplicate**: Use trade ID to dedupe
2. **Order by time**: Process in exchange timestamp order
3. **Aggregation window**: Aggregate trades within decision tick

### Private Updates

1. **Order updates**: Apply immediately
2. **Fill updates**: Reconcile with orders
3. **Position updates**: Validate against fills

---

## SimClock Behavior

### Time Advancement

```python
clock = SimClock()

# Set initial time
clock.set_time(1704067200.0, 0.0)

# Advance by delta
clock.advance(0.1)  # Now: 1704067200.1

# Advance to timestamp
clock.advance_to(1704067201.0)
```

### Event Replay

During replay, SimClock advances to each event's timestamp:

```python
async def replay(events: List[EventEnvelope], clock: SimClock):
    for event in events:
        # Advance clock to event time
        clock.advance_to(event.ts_mono)
        
        # Process event at this time
        await process_event(event)
```

---

## Jitter-Invariance Testing

### What is Jitter-Invariance?

Decisions should be identical regardless of minor timing variations:
- Small delays in event delivery
- Event reordering within tolerance
- Clock drift within bounds

### Test Strategy

```python
def test_jitter_invariance():
    """Decisions should be stable under jitter."""
    events = load_test_events()
    
    # Baseline run
    baseline_decisions = run_with_events(events)
    
    # Add jitter
    for _ in range(100):
        jittered = add_jitter(events, max_jitter_ms=10)
        decisions = run_with_events(jittered)
        
        # Decisions should match
        assert_decisions_equivalent(baseline_decisions, decisions)

def add_jitter(events: List[EventEnvelope], max_jitter_ms: float) -> List[EventEnvelope]:
    """Add random timing jitter to events."""
    jittered = []
    for e in events:
        jitter = random.uniform(-max_jitter_ms, max_jitter_ms) / 1000
        new_ts = e.ts_mono + jitter
        jittered.append(replace(e, ts_mono=new_ts))
    
    # Re-sort by monotonic time
    return sorted(jittered, key=lambda x: x.ts_mono)
```

### Jitter Bounds

| Component | Max Jitter | Notes |
|-----------|------------|-------|
| Book updates | 10ms | Within decision tick |
| Trades | 50ms | Aggregation window |
| Order updates | 100ms | Allow for WS latency |

### Invariant Checks

```python
def assert_decisions_equivalent(d1: DecisionRecord, d2: DecisionRecord):
    """Check decisions are equivalent (allowing for jitter)."""
    # These should be identical
    assert d1.symbol == d2.symbol
    assert d1.outcome == d2.outcome
    assert d1.signal_s == pytest.approx(d2.signal_s, abs=1e-6)
    assert d1.delta_w == pytest.approx(d2.delta_w, abs=1e-6)
    
    # These may differ
    # ts_wall - allowed to differ
    # trace_id - allowed to differ
```

---

## Deterministic Random

For any randomness in the pipeline (e.g., tie-breaking), use seeded RNG:

```python
class DeterministicPipeline:
    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
    
    def break_tie(self, candidates: List[str]) -> str:
        """Deterministic tie-breaking."""
        return self._rng.choice(sorted(candidates))
```

---

## Debugging Non-Determinism

### Common Causes

1. **Unsorted containers**: Use `sorted()` for dict iteration
2. **Threading**: Avoid shared state
3. **Wall time**: Use `clock.now_mono()` instead
4. **Hash randomization**: Python hash is non-deterministic

### Diagnosis Steps

```python
def diagnose_nondeterminism():
    """Run replay twice and compare."""
    events = load_events("session.jsonl")
    
    # First run
    results1 = run_replay(events, seed=42)
    
    # Second run
    results2 = run_replay(events, seed=42)
    
    # Find divergence point
    for i, (r1, r2) in enumerate(zip(results1, results2)):
        if r1 != r2:
            print(f"Divergence at index {i}")
            print(f"Result 1: {r1}")
            print(f"Result 2: {r2}")
            break
```

### Replay Verification

```bash
# Run replay twice
python -m quantgambit.scripts.replay session.jsonl --output run1.jsonl
python -m quantgambit.scripts.replay session.jsonl --output run2.jsonl

# Compare outputs
python -m quantgambit.scripts.diff_decisions run1.jsonl run2.jsonl
```
