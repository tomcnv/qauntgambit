# DeepTrader Monitoring Guide

## Overview

The DeepTrader hybrid architecture includes comprehensive monitoring for both Node.js and Python components. This guide covers all monitoring endpoints, health checks, metrics, and alerting.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React)                          │
│                   localhost:3000                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Node.js Backend (Express)                       │
│                   localhost:3001                             │
│                                                              │
│  Endpoints:                                                  │
│  • /api/monitoring/dashboard  - Unified dashboard           │
│  • /api/monitoring/health     - Quick health check          │
│  • /api/monitoring/metrics    - Detailed metrics            │
│  • /api/monitoring/alerts     - Active alerts               │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
┌──────────────────┐           ┌──────────────────┐
│  Node.js Data    │           │  Python Trading  │
│  Collectors      │           │  Engine          │
│                  │           │  localhost:8888  │
│  • newsAnalyzer  │           │                  │
│  • socialMonitor │           │  Endpoints:      │
│  • onChainMon... │           │  • /dashboard    │
│  • technicalAn...│           │  • /health       │
└──────────────────┘           │  • /metrics      │
                               │  • /workers      │
                               │  • /alerts       │
                               └──────────────────┘
```

---

## User-Scoped Redis Keys

Fast Scalper now publishes every runtime artifact under a user-specific prefix to keep tenant data isolated. Redis keys follow the pattern:

```
bot:{TRADING_USER_ID}:{metric_suffix}
```

Examples:

- `bot:1e6e2fa1-1645-445a-a13f-76da74af9929:metrics`
- `bot:1e6e2fa1-1645-445a-a13f-76da74af9929:positions`
- `bot:1e6e2fa1-1645-445a-a13f-76da74af9929:recent_trades`

All monitoring endpoints automatically scope reads with the authenticated user's ID, so operators only see their own exposure, risk, and telemetry snapshots.

---

## Monitoring Endpoints

### 1. Node.js Backend Monitoring

**Base URL:** `http://localhost:3001/api/monitoring`

#### GET /dashboard
Comprehensive system dashboard with all metrics.

**Response:**
```json
{
  "timestamp": "2025-11-19T12:31:26.679Z",
  "uptime": 17.35,
  "nodejs": {
    "server": {
      "running": true,
      "uptime": 17.35,
      "memory": { "rss": 230309888, "heapTotal": 140693504 },
      "pid": 74086
    },
    "dataCollectors": {
      "total": 4,
      "running": 4,
      "healthy": true,
      "details": [
        { "name": "newsAnalyzer", "running": true, "pid": 74185 },
        { "name": "socialMonitor", "running": true, "pid": 74195 },
        { "name": "onChainMonitor", "running": true, "pid": 74202 },
        { "name": "technicalAnalyzer", "running": true, "pid": 74212 }
      ]
    }
  },
  "python": {
    "workers": {
      "total": 5,
      "running": 3,
      "healthy": true,
      "details": [
        { "name": "data_worker", "status": "running" },
        { "name": "feature_worker", "status": "running" },
        { "name": "strategy_worker", "status": "running" }
      ]
    }
  },
  "redis": {
    "connected": true,
    "pubsub": { "channels": [...], "active": true },
    "streams": { "channels": [...], "active": true }
  },
  "health": "healthy"
}
```

