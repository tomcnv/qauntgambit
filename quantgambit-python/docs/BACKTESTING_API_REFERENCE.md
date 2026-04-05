# Backtesting API Reference

## Overview

The Backtesting API provides REST endpoints for creating, managing, and analyzing backtests of trading strategies. It integrates with the QuantGambit backtesting infrastructure to enable historical strategy evaluation through the dashboard.

**Base URL:** `/api/research`

**Authentication:** All endpoints require a valid JWT bearer token in the `Authorization` header.

```
Authorization: Bearer <token>
```

## Quick Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/backtests` | Create a new backtest |
| GET | `/backtests` | List backtest runs |
| GET | `/backtests/{run_id}` | Get backtest details |
| DELETE | `/backtests/{run_id}` | Cancel a backtest |
| GET | `/backtests/{run_id}/export` | Export backtest results |
| GET | `/datasets` | List available datasets |
| POST | `/walk-forward` | Create WFO run |
| GET | `/walk-forward` | List WFO runs |
| GET | `/walk-forward/{run_id}` | Get WFO details |
| GET | `/strategies` | List available strategies |

---

## Backtest Endpoints

### POST /api/research/backtests

Create a new backtest run.

**Request Body:**

```json
{
  "name": "BTC Scalp Test",
  "strategy_id": "amt_value_area_rejection_scalp",
  "symbol": "BTC-USDT-SWAP",
  "start_date": "2025-01-01",
  "end_date": "2025-01-15",
  "initial_capital": 10000.0,
  "config": {
    "risk_per_trade_pct": 0.5,
    "stop_loss_pct": 0.5
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | No | Optional name for the backtest |
| strategy_id | string | Yes | Strategy identifier (see `/strategies`) |
| symbol | string | Yes | Trading symbol (e.g., `BTC-USDT-SWAP`) |
| start_date | string | Yes | Start date in ISO format (`YYYY-MM-DD`) |
| end_date | string | Yes | End date in ISO format (`YYYY-MM-DD`) |
| initial_capital | float | No | Initial capital (default: 10000.0) |
| config | object | No | Additional strategy configuration |

**Response (201 Created):**

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Backtest job submitted successfully"
}
```

**Error Responses:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 400 | `validation_error` | Invalid request parameters |
| 401 | `authentication_error` | Missing or invalid token |
| 500 | `server_error` | Database or execution error |

---

### GET /api/research/backtests

List backtest runs with optional filtering.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| status | string | No | Filter by status (`pending`, `running`, `finished`, `failed`, `cancelled`) |
| strategy_id | string | No | Filter by strategy ID |
| symbol | string | No | Filter by trading symbol |
| limit | int | No | Maximum results (default: 50, max: 500) |
| offset | int | No | Pagination offset (default: 0) |

**Response (200 OK):**

```json
{
  "backtests": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "BTC Scalp Test",
      "strategy": "amt_value_area_rejection_scalp",
      "symbol": "BTC-USDT-SWAP",
      "status": "finished",
      "start_date": "2025-01-01",
      "end_date": "2025-01-15",
      "realized_pnl": 523.45,
      "total_return_pct": 5.23,
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "total": 42
}
```

---

### GET /api/research/backtests/{run_id}

Get detailed results for a specific backtest run.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| run_id | string | Backtest run UUID |

**Response (200 OK):**

```json
{
  "run": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "BTC Scalp Test",
    "strategy_id": "amt_value_area_rejection_scalp",
    "symbol": "BTC-USDT-SWAP",
    "status": "finished",
    "start_date": "2025-01-01",
    "end_date": "2025-01-15",
    "started_at": "2025-01-15T10:30:00Z",
    "finished_at": "2025-01-15T10:35:00Z",
    "error_message": null,
    "config": {
      "risk_per_trade_pct": 0.5
    }
  },
  "metrics": {
    "realized_pnl": 523.45,
    "total_fees": 45.20,
    "total_trades": 87,
    "win_rate": 0.62,
    "max_drawdown_pct": 3.5,
    "avg_slippage_bps": 2.1,
    "total_return_pct": 5.23,
    "profit_factor": 1.85,
    "avg_trade_pnl": 6.02
  },
  "equity_curve": [
    {
      "ts": "2025-01-01T00:00:00Z",
      "equity": 10000.0,
      "realized_pnl": 0.0,
      "open_positions": 0
    }
  ],
  "trades": [
    {
      "ts": "2025-01-01T08:15:00Z",
      "symbol": "BTC-USDT-SWAP",
      "side": "long",
      "size": 0.1,
      "entry_price": 42500.0,
      "exit_price": 42650.0,
      "pnl": 15.0,
      "total_fees": 0.85
    }
  ],
  "decisions": [
    {
      "ts": "2025-01-01T08:15:00Z",
      "symbol": "BTC-USDT-SWAP",
      "decision": "accepted",
      "rejection_reason": null,
      "profile_id": "scalp_btc"
    }
  ]
}
```

