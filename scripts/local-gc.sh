#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/local-gc.log"

mkdir -p "${LOG_DIR}"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting local GC"
  cd "${ROOT_DIR}"
  quantgambit-python/venv/bin/python scripts/add_db_retention_policies.py --profile local --apply-non-hypertable-cleanup
  bash scripts/docker-safe-gc.sh
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Local GC complete"
  echo
} >> "${LOG_FILE}" 2>&1
