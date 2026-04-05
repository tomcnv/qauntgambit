#!/usr/bin/env python3
"""
Continuously calibrate ONNX metadata and evaluate shadow score gates until pass.

This loop is useful for unattended calibration attempts during live/shadow runs.
It supports:
  - default model calibration (no expert id)
  - per-expert calibration for MoE metadata
  - optional runtime restart + warmup between attempts
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from typing import Any


_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RETRYABLE_FAILURE_KINDS = {
    "unstable_params",
    "no_improvement",
    "class_imbalance",
    "insufficient_eval_samples",
    "insufficient_samples",
    "no_calibration_fitted",
}
_NON_RETRYABLE_MARKERS = {
    "model_meta_not_found",
    "expert_not_found",
    "expert_targets_not_found_in_meta",
    "expert_targets_requested_but_no_experts_in_meta",
    "model_path_missing",
    "onnx_prediction_model_missing",
    "fallback_dataset_missing",
    "fallback_dataset_invalid",
}


def _run_command(command: list[str], *, cwd: pathlib.Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _extract_json_objects(raw: str) -> list[Any]:
    decoder = json.JSONDecoder()
    out: list[Any] = []
    idx = 0
    length = len(raw)
    while idx < length:
        start = raw.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(raw[start:])
            out.append(obj)
            idx = start + end
        except json.JSONDecodeError:
            idx = start + 1
    return out


def _last_json_dict(raw: str) -> dict[str, Any] | None:
    for item in reversed(_extract_json_objects(raw)):
        if isinstance(item, dict):
            return item
    return None


def _classify_calibration_failure(item: dict[str, Any], stdout: str, stderr: str) -> dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    reason = str(payload.get("reason") or "")
    failure_kind = str(payload.get("failure_kind") or "")
    status = str(payload.get("status") or "")
    retryable_raw = payload.get("retryable")
    combined = f"{stdout}\n{stderr}".lower()

    if isinstance(retryable_raw, bool):
        retryable = retryable_raw
    elif failure_kind in _RETRYABLE_FAILURE_KINDS or reason in _RETRYABLE_FAILURE_KINDS:
        retryable = True
    else:
        retryable = False

    marker = next((m for m in _NON_RETRYABLE_MARKERS if m in combined), None)
    if marker is not None:
        retryable = False
        if not reason:
            reason = marker
        if not failure_kind:
            failure_kind = marker
    if not reason and "no_calibration_fitted" in combined:
        reason = "no_calibration_fitted"
    if not failure_kind and reason:
        failure_kind = reason
    if not status:
        status = "failed"
    return {
        "status": status,
        "reason": reason or "unknown_failure",
        "failure_kind": failure_kind or "unknown",
        "retryable": bool(retryable),
    }


def _resolve_targets(
    model_meta: pathlib.Path,
    expert_ids_csv: str,
    all_experts: bool,
) -> list[str | None]:
    explicit = [item.strip() for item in (expert_ids_csv or "").split(",") if item.strip()]
    if explicit:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in explicit:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped
    if all_experts:
        payload = json.loads(model_meta.read_text(encoding="utf-8"))
        experts = payload.get("experts")
        if not isinstance(experts, list):
            return []
        ids: list[str] = []
        for item in experts:
            if not isinstance(item, dict):
                continue
            expert_id = str(item.get("id") or "").strip()
            if expert_id:
                ids.append(expert_id)
        return ids
    return [None]


def _resolve_model_meta_path(raw: str) -> pathlib.Path:
    path = pathlib.Path(raw or "")
    if path.is_absolute():
        return path
    candidate = (_ROOT / path).resolve()
    if candidate.exists():
        return candidate
    return path.resolve()


def _load_meta_payload(model_meta: pathlib.Path) -> dict[str, Any]:
    payload = json.loads(model_meta.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _list_expert_ids(meta_payload: dict[str, Any]) -> list[str]:
    experts = meta_payload.get("experts")
    if not isinstance(experts, list):
        return []
    ids: list[str] = []
    for item in experts:
        if not isinstance(item, dict):
            continue
        expert_id = str(item.get("id") or "").strip()
        if expert_id:
            ids.append(expert_id)
    return ids


def _resolve_expert_fallback_dataset(meta_payload: dict[str, Any], expert_id: str | None) -> str | None:
    if not expert_id:
        return None
    experts = meta_payload.get("experts")
    if not isinstance(experts, list):
        return None
    selected: dict[str, Any] | None = None
    for item in experts:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() == str(expert_id):
            selected = item
            break
    if selected is None:
        return None
    candidates: list[str] = []
    meta = selected.get("meta")
    if isinstance(meta, dict):
        candidates.append(str(meta.get("trained_from_dataset") or ""))
    calibration = selected.get("probability_calibration")
    if isinstance(calibration, dict):
        candidates.append(str(calibration.get("dataset") or ""))
        selection = calibration.get("selection")
        if isinstance(selection, dict):
            candidates.append(str(selection.get("fallback_dataset") or ""))
    for raw in candidates:
        raw = str(raw or "").strip()
        if not raw:
            continue
        path = pathlib.Path(raw)
        if not path.is_absolute():
            path = (_ROOT / path).resolve()
        if path.exists():
            return str(path)
    return None


def _validate_targets_against_meta(
    meta_payload: dict[str, Any],
    targets: list[str | None],
    *,
    expert_ids_csv: str,
    all_experts: bool,
) -> tuple[bool, str | None]:
    requested_experts = bool((expert_ids_csv or "").strip()) or bool(all_experts)
    if not requested_experts:
        return True, None
    configured = set(_list_expert_ids(meta_payload))
    if not configured:
        return False, "expert_targets_requested_but_no_experts_in_meta"
    requested = [str(t).strip() for t in targets if t]
    missing = [item for item in requested if item not in configured]
    if missing:
        return False, f"expert_targets_not_found_in_meta:{','.join(sorted(set(missing)))}"
    return True, None


def _select_expert_meta_fallback(model_meta: pathlib.Path) -> pathlib.Path | None:
    parent = model_meta.parent
    candidates = [
        item
        for item in parent.glob("latest.json*")
        if item.is_file() and item.resolve() != model_meta.resolve()
    ]
    # Prefer most recently modified candidate first.
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            payload = _load_meta_payload(candidate)
        except Exception:
            continue
        if _list_expert_ids(payload):
            return candidate.resolve()
    return None


def _default_runtime_process(tenant_id: str, bot_id: str) -> str:
    return f"runtime-{tenant_id}-{bot_id}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-meta", default="models/registry/latest.json")
    parser.add_argument("--model-path", default="", help="Optional ONNX path override for calibration.")
    parser.add_argument("--expert-ids", default="", help="Comma-separated expert ids to calibrate.")
    parser.add_argument(
        "--all-experts",
        action="store_true",
        help="Calibrate every expert in model metadata.",
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--redis-url", default="redis://localhost:6379")
    parser.add_argument("--stream", default="events:features")
    parser.add_argument("--sleep-sec", type=float, default=30.0)
    parser.add_argument("--warmup-sec", type=float, default=60.0)
    parser.add_argument("--max-iterations", type=int, default=40)
    parser.add_argument(
        "--max-runtime-sec",
        type=float,
        default=0.0,
        help="Overall loop timeout in seconds (0 disables timeout).",
    )
    parser.add_argument(
        "--restart-runtime",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Restart runtime process between attempts so new calibration is loaded.",
    )
    parser.add_argument(
        "--runtime-process-name",
        default="",
        help="PM2 runtime process name override.",
    )
    parser.add_argument(
        "--stop-on-calibration-error",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Stop immediately if any calibration command fails.",
    )
    parser.add_argument("--live-from-stream", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--tail-count", type=int, default=50000)
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--horizon-sec", type=float, default=60.0)
    parser.add_argument("--up-threshold", type=float, default=0.001)
    parser.add_argument("--down-threshold", type=float, default=-0.001)
    parser.add_argument("--label-source", default="future_return")
    parser.add_argument("--score-hours", type=float, default=0.15)
    parser.add_argument("--score-count", type=int, default=8000)
    parser.add_argument(
        "--score-provider",
        choices=["live", "shadow"],
        default="shadow",
        help="Prediction provider to score when writing the score snapshot.",
    )
    parser.add_argument("--score-min-samples", type=int, default=200)
    parser.add_argument("--score-min-ml-score", type=float, default=60.0)
    parser.add_argument("--score-min-exact-accuracy", type=float, default=0.50)
    parser.add_argument("--score-max-ece", type=float, default=0.20)
    parser.add_argument("--score-min-avg-realized-bps", type=float, default=-9999.0)
    parser.add_argument("--score-min-promotion-score-v2", type=float, default=0.0)
    parser.add_argument("--score-min-directional-coverage", type=float, default=0.10)
    parser.add_argument("--flat-threshold-bps", type=float, default=None,
                        help="Flat-zone threshold in bps for scoring. Auto-read from model meta if not set.")
    parser.add_argument(
        "--score-snapshot-ttl-sec",
        type=int,
        default=7200,
        help=(
            "TTL for the Redis prediction score snapshot written by "
            "prediction_shadow_outcome_report.py. This must be longer than the "
            "outer cycle sleep if you want the dashboard/pipeline-health to keep "
            "showing ML/Exact/ECE continuously."
        ),
    )
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument(
        "--auto-fallback-expert-meta",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "If expert targets are requested but model-meta has no experts, "
            "auto-select the newest latest.json* backup that contains experts."
        ),
    )
    args = parser.parse_args()

    model_meta = _resolve_model_meta_path(str(args.model_meta))
    if not model_meta.exists():
        raise SystemExit(f"model_meta_not_found:{model_meta}")
    meta_payload = _load_meta_payload(model_meta)

    # Auto-detect flat_threshold_bps from model meta when not explicitly set.
    if args.flat_threshold_bps is None:
        args.flat_threshold_bps = float(meta_payload.get("flat_threshold_bps") or meta_payload.get("tp_bps") or 3.0)

    targets = _resolve_targets(model_meta, args.expert_ids, args.all_experts)
    if not targets:
        raise SystemExit("no_calibration_targets")
    targets_ok, target_error = _validate_targets_against_meta(
        meta_payload,
        targets,
        expert_ids_csv=args.expert_ids,
        all_experts=bool(args.all_experts),
    )
    if not targets_ok:
        # Auto-recover common rollback case:
        # latest.json may be reverted to baseline while expert backups still exist.
        if (
            args.auto_fallback_expert_meta
            and target_error == "expert_targets_requested_but_no_experts_in_meta"
        ):
            fallback_meta = _select_expert_meta_fallback(model_meta)
            if fallback_meta is not None:
                fallback_payload = _load_meta_payload(fallback_meta)
                fallback_targets = _resolve_targets(fallback_meta, args.expert_ids, args.all_experts)
                fallback_ok, fallback_err = _validate_targets_against_meta(
                    fallback_payload,
                    fallback_targets,
                    expert_ids_csv=args.expert_ids,
                    all_experts=bool(args.all_experts),
                )
                if fallback_ok:
                    print(
                        json.dumps(
                            {
                                "status": "model_meta_auto_fallback",
                                "reason": target_error,
                                "model_meta": str(model_meta),
                                "fallback_model_meta": str(fallback_meta),
                                "available_experts": _list_expert_ids(fallback_payload),
                            },
                            sort_keys=True,
                        )
                    )
                    model_meta = fallback_meta
                    meta_payload = fallback_payload
                    targets = fallback_targets
                    targets_ok = True
                    target_error = None
                else:
                    target_error = fallback_err or target_error
        if not targets_ok:
            print(
                json.dumps(
                    {
                        "status": "invalid_calibration_targets",
                        "error": target_error,
                        "model_meta": str(model_meta),
                        "available_experts": _list_expert_ids(meta_payload),
                        "requested_targets": [item for item in targets if item],
                    },
                    sort_keys=True,
                )
            )
            return 2

    runtime_process = args.runtime_process_name.strip() or _default_runtime_process(args.tenant_id, args.bot_id)
    started = time.time()

    for iteration in range(1, max(1, int(args.max_iterations)) + 1):
        if args.max_runtime_sec and (time.time() - started) > float(args.max_runtime_sec):
            print(json.dumps({"status": "timeout", "iteration": iteration - 1}, sort_keys=True))
            return 1

        calibration_results: list[dict[str, Any]] = []
        for target in targets:
            cmd = [
                str(args.python_bin),
                str(_ROOT / "scripts" / "calibrate_onnx_probabilities.py"),
                "--model-meta",
                str(model_meta),
                "--redis-url",
                str(args.redis_url),
                "--stream",
                str(args.stream),
                "--tail-count",
                str(args.tail_count),
                "--hours",
                str(args.hours),
                "--horizon-sec",
                str(args.horizon_sec),
                "--up-threshold",
                str(args.up_threshold),
                "--down-threshold",
                str(args.down_threshold),
                "--label-source",
                str(args.label_source),
                "--tenant-id",
                str(args.tenant_id),
                "--bot-id",
                str(args.bot_id),
            ]
            if args.live_from_stream:
                cmd.append("--live-from-stream")
            if args.model_path:
                cmd.extend(["--model-path", str(args.model_path)])
            if target:
                cmd.extend(["--expert-id", str(target)])

            code, stdout, stderr = _run_command(cmd, cwd=_ROOT)
            last_obj = _last_json_dict(stdout)
            failure = None
            if code != 0:
                failure = _classify_calibration_failure(last_obj or {}, stdout, stderr)
            item = {
                "target": target or "default",
                "exit_code": code,
                "status": (last_obj or {}).get("status") if isinstance(last_obj, dict) else None,
                "stderr_tail": (stderr or "").strip()[-240:],
            }
            if failure is not None:
                item["failure"] = failure

            # Retryable failure path: for expert targets, retry once using explicit fallback dataset.
            if (
                code != 0
                and failure is not None
                and bool(failure.get("retryable"))
                and target
            ):
                fallback_dataset = _resolve_expert_fallback_dataset(meta_payload, str(target))
                if fallback_dataset:
                    retry_cmd = [part for part in cmd if part != "--live-from-stream"]
                    if "--fallback-dataset" not in retry_cmd:
                        retry_cmd.extend(["--fallback-dataset", str(fallback_dataset)])
                    retry_code, retry_stdout, retry_stderr = _run_command(retry_cmd, cwd=_ROOT)
                    retry_last_obj = _last_json_dict(retry_stdout)
                    retry_failure = None
                    if retry_code != 0:
                        retry_failure = _classify_calibration_failure(
                            retry_last_obj or {},
                            retry_stdout,
                            retry_stderr,
                        )
                    item["retry"] = {
                        "attempted": True,
                        "fallback_dataset": fallback_dataset,
                        "exit_code": retry_code,
                        "status": (retry_last_obj or {}).get("status")
                        if isinstance(retry_last_obj, dict)
                        else None,
                        "stderr_tail": (retry_stderr or "").strip()[-240:],
                    }
                    if retry_failure is not None:
                        item["retry"]["failure"] = retry_failure
                    if retry_code == 0:
                        item["exit_code"] = retry_code
                        item["status"] = (retry_last_obj or {}).get("status") if isinstance(retry_last_obj, dict) else None
                        item["stderr_tail"] = (retry_stderr or "").strip()[-240:]
                        item.pop("failure", None)

            calibration_results.append(item)
            effective_code = int(item.get("exit_code") or 0)
            if code != 0 and "expert_id_requested_but_no_experts_in_meta" in (stderr or ""):
                print(
                    json.dumps(
                        {
                            "status": "invalid_calibration_targets",
                            "iteration": iteration,
                            "result": item,
                            "model_meta": str(model_meta),
                            "available_experts": _list_expert_ids(meta_payload),
                        },
                        sort_keys=True,
                    )
                )
                return 2
            if effective_code != 0 and args.stop_on_calibration_error:
                print(
                    json.dumps(
                        {
                            "status": "calibration_failed",
                            "iteration": iteration,
                            "result": item,
                        },
                        sort_keys=True,
                    )
                )
                return 2

        if args.restart_runtime:
            rc, _, pm2_err = _run_command(["pm2", "restart", runtime_process])
            if rc != 0:
                print(
                    json.dumps(
                        {
                            "status": "runtime_restart_failed",
                            "iteration": iteration,
                            "runtime_process": runtime_process,
                            "stderr_tail": (pm2_err or "").strip()[-240:],
                        },
                        sort_keys=True,
                    )
                )
                return 3
            if args.warmup_sec > 0:
                time.sleep(float(args.warmup_sec))

        score_cmd = [
            str(args.python_bin),
            str(_ROOT / "scripts" / "prediction_shadow_outcome_report.py"),
            "--redis-url",
            str(args.redis_url),
            "--tenant-id",
            str(args.tenant_id),
            "--bot-id",
            str(args.bot_id),
            "--hours",
            str(args.score_hours),
            "--count",
            str(args.score_count),
            "--horizon-sec",
            str(args.horizon_sec),
            "--score-provider",
            str(args.score_provider),
            "--score-min-samples",
            str(args.score_min_samples),
            "--score-min-ml-score",
            str(args.score_min_ml_score),
            "--score-min-exact-accuracy",
            str(args.score_min_exact_accuracy),
            "--score-max-ece",
            str(args.score_max_ece),
            "--score-min-avg-realized-bps",
            str(args.score_min_avg_realized_bps),
            "--score-min-promotion-score-v2",
            str(args.score_min_promotion_score_v2),
            "--score-min-directional-coverage",
            str(args.score_min_directional_coverage),
            "--score-snapshot-ttl-sec",
            str(int(args.score_snapshot_ttl_sec)),
            "--flat-threshold-bps",
            str(args.flat_threshold_bps),
            "--write-score-snapshot",
        ]
        score_code, score_stdout, score_stderr = _run_command(score_cmd, cwd=_ROOT)
        score_payload = _last_json_dict(score_stdout)
        snapshot = (score_payload or {}).get("score_snapshot") if isinstance(score_payload, dict) else {}
        score_status = (snapshot or {}).get("status")
        symbols = (snapshot or {}).get("symbols") or {}
        blocked_symbols = [sym for sym, data in symbols.items() if isinstance(data, dict) and data.get("status") != "ok"]

        iteration_summary = {
            "iteration": iteration,
            "calibration_results": calibration_results,
            "score_exit_code": score_code,
            "score_status": score_status,
            "blocked_symbols": blocked_symbols,
            "timestamp": time.time(),
        }
        if score_code != 0:
            iteration_summary["score_stderr_tail"] = (score_stderr or "").strip()[-240:]
        print(json.dumps(iteration_summary, sort_keys=True))

        if score_code == 0 and score_status == "ok":
            print(json.dumps({"status": "passed", "iteration": iteration}, sort_keys=True))
            return 0

        if iteration < int(args.max_iterations):
            time.sleep(max(0.0, float(args.sleep_sec)))

    print(json.dumps({"status": "max_iterations_reached", "iterations": int(args.max_iterations)}, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
