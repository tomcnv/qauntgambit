#!/usr/bin/env bash
# Launch the spot trading bot through the canonical runtime launcher
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "=== Launching Spot Bot ==="
for required_key in TENANT_ID BOT_ID ACTIVE_EXCHANGE TRADING_MODE; do
  if [ -z "${!required_key:-}" ]; then
    echo "Error: ${required_key} must be set"
    exit 1
  fi
done

export MARKET_TYPE="spot"
export ENV_FILE="${ENV_FILE:-.env.spot}"
export RUNTIME_DEV_OVERRIDES="${RUNTIME_DEV_OVERRIDES:-false}"

echo "Forwarding to canonical runtime launcher..."
exec "$PROJECT_ROOT/scripts/launch-runtime.sh" --refresh-runtime
