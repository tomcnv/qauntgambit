# High-Impact Implementation Plan (Revised)

**Date:** January 2026  
**Status:** Ready for Implementation  
**Estimated Total Effort:** 2-3 days

---

## Executive Summary

| # | Item | Impact | Effort | Priority |
|---|------|--------|--------|----------|
| 1 | **Guard Alerting** | Know when guards fire | 3-4h | 🔴 High |
| 2 | **Correlation Guard** | Prevent concentrated risk | 4h | 🔴 High |
| 3 | **Dashboard Latency Graphs** | See performance trends | 4-5h | 🟠 High |
| 4 | **Guard Activity Panel** | Visibility into guard actions | 2-3h | 🟠 High |

**Deferred to Future:**
- Order book recording (debug tool, defer until needed)
- Dynamic correlation calculation (premature optimization)

---

## Day 1: Guard Alerting + Correlation Guard (8h)

### 1A. Guard Alerting (3-4h)

**Goal:** Slack/Discord alert when any guard triggers (trailing stop, max age, SL/TP)

#### Implementation

```python
# quantgambit/execution/position_guard_worker.py

async def _close_position(self, pos: PositionSnapshot, reason: str) -> None:
    # ... existing close logic ...
    
    # NEW: Send alert
    if self._alerts_client:
        await self._send_guard_alert(pos, reason, status)

async def _send_guard_alert(
    self, 
    pos: PositionSnapshot, 
    reason: str, 
    status: CloseStatus
) -> None:
    """Send Slack/Discord alert for guard trigger."""
    emoji = {
        "trailing_stop_hit": "📉",
        "stop_loss_hit": "🛑",
        "take_profit_hit": "🎯",
        "max_age_exceeded": "⏰",
    }.get(reason, "⚠️")
    
    pnl_emoji = "🟢" if (status.realized_pnl or 0) > 0 else "🔴"
    
    message = f"""
{emoji} **Position Guard Triggered**
• Symbol: `{pos.symbol}`
• Reason: `{reason}`
• Side: {pos.side}
• Entry: ${pos.entry_price:.2f}
• Exit: ${status.fill_price:.2f}
• PnL: {pnl_emoji} ${status.realized_pnl:.2f} ({status.realized_pnl_pct:.1f}%)
• Hold Time: {status.hold_time_sec:.0f}s
"""
    
    await self._alerts_client.send(
        alert_type="guard_trigger",
        message=message,
        severity="info" if reason == "take_profit_hit" else "warning",
    )
```

#### Wire to Runtime

```python
# In Runtime.__init__ or PositionGuardWorker creation:
self.position_guard_worker = PositionGuardWorker(
    exchange_client=self.exchange_client,
    position_manager=self.position_manager,
    config=guard_config,
    telemetry=self.telemetry,
    telemetry_context=self.telemetry_ctx,
    alerts_client=self.alerts,  # NEW
)
```

#### Test

```python
# tests/unit/test_guard_alerting.py
class TestGuardAlerting:
    @pytest.mark.asyncio
    async def test_trailing_stop_sends_alert(self):
        """Trailing stop trigger should send Slack alert."""
        
    @pytest.mark.asyncio
    async def test_alert_contains_pnl(self):
        """Alert should include P&L information."""
        
    @pytest.mark.asyncio
    async def test_alert_handles_client_failure(self):
        """Alert failure should not crash guard worker."""
```

---

### 1B. Correlation Guard (4h)

**Goal:** Block new positions if too correlated with existing positions

#### Implementation

