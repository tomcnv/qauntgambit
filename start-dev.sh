#!/bin/bash

# ═══════════════════════════════════════════════════════════════════════════
# QuantGambit Development Stack Startup Script
# ═══════════════════════════════════════════════════════════════════════════
#
# Starts all services needed for local development:
#   - Docker: PostgreSQL (TimescaleDB), Redis, pgAdmin
#   - PM2 managed services:
#     - Node.js backend API (port 3001)
#     - Dashboard frontend (port 5173)
#     - QuantGambit API (port 3002)
#     - Market Data Service (Bybit)
#     - Control Manager
#     - Backtest Worker
#   - Landing page (port 3000)
#   - Nginx reverse proxy [optional]
#
# Usage:
#   ./start-dev.sh              # Start core services via PM2
#   ./start-dev.sh --all        # Start everything including landing
#   ./start-dev.sh --no-nginx   # Skip nginx (use direct ports)
#   ./start-dev.sh --help       # Show help
#
# ═══════════════════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
START_LANDING=true
START_BOT=false
START_NGINX=true
VERBOSE=false
USE_PM2=true

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --all)
            START_LANDING=true
            START_BOT=true
            shift
            ;;
        --landing)
            START_LANDING=true
            shift
            ;;
        --no-landing)
            START_LANDING=false
            shift
            ;;
        --bot)
            START_BOT=true
            shift
            ;;
        --no-nginx)
            START_NGINX=false
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --all        Start all services (landing, bot, etc.)"
            echo "  --landing    Start landing page (default)"
            echo "  --no-landing Skip landing page"
            echo "  --bot        Start Python bot API"
            echo "  --no-nginx   Skip nginx reverse proxy"
            echo "  --verbose    Show detailed output"
            echo "  --help       Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() { echo -e "${BLUE}ℹ${NC}  $1"; }
log_success() { echo -e "${GREEN}✓${NC}  $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
log_error() { echo -e "${RED}✗${NC}  $1"; }
log_header() { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}$1${NC}"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# Check if a port is in use
check_port() {
    lsof -i:$1 >/dev/null 2>&1
}

# Kill process on port
kill_port() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        kill -9 $pid 2>/dev/null || true
        sleep 1
    fi
}

# Wait for service to be ready
wait_for_port() {
    local port=$1
    local name=$2
    local max_attempts=${3:-30}
    local attempt=0
    
    while ! check_port $port; do
        attempt=$((attempt + 1))
        if [ $attempt -ge $max_attempts ]; then
            log_error "$name failed to start on port $port"
            return 1
        fi
        sleep 1
    done
    return 0
}

# ═══════════════════════════════════════════════════════════════════════════
# STARTUP SEQUENCE
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          QuantGambit Development Stack Startup                    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Docker Services (PostgreSQL + Redis)
# ─────────────────────────────────────────────────────────────────────────────
log_header "🐳 Starting Docker Services"

# Function to start Colima with automatic recovery
start_colima() {
    local max_retries=2
    local retry=0
    
    while [ $retry -lt $max_retries ]; do
        log_info "Starting Colima (attempt $((retry + 1))/$max_retries)..."
        
        # Try to start Colima
        if colima start --cpu 4 --memory 8 2>&1; then
            export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
            sleep 3
            if docker info >/dev/null 2>&1; then
                log_success "Colima started successfully"
                return 0
            fi
        fi
        
        # Check if it's a disk-in-use error
        if [ -f "$HOME/.colima/_lima/colima/ha.stderr.log" ]; then
            if grep -q "disk.*in use" "$HOME/.colima/_lima/colima/ha.stderr.log" 2>/dev/null; then
                log_warn "Colima disk stuck in bad state. Recovering..."
                colima delete --force 2>/dev/null || true
                sleep 2
                retry=$((retry + 1))
                continue
            fi
        fi
        
        # Generic failure - try delete and recreate
        log_warn "Colima failed to start. Attempting recovery..."
        colima delete --force 2>/dev/null || true
        sleep 2
        retry=$((retry + 1))
    done
    
    return 1
}

# Check if Docker is running (supports Colima, Docker Desktop, etc.)
# For Colima, set DOCKER_HOST to the correct socket
if command -v colima &> /dev/null && colima status >/dev/null 2>&1; then
    export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
    log_info "Using Colima Docker socket"
