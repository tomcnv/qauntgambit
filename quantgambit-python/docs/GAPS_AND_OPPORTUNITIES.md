# Gaps and Opportunities

This document identifies technical gaps, missing features, and improvement opportunities in the DeepTrader bot platform.

> **Last Updated:** January 2026 - Many critical gaps have been addressed with quant-grade infrastructure.

## Executive Summary

The platform has a solid foundation with:
- ✅ Multi-exchange support (OKX, Bybit, Binance)
- ✅ Clean stage-based decision pipeline
- ✅ Redis Streams for real-time event processing
- ✅ Comprehensive risk controls
- ✅ Dashboard with startup progress tracking
- ✅ **NEW: Kill switch with Redis persistence**
- ✅ **NEW: Reconciliation worker for state healing**
- ✅ **NEW: Latency tracking (p50/p95/p99)**
- ✅ **NEW: Config bundle management with audit trail**

Key areas for improvement:
- ~~🔴 Position state synchronization reliability~~ → ✅ **FIXED** (ReconciliationWorker)
- 🟡 Configuration hot-reload not active → Partially addressed (ConfigBundleManager)
- ~~🟡 No latency aggregation metrics~~ → ✅ **FIXED** (LatencyTracker)
- 🟡 Limited observability tooling → Improved (API endpoints added)

---

## Critical Gaps

### 1. Position State Desync

**Severity:** ✅ **RESOLVED**

**Problem:**
Local position state (in `InMemoryStateManager`) can become desynchronized with actual exchange positions.

**Solution Implemented:**
A comprehensive `ReconciliationWorker` has been implemented in `quantgambit/core/reconciliation/worker.py`:

```python
# Detects and heals:
# - Ghost orders (local but not on exchange)
# - Orphan orders (on exchange but not local)
# - Ghost positions (local but not on exchange)
# - Orphan positions (on exchange but not local)
# - Size mismatches (local != exchange)
# - Filled quantity mismatches
```

**API Endpoints:**
- `GET /api/quant/reconciliation/status` - Worker status and stats
- `GET /api/quant/reconciliation/discrepancies` - Recent discrepancies

**Environment Variables:**
- `RECONCILIATION_INTERVAL_SEC=30` - How often to reconcile
- `RECONCILIATION_AUTO_HEAL=true` - Enable automatic healing

---

### 2. Configuration Hot-Reload Not Active

**Severity:** 🟡 Medium

**Problem:**
The `ConfigWatcher` class exists and can consume config update events from Redis, but:
- No runtime components actually use it
- Config changes require full bot restart
- Risk parameters can't be adjusted without stopping trading

**Current State:**
```python
# config/watcher.py exists but not wired in runtime
class ConfigWatcher:
    async def start(self) -> None:
        await self.redis.create_group(self.stream, self.consumer_group)
        while True:
            messages = await self.redis.read_group(...)
            for message in messages:
                await self._handle_message(payload)
```

**Gaps:**
- RuntimeConfigApplier not connected to workers
- No UI to push config updates without restart
- SafeConfigApplier checks (paused, no positions) not enforced

**Recommended Solution:**
1. Wire `ConfigWatcher` into `Runtime.start()`
2. Implement safe config application:
   - Check trading is paused
   - Verify no open positions for risk limit changes
   - Queue updates if unsafe, auto-apply when conditions met
3. Add dashboard button "Update Config" that publishes to `events:config`

**Implementation Effort:** Medium (2-3 days)

---

### 3. No Latency Aggregation

**Severity:** 🟡 Medium

**Problem:**
Individual operation latencies are logged but not aggregated into p50/p95/p99 metrics. This makes it difficult to:
- Monitor hot path performance over time
- Detect gradual degradation
- Set alerts on latency SLOs

**Current State:**
```python
# Decision payload includes raw latency
decision_payload = {
    "latency_ms": (time.time() - snapshot_ts) * 1000,
}
```

But no aggregation exists.

**Recommended Solution:**

```python
class LatencyAggregator:
    def __init__(self, window_sec: float = 60.0):
        self._samples: Dict[str, deque] = {}
        self._window_sec = window_sec
    
    def record(self, operation: str, latency_ms: float):
        now = time.time()
        samples = self._samples.setdefault(operation, deque())
        samples.append((now, latency_ms))
        
        # Trim old samples
        cutoff = now - self._window_sec
        while samples and samples[0][0] < cutoff:
            samples.popleft()
    
    def get_percentiles(self, operation: str) -> dict:
        samples = self._samples.get(operation, [])
        if not samples:
            return {}
        
        values = sorted(s[1] for s in samples)
        return {
            "p50": self._percentile(values, 50),
            "p95": self._percentile(values, 95),
            "p99": self._percentile(values, 99),
            "count": len(values),
        }
```

Publish periodically to Redis snapshot:
```
quantgambit:{tenant}:{bot}:latency:latest
```

**Implementation Effort:** Low (1 day)

---

## Medium Priority Improvements

### 4. Dashboard Risk Override UI

**Severity:** 🟡 Medium

**Problem:**
`RiskOverrideStore` exists and can temporarily modify risk parameters, but there's no UI to:
- View current overrides
- Apply new overrides
- Set override TTL
- Clear overrides

**Current State:**
```python
# risk/overrides.py
class RiskOverrideStore:
    async def set_override(self, key: str, value: float, ttl_sec: int):
        ...
    async def get_overrides(self) -> Dict[str, float]:
        ...
```

**Recommended Solution:**
Add dashboard panel for runtime risk adjustments:
- Emergency disable trading: `trading_enabled: false`
- Reduce exposure: `max_total_exposure_pct: 20%`
- Pause symbol: `symbol_blocked: true`
- Set TTL for auto-expiration