#### GET /health
Quick health check for all services.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-19T12:31:26.915Z",
  "checks": {
    "nodejs": {
      "healthy": true,
      "details": "4/4 data collectors running"
    },
    "python": {
      "healthy": true,
      "details": "3 Python processes running"
    },
    "redis": {
      "healthy": true,
      "details": "Redis connected"
    }
  }
}
```

**Status Codes:**
- `200` - All systems healthy
- `503` - One or more systems degraded

#### GET /metrics
Detailed metrics for performance monitoring.

**Response:**
```json
{
  "timestamp": "2025-11-19T12:31:27.000Z",
  "nodejs": {
    "memory": { "rss": 230309888, "heapTotal": 140693504 },
    "cpu": { "user": 1234567, "system": 234567 },
    "uptime": 17.35,
    "dataCollectors": [
      { "name": "newsAnalyzer", "running": true, "uptime": 15.2, "restarts": 0 }
    ]
  },
  "python": {
    "workers": [
      { "name": "data_worker", "pid": 12345, "cpu": 2.5, "memory": 1.2 }
    ]
  },
  "redis": {
    "connected": true,
    "messageCount": "N/A"
  }
}
```

#### GET /alerts
Active alerts and warnings.

**Response:**
```json
{
  "timestamp": "2025-11-19T12:31:27.100Z",
  "alerts": [
    {
      "severity": "critical",
      "component": "python_workers",
      "name": "data_worker",
      "message": "Worker data_worker is not running",
      "timestamp": "2025-11-19T12:31:27.100Z"
    }
  ],
  "warnings": [
    {
      "severity": "warning",
      "component": "nodejs_collector",
      "name": "newsAnalyzer",
      "message": "Data collector newsAnalyzer last seen 90s ago",
      "timestamp": "2025-11-19T12:31:27.100Z"
    }
  ],
  "total": 2
}
```

---

### 2. Python Engine Monitoring

**Base URL:** `http://localhost:8888`

#### GET /
Root endpoint with available endpoints.

**Response:**
```json
{
  "service": "DeepTrader Python Engine",
  "version": "1.0.0",
  "status": "running",
  "endpoints": {
    "health": "/health",
    "metrics": "/metrics",
    "workers": "/workers",
    "dashboard": "/dashboard",
    "alerts": "/alerts"
  }
}
```

#### GET /dashboard
Python-specific dashboard.

**Response:**
```json
{
  "timestamp": "2025-11-19T12:31:27.200Z",
  "uptime_seconds": 1234.5,
  "health": "healthy",
  "system": {
    "cpu_percent": 12.5,
    "memory_percent": 45.2,
    "memory_used_mb": 1024.5,
    "memory_available_mb": 2048.3
  },
  "workers": {
    "total": 3,
    "active": 3,
    "details": {
      "data_worker": { "status": "active", "messages_processed": 1234 },
      "feature_worker": { "status": "active", "messages_processed": 567 },
      "strategy_worker": { "status": "active", "messages_processed": 89 }
    }
  },
  "message_queue": {
    "connected": true
  }
}
```

#### GET /health
Python health check.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-19T12:31:27.300Z",
  "version": "1.0.0",
  "uptime_seconds": 1234.5,
  "memory_usage_mb": 1024.5,
  "cpu_usage_percent": 12.5
}
```

#### GET /workers
Detailed worker status.

**Response:**
```json
{
  "timestamp": "2025-11-19T12:31:27.400Z",
  "workers": {
    "data_worker": {
      "status": "active",
      "messages_processed": 1234,
      "errors": 0,
      "last_seen": "2025-11-19T12:31:27.000Z"
    },
    "feature_worker": {
      "status": "active",
      "messages_processed": 567,
      "errors": 0,
      "last_seen": "2025-11-19T12:31:26.500Z"
    }
  },
  "last_updates": {
    "data_worker": "2025-11-19T12:31:27.000Z",
    "feature_worker": "2025-11-19T12:31:26.500Z"
  }
}
```

#### GET /alerts
Python-specific alerts.

**Response:**
```json
{
  "timestamp": "2025-11-19T12:31:27.500Z",
  "alerts": [
    {
      "severity": "critical",
      "component": "system",
      "name": "memory",
      "message": "Memory usage at 92%",
      "timestamp": "2025-11-19T12:31:27.500Z"
    }
  ],
  "warnings": [
    {
      "severity": "warning",
      "component": "python_worker",
      "name": "strategy_worker",
      "message": "Worker strategy_worker last seen 75s ago",
      "timestamp": "2025-11-19T12:31:27.500Z"
    }
  ],
  "total": 2
}
```

---

## Health Status Definitions

### Overall Health States

| State | Description | Action Required |
|-------|-------------|-----------------|
| `healthy` | All systems operational | None |
| `degraded` | Some services down but core functionality works | Monitor closely |
| `warning` | High resource usage or minor issues | Investigate soon |
| `critical` | Core services down | Immediate action required |
| `unhealthy` | System cannot function | Emergency response |

### Component Health

**Node.js Data Collectors:**
- ✅ Healthy: All 4 collectors running
- ⚠️ Degraded: 1-3 collectors running
- ❌ Critical: 0 collectors running

**Python Workers:**
- ✅ Healthy: At least data_worker and feature_worker running
- ⚠️ Degraded: Only 1 worker running
- ❌ Critical: No workers running

**Redis:**
- ✅ Healthy: Connected
- ❌ Critical: Disconnected

---

## Alert Severity Levels

### Critical
- Python workers not running
- Redis disconnected
- CPU usage > 90%
- Memory usage > 90%
- Worker not seen for > 5 minutes

### Error
- Data collector crashed
- Database connection lost
- Exchange API errors

### Warning
- Worker not seen for > 1 minute
- High resource usage (70-90%)
- Slow message processing

---

## Monitoring Best Practices

### 1. Regular Health Checks

Set up automated health checks every 30 seconds:

```bash
# Check Node.js health
curl http://localhost:3001/api/monitoring/health

