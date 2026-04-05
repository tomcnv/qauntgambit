# DeepTrader Bot Architecture

## Overview

DeepTrader is a multi-exchange algorithmic trading platform consisting of:
- **Dashboard** (React/TypeScript) - User interface for configuration and monitoring
- **Backend** (Node.js) - API server, authentication, control plane interface
- **Bot Runtime** (Python) - Trading engine with decision pipeline and execution
- **Market Data Service** (Python) - Exchange WebSocket aggregation
- **Control Manager** (Python) - Bot lifecycle orchestration via PM2

## System Topology

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                    Dashboard (React + Vite)                              │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │    │
│  │  │ Run Bar  │  │ Overview │  │ Positions│  │ Settings │  │  Alerts  │  │    │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │    │
│  └───────┼─────────────┼─────────────┼─────────────┼─────────────┼────────┘    │
└──────────┼─────────────┼─────────────┼─────────────┼─────────────┼──────────────┘
           │             │             │             │             │
           ▼             ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           NODE.JS BACKEND (:3001)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ Control API  │  │ Dashboard API│  │ Config API   │  │ Secrets Prov │        │
│  │ /api/control │  │ /api/dashboard│ │ /api/config  │  │ Credentials  │        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
└─────────┼─────────────────┼─────────────────┼─────────────────┼─────────────────┘
          │                 │                 │                 │
          ▼                 ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE LAYER                                       │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐        │
│  │    Redis (:6379)   │  │  Platform DB       │  │   Bot TimescaleDB  │        │
│  │  • Streams         │  │  PostgreSQL (:5432)│  │   PostgreSQL(:5433)│        │
│  │  • Snapshots       │  │  • users           │  │   • orders         │        │
│  │  • Commands        │  │  • bots            │  │   • positions      │        │
│  │  • Events          │  │  • exchange_accts  │  │   • telemetry      │        │
│  └─────────┬──────────┘  └────────────────────┘  └────────────────────┘        │
└────────────┼────────────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           PYTHON SERVICES                                        │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                     Control Manager (Always Running)                        │ │
│  │  • Listens on commands:control:* Redis streams                             │ │
│  │  • Launches/stops bot runtimes via PM2                                     │ │
│  │  • Publishes platform health                                               │ │
│  └─────────────────────────────────┬──────────────────────────────────────────┘ │
│                                    │ spawn via launch-runtime.sh               │
│                                    ▼                                            │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │               Bot Runtime (Per tenant:bot, On-Demand)                       │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │ │
│  │  │Feature      │─▶│Decision     │─▶│Risk         │─▶│Execution    │       │ │
│  │  │Worker       │  │Worker       │  │Worker       │  │Worker       │       │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └──────┬──────┘       │ │
│  │         ▲                                                   │              │ │
│  │         │                                                   ▼              │ │
│  │  ┌──────┴──────┐                                    ┌─────────────┐       │ │
│  │  │Orderbook    │                                    │  Exchange   │       │ │
│  │  │Worker       │                                    │  Adapter    │       │ │
│  │  └─────────────┘                                    │  (ccxt)     │       │ │
│  │                                                     └──────┬──────┘       │ │
│  └─────────────────────────────────────────────────────────────┼──────────────┘ │
│                                                                │                │
│  ┌────────────────────────────────────────────────────────────┼───────────────┐ │
│  │              Market Data Service (Per Exchange)            │               │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │               │ │
│  │  │ Binance MDS │  │   OKX MDS   │  │  Bybit MDS  │        │               │ │
│  │  │   (:8082)   │  │   (:8081)   │  │   (:8083)   │        │               │ │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │               │ │
│  └─────────┼────────────────┼────────────────┼────────────────┼───────────────┘ │
└────────────┼────────────────┼────────────────┼────────────────┼─────────────────┘
             │                │                │                │
             ▼                ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           EXCHANGES                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                          │
│  │   Binance    │  │     OKX      │  │    Bybit     │                          │
│  │  • Futures   │  │  • Futures   │  │  • Futures   │                          │
│  │  • Testnet   │  │  • Demo      │  │  • Testnet   │                          │
│  └──────────────┘  └──────────────┘  └──────────────┘                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Dashboard (React)

**Location:** `deeptrader-dashhboard/`

The user-facing web application built with React + Vite + TypeScript:

| Component | Purpose |
|-----------|---------|
| `RunBar` | Bot start/stop controls, status display |
| `BotStartupModal` | Startup progress with warmup tracking |
| `Overview` | Real-time metrics, equity curve, positions |
| `ScopeBar` | Exchange account and bot selection |
| `WarmupStatus` | Data quality and warmup progress |

