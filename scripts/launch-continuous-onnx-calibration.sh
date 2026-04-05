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

CAL_NAME="onnx-continuous-calibration-${TENANT_ID}-${BOT_ID}"
CONFIG_FILE="/tmp/${CAL_NAME}.config.js"

# Conservative defaults: bounded run + cooldown to avoid churn.
# Keep default cycle sleep below prediction score stale threshold so strict
# fail-closed score-gating does not suppress ONNX due to stale snapshots.
SCORE_STALE_SEC="${PREDICTION_SCORE_STALE_SEC:-900}"
if [[ -n "${CYCLE_SLEEP_SEC:-}" ]]; then
  CYCLE_SLEEP_SEC="${CYCLE_SLEEP_SEC}"
else
  # Use a safe cadence by default: 5m updates, or stale-threshold-60s if lower.
  SAFE_SLEEP=$(( SCORE_STALE_SEC - 60 ))
  if (( SAFE_SLEEP < 120 )); then
    SAFE_SLEEP=120
  fi
  if (( SAFE_SLEEP > 300 )); then
    SAFE_SLEEP=300
  fi
  CYCLE_SLEEP_SEC="${SAFE_SLEEP}"
fi
MAX_RUNTIME_SEC="${MAX_RUNTIME_SEC:-300}"                  # each run capped at 5 minutes
SLEEP_SEC="${SLEEP_SEC:-20}"                               # intra-run sleep (script iterations)
WARMUP_SEC="${WARMUP_SEC:-20}"                             # post-restart warmup
MAX_ITERATIONS="${MAX_ITERATIONS:-1}"                      # one attempt per cycle
TAIL_COUNT="${TAIL_COUNT:-60000}"
HOURS_LOOKBACK="${HOURS_LOOKBACK:-24}"
HORIZON_SEC="${HORIZON_SEC:-60}"
SCORE_HOURS="${SCORE_HOURS:-2.0}"
SCORE_COUNT="${SCORE_COUNT:-15000}"
SCORE_PROVIDER="${SCORE_PROVIDER:-shadow}"
SCORE_MIN_SAMPLES="${SCORE_MIN_SAMPLES:-200}"
SCORE_MIN_ML_SCORE="${SCORE_MIN_ML_SCORE:-${PREDICTION_SCORE_MIN_ML_SCORE:-30}}"
SCORE_MIN_EXACT_ACCURACY="${SCORE_MIN_EXACT_ACCURACY:-${PREDICTION_SCORE_MIN_EXACT_ACCURACY:-0.30}}"
SCORE_MAX_ECE="${SCORE_MAX_ECE:-${PREDICTION_SCORE_MAX_ECE:-0.60}}"
# Directional coverage can be near-zero for mean-reversion-dominant regimes.
# Keep permissive by default so scorer status reflects calibration quality first.
SCORE_MIN_DIRECTIONAL_COVERAGE="${SCORE_MIN_DIRECTIONAL_COVERAGE:-0.00}"
# Keep score snapshot key alive comfortably longer than cycle sleep to avoid
# key-expiry-related blind spots in dashboard/pipeline-health.
SCORE_SNAPSHOT_TTL_SEC="${SCORE_SNAPSHOT_TTL_SEC:-7200}"
# Auto-select label source from latest model contract when not explicitly set.
if [[ -z "${LABEL_SOURCE:-}" ]]; then
  MODEL_META_PATH="${PROJECT_ROOT}/quantgambit-python/models/registry/latest.json"
  if [[ -f "${MODEL_META_PATH}" ]]; then
    DETECTED_CONTRACT="$("${PYTHON_BIN}" - <<'PY'
