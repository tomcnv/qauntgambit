# Configuration Reference

Complete reference of all configuration options for the DeepTrader bot platform.

## Configuration Sources

| Priority | Source | Description |
|----------|--------|-------------|
| 1 (highest) | Environment variables | Runtime overrides |
| 2 | Control Manager payload | Dashboard-initiated start |
| 3 | Dashboard database | `exchange_configs` table |
| 4 | Ecosystem config | PM2 defaults |
| 5 (lowest) | Code defaults | Hardcoded fallbacks |

## Identity & Routing

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `TENANT_ID` | Required | Control Manager | User/tenant UUID |
| `BOT_ID` | Required | Control Manager | Bot instance UUID |
| `ACTIVE_EXCHANGE` | `okx` | Control Manager | Exchange: `okx`, `bybit`, `binance` |

## Trading Mode

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `TRADING_MODE` | `paper` | Control Manager | `paper` or `live` |
| `EXECUTION_PROVIDER` | `none` | Control Manager | `none`, `ccxt`, `ccxt_oco` |
| `MARKET_TYPE` | `perp` | Control Manager | `perp` or `spot` |
| `MARGIN_MODE` | `isolated` | Control Manager | `isolated` or `cross` |
| `SHADOW_MODE` | `false` | Environment | Log signals without executing |

## Exchange Credentials

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `EXCHANGE_SECRET_ID` | - | Control Manager | Secrets store lookup key |
| `EXCHANGE_ACCOUNT_ID` | - | Control Manager | Exchange account UUID |
| `OKX_API_KEY` | - | Environment | OKX API key (fallback) |
| `OKX_SECRET_KEY` | - | Environment | OKX secret key (fallback) |
| `OKX_PASSPHRASE` | - | Environment | OKX passphrase (fallback) |
| `BYBIT_API_KEY` | - | Environment | Bybit API key (fallback) |
| `BYBIT_SECRET_KEY` | - | Environment | Bybit secret key (fallback) |
| `BINANCE_API_KEY` | - | Environment | Binance API key (fallback) |
| `BINANCE_SECRET_KEY` | - | Environment | Binance secret key (fallback) |

## Testnet Flags

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `ORDERBOOK_TESTNET` | `false` | Control Manager | Use testnet for market data |
| `OKX_TESTNET` | `false` | Control Manager | OKX demo trading |
| `BYBIT_TESTNET` | `false` | Control Manager | Bybit testnet |
| `BINANCE_TESTNET` | `false` | Control Manager | Binance testnet |

## Database Connections

### Redis

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Environment | Full Redis URL |
| `REDIS_HOST` | `localhost` | Environment | Redis host (if URL not set) |
| `REDIS_PORT` | `6379` | Environment | Redis port (if URL not set) |

### TimescaleDB (Bot Data)

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `BOT_TIMESCALE_URL` | - | Environment | Full connection URL |
| `BOT_DB_HOST` | `localhost` | Environment | Database host |
| `BOT_DB_PORT` | `5433` | Environment | Database port |
| `BOT_DB_USER` | `quantgambit` | Environment | Database user |
| `BOT_DB_PASSWORD` | `quantgambit_pw` | Environment | Database password |
| `BOT_DB_NAME` | `quantgambit_bot` | Environment | Database name |

### Platform Database

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `PLATFORM_DB_HOST` | `localhost` | Environment | Platform DB host |
| `PLATFORM_DB_PORT` | `5432` | Environment | Platform DB port |
| `PLATFORM_DB_USER` | `platform` | Environment | Platform DB user |
| `PLATFORM_DB_PASSWORD` | `platform_pw` | Environment | Platform DB password |
| `PLATFORM_DB_NAME` | `platform_db` | Environment | Platform DB name |

## Redis Streams

### Input Streams

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `MARKET_DATA_STREAM` | `events:market_data:{exchange}` | Control Manager | Price ticks source |
| `ORDERBOOK_EVENT_STREAM` | `events:orderbook_feed:{exchange}` | Control Manager | Orderbook source |
| `TRADE_STREAM` | `events:trades:{exchange}` | Control Manager | Trade feed source |