```python
# quantgambit/core/risk/correlation_guard.py
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

@dataclass
class CorrelationGuardConfig:
    enabled: bool = True
    max_correlation: float = 0.70  # 70% threshold
    
# Static matrix - good enough for now
# TODO: Add dynamic correlation calculation in future
CORRELATION_MATRIX: Dict[Tuple[str, str], float] = {
    # Major pairs (high correlation)
    ("BTCUSDT", "ETHUSDT"): 0.85,
    ("BTCUSDT", "SOLUSDT"): 0.75,
    ("BTCUSDT", "BNBUSDT"): 0.70,
    ("ETHUSDT", "SOLUSDT"): 0.80,
    ("ETHUSDT", "BNBUSDT"): 0.65,
    # Stablecoins (assumed 0 correlation with crypto)
    # Any pair not in matrix defaults to 0.0
}

class CorrelationGuard:
    """
    Block positions if too correlated with existing holdings.
    
    Rules:
    - Same direction + high correlation = BLOCK
    - Opposite direction = ALLOW (hedge)
    - Unknown pair = ALLOW (assume uncorrelated)
    """
    
    def __init__(
        self,
        config: CorrelationGuardConfig,
        correlations: Optional[Dict[Tuple[str, str], float]] = None,
        alerts_client = None,
    ):
        self._config = config
        self._correlations = correlations or CORRELATION_MATRIX
        self._alerts = alerts_client
        
    def get_correlation(self, sym1: str, sym2: str) -> float:
        if sym1 == sym2:
            return 1.0
        # Try both orderings
        return (
            self._correlations.get((sym1, sym2)) or 
            self._correlations.get((sym2, sym1)) or 
            0.0
        )
    
    async def check(
        self,
        new_symbol: str,
        new_side: str,  # "long" or "short"
        existing_positions: List[Dict],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if new position is allowed.
        
        Returns: (allowed, rejection_reason)
        """
        if not self._config.enabled:
            return True, None
            
        for pos in existing_positions:
            if pos.get("size", 0) == 0:
                continue
                
            corr = self.get_correlation(new_symbol, pos["symbol"])
            
            if corr >= self._config.max_correlation:
                pos_side = "long" if pos["size"] > 0 else "short"
                
                # Same direction = concentrated risk
                if new_side == pos_side:
                    reason = f"Correlation block: {new_symbol} is {corr:.0%} correlated with existing {pos['symbol']} {pos_side}"
                    
                    # Alert on block
                    if self._alerts:
                        await self._alerts.send(
                            alert_type="correlation_block",
                            message=f"⚠️ **Position Blocked**\n{reason}",
                            severity="info",
                        )
                    
                    return False, reason
        
        return True, None
```

#### Wire to RiskStage

```python
# quantgambit/signals/pipeline.py - In RiskStage

class RiskStage(Stage):
    def __init__(
        self,
        validator: RiskValidator,
        correlation_guard: Optional[CorrelationGuard] = None,
    ):
        self._validator = validator
        self._correlation_guard = correlation_guard
    
    async def run(self, ctx: StageContext) -> StageResult:
        # Existing risk validation...
        
        # NEW: Correlation check before entry
        if self._correlation_guard and ctx.signal and ctx.signal.direction:
            existing = await self._get_existing_positions(ctx)
            allowed, reason = await self._correlation_guard.check(
                new_symbol=ctx.symbol,
                new_side=ctx.signal.direction,
                existing_positions=existing,
            )
            if not allowed:
                ctx.rejection_reason = reason
                ctx.rejection_stage = "correlation_guard"
                return StageResult.REJECT
        
        return StageResult.CONTINUE
```

#### Tests

