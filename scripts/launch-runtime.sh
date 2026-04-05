#!/bin/bash
# Runtime launcher script - called by control manager with full environment in env vars

set -e

# Ensure PATH includes common PM2 install locations on both macOS and Linux.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:$PATH"
PM2="${PM2_BIN:-$(command -v pm2 || true)}"
if [ -z "$PM2" ]; then
    echo "Error: pm2 not found in PATH"
    exit 1
fi

# Optional explicit refresh flag.
# Can be set either as CLI arg (--refresh-runtime) or env var REFRESH_RUNTIME=true.
REFRESH_RUNTIME="${REFRESH_RUNTIME:-false}"
while [ $# -gt 0 ]; do
    case "$1" in
        --refresh-runtime)
            REFRESH_RUNTIME="true"
            shift
            ;;
        --no-refresh-runtime)
            REFRESH_RUNTIME="false"
            shift
            ;;
        *)
            break
            ;;
    esac
done

if [ -z "$TENANT_ID" ] || [ -z "$BOT_ID" ]; then
    echo "Error: TENANT_ID and BOT_ID must be set"
    exit 1
fi

load_env_file() {
    local env_file="$1"
    if [ -z "$env_file" ]; then
        return 0
    fi
    local resolved="$env_file"
    if [ ! -f "$resolved" ]; then
        resolved="${PROJECT_ROOT}/${env_file}"
    fi
    if [ ! -f "$resolved" ]; then
        echo "Error: ENV_FILE '${env_file}' not found"
        exit 1
    fi
    while IFS='=' read -r key value; do
        case "$key" in
            ""|\#*) continue ;;
        esac
        key="${key#export }"
        key="$(printf '%s' "$key" | xargs)"
        if [ -z "$key" ]; then
            continue
        fi
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        if printf '%s\n' "$ORIGINAL_ENV_KEYS" | grep -qx "$key"; then
            continue
        fi
        export "$key=$value"
    done < "$resolved"
}

RUNTIME_NAME="runtime-${TENANT_ID}-${BOT_ID}"
RECONCILE_NAME="execution-reconcile-${TENANT_ID}-${BOT_ID}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="/tmp/runtime-${TENANT_ID}-${BOT_ID}.config.js"
RECONCILE_CONFIG_FILE="/tmp/execution-reconcile-${TENANT_ID}-${BOT_ID}.config.js"

if [ -x "${PROJECT_ROOT}/quantgambit-python/venv311/bin/python" ]; then
    PYTHON_PATH="${PROJECT_ROOT}/quantgambit-python/venv311/bin/python"
elif [ -x "${PROJECT_ROOT}/quantgambit-python/venv/bin/python" ]; then
    PYTHON_PATH="${PROJECT_ROOT}/quantgambit-python/venv/bin/python"
else
    echo "Error: QuantGambit Python runtime not found in venv/bin/python or venv311/bin/python"
    exit 1
fi

ORIGINAL_ENV_KEYS="$(env | awk -F= '{print $1}')"
SELECTED_ENV_FILE="${ENV_FILE:-.env}"
load_env_file ".env"
if [ "$SELECTED_ENV_FILE" != ".env" ]; then
    load_env_file "$SELECTED_ENV_FILE"
fi
export ENV_FILE="$SELECTED_ENV_FILE"

apply_ai_profile_overrides() {
    if [ -z "${PROFILE_OVERRIDES:-}" ]; then
        return 0
    fi
    local ai_values
    ai_values="$(
        PROFILE_OVERRIDES_JSON="${PROFILE_OVERRIDES}" python3 - <<'PY'
import json
import os

raw = os.environ.get("PROFILE_OVERRIDES_JSON", "").strip()
if not raw:
    raise SystemExit(0)
try:
    payload = json.loads(raw)
except Exception:
    raise SystemExit(0)
if not isinstance(payload, dict):
    raise SystemExit(0)
bot_type = str(payload.get("bot_type") or "").strip().lower()
ai_provider = str(payload.get("ai_provider") or "").strip().lower()
if bot_type != "ai_spot_swing" and ai_provider not in {"deepseek_context", "context_model", "ai_spot_swing"}:
    raise SystemExit(0)
provider = ai_provider or "deepseek_context"
print(f"PREDICTION_PROVIDER={provider}")
confidence = payload.get("ai_confidence_floor")
if confidence is not None:
    print(f"AI_PROVIDER_MIN_CONFIDENCE={confidence}")
sessions = payload.get("ai_sessions")
if isinstance(sessions, list):
    cleaned = ",".join(str(item).strip() for item in sessions if str(item).strip())
    if cleaned:
        print(f"AI_ENABLED_SESSIONS={cleaned}")
for key in ("ai_shadow_mode", "ai_require_baseline_alignment", "ai_sentiment_required"):
    if key in payload:
        env_key = {
            "ai_shadow_mode": "AI_SHADOW_ONLY",
            "ai_require_baseline_alignment": "AI_PROVIDER_REQUIRE_BASELINE_ALIGNMENT",
            "ai_sentiment_required": "AI_SENTIMENT_REQUIRED",
        }[key]
        print(f"{env_key}={'true' if bool(payload.get(key)) else 'false'}")
PY
    )"
    if [ -n "$ai_values" ]; then
        while IFS='=' read -r key value; do
            [ -z "$key" ] && continue
            export "$key=$value"
        done <<EOF
$ai_values
EOF
        unset PREDICTION_MODEL_PATH
        unset PREDICTION_MODEL_CONFIG
        unset PREDICTION_MODEL_FEATURES
        unset PREDICTION_MODEL_CLASSES
    fi
}

apply_ai_profile_overrides

STREAM_SUFFIX=""
if [ -n "${ACTIVE_EXCHANGE:-}" ]; then
    normalized_market_type="$(printf '%s' "${MARKET_TYPE:-}" | tr '[:upper:]' '[:lower:]')"
    if [ "$normalized_market_type" = "spot" ]; then
        STREAM_SUFFIX=":${ACTIVE_EXCHANGE}:spot"
    else
        STREAM_SUFFIX=":${ACTIVE_EXCHANGE}"
    fi
fi

require_env() {
    local key="$1"
    if [ -z "${!key:-}" ]; then
        echo "Error: ${key} must be set"
        exit 1
    fi
}

require_any_env() {
    local provided=false
    for key in "$@"; do
        if [ -n "${!key:-}" ]; then
            provided=true
            break
        fi
    done
    if [ "$provided" = "false" ]; then
        echo "Error: one of the following must be set: $*"
        exit 1
    fi
}

build_postgres_url() {
    local host="$1"
    local port="$2"
    local user="$3"
    local password="$4"
    local dbname="$5"
    PG_HOST="$host" \
    PG_PORT="$port" \
    PG_USER="$user" \
    PG_PASSWORD="$password" \
    PG_DBNAME="$dbname" \
    python3 - <<'PY'
import os
import urllib.parse

host = os.environ["PG_HOST"]
port = os.environ["PG_PORT"]
user = urllib.parse.quote(os.environ["PG_USER"], safe="")
password = urllib.parse.quote(os.environ["PG_PASSWORD"], safe="")
dbname = urllib.parse.quote(os.environ["PG_DBNAME"], safe="")
print(f"postgresql://{user}:{password}@{host}:{port}/{dbname}")
PY
}

