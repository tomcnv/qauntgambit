#!/bin/bash
# Start backend server for integration tests

cd "$(dirname "$0")/.."

echo "🚀 Starting backend server for integration tests..."

# Check if already running
if lsof -ti:3001 > /dev/null 2>&1; then
  echo "✅ Backend already running on port 3001"
  exit 0
fi

# Start backend in background
cd deeptrader-backend
node server.js > /tmp/deeptrader-backend-test.log 2>&1 &
BACKEND_PID=$!

echo "⏳ Waiting for backend to start..."
sleep 3

# Check if started
if ps -p $BACKEND_PID > /dev/null 2>&1; then
  echo "✅ Backend started (PID: $BACKEND_PID)"
  echo "   Log: /tmp/deeptrader-backend-test.log"
  echo "   To stop: kill $BACKEND_PID"
  echo $BACKEND_PID > /tmp/deeptrader-backend-test.pid
else
  echo "❌ Backend failed to start"
  echo "Last 20 lines of log:"
  tail -20 /tmp/deeptrader-backend-test.log
  exit 1
fi





