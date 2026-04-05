# Bot API Response Shapes (Dashboard Integration)

This document defines the **minimum required response shapes** the dashboard expects from the QuantGambit API for high‑traffic endpoints. These are sourced from the FastAPI response models and dashboard hooks.

## Risk + Exposure

### GET `/api/dashboard/risk`
```json
{
  "data": {
    "limits": { "max_positions": 4, "max_total_exposure_pct": 0.50, "min_position_size_usd": 10.0 },
    "remaining": { "total_usd": 50000.0, "symbol_usd": 20000.0 },
    "exposure": { "total_usd": 0.0, "long_usd": 0.0, "short_usd": 0.0, "net_usd": 0.0 },
    "totals": { "totalExposureUsd": 0.0, "engineTotalExposureUsd": 0.0, "engineNetExposureUsd": 0.0 },
    "exposureBySymbol": [],
    "account_equity": 100000.0
  }
}
```

### GET `/api/runtime/risk`
```json
{
  "status": "accepted",
  "symbol": "BTCUSDT",
  "account_equity": 100000.0,
  "limits": { "max_total_exposure_pct": 0.50 },
  "remaining": { "total_usd": 50000.0 },
  "exposure": { "total_usd": 0.0, "net_usd": 0.0 }
}
```

## Data Quality + Market Resilience

### GET `/api/runtime/quality`
```json
{
  "orderbook_sync_state": "synced|resyncing|unknown",
  "trade_sync_state": "synced|stale|unknown",
  "quality_score": 0.0,
  "quality_flags": ["orderbook_gap", "trade_stale"],
  "active_provider": "ws|ccxt|ticker|auto",
  "switch_count": 0,
  "last_switch_at": 1720000000.0
}
```

### GET `/api/data-quality/metrics`
```json
{
  "data": {
    "quality_score": 0.95,
    "orderbook_sync_state": "synced",
    "trade_sync_state": "synced",
    "gap_count": 0
  }
}
```

## Orders + Positions

### GET `/api/dashboard/positions`
```json
{
  "data": {
    "positions": [
      {
        "symbol": "BTCUSDT",
        "side": "long",
        "size": 0.01,
        "entry_price": 89000.0,
        "mark_price": 89100.0,
        "unrealized_pnl": 1.0,
        "guard_status": "ok|triggered",
        "age_sec": 120
      }
    ]
  }
}
```

### GET `/api/dashboard/pending-orders`
```json
{
  "data": {
    "orders": [
      {
        "order_id": "317...",
        "client_order_id": "qg...",
        "symbol": "BTCUSDT",
        "side": "buy",
        "status": "open|filled|canceled",
        "type": "market|limit",
        "size": 0.01
      }
    ]
  }
}
```

## Control + Runtime Config

### GET `/api/monitoring/runtime-config`
```json
{
  "drift": true,
  "stored_version": 12,
  "runtime_version": 11,
  "timestamp": 1720000000.0
}
```

### POST `/api/bot/control`
```json
{ "status": "accepted", "message": "queued" }
```

## Telemetry Guardrails (UI panels)
Guardrails are emitted as events (Redis streams) and surfaced via history endpoints:

### GET `/api/history/guardrails`
```json
{
  "events": [
    {
      "type": "market_data_quality",
      "symbol": "BTCUSDT",
      "source": "ws",
      "reason": "orderbook_gap",
      "order_id": "...",
      "client_order_id": "...",
      "attempt": 1,
      "poll_attempts": 0,
      "timestamp": 1720000000.0
    }
  ]
}
```

## Notes
- All endpoints support `tenant_id` + `bot_id` query params when applicable.
- Any missing optional fields should be `null` rather than omitted to keep UI rendering stable.