**Key APIs consumed:**
- `/api/control/command` - Start/stop bot commands
- `/api/dashboard/state` - Real-time bot state
- `/api/dashboard/metrics` - Performance metrics
- `/api/config/*` - Bot and exchange configuration

### 2. Node.js Backend

**Location:** `deeptrader-backend/`

REST API server handling authentication, configuration, and control plane interface:

| Route | Purpose |
|-------|---------|
| `/api/control/command` | Enqueue start/stop/pause commands |
| `/api/dashboard/*` | Real-time data aggregation |
| `/api/config/*` | Bot configuration CRUD |
| `/api/exchange-accounts/*` | Exchange credential management |

**Key Services:**
- `controlQueueService.js` - Redis stream command publishing
- `secretsProvider.js` - Encrypted credential storage
- `guardianOrchestrator.js` - Per-tenant guardian management

### 3. Control Manager

**Location:** `quantgambit-python/quantgambit/control/command_manager.py`

Always-running Python process that:
- Listens on `commands:control:*` Redis streams
- Handles `start_bot`, `stop_bot`, `pause_bot`, `halt_bot`, `flatten_positions`
- Spawns bot runtimes via PM2 with `launch-runtime.sh`
- Publishes platform health to `quantgambit:::health:latest`

### 4. Bot Runtime

**Location:** `quantgambit-python/quantgambit/runtime/`

Per-bot Python process spawned by Control Manager:

| Module | Purpose |
|--------|---------|
| `entrypoint.py` | Bootstrap connections, build providers |
| `app.py` | Wire workers, start async tasks |
| `config_apply.py` | Hot-reload configuration application |

**Workers (Hot Path):**

```
Market Data → Feature Worker → Decision Worker → Risk Worker → Execution Worker → Exchange
     │              │                │                │               │
     ▼              ▼                ▼                ▼               ▼
  Redis         Redis            Redis           Redis          Order
 Streams       Streams          Streams         Streams        Updates
```

### 5. Market Data Service

**Location:** `market-data-service/`

Per-exchange WebSocket aggregator publishing to Redis streams:

| Stream | Content |
|--------|---------|
| `events:trades:{exchange}` | Trade executions |
| `events:orderbook_feed:{exchange}` | Orderbook snapshots/deltas |
| `events:market_data:{exchange}` | Price ticks |

## Data Flow

### Redis Streams (Hot Path)

```
events:market_data:{exchange}     ← Market Data Service
         │
         ▼
events:features:{tenant}:{bot}    ← Feature Worker
         │
         ▼
events:decisions:{tenant}:{bot}   ← Decision Worker
         │
         ▼
events:risk_decisions:{tenant}:{bot} ← Risk Worker
         │
         ▼
(Exchange Order API)              ← Execution Worker
```

### Redis Snapshots (State)

| Key Pattern | Content | TTL |
|-------------|---------|-----|
| `quantgambit:{tenant}:{bot}:positions:latest` | Open positions | None |
| `quantgambit:{tenant}:{bot}:warmup:status` | Warmup progress | None |
| `quantgambit:{tenant}:{bot}:decision:latest` | Last decision | None |
| `quantgambit:{tenant}:{bot}:health:latest` | Bot health | 30s |
| `quantgambit:{tenant}:{bot}:risk:overrides` | Risk override state | None |

### Redis Commands

| Stream | Content |
|--------|---------|
| `commands:control:{tenant}:{bot}` | start_bot, stop_bot, etc. |
| `commands:control:{tenant}:{bot}:results` | Command execution results |

## Worker Pipeline

### Feature Worker

**Source:** `quantgambit/signals/feature_worker.py`

Consumes market ticks and produces enriched feature snapshots:

**Inputs:**
- `events:market_data:{exchange}` - Price ticks
- `events:candles:{tenant}:{bot}` - Aggregated candles

**Computations:**
- EMA (fast/slow)
- ATR and volatility regime
- Value area (VAH, VAL, POC)
- Orderbook imbalance
- Trade flow analysis
- Data quality scoring

**Output:** `events:features:{tenant}:{bot}`

### Decision Worker

**Source:** `quantgambit/signals/decision_worker.py`

Runs the decision pipeline stages:

1. **DataReadinessStage** - Validates features present
2. **ProfileRoutingStage** - Selects trading profile
3. **PositionEvaluationStage** - Generates exit signals
4. **PredictionStage** - ML/heuristic direction
5. **SignalStage** - Strategy signal generation
6. **RiskStage** - Pre-sizing risk check
7. **ExecutionStage** - Signal finalization