### Output Streams (Auto-scoped by tenant:bot)

| Stream | Description |
|--------|-------------|
| `events:features:{tenant}:{bot}` | Feature snapshots |
| `events:candles:{tenant}:{bot}` | Aggregated candles |
| `events:decisions:{tenant}:{bot}` | Decision events |
| `events:risk_decisions:{tenant}:{bot}` | Risk-approved signals |

### Consumer Groups

| Variable | Default | Description |
|----------|---------|-------------|
| `ORDERBOOK_CONSUMER_GROUP` | `quantgambit_orderbook:{tenant}:{bot}` | Orderbook worker group |
| `TRADE_CONSUMER_GROUP` | `quantgambit_trades:{tenant}:{bot}` | Trade worker group |
| `FEATURE_CONSUMER_GROUP` | `quantgambit_features:{tenant}:{bot}` | Feature worker group |
| `DECISION_CONSUMER_GROUP` | `quantgambit_decisions:{tenant}:{bot}` | Decision worker group |
| `RISK_CONSUMER_GROUP` | `quantgambit_risk:{tenant}:{bot}` | Risk worker group |
| `EXECUTION_CONSUMER_GROUP` | `quantgambit_execution:{tenant}:{bot}` | Execution worker group |

## Symbols Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `ORDERBOOK_SYMBOLS` | - | Control Manager | Comma-separated symbols |
| `ORDERBOOK_SYMBOL` | - | Environment | Single symbol (fallback) |
| `TRADE_SYMBOLS` | - | Environment | Trade symbols (defaults to orderbook) |
| `MARKET_DATA_SYMBOLS` | - | Environment | Market data symbols |

## Account & Equity

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `LIVE_EQUITY` | - | Control Manager | Live trading account balance |
| `PAPER_EQUITY` | `100000` | Environment | Paper trading starting balance |

## Risk Configuration

### Position Limits

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `MAX_POSITIONS` | `4` | Dashboard DB | Maximum concurrent positions |
| `MAX_POSITIONS_PER_SYMBOL` | `1` | Dashboard DB | Positions per symbol |
| `MAX_TOTAL_EXPOSURE_PCT` | `50.0` | Dashboard DB | Total exposure as % of equity |

### Loss Limits

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `MAX_DAILY_DRAWDOWN_PCT` | `5.0` | Dashboard DB | Max daily loss % |
| `MAX_DRAWDOWN_PCT` | `10.0` | Dashboard DB | Max total drawdown % |

### Position Sizing

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `RISK_PER_TRADE_PCT` | `5.0` | Dashboard DB | % of equity to risk per trade |
| `MIN_POSITION_SIZE_USD` | `500.0` | Dashboard DB | Minimum position size |
| `MAX_POSITION_SIZE_USD` | - | Dashboard DB | Maximum position size |

### Default SL/TP

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `DEFAULT_STOP_LOSS_PCT` | - | Dashboard DB | Default stop loss % |
| `DEFAULT_TAKE_PROFIT_PCT` | - | Dashboard DB | Default take profit % |

## Execution Configuration

### Timing

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `MAX_DECISION_AGE_SEC` | `60.0` | Dashboard DB | Max age of decision to execute |
| `MIN_ORDER_INTERVAL_SEC` | `60.0` | Dashboard DB | Min time between orders per symbol |
| `ORDER_INTENT_MAX_AGE_SEC` | `0` | Environment | Max intent age (0=disabled) |

### Behavior

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `BLOCK_IF_POSITION_EXISTS` | `true` | Dashboard DB | Block entries if position exists |
| `MAX_ORDER_RETRIES` | `2` | Dashboard DB | Order retry attempts |

### Rate Limiting

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `EXECUTION_RATE_LIMIT_PER_SEC` | `5` | Environment | Max API calls/second |
| `EXECUTION_BREAKER_THRESHOLD` | `5` | Environment | Failures to trip breaker |
| `EXECUTION_BREAKER_RESET_SEC` | `10` | Environment | Breaker reset time |

