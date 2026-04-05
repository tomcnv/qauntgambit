# Backtest + Replay Exports (Dashboard Integration)

This describes how backtest/replay outputs are persisted and exposed to the dashboard.

## Persistence (Dashboard DB)
Backtest outputs are written to the **dashboard database** using the tables defined in:
- `quantgambit-python/docs/sql/dashboard.sql`

Key tables:
- `backtest_runs`
- `backtest_metrics`
- `backtest_trades`
- `backtest_equity_curve`
- `backtest_symbol_equity_curve`
- `backtest_symbol_metrics`
- `backtest_decision_snapshots`
- `backtest_position_snapshots`

The writer is `quantgambit-python/quantgambit/backtesting/store.py` and is used by the replay/backtest pipeline.

## API Endpoints
The dashboard consumes backtest data via the QuantGambit API:

### List backtests
`GET /api/backtests?tenant_id=...&bot_id=...&limit=50`

### Backtest detail (metrics + equity + decisions + fills)
`GET /api/backtests/{backtest_id}`

These endpoints are implemented in:
- `quantgambit-python/quantgambit/api/app.py`

## Replay APIs
Replay endpoints exist under `/api/replay/*` for session management and UI tooling. These should use the same
backtest tables above for exports and history, and can be extended for additional UX features without changing
storage.

## Runtime wiring
Ensure the API reads from the **dashboard DB** pool:
- `DASHBOARD_DB_*` envs control the pool used by `/api/backtests/*`.

Backtest retention is handled by:
- `quantgambit-python/quantgambit/backtesting/retention.py`

Configure retention windows via env:
- `BACKTEST_SNAPSHOT_RETENTION_DAYS`
- `BACKTEST_HISTORY_RETENTION_DAYS`

## Validation checklist
- Run a replay/backtest job that writes rows to the tables above.
- Call `/api/backtests` and `/api/backtests/{id}` and verify the response maps to UI needs.
- Confirm dashboard DB retention settings prune old snapshots as expected.