# Check Python health
curl http://localhost:8888/health
```

### 2. Dashboard Monitoring

Access the unified dashboard for a complete system view:

```bash
curl http://localhost:3001/api/monitoring/dashboard | jq
```

### 3. Alert Monitoring

Check for active alerts every minute:

```bash
# Node.js alerts
curl http://localhost:3001/api/monitoring/alerts | jq '.alerts'

# Python alerts
curl http://localhost:8888/alerts | jq '.alerts'
```

### 4. Metrics Collection

Collect detailed metrics for trending:

```bash
# Node.js metrics
curl http://localhost:3001/api/monitoring/metrics > metrics_$(date +%s).json

# Python metrics
curl http://localhost:8888/metrics >> python_metrics_$(date +%s).json
```

---

## Troubleshooting

### Node.js Data Collectors Not Running

**Symptoms:**
- Dashboard shows `"running": 0` for data collectors
- Health check shows `"nodejs": { "healthy": false }`

**Solution:**
```bash
# Check process manager status
curl http://localhost:3001/api/monitoring/dashboard | jq '.nodejs.dataCollectors'

# Restart data collectors via API
curl -X POST http://localhost:3001/api/bot/start
```

### Python Workers Not Running

**Symptoms:**
- Dashboard shows low worker count
- Health check shows `"python": { "healthy": false }`

**Solution:**
```bash
# Check Python processes
ps aux | grep python | grep workers

# Start workers via control manager
curl -X POST http://localhost:3001/api/python/start-workers

# Or manually
cd deeptrader-python
python control_workers.py start all
```

### Redis Connection Issues

**Symptoms:**
- Health check shows `"redis": { "healthy": false }`
- Workers logging connection errors

**Solution:**
```bash
# Check Redis status
redis-cli ping

# Restart Redis (Docker)
docker restart deeptrader-redis

# Check connection from Node.js
curl http://localhost:3001/api/monitoring/health | jq '.checks.redis'
```

### High Resource Usage

**Symptoms:**
- CPU > 90% or Memory > 90%
- Alerts showing resource warnings

**Solution:**
```bash
# Check which processes are using resources
curl http://localhost:3001/api/monitoring/metrics | jq '.python.workers'

# Identify heavy workers
ps aux | grep python | sort -k3 -r | head -5

# Consider scaling or optimization
```

---

## Integration with Frontend

The monitoring data can be displayed in the React frontend:

```javascript
// Fetch monitoring dashboard
const response = await fetch('http://localhost:3001/api/monitoring/dashboard');
const dashboard = await response.json();

// Display health status
console.log(`System Health: ${dashboard.health}`);
console.log(`Node.js Collectors: ${dashboard.nodejs.dataCollectors.running}/${dashboard.nodejs.dataCollectors.total}`);
console.log(`Python Workers: ${dashboard.python.workers.running}/${dashboard.python.workers.total}`);

// Check for alerts
const alertsResponse = await fetch('http://localhost:3001/api/monitoring/alerts');
const alerts = await alertsResponse.json();

