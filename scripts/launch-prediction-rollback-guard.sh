#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/quantgambit-python/venv/bin/python}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"

if [[ -z "${TENANT_ID:-}" || -z "${BOT_ID:-}" ]]; then
  echo "Error: TENANT_ID and BOT_ID must be set"
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: PYTHON_BIN not executable: $PYTHON_BIN"
  exit 1
fi

GUARD_NAME="prediction-rollback-guard-${TENANT_ID}-${BOT_ID}"
CONFIG_FILE="/tmp/${GUARD_NAME}.config.js"

LOOKBACK_HOURS="${LOOKBACK_HOURS:-4}"
REPORT_COUNT="${REPORT_COUNT:-12000}"
HORIZON_SEC="${HORIZON_SEC:-60}"
FLAT_THRESHOLD_BPS="${FLAT_THRESHOLD_BPS:-3.0}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-120}"

SCORE_MIN_SAMPLES="${SCORE_MIN_SAMPLES:-120}"
SCORE_MIN_ML_SCORE="${SCORE_MIN_ML_SCORE:-52.0}"
SCORE_MIN_PROMOTION_SCORE_V2="${SCORE_MIN_PROMOTION_SCORE_V2:-0.0}"
SCORE_MIN_EXACT_ACCURACY="${SCORE_MIN_EXACT_ACCURACY:-0.50}"
SCORE_MAX_ECE="${SCORE_MAX_ECE:-0.20}"
SCORE_MIN_AVG_REALIZED_BPS="${SCORE_MIN_AVG_REALIZED_BPS:--1.0}"
SCORE_SNAPSHOT_TTL_SEC="${SCORE_SNAPSHOT_TTL_SEC:-300}"
SCORE_PROVIDER="${SCORE_PROVIDER:-shadow}"

ROLLBACK_MAX_CONSECUTIVE="${ROLLBACK_MAX_CONSECUTIVE:-3}"
ROLLBACK_COOLDOWN_SEC="${ROLLBACK_COOLDOWN_SEC:-1800}"
ROLLBACK_MIN_SYMBOL_SAMPLES="${ROLLBACK_MIN_SYMBOL_SAMPLES:-120}"
ROLLBACK_MAX_SNAPSHOT_AGE_SEC="${ROLLBACK_MAX_SNAPSHOT_AGE_SEC:-1200}"
ROLLBACK_STATE_TTL_SEC="${ROLLBACK_STATE_TTL_SEC:-604800}"
ROLLBACK_SYMBOLS="${ROLLBACK_SYMBOLS:-}"
RUNTIME_PROCESS_NAME="${RUNTIME_PROCESS_NAME:-runtime-${TENANT_ID}-${BOT_ID}}"

echo "Launching prediction rollback guard:"
echo "  PM2 process: $GUARD_NAME"
echo "  Runtime process: $RUNTIME_PROCESS_NAME"
echo "  Tenant/Bot: $TENANT_ID / $BOT_ID"
echo "  Poll interval: ${POLL_INTERVAL_SEC}s"
echo "  Score provider: ${SCORE_PROVIDER}"

cat > "$CONFIG_FILE" << EOF
module.exports = {
  apps: [{
    name: '${GUARD_NAME}',
    cwd: '${PROJECT_ROOT}',
    script: '/bin/bash',
    args: ['-lc', 'set -euo pipefail; while true; do \
"${PYTHON_BIN}" "quantgambit-python/scripts/prediction_shadow_outcome_report.py" \
  --tenant-id "${TENANT_ID}" \
  --bot-id "${BOT_ID}" \
  --redis-url "${REDIS_URL}" \
  --hours "${LOOKBACK_HOURS}" \
  --count "${REPORT_COUNT}" \
  --horizon-sec "${HORIZON_SEC}" \
  --flat-threshold-bps "${FLAT_THRESHOLD_BPS}" \
  --score-provider "${SCORE_PROVIDER}" \
  --score-min-samples "${SCORE_MIN_SAMPLES}" \
  --score-min-ml-score "${SCORE_MIN_ML_SCORE}" \
  --score-min-promotion-score-v2 "${SCORE_MIN_PROMOTION_SCORE_V2}" \
  --score-min-exact-accuracy "${SCORE_MIN_EXACT_ACCURACY}" \
  --score-max-ece "${SCORE_MAX_ECE}" \
  --score-min-avg-realized-bps "${SCORE_MIN_AVG_REALIZED_BPS}" \
  --write-score-snapshot \
  --score-snapshot-ttl-sec "${SCORE_SNAPSHOT_TTL_SEC}" > "/tmp/${GUARD_NAME}.score.json" 2>&1 || true; \
"${PYTHON_BIN}" "quantgambit-python/scripts/auto_rollback_prediction_model.py" \
  --tenant-id "${TENANT_ID}" \
  --bot-id "${BOT_ID}" \
  --registry "quantgambit-python/models/registry" \
  --redis-url "${REDIS_URL}" \
  --max-consecutive-breaches "${ROLLBACK_MAX_CONSECUTIVE}" \
  --cooldown-sec "${ROLLBACK_COOLDOWN_SEC}" \
  --min-symbol-samples "${ROLLBACK_MIN_SYMBOL_SAMPLES}" \
  --max-snapshot-age-sec "${ROLLBACK_MAX_SNAPSHOT_AGE_SEC}" \
  --state-ttl-sec "${ROLLBACK_STATE_TTL_SEC}" \
  --min-ml-score "${SCORE_MIN_ML_SCORE}" \
  --min-exact-accuracy "${SCORE_MIN_EXACT_ACCURACY}" \
  --max-ece-top1 "${SCORE_MAX_ECE}" \
  --min-avg-realized-bps "${SCORE_MIN_AVG_REALIZED_BPS}" \
  --symbols "${ROLLBACK_SYMBOLS}" \
  --restart-runtime \
  --runtime-process-name "${RUNTIME_PROCESS_NAME}" || true; \
sleep "${POLL_INTERVAL_SEC}"; done'],
    interpreter: 'none',
    exec_mode: 'fork',
    autorestart: true,
    max_restarts: 50,
    restart_delay: 5000
  }]
}
EOF

pm2 delete "$GUARD_NAME" >/dev/null 2>&1 || true
pm2 start "$CONFIG_FILE"
pm2 save

echo "Started ${GUARD_NAME}"
echo "Logs: pm2 logs ${GUARD_NAME}"