fi

if ! docker info >/dev/null 2>&1; then
    log_warn "Docker not responding. Attempting to start Colima..."
    if command -v colima &> /dev/null; then
        if start_colima; then
            log_success "Docker is now available via Colima"
        else
            log_error "Failed to start Colima after multiple attempts."
            log_error "Try manually: colima delete --force && colima start --cpu 4 --memory 8"
            exit 1
        fi
    else
        log_error "Docker is not running. Please start your Docker runtime (Colima, Docker Desktop, etc.)"
        exit 1
    fi
fi

# Start docker services from primary compose (docker/docker-compose.yml) only
MAIN_DOCKER_DIR="$SCRIPT_DIR/docker"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

DEEPTRADER_DB_USER="${DEEPTRADER_DB_USER:-${DB_USER:-deeptrader_user}}"
DEEPTRADER_DB_NAME="${DEEPTRADER_DB_NAME:-${DB_NAME:-deeptrader}}"

cd "$MAIN_DOCKER_DIR"
if docker compose -f docker-compose.yml ps --services >/dev/null 2>&1; then
    if ! docker ps --format '{{.Names}}' | grep -q '^deeptrader-redis$'; then
        docker compose up -d redis
    fi
else
    log_error "Main docker compose file unavailable in $MAIN_DOCKER_DIR"
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q '^deeptrader-postgres$'; then
    docker compose up -d postgres >/dev/null 2>&1
fi

if ! docker ps --format '{{.Names}}' | grep -q '^deeptrader-postgres$'; then
    log_error "Primary PostgreSQL container (deeptrader-postgres) not found after startup"
    exit 1
fi

PG_CONTAINER="deeptrader-postgres"
PG_USER="$DEEPTRADER_DB_USER"
PG_DB="$DEEPTRADER_DB_NAME"

# Wait for services to be healthy
log_info "Checking PostgreSQL..."
attempt=0
max_attempts=30
while ! docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ $attempt -ge $max_attempts ]; then
        log_error "PostgreSQL failed to start"
        exit 1
    fi
    sleep 1
done
log_success "PostgreSQL ready on port 5432"

log_info "Checking Redis..."
attempt=0
while ! docker exec deeptrader-redis redis-cli ping >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ $attempt -ge $max_attempts ]; then
        log_error "Redis failed to start"
        exit 1
    fi
    sleep 1
done
log_success "Redis ready on port 6379"

log_info "Reconciling local databases via authoritative runners..."
if ! python3 "$SCRIPT_DIR/scripts/reconcile_local_databases.py"; then
    log_error "Local database reconciliation failed"
    exit 1
fi
log_success "Local database reconciliation completed"

# Check if pgAdmin is running
if docker ps --format '{{.Names}}' | grep -q "pgadmin\|deeptrader-pgadmin"; then
    log_success "pgAdmin available at http://localhost:8080"
    log_info "  Email: admin@deeptrader.com | Password: admin123"
fi

cd "$SCRIPT_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: PM2 Services (Backend, Dashboard, QuantGambit API, MDS, etc.)
# ─────────────────────────────────────────────────────────────────────────────
log_header "🚀 Starting PM2 Services"

# Check if PM2 is installed
if ! command -v pm2 &> /dev/null; then
    log_error "PM2 not installed. Install with: npm install -g pm2"
    exit 1
fi

cd "$SCRIPT_DIR"

# Stop any existing PM2 processes to avoid conflicts
log_info "Stopping existing PM2 processes..."
pm2 delete all 2>/dev/null || true

# Start all PM2 apps from ecosystem config
log_info "Starting PM2 ecosystem..."
pm2 start ecosystem.config.js

# Wait a moment for services to initialize
sleep 3

# Show PM2 status
log_success "PM2 services started:"
pm2 list

echo ""
log_info "PM2 manages: dashboard, deeptrader-backend, quantgambit-api, market-data-service-bybit, control-manager, backtest-worker"

