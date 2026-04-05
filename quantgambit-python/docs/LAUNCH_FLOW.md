# Bot Launch Flow

This document details the complete sequence of events when a user starts a trading bot from the dashboard.

## Overview

```
Dashboard → Backend → Redis → Control Manager → PM2 → Runtime → Trading
   (1)       (2)       (3)         (4)          (5)      (6)       (7)
```

## Phase 1: Dashboard Initiates Start

**Location:** `deeptrader-dashhboard/src/components/run-bar.tsx`

When the user clicks "Start" in the RunBar:

1. `BotStartupModal` opens with phase `"sending_command"`
2. POST request to `/api/control/command` with:
   ```json
   {
     "type": "start_bot",
     "tenantId": "user-uuid",
     "botId": "bot-uuid",
     "exchangeAccountId": "exchange-account-uuid"
   }
   ```

## Phase 2: Backend Builds Start Payload

**Location:** `deeptrader-backend/routes/control.js` → `buildStartPayload()`

The backend assembles a comprehensive payload:

```javascript
const payload = {
  // Identity
  tenant_id: tenantId,
  bot_id: botId,
  
  // Exchange configuration
  exchange: "bybit",                    // from exchange_account.venue
  environment: "testnet",               // testnet | mainnet
  trading_mode: "paper",                // paper | live
  is_testnet: true,                     // derived from environment
  market_type: "perp",                  // spot | perp
  margin_mode: "isolated",              // isolated | cross
  
  // Symbols to trade
  enabled_symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
  
  // Risk configuration (from exchange_configs table)
  risk_config: {
    max_positions: 4,
    max_positions_per_symbol: 1,
    risk_per_trade_pct: 5.0,
    max_total_exposure_pct: 50.0,
    max_daily_drawdown_pct: 5.0,
    max_drawdown_pct: 10.0,
    min_position_size_usd: 500.0,
    max_position_size_usd: 5000.0
  },
  
  // Execution configuration
  execution_config: {
    max_decision_age_sec: 60.0,
    min_order_interval_sec: 60.0,
    block_if_position_exists: true,
    max_order_retries: 2
  },
  
  // Profile/strategy overrides
  profile_overrides: {},
  
  // Exchange account details (for runtime credential fetch)
  exchange_account: {
    id: "uuid",
    label: "Bybit Testnet",
    venue: "bybit",
    environment: "testnet",
    is_testnet: true,
    secret_id: "deeptrader/dev/user-uuid/bybit",  // For secrets store lookup
    exchange_balance: 10000.0,
    available_balance: 8500.0,
    balance_currency: "USDT"
  },
  
  // Redis stream names for market data
  streams: {
    orderbook: "events:orderbook_feed:bybit",
    trades: "events:trades:bybit",
    market_data: "events:market_data:bybit"
  },
  
  // Bot metadata
  bot: {
    id: "uuid",
    name: "My Trading Bot",
    allocator_role: "primary"
  }
};
```

## Phase 3: Command Published to Redis

**Location:** `deeptrader-backend/services/controlQueueService.js` → `enqueueCommand()`

1. Generate unique `command_id`
2. Check start lock doesn't exist: `control:start_lock:{tenant}:{bot}`
3. Publish to Redis stream: `commands:control:{tenant}:{bot}`

```javascript
const command = {
  command_id: "uuid",
  type: "start_bot",
  scope: {
    tenant_id: tenantId,
    bot_id: botId
  },
  requested_by: "dashboard",
  requested_at: "2024-01-01T00:00:00Z",
  schema_version: "v1",
  payload: payload  // Full payload from step 2
};

await redis.xadd(stream, '*', 'data', JSON.stringify(command));
```

4. Set start lock with 300s TTL (covers warmup)
5. Return `commandId` and `resultStream` to dashboard

## Phase 4: Control Manager Handles Command

**Location:** `quantgambit-python/quantgambit/control/command_manager.py`

The Control Manager (always running via PM2) processes the command:

### 4.1 Command Consumption

```python
messages = await self.redis_client.read_group(
    self.cfg.consumer_group,
    self.cfg.consumer_name,
    {stream: ">" for stream in self._stream_cache},
    block_ms=self.cfg.block_ms,
)
```

### 4.2 Command Validation

```python
async def _handle_start(self, command_id, scope, payload, ...):
    # Check not already starting
    lock_key = f"control:bot_status:{tenant_id}:{bot_id}"
    if await self.redis_client.redis.exists(lock_key):
        await self._publish_result(command_id, "failed", "already_starting")
        return
    
    # Set lock for warmup period
    await self.redis_client.redis.set(lock_key, "starting", ex=300)
    
    # Publish queued status
    await self._publish_result(command_id, "queued", "accepted")
```

### 4.3 Build Runtime Environment

