#!/bin/bash
set -e
cd "$(dirname "$0")/.."

source .env.spot
# LLM keys are in main .env
export COPILOT_LLM_API_KEY=$(grep COPILOT_LLM_API_KEY .env | cut -d= -f2)
export COPILOT_LLM_BASE_URL=$(grep COPILOT_LLM_BASE_URL .env | cut -d= -f2)
export COPILOT_LLM_MODEL=$(grep COPILOT_LLM_MODEL .env | cut -d= -f2)

echo "=== Launching Sentiment Signal ==="
pm2 start venv/bin/python \
  --name "sentiment-signal" \
  --cwd "$(pwd)/quantgambit-python" \
  -- -m quantgambit.ai.sentiment_signal

echo "✅ Sentiment signal running (5-min poll)"
echo "   Monitor: pm2 logs sentiment-signal"
