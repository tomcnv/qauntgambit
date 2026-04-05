#!/bin/bash

# Cleanup script to kill all duplicate Python workers
# This ensures a clean state before starting workers

echo "🧹 Cleaning up duplicate Python workers..."
echo ""

# Define worker names
WORKERS=("data_worker" "feature_worker" "strategy_worker" "risk_worker" "execution_worker")

for worker in "${WORKERS[@]}"; do
    # Find all PIDs for this worker
    PIDS=$(ps aux | grep "${worker}.py" | grep -v grep | awk '{print $2}')
    
    if [ -z "$PIDS" ]; then
        echo "✓ ${worker}: No processes found"
    else
        COUNT=$(echo "$PIDS" | wc -l | xargs)
        echo "🔴 ${worker}: Found ${COUNT} instance(s)"
        
        # Kill each PID
        for pid in $PIDS; do
            echo "   Killing PID: $pid"
            kill -9 $pid 2>/dev/null
        done
        
        echo "✅ ${worker}: Cleaned up"
    fi
done

echo ""
echo "🎯 Cleanup complete!"
echo ""
echo "⚠️  NOTE: Always-on workers (data_worker, feature_worker) were killed."
echo "   They will auto-restart when control_manager restarts."
echo ""
echo "To restart always-on workers immediately:"
echo "  1. Restart control_manager: npm run stop && npm start"
echo "  2. Or wait - they'll start on next system boot"

