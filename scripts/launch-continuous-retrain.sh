#!/usr/bin/env bash
set -euo pipefail
# Continuous model improvement: export from live feature stream → retrain → promote if better → sleep → repeat
# Run: TENANT_ID=... BOT_ID=... bash scripts/launch-continuous-retrain.sh

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/quantgambit-python/venv311/bin/python}"

: "${TENANT_ID:?TENANT_ID required}"
: "${BOT_ID:?BOT_ID required}"

RETRAIN_NAME="continuous-retrain-${TENANT_ID}-${BOT_ID}"
CONFIG_FILE="/tmp/${RETRAIN_NAME}.config.js"
CYCLE_SLEEP_SEC="${CYCLE_SLEEP_SEC:-14400}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
STREAM="${STREAM:-events:features:${TENANT_ID}:${BOT_ID}}"
LIMIT="${LIMIT:-100000}"
HOURS_LOOKBACK="${HOURS_LOOKBACK:-24}"
HORIZON_PROFILE="${HORIZON_PROFILE:-scalp_1m}"
LABEL_SOURCE="${LABEL_SOURCE:-future_return}"
REGISTRY="${PROJECT_ROOT}/quantgambit-python/models/registry"

# Write the inner loop as a standalone script
LOOP_SCRIPT="/tmp/${RETRAIN_NAME}-loop.sh"
cat > "$LOOP_SCRIPT" << EOF
#!/usr/bin/env bash
set -euo pipefail
PYTHON="${PYTHON_BIN}"
REGISTRY="${REGISTRY}"
REDIS_URL="${REDIS_URL}"
TENANT_ID="${TENANT_ID}"
BOT_ID="${BOT_ID}"
STREAM="${STREAM}"
LIMIT=${LIMIT}
HOURS=${HOURS_LOOKBACK}
HORIZON_PROFILE="${HORIZON_PROFILE}"
LABEL_SOURCE="${LABEL_SOURCE}"
CYCLE=${CYCLE_SLEEP_SEC}
CWD="${PROJECT_ROOT}/quantgambit-python"

cd "\$CWD"
export PYTHONPATH="\$CWD:\${PYTHONPATH:-}"
while true; do
  echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ) retrain_cycle_start"
  "\$PYTHON" scripts/retrain_prediction_baseline.py \
    --redis-url "\$REDIS_URL" \
    --tenant-id "\$TENANT_ID" \
    --bot-id "\$BOT_ID" \
    --stream "\$STREAM" \
    --limit "\$LIMIT" \
    --hours "\$HOURS" \
    --horizon-profile "\$HORIZON_PROFILE" \
    --label-source "\$LABEL_SOURCE" \
    --registry "\$REGISTRY" \
    --keep-dataset \
    --drift-check \
    --allow-imbalance || echo "retrain_cycle_failed"
  echo "retrain_cycle_complete sleep=\${CYCLE}s"
  sleep "\$CYCLE"
done
EOF
chmod +x "$LOOP_SCRIPT"

cat > "$CONFIG_FILE" << EOF
module.exports = {
  apps: [{
    name: '${RETRAIN_NAME}',
    script: '${LOOP_SCRIPT}',
    interpreter: '/bin/bash',
    exec_mode: 'fork',
    autorestart: true,
    max_restarts: 50,
    restart_delay: 10000
  }]
}
EOF

pm2 delete "$RETRAIN_NAME" >/dev/null 2>&1 || true
pm2 start "$CONFIG_FILE"
pm2 save

echo "Started ${RETRAIN_NAME}"
echo "  Cycle: every ${CYCLE_SLEEP_SEC}s ($(( CYCLE_SLEEP_SEC / 3600 ))h)"
echo "  Stream: ${STREAM}"
echo "  Lookback: ${HOURS_LOOKBACK}h"
echo "  Horizon profile: ${HORIZON_PROFILE}"
echo "  Label source: ${LABEL_SOURCE}"
echo "Logs: pm2 logs ${RETRAIN_NAME}"
