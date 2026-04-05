#!/bin/bash

# DeepTrader - Unified Stop Script
# Stops all services: Node.js backend + Python workers + Monitoring API

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                                                                  ║"
echo "║              🛑 STOPPING DEEPTRADER SERVICES 🛑                  ║"
echo "║                                                                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

# Stop Python workers
echo "🐍 Stopping Python workers..."
pkill -f "control_manager.py" && echo "   ✅ control_manager stopped" || echo "   ⚠️  control_manager not running"
pkill -f "data_worker.py" && echo "   ✅ data_worker stopped" || echo "   ⚠️  data_worker not running"
pkill -f "feature_worker.py" && echo "   ✅ feature_worker stopped" || echo "   ⚠️  feature_worker not running"
pkill -f "strategy_worker.py" && echo "   ✅ strategy_worker stopped" || echo "   ⚠️  strategy_worker not running"
pkill -f "risk_worker.py" && echo "   ✅ risk_worker stopped" || echo "   ⚠️  risk_worker not running"
pkill -f "execution_worker.py" && echo "   ✅ execution_worker stopped" || echo "   ⚠️  execution_worker not running"
pkill -f "monitoring_api.py" && echo "   ✅ monitoring_api stopped" || echo "   ⚠️  monitoring_api not running"

# Stop Node.js processes
echo ""
echo "🟢 Stopping Node.js data collectors..."
pkill -f "newsAnalyzer.js" && echo "   ✅ newsAnalyzer stopped" || echo "   ⚠️  newsAnalyzer not running"
pkill -f "socialMonitor.js" && echo "   ✅ socialMonitor stopped" || echo "   ⚠️  socialMonitor not running"
pkill -f "onChainMonitor.js" && echo "   ✅ onChainMonitor stopped" || echo "   ⚠️  onChainMonitor not running"
pkill -f "technicalAnalyzer.js" && echo "   ✅ technicalAnalyzer stopped" || echo "   ⚠️  technicalAnalyzer not running"

# Stop Node.js backend (be careful - this will stop the main server)
echo ""
read -p "🟢 Stop Node.js backend server? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    pkill -f "deeptrader-backend/server.js" && echo "   ✅ Node.js backend stopped" || echo "   ⚠️  Node.js backend not running"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All services stopped"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

