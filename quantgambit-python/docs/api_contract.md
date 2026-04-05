# QuantGambit API Contract (v1)

Base URL: `/api/v1`

## Auth (SOC2‑friendly recommendation)
- **Primary:** OIDC/OAuth2 with short‑lived **JWT bearer tokens**.
- **Service‑to‑service:** mTLS or signed JWTs.
- **Scopes/roles:** `bot:read`, `bot:control`, `bot:write`, `backtest:read`, `backtest:write`, `telemetry:read`.

For now, this contract assumes `Authorization: Bearer <JWT>` (HS256 in local dev).

---

## Control Plane

### POST `/control/pause`
Body:
```json
{"tenant_id":"t1","bot_id":"b1","requested_by":"user","reason":"manual","scope":{"bot_id":"b1"}}
```
Response:
```json
{"command_id":"uuid","status":"accepted","message":"queued"}
```

### POST `/control/resume`
Same shape as `/control/pause`.

### POST `/control/flatten`
Same shape, `confirm_required=true` enforced server‑side.

### POST `/control/halt`
Same shape, `confirm_required=true` enforced server‑side.

### POST `/control/failover/arm`
Body:
```json
{"tenant_id":"t1","bot_id":"b1","symbol":"BTC","primary_exchange":"okx","secondary_exchange":"bybit","requested_by":"user"}
```

### POST `/control/failover/execute`
Body:
```json
{"tenant_id":"t1","bot_id":"b1","symbol":"BTC","confirm_token":"...","requested_by":"user"}
```

### POST `/control/recover/arm`
Same as failover arm.

### POST `/control/recover/execute`
Same as failover execute.

### POST `/control/risk_override`
Body:
```json
{"tenant_id":"t1","bot_id":"b1","overrides":{"max_positions":0},"ttl_seconds":60,"requested_by":"user","scope":{"bot_id":"b1"}}
```

### POST `/control/reload_config`
Body:
```json
{"tenant_id":"t1","bot_id":"b1","requested_by":"user"}
```

### GET `/control/state`
Query: `tenant_id`, `bot_id`
Response:
```json
{"trading_paused":false,"pause_reason":null,"failover_state":"idle","primary_exchange":"okx","secondary_exchange":"bybit","timestamp":"..."}
```

### GET `/control/commands`
Query: `tenant_id`, `bot_id`, `limit`
Response:
```json
{"items":[{"command_id":"...","status":"executed","message":"...","executed_at":"..."}]}
```

---

## Telemetry (Read‑only)

### GET `/telemetry/decisions`
Query: `tenant_id`, `bot_id`, `limit`

### GET `/telemetry/orders`
Query: `tenant_id`, `bot_id`, `limit`

### GET `/telemetry/latency`
Query: `tenant_id`, `bot_id`, `limit`

### GET `/telemetry/health`
Query: `tenant_id`, `bot_id`, `limit`

### GET `/telemetry/guardrails`
Query: `tenant_id`, `bot_id`, `limit`

Payloads map to Timescale tables (`decision_events`, `order_events`, `latency_events`, `guardrail_events`, `order_update_events`).

Guardrail payload (minimal contract):
```json
{
  "type": "string",
  "symbol": "optional",
  "source": "optional",
  "reason": "optional",
  "order_id": "optional",
  "client_order_id": "optional",
  "attempt": 0,
  "poll_attempts": 0
}
```
Notes:
- `type` is required; other fields are optional and may be null or omitted.
- `attempt`/`poll_attempts` are used for REST polling and retry guardrails.

---

## Runtime (Quality)

### GET `/api/runtime/quality`
Query: `tenant_id`, `bot_id`
Response:
```json
{
  "orderbook_sync_state": "ok|stale|unsynced|unknown",
  "trade_sync_state": "ok|stale|unsynced|unknown",
  "quality_score": 0.0,
  "quality_flags": [],
  "active_provider": "okx",
  "switch_count": 0,
  "last_switch_at": 0
}
```

