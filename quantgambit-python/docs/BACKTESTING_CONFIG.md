# Backtesting Configuration Reference

Complete reference for configuring the backtesting API and execution infrastructure.

## Overview

The backtesting system uses environment variables to configure:
- Job execution concurrency and timeouts
- Temporary file storage
- Redis data source settings
- Database connections

## Environment Variables

### Job Execution

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKTEST_MAX_CONCURRENT` | `2` | Maximum number of concurrent backtest jobs |
| `BACKTEST_TIMEOUT_HOURS` | `4.0` | Maximum execution time per backtest (hours) |
| `BACKTEST_TEMP_DIR` | `/tmp/backtests` | Directory for temporary snapshot files |

#### BACKTEST_MAX_CONCURRENT

Controls how many backtests can run simultaneously. Higher values allow more parallel execution but increase resource usage.

**Recommendations:**
- Development: `1-2`
- Production (small): `2-4`
- Production (large): `4-8` (requires adequate CPU/memory)

**Example:**
```bash
export BACKTEST_MAX_CONCURRENT=4
```

#### BACKTEST_TIMEOUT_HOURS

Maximum time a single backtest can run before being automatically cancelled. Prevents runaway jobs from consuming resources indefinitely.

**Recommendations:**
- Short backtests (1 week): `1.0`
- Medium backtests (1 month): `2.0-4.0`
- Long backtests (3+ months): `4.0-8.0`

**Example:**
```bash
export BACKTEST_TIMEOUT_HOURS=6.0
```

#### BACKTEST_TEMP_DIR

Directory where snapshot export files are temporarily stored during backtest execution. Files are cleaned up after completion.

**Requirements:**
- Must be writable by the API process
- Should have sufficient disk space (estimate: 100MB per month of 1-minute data)
- Consider using SSD for better performance

**Example:**
```bash
export BACKTEST_TEMP_DIR=/var/lib/quantgambit/backtests
```

### Redis Data Source

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKTEST_STREAM_KEY` | `events:feature_snapshots` | Redis stream containing historical snapshots |
| `BACKTEST_EXCHANGE` | `OKX` | Default exchange name for datasets |
| `BOT_REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `REDIS_URL` | `redis://localhost:6379` | Fallback Redis URL |

#### BACKTEST_STREAM_KEY

The Redis stream key where feature snapshots are stored. This is the primary data source for backtesting.

**Stream Format:**
```
events:feature_snapshots
├── Entry ID: 1704067200000-0
│   ├── symbol: BTC-USDT-SWAP
│   ├── timestamp: 1704067200.0
│   ├── market_context: {...}
│   ├── features: {...}
│   └── prediction: {...}
```

**Example:**
```bash
export BACKTEST_STREAM_KEY=events:feature_snapshots
```

#### BACKTEST_EXCHANGE

Default exchange name used when scanning datasets. This is used for display purposes in the dataset list.

**Example:**
```bash
export BACKTEST_EXCHANGE=OKX
```

### Redis Retention Requirements

For backtesting to work effectively, Redis must retain sufficient historical data.

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Retention Period | 7 days | 30+ days |
| Memory per Symbol | ~50MB/week | ~200MB/month |
| Stream Max Length | 100,000 | 500,000+ |

**Redis Configuration:**
```redis
# Set stream max length (per stream)
XTRIM events:feature_snapshots MAXLEN ~ 500000

# Or use memory-based eviction
CONFIG SET maxmemory-policy allkeys-lru
```

**Archival Strategy:**

For long-term backtesting (months of data), consider:
1. Periodic export to S3/disk using `snapshot_exporter.py`
2. Redis cluster with dedicated backtesting nodes
3. TimescaleDB for historical snapshot storage

### Database Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHBOARD_DB_HOST` | `localhost` | PostgreSQL host |
| `DASHBOARD_DB_PORT` | `5432` | PostgreSQL port |
| `DASHBOARD_DB_NAME` | `platform_db` | Database name |
| `DASHBOARD_DB_USER` | `platform` | Database user |
| `DASHBOARD_DB_PASSWORD` | `platform_pw` | Database password |

The backtesting API uses the platform database to store:
- Backtest run metadata (`backtest_runs`)
- Performance metrics (`backtest_metrics`)
- Equity curves (`backtest_equity_curve`)
- Trade logs (`backtest_trades`)
- Decision snapshots (`backtest_decision_snapshots`)
- WFO runs (`wfo_runs`)

