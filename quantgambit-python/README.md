# QuantGambit Python

A modular, stage-based trading bot with Redis + Postgres control/telemetry and a Rich dashboard.

## Structure

- `quantgambit/` core runtime and modules
- `quantgambit/deeptrader_core/` embedded profile/strategy/risk logic (no external dependency)
- `docs/` architecture and integration docs
- `infra/terraform/` AWS infrastructure (Redis + Postgres)

## Next Steps

- Implement Redis/Postgres storage layer
- Implement control API + command consumer
- Implement Decision Engine V2 pipeline

## Runtime Configuration

Environment variables used by the runtime entrypoint:

- `ACTIVE_EXCHANGE` (okx|bybit|binance)
- `EXECUTION_PROVIDER=ccxt` to enable REST order status polling via CCXT
- `EXECUTION_PROVIDER=ccxt_oco` to use exchange-native protective orders
- `EXECUTION_RATE_LIMIT_PER_SEC` (default 5)
- `EXECUTION_BREAKER_THRESHOLD` (default 5)
- `EXECUTION_BREAKER_RESET_SEC` (default 10)
- `MARKET_TYPE` (perp|spot)
- `MARGIN_MODE` (isolated|cross)
- `ORDERBOOK_SYMBOLS` (comma-separated)
- `ORDERBOOK_EXCHANGE` (defaults to `ACTIVE_EXCHANGE`)
- `ORDERBOOK_TESTNET` (true|false)
- `ORDER_UPDATES_EXCHANGE` (defaults to `ACTIVE_EXCHANGE`)
- `ORDER_UPDATES_TESTNET` (true|false)
- `ORDER_UPDATES_MARKET_TYPE` (perp|spot; defaults to `MARKET_TYPE`)
- `MARKET_DATA_PROVIDER` (ccxt|ticker|ws|auto; `auto` keeps WS primary with CCXT fallback when no event bus)
- `MARKET_DATA_SYMBOLS` (comma-separated CCXT symbols, e.g. `BTC/USDT:USDT`)
- `MARKET_DATA_POLL_INTERVAL_SEC` (default 0.5)
- `MARKET_DATA_TESTNET` (true|false)
- `MARKET_DATA_FAILURE_THRESHOLD` (consecutive misses to trigger provider switch, default 3)
- `MARKET_DATA_IDLE_BACKOFF_SEC` (idle pause when providers fail, default 0.1)
- `MARKET_DATA_GUARD_INTERVAL_SEC` (seconds between provider failure guardrails/alerts, default 60)
- `API_PORT` (FastAPI server port; default 8080)
- `BOT_REDIS_URL` (Redis URL for API snapshot reads; falls back to `REDIS_URL`)
- `BOT_DB_*` envs for Timescale (used by API to read backtests when implemented)
- `PREDICTION_PROVIDER` (heuristic|legacy|model|onnx)
- `PREDICTION_MODEL_PATH` (path to ONNX file when `PREDICTION_PROVIDER=onnx`)
- `PREDICTION_MODEL_FEATURES` (comma-separated feature keys for ONNX input)
- `PREDICTION_MODEL_CLASSES` (comma-separated labels, default `down,flat,up`)
- `PREDICTION_MIN_CONFIDENCE` (default 0.0)
- `PREDICTION_ALLOWED_DIRECTIONS` (comma-separated, e.g. "up,down")
- `PREDICTION_CONFIDENCE_SCALE` (default 1.0)
- `PREDICTION_CONFIDENCE_BIAS` (default 0.0)
- `BOT_REDIS_URL` (overrides `REDIS_URL`)
- `BOT_TIMESCALE_URL` (overrides `TIMESCALE_URL`)
- `BOT_DB_HOST`, `BOT_DB_PORT`, `BOT_DB_NAME`, `BOT_DB_USER`, `BOT_DB_PASSWORD`
- `DASHBOARD_DB_HOST`, `DASHBOARD_DB_PORT`, `DASHBOARD_DB_NAME`, `DASHBOARD_DB_USER`, `DASHBOARD_DB_PASSWORD`
- Alerting hooks:
  - `ALERT_WEBHOOK_URL` (generic webhook, POST JSON)
  - `SLACK_WEBHOOK_URL` (Slack webhook, formats text payload)
