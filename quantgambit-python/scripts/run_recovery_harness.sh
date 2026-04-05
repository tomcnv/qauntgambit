#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(dirname "$0")/.."
if [[ -x "$BASE_DIR/venv311/bin/python" ]]; then
  VENV_PYTHON="$BASE_DIR/venv311/bin/python"
else
  VENV_PYTHON="$BASE_DIR/venv/bin/python"
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "venv not found at: $VENV_PYTHON" >&2
  echo "Create it first with: python3.11 -m venv quantgambit-python/venv311" >&2
  exit 1
fi

REAL_SERVICES=1 PYTHONPATH="$BASE_DIR" "$VENV_PYTHON" -m pytest \
  quantgambit/tests/integration/test_runtime_recovery_real_services.py -vv