**Connection Pool:**
```bash
# Optional: Configure pool size
export DASHBOARD_DB_POOL_MIN=2
export DASHBOARD_DB_POOL_MAX=10
```

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_MODE` | `none` | Authentication mode: `none`, `jwt` |
| `AUTH_JWT_SECRET` | - | JWT signing secret (required if AUTH_MODE=jwt) |
| `DEFAULT_TENANT_ID` | `default` | Default tenant for non-isolated mode |
| `DEFAULT_BOT_ID` | `default` | Default bot ID |

**Example (JWT enabled):**
```bash
export AUTH_MODE=jwt
export AUTH_JWT_SECRET=your-secret-key-here
```

## Complete Configuration Example

### Development Environment

```bash
# .env.development

# Job Execution
BACKTEST_MAX_CONCURRENT=2
BACKTEST_TIMEOUT_HOURS=2.0
BACKTEST_TEMP_DIR=/tmp/backtests

# Redis
BOT_REDIS_URL=redis://localhost:6379
BACKTEST_STREAM_KEY=events:feature_snapshots
BACKTEST_EXCHANGE=OKX

# Database
DASHBOARD_DB_HOST=localhost
DASHBOARD_DB_PORT=5432
DASHBOARD_DB_NAME=platform_db
DASHBOARD_DB_USER=platform
DASHBOARD_DB_PASSWORD=platform_pw

# Auth (disabled for dev)
AUTH_MODE=none
DEFAULT_TENANT_ID=dev-tenant
DEFAULT_BOT_ID=dev-bot
```

### Production Environment

```bash
# .env.production

# Job Execution
BACKTEST_MAX_CONCURRENT=4
BACKTEST_TIMEOUT_HOURS=8.0
BACKTEST_TEMP_DIR=/var/lib/quantgambit/backtests

# Redis
BOT_REDIS_URL=redis://redis-cluster:6379
BACKTEST_STREAM_KEY=events:feature_snapshots
BACKTEST_EXCHANGE=OKX

# Database
DASHBOARD_DB_HOST=postgres-primary
DASHBOARD_DB_PORT=5432
DASHBOARD_DB_NAME=platform_db
DASHBOARD_DB_USER=quantgambit_api
DASHBOARD_DB_PASSWORD=${DB_PASSWORD}

# Auth (JWT enabled)
AUTH_MODE=jwt
AUTH_JWT_SECRET=${JWT_SECRET}
```

## Database Schema Setup

Before using the backtesting API, ensure the database schema is created:

```bash
# Run the migration
cd quantgambit-python
alembic upgrade head

# Or manually apply the schema
psql -h localhost -U platform -d platform_db -f docs/sql/migrations/001_backtest_schema_enhancements.sql
```

## Monitoring

### Key Metrics to Monitor

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Active backtest count | Number of running jobs | > BACKTEST_MAX_CONCURRENT |
| Queue depth | Pending jobs waiting | > 10 |
| Average execution time | Time per backtest | > BACKTEST_TIMEOUT_HOURS * 0.8 |
| Success rate | Completed / Total | < 90% |
| Database query latency | P95 query time | > 500ms |

### Log Messages

Key log messages to monitor:

```
# Job lifecycle
INFO: Backtest job submitted: run_id=xxx
INFO: Backtest job started: run_id=xxx
INFO: Backtest job completed: run_id=xxx, duration=xxx
ERROR: Backtest job failed: run_id=xxx, error=xxx

# Resource warnings
WARNING: Backtest queue depth high: depth=xxx
WARNING: Backtest execution slow: run_id=xxx, elapsed=xxx
ERROR: Backtest timeout: run_id=xxx
```

## Troubleshooting

### Common Issues

**1. "No data available for date range"**
- Check Redis retention settings
- Verify `BACKTEST_STREAM_KEY` is correct
- Ensure data collection is running

**2. "Backtest timeout"**
- Increase `BACKTEST_TIMEOUT_HOURS`
- Reduce date range
- Check for resource contention

**3. "Database connection failed"**
- Verify database credentials
- Check network connectivity
- Ensure database is running

**4. "Redis connection failed"**
- Verify Redis URL
- Check Redis is running
- Ensure sufficient memory

### Debug Mode

Enable detailed logging:

```bash
export LOG_LEVEL=DEBUG
export BACKTEST_DEBUG=true
```

## Related Documentation

- [BACKTESTING_API_REFERENCE.md](BACKTESTING_API_REFERENCE.md) - API endpoint documentation
- [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) - General configuration reference
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