# Optionally start landing page
if $START_LANDING; then
    log_info "Starting landing page via PM2..."
    pm2 start ecosystem.config.js --only landing
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Nginx Reverse Proxy (optional)
# ─────────────────────────────────────────────────────────────────────────────
if $START_NGINX; then
    log_header "🔀 Starting Nginx Reverse Proxy"
    
    # Check if nginx is installed
    if ! command -v nginx &> /dev/null; then
        log_warn "Nginx not installed. Install with: brew install nginx"
        log_info "Skipping nginx - use direct ports instead"
    else
        # Stop existing nginx gracefully
        sudo nginx -s stop 2>/dev/null || true
        sleep 1
        
        # Kill any remaining nginx processes
        sudo pkill nginx 2>/dev/null || true
        sleep 1
        
        # Check hosts file
        if ! grep -q "quantgambit.local" /etc/hosts; then
            log_warn "Hosts entries not found. Add to /etc/hosts:"
            echo "    127.0.0.1 quantgambit.local dashboard.quantgambit.local api.quantgambit.local bot.quantgambit.local"
        fi
        
        # Test nginx config first
        if nginx -t -c "$SCRIPT_DIR/nginx.conf" 2>/dev/null; then
            # Start nginx with our config file
            if sudo nginx -c "$SCRIPT_DIR/nginx.conf" 2>/dev/null; then
                log_success "Nginx proxy running on port 80"
                log_info "  Dashboard: http://dashboard.quantgambit.local"
                log_info "  API:       http://api.quantgambit.local"
                log_info "  Bot API:   http://bot.quantgambit.local"
            else
                log_warn "Nginx failed to start. Check: sudo nginx -t -c $SCRIPT_DIR/nginx.conf"
                log_info "Use direct ports instead (localhost:5173, localhost:3001, etc.)"
            fi
        else
            log_error "Nginx config test failed. Check: nginx -t -c $SCRIPT_DIR/nginx.conf"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    🚀 Stack Started Successfully                  ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo "  🐘 PostgreSQL (TimescaleDB): localhost:5432"
echo "  📦 Redis:                    localhost:6379"
echo "  🔧 pgAdmin:                  http://localhost:8080"
if $USE_PM2; then
    echo ""
    echo -e "${BLUE}PM2 Managed Services:${NC}"
    echo "  🔌 Backend API:              http://localhost:3001"
    echo "  📊 Dashboard:                http://localhost:5173"
    echo "  🐍 QuantGambit API:          http://localhost:3002"
    echo "  📈 Market Data (Bybit):      Running"
    echo "  🎮 Control Manager:          Running"
    echo "  ⚙️  Backtest Worker:          Running"
    if $START_LANDING; then
        echo "  📄 Landing Page:             http://localhost:3000"
    fi
else
    echo "  🔌 Backend API:              http://localhost:3001"
    echo "  📊 Dashboard:                http://localhost:5173"
    if $START_LANDING; then
        echo "  📄 Landing Page:             http://localhost:3000"
    fi
    if $START_BOT && check_port 8080; then
        echo "  🤖 Bot API:                  http://localhost:8080"
    fi
fi
echo ""

if $START_NGINX && command -v nginx &> /dev/null; then
    echo -e "${BLUE}Via Nginx Proxy:${NC}"
    echo "  📊 Dashboard:    http://dashboard.quantgambit.local"
    echo "  🔌 API:          http://api.quantgambit.local"
    if $START_LANDING; then
        echo "  📄 Landing:      http://quantgambit.local"
    fi
    echo ""
fi

echo -e "${BLUE}Logs:${NC}"
if $USE_PM2; then
    echo "  PM2 logs:  pm2 logs"
    echo "  PM2 monit: pm2 monit"
else
    echo "  Backend:   tail -f /tmp/deeptrader-backend.log"
    echo "  Dashboard: tail -f /tmp/deeptrader-dashboard.log"
    if $START_LANDING; then
        echo "  Landing:   tail -f /tmp/deeptrader-landing.log"
    fi
    if $START_BOT; then
        echo "  Bot:       tail -f /tmp/quantgambit-bot.log"
    fi
fi
echo ""
echo -e "${YELLOW}To stop all services:${NC} ./stop-dev.sh"
if $USE_PM2; then
    echo -e "${YELLOW}PM2 status:${NC} pm2 list"
fi
echo ""