## Position Guard

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `POSITION_GUARD_ENABLED` | `false` | Control Manager | Enable position guardian |
| `POSITION_GUARD_INTERVAL_SEC` | `1.0` | Control Manager | Check interval |
| `POSITION_GUARD_MAX_AGE_SEC` | `0.0` | Control Manager | Max position age (0=disabled) |
| `POSITION_GUARD_TRAILING_BPS` | `0.0` | Control Manager | Trailing stop in bps |

## Warmup Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `DECISION_WARMUP_MIN_CANDLES` | `10` | Environment | Min candles before trading |
| `DECISION_WARMUP_GATE_ENABLED` | `false` | Environment | Enable warmup gating |
| `DECISION_MIN_DATA_QUALITY_SCORE` | `0.2` | Environment | Min quality for decisions |
| `DECISION_WARMUP_QUALITY_MIN_SCORE` | `0.2` | Environment | Min quality during warmup |

## Feature Worker Configuration

### Quality Gates

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `FEATURE_GATE_ORDERBOOK_GAP` | `true` | Environment | Gate on orderbook gaps |
| `FEATURE_GATE_ORDERBOOK_STALE` | `true` | Environment | Gate on stale orderbook |
| `FEATURE_GATE_TRADE_STALE` | `true` | Environment | Gate on stale trades |
| `FEATURE_GATE_CANDLE_STALE` | `true` | Environment | Gate on stale candles |
| `FEATURE_MIN_QUALITY` | `0.6` | Environment | Min quality for prediction |
| `FEATURE_EMIT_DEGRADED` | `true` | Environment | Emit even with low quality |

### Staleness Thresholds

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `QUALITY_TICK_STALE_SEC` | `5.0` | Environment | Tick staleness threshold |
| `QUALITY_TRADE_STALE_SEC` | `5.0` | Environment | Trade staleness threshold |
| `QUALITY_ORDERBOOK_STALE_SEC` | `5.0` | Environment | Orderbook staleness threshold |
| `QUALITY_GAP_WINDOW_SEC` | `30.0` | Environment | Gap detection window |

## Prediction Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `PREDICTION_PROVIDER` | `heuristic` | Environment | `heuristic`, `onnx`, `custom` |
| `PREDICTION_MODEL_PATH` | - | Environment | Path to ONNX model |
| `PREDICTION_MODEL_CONFIG` | - | Environment | Path to model config JSON |
| `PREDICTION_MODEL_FEATURES` | - | Environment | Comma-separated feature keys |
| `PREDICTION_MODEL_CLASSES` | `down,flat,up` | Environment | Output class labels |
| `PREDICTION_MIN_CONFIDENCE` | `0.0` | Environment | Min confidence to act |
| `PREDICTION_ALLOWED_DIRECTIONS` | - | Environment | Allowed directions (comma-sep) |
| `PREDICTION_CONFIDENCE_SCALE` | `1.0` | Environment | Confidence multiplier |
| `PREDICTION_CONFIDENCE_BIAS` | `0.0` | Environment | Confidence bias |
| `PREDICTION_DRIFT_BLOCK` | `false` | Environment | Block on drift detection |

## Position Exit Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `POSITION_EVAL_MIN_CONFIRMATIONS` | `1` | Code | Exit condition confirmations |
| `POSITION_EVAL_UNDERWATER_THRESHOLD_PCT` | `-1.0` | Code | P&L threshold for evaluation |
| `POSITION_EVAL_MAX_UNDERWATER_HOLD_SEC` | `3600` | Code | Max time holding underwater |
| `POSITION_EXIT_TRACE` | `false` | Environment | Enable exit evaluation logging |