**Output:** `events:decisions:{tenant}:{bot}`

### Risk Worker

**Source:** `quantgambit/risk/risk_worker.py`

Applies position sizing and risk guardrails:

- Max positions check
- Exposure limits
- Drawdown limits
- Position sizing calculation
- Exit signal passthrough (bypass position checks)

**Output:** `events:risk_decisions:{tenant}:{bot}`

### Execution Worker

**Source:** `quantgambit/execution/execution_worker.py`

Executes trading decisions:

- Symbol throttling (min interval between orders)
- Position existence check
- Idempotency deduplication
- Order placement via ExecutionManager
- Status polling and retry logic

## Execution Layer

### Adapter Hierarchy

```
ExecutionManager
       │
       ├── GuardedExchangeClient (rate limit, circuit breaker)
       │          │
       │          └── Live Adapter (OKX/Bybit/Binance)
       │                    │
       │                    └── ccxt client
       │
       └── PaperExchangeAdapter (simulation)
```

### Position Management

**InMemoryStateManager** (`portfolio/state_manager.py`):
- Tracks open positions in memory
- Supports position accumulation (weighted avg entry)
- Async position listing for pipeline

**PositionManager Interface:**
- `list_open_positions()` - Get current positions
- `upsert_position()` - Add/update position
- `mark_closing()` - Flag position for closure
- `finalize_close()` - Remove position

## Security

### Credential Flow

1. User stores credentials via Dashboard → Backend
2. Backend encrypts and stores in `.secrets/` directory
3. Runtime receives `EXCHANGE_SECRET_ID` env var
4. Runtime fetches decrypted credentials from secrets store
5. Credentials never appear in Redis or logs

### Multi-Tenancy

- All Redis keys namespaced: `quantgambit:{tenant_id}:{bot_id}:*`
- Control commands scoped to tenant
- Database queries filtered by `tenant_id`

## Configuration

### Environment Variable Sources

| Source | Examples | When Set |
|--------|----------|----------|
| `.env` file | `REDIS_URL`, `DB_HOST` | Process start |
| `ecosystem.config.js` | Service-specific defaults | PM2 start |
| Control Manager | `TENANT_ID`, `BOT_ID`, `ACTIVE_EXCHANGE` | Runtime launch |
| Dashboard DB | Risk config, execution config | Runtime launch |
| Secrets Store | API keys, secrets | Runtime fetch |

### Configuration Layers

1. **Platform defaults** - Hardcoded in Python
2. **Environment overrides** - Via env vars
3. **Bot configuration** - From `bots` table
4. **Exchange configuration** - From `exchange_configs` table
5. **Runtime overrides** - Via `PROFILE_OVERRIDES` JSON

## Observability

### Logging

Structured JSON logging via `observability/logger.py`:

```python
log_info("event_name", key1=value1, key2=value2)
log_warning("event_name", error=str(exc))
log_error("event_name", error=str(exc))
```

### Telemetry

**TelemetryPipeline** publishes to:
- Redis Streams (real-time)
- TimescaleDB (durable)

Events: decisions, orders, predictions, guardrails, latency

### Health Monitoring

- Control Manager publishes platform health every 5s
- Bot runtime writes warmup status
- Dashboard polls health snapshots

## File Structure

```
deeptrader/
├── deeptrader-dashhboard/     # React frontend
├── deeptrader-backend/        # Node.js API
├── quantgambit-python/        # Python trading engine
│   ├── quantgambit/
│   │   ├── api/              # Python REST API
│   │   ├── config/           # Configuration system
│   │   ├── control/          # Control plane
│   │   ├── execution/        # Order execution
│   │   ├── ingest/           # Market data ingestion
│   │   ├── market/           # Market data providers
│   │   ├── observability/    # Logging, telemetry
│   │   ├── portfolio/        # State management
│   │   ├── profiles/         # Profile routing
│   │   ├── risk/             # Risk management
│   │   ├── runtime/          # Bot runtime
│   │   ├── signals/          # Decision pipeline
│   │   ├── storage/          # Redis, Postgres
│   │   └── strategies/       # Strategy registry
│   └── docs/                 # Documentation
├── market-data-service/      # Exchange data aggregator
├── scripts/                  # Launch/utility scripts
└── ecosystem.config.js       # PM2 configuration
```

## Related Documentation

- [LAUNCH_FLOW.md](LAUNCH_FLOW.md) - Detailed bot startup sequence
- [HOT_PATH.md](HOT_PATH.md) - Trading pipeline performance
- [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) - All configuration options
- [CONTROL_PLANE.md](CONTROL_PLANE.md) - Command handling
