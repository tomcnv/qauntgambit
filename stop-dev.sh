#!/bin/bash

# ═══════════════════════════════════════════════════════════════════════════
# QuantGambit Development Stack Shutdown Script
# ═══════════════════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ${NC}  $1"; }
log_success() { echo -e "${GREEN}✓${NC}  $1"; }

echo ""
echo -e "${YELLOW}╔═══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║          QuantGambit Development Stack Shutdown                   ║${NC}"
echo -e "${YELLOW}╚═══════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Stop PM2 processes first
if command -v pm2 &> /dev/null; then
    log_info "Stopping PM2 processes..."
    pm2 delete all 2>/dev/null || true
    log_success "PM2 processes stopped"
fi

# Stop Nginx
log_info "Stopping Nginx..."
sudo nginx -s stop 2>/dev/null || true
sudo pkill nginx 2>/dev/null || true
log_success "Nginx stopped"

# Stop any legacy nohup Node.js processes
log_info "Stopping legacy Node.js services..."

# Backend
if [ -f /tmp/deeptrader-backend.pid ]; then
    kill $(cat /tmp/deeptrader-backend.pid) 2>/dev/null || true
    rm /tmp/deeptrader-backend.pid
fi
lsof -ti:3001 | xargs kill -9 2>/dev/null || true
log_success "Backend API stopped"

# Dashboard
if [ -f /tmp/deeptrader-dashboard.pid ]; then
    kill $(cat /tmp/deeptrader-dashboard.pid) 2>/dev/null || true
    rm /tmp/deeptrader-dashboard.pid
fi
lsof -ti:5173 | xargs kill -9 2>/dev/null || true
log_success "Dashboard stopped"

# Landing
if [ -f /tmp/deeptrader-landing.pid ]; then
    kill $(cat /tmp/deeptrader-landing.pid) 2>/dev/null || true
    rm /tmp/deeptrader-landing.pid
fi
lsof -ti:3000 | xargs kill -9 2>/dev/null || true
log_success "Landing page stopped"

# QuantGambit API (port 3002)
lsof -ti:3002 | xargs kill -9 2>/dev/null || true
log_success "QuantGambit API stopped"

# Python Bot
log_info "Stopping Python services..."
if [ -f /tmp/quantgambit-bot.pid ]; then
    kill $(cat /tmp/quantgambit-bot.pid) 2>/dev/null || true
    rm /tmp/quantgambit-bot.pid
fi
# Don't kill 8080 as it might be pgAdmin
log_success "Bot API stopped"

# Stop Docker services (optional - ask user)
echo ""
read -p "Stop Docker services (PostgreSQL, Redis, pgAdmin)? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Stopping Docker services..."
    
    # Set Colima docker socket if using Colima
    if command -v colima &> /dev/null && colima status >/dev/null 2>&1; then
        export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
    fi
    
    cd "$SCRIPT_DIR/docker"
    docker compose down 2>/dev/null || true
    log_success "Docker services stopped"
else
    log_info "Docker services left running"
fi

echo ""
echo -e "${GREEN}✓ All services stopped${NC}"
echo ""
