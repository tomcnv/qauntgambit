#!/bin/bash
# E2E Stack Verification Script
# Verifies all components of the DeepTrader platform work together

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }

PROJECT_ROOT="/Users/thomas/projects/deeptrader"
cd "$PROJECT_ROOT"

echo "=============================================="
echo "DeepTrader E2E Stack Verification"
echo "=============================================="
echo ""

# ═══════════════════════════════════════════════════════════════
# 1. CHECK INFRASTRUCTURE (Docker)
# ═══════════════════════════════════════════════════════════════
log_info "Checking infrastructure..."

# Check Redis
if docker ps | grep -q "deeptrader-redis"; then
    REDIS_PING=$(redis-cli ping 2>/dev/null || echo "FAIL")
    if [ "$REDIS_PING" = "PONG" ]; then
        log_success "Redis: Running and responding"
    else
        log_error "Redis: Container running but not responding"
    fi
else
    log_error "Redis: Not running. Start with 'docker-compose up -d'"
fi

# Check PostgreSQL (platform DB)
PLATFORM_DB_HOST="${PLATFORM_DB_HOST:-localhost}"
PLATFORM_DB_PORT="${PLATFORM_DB_PORT:-5432}"
PLATFORM_DB_NAME="${PLATFORM_DB_NAME:-platform_db}"
PLATFORM_DB_USER="${PLATFORM_DB_USER:-platform}"

if psql -h "$PLATFORM_DB_HOST" -p "$PLATFORM_DB_PORT" -U "$PLATFORM_DB_USER" -d "$PLATFORM_DB_NAME" -c "SELECT 1" &>/dev/null; then
    log_success "PostgreSQL (Platform): Connected"
else
    log_warning "PostgreSQL (Platform): Not accessible at $PLATFORM_DB_HOST:$PLATFORM_DB_PORT"
fi

# Check TimescaleDB (bot DB)
BOT_DB_HOST="${BOT_DB_HOST:-localhost}"
BOT_DB_PORT="${BOT_DB_PORT:-${PLATFORM_DB_PORT:-5432}}"
BOT_DB_NAME="${BOT_DB_NAME:-quantgambit_bot}"
BOT_DB_USER="${BOT_DB_USER:-quantgambit}"

if psql -h "$BOT_DB_HOST" -p "$BOT_DB_PORT" -U "$BOT_DB_USER" -d "$BOT_DB_NAME" -c "SELECT 1" &>/dev/null; then
    log_success "TimescaleDB (Bot): Connected"
else
    log_warning "TimescaleDB (Bot): Not accessible at $BOT_DB_HOST:$BOT_DB_PORT"
fi

echo ""

# ═══════════════════════════════════════════════════════════════
# 2. CHECK PM2 SERVICES
# ═══════════════════════════════════════════════════════════════
log_info "Checking PM2 services..."

PM2_LIST=$(pm2 jlist 2>/dev/null || echo "[]")

check_pm2_service() {
    local NAME=$1
    local STATUS=$(echo "$PM2_LIST" | jq -r ".[] | select(.name == \"$NAME\") | .pm2_env.status" 2>/dev/null || echo "not_found")
    
    if [ "$STATUS" = "online" ]; then
        log_success "$NAME: Running"
        return 0
    elif [ "$STATUS" = "not_found" ] || [ "$STATUS" = "" ]; then
        log_warning "$NAME: Not started"
        return 1
    else
        log_error "$NAME: Status=$STATUS"
        return 1
    fi
}

check_pm2_service "deeptrader-backend"
check_pm2_service "dashboard"
check_pm2_service "control-manager"
check_pm2_service "market-data-service-bybit"

echo ""

# ═══════════════════════════════════════════════════════════════
# 3. CHECK API ENDPOINTS
# ═══════════════════════════════════════════════════════════════
log_info "Checking API endpoints..."

# Backend API health
BACKEND_HEALTH=$(curl -s http://localhost:3001/api/health 2>/dev/null || echo "{}")
BACKEND_STATUS=$(echo "$BACKEND_HEALTH" | jq -r '.status' 2>/dev/null || echo "error")

if [ "$BACKEND_STATUS" = "ok" ]; then
    log_success "Backend API (:3001): Healthy"
else
    log_error "Backend API (:3001): $BACKEND_STATUS"
fi

# QuantGambit API health
QG_HEALTH=$(curl -s http://localhost:3002/health 2>/dev/null || echo "{}")
QG_STATUS=$(echo "$QG_HEALTH" | jq -r '.status' 2>/dev/null || echo "error")

if [ "$QG_STATUS" = "ok" ]; then
    log_success "QuantGambit API (:3002): Healthy"
else
    log_warning "QuantGambit API (:3002): $QG_STATUS (may not be running)"
fi

echo ""

# ═══════════════════════════════════════════════════════════════
# 4. CHECK REDIS STREAMS (Market Data)
# ═══════════════════════════════════════════════════════════════
log_info "Checking Redis streams (market data)..."

check_stream() {
    local STREAM=$1
    local LEN=$(redis-cli XLEN "$STREAM" 2>/dev/null || echo "0")
    
    if [ "$LEN" != "0" ] && [ -n "$LEN" ]; then
        log_success "$STREAM: $LEN messages"
        return 0
    else
        log_warning "$STREAM: Empty or not found"
        return 1
    fi
}

check_stream "events:orderbook_feed:bybit"
check_stream "events:trades:bybit"

echo ""

# ═══════════════════════════════════════════════════════════════
# 5. CHECK CONTROL PLANE
# ═══════════════════════════════════════════════════════════════
log_info "Checking control plane..."

# Check platform health key
PLATFORM_HEALTH=$(redis-cli GET "quantgambit:::health:latest" 2>/dev/null || echo "{}")
if [ -n "$PLATFORM_HEALTH" ] && [ "$PLATFORM_HEALTH" != "{}" ]; then
    CTRL_STATUS=$(echo "$PLATFORM_HEALTH" | jq -r '.status' 2>/dev/null || echo "unknown")
    log_success "Control Manager: Publishing health ($CTRL_STATUS)"
else
    log_warning "Control Manager: No health data (may not be running)"
fi

# Check control command stream exists
CMD_STREAM_LEN=$(redis-cli XLEN "commands:control" 2>/dev/null || echo "0")
log_info "Command stream length: $CMD_STREAM_LEN"

echo ""

# ═══════════════════════════════════════════════════════════════
# 6. CHECK DASHBOARD ACCESSIBILITY
# ═══════════════════════════════════════════════════════════════
log_info "Checking dashboard accessibility..."

DASHBOARD_RESP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null || echo "000")
if [ "$DASHBOARD_RESP" = "200" ]; then
    log_success "Dashboard (:5173): Accessible"
else
    log_warning "Dashboard (:5173): HTTP $DASHBOARD_RESP"
fi

echo ""

# ═══════════════════════════════════════════════════════════════
# 7. SUMMARY
# ═══════════════════════════════════════════════════════════════
echo "=============================================="
echo "Quick Start Commands"
echo "=============================================="
echo ""
echo "# Start all services:"
echo "  pm2 start ecosystem.config.js"
echo ""
echo "# Check service status:"
echo "  pm2 status"
echo ""
echo "# View logs:"
echo "  pm2 logs control-manager"
echo "  pm2 logs market-data-service-bybit"
echo "  pm2 logs deeptrader-backend"
echo ""
echo "# Dashboard URL:"
echo "  http://localhost:5173"
echo ""
echo "# Backend API:"
echo "  http://localhost:3001/api/health"
echo ""
