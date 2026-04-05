#!/usr/bin/env python3
"""Export replay JSONL snapshots from decision_events.

This creates richer snapshots than the orderbook-only transformer by using
decision payload snapshot/metrics fields and synthesizing bid/ask from
mid_price + spread_bps when needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg

from quantgambit.config.env_loading import apply_layered_env_defaults


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_epoch_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        elif ts > 1e15:
            ts /= 1e9
        return ts
    if isinstance(value, str):
        try:
            return _to_epoch_seconds(float(value))
        except Exception:
            return 0.0
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    return 0.0


def _confidence_from_payload(payload: dict[str, Any]) -> float:
    for key in ("p_calibrated", "p_raw", "confidence", "prob", "p_win"):
        value = payload.get(key)
        if value is not None:
            fv = _safe_float(value, -1.0)
            if 0.0 <= fv <= 1.0:
                return fv
    prediction = payload.get("prediction")
    if isinstance(prediction, dict):
        fv = _safe_float(prediction.get("confidence"), -1.0)
        if 0.0 <= fv <= 1.0:
            return fv
    return 0.5


def _direction_from_payload(payload: dict[str, Any], snapshot: dict[str, Any]) -> str:
    prediction = payload.get("prediction")
    if isinstance(prediction, dict):
        raw = str(prediction.get("direction") or "").lower()
        if raw in {"up", "long", "buy"}:
            return "up"
        if raw in {"down", "short", "sell"}:
            return "down"
    trend = str(snapshot.get("trend_direction") or "").lower()
    if trend in {"up", "down"}:
        return trend
    return "neutral"


async def _export(args: argparse.Namespace) -> int:
    apply_layered_env_defaults(Path(__file__).resolve().parents[1], os.getenv("ENV_FILE"), os.environ)
    load_dotenv()

    db_url = os.getenv(
        "BOT_TIMESCALE_URL",
        "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot",
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.lookback_hours)
    if args.start:
        start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    if args.end:
        end = datetime.fromisoformat(args.end.replace("Z", "+00:00"))

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    try:
        query = """
            SELECT ts, payload
            FROM decision_events
            WHERE symbol = $1
              AND ts >= $2
              AND ts <= $3
              AND payload::text LIKE '%"snapshot"%'
            ORDER BY ts ASC
            LIMIT $4
        """
        rows = await pool.fetch(query, args.symbol, start, end, args.limit)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = row["payload"]
                if not isinstance(payload, dict):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        continue
                snapshot = payload.get("snapshot") or {}
                metrics = payload.get("metrics") or {}
                if not isinstance(snapshot, dict):
                    snapshot = {}
                if not isinstance(metrics, dict):
                    metrics = {}

                mid = _safe_float(snapshot.get("mid_price"), 0.0)
                spread_bps = _safe_float(metrics.get("spread_bps") or snapshot.get("spread_bps"), 0.0)
                if mid <= 0:
                    continue
                spread_frac = spread_bps / 10000.0
                bid = mid * (1.0 - spread_frac / 2.0)
                ask = mid * (1.0 + spread_frac / 2.0)
                ts = _to_epoch_seconds(row["ts"])

                market_context = {
                    "price": mid,
                    "bid": bid,
                    "ask": ask,
                    "best_bid": bid,
                    "best_ask": ask,
                    "spread": spread_frac,
                    "spread_bps": spread_bps,
                    "bid_depth_usd": _safe_float(metrics.get("bid_depth_usd"), 0.0),
                    "ask_depth_usd": _safe_float(metrics.get("ask_depth_usd"), 0.0),
                    "snapshot_age_ms": _safe_float(snapshot.get("snapshot_age_ms"), 0.0),
                    "trade_age_sec": _safe_float(metrics.get("trade_age_sec"), 0.0),
                    "orderbook_feed_age_sec": _safe_float(metrics.get("orderbook_feed_age_sec"), 0.0),
                    "trade_feed_age_sec": _safe_float(metrics.get("trade_feed_age_sec"), 0.0),
                    "volatility_regime": snapshot.get("vol_regime"),
                    "trend_direction": snapshot.get("trend_direction"),
                    "trend_strength": _safe_float(snapshot.get("trend_strength"), 0.0),
                    "position_in_value": snapshot.get("position_in_value"),
                    "rotation_factor": _safe_float(snapshot.get("rotation_factor"), 0.0),
                    "point_of_control": _safe_float(snapshot.get("poc_price"), 0.0),
                    "value_area_high": _safe_float(snapshot.get("vah_price"), 0.0),
                    "value_area_low": _safe_float(snapshot.get("val_price"), 0.0),
                    "poc_price": _safe_float(snapshot.get("poc_price"), 0.0),
                    "vah_price": _safe_float(snapshot.get("vah_price"), 0.0),
                    "val_price": _safe_float(snapshot.get("val_price"), 0.0),
                    "distance_to_poc_bps": _safe_float(snapshot.get("distance_to_poc_bps"), 0.0),
                    "distance_to_vah_bps": _safe_float(snapshot.get("distance_to_vah_bps"), 0.0),
                    "distance_to_val_bps": _safe_float(snapshot.get("distance_to_val_bps"), 0.0),
                    "timestamp": ts,
                }

                features = {
                    "price": mid,
                    "bid": bid,
                    "ask": ask,
                    "best_bid": bid,
                    "best_ask": ask,
                    "spread": spread_frac,
                    "bid_depth_usd": market_context["bid_depth_usd"],
                    "ask_depth_usd": market_context["ask_depth_usd"],
                    "spread_bps": spread_bps,
                    "trade_count": 1,
                    "buy_volume": 0.0,
                    "sell_volume": 0.0,
                    "timestamp": ts,
                    "atr_5m": _safe_float(snapshot.get("atr_5m"), 0.0),
                    "atr_5m_baseline": _safe_float(snapshot.get("atr_5m_baseline"), 0.0),
                    "volatility_regime": snapshot.get("vol_regime"),
                    "trend_direction": snapshot.get("trend_direction"),
                    "trend_strength": _safe_float(snapshot.get("trend_strength"), 0.0),
                    "position_in_value": snapshot.get("position_in_value"),
                    "rotation_factor": _safe_float(snapshot.get("rotation_factor"), 0.0),
                    "point_of_control": market_context["point_of_control"],
                    "value_area_high": market_context["value_area_high"],
                    "value_area_low": market_context["value_area_low"],
                    "poc_price": _safe_float(snapshot.get("poc_price"), 0.0),
                    "vah_price": _safe_float(snapshot.get("vah_price"), 0.0),
                    "val_price": _safe_float(snapshot.get("val_price"), 0.0),
                    "distance_to_poc_bps": market_context["distance_to_poc_bps"],
                    "distance_to_vah_bps": market_context["distance_to_vah_bps"],
                    "distance_to_val_bps": market_context["distance_to_val_bps"],
                }

                out_row = {
                    "symbol": args.symbol,
                    "timestamp": ts,
                    "market_context": market_context,
                    "features": features,
                    "prediction": {
                        "confidence": _confidence_from_payload(payload),
                        "direction": _direction_from_payload(payload, snapshot),
                        "source": "decision_events_export",
                    },
                    "warmup_ready": True,
                }
                handle.write(json.dumps(out_row) + "\n")
                written += 1

        print(
            json.dumps(
                {
                    "output": str(output),
                    "symbol": args.symbol,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "rows_fetched": len(rows),
                    "rows_written": written,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if written > 0 else 1
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Export replay snapshots from decision_events.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--lookback-hours", type=float, default=12.0)
    parser.add_argument("--start", default=None, help="ISO timestamp (overrides lookback start)")
    parser.add_argument("--end", default=None, help="ISO timestamp (default: now)")
    parser.add_argument("--limit", type=int, default=250000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return asyncio.run(_export(args))


if __name__ == "__main__":
    raise SystemExit(main())
