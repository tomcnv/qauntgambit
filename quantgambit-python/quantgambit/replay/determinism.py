"""Determinism harness for replaying normalized events with explicit now_ts schedule."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from quantgambit.ingest.time_utils import us_to_sec
from quantgambit.market.trades import TradeStatsCache
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput


DecisionFn = Callable[[dict], dict]


class _NullRedis:
    async def get(self, *_args, **_kwargs):
        return None

    async def lrange(self, *_args, **_kwargs):
        return []


class _NullRedisClient:
    def __init__(self):
        self.redis = _NullRedis()


@dataclass
class DeterminismConfig:
    symbols: Optional[list[str]] = None
    emit_empty_snapshots: bool = False


@dataclass
class DeterminismResult:
    snapshots: list[dict]
    decisions: list[dict]
    snapshot_hashes: list[str]
    decision_hashes: list[str]


def load_events(path: str) -> list[dict]:
    events: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def load_now_schedule(path: str) -> list[int]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return [int(x) for x in payload]
    raise ValueError("now_ts_schedule_must_be_list")


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _canonicalize(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        if not obj:
            return []
        if all(isinstance(x, str) for x in obj):
            return sorted(obj)
        if all(isinstance(x, dict) for x in obj):
            sample = obj[0]
            if "price" in sample:
                return [_canonicalize(x) for x in sorted(obj, key=lambda v: v.get("price", 0))]
            if "ts" in sample:
                return [_canonicalize(x) for x in sorted(obj, key=lambda v: v.get("ts", 0))]
            if "timestamp" in sample:
                return [_canonicalize(x) for x in sorted(obj, key=lambda v: v.get("timestamp", 0))]
        return [_canonicalize(x) for x in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("non_finite_float")
        return format(obj, ".10f")
    return obj


def canonical_json(obj: Any) -> str:
    canonical = _canonicalize(obj)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


def hash_json(obj: Any) -> str:
    data = canonical_json(obj).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row))
            handle.write("\n")
            count += 1
    return count


def _event_ts_us(event: dict) -> int:
    if "ts_canon_us" in event:
        return int(event["ts_canon_us"])
    payload = event.get("payload") or {}
    if "ts_canon_us" in payload:
        return int(payload["ts_canon_us"])
    if "ts_recv_us" in event:
        return int(event["ts_recv_us"])
    if "ts_recv_us" in payload:
        return int(payload["ts_recv_us"])
    raise ValueError("event_missing_ts_canon_us")


def _event_symbol(event: dict) -> Optional[str]:
    return event.get("symbol") or (event.get("payload") or {}).get("symbol")


def _event_type(event: dict) -> str:
    return event.get("event_type") or event.get("type") or (event.get("payload") or {}).get("event_type") or ""


async def run_determinism_harness(
    events: Iterable[dict],
    now_schedule_us: Iterable[int],
    engine: Optional[DecisionEngine] = None,
    decision_fn: Optional[DecisionFn] = None,
    config: Optional[DeterminismConfig] = None,
) -> DeterminismResult:
    cfg = config or DeterminismConfig()
    trade_cache = TradeStatsCache()
    redis_client = _NullRedisClient()
    feature_worker = FeaturePredictionWorker(
        redis_client=redis_client,
        bot_id="determinism",
        exchange="replay",
        config=FeatureWorkerConfig(),
        trade_cache=trade_cache,
        quality_tracker=None,
    )
    last_ticks: dict[str, dict] = {}
    snapshots: list[dict] = []
    decisions: list[dict] = []
    snapshot_hashes: list[str] = []
    decision_hashes: list[str] = []

    events_list = list(events)
    indexed = list(enumerate(events_list))
    indexed.sort(key=lambda item: (_event_ts_us(item[1]), item[0]))
    idx = 0
    now_list = list(now_schedule_us)

    for now_us in now_list:
        while idx < len(indexed):
            _, event = indexed[idx]
            ts_us = _event_ts_us(event)
            if ts_us > now_us:
                break
            etype = _event_type(event)
            payload = event.get("payload") or event
            symbol = _event_symbol(event)
            if etype in {"trade", "trades"}:
                if symbol:
                    trade_cache.update_trade(
                        symbol=symbol,
                        timestamp_us=int(payload.get("ts_canon_us") or ts_us),
                        price=float(payload.get("price", 0.0)),
                        size=float(payload.get("size", 0.0)),
                        side=str(payload.get("side") or ""),
                    )
            if etype in {"market_tick", "tick"} or payload.get("bid") is not None or payload.get("ask") is not None:
                if symbol:
                    last_ticks[symbol] = payload
            idx += 1
        symbols = cfg.symbols or list(last_ticks.keys())
        for symbol in symbols:
            tick = last_ticks.get(symbol)
            if not tick:
                if cfg.emit_empty_snapshots:
                    snapshots.append({"symbol": symbol, "timestamp": us_to_sec(now_us)})
                    snapshot_hashes.append(hash_json(snapshots[-1]))
                continue
            tick = {**tick}
            tick["ts_canon_us"] = int(now_us)
            tick["timestamp"] = us_to_sec(now_us)
            snapshot = await feature_worker._build_snapshot(symbol, tick)
            if not snapshot:
                continue
            snapshots.append(snapshot)
            snapshot_hashes.append(hash_json(snapshot))
            if decision_fn:
                decision = decision_fn(snapshot)
            elif engine:
                decision_input = DecisionInput(
                    symbol=snapshot["symbol"],
                    market_context=snapshot.get("market_context") or {},
                    features=snapshot.get("features") or {},
                    prediction=snapshot.get("prediction"),
                    account_state={},
                    positions=[],
                )
                accepted, ctx = await engine.decide_with_context(decision_input)
                decision = {
                    "symbol": snapshot["symbol"],
                    "timestamp": snapshot.get("timestamp"),
                    "accepted": accepted,
                    "rejection_reason": getattr(ctx, "rejection_reason", None),
                    "profile_id": getattr(ctx, "profile_id", None),
                    "signal": getattr(ctx, "signal", None),
                }
            else:
                decision = {}
            if decision:
                decisions.append(decision)
                decision_hashes.append(hash_json(decision))
    return DeterminismResult(
        snapshots=snapshots,
        decisions=decisions,
        snapshot_hashes=snapshot_hashes,
        decision_hashes=decision_hashes,
    )


async def run_determinism_files(
    events_path: str | Path,
    now_schedule_path: str | Path,
    output_dir: str | Path,
    config: Optional[DeterminismConfig] = None,
) -> DeterminismResult:
    events = load_events(str(events_path))
    now_schedule = load_now_schedule(str(now_schedule_path))
    result = await run_determinism_harness(events, now_schedule, config=config)
    out_dir = Path(output_dir)
    write_jsonl(out_dir / "snapshots.jsonl", result.snapshots)
    write_jsonl(out_dir / "decisions.jsonl", result.decisions)
    hash_rows = [
        {"type": "snapshot", "index": idx, "hash": h}
        for idx, h in enumerate(result.snapshot_hashes)
    ]
    hash_rows.extend(
        {"type": "decision", "index": idx, "hash": h}
        for idx, h in enumerate(result.decision_hashes)
    )
    write_jsonl(out_dir / "hashes.jsonl", hash_rows)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="quantgambit.replay.determinism",
        description="Run determinism harness and emit canonical JSONL outputs.",
    )
    parser.add_argument("--events", required=True, help="Path to events.jsonl")
    parser.add_argument("--now-schedule", required=True, help="Path to now_ts.json")
    parser.add_argument("--output-dir", required=True, help="Output directory for JSONL files")
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbol allowlist (default: all symbols seen in events)",
    )
    parser.add_argument(
        "--emit-empty-snapshots",
        action="store_true",
        help="Emit empty snapshots when no tick is available for a symbol",
    )
    args = parser.parse_args()
    symbols = None
    if args.symbols:
        symbols = [sym.strip() for sym in args.symbols.split(",") if sym.strip()]
    config = DeterminismConfig(symbols=symbols, emit_empty_snapshots=args.emit_empty_snapshots)
    result = asyncio.run(
        run_determinism_files(
            events_path=args.events,
            now_schedule_path=args.now_schedule,
            output_dir=args.output_dir,
            config=config,
        )
    )
    print(
        "Determinism harness complete:",
        f"{len(result.snapshots)} snapshots, {len(result.decisions)} decisions.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
