#!/bin/bash
#
# DeepTrader Fresh Start Script (NON-INTERACTIVE)
# ================================================
# Clears ALL trading data: paper trades, live trades, decisions, replays, etc.
# USE WITH CAUTION!
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Load .env file if it exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$BACKEND_DIR/.env" ]; then
  echo "Loading environment from $BACKEND_DIR/.env"
  export $(grep -v '^#' "$BACKEND_DIR/.env" | xargs)
fi

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🧹 DeepTrader Fresh Start Script (NON-INTERACTIVE)       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: Check for running bots
echo -e "${YELLOW}📍 Step 1: Checking for running processes...${NC}"

if command -v pm2 &> /dev/null; then
  RUNNING_BOTS=$(pm2 jlist 2>/dev/null | grep -o '"name":"[^"]*bot[^"]*"' | wc -l || echo "0")
  if [ "$RUNNING_BOTS" -gt 0 ]; then
    echo -e "${YELLOW}   ⚠️  Found running bot processes. Stopping...${NC}"
    pm2 stop all 2>/dev/null || true
    echo -e "${GREEN}   ✅ Processes stopped${NC}"
  else
    echo -e "${GREEN}   ✅ No bot processes running${NC}"
  fi
else
  echo -e "${YELLOW}   ⚠️  pm2 not found, skipping process check${NC}"
fi

# Step 2: Clear Redis
echo ""
echo -e "${YELLOW}📍 Step 2: Clearing Redis bot data...${NC}"

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

if [ -n "$REDIS_PASSWORD" ]; then
  REDIS_AUTH="-a $REDIS_PASSWORD"
else
  REDIS_AUTH=""
fi

# Count keys before deletion
KEY_COUNT=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" $REDIS_AUTH KEYS "bot:*" 2>/dev/null | wc -l || echo "0")
echo "   Found $KEY_COUNT Redis keys matching 'bot:*'"

if [ "$KEY_COUNT" -gt 0 ]; then
  # Delete all bot:* keys
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" $REDIS_AUTH KEYS "bot:*" | xargs -r redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" $REDIS_AUTH DEL > /dev/null 2>&1
  echo -e "${GREEN}   ✅ Deleted $KEY_COUNT Redis keys${NC}"
else
  echo -e "${GREEN}   ✅ No Redis keys to delete${NC}"
fi

# Step 3: Clear Database Tables
echo ""
echo -e "${YELLOW}📍 Step 3: Clearing ALL trading data from database...${NC}"

# Use same env vars as backend config/database.js
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-deeptrader}"
DB_USER="${DB_USER:-deeptrader_user}"
DB_PASSWORD="${DB_PASSWORD:-deeptrader_pass}"

export PGPASSWORD="$DB_PASSWORD"

echo "   Connecting to $DB_HOST:$DB_PORT/$DB_NAME as $DB_USER"

# Execute SQL cleanup
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -q << 'EOSQL'
BEGIN;

-- =====================================================
-- PAPER TRADING DATA
-- =====================================================
TRUNCATE TABLE paper_trades CASCADE;
TRUNCATE TABLE paper_position_history CASCADE;
TRUNCATE TABLE paper_position_alerts CASCADE;
TRUNCATE TABLE paper_positions CASCADE;
TRUNCATE TABLE paper_orders CASCADE;
TRUNCATE TABLE paper_balances CASCADE;
TRUNCATE TABLE paper_performance_snapshots CASCADE;

-- =====================================================
-- LIVE/FAST SCALPER TRADING DATA
-- =====================================================
TRUNCATE TABLE fast_scalper_trades CASCADE;
TRUNCATE TABLE fast_scalper_positions CASCADE;
TRUNCATE TABLE fast_scalper_metrics CASCADE;

-- =====================================================
-- LEGACY TRADING TABLES (likely unused but clear anyway)
-- =====================================================
TRUNCATE TABLE trades CASCADE;
TRUNCATE TABLE positions CASCADE;
TRUNCATE TABLE orders CASCADE;
TRUNCATE TABLE trading_activity CASCADE;
TRUNCATE TABLE trading_decisions CASCADE;
TRUNCATE TABLE trade_costs CASCADE;

-- =====================================================
-- DECISION/REPLAY DATA (large tables)
-- =====================================================
TRUNCATE TABLE decision_traces CASCADE;
TRUNCATE TABLE replay_snapshots CASCADE;
TRUNCATE TABLE replay_sessions CASCADE;
TRUNCATE TABLE replay_annotations CASCADE;

-- =====================================================
-- ANALYTICS & METRICS
-- =====================================================
TRUNCATE TABLE equity_curves CASCADE;
TRUNCATE TABLE portfolio_equity CASCADE;
TRUNCATE TABLE portfolio_summary CASCADE;
TRUNCATE TABLE var_calculations CASCADE;
TRUNCATE TABLE component_var CASCADE;
TRUNCATE TABLE scenario_results CASCADE;
TRUNCATE TABLE risk_metrics_aggregation CASCADE;
TRUNCATE TABLE cost_aggregation CASCADE;
TRUNCATE TABLE strategy_signals CASCADE;
TRUNCATE TABLE strategy_correlation CASCADE;

-- =====================================================
-- BACKTEST DATA
-- =====================================================
TRUNCATE TABLE backtest_trades CASCADE;
TRUNCATE TABLE backtest_equity_curve CASCADE;
TRUNCATE TABLE backtest_runs CASCADE;

-- =====================================================
-- ALERTS & INCIDENTS
-- =====================================================
TRUNCATE TABLE alerts CASCADE;
TRUNCATE TABLE incident_events CASCADE;
TRUNCATE TABLE incident_affected_objects CASCADE;
TRUNCATE TABLE incidents CASCADE;
TRUNCATE TABLE data_quality_alerts CASCADE;

-- =====================================================
-- RESET BOT STATE
-- =====================================================
-- Clear active bot references on exchange accounts
UPDATE exchange_accounts 
SET active_bot_id = NULL 
WHERE active_bot_id IS NOT NULL;

-- Clear bot commands queue
TRUNCATE TABLE bot_commands CASCADE;

COMMIT;

-- Report what was cleared
SELECT 'Cleanup complete!' as status;
EOSQL

echo -e "${GREEN}   ✅ All trading data cleared${NC}"

# Step 4: Summary
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}✅ Fresh start complete!${NC}"
echo ""
echo "   Cleared data:"
echo "   ├── Paper trades, positions, orders, balances"
echo "   ├── Live/fast_scalper trades, positions, metrics"
echo "   ├── Legacy trades, positions, orders"
echo "   ├── Decision traces (5.6M+ rows)"
echo "   ├── Replay snapshots (1.5M+ rows)"
echo "   ├── Analytics, VaR, equity curves"
echo "   ├── Backtest data"
echo "   ├── Alerts and incidents"
echo "   └── Redis bot:* keys"
echo ""
echo "   Preserved data:"
echo "   ├── Users and authentication"
echo "   ├── Exchange accounts (credentials)"
echo "   ├── Bot instances and configurations"
echo "   ├── Profiles and strategies"
echo "   ├── Market data (candles, order books)"
echo "   └── Audit logs"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "   1. Restart the backend:  pm2 restart backend"
echo "   2. Refresh the dashboard"
echo "   3. Start your bot on the desired exchange account"
echo "   4. Paper balances will be auto-initialized on first trade"
echo ""