## Market Data Provider Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `MARKET_DATA_PROVIDER` | `ccxt` | Environment | `ccxt`, `ws`, `auto` |
| `MARKET_DATA_POLL_INTERVAL_SEC` | `0.5` | Environment | CCXT poll interval |
| `MARKET_DATA_TESTNET` | `false` | Environment | Use testnet |
| `MARKET_DATA_TIMESTAMP_SOURCE` | `exchange` | Environment | `exchange` or `local` |
| `MARKET_DATA_MAX_CLOCK_SKEW_SEC` | `5.0` | Environment | Max allowed clock skew |
| `MARKET_DATA_STALE_SEC` | `5.0` | Environment | Staleness threshold |
| `MARKET_DATA_FAILURE_THRESHOLD` | `3` | Environment | Failures before switch |
| `MARKET_DATA_IDLE_BACKOFF_SEC` | `0.1` | Environment | Backoff on idle |
| `MARKET_DATA_GUARD_INTERVAL_SEC` | `60` | Environment | Guardrail cooldown |

## Orderbook Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `ORDERBOOK_SOURCE` | - | Environment | `external` or `internal` |
| `ORDERBOOK_EXTERNAL` | `false` | Environment | Use external MDS |
| `ORDERBOOK_WS_RECV_TIMEOUT_SEC` | `10` | Environment | WS receive timeout |
| `ORDERBOOK_WS_HEARTBEAT_SEC` | `20` | Environment | WS heartbeat interval |
| `ORDERBOOK_WS_SNAPSHOT_SEC` | `30` | Environment | Snapshot interval |
| `ORDERBOOK_TIMESTAMP_SOURCE` | `exchange` | Environment | `exchange` or `local` |
| `ORDERBOOK_MAX_CLOCK_SKEW_SEC` | `5.0` | Environment | Max clock skew |
| `ORDERBOOK_EMIT_MARKET_TICKS` | `true` | Environment | Emit market ticks |

## Trade Feed Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `TRADE_SOURCE` | - | Environment | `external` or `internal` |
| `TRADES_EXTERNAL` | `false` | Environment | Use external trade feed |
| `TRADE_WINDOW_SEC` | `60` | Environment | Stats window |
| `TRADE_PROFILE_WINDOW_SEC` | `300` | Environment | Profile window |
| `TRADE_BUCKET_SIZE` | `5` | Environment | Aggregation bucket size |
| `TRADE_MAX_TRADES` | `10000` | Environment | Max trades in memory |
| `TRADE_WS_RECONNECT_SEC` | `1` | Environment | WS reconnect delay |
| `TRADE_WS_MAX_RECONNECT_SEC` | `10` | Environment | Max reconnect delay |
| `TRADE_WS_MESSAGE_TIMEOUT_SEC` | `30` | Environment | Message timeout |
| `TRADE_WS_STALE_GUARDRAIL_SEC` | `60` | Environment | Stale guardrail |
| `TRADE_REST_FALLBACK_ENABLED` | `false` | Environment | Enable REST fallback |
| `TRADE_REST_FALLBACK_INTERVAL_SEC` | `30` | Environment | REST poll interval |

## Trading Hours

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `TRADING_HOURS_START_UTC` | `0` | Environment | Start hour (0-23) |
| `TRADING_HOURS_END_UTC` | `24` | Environment | End hour (0-24) |

## Telemetry & Observability

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `POSITIONS_SNAPSHOT_ON_DECISION` | `false` | Environment | Snapshot positions on each decision |
| `POSITIONS_SNAPSHOT_INTERVAL_SEC` | `1.0` | Environment | Position snapshot interval |
| `POSITIONS_SNAPSHOT_HEARTBEAT_SEC` | `5.0` | Environment | Heartbeat interval |
| `RISK_PERSIST_POSITIONS` | `false` | Environment | Persist positions in risk worker |
| `RISK_POSITIONS_SNAPSHOT_INTERVAL_SEC` | `2.0` | Environment | Risk snapshot interval |

## Debug & Tracing

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `POSITION_EXIT_TRACE` | `false` | Environment | Log exit evaluation details |
| `DECISION_TRACE_ENABLED` | `false` | Environment | Log stage traces |
| `TRACE_DETAIL_ENABLED` | `false` | Environment | Extra debug logging |

