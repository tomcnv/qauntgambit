# Quant-Grade Infrastructure Migration Plan

This document outlines the complete integration of quant-grade infrastructure components into the QuantGambit trading system.

## Overview

The quant-grade infrastructure provides:
- **Kill Switch**: Emergency halt with Redis persistence
- **Config Bundle Management**: Versioned config with approval workflow
- **Reconciliation Worker**: Order/position state healing
- **Latency Tracking**: p50/p95/p99 metrics for critical paths
- **Book Guardian**: Market data integrity gates

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer                                │
│  /api/quant/kill-switch/*    /api/quant/config-bundles/*        │
│  /api/quant/reconciliation/* /api/quant/latency/*               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Redis (State Store)                         │
│  quantgambit:{tenant}:{bot}:kill_switch:state                   │
│  quantgambit:{tenant}:config:bundles:*                          │
│  quantgambit:{tenant}:{bot}:reconciliation:status               │
│  quantgambit:{tenant}:{bot}:latency:metrics                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Runtime (Bot Process)                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   QuantIntegration                        │   │
│  │  ├── PersistentKillSwitch                                │   │
│  │  ├── ReconciliationWorker                                │   │
│  │  └── LatencyTracker                                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                            │                                     │
│  ┌─────────────┐  ┌────────┴───────┐  ┌─────────────────────┐   │
│  │FeatureWorker│  │DecisionWorker │  │ ExecutionWorker     │   │
│  └─────────────┘  └────────────────┘  └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Step-by-Step Integration

### Step 1: Enable the Quant API Endpoints ✅

The quant router is already wired into the main API:

```python
# quantgambit/api/app.py
from quantgambit.api.quant_endpoints import router as quant_router

def create_app():
    app = FastAPI(...)
    app.include_router(quant_router)  # ✅ Already added
```

### Step 2: Add QuantIntegration to Runtime

Modify `runtime/app.py` to initialize QuantIntegration:

```python
# In Runtime.__init__, add:
from quantgambit.runtime.quant_integration import (
    QuantIntegration,
    OrderStoreAdapter,
    PositionStoreAdapter,
    ExchangeClientAdapter,
)

class Runtime:
    def __init__(self, ...):
        # ... existing init code ...
        
        # Initialize quant integration
        self.quant = QuantIntegration(
            redis_client=redis,
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            order_store=OrderStoreAdapter(self.order_store),
            position_store=PositionStoreAdapter(self.state_manager),
            exchange_client=ExchangeClientAdapter(self.execution_manager.exchange_client),
        )
```

### Step 3: Start/Stop QuantIntegration in Runtime Lifecycle

```python
# In Runtime.start(), add:
async def start(self) -> None:
    # ... existing startup code ...
    
    # Start quant integration
    await self.quant.start()
    
    # ... rest of startup ...

# Add shutdown method:
async def stop(self) -> None:
    await self.quant.stop()
```

### Step 4: Add Kill Switch Checks to Decision Pipeline

```python
# In DecisionWorker, add kill switch check:
async def _process_snapshot(self, snapshot):
    # Check kill switch before making decisions
    if self.quant and self.quant.is_kill_switch_active():
        logger.warning("Kill switch active - skipping decision")
        return None
    
    # ... rest of decision logic ...
```

### Step 5: Add Latency Tracking to Workers

```python
# In FeatureWorker._process():
async def _process(self):
    start = self.quant.start_latency_timer("feature_worker")
    try:
        # ... existing logic ...
    finally:
        self.quant.end_latency_timer("feature_worker", start)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RECONCILIATION_INTERVAL_SEC` | 30.0 | Interval between reconciliation runs |
| `RECONCILIATION_AUTO_HEAL` | true | Enable automatic state healing |
| `QUANT_STATS_INTERVAL_SEC` | 5.0 | Interval for publishing stats to Redis |
| `LATENCY_WINDOW_SIZE` | 1000 | Number of latency samples to keep |

## API Endpoints

### Kill Switch

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/quant/kill-switch/status` | GET | Get current kill switch state |
| `/api/quant/kill-switch/trigger` | POST | Manually trigger kill switch |
| `/api/quant/kill-switch/reset` | POST | Reset kill switch |
| `/api/quant/kill-switch/history` | GET | Get trigger/reset history |

### Config Bundles

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/quant/config-bundles` | GET | List all bundles |
| `/api/quant/config-bundles` | POST | Create new bundle |
| `/api/quant/config-bundles/active` | GET | Get active bundle |
| `/api/quant/config-bundles/{id}/submit` | POST | Submit for approval |
| `/api/quant/config-bundles/{id}/approve` | POST | Approve bundle |
| `/api/quant/config-bundles/{id}/activate` | POST | Activate bundle |
| `/api/quant/config-bundles/rollback` | POST | Rollback to previous |
| `/api/quant/config-bundles/{id}/audit` | GET | Get audit log |

### Reconciliation

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/quant/reconciliation/status` | GET | Get worker status |
| `/api/quant/reconciliation/discrepancies` | GET | Get recent discrepancies |

### Latency

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/quant/latency/metrics` | GET | Get p50/p95/p99 for all metrics |
| `/api/quant/hot-path/stats` | GET | Get hot path statistics |

## Testing the Integration

### 1. Unit Tests

```bash
cd /Users/thomas/projects/deeptrader/quantgambit-python
source venv311/bin/activate

# Run all quant-related tests
python -m pytest quantgambit/tests/unit/test_config_audit.py -v
python -m pytest quantgambit/tests/integration/test_reconciliation_worker.py -v
python -m pytest quantgambit/tests/integration/test_sim_exchange_flow.py -v
```

### 2. API Testing

```bash
# Start the API server
python -m quantgambit.api.app

# Test kill switch endpoints
curl "http://localhost:8000/api/quant/kill-switch/status?tenant_id=test&bot_id=test"

curl -X POST "http://localhost:8000/api/quant/kill-switch/trigger?tenant_id=test&bot_id=test" \
  -H "Content-Type: application/json" \
  -d '{"trigger": "OPERATOR_TRIGGER", "message": "Manual test trigger"}'

curl -X POST "http://localhost:8000/api/quant/kill-switch/reset?tenant_id=test&bot_id=test" \
  -H "Content-Type: application/json" \
  -d '{"operator_id": "admin"}'

# Test config bundle endpoints
curl "http://localhost:8000/api/quant/config-bundles?tenant_id=test"

curl -X POST "http://localhost:8000/api/quant/config-bundles?tenant_id=test&created_by=admin" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Bundle", "description": "Testing config bundles"}'
```

### 3. Integration Testing with Redis

```python
import asyncio
import redis.asyncio as redis

async def test_full_integration():
    # Connect to Redis
    client = redis.from_url("redis://localhost:6379/0")
    
    # Test kill switch persistence
    from quantgambit.core.risk.kill_switch_store import (
        PersistentKillSwitch,
        RedisKillSwitchStore,
    )
    from quantgambit.core.clock import WallClock
    from quantgambit.core.risk.kill_switch import KillSwitchTrigger
    
    clock = WallClock()
    store = RedisKillSwitchStore(client, "test_tenant", "test_bot")
    kill_switch = PersistentKillSwitch(clock, store)
    
    await kill_switch.initialize()
    print(f"Initial state: active={kill_switch.is_active()}")
    
    await kill_switch.trigger(KillSwitchTrigger.OPERATOR_TRIGGER, "Test trigger")
    print(f"After trigger: active={kill_switch.is_active()}")
    
    await kill_switch.reset("test_admin")
    print(f"After reset: active={kill_switch.is_active()}")
    
    await client.close()

asyncio.run(test_full_integration())
```

## Rollout Plan

### Phase 1: Shadow Mode (Week 1)
- Deploy quant endpoints alongside existing system
- QuantIntegration runs but doesn't affect trading
- Monitor latency metrics and reconciliation findings
- Kill switch triggers only log, don't halt

### Phase 2: Soft Launch (Week 2)
- Enable kill switch enforcement on one bot
- Enable auto-healing for reconciliation
- Monitor for false positives
- Tune thresholds based on observations

### Phase 3: Full Deployment (Week 3+)
- Roll out to all bots
- Enable config bundle workflow for production changes
- Set up alerting on kill switch triggers
- Document runbooks for operators

## Monitoring

### Key Metrics to Watch

1. **Kill Switch**
   - Trigger frequency
   - Time-to-reset
   - Trigger types distribution

2. **Reconciliation**
   - Discrepancy count per run
   - Healing success rate
   - Ghost/orphan position frequency

3. **Latency**
   - p99 tick-to-decision < 10ms target
   - p99 decision-to-order < 5ms target
   - Any latency spike > 100ms

### Alerts

Configure alerts for:
- Kill switch triggered (Critical)
- Reconciliation found > 5 discrepancies (Warning)
- p99 latency > 50ms (Warning)
- Book guardian staleness > 5s (Critical)

## Rollback Procedure

If issues arise:

1. **Disable QuantIntegration**:
   ```bash
   export QUANT_INTEGRATION_ENABLED=false
   pm2 restart quantgambit-runtime
   ```

2. **Clear Redis State** (if corrupted):
   ```bash
   redis-cli KEYS "quantgambit:*:kill_switch:*" | xargs redis-cli DEL
   redis-cli KEYS "quantgambit:*:config:bundles:*" | xargs redis-cli DEL
   ```

3. **Reset Kill Switch via API**:
   ```bash
   curl -X POST "http://localhost:8000/api/quant/kill-switch/reset?tenant_id=...&bot_id=..." \
     -H "Content-Type: application/json" \
     -d '{"operator_id": "emergency_reset"}'
   ```

## Files Changed

| File | Change |
|------|--------|
| `quantgambit/api/app.py` | Added quant_router import and include |
| `quantgambit/api/quant_endpoints.py` | New - API endpoints |
| `quantgambit/core/config/redis_store.py` | New - Redis bundle store |
| `quantgambit/core/risk/kill_switch_store.py` | New - Redis kill switch |
| `quantgambit/runtime/quant_integration.py` | New - Integration module |
| `quantgambit/execution/reconciliation.py` | New - Reconciliation worker |

## Completion Status

### ✅ Completed

1. ✅ Add QuantIntegration initialization to `runtime/app.py` - Done
2. ✅ Add kill switch checks to DecisionWorker - Done (lines 119-127)
3. ✅ Add kill switch checks to ExecutionWorker - Done (lines 115-123)
4. ✅ Add latency tracking to FeatureWorker - Done (lines 148-159)
5. ✅ Add latency tracking to DecisionWorker - Done (lines 104-115)
6. ✅ Add latency tracking to ExecutionWorker - Done (lines 100-111)
7. ✅ Create Redis-backed stores - Done
8. ✅ Wire kill switch and latency tracker from Runtime to workers - Done
9. ✅ API endpoints for kill switch, config bundles, reconciliation - Done

### 🔲 Remaining

1. ☐ Set up monitoring dashboards (frontend)
2. ☐ Create operator runbooks
3. ☐ Schedule Phase 1 deployment
4. ☐ Add Slack/Discord alerting integration
