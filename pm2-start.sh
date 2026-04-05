#!/bin/bash
# Start DeepTrader with PM2

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                                                                  ║"
echo "║         🚀 STARTING DEEPTRADER WITH PM2 🚀                       ║"
echo "║                                                                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Load environment variables from QuantGambit .env
if [ -f "quantgambit-python/.env" ]; then
    echo "📝 Loading environment variables..."
    export $(grep -v '^#' quantgambit-python/.env | xargs)
fi

# Stop any existing PM2 processes
echo "🛑 Stopping any existing processes..."
pm2 delete all 2>/dev/null || true
sleep 2

# Clean up old PID files
rm -f /tmp/deeptrader_control_manager.pid

# Start all services with PM2
echo "🚀 Starting services with PM2..."
pm2 start ecosystem.config.js

echo ""
echo "✅ Services started with PM2!"
echo ""
echo "📊 Process Status:"
pm2 list

echo ""
echo "📋 Useful Commands:"
echo "   pm2 list              - Show all processes"
echo "   pm2 logs              - View all logs"
echo "   pm2 logs backend      - View backend logs"
echo "   pm2 logs python       - View Python logs"
echo "   pm2 restart all       - Restart all services"
echo "   pm2 stop all          - Stop all services"
echo "   pm2 monit             - Monitor in real-time"
echo ""