runtime_contract_hash() {
    local payload
    payload=$(cat <<EOF
version=1
tenant_id=${TENANT_ID}
bot_id=${BOT_ID}
runtime_name=${RUNTIME_NAME}
env_file=${ENV_FILE:-.env}
active_exchange=${ACTIVE_EXCHANGE}
trading_mode=${TRADING_MODE}
market_type=${MARKET_TYPE}
execution_provider=${EXECUTION_PROVIDER}
orderbook_source=${ORDERBOOK_SOURCE}
trade_source=${TRADE_SOURCE}
market_data_provider=${MARKET_DATA_PROVIDER}
orderbook_symbols=${ORDERBOOK_SYMBOLS}
market_data_symbols=${MARKET_DATA_SYMBOLS:-${ORDERBOOK_SYMBOLS}}
config_version=${CONFIG_VERSION:-}
exchange_account_id=${EXCHANGE_ACCOUNT_ID:-}
exchange_secret_id_present=$([ -n "${EXCHANGE_SECRET_ID:-}" ] && echo 1 || echo 0)
bot_db_host=${BOT_DB_HOST:-}
bot_db_port=${BOT_DB_PORT:-}
bot_db_name=${BOT_DB_NAME:-}
bot_db_user=${BOT_DB_USER:-}
bot_timescale_url_present=$([ -n "${BOT_TIMESCALE_URL:-}" ] && echo 1 || echo 0)
redis_url=${REDIS_URL_VALUE:-}
prediction_provider=${PREDICTION_PROVIDER:-}
prediction_model_config=${PREDICTION_MODEL_CONFIG:-}
prediction_model_path=${PREDICTION_MODEL_PATH:-}
prediction_model_features=${PREDICTION_MODEL_FEATURES:-}
prediction_model_classes=${PREDICTION_MODEL_CLASSES:-}
prediction_shadow_provider=${PREDICTION_SHADOW_PROVIDER:-}
prediction_shadow_model_config=${PREDICTION_SHADOW_MODEL_CONFIG:-}
prediction_shadow_model_path=${PREDICTION_SHADOW_MODEL_PATH:-}
prediction_shadow_model_features=${PREDICTION_SHADOW_MODEL_FEATURES:-}
prediction_shadow_model_classes=${PREDICTION_SHADOW_MODEL_CLASSES:-}
trading_disabled=${TRADING_DISABLED:-false}
EOF
)
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$payload" | sha256sum | awk '{print $1}'
    else
        printf '%s' "$payload" | shasum -a 256 | awk '{print $1}'
    fi
}

for required_key in TENANT_ID BOT_ID ACTIVE_EXCHANGE TRADING_MODE MARKET_TYPE EXECUTION_PROVIDER ORDERBOOK_SOURCE TRADE_SOURCE MARKET_DATA_PROVIDER ORDERBOOK_SYMBOLS; do
    require_env "$required_key"
done
require_any_env EXCHANGE_SECRET_ID EXCHANGE_ACCOUNT_ID

RUNTIME_DEV_OVERRIDES="${RUNTIME_DEV_OVERRIDES:-false}"