**Error Responses:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 404 | `not_found` | Backtest run not found |

---

### DELETE /api/research/backtests/{run_id}

Cancel a running backtest job.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| run_id | string | Backtest run UUID |

**Response (200 OK):**

```json
{
  "success": true,
  "message": "Backtest cancelled successfully",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled"
}
```

**Error Responses:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 404 | `not_found` | Backtest run not found |
| 409 | `conflict` | Cannot cancel backtest with current status |

---

### GET /api/research/backtests/{run_id}/export

Export backtest results in specified format.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| run_id | string | Backtest run UUID |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| format | string | No | Export format: `json` (default) or `csv` |

**Response (200 OK):**

Returns a downloadable file with `Content-Disposition` header.

- **JSON format:** Complete backtest data including run metadata, metrics, equity curve, and trades
- **CSV format:** Trade-by-trade data with columns: ts, symbol, side, size, entry_price, exit_price, pnl, total_fees, entry_slippage_bps, exit_slippage_bps

**Error Responses:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 400 | `validation_error` | Invalid format parameter |
| 404 | `not_found` | Backtest run not found |

---

## Dataset Endpoints

### GET /api/research/datasets

List available datasets for backtesting.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| symbol | string | No | Filter by symbol (e.g., `BTC-USDT-SWAP`) |

**Response (200 OK):**

```json
{
  "datasets": [
    {
      "symbol": "BTC-USDT-SWAP",
      "exchange": "OKX",
      "earliest_date": "2024-12-01T00:00:00Z",
      "latest_date": "2025-01-15T23:59:00Z",
      "candle_count": 64800,
      "gaps": 2,
      "gap_dates": ["2024-12-25", "2025-01-01"],
      "completeness_pct": 99.8,
      "last_updated": "2025-01-15T23:59:00Z"
    }
  ],
  "total": 5
}
```

---

## Walk-Forward Optimization Endpoints

### POST /api/research/walk-forward

Create a new walk-forward optimization run.

**Request Body:**

```json
{
  "profile_id": "scalp_btc",
  "symbol": "BTC-USDT-SWAP",
  "config": {
    "in_sample_days": 30,
    "out_sample_days": 7,
    "periods": 4,
    "objective": "sharpe"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| profile_id | string | Yes | Profile identifier for the strategy |
| symbol | string | Yes | Trading symbol |
| config.in_sample_days | int | Yes | Days for in-sample period (≥1) |
| config.out_sample_days | int | Yes | Days for out-of-sample period (≥1) |
| config.periods | int | Yes | Number of WFO periods (≥1) |
| config.objective | string | No | Optimization objective: `sharpe`, `sortino`, `profit_factor` (default: `sharpe`) |

**Response (201 Created):**

```json
{
  "run_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "pending",
  "message": "WFO job submitted successfully"
}
```

---

### GET /api/research/walk-forward

List walk-forward optimization runs.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| profile_id | string | No | Filter by profile ID |
| symbol | string | No | Filter by symbol |
| status | string | No | Filter by status |
| limit | int | No | Maximum results (default: 50, max: 500) |
| offset | int | No | Pagination offset (default: 0) |

**Response (200 OK):**

```json
{
  "runs": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "profile_id": "scalp_btc",
      "symbol": "BTC-USDT-SWAP",
      "status": "finished",
      "config": {
        "in_sample_days": 30,
        "out_sample_days": 7,
        "periods": 4,
        "objective": "sharpe"
      },
      "created_at": "2025-01-15T10:30:00Z",
      "avg_is_sharpe": 1.85,
      "avg_oos_sharpe": 1.42,
      "degradation_pct": 23.2
    }
  ],
  "total": 12
}
```

---

### GET /api/research/walk-forward/{run_id}

Get detailed results for a specific WFO run.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| run_id | string | WFO run UUID |

**Response (200 OK):**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "profile_id": "scalp_btc",
  "symbol": "BTC-USDT-SWAP",
  "status": "finished",
  "config": {
    "in_sample_days": 30,
    "out_sample_days": 7,
    "periods": 4,
    "objective": "sharpe"
  },
  "started_at": "2025-01-15T10:30:00Z",
  "finished_at": "2025-01-15T11:45:00Z",
  "created_at": "2025-01-15T10:30:00Z",
  "periods": [
    {
      "period": 1,
      "in_sample_start": "2024-12-01",
      "in_sample_end": "2024-12-31",
      "out_sample_start": "2025-01-01",
      "out_sample_end": "2025-01-07",
      "in_sample_sharpe": 1.92,
      "out_sample_sharpe": 1.45,
      "in_sample_return_pct": 8.5,
      "out_sample_return_pct": 2.1,
      "in_sample_max_dd_pct": 4.2,
      "out_sample_max_dd_pct": 3.8,
      "optimized_params": {
        "risk_per_trade_pct": 0.6,
        "stop_loss_pct": 0.45
      }
    }
  ],
  "summary": {
    "avg_is_sharpe": 1.85,
    "avg_oos_sharpe": 1.42,
    "degradation_pct": 23.2,
    "consistency_score": 0.78
  },
  "recommended_params": {
    "risk_per_trade_pct": 0.55,
    "stop_loss_pct": 0.48
  },
  "error_message": null
}
```