```python
# tests/unit/test_correlation_guard.py
class TestCorrelationGuard:
    def test_blocks_btc_when_eth_long_exists(self):
        """BTC long blocked when ETH long exists (85% correlated)."""
        guard = CorrelationGuard(CorrelationGuardConfig(max_correlation=0.7))
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        allowed, reason = await guard.check("BTCUSDT", "long", existing)
        
        assert allowed is False
        assert "85%" in reason
    
    def test_allows_btc_short_when_eth_long(self):
        """BTC short allowed when ETH long exists (hedge)."""
        guard = CorrelationGuard(CorrelationGuardConfig(max_correlation=0.7))
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        allowed, _ = await guard.check("BTCUSDT", "short", existing)
        
        assert allowed is True
    
    def test_allows_uncorrelated_symbols(self):
        """Unknown pairs should be allowed (assume uncorrelated)."""
        guard = CorrelationGuard(CorrelationGuardConfig(max_correlation=0.7))
        existing = [{"symbol": "BTCUSDT", "size": 1.0}]
        
        allowed, _ = await guard.check("DOGEUSDT", "long", existing)
        
        assert allowed is True
    
    def test_respects_threshold(self):
        """Should only block above threshold."""
        guard = CorrelationGuard(CorrelationGuardConfig(max_correlation=0.9))
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        # BTC/ETH is 85%, below 90% threshold
        allowed, _ = await guard.check("BTCUSDT", "long", existing)
        
        assert allowed is True
    
    def test_disabled_allows_all(self):
        """Disabled guard should allow all."""
        guard = CorrelationGuard(CorrelationGuardConfig(enabled=False))
        existing = [{"symbol": "ETHUSDT", "size": 1.0}]
        
        allowed, _ = await guard.check("BTCUSDT", "long", existing)
        
        assert allowed is True
```

---

## Day 2: Dashboard Latency Graphs + Guard Panel (6-8h)

### 2A. Latency History & Graphs (4-5h)

#### Backend: Add History to LatencyTracker

```python
# quantgambit/core/latency.py

@dataclass
class LatencySnapshot:
    timestamp: float
    metrics: Dict[str, Dict[str, float]]  # {operation: {p50, p95, p99, count}}

class LatencyTracker:
    def __init__(self, ...):
        # ... existing init ...
        self._history: List[LatencySnapshot] = []
        self._history_max_size = 360  # 6 hours at 1-minute intervals
        self._last_snapshot_ts = 0.0
        self._snapshot_interval_sec = 60.0  # 1 minute
    
    def _maybe_record_snapshot(self) -> None:
        """Record snapshot every minute."""
        now = self._clock.now()
        if now - self._last_snapshot_ts < self._snapshot_interval_sec:
            return
        
        self._last_snapshot_ts = now
        snapshot = LatencySnapshot(
            timestamp=now,
            metrics=self.get_all_percentiles(),
        )
        self._history.append(snapshot)
        
        # Trim old entries
        while len(self._history) > self._history_max_size:
            self._history.pop(0)
    
    def get_history(
        self, 
        since_ts: float = 0,
        operation: Optional[str] = None,
    ) -> List[Dict]:
        """Get latency history."""
        result = []
        for s in self._history:
            if s.timestamp < since_ts:
                continue
            if operation:
                result.append({
                    "timestamp": s.timestamp,
                    "metrics": {operation: s.metrics.get(operation, {})},
                })
            else:
                result.append({
                    "timestamp": s.timestamp,
                    "metrics": s.metrics,
                })
        return result
```

#### Backend: Add API Endpoint

```python
# quantgambit/api/quant_endpoints.py

@quant_router.get("/latency/history")
async def get_latency_history(
    since: Optional[float] = Query(None, description="Unix timestamp"),
    operation: Optional[str] = Query(None, description="Filter by operation"),
    hours: float = Query(1.0, description="Hours of history"),
):
    """Get historical latency metrics."""
    if since is None:
        since = time.time() - (hours * 3600)
    
    history = latency_tracker.get_history(since_ts=since, operation=operation)
    
    return {
        "history": history,
        "operations": list(latency_tracker.get_all_percentiles().keys()),
    }
```

#### Frontend: React Hook

```typescript
// deeptrader-dashhboard/src/lib/api/quant-hooks.ts

export function useLatencyHistory(operation?: string, hours = 1) {
  return useQuery({
    queryKey: ['latency-history', operation, hours],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (operation) params.set('operation', operation);
      params.set('hours', hours.toString());
      
      const res = await fetch(`/api/quant/latency/history?${params}`);
      return res.json();
    },
    refetchInterval: 60_000, // Refresh every minute
  });
}
```

#### Frontend: Chart Component