# Optional local-dev runtime tuning overrides. Control-manager remains authoritative
# unless RUNTIME_DEV_OVERRIDES=true is set explicitly.
if [ "$RUNTIME_DEV_OVERRIDES" = "true" ] && [ -f "${PROJECT_ROOT}/.env" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            ""|\#*) continue ;;
        esac
        if ! [[ "$key" =~ ^(EV_GATE_|GLOBAL_GATE_|CANDIDATE_VETO_|POC_MAGNET_|PREDICTION_|ACTION_CONDITIONAL_|COOLDOWN_|ENTRY_|SNAPSHOT_|MODEL_DIRECTION_ALIGNMENT_|REPLACE_MIN_EDGE_BPS|MIN_NET_EDGE_BPS|EXECUTION_POLICY_FORCE_TAKER|EV_GATE_FEE_CONFIG|POSITION_GUARD_|EXIT_SIGNAL_|SLIPPAGE_MODEL_|CONFIRMATION_POLICY_|ENABLE_UNIFIED_CONFIRMATION_POLICY|ENABLE_LEGACY_CONFIRMATION_ADAPTER|ENABLE_CONFIRMATION_STAGE|THROTTLE_MODE|PARAM_) ]]; then
            continue
        fi
        # Strip surrounding quotes if present
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        export "$key=$value"
    done < "${PROJECT_ROOT}/.env"
fi

# Check if runtime already exists in PM2 (any state except stopped/errored)
RUNTIME_STATUS=$($PM2 show "$RUNTIME_NAME" 2>/dev/null | grep "│ status" | awk -F '│' '{gsub(/^[ \t]+|[ \t]+$/, "", $3); print $3}' || echo "not_found")

echo "Current runtime status: $RUNTIME_STATUS"

# Skip launch if runtime is already online OR is still starting up (launching),
# unless explicit refresh was requested.
if [ "$RUNTIME_STATUS" = "online" ] || [ "$RUNTIME_STATUS" = "launching" ]; then
    if [ "$REFRESH_RUNTIME" = "true" ]; then
        echo "Runtime $RUNTIME_NAME is $RUNTIME_STATUS; explicit refresh requested, restarting"
    else
        echo "Runtime $RUNTIME_NAME is already running (status: $RUNTIME_STATUS) - skipping restart"
        echo "Use '--refresh-runtime' or REFRESH_RUNTIME=true to force restart"
        exit 0
    fi
fi

# Also check if runtime process actually exists and is running via PM2
RUNTIME_PID=$($PM2 show "$RUNTIME_NAME" 2>/dev/null | grep "│ pid" | awk -F '│' '{gsub(/^[ \t]+|[ \t]+$/, "", $3); print $3}')
if [ -n "$RUNTIME_PID" ] && [ "$RUNTIME_PID" != "N/A" ] && [ "$RUNTIME_PID" != "0" ]; then
    # Process exists with a valid PID - check if it's actually running
    if kill -0 "$RUNTIME_PID" 2>/dev/null; then
        if [ "$REFRESH_RUNTIME" = "true" ]; then
            echo "Runtime $RUNTIME_NAME process (PID $RUNTIME_PID) is running; explicit refresh requested, restarting"
        else
            echo "Runtime $RUNTIME_NAME process (PID $RUNTIME_PID) is still running - skipping restart"
            echo "Use '--refresh-runtime' or REFRESH_RUNTIME=true to force restart"
            exit 0
        fi
    fi
fi

# Apply bot migrations before starting a fresh runtime.
BOT_MIGRATION_PYTHON="$PYTHON_PATH"
echo "Applying bot database migrations via authoritative runner..."
if ! (
    cd "${PROJECT_ROOT}/quantgambit-python" && \
    PYTHONPATH="${PROJECT_ROOT}/quantgambit-python${PYTHONPATH:+:${PYTHONPATH}}" \
    "$BOT_MIGRATION_PYTHON" scripts/run_migrations.py
); then
    echo "Error: bot database migrations failed"
    exit 1
fi

echo "Starting new runtime: $RUNTIME_NAME"
echo "Environment: ACTIVE_EXCHANGE=${ACTIVE_EXCHANGE:-binance}, TENANT_ID=${TENANT_ID}, BOT_ID=${BOT_ID}"
echo "Runtime gate summary: SCORE_MODE=${PREDICTION_SCORE_GATE_MODE:-block}, SCORE_ENABLED=${PREDICTION_SCORE_GATE_ENABLED:-false}, ALIGN_SOURCES=${MODEL_DIRECTION_ALIGNMENT_ENFORCE_SOURCES:-onnx}, MAX_SLIPPAGE=${EXECUTION_MAX_SLIPPAGE_BPS:-30}, MIN_NET_EDGE=${MIN_NET_EDGE_BPS:-5}"
echo "Position guard summary: ENABLED=${POSITION_GUARD_ENABLED:-unset}, MAX_AGE=${POSITION_GUARD_MAX_AGE_SEC:-unset}, HARD_MAX_AGE=${POSITION_GUARD_MAX_AGE_HARD_SEC:-unset}, TP_LIMIT=${POSITION_GUARD_TP_LIMIT_EXIT_ENABLED:-unset}"

# Optional local-dev escape hatch for secret discovery.
ALLOW_LOCAL_SECRET_AUTODETECT="${ALLOW_LOCAL_SECRET_AUTODETECT:-false}"
if [ -z "${EXCHANGE_SECRET_ID:-}" ] && [ "$ALLOW_LOCAL_SECRET_AUTODETECT" = "true" ]; then
    ENV_NAME="${DEEPTRADER_ENV:-dev}"
    EXCHANGE_LC="$(echo "${ACTIVE_EXCHANGE:-}" | tr '[:upper:]' '[:lower:]')"
    SECRETS_DIR="${PROJECT_ROOT}/deeptrader-backend/.secrets/${ENV_NAME}"
    # Filename format: deeptrader__{env}__{tenant}__{exchange}__{credentialId}.enc
    CANDIDATE_FILE="$(ls -1t "${SECRETS_DIR}/deeptrader__${ENV_NAME}__${TENANT_ID}__${EXCHANGE_LC}__"*.enc 2>/dev/null | head -n 1 || true)"
    if [ -n "$CANDIDATE_FILE" ]; then
        BASE_NAME="$(basename "$CANDIDATE_FILE" .enc)"
        # Reverse sanitize: "__" -> "/"
        EXCHANGE_SECRET_ID="${BASE_NAME//__/\/}"
    fi
fi
require_any_env EXCHANGE_SECRET_ID EXCHANGE_ACCOUNT_ID

# Compute default values for database and Redis connections
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_URL_VALUE="${REDIS_URL:-redis://${REDIS_HOST}:${REDIS_PORT}}"
BOT_REDIS_URL_VALUE="${REDIS_URL_VALUE}"

if [ -n "${BOT_DB_HOST:-}" ] && [ -n "${BOT_DB_PORT:-}" ] && [ -n "${BOT_DB_USER:-}" ] && [ -n "${BOT_DB_PASSWORD:-}" ] && [ -n "${BOT_DB_NAME:-}" ]; then
    if [ -n "${BOT_TIMESCALE_URL:-}" ] && [[ "${BOT_TIMESCALE_URL}" == *'${'* ]]; then
        echo "Warning: ignoring unresolved BOT_TIMESCALE_URL template and rebuilding from BOT_DB_* vars"
    fi
    BOT_TIMESCALE_URL_VALUE="$(build_postgres_url "${BOT_DB_HOST}" "${BOT_DB_PORT}" "${BOT_DB_USER}" "${BOT_DB_PASSWORD}" "${BOT_DB_NAME}")"
elif [ -n "${BOT_TIMESCALE_URL:-}" ] && [[ "${BOT_TIMESCALE_URL}" != *'${'* ]]; then
    BOT_TIMESCALE_URL_VALUE="${BOT_TIMESCALE_URL}"
else
    REQUIRED_BOT_DB_VARS=(BOT_DB_HOST BOT_DB_PORT BOT_DB_USER BOT_DB_PASSWORD BOT_DB_NAME)
    for required_var in "${REQUIRED_BOT_DB_VARS[@]}"; do
        if [ -z "${!required_var:-}" ]; then
            echo "Error: ${required_var} must be set when BOT_TIMESCALE_URL is not provided"
            exit 1
        fi
    done
    BOT_TIMESCALE_URL_VALUE="$(build_postgres_url "${BOT_DB_HOST}" "${BOT_DB_PORT}" "${BOT_DB_USER}" "${BOT_DB_PASSWORD}" "${BOT_DB_NAME}")"
fi

if [ "${PREDICTION_PROVIDER:-}" = "onnx" ]; then
    for required_key in PREDICTION_MODEL_CONFIG PREDICTION_MODEL_PATH; do
        require_env "$required_key"
    done
fi

if [ "${PREDICTION_SHADOW_PROVIDER:-}" = "onnx" ]; then
    for required_key in PREDICTION_SHADOW_MODEL_CONFIG PREDICTION_SHADOW_MODEL_PATH; do
        require_env "$required_key"
    done
fi

# For live trading, default EXECUTION_PROVIDER to ccxt if missing/none
if [ "$TRADING_MODE" = "live" ] && { [ -z "$EXECUTION_PROVIDER" ] || [ "$EXECUTION_PROVIDER" = "none" ]; }; then
    EXECUTION_PROVIDER="ccxt"
fi

# Fee-first canary profile:
# - enabled by default only for BTC-only live runs
# - enforces stricter spread/slippage/churn settings to reduce fee drag
if [ -z "${FEE_FIRST_CANARY_ENABLED+x}" ]; then
    if [ "${TRADING_MODE:-}" = "live" ] && [ "${ORDERBOOK_SYMBOLS:-}" = "BTCUSDT" ]; then
        FEE_FIRST_CANARY_ENABLED="true"
    else
        FEE_FIRST_CANARY_ENABLED="false"
    fi
fi

if [ "${TRADING_MODE:-}" = "live" ] && [ "${FEE_FIRST_CANARY_ENABLED}" = "true" ]; then
    export MIN_ORDER_INTERVAL_SEC="${FEE_FIRST_MIN_ORDER_INTERVAL_SEC:-45}"
    export EXECUTION_MAX_SLIPPAGE_BPS="${FEE_FIRST_MAX_SLIPPAGE_BPS:-10}"
    export GLOBAL_GATE_MAX_SPREAD_BPS="${FEE_FIRST_MAX_SPREAD_BPS:-8}"
    export POSITION_GUARD_BREAKEVEN_ACTIVATION_BPS="${FEE_FIRST_BREAKEVEN_ACTIVATION_BPS:-24.0}"
    export POSITION_GUARD_MIN_PROFIT_BUFFER_BPS="${FEE_FIRST_MIN_PROFIT_BUFFER_BPS:-18.0}"
    export POSITION_GUARD_MAX_AGE_SEC="${FEE_FIRST_MAX_AGE_SEC:-480}"
fi

# Safety policy is set by the control plane; do not silently force-disable live runtime
# launches here or every bot will arm its own persistent kill switch by default.
if [ -z "${TRADING_DISABLED+x}" ]; then
    TRADING_DISABLED="false"
fi

LAUNCH_RUNTIME_CONTRACT_VERSION="1"
LAUNCH_RUNTIME_CONTRACT_HASH="$(runtime_contract_hash)"
if [ -n "${LAUNCH_RUNTIME_CONTRACT_HASH_EXPECTED:-}" ] && [ "$LAUNCH_RUNTIME_CONTRACT_HASH" != "$LAUNCH_RUNTIME_CONTRACT_HASH_EXPECTED" ]; then
    echo "Error: launch runtime contract hash mismatch (expected ${LAUNCH_RUNTIME_CONTRACT_HASH_EXPECTED}, got ${LAUNCH_RUNTIME_CONTRACT_HASH})"
    exit 1
fi

# Generate a temporary ecosystem config file with all environment variables
cat > "$CONFIG_FILE" << EOF
module.exports = {
  apps: [{
    name: '${RUNTIME_NAME}',
    script: '${PYTHON_PATH}',
    args: '-m quantgambit.runtime.entrypoint',
    cwd: '${PROJECT_ROOT}/quantgambit-python',
    interpreter: 'none',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      ...process.env,
      PYTHONPATH: '${PROJECT_ROOT}/quantgambit-python',
      ENV_FILE: '${ENV_FILE:-.env}',
      LAUNCH_RUNTIME_CONTRACT_VERSION: '${LAUNCH_RUNTIME_CONTRACT_VERSION}',
      LAUNCH_RUNTIME_CONTRACT_HASH: '${LAUNCH_RUNTIME_CONTRACT_HASH}',
      REDIS_URL: '${REDIS_URL_VALUE}',
      BOT_REDIS_URL: '${BOT_REDIS_URL_VALUE}',
      REDIS_HOST: '${REDIS_HOST}',
      REDIS_PORT: '${REDIS_PORT}',
      BOT_TIMESCALE_URL: '${BOT_TIMESCALE_URL_VALUE}',
      TENANT_ID: '${TENANT_ID}',
      BOT_ID: '${BOT_ID}',
      ACTIVE_EXCHANGE: '${ACTIVE_EXCHANGE}',
      TRADING_MODE: '${TRADING_MODE:-paper}',
      TRADING_DISABLED: '${TRADING_DISABLED:-false}',
      EXECUTION_PROVIDER: '${EXECUTION_PROVIDER}',
      ORDERBOOK_SOURCE: '${ORDERBOOK_SOURCE}',
      TRADE_SOURCE: '${TRADE_SOURCE}',
      ORDERBOOK_SYMBOLS: '${ORDERBOOK_SYMBOLS}',
      MARKET_DATA_SYMBOLS: '${MARKET_DATA_SYMBOLS:-${ORDERBOOK_SYMBOLS}}',
      MARKET_DATA_PROVIDER: '${MARKET_DATA_PROVIDER}',
      ORDERBOOK_TESTNET: '${ORDERBOOK_TESTNET:-false}',
      ORDER_UPDATES_TESTNET: '${ORDER_UPDATES_TESTNET:-${ORDERBOOK_TESTNET:-false}}',
      ORDER_UPDATES_DEMO: '${ORDER_UPDATES_DEMO:-false}',
      // Exchange-specific testnet flag (used by credential loading)
      OKX_TESTNET: '${OKX_TESTNET:-${ORDERBOOK_TESTNET:-false}}',
      BINANCE_TESTNET: '${BINANCE_TESTNET:-${ORDERBOOK_TESTNET:-false}}',
      BYBIT_TESTNET: '${BYBIT_TESTNET:-${ORDERBOOK_TESTNET:-false}}',
      BYBIT_DEMO: '${BYBIT_DEMO:-${ORDER_UPDATES_DEMO:-false}}',
      ORDERBOOK_EVENT_STREAM: '${ORDERBOOK_EVENT_STREAM:-events:orderbook_feed${STREAM_SUFFIX}}',
      TRADE_STREAM: '${TRADE_STREAM:-events:trades${STREAM_SUFFIX}}',
      MARKET_DATA_STREAM: '${MARKET_DATA_STREAM:-events:market_data${STREAM_SUFFIX}}',
      MARKET_TYPE: '${MARKET_TYPE}',
      MARGIN_MODE: '${MARGIN_MODE:-}',
      CONFIG_VERSION: '${CONFIG_VERSION:-}',
      // Secure credentials - runtime fetches from secrets store using this ID
      EXCHANGE_SECRET_ID: '${EXCHANGE_SECRET_ID:-}',
      EXCHANGE_ACCOUNT_ID: '${EXCHANGE_ACCOUNT_ID:-}',
      // Account balance for live trading (set by control manager from exchange_accounts table)
      LIVE_EQUITY: '${LIVE_EQUITY:-}',
      PAPER_EQUITY: '${PAPER_EQUITY:-100000}',
      // Risk parameters - loaded from bot/exchange config, with defaults
      RISK_PER_TRADE_PCT: '${RISK_PER_TRADE_PCT:-5.0}',  // Default 5% for testnet to meet minimums
      MIN_POSITION_SIZE_USD: '${MIN_POSITION_SIZE_USD:-500.0}',
      MAX_POSITIONS: '${MAX_POSITIONS:-4}',
      MAX_POSITIONS_PER_SYMBOL: '${MAX_POSITIONS_PER_SYMBOL:-1}',
      MAX_TOTAL_EXPOSURE_PCT: '${MAX_TOTAL_EXPOSURE_PCT:-50.0}',
      MAX_DAILY_DRAWDOWN_PCT: '${MAX_DAILY_DRAWDOWN_PCT:-5.0}',
      MAX_DRAWDOWN_PCT: '${MAX_DRAWDOWN_PCT:-10.0}',
      MAX_POSITION_SIZE_USD: '${MAX_POSITION_SIZE_USD:-}',
      DEFAULT_STOP_LOSS_PCT: '${DEFAULT_STOP_LOSS_PCT:-}',
      DEFAULT_TAKE_PROFIT_PCT: '${DEFAULT_TAKE_PROFIT_PCT:-}',
      // Execution parameters
      MAX_DECISION_AGE_SEC: '${MAX_DECISION_AGE_SEC:-60.0}',
      // Prediction thresholds
      PREDICTION_MIN_CONFIDENCE: '${PREDICTION_MIN_CONFIDENCE:-0.0}',
      ACTION_CONDITIONAL_POLICY_ENABLED: '${ACTION_CONDITIONAL_POLICY_ENABLED:-true}',
      ACTION_CONDITIONAL_P_THRESH: '${ACTION_CONDITIONAL_P_THRESH:-0.65}',
      ACTION_CONDITIONAL_MARGIN_THRESH: '${ACTION_CONDITIONAL_MARGIN_THRESH:-0.0}',
      PREDICTION_GATE_ENFORCE_SCORE_METRICS: '${PREDICTION_GATE_ENFORCE_SCORE_METRICS:-true}',
      PREDICTION_GATE_SCORE_FAIL_CLOSED: '${PREDICTION_GATE_SCORE_FAIL_CLOSED:-false}',
      PREDICTION_SCORE_GATE_ENABLED: '${PREDICTION_SCORE_GATE_ENABLED:-false}',
      PREDICTION_SCORE_GATE_MODE: '${PREDICTION_SCORE_GATE_MODE:-block}',
      PREDICTION_SCORE_FAIL_CLOSED: '${PREDICTION_SCORE_FAIL_CLOSED:-false}',
      PREDICTION_SCORE_MIN_SAMPLES: '${PREDICTION_SCORE_MIN_SAMPLES:-200}',
      PREDICTION_SCORE_MIN_ML_SCORE: '${PREDICTION_SCORE_MIN_ML_SCORE:-60.0}',
      PREDICTION_SCORE_MIN_EXACT_ACCURACY: '${PREDICTION_SCORE_MIN_EXACT_ACCURACY:-0.50}',
      PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY: '${PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY:-0.50}',
      PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_LONG: '${PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_LONG:-}',
      PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_SHORT: '${PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_SHORT:-}',
      PREDICTION_SCORE_MAX_ECE: '${PREDICTION_SCORE_MAX_ECE:-0.20}',
      PREDICTION_SCORE_MAX_ECE_LONG: '${PREDICTION_SCORE_MAX_ECE_LONG:-}',
      PREDICTION_SCORE_MAX_ECE_SHORT: '${PREDICTION_SCORE_MAX_ECE_SHORT:-}',
      CONFIRMATION_READY_MAX_ROWS: '${CONFIRMATION_READY_MAX_ROWS:-20000}',
      CONFIRMATION_READY_QUERY_TIMEOUT_SEC: '${CONFIRMATION_READY_QUERY_TIMEOUT_SEC:-2.0}',
      // Decision tracing
      DECISION_GATE_TRACE_VERBOSE: '${DECISION_GATE_TRACE_VERBOSE:-0}',
      // Data readiness gating
      DATA_READINESS_MIN_BID_DEPTH_USD: '${DATA_READINESS_MIN_BID_DEPTH_USD:-1000}',
      DATA_READINESS_MIN_ASK_DEPTH_USD: '${DATA_READINESS_MIN_ASK_DEPTH_USD:-1000}',
      DATA_READINESS_MAX_TRADE_AGE_SEC: '${DATA_READINESS_MAX_TRADE_AGE_SEC:-30}',
      DATA_READINESS_MAX_TRADE_FEED_AGE_SEC: '${DATA_READINESS_MAX_TRADE_FEED_AGE_SEC:-30}',
      DATA_READINESS_TRADE_LAG_GREEN_MS: '${DATA_READINESS_TRADE_LAG_GREEN_MS:-1500}',
      DATA_READINESS_TRADE_LAG_YELLOW_MS: '${DATA_READINESS_TRADE_LAG_YELLOW_MS:-4000}',
      DATA_READINESS_TRADE_LAG_RED_MS: '${DATA_READINESS_TRADE_LAG_RED_MS:-6000}',
      DATA_READINESS_BOOK_GAP_GREEN_MS: '${DATA_READINESS_BOOK_GAP_GREEN_MS:-2000}',
      DATA_READINESS_BOOK_GAP_YELLOW_MS: '${DATA_READINESS_BOOK_GAP_YELLOW_MS:-5000}',
      DATA_READINESS_BOOK_GAP_RED_MS: '${DATA_READINESS_BOOK_GAP_RED_MS:-10000}',
      DATA_READINESS_TRADE_GAP_GREEN_MS: '${DATA_READINESS_TRADE_GAP_GREEN_MS:-2000}',
      DATA_READINESS_TRADE_GAP_YELLOW_MS: '${DATA_READINESS_TRADE_GAP_YELLOW_MS:-5000}',
      DATA_READINESS_TRADE_GAP_RED_MS: '${DATA_READINESS_TRADE_GAP_RED_MS:-10000}',
      // Cost data quality gating
      COST_DATA_QUALITY_MAX_SPREAD_AGE_MS: '${COST_DATA_QUALITY_MAX_SPREAD_AGE_MS:-500}',
      COST_DATA_QUALITY_MAX_BOOK_AGE_MS: '${COST_DATA_QUALITY_MAX_BOOK_AGE_MS:-500}',
      // Degradation thresholds
      DEGRADATION_DEPTH_REDUCE_USD: '${DEGRADATION_DEPTH_REDUCE_USD:-5000}',
      DEGRADATION_DEPTH_NO_ENTRY_USD: '${DEGRADATION_DEPTH_NO_ENTRY_USD:-1000}',
      DEGRADATION_UPGRADE_COOLDOWN_SEC: '${DEGRADATION_UPGRADE_COOLDOWN_SEC:-60}',
      MIN_ORDER_INTERVAL_SEC: '${MIN_ORDER_INTERVAL_SEC:-60.0}',
      BLOCK_IF_POSITION_EXISTS: '${BLOCK_IF_POSITION_EXISTS:-true}',
      MAX_ORDER_RETRIES: '${MAX_ORDER_RETRIES:-2}',
      EXECUTION_MAX_SLIPPAGE_BPS: '${EXECUTION_MAX_SLIPPAGE_BPS:-10}',
      EXECUTION_MAX_SLIPPAGE_BPS_BY_SYMBOL: '${EXECUTION_MAX_SLIPPAGE_BPS_BY_SYMBOL:-}',
      EXECUTION_MAX_SLIPPAGE_BPS_BY_SYMBOL_SESSION: '${EXECUTION_MAX_SLIPPAGE_BPS_BY_SYMBOL_SESSION:-}',
      MIN_NET_EDGE_BPS: '${MIN_NET_EDGE_BPS:-5.0}',
      MIN_NET_EDGE_BPS_BY_SYMBOL: '${MIN_NET_EDGE_BPS_BY_SYMBOL:-}',
      MIN_NET_EDGE_BPS_BY_SYMBOL_SESSION: '${MIN_NET_EDGE_BPS_BY_SYMBOL_SESSION:-}',
      FEE_BPS: '${FEE_BPS:-2.0}',
      SLIPPAGE_BPS_MULTIPLIER: '${SLIPPAGE_BPS_MULTIPLIER:-1.0}',
      NET_EDGE_BUFFER_BPS: '${NET_EDGE_BUFFER_BPS:-0.0}',
      // Throttle mode (scalping, swing, conservative) - controls trading frequency
      THROTTLE_MODE: '${THROTTLE_MODE:-swing}',
      // Position guard
      POSITION_GUARD_ENABLED: '${POSITION_GUARD_ENABLED:-true}',
      POSITION_GUARD_INTERVAL_SEC: '${POSITION_GUARD_INTERVAL_SEC:-1.0}',
      POSITION_GUARD_MAX_AGE_SEC: '${POSITION_GUARD_MAX_AGE_SEC:-300.0}',
      POSITION_GUARD_TRAILING_BPS: '${POSITION_GUARD_TRAILING_BPS:-8.0}',
      POSITION_GUARD_TRAILING_ACTIVATION_BPS: '${POSITION_GUARD_TRAILING_ACTIVATION_BPS:-10.0}',
      POSITION_GUARD_TRAILING_MIN_HOLD_SEC: '${POSITION_GUARD_TRAILING_MIN_HOLD_SEC:-10.0}',
      POSITION_GUARD_BREAKEVEN_ACTIVATION_BPS: '${POSITION_GUARD_BREAKEVEN_ACTIVATION_BPS:-15.0}',
      POSITION_GUARD_BREAKEVEN_BUFFER_BPS: '${POSITION_GUARD_BREAKEVEN_BUFFER_BPS:-10.0}',
      POSITION_GUARD_BREAKEVEN_MIN_HOLD_SEC: '${POSITION_GUARD_BREAKEVEN_MIN_HOLD_SEC:-15.0}',
      POSITION_GUARD_MIN_PROFIT_BUFFER_BPS: '${POSITION_GUARD_MIN_PROFIT_BUFFER_BPS:-5.0}',
      POSITION_GUARD_TP_LIMIT_EXIT_ENABLED: '${POSITION_GUARD_TP_LIMIT_EXIT_ENABLED:-true}',
      POSITION_GUARD_TP_LIMIT_FILL_WINDOW_MS: '${POSITION_GUARD_TP_LIMIT_FILL_WINDOW_MS:-800}',
      POSITION_GUARD_TP_LIMIT_PRICE_BUFFER_BPS: '${POSITION_GUARD_TP_LIMIT_PRICE_BUFFER_BPS:-0.5}',
      POSITION_GUARD_TP_LIMIT_POLL_INTERVAL_MS: '${POSITION_GUARD_TP_LIMIT_POLL_INTERVAL_MS:-150}',
      POSITION_GUARD_TP_LIMIT_TIME_IN_FORCE: '${POSITION_GUARD_TP_LIMIT_TIME_IN_FORCE:-GTC}',
      POSITION_GUARD_TP_LIMIT_EXIT_REASONS: '${POSITION_GUARD_TP_LIMIT_EXIT_REASONS:-}',
      POSITION_GUARD_MAX_AGE_HARD_SEC: '${POSITION_GUARD_MAX_AGE_HARD_SEC:-600.0}',
      POSITION_GUARD_MAX_AGE_CONFIRMATIONS: '${POSITION_GUARD_MAX_AGE_CONFIRMATIONS:-2}',
      POSITION_GUARD_MAX_AGE_RECHECK_SEC: '${POSITION_GUARD_MAX_AGE_RECHECK_SEC:-20.0}',
      POSITION_GUARD_MAX_AGE_EXTENSION_SEC: '${POSITION_GUARD_MAX_AGE_EXTENSION_SEC:-60.0}',
      POSITION_GUARD_MAX_AGE_MAX_EXTENSIONS: '${POSITION_GUARD_MAX_AGE_MAX_EXTENSIONS:-1}',
      POSITION_GUARD_MIN_PNL_BPS_TO_EXTEND: '${POSITION_GUARD_MIN_PNL_BPS_TO_EXTEND:-6.0}',
      POSITION_CONTINUATION_GATE_ENABLED: '${POSITION_CONTINUATION_GATE_ENABLED:-true}',
      POSITION_CONTINUATION_MIN_CONFIDENCE: '${POSITION_CONTINUATION_MIN_CONFIDENCE:-0.70}',
      POSITION_CONTINUATION_MIN_PNL_BPS: '${POSITION_CONTINUATION_MIN_PNL_BPS:-10.0}',
      POSITION_CONTINUATION_MAX_PREDICTION_AGE_SEC: '${POSITION_CONTINUATION_MAX_PREDICTION_AGE_SEC:-20.0}',
      POSITION_CONTINUATION_MAX_DEFER_SEC: '${POSITION_CONTINUATION_MAX_DEFER_SEC:-90.0}',
      POSITION_CONTINUATION_MAX_DEFERS: '${POSITION_CONTINUATION_MAX_DEFERS:-60}',
      // Exit signal gating
      EXIT_SIGNAL_MIN_HOLD_SEC: '${EXIT_SIGNAL_MIN_HOLD_SEC:-0.0}',
      EXIT_SIGNAL_ENFORCE_FEE_CHECK: '${EXIT_SIGNAL_ENFORCE_FEE_CHECK:-true}',
      // Replacement controls
      ALLOW_POSITION_REPLACEMENT: '${ALLOW_POSITION_REPLACEMENT:-false}',
      REPLACE_OPPOSITE_ONLY: '${REPLACE_OPPOSITE_ONLY:-true}',
      REPLACE_MIN_EDGE_BPS: '${REPLACE_MIN_EDGE_BPS:-0.0}',
      REPLACE_MIN_CONFIDENCE: '${REPLACE_MIN_CONFIDENCE:-0.0}',
      REPLACE_MIN_HOLD_SEC: '${REPLACE_MIN_HOLD_SEC:-0.0}',
      // Prediction gate
      PREDICTION_PROVIDER: '${PREDICTION_PROVIDER:-heuristic}',
      PREDICTION_MIN_CONFIDENCE: '${PREDICTION_MIN_CONFIDENCE:-0.0}',
      PREDICTION_CONFIDENCE_SCALE: '${PREDICTION_CONFIDENCE_SCALE:-1.0}',
      PREDICTION_CONFIDENCE_BIAS: '${PREDICTION_CONFIDENCE_BIAS:-0.0}',
      PREDICTION_ALLOWED_DIRECTIONS: '${PREDICTION_ALLOWED_DIRECTIONS:-}',
      ENABLE_CONFIRMATION_STAGE: '${ENABLE_CONFIRMATION_STAGE:-true}',
      ENABLE_UNIFIED_CONFIRMATION_POLICY: '${ENABLE_UNIFIED_CONFIRMATION_POLICY:-true}',
      ENABLE_LEGACY_CONFIRMATION_ADAPTER: '${ENABLE_LEGACY_CONFIRMATION_ADAPTER:-false}',
      CONFIRMATION_POLICY_MODE: '${CONFIRMATION_POLICY_MODE:-enforce}',
      CONFIRMATION_POLICY_VERSION: '${CONFIRMATION_POLICY_VERSION:-v1}',
      CONFIRMATION_POLICY_ENTRY_MIN_CONFIDENCE: '${CONFIRMATION_POLICY_ENTRY_MIN_CONFIDENCE:-0.64}',
      CONFIRMATION_POLICY_ENTRY_MIN_VOTES: '${CONFIRMATION_POLICY_ENTRY_MIN_VOTES:-2}',
      CONFIRMATION_POLICY_EXIT_MIN_CONFIDENCE: '${CONFIRMATION_POLICY_EXIT_MIN_CONFIDENCE:-0.50}',
      CONFIRMATION_POLICY_EXIT_MIN_VOTES: '${CONFIRMATION_POLICY_EXIT_MIN_VOTES:-2}',
      CONFIRMATION_POLICY_WEIGHT_TREND: '${CONFIRMATION_POLICY_WEIGHT_TREND:-1.0}',
      CONFIRMATION_POLICY_WEIGHT_FLOW: '${CONFIRMATION_POLICY_WEIGHT_FLOW:-1.0}',
      CONFIRMATION_POLICY_WEIGHT_RISK_STABILITY: '${CONFIRMATION_POLICY_WEIGHT_RISK_STABILITY:-1.0}',
      CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE: '${CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE:-0.5}',
      CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE_BY_SYMBOL: '${CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE_BY_SYMBOL:-}',
      CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON: '${CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON:-}',
      PREDICTION_MODEL_CONFIG: '${PREDICTION_MODEL_CONFIG:-}',
      PREDICTION_MODEL_PATH: '${PREDICTION_MODEL_PATH:-}',
      PREDICTION_MODEL_FEATURES: '${PREDICTION_MODEL_FEATURES:-}',
      PREDICTION_MODEL_CLASSES: '${PREDICTION_MODEL_CLASSES:-}',
      PREDICTION_ONNX_MIN_CONFIDENCE: '${PREDICTION_ONNX_MIN_CONFIDENCE:-}',
      PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL: '${PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL:-}',
      PREDICTION_ONNX_MIN_CONFIDENCE_BY_SESSION: '${PREDICTION_ONNX_MIN_CONFIDENCE_BY_SESSION:-}',
      PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL_SESSION: '${PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL_SESSION:-}',
      PREDICTION_ONNX_MIN_MARGIN: '${PREDICTION_ONNX_MIN_MARGIN:-}',
      PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL: '${PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL:-}',
      PREDICTION_ONNX_MIN_MARGIN_BY_SESSION: '${PREDICTION_ONNX_MIN_MARGIN_BY_SESSION:-}',
      PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL_SESSION: '${PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL_SESSION:-}',
      PREDICTION_ONNX_MAX_ENTROPY: '${PREDICTION_ONNX_MAX_ENTROPY:-}',
      PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL: '${PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL:-}',
      PREDICTION_ONNX_MAX_ENTROPY_BY_SESSION: '${PREDICTION_ONNX_MAX_ENTROPY_BY_SESSION:-}',
      PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL_SESSION: '${PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL_SESSION:-}',
      PREDICTION_ONNX_REJECT_FLAT: '${PREDICTION_ONNX_REJECT_FLAT:-}',
      PREDICTION_MIN_F1_DOWN_FOR_SHORT: '${PREDICTION_MIN_F1_DOWN_FOR_SHORT:-}',
      PREDICTION_ONNX_CRITICAL_FEATURES: '${PREDICTION_ONNX_CRITICAL_FEATURES:-}',
      PREDICTION_ONNX_CRITICAL_FEATURE_GATE_ENABLED: '${PREDICTION_ONNX_CRITICAL_FEATURE_GATE_ENABLED:-}',
      PREDICTION_ONNX_CRITICAL_FEATURE_MIN_PRESENCE: '${PREDICTION_ONNX_CRITICAL_FEATURE_MIN_PRESENCE:-}',
      PREDICTION_HEURISTIC_VERSION: '${PREDICTION_HEURISTIC_VERSION:-v1}',
      PREDICTION_HEURISTIC_V2_ENTRY_SCORE: '${PREDICTION_HEURISTIC_V2_ENTRY_SCORE:-}',
      PREDICTION_HEURISTIC_V2_ENTRY_SCORE_LONG: '${PREDICTION_HEURISTIC_V2_ENTRY_SCORE_LONG:-}',
      PREDICTION_HEURISTIC_V2_ENTRY_SCORE_SHORT: '${PREDICTION_HEURISTIC_V2_ENTRY_SCORE_SHORT:-}',
      PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE: '${PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE:-}',
      PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE_LONG: '${PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE_LONG:-}',
      PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE_SHORT: '${PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE_SHORT:-}',
      PREDICTION_HEURISTIC_V2_MIN_DATA_COMPLETENESS: '${PREDICTION_HEURISTIC_V2_MIN_DATA_COMPLETENESS:-}',
      PREDICTION_HEURISTIC_V2_MAX_SPREAD_BPS: '${PREDICTION_HEURISTIC_V2_MAX_SPREAD_BPS:-}',
      PREDICTION_HEURISTIC_V2_MIN_NET_EDGE_BPS: '${PREDICTION_HEURISTIC_V2_MIN_NET_EDGE_BPS:-}',
      PREDICTION_HEURISTIC_V2_EXPECTED_MOVE_PER_SCORE_BPS: '${PREDICTION_HEURISTIC_V2_EXPECTED_MOVE_PER_SCORE_BPS:-}',
      PREDICTION_HEURISTIC_V2_FEE_BPS: '${PREDICTION_HEURISTIC_V2_FEE_BPS:-}',
      PREDICTION_HEURISTIC_V2_SLIPPAGE_BPS: '${PREDICTION_HEURISTIC_V2_SLIPPAGE_BPS:-}',
      PREDICTION_HEURISTIC_V2_ADVERSE_SELECTION_BPS: '${PREDICTION_HEURISTIC_V2_ADVERSE_SELECTION_BPS:-}',
      PREDICTION_HEURISTIC_V2_WEIGHT_IMBALANCE: '${PREDICTION_HEURISTIC_V2_WEIGHT_IMBALANCE:-}',
      PREDICTION_HEURISTIC_V2_WEIGHT_TREND: '${PREDICTION_HEURISTIC_V2_WEIGHT_TREND:-}',
      PREDICTION_HEURISTIC_V2_WEIGHT_ROTATION: '${PREDICTION_HEURISTIC_V2_WEIGHT_ROTATION:-}',
      PREDICTION_HEURISTIC_V2_SYMBOL_BIAS: '${PREDICTION_HEURISTIC_V2_SYMBOL_BIAS:-}',
      PREDICTION_HEURISTIC_V2_SESSION_BIAS: '${PREDICTION_HEURISTIC_V2_SESSION_BIAS:-}',
      PREDICTION_HEURISTIC_V2_SYMBOL_SESSION_BIAS: '${PREDICTION_HEURISTIC_V2_SYMBOL_SESSION_BIAS:-}',
      // Prediction shadow mode (secondary provider for evaluation only)
      PREDICTION_SHADOW_PROVIDER: '${PREDICTION_SHADOW_PROVIDER:-}',
      PREDICTION_SHADOW_HEURISTIC_VERSION: '${PREDICTION_SHADOW_HEURISTIC_VERSION:-}',
      PREDICTION_SHADOW_MODEL_CONFIG: '${PREDICTION_SHADOW_MODEL_CONFIG:-}',
      PREDICTION_SHADOW_MODEL_PATH: '${PREDICTION_SHADOW_MODEL_PATH:-}',
      PREDICTION_SHADOW_MODEL_FEATURES: '${PREDICTION_SHADOW_MODEL_FEATURES:-}',
      PREDICTION_SHADOW_MODEL_CLASSES: '${PREDICTION_SHADOW_MODEL_CLASSES:-}',
      PREDICTION_SHADOW_ONNX_MIN_CONFIDENCE: '${PREDICTION_SHADOW_ONNX_MIN_CONFIDENCE:-}',
      PREDICTION_SHADOW_ONNX_MIN_MARGIN: '${PREDICTION_SHADOW_ONNX_MIN_MARGIN:-}',
      PREDICTION_SHADOW_ONNX_MAX_ENTROPY: '${PREDICTION_SHADOW_ONNX_MAX_ENTROPY:-}',
      MODEL_DIRECTION_ALIGNMENT_ENABLED: '${MODEL_DIRECTION_ALIGNMENT_ENABLED:-true}',
      MODEL_DIRECTION_ALIGNMENT_MIN_CONFIDENCE: '${MODEL_DIRECTION_ALIGNMENT_MIN_CONFIDENCE:-0.60}',
      MODEL_DIRECTION_ALIGNMENT_MIN_MARGIN: '${MODEL_DIRECTION_ALIGNMENT_MIN_MARGIN:-0.02}',
      MODEL_DIRECTION_ALIGNMENT_ENFORCE_SOURCES: '${MODEL_DIRECTION_ALIGNMENT_ENFORCE_SOURCES:-onnx}',
      // EV gate + sizing
      EV_GATE_MODE: '${EV_GATE_MODE:-shadow}',
      EV_GATE_EV_MIN: '${EV_GATE_EV_MIN:-0.02}',
      EV_GATE_EV_MIN_FLOOR: '${EV_GATE_EV_MIN_FLOOR:-0.01}',
      EV_GATE_ADVERSE_SELECTION_BPS: '${EV_GATE_ADVERSE_SELECTION_BPS:-1.5}',
      EV_GATE_MIN_SLIPPAGE_BPS: '${EV_GATE_MIN_SLIPPAGE_BPS:-0.5}',
      EV_GATE_MAX_BOOK_AGE_MS: '${EV_GATE_MAX_BOOK_AGE_MS:-250}',
      EV_GATE_MAX_SPREAD_AGE_MS: '${EV_GATE_MAX_SPREAD_AGE_MS:-250}',
      EV_GATE_MIN_STOP_DISTANCE_BPS: '${EV_GATE_MIN_STOP_DISTANCE_BPS:-5.0}',
      MIN_SIGNAL_STOP_DISTANCE_BPS: '${MIN_SIGNAL_STOP_DISTANCE_BPS:-}',
      MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL: '${MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL:-}',
      MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL_SESSION: '${MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL_SESSION:-}',
      MIN_SIGNAL_RR: '${MIN_SIGNAL_RR:-}',
      MIN_SIGNAL_RR_BY_SYMBOL: '${MIN_SIGNAL_RR_BY_SYMBOL:-}',
      MIN_SIGNAL_RR_BY_SYMBOL_SESSION: '${MIN_SIGNAL_RR_BY_SYMBOL_SESSION:-}',
      PARAM_MIN_STOP_LOSS_BPS: '${PARAM_MIN_STOP_LOSS_BPS:-20}',
      PARAM_MAX_STOP_LOSS_BPS: '${PARAM_MAX_STOP_LOSS_BPS:-80}',
      PARAM_MIN_TAKE_PROFIT_BPS: '${PARAM_MIN_TAKE_PROFIT_BPS:-35}',
      PARAM_MAX_TAKE_PROFIT_BPS: '${PARAM_MAX_TAKE_PROFIT_BPS:-140}',
      EV_GATE_P_MARGIN_UNCALIBRATED: '${EV_GATE_P_MARGIN_UNCALIBRATED:-0.02}',
      EV_GATE_MIN_RELIABILITY_SCORE: '${EV_GATE_MIN_RELIABILITY_SCORE:-0.6}',
      EV_GATE_MIN_EXPECTED_EDGE_BPS: '${EV_GATE_MIN_EXPECTED_EDGE_BPS:-0.0}',
      EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL: '${EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL:-}',
      EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SIDE: '${EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SIDE:-}',
      EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL_SIDE: '${EV_GATE_MIN_EXPECTED_EDGE_BPS_BY_SYMBOL_SIDE:-}',
      EV_GATE_MAX_EXCHANGE_LATENCY_MS: '${EV_GATE_MAX_EXCHANGE_LATENCY_MS:-500}',
      CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL: '${CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL:-}',
      CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL_SESSION: '${CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL_SESSION:-}',
      CANDIDATE_VETO_PREVENT_IMMEDIATE_INVALIDATION_ENTRY: '${CANDIDATE_VETO_PREVENT_IMMEDIATE_INVALIDATION_ENTRY:-true}',
      CANDIDATE_VETO_REQUIRE_GREEN_READINESS: '${CANDIDATE_VETO_REQUIRE_GREEN_READINESS:-false}',
      CANDIDATE_VETO_ENFORCE_SIDE_QUALITY_GATE: '${CANDIDATE_VETO_ENFORCE_SIDE_QUALITY_GATE:-true}',
      CANDIDATE_VETO_SIDE_QUALITY_FAIL_CLOSED: '${CANDIDATE_VETO_SIDE_QUALITY_FAIL_CLOSED:-false}',
      CANDIDATE_VETO_SIDE_QUALITY_MIN_SAMPLES: '${CANDIDATE_VETO_SIDE_QUALITY_MIN_SAMPLES:-100}',
      CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_LONG: '${CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_LONG:-0.50}',
      CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_SHORT: '${CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_SHORT:-0.50}',
      CANDIDATE_VETO_DISABLE_SHORT_ENTRIES: '${CANDIDATE_VETO_DISABLE_SHORT_ENTRIES:-false}',
      CANDIDATE_VETO_MIN_GROSS_EDGE_TO_COST_RATIO: '${CANDIDATE_VETO_MIN_GROSS_EDGE_TO_COST_RATIO:-1.0}',
      POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL: '${POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL:-}',
      POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL_SESSION: '${POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL_SESSION:-}',
      POC_MAGNET_LONG_ROTATION_MIN_BY_SYMBOL: '${POC_MAGNET_LONG_ROTATION_MIN_BY_SYMBOL:-}',
      POC_MAGNET_LONG_ROTATION_MIN_BY_SYMBOL_SESSION: '${POC_MAGNET_LONG_ROTATION_MIN_BY_SYMBOL_SESSION:-}',
      EV_SIZER_ENABLED: '${EV_SIZER_ENABLED:-true}',
      EV_SIZER_K: '${EV_SIZER_K:-2.0}',
      EV_SIZER_MIN_MULT: '${EV_SIZER_MIN_MULT:-0.5}',
      EV_SIZER_MAX_MULT: '${EV_SIZER_MAX_MULT:-1.25}',
      EV_SIZER_COST_ALPHA: '${EV_SIZER_COST_ALPHA:-0.5}',
      EV_SIZER_MIN_RELIABILITY_MULT: '${EV_SIZER_MIN_RELIABILITY_MULT:-0.8}',
      // Global gate
      GLOBAL_GATE_MIN_DEPTH_USD: '${GLOBAL_GATE_MIN_DEPTH_USD:-2000}',
      GLOBAL_GATE_MAX_SPREAD_BPS: '${GLOBAL_GATE_MAX_SPREAD_BPS:-30}',
      GLOBAL_GATE_SNAPSHOT_AGE_OK_MS: '${GLOBAL_GATE_SNAPSHOT_AGE_OK_MS:-2000}',
      GLOBAL_GATE_SNAPSHOT_AGE_REDUCE_MS: '${GLOBAL_GATE_SNAPSHOT_AGE_REDUCE_MS:-5000}',
      GLOBAL_GATE_SNAPSHOT_AGE_BLOCK_MS: '${GLOBAL_GATE_SNAPSHOT_AGE_BLOCK_MS:-10000}',
      GLOBAL_GATE_MAX_SPREAD_VS_TYPICAL: '${GLOBAL_GATE_MAX_SPREAD_VS_TYPICAL:-3.0}',
      GLOBAL_GATE_DEPTH_TYPICAL_MULT: '${GLOBAL_GATE_DEPTH_TYPICAL_MULT:-0.5}',
      GLOBAL_GATE_BLOCK_VOL_SHOCK: '${GLOBAL_GATE_BLOCK_VOL_SHOCK:-true}',
      // Cooldown
      COOLDOWN_ENTRY_SEC: '${COOLDOWN_ENTRY_SEC:-15}',
      COOLDOWN_EXIT_SEC: '${COOLDOWN_EXIT_SEC:-30}',
      COOLDOWN_SAME_DIRECTION_SEC: '${COOLDOWN_SAME_DIRECTION_SEC:-30}',
      COOLDOWN_MAX_ENTRIES_PER_HOUR: '${COOLDOWN_MAX_ENTRIES_PER_HOUR:-50}',
      // Cost data quality
      COST_DATA_QUALITY_ENABLED: '${COST_DATA_QUALITY_ENABLED:-false}',
      COST_DATA_QUALITY_MAX_SPREAD_AGE_MS: '${COST_DATA_QUALITY_MAX_SPREAD_AGE_MS:-500}',
      COST_DATA_QUALITY_MAX_BOOK_AGE_MS: '${COST_DATA_QUALITY_MAX_BOOK_AGE_MS:-500}',
      COST_DATA_QUALITY_REQUIRE_SLIPPAGE_MODEL: '${COST_DATA_QUALITY_REQUIRE_SLIPPAGE_MODEL:-false}',
      // Profile overrides (JSON string)
      PROFILE_OVERRIDES: '${PROFILE_OVERRIDES:-}',
      // Quality staleness thresholds - increased to handle throttled data rates
      QUALITY_TICK_STALE_SEC: '${QUALITY_TICK_STALE_SEC:-60.0}',
      QUALITY_TRADE_STALE_SEC: '${QUALITY_TRADE_STALE_SEC:-60.0}',
      QUALITY_ORDERBOOK_STALE_SEC: '${QUALITY_ORDERBOOK_STALE_SEC:-60.0}',
      QUALITY_GAP_WINDOW_SEC: '${QUALITY_GAP_WINDOW_SEC:-60.0}',
      TELEMETRY_ORDERBOOK_DB_INTERVAL_SEC: '${TELEMETRY_ORDERBOOK_DB_INTERVAL_SEC:-1.0}',
      TELEMETRY_DECISION_DB_INTERVAL_SEC: '${TELEMETRY_DECISION_DB_INTERVAL_SEC:-0.25}',
      TELEMETRY_PREDICTION_DB_INTERVAL_SEC: '${TELEMETRY_PREDICTION_DB_INTERVAL_SEC:-0.50}',
    },
    error_file: '/tmp/${RUNTIME_NAME}-error.log',
    out_file: '/tmp/${RUNTIME_NAME}-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    merge_logs: true,
    kill_timeout: 10000
  }]
};
EOF