**Error Responses:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 404 | `not_found` | WFO run not found |

---

## Strategy Endpoints

### GET /api/research/strategies

List available strategies for backtesting.

**Response (200 OK):**

```json
{
  "strategies": [
    {
      "id": "amt_value_area_rejection_scalp",
      "name": "AMT Value Area Rejection Scalp",
      "description": "Scalps rejections at value area boundaries using AMT principles.",
      "parameters": [
        {
          "name": "risk_per_trade_pct",
          "type": "float",
          "description": "Risk per trade as percentage of equity",
          "default": 0.5,
          "min_value": 0.1,
          "max_value": 2.0
        },
        {
          "name": "stop_loss_pct",
          "type": "float",
          "description": "Stop loss percentage",
          "default": 0.5,
          "min_value": 0.1,
          "max_value": 2.0
        }
      ],
      "default_values": {
        "risk_per_trade_pct": 0.5,
        "stop_loss_pct": 0.5
      }
    }
  ],
  "total": 20
}
```

---

## Error Response Format

All errors follow a consistent format:

```json
{
  "error": "error_type",
  "message": "Human-readable error message",
  "details": {
    "field": "additional_context"
  }
}
```

### Error Codes

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 400 | `validation_error` | Invalid request parameters or body |
| 401 | `authentication_error` | Missing or invalid authentication token |
| 403 | `authorization_error` | Access denied (cross-tenant access) |
| 404 | `not_found` | Requested resource does not exist |
| 409 | `conflict` | Resource conflict (e.g., invalid status transition) |
| 500 | `server_error` | Internal server error |

### Validation Error Examples

**Invalid date format:**
```json
{
  "error": "validation_error",
  "message": "Invalid start_date format. Use YYYY-MM-DD or ISO format.",
  "details": {
    "field": "start_date",
    "value": "01-15-2025"
  }
}
```

**Invalid date range:**
```json
{
  "error": "validation_error",
  "message": "start_date must be before end_date",
  "details": {
    "start_date": "2025-01-15",
    "end_date": "2025-01-01"
  }
}
```

**Missing required field:**
```json
{
  "error": "validation_error",
  "message": "strategy_id is required",
  "details": {
    "field": "strategy_id"
  }
}
```

---

## Backtest Status Values

| Status | Description |
|--------|-------------|
| `pending` | Job submitted, waiting to start |
| `running` | Backtest is currently executing |
| `finished` | Backtest completed successfully |
| `failed` | Backtest failed with error |
| `cancelled` | Backtest was cancelled by user |
| `degraded` | Backtest completed with warnings (data quality issues) |

---

## Rate Limits

- Maximum 2 concurrent backtest jobs per tenant
- Backtest timeout: 4 hours (configurable)
- List endpoints: 500 results maximum per request

---

## OpenAPI/Swagger

Interactive API documentation is available at:
- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **OpenAPI JSON:** `/openapi.json`