```tsx
// deeptrader-dashhboard/src/components/quant/LatencyChart.tsx
import { useMemo } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, Tooltip, 
  ResponsiveContainer, ReferenceLine, Legend 
} from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { useLatencyHistory } from '@/lib/api/quant-hooks';

interface LatencyChartProps {
  operation: string;
  title?: string;
  thresholds?: { warning: number; critical: number };
  hours?: number;
}

export function LatencyChart({ 
  operation, 
  title,
  thresholds = { warning: 5, critical: 10 },
  hours = 1,
}: LatencyChartProps) {
  const { data, isLoading } = useLatencyHistory(operation, hours);
  
  const chartData = useMemo(() => {
    if (!data?.history) return [];
    return data.history.map((point: any) => ({
      time: new Date(point.timestamp * 1000).toLocaleTimeString(),
      p50: point.metrics[operation]?.p50 ?? null,
      p95: point.metrics[operation]?.p95 ?? null,
      p99: point.metrics[operation]?.p99 ?? null,
    }));
  }, [data, operation]);
  
  if (isLoading) {
    return <Card><CardContent className="h-48 flex items-center justify-center">Loading...</CardContent></Card>;
  }
  
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">
          {title || `Latency: ${operation}`}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData}>
            <XAxis 
              dataKey="time" 
              tick={{ fontSize: 10 }} 
              interval="preserveStartEnd"
            />
            <YAxis 
              tick={{ fontSize: 10 }}
              domain={[0, 'auto']}
              label={{ value: 'ms', angle: -90, position: 'insideLeft', fontSize: 10 }}
            />
            <Tooltip />
            <Legend />
            <Line 
              type="monotone" 
              dataKey="p50" 
              stroke="#22c55e" 
              dot={false}
              name="p50"
            />
            <Line 
              type="monotone" 
              dataKey="p95" 
              stroke="#f59e0b" 
              dot={false}
              name="p95"
            />
            <Line 
              type="monotone" 
              dataKey="p99" 
              stroke="#ef4444" 
              dot={false}
              strokeWidth={2}
              name="p99"
            />
            {thresholds && (
              <>
                <ReferenceLine 
                  y={thresholds.warning} 
                  stroke="#f59e0b" 
                  strokeDasharray="3 3"
                  label={{ value: 'Warning', fontSize: 10 }}
                />
                <ReferenceLine 
                  y={thresholds.critical} 
                  stroke="#ef4444" 
                  strokeDasharray="3 3"
                  label={{ value: 'Critical', fontSize: 10 }}
                />
              </>
            )}
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```

---

### 2B. Guard Activity Panel (2-3h)

#### Extend Kill Switch Panel

