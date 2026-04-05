#!/usr/bin/env bash
set -euo pipefail

# Load platform and bot schemas into the mini-b stack.
# Uses .env values from this directory if present.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +a
fi

PLATFORM_HOST="${PLATFORM_HOST:-${PLATFORM_DB_HOST:-${DB_HOST:-localhost}}}"
PLATFORM_PORT="${PLATFORM_DB_PORT:-5432}"
PLATFORM_USER="${PLATFORM_DB_USER:-platform}"
PLATFORM_PASS="${PLATFORM_DB_PASSWORD:-platform_pw}"
PLATFORM_DB="${PLATFORM_DB_NAME:-platform_db}"

BOT_HOST="${BOT_HOST:-${BOT_DB_HOST:-localhost}}"
BOT_PORT="${BOT_DB_PORT:-5433}"
BOT_USER="${BOT_DB_USER:-quantgambit}"
BOT_PASS="${BOT_DB_PASSWORD:-quantgambit_pw}"
BOT_DB="${BOT_DB_NAME:-quantgambit_bot}"

QL_DIR="${PROJECT_ROOT}/quantgambit-python/docs/sql"

echo "Loading platform schema into ${PLATFORM_DB}@${PLATFORM_HOST}:${PLATFORM_PORT}..."
PGPASSWORD="${PLATFORM_PASS}" psql -h "${PLATFORM_HOST}" -p "${PLATFORM_PORT}" -U "${PLATFORM_USER}" -d "${PLATFORM_DB}" -v ON_ERROR_STOP=1 -f "${QL_DIR}/dashboard.sql"

echo "Loading bot schema into ${BOT_DB}@${BOT_HOST}:${BOT_PORT}..."
PGPASSWORD="${BOT_PASS}" psql -h "${BOT_HOST}" -p "${BOT_PORT}" -U "${BOT_USER}" -d "${BOT_DB}" -v ON_ERROR_STOP=1 -f "${QL_DIR}/bot_configs.sql"
PGPASSWORD="${BOT_PASS}" psql -h "${BOT_HOST}" -p "${BOT_PORT}" -U "${BOT_USER}" -d "${BOT_DB}" -v ON_ERROR_STOP=1 -f "${QL_DIR}/orders.sql"
PGPASSWORD="${BOT_PASS}" psql -h "${BOT_HOST}" -p "${BOT_PORT}" -U "${BOT_USER}" -d "${BOT_DB}" -v ON_ERROR_STOP=1 -f "${QL_DIR}/telemetry.sql"

echo "Done."
