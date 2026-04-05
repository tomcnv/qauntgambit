#!/usr/bin/env python3
"""Auto-rollback latest ONNX model when live score snapshot degrades persistently."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import redis


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _build_snapshot_key(tenant_id: str, bot_id: str) -> str:
    return f"quantgambit:{tenant_id}:{bot_id}:prediction:score:latest"


def _build_state_key(tenant_id: str, bot_id: str) -> str:
    return f"quantgambit:{tenant_id}:{bot_id}:prediction:rollback_guard:state"


def _guess_active_config_artifact(registry: Path, latest_payload: dict) -> str | None:
    if not latest_payload:
        return None
    latest_metrics = latest_payload.get("metrics") or {}
    latest_samples = latest_payload.get("samples") or {}
    latest_contract = str(latest_payload.get("prediction_contract") or "")
    candidates = sorted(registry.glob("prediction_baseline_*.json"), reverse=True)
    for candidate in candidates:
        payload = _load_json(candidate)
        if not payload:
            continue
        metrics = payload.get("metrics") or {}
        samples = payload.get("samples") or {}
        contract = str(payload.get("prediction_contract") or "")
        if (
            _safe_float(metrics.get("accuracy"), -1.0) == _safe_float(latest_metrics.get("accuracy"), -2.0)
            and int(samples.get("total") or -1) == int(latest_samples.get("total") or -2)
            and contract == latest_contract
        ):
            return candidate.name
    return None


def _guess_previous_pair(registry: Path, current_config_name: str | None) -> tuple[str | None, str | None]:
    candidates = sorted(registry.glob("prediction_baseline_*.json"), reverse=True)
    if not candidates:
        return None, None
    current_name = str(current_config_name or "").strip()
    for candidate in candidates:
        if candidate.name == current_name:
            continue
        model_name = candidate.with_suffix(".onnx").name
        if (registry / model_name).exists():
            return model_name, candidate.name
    return None, None


def _ensure_pointer_previous_populated(registry: Path, pointer_path: Path, pointer: dict) -> dict:
    current = pointer.get("current") if isinstance(pointer.get("current"), dict) else {}
    previous = pointer.get("previous") if isinstance(pointer.get("previous"), dict) else {}
    prev_model = previous.get("model")
    prev_config = previous.get("config")
    if prev_model and prev_config:
        return pointer

    current_config = current.get("config")
    guessed_prev_model, guessed_prev_config = _guess_previous_pair(registry, current_config)
    if not guessed_prev_model or not guessed_prev_config:
        return pointer

    pointer["updated_at"] = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    pointer["previous"] = {"model": guessed_prev_model, "config": guessed_prev_config}
    _write_json(pointer_path, pointer)
    return pointer


def _bootstrap_pointer_if_missing(registry: Path, pointer_path: Path) -> dict:
    pointer = _load_json(pointer_path)
    if pointer:
        return _ensure_pointer_previous_populated(registry, pointer_path, pointer)
    latest_payload = _load_json(registry / "latest.json")
    guessed_config = _guess_active_config_artifact(registry, latest_payload)
    guessed_model = guessed_config.replace(".json", ".onnx") if guessed_config else None
    pointer = {
        "updated_at": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "current": {"model": guessed_model, "config": guessed_config},
        "previous": {"model": None, "config": None},
    }
    pointer = _ensure_pointer_previous_populated(registry, pointer_path, pointer)
    _write_json(pointer_path, pointer)
    return pointer


def _evaluate_breach(
    snapshot: dict,
    symbols_filter: set[str],
    min_symbol_samples: int,
    min_ml_score: float | None,
    min_exact_accuracy: float | None,
    max_ece_top1: float | None,
    min_avg_realized_bps: float | None,
) -> tuple[bool, list[dict]]:
    symbols = snapshot.get("symbols") or {}
    if not isinstance(symbols, dict) or not symbols:
        return False, []
    breaches: list[dict] = []
    for symbol, payload in symbols.items():
        symbol_u = str(symbol).upper()
        if symbols_filter and symbol_u not in symbols_filter:
            continue
        meta = payload if isinstance(payload, dict) else {}
        samples = int(_safe_float(meta.get("samples"), 0) or 0)
        if samples < int(min_symbol_samples):
            continue
        status = str(meta.get("status") or "")
        ml_score = _safe_float(meta.get("ml_score"))
        exact_acc = _safe_float(meta.get("exact_accuracy"))
        ece = _safe_float(meta.get("ece_top1"))
        avg_realized_bps = _safe_float(meta.get("avg_realized_bps"))
        reason: list[str] = []
        if status == "blocked":
            reason.append("snapshot_blocked")
        if min_ml_score is not None and ml_score is not None and ml_score < min_ml_score:
            reason.append(f"ml_score<{min_ml_score:g}")
        if min_exact_accuracy is not None and exact_acc is not None and exact_acc < min_exact_accuracy:
            reason.append(f"exact_accuracy<{min_exact_accuracy:g}")
        if max_ece_top1 is not None and ece is not None and ece > max_ece_top1:
            reason.append(f"ece_top1>{max_ece_top1:g}")
        if min_avg_realized_bps is not None and avg_realized_bps is not None and avg_realized_bps < min_avg_realized_bps:
            reason.append(f"avg_realized_bps<{min_avg_realized_bps:g}")
        if reason:
            breaches.append(
                {
                    "symbol": symbol_u,
                    "samples": samples,
                    "status": status,
                    "ml_score": ml_score,
                    "exact_accuracy": exact_acc,
                    "ece_top1": ece,
                    "avg_realized_bps": avg_realized_bps,
                    "reasons": reason,
                }
            )
    return (len(breaches) > 0), breaches


def _rollback_to_previous(registry: Path, pointer: dict, now_ts: float) -> tuple[bool, str]:
    current = pointer.get("current") or {}
    previous = pointer.get("previous") or {}
    prev_model = previous.get("model")
    prev_config = previous.get("config")
    if not prev_model or not prev_config:
        return False, "missing_previous_pointer"

    prev_model_path = registry / str(prev_model)
    prev_config_path = registry / str(prev_config)
    latest_model_path = registry / "latest.onnx"
    latest_json_path = registry / "latest.json"
    if not prev_model_path.exists() or not prev_config_path.exists():
        return False, "previous_artifacts_missing"

    backup_path = registry / f"latest.json.rollback_backup.{int(now_ts)}"
    if latest_json_path.exists():
        shutil.copy2(latest_json_path, backup_path)

    shutil.copy2(prev_model_path, latest_model_path)
    payload = _load_json(prev_config_path)
    payload["onnx_path"] = "models/registry/latest.onnx"
    promotion = payload.get("promotion") if isinstance(payload.get("promotion"), dict) else {}
    promotion.update(
        {
            "rollback_applied_at": now_ts,
            "rollback_from_model_file": current.get("model"),
            "rollback_from_config_file": current.get("config"),
        }
    )
    payload["promotion"] = promotion
    _write_json(latest_json_path, payload)

    pointer["updated_at"] = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now_ts))
    pointer["current"] = {"model": prev_model, "config": prev_config}
    pointer["previous"] = {"model": current.get("model"), "config": current.get("config")}
    _write_json(registry / "latest_pointer.json", pointer)
    return True, "rollback_applied"


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-rollback ONNX model on persistent live-score degradation.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--registry", default="quantgambit-python/models/registry")
    parser.add_argument("--redis-url", default="redis://localhost:6379")
    parser.add_argument("--snapshot-key", default="")
    parser.add_argument("--state-key", default="")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols to monitor.")
    parser.add_argument("--min-symbol-samples", type=int, default=120)
    parser.add_argument("--max-snapshot-age-sec", type=float, default=1200.0)
    parser.add_argument("--max-consecutive-breaches", type=int, default=3)
    parser.add_argument("--cooldown-sec", type=int, default=1800)
    parser.add_argument("--state-ttl-sec", type=int, default=604800)
    parser.add_argument("--min-ml-score", type=float, default=None)
    parser.add_argument("--min-exact-accuracy", type=float, default=None)
    parser.add_argument("--max-ece-top1", type=float, default=None)
    parser.add_argument("--min-avg-realized-bps", type=float, default=None)
    parser.add_argument("--restart-runtime", action="store_true")
    parser.add_argument("--runtime-process-name", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now_ts = time.time()
    registry = Path(args.registry).resolve()
    pointer_path = registry / "latest_pointer.json"
    pointer = _bootstrap_pointer_if_missing(registry, pointer_path)

    snapshot_key = args.snapshot_key.strip() or _build_snapshot_key(args.tenant_id, args.bot_id)
    state_key = args.state_key.strip() or _build_state_key(args.tenant_id, args.bot_id)
    symbols_filter = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    snapshot_raw = client.get(snapshot_key)
    if not snapshot_raw:
        print(json.dumps({"ok": True, "action": "noop", "reason": "missing_snapshot", "snapshot_key": snapshot_key}))
        return 0
    try:
        snapshot = json.loads(snapshot_raw)
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "reason": "invalid_snapshot_json", "snapshot_key": snapshot_key}))
        return 3

    snapshot_ts = _safe_float(snapshot.get("timestamp"), 0.0) or 0.0
    if snapshot_ts <= 0 or (now_ts - snapshot_ts) > float(args.max_snapshot_age_sec):
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": "noop",
                    "reason": "stale_snapshot",
                    "snapshot_age_sec": now_ts - snapshot_ts if snapshot_ts > 0 else None,
                }
            )
        )
        return 0

    breached, breach_details = _evaluate_breach(
        snapshot=snapshot,
        symbols_filter=symbols_filter,
        min_symbol_samples=args.min_symbol_samples,
        min_ml_score=args.min_ml_score,
        min_exact_accuracy=args.min_exact_accuracy,
        max_ece_top1=args.max_ece_top1,
        min_avg_realized_bps=args.min_avg_realized_bps,
    )
    state = {}
    state_raw = client.get(state_key)
    if state_raw:
        try:
            state = json.loads(state_raw)
        except json.JSONDecodeError:
            state = {}
    last_snapshot_ts = _safe_float(state.get("last_snapshot_ts"), 0.0) or 0.0
    consecutive = int(_safe_float(state.get("consecutive_breaches"), 0) or 0)
    last_rollback_ts = _safe_float(state.get("last_rollback_ts"), 0.0) or 0.0

    if not breached:
        state.update(
            {
                "last_snapshot_ts": snapshot_ts,
                "consecutive_breaches": 0,
                "last_checked_at": now_ts,
                "last_status": "ok",
                "last_breach_details": [],
            }
        )
        client.set(state_key, json.dumps(state, allow_nan=False), ex=max(60, int(args.state_ttl_sec)))
        print(json.dumps({"ok": True, "action": "noop", "reason": "no_breach", "snapshot_ts": snapshot_ts}))
        return 0

    if snapshot_ts > last_snapshot_ts:
        consecutive += 1
    if snapshot_ts == last_snapshot_ts and consecutive <= 0:
        consecutive = 1

    state.update(
        {
            "last_snapshot_ts": snapshot_ts,
            "consecutive_breaches": consecutive,
            "last_checked_at": now_ts,
            "last_status": "breach",
            "last_breach_details": breach_details,
        }
    )

    if consecutive < int(args.max_consecutive_breaches):
        client.set(state_key, json.dumps(state, allow_nan=False), ex=max(60, int(args.state_ttl_sec)))
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": "wait",
                    "reason": "breach_below_threshold",
                    "consecutive_breaches": consecutive,
                    "required_breaches": int(args.max_consecutive_breaches),
                    "breaches": breach_details,
                }
            )
        )
        return 0

    if last_rollback_ts > 0 and (now_ts - last_rollback_ts) < int(args.cooldown_sec):
        state["last_status"] = "cooldown"
        client.set(state_key, json.dumps(state, allow_nan=False), ex=max(60, int(args.state_ttl_sec)))
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": "noop",
                    "reason": "cooldown_active",
                    "cooldown_remaining_sec": int(args.cooldown_sec) - int(now_ts - last_rollback_ts),
                    "breaches": breach_details,
                }
            )
        )
        return 0

    if args.dry_run:
        state["last_status"] = "dry_run_triggered"
        client.set(state_key, json.dumps(state, allow_nan=False), ex=max(60, int(args.state_ttl_sec)))
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": "dry_run_rollback",
                    "consecutive_breaches": consecutive,
                    "breaches": breach_details,
                }
            )
        )
        return 0

    ok, reason = _rollback_to_previous(registry, pointer, now_ts)
    state["last_status"] = "rolled_back" if ok else "rollback_failed"
    state["last_rollback_reason"] = reason
    state["last_rollback_ts"] = now_ts if ok else last_rollback_ts
    state["consecutive_breaches"] = 0 if ok else consecutive
    client.set(state_key, json.dumps(state, allow_nan=False), ex=max(60, int(args.state_ttl_sec)))

    restart_result = None
    if ok and args.restart_runtime:
        process_name = args.runtime_process_name.strip() or f"runtime-{args.tenant_id}-{args.bot_id}"
        try:
            proc = subprocess.run(
                ["pm2", "restart", process_name],
                check=False,
                capture_output=True,
                text=True,
            )
            restart_result = {
                "process": process_name,
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "").strip()[-600:],
                "stderr": (proc.stderr or "").strip()[-600:],
            }
        except Exception as exc:  # pragma: no cover
            restart_result = {"process": process_name, "error": str(exc)}

    print(
        json.dumps(
            {
                "ok": bool(ok),
                "action": "rollback" if ok else "rollback_failed",
                "reason": reason,
                "consecutive_breaches": consecutive,
                "breaches": breach_details,
                "restart": restart_result,
            },
            allow_nan=False,
        )
    )
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
