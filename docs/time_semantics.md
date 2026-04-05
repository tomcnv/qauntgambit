# QuantGambit Time Semantics Spec

## Canonical Time (Final Spec)
We use **receive time** as the canonical timestamp for all window boundaries and staleness checks.

- `ts_canon_us` (int microseconds): **canonical** time for events/snapshots.
- `ts_recv_us` (int microseconds): receive time at ingestion.
- `ts_exchange_s` (float seconds): exchange-provided time (**diagnostics only**).

All membership, bucketing, ordering, and staleness logic MUST use `*_us` fields.
`ts_exchange_s` must never affect decisions, window membership, or staleness.

## Invariants
- `snapshot.ts_canon_us` is canonical and is the sole time used for:
  - trailing window boundaries
  - candle bucketing
  - staleness checks
- Every window uses `window_end = snapshot.ts_canon_us`.
- Every event included in windows satisfies `event.ts_canon_us <= snapshot.ts_canon_us`.
- Snapshot timestamps are monotonic per-symbol (via `MonotonicClock`).

## Usage Rules
- **Never** call `time.time()` / `datetime.now()` / `Timestamp.now()` inside snapshot/feature/window code paths.
- All staleness and window logic must accept an explicit `now_ts_canon_us`.
- Exchange timestamps are retained for:
  - diagnostics
  - skew/lag measurement
  - microstructure analytics

## CI Guard (Phase 1)
Wallclock calls are banned in the core snapshot paths via a CI test.
Current denylist:
- `quantgambit/signals/feature_worker.py`
- `quantgambit/market/quality.py`
- `quantgambit/market/trades.py`
- `quantgambit/market/derived_metrics.py`

Banned patterns:
- `time.time(`
- `datetime.now(`
- `Timestamp.now(`

Ingestion and infrastructure code may use wallclock time.

## Late/Out-of-Order Policy
- Canonical ordering is determined by `ts_canon_us`.
- Exchange timestamps may be out of order; they must not affect window membership.

## Backtest Parity
- Backtests must construct snapshots with the same canonical-time rules.
- Replays must ensure `snapshot.ts_canon_us` is the window end for all caches.