if (alerts.total > 0) {
  console.warn(`⚠️ ${alerts.alerts.length} critical alerts, ${alerts.warnings.length} warnings`);
}
```

---

## Monitoring Checklist

### Daily
- [ ] Check overall system health
- [ ] Review active alerts
- [ ] Verify all workers are running
- [ ] Check resource usage trends

### Weekly
- [ ] Review error logs
- [ ] Analyze performance metrics
- [ ] Check for memory leaks
- [ ] Verify data flow integrity

### Monthly
- [ ] Review alert history
- [ ] Optimize resource usage
- [ ] Update monitoring thresholds
- [ ] Plan capacity upgrades

---

## Multi-User Operations

DeepTrader supports multiple concurrent users, each with isolated trading data, credentials, and bot instances. This section covers key aspects of multi-user deployment.

### Data Isolation Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User A                                    │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │  Dashboard      │  │  Fast Scalper   │                   │
│  │  (React)        │──│  Bot Instance   │                   │
│  └────────┬────────┘  └────────┬────────┘                   │
│           │                    │                            │
│           ▼                    ▼                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Redis: bot:user-A-id:*                              │    │
│  │  • bot:user-A-id:metrics                            │    │
│  │  • bot:user-A-id:positions                          │    │
│  │  • bot:user-A-id:recent_trades                      │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    User B (Completely Isolated)              │
│  ┌─────────────────┐  ┌─────────────────┐                   │
│  │  Dashboard      │  │  Fast Scalper   │                   │
│  │  (React)        │──│  Bot Instance   │                   │
│  └────────┬────────┘  └────────┬────────┘                   │
│           │                    │                            │
│           ▼                    ▼                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Redis: bot:user-B-id:*                              │    │
│  │  • bot:user-B-id:metrics                            │    │
│  │  • bot:user-B-id:positions                          │    │
│  │  • bot:user-B-id:recent_trades                      │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Environment Variables for Bot Instances

When launching a bot for a specific user, the `botPoolService` injects these environment variables:

| Variable | Description |
|----------|-------------|
| `TRADING_USER_ID` | UUID of the authenticated user |
| `TRADING_MODE` | `paper` or `live` |
| `ACTIVE_EXCHANGE` | `okx`, `binance`, or `bybit` |
| `CREDENTIAL_SECRET_ID` | Path to user's exchange credentials |
| `TRADING_CAPITAL` | User's configured trading capital |
| `EXCHANGE_BALANCE` | Actual balance on exchange |

### WebSocket User Scoping

WebSocket connections are associated with authenticated users:

```javascript
// Connection URL includes auth token
const wsUrl = `ws://localhost:3001?token=${authToken}`;

// Backend extracts userId and stores with connection
wsClients.set(ws, { userId: decoded.userId });

// Broadcasts can target specific users
broadcastToUser(userId, 'bot:status', data);
```

### Verifying User Data Isolation

Use the `verify-redis-keys.js` script to check a user's Redis keys:

```bash
# Check keys for a specific user
node scripts/verify-redis-keys.js 1e6e2fa1-1645-445a-a13f-76da74af9929

# Check default namespace (when no user ID is provided)
node scripts/verify-redis-keys.js
```

### React Query Cache Invalidation

The dashboard clears the React Query cache on login/logout to prevent data leakage:

```typescript
// auth-store.ts
login: async (payload) => {
  // ... authentication
  queryClientRef?.clear(); // Clear cache on login
}

logout: async () => {
  // ... logout
  queryClientRef?.clear(); // Clear cache on logout
}
```

### Common Multi-User Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| User sees another user's data | Missing user ID in Redis key | Ensure `TRADING_USER_ID` is set when launching bot |
| Stale data after login | Query cache not cleared | Verify `setQueryClientRef` is called in App.tsx |
| WebSocket receives all events | Anonymous WebSocket connection | Include `?token=` in WebSocket URL |
| Bot starts with wrong config | Credential not scoped to user | Check `active_credential_id` belongs to authenticated user |

---

## Next Steps

1. **Set up automated monitoring** - Use a cron job or monitoring service to check health endpoints
2. **Configure alerting** - Set up email/Slack notifications for critical alerts
3. **Create dashboards** - Build Grafana dashboards for visualization
4. **Log aggregation** - Set up centralized logging (e.g., ELK stack)
5. **Performance tuning** - Use metrics to identify and fix bottlenecks

---

## Support

For issues or questions about monitoring:
1. Check this guide first
2. Review logs in `/tmp/*_worker*.log`
3. Check the troubleshooting section
4. Consult the main README.md

---

**Last Updated:** November 19, 2025  
**Version:** 1.0.0  
**Status:** ✅ Complete

