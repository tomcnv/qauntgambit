#!/bin/bash
# Stop DeepTrader PM2 processes

echo "🛑 Stopping DeepTrader services..."
pm2 stop all
echo "✅ All services stopped"
echo ""
echo "To completely remove from PM2:"
echo "  pm2 delete all"