- Backtest retention tuning (ReplayConfig):
  - `max_equity_points` (default 2000)
  - `max_symbol_equity_points` (default 2000)
  - `max_decision_snapshots` (default 2000)
  - `max_position_snapshots` (default 2000)
- Backtest runtime env overrides:
  - `BACKTEST_SLEEP_MS`, `BACKTEST_FEE_BPS`, `BACKTEST_FEE_MODEL`, `BACKTEST_FEE_TIERS`
  - `BACKTEST_SLIPPAGE_BPS`, `BACKTEST_SLIPPAGE_MODEL`, `BACKTEST_IMPACT_BPS`, `BACKTEST_MAX_SLIPPAGE_BPS`
  - `BACKTEST_VOLATILITY_BPS`, `BACKTEST_VOLATILITY_RATIO_CAP`
  - `BACKTEST_EQUITY_SAMPLE_EVERY`
  - `BACKTEST_MAX_EQUITY_POINTS`, `BACKTEST_MAX_SYMBOL_EQUITY_POINTS`
  - `BACKTEST_MAX_DECISION_SNAPSHOTS`, `BACKTEST_MAX_POSITION_SNAPSHOTS`
  - `BACKTEST_RUN_ID`, `TENANT_ID`, `BOT_ID`
- Backtest retention cleanup:
  - `BACKTEST_SNAPSHOT_RETENTION_DAYS` (default 30)
  - `BACKTEST_HISTORY_RETENTION_DAYS` (default 365)
  - `BACKTEST_RETENTION_INTERVAL_SEC` (default 3600)
- Position guard tuning:
  - `POSITION_GUARD_INTERVAL_SEC` (default 1.0)
  - `POSITION_GUARD_MAX_AGE_SEC` (default 0 = disabled)
  - `POSITION_GUARD_TRAILING_BPS` (default 0 = disabled)

Symbol formats for `ORDERBOOK_SYMBOLS`:

- OKX: `BTC-USDT-SWAP`
- Bybit: `BTCUSDT`
- Binance: `BTCUSDT`

If `ORDERBOOK_SYMBOLS` is unset, the runtime defaults to `BTC-USDT-SWAP` for OKX and `BTCUSDT` for Bybit/Binance.

## Prediction Baseline (Data Export + ONNX)

Export feature snapshots to a labeled CSV:

```bash
./venv311/bin/python scripts/export_prediction_dataset.py --output prediction_dataset.csv
```

Train a baseline classifier and export to ONNX:

```bash
./venv311/bin/python -m pip install -r requirements-ml.txt
./venv311/bin/python scripts/train_prediction_baseline.py --input prediction_dataset.csv --output prediction_baseline.onnx
```

The training script emits environment variables for runtime wiring:

```bash
PREDICTION_PROVIDER=onnx
PREDICTION_MODEL_PATH=prediction_baseline.onnx
PREDICTION_MODEL_FEATURES=price,spread_bps,price_change_1s,price_change_5s,price_change_30s,price_change_5m,rotation_factor,ema_fast_15m,ema_slow_15m,ema_spread_pct,trend_strength,atr_5m,atr_5m_baseline,vwap,orderbook_imbalance,bid_depth_usd,ask_depth_usd,data_completeness
PREDICTION_MODEL_CLASSES=down,flat,up
```

Retrain + register latest artifacts:

```bash
./venv311/bin/python scripts/retrain_prediction_baseline.py --redis-url redis://localhost:6380
```

## WS Capture (Order Updates)

Capture private order update payloads for OKX/Bybit/Binance into `exports/order_updates_ws.jsonl`:

```bash
OKX_API_KEY=... OKX_SECRET_KEY=... OKX_PASSPHRASE=... python scripts/capture_order_updates_ws.py \
  --exchange okx --market-type perp --max-messages 50
```

Convert capture logs into test fixtures:

```bash
PYTHONPATH=. ./venv311/bin/python scripts/trim_ws_fixtures.py \
  --input exports/order_updates_ws.jsonl \
  --exchange binance \
  --event ORDER_TRADE_UPDATE \
  --limit 1 \
  --prefix binance_order_trade_update_live
```

## Durable Recovery (Real Services Harness)

End-to-end recovery validation against **real Redis + Timescale/Postgres** is available as an opt-in test.
It seeds order/position data, triggers restore + replay, and verifies dashboard snapshots, then cleans up.

Prereqs:
- Redis and Timescale/Postgres running locally.
- `docs/sql/telemetry.sql` and `docs/sql/orders.sql` applied.

Env vars:
- `BOT_REDIS_URL` (or `REDIS_URL`)
- `BOT_TIMESCALE_URL` (or `BOT_DB_HOST/BOT_DB_PORT/BOT_DB_NAME/BOT_DB_USER/BOT_DB_PASSWORD`)

Run:

```bash
cd quantgambit-python
REAL_SERVICES=1 PYTHONPATH=. ./venv311/bin/pytest \
  quantgambit/tests/integration/test_runtime_recovery_real_services.py -vv
```

## Market Data Resilience Soak Harness

Simulate provider failures and verify guardrail throttling + switch behavior:

```bash
PYTHONPATH=. ./venv311/bin/python scripts/market_data_resilience_soak.py \
  --iterations 25 \
  --switch-threshold 2 \
  --guardrail-cooldown-sec 10
```

One-command helper:

```bash
cd quantgambit-python
./scripts/run_recovery_harness.sh
```

Notes:
- Uses unique `tenant_id`/`bot_id` each run and deletes rows afterward.
- Skips automatically if `REAL_SERVICES` or DB/Redis envs are missing.

## Execution Notes

- Protective orders are placed via CCXT with exchange-specific order types:
  - OKX/Bybit: `stop` + `take_profit` with `stopPrice`
  - Binance Futures: `STOP_MARKET` + `TAKE_PROFIT_MARKET` with `stopPrice` + `closePosition=true`
- Native trigger/OCO APIs (via `EXECUTION_PROVIDER=ccxt_oco`) use exchange-specific endpoints when available:
  - OKX: `trade/order-algo` with `ordType=oco` or `conditional`
  - Bybit: `v5/position/trading-stop` with `tpslMode=Full`
- If we decide to use native OCO/trigger APIs, add a dedicated adapter per exchange and swap via the execution provider.

## Telemetry & Alerting

- `order_reconcile_rest_poll`: guardrail emitted before REST polls because the WS feed reported a gap; payload includes `symbol`, `order_id`, `client_order_id`, `reason="ws_gap_rest_poll"`, `source="rest"`.
- `order_reconcile_override`: guardrail emitted after REST returns a new status (e.g., filled); includes `previous_status`, `current_status`, `source="rest"`, `symbol`.
- `order_resync`: emitted when the orderbook worker detects a gap/out-of-order delta and requests a snapshot; payload carries `symbol`, `reason`, and `last_seq`.
- `market_data_quality` / `trade_feed_stale`: emitted when quality tracker flags stale ticks, orderbooks, or trades; payload lists `flags`, `quality_score`, `orderbook_sync_state`, `trade_sync_state`.
- `config_drift`: runtime version differs from stored config; also triggers Slack/webhook alerts when `ALERT_WEBHOOK_URL` or `SLACK_WEBHOOK_URL` is set.
- `market_data_provider_switch`: emitted when the resilient provider flips from WS to CCXT; payload includes `from`, `to`, and `reason` so dashboards can highlight provider changes.
- `market_data_provider_failure`: emitted when all configured providers fail to deliver ticks; payload carries `active_providers`, `reason`, and `last_success_age` so UI/alerting hooks can warn stakeholders.

Use these guardrails to drive dashboards or notification channels. Guardrail payloads are published via Redis streams; subscribe with `TelemetryPipeline` or custom consumers so your UI can highlight degraded data/resync/replay states.