## Profile Overrides

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `PROFILE_OVERRIDES` | - | Control Manager | JSON string of profile policy |

### Profile Override Schema

```json
{
  "allow_profiles": ["profile_1", "profile_2"],
  "block_profiles": ["risky_profile"],
  "min_score": 0.5,
  "min_confidence": 0.6,
  "profile_regimes": {
    "profile_1": ["trending", "volatile"]
  },
  "risk_mode": {
    "conservative": {
      "allow": ["safe_profile"],
      "block": ["aggressive_profile"]
    }
  },
  "profile_quarantine_sec": 300,
  "profile_warmup_min_samples": 10,
  "top_k": 5
}
```

## Control Manager Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `CONTROL_GROUP` | `quantgambit_control` | Environment | Redis consumer group |
| `CONTROL_CONSUMER` | `control_manager` | Environment | Consumer name |
| `CONTROL_ENABLE_LAUNCH` | `true` | Environment | Enable runtime launching |
| `CONTROL_REQUIRE_HEALTH` | `false` | Environment | Require health before start |
| `RUNTIME_LAUNCH_CMD` | `scripts/launch-runtime.sh` | Environment | Launch script path |
| `RUNTIME_STOP_CMD` | `scripts/stop-runtime.sh` | Environment | Stop script path |

## Configuration Flow Diagram

```
Dashboard UI
     │
     ▼ (stores in database)
┌─────────────────────────────────────────────────────────┐
│  Platform Database                                       │
│  ├── bots: name, default_risk_config, allocator_role    │
│  ├── exchange_accounts: venue, environment, secret_id   │
│  └── exchange_configs: risk_config, execution_config    │
└─────────────────────────────────────────────────────────┘
     │
     ▼ (buildStartPayload)
┌─────────────────────────────────────────────────────────┐
│  Node.js Backend                                         │
│  Assembles payload from DB + derives environment vars   │
└─────────────────────────────────────────────────────────┘
     │
     ▼ (Redis Stream command)
┌─────────────────────────────────────────────────────────┐
│  Control Manager                                         │
│  _build_runtime_env() extracts env vars from payload    │
└─────────────────────────────────────────────────────────┘
     │
     ▼ (launch-runtime.sh)
┌─────────────────────────────────────────────────────────┐
│  PM2 Config Generation                                   │
│  Writes /tmp/runtime-{tenant}-{bot}.config.js           │
└─────────────────────────────────────────────────────────┘
     │
     ▼ (pm2 start)
┌─────────────────────────────────────────────────────────┐
│  Bot Runtime                                             │
│  Reads env vars, applies defaults, initializes workers  │
└─────────────────────────────────────────────────────────┘
```

## Backtesting Configuration

| Variable | Default | Source | Description |
|----------|---------|--------|-------------|
| `BACKTEST_MAX_CONCURRENT` | `2` | Environment | Maximum concurrent backtest jobs |
| `BACKTEST_TIMEOUT_HOURS` | `4.0` | Environment | Maximum execution time per backtest |
| `BACKTEST_TEMP_DIR` | `/tmp/backtests` | Environment | Temporary file storage directory |
| `BACKTEST_STREAM_KEY` | `events:feature_snapshots` | Environment | Redis stream for historical data |
| `BACKTEST_EXCHANGE` | `OKX` | Environment | Default exchange for datasets |

For complete backtesting configuration details, see [BACKTESTING_CONFIG.md](BACKTESTING_CONFIG.md).

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System overview
- [LAUNCH_FLOW.md](LAUNCH_FLOW.md) - Bot startup sequence
- [HOT_PATH.md](HOT_PATH.md) - Trading pipeline
- [GAPS_AND_OPPORTUNITIES.md](GAPS_AND_OPPORTUNITIES.md) - Improvement roadmap
- [BACKTESTING_CONFIG.md](BACKTESTING_CONFIG.md) - Backtesting configuration
- [BACKTESTING_API_REFERENCE.md](BACKTESTING_API_REFERENCE.md) - Backtesting API reference