**Implementation Effort:** Medium (2-3 days including UI)

---

### 5. Alerting Integration

**Severity:** 🟡 Medium

**Problem:**
`AlertsClient` is wired throughout the codebase but not connected to external notification systems. Alerts are logged but not delivered to:
- Slack
- Discord
- Email
- PagerDuty

**Current State:**
```python
# observability/alerts.py
class AlertsClient:
    async def send(self, alert_type: str, message: str, context: dict):
        # Currently just logs
        log_warning("alert", type=alert_type, message=message)
```

**Recommended Solution:**
1. Add webhook configuration per tenant
2. Implement delivery adapters:
   ```python
   class SlackAlertDelivery:
       async def deliver(self, alert):
           await httpx.post(self.webhook_url, json={"text": alert.message})
   ```
3. Add alert routing rules (which alerts to which channels)
4. Rate limit to prevent alert storms

**Implementation Effort:** Medium (2 days)

---

### 6. Profile System Documentation

**Severity:** 🟡 Medium

**Problem:**
The profile routing system (`deeptrader_core`) exists but:
- Limited documentation on how profiles work
- Strategy implementations scattered across modules
- Profile-to-strategy mapping unclear
- Policy filtering logic complex and undocumented

**Gaps:**
- No README for profile system
- No example of creating custom profile
- Context vector fields not fully documented
- Regime mapping not explained

**Recommended Solution:**
1. Add `quantgambit/profiles/README.md` explaining:
   - Profile concept
   - Context vector fields
   - Scoring algorithm
   - Policy filtering
2. Document built-in profiles
3. Add example of custom profile definition

**Implementation Effort:** Low (1 day documentation)

---

## Lower Priority Opportunities

### 7. Credential Rotation Support

**Problem:** API keys can't be rotated without bot restart.

**Solution:** 
- Refresh credentials from secrets store periodically
- Rebuild ccxt client with new credentials
- Support credential update via control command

**Effort:** Medium (2 days)

---

### 8. Multi-Bot Orchestration

**Problem:** Guardian process runs per-tenant but coordination between bots is limited.

**Opportunities:**
- Cross-bot exposure limits
- Portfolio-level risk management
- Shared position tracking
- Coordinated exits during market events

**Effort:** High (1 week+)

---

### 9. Backtest Integration

**Problem:** Backtesting uses separate code path, making it hard to verify production logic.

**Solution:**
- Replay historical data through same pipeline
- Mock execution adapter for fill simulation
- Compare backtest vs live behavior

**Effort:** High (1-2 weeks)

---

### 10. Order Book Replay

**Problem:** No ability to replay historical orderbook data for debugging.

**Solution:**
- Store orderbook snapshots to TimescaleDB
- Implement replay provider
- Support time-travel debugging

**Effort:** Medium (3-5 days)

---

### 11. Position Guardian Enhancement

**Problem:** Position guard exists but is basic.

**Opportunities:**
- Trailing stop implementation
- Time-based position aging
- Correlation-based exits
- Volatility-adjusted stops

**Effort:** Medium (2-3 days)

---

### 12. Multi-Tenant Isolation

**Problem:** Current design assumes single-tenant deployment.

**Gaps:**
- No resource limits per tenant
- No rate limiting per tenant
- Shared Redis streams for some data

**Effort:** High (1 week)

---

## Technical Debt

### 1. Symbol Normalization Complexity

Multiple places handle symbol format conversion:
- `_normalize_symbol()` in pipeline.py
- `normalize_exchange_symbol()` in symbols.py
- Ad-hoc normalization in adapters

**Recommendation:** Centralize in single utility module.

---

### 2. Environment Variable Proliferation

100+ environment variables with inconsistent naming:
- Some use `_` separator: `MAX_POSITIONS`
- Some use service prefix: `FEATURE_GATE_ORDERBOOK_GAP`
- Some duplicated: `PAPER_EQUITY` vs `LIVE_EQUITY`

**Recommendation:** Create config schema with validation.

---

### 3. Test Coverage Gaps

Critical paths with limited test coverage:
- Live adapter error handling
- Position reconciliation
- WebSocket reconnection

**Recommendation:** Add integration tests with mock exchange.

---

## Prioritized Roadmap

### Phase 1: Stability (Week 1-2)
| Item | Priority | Effort |
|------|----------|--------|
| Position reconciliation worker | 🔴 Critical | 2 days |
| Latency aggregation | 🟡 Medium | 1 day |
| Symbol normalization cleanup | 🟢 Low | 0.5 day |

### Phase 2: Operations (Week 3-4)
| Item | Priority | Effort |
|------|----------|--------|
| Dashboard risk override UI | 🟡 Medium | 3 days |
| Alerting integration | 🟡 Medium | 2 days |
| Config hot-reload | 🟡 Medium | 3 days |

### Phase 3: Features (Week 5-8)
| Item | Priority | Effort |
|------|----------|--------|
| Profile documentation | 🟡 Medium | 1 day |
| Credential rotation | 🟢 Low | 2 days |
| Position guardian enhancement | 🟢 Low | 3 days |
| Backtest integration | 🟢 Low | 2 weeks |

---

## Metrics to Track

After improvements, measure:

| Metric | Target | Current |
|--------|--------|---------|
| Position desync rate | <0.1% | Unknown |
| Tick-to-order p95 latency | <300ms | ~270ms |
| Alert delivery latency | <5s | N/A |
| Config apply time | <1s | Restart required |
| Mean time to recovery | <60s | Manual |

---

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - System overview
- [LAUNCH_FLOW.md](LAUNCH_FLOW.md) - Bot startup sequence
- [HOT_PATH.md](HOT_PATH.md) - Trading pipeline
- [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) - Configuration options
