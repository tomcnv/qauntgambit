#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="${ROOT_DIR}/venv/bin/python"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "venv python not found at ${PY_BIN}" >&2
  exit 1
fi

TENANT_ID="${TENANT_ID:-11111111-1111-1111-1111-111111111111}"
BOT_ID="${BOT_ID:-bf167763-fee1-4f11-ab9a-6fddadf125de}"

"${PY_BIN}" "${ROOT_DIR}/scripts/prediction_error_audit_job.py" \
  --tenant-id "${TENANT_ID}" \
  --bot-id "${BOT_ID}" \
  "$@"