# Start exchange execution reconciliation worker (durable trade history sync).
cat > "$RECONCILE_CONFIG_FILE" << EOF
module.exports = {
  apps: [{
    name: '${RECONCILE_NAME}',
    script: '${PYTHON_PATH}',
    args: '-m quantgambit.execution.execution_reconcile_worker',
    cwd: '${PROJECT_ROOT}/quantgambit-python',
    interpreter: 'none',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '512M',
    env: {
      ...process.env,
      PYTHONPATH: '${PROJECT_ROOT}/quantgambit-python',
      LAUNCH_RUNTIME_CONTRACT_VERSION: '${LAUNCH_RUNTIME_CONTRACT_VERSION}',
      LAUNCH_RUNTIME_CONTRACT_HASH: '${LAUNCH_RUNTIME_CONTRACT_HASH}',
      REDIS_URL: '${REDIS_URL_VALUE}',
      BOT_REDIS_URL: '${BOT_REDIS_URL_VALUE}',
      REDIS_HOST: '${REDIS_HOST}',
      REDIS_PORT: '${REDIS_PORT}',
      BOT_TIMESCALE_URL: '${BOT_TIMESCALE_URL_VALUE}',
      TENANT_ID: '${TENANT_ID}',
      BOT_ID: '${BOT_ID}',
      ACTIVE_EXCHANGE: '${ACTIVE_EXCHANGE}',
      ORDERBOOK_SYMBOLS: '${ORDERBOOK_SYMBOLS}',
      EXCHANGE_SECRET_ID: '${EXCHANGE_SECRET_ID:-}',
      BYBIT_TESTNET: '${BYBIT_TESTNET:-${ORDERBOOK_TESTNET:-false}}',
      BYBIT_DEMO: '${BYBIT_DEMO:-${ORDER_UPDATES_DEMO:-false}}',
      EXECUTION_RECONCILE_ENABLED: '${EXECUTION_RECONCILE_ENABLED:-true}',
      EXECUTION_RECONCILE_INTERVAL_SEC: '${EXECUTION_RECONCILE_INTERVAL_SEC:-30}',
      EXECUTION_RECONCILE_LOOKBACK_SEC: '${EXECUTION_RECONCILE_LOOKBACK_SEC:-3600}',
      EXECUTION_RECONCILE_OVERLAP_SEC: '${EXECUTION_RECONCILE_OVERLAP_SEC:-30}',
      EXECUTION_RECONCILE_LIMIT: '${EXECUTION_RECONCILE_LIMIT:-200}',
      EXECUTION_RECONCILE_MAX_PAGES: '${EXECUTION_RECONCILE_MAX_PAGES:-10}',
      EXECUTION_RECONCILE_WRITE_ORDER_EVENTS: '${EXECUTION_RECONCILE_WRITE_ORDER_EVENTS:-true}',
      BYBIT_V5_CATEGORY: '${BYBIT_V5_CATEGORY:-linear}'
    },
    error_file: '/tmp/${RECONCILE_NAME}-error.log',
    out_file: '/tmp/${RECONCILE_NAME}-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    merge_logs: true,
    kill_timeout: 10000
  }]
};
EOF

# Start using the generated config file
echo "[launch-runtime] contract_hash=${LAUNCH_RUNTIME_CONTRACT_HASH} version=${LAUNCH_RUNTIME_CONTRACT_VERSION} tenant=${TENANT_ID} bot=${BOT_ID} exchange=${ACTIVE_EXCHANGE} mode=${TRADING_MODE} market=${MARKET_TYPE}"

start_or_restart_pm2_app() {
    local config_file="$1"
    local app_name="$2"
    if $PM2 describe "$app_name" >/dev/null 2>&1; then
        $PM2 startOrRestart "$config_file" --only "$app_name"
    else
        $PM2 start "$config_file" --only "$app_name"
    fi
}

start_or_restart_pm2_app "$RECONCILE_CONFIG_FILE" "$RECONCILE_NAME"
start_or_restart_pm2_app "$CONFIG_FILE" "$RUNTIME_NAME"

# Clean up config file after start
rm -f "$CONFIG_FILE"
rm -f "$RECONCILE_CONFIG_FILE"

echo "Runtime $RUNTIME_NAME launched successfully"