### Redis Snapshot Payloads (UI)
Positions snapshot (key: `quantgambit:{tenant_id}:{bot_id}:positions:latest`):
```json
{
  "exchange": "okx",
  "timestamp": "2025-01-01T00:00:00Z",
  "count": 1,
  "positions": [
    {
      "symbol": "BTC-USDT-SWAP",
      "side": "long",
      "size": 1.0,
      "reference_price": 100.5,
      "entry_price": 100.0,
      "stop_loss": 95.0,
      "take_profit": 110.0,
      "opened_at": 1735689600.0,
      "age_sec": 120.0,
      "guard_status": "protected",
      "prediction_confidence": 0.62
    }
  ]
}
```

Prediction snapshot (key: `quantgambit:{tenant_id}:{bot_id}:prediction:latest`):
```json
{
  "symbol": "BTC-USDT-SWAP",
  "exchange": "okx",
  "timestamp": "2025-01-01T00:00:00Z",
  "direction": "up",
  "confidence": 0.62,
  "volatility_regime": "normal",
  "trend_strength": 0.003,
  "orderbook_imbalance": 0.08,
  "source": "heuristic_v1",
  "reject": false
}
```

---

## Backtests

### GET `/backtests/runs`
Query: `tenant_id`, `bot_id`, `limit`
Response: list of runs with `config`, `status`, timestamps.

### GET `/backtests/metrics`
Query: `tenant_id`, `bot_id`, `limit`
Response: list of metrics per run.

### GET `/backtests/trades`
Query: `run_id`, `limit`
Response: list of trades for a run with fields:
`run_id`, `ts`, `symbol`, `side`, `size`, `entry_price`, `exit_price`,
`pnl`, `entry_fee`, `exit_fee`, `total_fees`,
`entry_slippage_bps`, `exit_slippage_bps`,
`strategy_id`, `profile_id`, `reason`.

### GET `/backtests/equity`
Query: `run_id`, `limit`
Response: equity curve points for a run.

### GET `/backtests/equity/symbols`
Query: `run_id`, `limit`, `symbol` (optional)
Response: per‑symbol equity curve points. `equity` is per‑symbol PnL delta (realized + open).

### GET `/backtests/metrics/symbols`
Query: `run_id`
Response: per‑symbol performance metrics.

### GET `/backtests/decisions`
Query: `run_id`, `limit`, `symbol` (optional)

### GET `/backtests/positions`
Query: `run_id`, `limit`, `symbol` (optional)

---

## Configs

### GET `/config/{tenant_id}/{bot_id}`
Returns latest config version metadata.

### GET `/config/{tenant_id}/{bot_id}/versions`
Query: `limit` (default 50)
Response: list of versioned config records.

### GET `/config/{tenant_id}/{bot_id}/versions/{version}`
Response: full config payload for that version.

### POST `/config/update`
Body: `ConfigUpdateRequest` with full config JSON (versioned).

### POST `/config/rollback`
Body: `{ "tenant_id": "...", "bot_id": "...", "target_version": 3, "requested_by": "...", "reason": "..." }`
Creates a new version derived from the target and publishes a hot-reload event.

---

## Data Settings

### GET `/settings/data`
Query: `tenant_id`
Response:
```json
{
  "tenant_id": "t1",
  "trade_history_retention_days": 365,
  "replay_snapshot_retention_days": 30,
  "backtest_history_retention_days": 365,
  "backtest_equity_sample_every": 1,
  "backtest_max_equity_points": 2000,
  "backtest_max_symbol_equity_points": 2000,
  "backtest_max_decision_snapshots": 2000,
  "backtest_max_position_snapshots": 2000,
  "capture_decision_traces": true,
  "capture_feature_values": true,
  "capture_orderbook": false
}
```

### POST `/settings/data`
Body: same as GET response. Returns `{ "success": true, "settings": { ... } }`.

---

## Notes
- All responses include `tenant_id` + `bot_id` fields where applicable.
- Error format:
```json
{"error":"message","code":"ERR_CODE","details":{}}
```

## Local Dev Auth
- Set `AUTH_MODE=jwt` and `AUTH_JWT_SECRET` to enable JWT auth.
- Generate tokens with `scripts/mint_dev_jwt.py`.