```python
def _build_runtime_env(self, scope, payload):
    env = {}
    
    # Exchange settings
    env["ACTIVE_EXCHANGE"] = payload.get("exchange")
    env["TRADING_MODE"] = payload.get("trading_mode")
    env["EXECUTION_PROVIDER"] = "ccxt" if live else "none"
    env["MARKET_TYPE"] = payload.get("market_type")
    env["MARGIN_MODE"] = payload.get("margin_mode")
    
    # Symbols
    env["ORDERBOOK_SYMBOLS"] = ",".join(payload.get("enabled_symbols", []))
    
    # Testnet flags
    env["ORDERBOOK_TESTNET"] = str(payload.get("is_testnet", False)).lower()
    env["BYBIT_TESTNET"] = str(payload.get("is_testnet", False)).lower()
    
    # Stream names
    streams = payload.get("streams", {})
    env["ORDERBOOK_EVENT_STREAM"] = streams.get("orderbook")
    env["TRADE_STREAM"] = streams.get("trades")
    env["MARKET_DATA_STREAM"] = streams.get("market_data")
    
    # Secure credential reference (not the actual key!)
    exchange_account = payload.get("exchange_account", {})
    env["EXCHANGE_SECRET_ID"] = exchange_account.get("secret_id")
    env["EXCHANGE_ACCOUNT_ID"] = exchange_account.get("id")
    
    # Account balance for sizing
    env["LIVE_EQUITY"] = str(exchange_account.get("exchange_balance") or "")
    
    # Risk parameters
    risk_config = payload.get("risk_config", {})
    env["RISK_PER_TRADE_PCT"] = str(risk_config.get("risk_per_trade_pct", 5.0))
    env["MIN_POSITION_SIZE_USD"] = str(risk_config.get("min_position_size_usd", 500.0))
    env["MAX_POSITIONS"] = str(risk_config.get("max_positions", 4))
    # ... more risk params
    
    # Execution parameters
    exec_config = payload.get("execution_config", {})
    env["MAX_DECISION_AGE_SEC"] = str(exec_config.get("max_decision_age_sec", 60.0))
    env["MIN_ORDER_INTERVAL_SEC"] = str(exec_config.get("min_order_interval_sec", 60.0))
    # ... more exec params
    
    return env
```

## Phase 5: PM2 Spawns Runtime

**Location:** `scripts/launch-runtime.sh`

### 5.1 Pre-flight Checks

```bash
# Check if already running
RUNTIME_STATUS=$(pm2 show "$RUNTIME_NAME" | grep status)
if [ "$RUNTIME_STATUS" = "online" ]; then
    echo "Runtime already running - skipping restart"
    exit 0
fi

# Delete stopped/errored instances
pm2 delete "$RUNTIME_NAME" 2>/dev/null || true
```

### 5.2 Generate PM2 Config

```bash
CONFIG_FILE="/tmp/runtime-${TENANT_ID}-${BOT_ID}.config.js"

cat > "$CONFIG_FILE" << EOF
module.exports = {
  apps: [{
    name: 'runtime-${TENANT_ID}-${BOT_ID}',
    script: '${PYTHON_PATH}',
    args: '-m quantgambit.runtime.entrypoint',
    cwd: '${PROJECT_ROOT}/quantgambit-python',
    env: {
      PYTHONPATH: '${PROJECT_ROOT}/quantgambit-python',
      TENANT_ID: '${TENANT_ID}',
      BOT_ID: '${BOT_ID}',
      ACTIVE_EXCHANGE: '${ACTIVE_EXCHANGE}',
      TRADING_MODE: '${TRADING_MODE}',
      // ... all env vars from Control Manager
    }
  }]
};
EOF
```

### 5.3 Start Runtime

```bash
pm2 start "$CONFIG_FILE"
rm -f "$CONFIG_FILE"  # Clean up
```

## Phase 6: Runtime Bootstrap

**Location:** `quantgambit-python/quantgambit/runtime/entrypoint.py`

### 6.1 Load Configuration

```python
async def run():
    tenant_id = os.getenv("TENANT_ID")
    bot_id = os.getenv("BOT_ID")
    exchange = os.getenv("ACTIVE_EXCHANGE")
    trading_mode = os.getenv("TRADING_MODE")
    # ... parse all env vars
```

### 6.2 Connect to Storage

```python
redis_client = redis.from_url(redis_url)
timescale_pool = await asyncpg.create_pool(timescale_url)
```

### 6.3 Load Credentials

```python
# Secure credential loading from secrets store
secret_id = os.getenv("EXCHANGE_SECRET_ID")
if secret_id:
    credentials = get_exchange_credentials(secret_id)
    # credentials.api_key, credentials.secret_key, credentials.passphrase
```

### 6.4 Build Providers

```python
# Market data provider
market_data_provider = CcxtTickerProvider(
    exchange=exchange,
    symbols=symbols,
    testnet=testnet
)

# Trade provider (WebSocket)
trade_provider = BybitTradeWebsocketProvider(
    symbol, testnet=testnet
)

# Order update provider (WebSocket)
order_update_provider = BybitOrderUpdateProvider(
    BybitWsCredentials(
        api_key=credentials.api_key,
        secret_key=credentials.secret_key,
        testnet=testnet
    )
)

# Execution adapter
execution_adapter = BybitLiveAdapter(ccxt_client)
```

