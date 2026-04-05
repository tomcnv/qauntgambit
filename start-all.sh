#!/bin/bash
# Legacy startup script disabled.
echo "This script is deprecated. Use the QuantGambit startup flow instead."
exit 1
echo ""

# Step 3: Start Python Control Manager
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 STEP 3: Starting Python Control Manager"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$PYTHON_DIR"

# Load environment variables from .env file
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "🐍 Starting Python control manager..."
PYTHONPATH="$PYTHON_DIR" DB_USER=deeptrader_user DB_PASSWORD=deeptrader_pass nohup venv/bin/python -u services/control_manager.py > /tmp/control_manager.log 2>&1 &
CONTROL_PID=$!
echo "✅ Python control manager started (PID: $CONTROL_PID)"
echo "   Log: /tmp/control_manager.log"
sleep 2
echo ""

# Step 4: Start Python Monitoring API
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 STEP 4: Starting Python Monitoring API"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if check_port 8888; then
    echo "⚠️  Port 8888 is already in use - killing existing process..."
    kill_port 8888
fi

echo "🐍 Starting Python monitoring API on port 8888..."
PYTHONPATH="$PYTHON_DIR" DB_USER=deeptrader_user DB_PASSWORD=deeptrader_pass nohup venv/bin/python -u services/monitoring_api.py > /tmp/monitoring_api.log 2>&1 &
MONITORING_PID=$!
echo "✅ Python monitoring API started (PID: $MONITORING_PID)"
echo "   Log: /tmp/monitoring_api.log"
sleep 3

# Verify monitoring API is running
if check_port 8888; then
    echo "✅ Python monitoring API is responding on port 8888"
else
    echo "❌ Python monitoring API failed to start"
    cat /tmp/monitoring_api.log | tail -20
    exit 1
fi
echo ""

# Step 5: Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 STARTUP COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Services Running:"
echo "   🟢 Node.js Backend:        http://localhost:3001 (PID: $BACKEND_PID)"
echo "   🐍 Python Control Manager: (PID: $CONTROL_PID)"
echo "   🐍 Python Monitoring API:  http://localhost:8888 (PID: $MONITORING_PID)"
echo ""
echo "📋 Logs:"
echo "   Node.js:    /tmp/deeptrader-backend.log"
echo "   Control:    /tmp/control_manager.log"
echo "   Monitoring: /tmp/monitoring_api.log"
echo ""
echo "🎯 Next Steps:"
echo "   1. Start the frontend: cd deeptrader-dashhboard && npm run dev"
echo "   2. Start Python workers via the UI or API:"
echo "      curl -X POST http://localhost:3001/api/bot/start"
echo ""
echo "🛑 To stop all services:"
echo "   ./stop-all.sh"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
