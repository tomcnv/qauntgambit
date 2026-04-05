#!/usr/bin/env python3
"""Guarded re-optimization controller.

Workflow:
1) Require minimum new close samples since last run.
2) Run tighter-jitter optimization from executed closes.
3) Apply only if improvement and side-safety checks pass.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg


ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "quantgambit-python" / "outputs" / "guarded_reopt_state.json"

OPT_SCRIPT = ROOT / "quantgambit-python" / "scripts" / "optimize_env_from_executed_trades.py"
PYTHON = ROOT / "quantgambit-python" / "venv" / "bin" / "python"


def _read_dotenv(key: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


async def _count_close_rows(db_url: str, tenant_id: str, bot_id: str, since: datetime) -> int:
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2, timeout=10.0)
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM order_events
                WHERE tenant_id=$1 AND bot_id=$2
                  AND LOWER(COALESCE(payload->>'status',''))='filled'
                  AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                  AND ts >= $3
                """,
                tenant_id,
                bot_id,
                since,
            )
            return int(n or 0)
    finally:
        await pool.close()


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _apply_env_fragment(env_fragment: Path, target_env: Path) -> None:
    if not env_fragment.exists():
        raise RuntimeError(f"missing env fragment: {env_fragment}")
    updates: dict[str, str] = {}
    for line in env_fragment.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        updates[k.strip()] = v.strip()

    lines = target_env.read_text(encoding="utf-8").splitlines()
    replaced: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                replaced.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in replaced:
            out.append(f"{k}={v}")
    target_env.write_text("\n".join(out) + "\n", encoding="utf-8")


def _restart_runtime() -> None:
    cmd = [
        str(ROOT / "scripts" / "launch-runtime.sh"),
    ]
    env = os.environ.copy()
    env["TENANT_ID"] = env.get("TENANT_ID") or _read_dotenv("TENANT_ID") or "11111111-1111-1111-1111-111111111111"
    env["BOT_ID"] = env.get("BOT_ID") or _read_dotenv("BOT_ID") or "bf167763-fee1-4f11-ab9a-6fddadf125de"
    env["REFRESH_RUNTIME"] = "true"
    subprocess.run(cmd, check=True, cwd=str(ROOT), env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded optimizer and apply flow.")
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument("--min-new-closes", type=int, default=25)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--min-trades", type=int, default=40)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--jitter-scale", type=float, default=0.5)
    parser.add_argument("--min-improvement", type=float, default=20.0)
    parser.add_argument("--max-side-net-degradation", type=float, default=80.0)
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID", "11111111-1111-1111-1111-111111111111"))
    parser.add_argument("--bot-id", default=os.getenv("BOT_ID", "bf167763-fee1-4f11-ab9a-6fddadf125de"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_url = os.getenv("BOT_TIMESCALE_URL") or _read_dotenv("BOT_TIMESCALE_URL")
    if not db_url:
        raise SystemExit("BOT_TIMESCALE_URL missing")

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    current_close_count = __import__("asyncio").run(_count_close_rows(db_url, args.tenant_id, args.bot_id, since))
    state = _load_state()
    prev_count = int(state.get("last_close_count", 0))
    new_closes = max(0, current_close_count - prev_count)

    if prev_count > 0 and new_closes < args.min_new_closes:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "not_enough_new_closes",
                    "current_close_count": current_close_count,
                    "previous_close_count": prev_count,
                    "new_closes": new_closes,
                    "required_new_closes": args.min_new_closes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    out_env = ROOT / "quantgambit-python" / "outputs" / "optimized.guarded.env"
    out_json = ROOT / "quantgambit-python" / "outputs" / "optimization_guarded.json"
    cmd = [
        str(PYTHON),
        str(OPT_SCRIPT),
        "--hours",
        str(args.hours),
        "--iterations",
        str(args.iterations),
        "--min-trades",
        str(args.min_trades),
        "--folds",
        str(args.folds),
        "--jitter-scale",
        str(args.jitter_scale),
        "--tenant-id",
        args.tenant_id,
        "--bot-id",
        args.bot_id,
        "--output-env",
        str(out_env),
        "--output-json",
        str(out_json),
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT / "quantgambit-python"))
    report = json.loads(out_json.read_text(encoding="utf-8"))
    best = report.get("best") or {}
    baseline = report.get("baseline") or {}

    best_score = float(best.get("score") or 0.0)
    baseline_score = float(baseline.get("score") or 0.0)
    improvement = best_score - baseline_score

    best_sides = (best.get("side_breakdown") or {})
    base_sides = (baseline.get("side_breakdown") or {})
    worst_side_degradation = 0.0
    for side in ("buy", "sell"):
        b = float((best_sides.get(side) or {}).get("sum_net") or 0.0)
        a = float((base_sides.get(side) or {}).get("sum_net") or 0.0)
        deg = a - b
        if deg > worst_side_degradation:
            worst_side_degradation = deg

    passes = improvement >= args.min_improvement and worst_side_degradation <= args.max_side_net_degradation
    result = {
        "status": "pass" if passes else "fail",
        "improvement": improvement,
        "best_score": best_score,
        "baseline_score": baseline_score,
        "worst_side_degradation": worst_side_degradation,
        "thresholds": {
            "min_improvement": args.min_improvement,
            "max_side_net_degradation": args.max_side_net_degradation,
        },
        "best_knobs": best.get("knobs"),
        "new_closes": new_closes,
        "current_close_count": current_close_count,
    }

    if passes and args.apply:
        _apply_env_fragment(out_env, ROOT / ".env")
        _restart_runtime()
        result["applied"] = True
    else:
        result["applied"] = False

    state.update(
        {
            "last_close_count": current_close_count,
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_result": result,
        }
    )
    _save_state(state)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