### 6.5 Initialize Runtime

```python
runtime = Runtime(
    config=RuntimeConfig(
        tenant_id=tenant_id,
        bot_id=bot_id,
        exchange=exchange,
        trading_mode=trading_mode,
        # ...
    ),
    redis=redis_client,
    timescale_pool=timescale_pool,
    state_manager=InMemoryStateManager(),
    market_data_provider=market_data_provider,
    execution_adapter=execution_adapter,
    # ...
)

await runtime.start()
```

## Phase 7: Workers Start

**Location:** `quantgambit-python/quantgambit/runtime/app.py` → `Runtime.start()`

### 7.1 Worker Initialization

```python
async def start(self):
    # Create all Redis consumer groups
    await self._ensure_streams()
    
    # Start workers as concurrent tasks
    tasks = [
        asyncio.create_task(self.orderbook_worker.run()),
        asyncio.create_task(self.feature_worker.run()),
        asyncio.create_task(self.candle_worker.run()),
        asyncio.create_task(self.decision_worker.run()),
        asyncio.create_task(self.risk_worker.run()),
        asyncio.create_task(self.execution_worker.run()),
        asyncio.create_task(self.health_worker.run()),
        # Optional workers based on config
    ]
    
    if self.trade_worker:
        tasks.append(asyncio.create_task(self.trade_worker.run()))
    
    if self.order_update_worker:
        tasks.append(asyncio.create_task(self.order_update_worker.run()))
    
    # Also start control consumer for runtime commands
    tasks.append(asyncio.create_task(self.control_consumer.run()))
    
    await asyncio.gather(*tasks)
```

### 7.2 Warmup Phase

The **Decision Worker** implements warmup gating:

```python
class WarmupTracker:
    def __init__(self, min_samples=5, min_age_sec=10.0):
        self.min_samples = min_samples
        self.min_age_sec = min_age_sec
        self._samples: Dict[str, int] = {}
        self._first_seen: Dict[str, float] = {}
    
    def record(self, symbol: str, timestamp, candle_count: int):
        if symbol not in self._first_seen:
            self._first_seen[symbol] = time.time()
        self._samples[symbol] = self._samples.get(symbol, 0) + 1
        
        age = time.time() - self._first_seen[symbol]
        warmed = (
            self._samples[symbol] >= self.min_samples
            and age >= self.min_age_sec
        )
        return warmed, {
            "samples": self._samples[symbol],
            "age_sec": age,
            "ready": warmed
        }
```

Warmup status is published to Redis for dashboard display:

```python
await self._write_warmup_snapshot(
    symbol,
    warmup_ready,
    stats,
    candle_count,
    warmup_reasons,
    quality_score,
    market_context,
)
```

### 7.3 Trading Ready

Once warmup completes:
1. Decision Worker begins processing signals
2. Dashboard receives `warmup:status` update with `ready: true`
3. `BotStartupModal` transitions to "ready" phase
4. Trading begins

## Startup Timeline

```
T+0s    User clicks Start
T+0.1s  Command published to Redis
T+0.2s  Control Manager receives command
T+0.5s  PM2 starts runtime process
T+1s    Redis/TimescaleDB connected
T+1.5s  Workers initialized
T+2s    First market tick consumed
T+5s    Feature computation begins
T+10s   Warmup minimum age reached
T+10s+  First decisions generated (if quality sufficient)
T+30s   Typical warmup complete (stable data quality)
```

## Error Handling

### Dashboard Timeout

If no progress after 60s, dashboard shows error and allows retry.

### Control Manager Errors

```python
try:
    launch_ok = await self._maybe_launch_runtime(...)
except Exception as exc:
    log_error("control_launch_exception", error=str(exc))
    await self._publish_result(command_id, "failed", "launch_failed")
```

### Runtime Crash

PM2 auto-restarts crashed runtimes (configurable):

```javascript
{
  autorestart: true,
  max_restarts: 10,
  min_uptime: '10s',
  restart_delay: 5000
}
```

### Lock Cleanup

Start locks are cleared on:
- Successful completion
- Command failure
- 300s TTL expiration (failsafe)

## Shutdown Flow

### User Stop

1. Dashboard sends `stop_bot` command
2. Control Manager calls `scripts/stop-runtime.sh`
3. PM2 stops the runtime process
4. Workers receive shutdown signal
5. Open orders can be cancelled (flatten_positions)
6. Position state persisted to Redis snapshot

### Graceful Shutdown

```python
async def shutdown(self):
    # Stop accepting new decisions
    self._shutting_down = True
    
    # Wait for in-flight orders
    await self._wait_for_pending_orders(timeout=10)
    
    # Close connections
    await self.redis_client.close()
    await self.timescale_pool.close()
```

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System overview
- [HOT_PATH.md](HOT_PATH.md) - Trading pipeline details
- [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) - All configuration options
