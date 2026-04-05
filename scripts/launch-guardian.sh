#!/bin/bash
# Launch standalone Position Guardian for an exchange account
#
# Usage: 
#   TENANT_ID=xxx EXCHANGE_ACCOUNT_ID=xxx EXCHANGE=binance ./launch-guardian.sh
#
# Required env vars:
#   TENANT_ID - Tenant/user ID
#   EXCHANGE_ACCOUNT_ID - Exchange account ID to monitor
#   EXCHANGE - Exchange name (binance, okx, bybit)
#   EXCHANGE_SECRET_ID - Secret ID for credentials
#
# Optional env vars:
#   IS_TESTNET - true/false
#   GUARDIAN_POLL_SEC - Poll interval (default 5)
#   GUARDIAN_MAX_AGE_SEC - Max position age before force close (0=disabled)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_DIR="$PROJECT_ROOT/quantgambit-python"

# Validate required vars
if [ -z "$TENANT_ID" ]; then
    echo "Error: TENANT_ID is required"
    exit 1
fi

if [ -z "$EXCHANGE_ACCOUNT_ID" ]; then
    echo "Error: EXCHANGE_ACCOUNT_ID is required"
    exit 1
fi

if [ -z "$EXCHANGE" ]; then
    echo "Error: EXCHANGE is required"
    exit 1
fi

if [ -z "$EXCHANGE_SECRET_ID" ]; then
    echo "Error: EXCHANGE_SECRET_ID is required"
    exit 1
fi

# Compute default values for Redis connection
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_URL_VALUE="${REDIS_URL:-redis://${REDIS_HOST}:${REDIS_PORT}}"

# Process name
GUARDIAN_NAME="guardian-${TENANT_ID:0:8}-${EXCHANGE_ACCOUNT_ID:0:8}"

cd "$PYTHON_DIR"

# Check if already running
if pm2 describe "$GUARDIAN_NAME" > /dev/null 2>&1; then
    echo "Guardian $GUARDIAN_NAME already running, restarting..."
    pm2 restart "$GUARDIAN_NAME" --update-env
else
    echo "Starting guardian $GUARDIAN_NAME..."
    pm2 start "$PYTHON_DIR/venv/bin/python" \
        --name "$GUARDIAN_NAME" \
        --interpreter none \
        -- -m quantgambit.guardian.standalone_guardian \
        --env "
            TENANT_ID=${TENANT_ID}
            EXCHANGE_ACCOUNT_ID=${EXCHANGE_ACCOUNT_ID}
            EXCHANGE=${EXCHANGE}
            EXCHANGE_SECRET_ID=${EXCHANGE_SECRET_ID}
            IS_TESTNET=${IS_TESTNET:-false}
            REDIS_URL=${REDIS_URL_VALUE}
            GUARDIAN_POLL_SEC=${GUARDIAN_POLL_SEC:-5}
            GUARDIAN_MAX_AGE_SEC=${GUARDIAN_MAX_AGE_SEC:-0}
        "
fi

echo "Guardian started: $GUARDIAN_NAME"
pm2 save


