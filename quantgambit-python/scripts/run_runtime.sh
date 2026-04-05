#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "${ROOT}/venv311/bin/activate"
set -a
source "${ROOT}/.env"
set +a
export PYTHONPATH="${ROOT}"

exec python -m quantgambit.runtime.entrypoint