```tsx
// deeptrader-dashhboard/src/components/quant/SafetyEventsPanel.tsx
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useKillSwitchHistory } from '@/lib/api/quant-hooks';

// New hook for guard events (reuse telemetry data)
function useGuardEvents(limit = 20) {
  return useQuery({
    queryKey: ['guard-events', limit],
    queryFn: async () => {
      const res = await fetch(`/api/telemetry/guardrails?limit=${limit}`);
      return res.json();
    },
    refetchInterval: 5_000,
  });
}

export function SafetyEventsPanel() {
  const { data: killSwitchHistory } = useKillSwitchHistory(5);
  const { data: guardEvents } = useGuardEvents(10);
  
  // Merge and sort events
  const allEvents = useMemo(() => {
    const events = [];
    
    // Kill switch events
    (killSwitchHistory?.history || []).forEach((e: any) => ({
      type: 'kill_switch',
      time: e.timestamp,
      icon: '🛑',
      title: `Kill Switch ${e.is_active ? 'Triggered' : 'Reset'}`,
      detail: e.message,
    }));
    
    // Guard events
    (guardEvents?.events || []).forEach((e: any) => ({
      type: 'guard',
      time: e.timestamp,
      icon: e.reason === 'take_profit_hit' ? '🎯' : 
            e.reason === 'trailing_stop_hit' ? '📉' :
            e.reason === 'stop_loss_hit' ? '🛑' : '⏰',
      title: `${e.symbol} - ${e.reason.replace(/_/g, ' ')}`,
      detail: `${e.side} position closed`,
    }));
    
    return events.sort((a, b) => b.time - a.time).slice(0, 15);
  }, [killSwitchHistory, guardEvents]);
  
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          🛡️ Safety Events
          <Badge variant="outline" className="text-xs">
            {allEvents.length} recent
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {allEvents.length === 0 ? (
            <p className="text-muted-foreground text-sm">No recent events</p>
          ) : (
            allEvents.map((event, i) => (
              <div 
                key={i}
                className="flex items-start gap-2 text-sm border-b last:border-0 pb-2"
              >
                <span className="text-lg">{event.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{event.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {event.detail} • {new Date(event.time * 1000).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

---

## Implementation Schedule

### Day 1 (8h)
| Task | Time | Deliverable |
|------|------|-------------|
| Guard alerting implementation | 2h | `_send_guard_alert()` |
| Wire alerts to PositionGuardWorker | 1h | Constructor change |
| Guard alerting tests | 1h | 3 unit tests |
| Correlation guard class | 1.5h | `CorrelationGuard` |
| Wire to RiskStage | 1h | Pipeline integration |
| Correlation guard tests | 1.5h | 5 unit tests |

### Day 2 (6-8h)
| Task | Time | Deliverable |
|------|------|-------------|
| Latency history storage | 1.5h | `LatencyTracker._history` |
| Latency history API | 1h | `/api/quant/latency/history` |
| Latency chart hook | 30min | `useLatencyHistory()` |
| Latency chart component | 2h | `<LatencyChart />` |
| Safety events panel | 2h | `<SafetyEventsPanel />` |
| Integration & testing | 1h | Manual verification |

---

## Success Criteria

### Guard Alerting
- [ ] Trailing stop sends Slack alert with P&L
- [ ] Stop loss sends alert
- [ ] Take profit sends alert  
- [ ] Max age sends alert
- [ ] Alert failure doesn't crash worker

### Correlation Guard
- [ ] BTC blocked when ETH long exists
- [ ] BTC short allowed when ETH long (hedge)
- [ ] Unknown pairs allowed
- [ ] Threshold configurable
- [ ] Disabled mode works

### Latency Graphs
- [ ] History stored (6 hours)
- [ ] API returns data
- [ ] Chart renders p50/p95/p99
- [ ] Warning/critical lines show
- [ ] Auto-refreshes

### Safety Events Panel
- [ ] Shows kill switch events
- [ ] Shows guard events
- [ ] Sorted by time
- [ ] Icons per event type
- [ ] Auto-refreshes

---

## Future TODOs (Deferred)

### Near-term (Next Sprint)
- [ ] Dynamic correlation calculation (rolling 30-day)
- [ ] Correlation matrix admin UI
- [ ] Latency alerting (auto-alert on p99 > threshold)

### Medium-term
- [ ] Order book recording (when needed for debug)
- [ ] Decision replay mode
- [ ] Backtest integration with Pure Core

### Long-term
- [ ] Multi-venue correlation
- [ ] ML-based correlation prediction
- [ ] Cross-bot portfolio coordination

---

## Files to Create/Modify

### New Files
- `quantgambit/core/risk/correlation_guard.py`
- `quantgambit/tests/unit/test_correlation_guard.py`
- `quantgambit/tests/unit/test_guard_alerting.py`
- `deeptrader-dashhboard/src/components/quant/LatencyChart.tsx`
- `deeptrader-dashhboard/src/components/quant/SafetyEventsPanel.tsx`

### Modified Files
- `quantgambit/execution/position_guard_worker.py` - Add alerts
- `quantgambit/core/latency.py` - Add history
- `quantgambit/api/quant_endpoints.py` - Add history endpoint
- `quantgambit/signals/pipeline.py` - Wire correlation guard
- `quantgambit/runtime/app.py` - Wire components
- `deeptrader-dashhboard/src/lib/api/quant-hooks.ts` - Add hooks
- `deeptrader-dashhboard/src/pages/dashboard/overview.tsx` - Add components
