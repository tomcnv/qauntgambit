#!/usr/bin/env python3
"""Reconcile local platform/quant databases before starting services.

Authoritative executors remain:
- scripts/apply_local_schemas.py
- deeptrader-backend/run_all_migrations.sh
- quantgambit-python/scripts/run_migrations.py
- scripts/preflight_local_stack.py

This script only orchestrates them in the correct local startup order.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: Path | None = None, label: str) -> None:
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")


def _resolve_bot_python() -> Path:
    candidates = (
        ROOT / "quantgambit-python" / "venv" / "bin" / "python",
        ROOT / "quantgambit-python" / "venv311" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise RuntimeError(
        "bot python venv not found in quantgambit-python/venv or quantgambit-python/venv311"
    )


def reconcile_local_databases() -> None:
    _run(
        ["python3", str(ROOT / "scripts" / "apply_local_schemas.py")],
        cwd=ROOT,
        label="local schema bootstrap",
    )
    _run(
        ["./run_all_migrations.sh"],
        cwd=ROOT / "deeptrader-backend",
        label="platform migrations",
    )
    _run(
        [str(_resolve_bot_python()), "scripts/run_migrations.py"],
        cwd=ROOT / "quantgambit-python",
        label="quant migrations",
    )
    _run(
        ["python3", str(ROOT / "scripts" / "preflight_local_stack.py")],
        cwd=ROOT,
        label="local schema preflight",
    )


def main() -> int:
    try:
        reconcile_local_databases()
    except Exception as exc:
        sys.stderr.write(f"reconcile_local_databases failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
