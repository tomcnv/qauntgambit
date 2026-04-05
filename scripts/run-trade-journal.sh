#!/bin/bash
set -e
cd "$(dirname "$0")/.."

set -a
source .env.spot
set +a
export COPILOT_LLM_API_KEY=$(grep COPILOT_LLM_API_KEY .env | cut -d= -f2)
export COPILOT_LLM_BASE_URL=$(grep COPILOT_LLM_BASE_URL .env | cut -d= -f2)
export COPILOT_LLM_MODEL=$(grep COPILOT_LLM_MODEL .env | cut -d= -f2)
export TIMESCALE_PASSWORD=$(grep BOT_DB_PASSWORD .env | cut -d= -f2)
export TIMESCALE_URL=$(grep BOT_TIMESCALE_URL .env | cut -d= -f2)

echo "=== Running Trade Journal ==="
cd quantgambit-python
venv/bin/python -m quantgambit.ai.trade_journal