import json
from pathlib import Path
path = Path("quantgambit-python/models/registry/latest.json")
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
contract = str(payload.get("prediction_contract") or "").strip().lower()
print(contract)
PY
)"
    case "${DETECTED_CONTRACT}" in
      tp_before_sl_within_horizon)
        LABEL_SOURCE="tp_sl"
        ;;
      action_conditional_pnl_winprob)
        LABEL_SOURCE="policy_replay"
        ;;
      *)
        LABEL_SOURCE="future_return"
        ;;
    esac
  else
    LABEL_SOURCE="future_return"
  fi
else
  LABEL_SOURCE="${LABEL_SOURCE}"
fi

RUNTIME_PROCESS_NAME="${RUNTIME_PROCESS_NAME:-runtime-${TENANT_ID}-${BOT_ID}}"
FEATURE_STREAM="${FEATURE_STREAM:-events:features:${TENANT_ID}:${BOT_ID}}"
RESTART_RUNTIME="${RESTART_RUNTIME:-false}"

if [[ "${RESTART_RUNTIME}" == "true" ]]; then
  RESTART_RUNTIME_ARG="--restart-runtime"
else
  RESTART_RUNTIME_ARG="--no-restart-runtime"
fi

echo "Launching continuous ONNX calibration:"
echo "  PM2 process: $CAL_NAME"
echo "  Runtime process: $RUNTIME_PROCESS_NAME"
echo "  Tenant/Bot: $TENANT_ID / $BOT_ID"
echo "  Cycle sleep: ${CYCLE_SLEEP_SEC}s"
echo "  Max runtime per cycle: ${MAX_RUNTIME_SEC}s"
echo "  Runtime restart mode: ${RESTART_RUNTIME_ARG}"

cat > "$CONFIG_FILE" << EOF
module.exports = {
  apps: [{
    name: '${CAL_NAME}',
    cwd: '${PROJECT_ROOT}',
    script: '/bin/bash',
    args: ['-lc', 'set -euo pipefail; while true; do \
"${PYTHON_BIN}" "quantgambit-python/scripts/continuous_calibrate_until_pass.py" \
  --model-meta "models/registry/latest.json" \
  --tenant-id "${TENANT_ID}" \
  --bot-id "${BOT_ID}" \
  --redis-url "${REDIS_URL}" \
  --stream "${FEATURE_STREAM}" \
  --tail-count "${TAIL_COUNT}" \
  --hours "${HOURS_LOOKBACK}" \
  --horizon-sec "${HORIZON_SEC}" \
  --label-source "${LABEL_SOURCE}" \
  --score-hours "${SCORE_HOURS}" \
  --score-count "${SCORE_COUNT}" \
  --score-provider "${SCORE_PROVIDER}" \
  --score-min-samples "${SCORE_MIN_SAMPLES}" \
  --score-min-ml-score "${SCORE_MIN_ML_SCORE}" \
  --score-min-exact-accuracy "${SCORE_MIN_EXACT_ACCURACY}" \
  --score-max-ece "${SCORE_MAX_ECE}" \
  --score-min-directional-coverage "${SCORE_MIN_DIRECTIONAL_COVERAGE}" \
  --score-snapshot-ttl-sec "${SCORE_SNAPSHOT_TTL_SEC}" \
  --max-iterations "${MAX_ITERATIONS}" \
  --max-runtime-sec "${MAX_RUNTIME_SEC}" \
  --sleep-sec "${SLEEP_SEC}" \
  --warmup-sec "${WARMUP_SEC}" \
  "${RESTART_RUNTIME_ARG}" \
  --runtime-process-name "${RUNTIME_PROCESS_NAME}" \
  --live-from-stream || true; \
sleep "${CYCLE_SLEEP_SEC}"; done'],
    interpreter: 'none',
    exec_mode: 'fork',
    autorestart: true,
    max_restarts: 50,
    restart_delay: 5000
  }]
}
EOF

pm2 delete "$CAL_NAME" >/dev/null 2>&1 || true
pm2 start "$CONFIG_FILE"
pm2 save

echo "Started ${CAL_NAME}"
echo "Logs: pm2 logs ${CAL_NAME}"
