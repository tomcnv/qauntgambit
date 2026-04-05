#!/usr/bin/env python3
"""Export feature snapshots to a labeled CSV for model training."""

from __future__ import annotations

import argparse
import asyncio
import bisect
import calendar
import csv
import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple

import redis.asyncio as redis
import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantgambit.ingest.schemas import coerce_float
from quantgambit.storage.redis_streams import decode_message


DEFAULT_FEATURES = [
    "price",
    "spread_bps",
    "price_change_1s",
    "price_change_5s",
    "price_change_30s",
    "price_change_5m",
    "rotation_factor",
    "ema_fast_15m",
    "ema_slow_15m",
    "ema_spread_pct",
    "trend_strength",
    "atr_5m",
    "atr_5m_baseline",
    "vwap",
    "orderbook_imbalance",
    "bid_depth_usd",
    "ask_depth_usd",
    "data_completeness",
]


@dataclasses.dataclass(frozen=True)
class ReplayCostConfig:
    half_spread_bps: float = 2.0
    slippage_bps: float = 2.0
    fee_bps_entry: float = 5.5
    fee_bps_exit: float = 5.5


@dataclasses.dataclass(frozen=True)
class ReplayEngineConfig:
    step_hz: float = 4.0
    max_horizon_sec: float = 300.0
    max_age_sec: float = 300.0
    stop_loss_bps: float = 60.0
    take_profit_bps: float = 90.0
    trailing_activation_bps: float = 20.0
    trailing_bps: float = 25.0
    breakeven_activation_bps: float = 12.0
    breakeven_buffer_bps: float = 3.0
    profit_lock_activation_bps: float = 25.0
    profit_lock_retrace_bps: float = 8.0
    hard_stop_pct: float = 2.0
    deep_underwater_pct: float = 1.0
    time_to_work_sec: float = 120.0
    mfe_min_bps: float = 6.0


_FORCED_RISK_REASONS = {
    "hard_stop_hit",
    "stop_loss_hit",
    "data_stale_while_in_position",
    "deeply_underwater_emergency",
    "guardian_stop_loss",
    "guardian_take_profit",
    "guardian_trailing_stop",
    "guardian_breakeven_stop",
    "guardian_profit_lock",
    "guardian_protection_failure",
}


_FORCED_TIME_REASONS = {
    "time_to_work_fail",
    "max_hold_exceeded",
    "grace_period_expired",
}

def _load_feature_keys(path: str) -> list[str]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"missing_features_config:{path}")
    except Exception as exc:
        raise SystemExit(f"invalid_features_config:{path}:{exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"features_config_not_dict:{path}")
    feature_keys = raw.get("feature_keys")
    if not isinstance(feature_keys, list) or not feature_keys:
        raise SystemExit(f"features_config_missing_keys:{path}")
    return [str(item) for item in feature_keys]

def _session_label(ts_sec: float) -> str:
    hour = time.gmtime(ts_sec).tm_hour
    if 12 <= hour < 20:
        return "us"
    if 7 <= hour < 15:
        return "europe"
    return "asia"


def _inject_categoricals(
    row: dict,
    *,
    symbols_onehot: Optional[List[str]],
    session_onehot: bool,
) -> None:
    symbol = str(row.get("symbol") or "")
    ts = coerce_float(row.get("timestamp"))
    if symbols_onehot:
        sym_u = symbol.upper()
        for sym in symbols_onehot:
            row[f"symbol_{sym}"] = 1.0 if sym == sym_u else 0.0
    if session_onehot and ts is not None:
        sess = _session_label(float(ts))
        row["session_us"] = 1.0 if sess == "us" else 0.0
        row["session_europe"] = 1.0 if sess == "europe" else 0.0
        row["session_asia"] = 1.0 if sess == "asia" else 0.0


def _get_price(features: dict, market_context: dict) -> Optional[float]:
    return (
        coerce_float(market_context.get("price"))
        or coerce_float(features.get("price"))
        or coerce_float(market_context.get("last"))
        or coerce_float(features.get("last"))
    )


async def _load_snapshots(
    redis_client,
    stream: str,
    limit: Optional[int],
    *,
    min_ts: Optional[float] = None,
    tail_count: Optional[int] = None,
) -> Dict[str, List[dict]]:
    records: Dict[str, List[dict]] = {}
    if tail_count is not None:
        entries = await redis_client.xrevrange(stream, count=int(tail_count))
        entries = list(reversed(entries))  # oldest -> newest
        remaining = limit
        for _, payload in entries:
            if remaining is not None and remaining <= 0:
                break
            message = decode_message(payload)
            if message.get("event_type") != "feature_snapshot":
                continue
            snapshot = message.get("payload") or {}
            symbol = snapshot.get("symbol")
            if not symbol:
                continue
            features = snapshot.get("features") or {}
            market_context = snapshot.get("market_context") or {}
            ts = coerce_float(snapshot.get("timestamp")) or coerce_float(market_context.get("timestamp"))
            price = _get_price(features, market_context)
            if ts is None or price is None:
                continue
            if min_ts is not None and ts < min_ts:
                continue
            records.setdefault(symbol, []).append(
                {
                    "timestamp": ts,
                    "price": price,
                    "features": features,
                    "market_context": market_context,
                }
            )
            if remaining is not None:
                remaining -= 1
    else:
        cursor = "-"
        remaining = limit
        while True:
            count = 1000
            if remaining is not None:
                count = min(count, remaining)
            entries = await redis_client.xrange(stream, min=cursor, max="+", count=count)
            if not entries:
                break
            for entry_id, payload in entries:
                if cursor != "-" and entry_id == cursor:
                    continue
                message = decode_message(payload)
                if message.get("event_type") != "feature_snapshot":
                    continue
                snapshot = message.get("payload") or {}
                symbol = snapshot.get("symbol")
                if not symbol:
                    continue
                features = snapshot.get("features") or {}
                market_context = snapshot.get("market_context") or {}
                ts = coerce_float(snapshot.get("timestamp")) or coerce_float(market_context.get("timestamp"))
                price = _get_price(features, market_context)
                if ts is None or price is None:
                    continue
                if min_ts is not None and ts < min_ts:
                    continue
                records.setdefault(symbol, []).append(
                    {
                        "timestamp": ts,
                        "price": price,
                        "features": features,
                        "market_context": market_context,
                    }
                )
            cursor = entries[-1][0]
            if remaining is not None:
                remaining -= len(entries)
                if remaining <= 0:
                    break
    for symbol, items in records.items():
        items.sort(key=lambda item: item["timestamp"])
    return records


async def _load_snapshots_timescale(
    timescale_url: str,
    tenant_id: str,
    bot_id: str,
    *,
    limit: Optional[int],
    min_ts: Optional[float] = None,
) -> Dict[str, List[dict]]:
    records: Dict[str, List[dict]] = {}
    pool = await asyncpg.create_pool(timescale_url)
    try:
        params: list[object] = [tenant_id, bot_id]
        where = "WHERE tenant_id=$1 AND bot_id=$2 "
        if min_ts is not None:
            params.append(datetime.fromtimestamp(float(min_ts), tz=timezone.utc))
            where += f"AND ts >= ${len(params)} "
        limit_n = int(limit or 200000)
        params.append(limit_n)
        rows = await pool.fetch(
            f"""
            SELECT ts, payload, symbol
            FROM decision_events
            {where}
            ORDER BY ts DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    finally:
        await pool.close()

    for row in reversed(rows):
        payload = row.get("payload") if isinstance(row, dict) else row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            continue
        symbol = str(payload.get("symbol") or row.get("symbol") or "").strip()
        if not symbol:
            continue
        features = payload.get("features") or {}
        if not isinstance(features, dict):
            features = {}
        market_context = payload.get("market_context") or {}
        if not isinstance(market_context, dict):
            market_context = {}
        ts = coerce_float(payload.get("timestamp"))
        if ts is None:
            try:
                ts = float(calendar.timegm(row["ts"].utctimetuple()))
            except Exception:
                ts = None
        price = _get_price(features, market_context)
        if ts is None or price is None:
            continue
        records.setdefault(symbol, []).append(
            {
                "timestamp": ts,
                "price": price,
                "features": features,
                "market_context": market_context,
            }
        )
    return records


def _label_return(
    current_price: float,
    future_price: float,
    up_threshold: float,
    down_threshold: float,
) -> tuple[str, float]:
    ret = (future_price - current_price) / current_price
    if ret >= up_threshold:
        return "up", ret
    if ret <= down_threshold:
        return "down", ret
    return "flat", ret


def _label_from_return(ret: float, up_threshold: float, down_threshold: float) -> str:
    if ret >= up_threshold:
        return "up"
    if ret <= down_threshold:
        return "down"
    return "flat"


def _label_tp_sl_path(
    timestamps: List[float],
    prices: List[float],
    idx: int,
    horizon_sec: float,
    tp_threshold: float,
    sl_threshold: float,
) -> tuple[str, float]:
    """
    Triple-barrier style label using only future price path:
    - "up" if TP (>= +tp_threshold) hits first
    - "down" if SL (<= sl_threshold, typically negative) hits first
    - "flat" if neither hits by horizon

    Returns: (label, realized_return_at_barrier_or_horizon)
    """
    t0 = timestamps[idx]
    p0 = prices[idx]
    if p0 <= 0:
        return "flat", 0.0
    tp_price = p0 * (1.0 + tp_threshold)
    sl_price = p0 * (1.0 + sl_threshold)
    end_ts = t0 + horizon_sec
    j = idx + 1
    last_price = p0
    while j < len(timestamps) and timestamps[j] <= end_ts:
        pj = prices[j]
        last_price = pj
        if pj >= tp_price:
            return "up", (pj - p0) / p0
        if pj <= sl_price:
            return "down", (pj - p0) / p0
        j += 1
    return "flat", (last_price - p0) / p0 if last_price else 0.0


def _iter_labeled_rows(
    records: Dict[str, List[dict]],
    horizon_sec: float,
    up_threshold: float,
    down_threshold: float,
    feature_keys: List[str],
) -> Iterable[dict]:
    for symbol, items in records.items():
        if len(items) < 2:
            continue
        timestamps = [item["timestamp"] for item in items]
        for idx, item in enumerate(items):
            target_ts = item["timestamp"] + horizon_sec
            next_idx = _find_future_index(timestamps, target_ts, idx + 1)
            if next_idx is None:
                continue
            future_price = items[next_idx]["price"]
            label, ret = _label_return(item["price"], future_price, up_threshold, down_threshold)
            row = {
                "symbol": symbol,
                "timestamp": item["timestamp"],
                "label": label,
                "return": ret,
            }
            features = item["features"]
            market_context = item["market_context"]
            for key in feature_keys:
                value = coerce_float(features.get(key))
                if value is None:
                    value = coerce_float(market_context.get(key))
                row[key] = value if value is not None else 0.0
            yield row


def _iter_tp_sl_rows(
    records: Dict[str, List[dict]],
    horizon_sec: float,
    tp_threshold: float,
    sl_threshold: float,
    feature_keys: List[str],
) -> Iterable[dict]:
    for symbol, items in records.items():
        if len(items) < 2:
            continue
        timestamps = [item["timestamp"] for item in items]
        prices = [item["price"] for item in items]
        for idx, item in enumerate(items):
            if idx >= len(items) - 1:
                continue
            label, ret = _label_tp_sl_path(
                timestamps,
                prices,
                idx,
                horizon_sec=horizon_sec,
                tp_threshold=tp_threshold,
                sl_threshold=sl_threshold,
            )
            row = {
                "symbol": symbol,
                "timestamp": item["timestamp"],
                "label": label,
                "return": ret,
            }
            features = item["features"]
            market_context = item["market_context"]
            for key in feature_keys:
                value = coerce_float(features.get(key))
                if value is None:
                    value = coerce_float(market_context.get(key))
                row[key] = value if value is not None else 0.0
            yield row


def _iter_order_labeled_rows(
    records: Dict[str, List[dict]],
    order_events: Dict[str, List[dict]],
    window_sec: float,
    feature_keys: List[str],
) -> Iterable[dict]:
    for symbol, items in records.items():
        orders = order_events.get(symbol) or []
        if not orders:
            continue
        order_ts = [order["timestamp"] for order in orders]
        for item in items:
            label = _label_from_orders(order_ts, orders, item["timestamp"], window_sec)
            if label is None:
                continue
            row = {
                "symbol": symbol,
                "timestamp": item["timestamp"],
                "label": label,
                "return": 0.0,
            }
            features = item["features"]
            market_context = item["market_context"]
            for key in feature_keys:
                value = coerce_float(features.get(key))
                if value is None:
                    value = coerce_float(market_context.get(key))
                row[key] = value if value is not None else 0.0
            yield row


def _iter_order_pnl_rows(
    records: Dict[str, List[dict]],
    order_events: Dict[str, List[dict]],
    window_sec: float,
    horizon_sec: float,
    up_threshold: float,
    down_threshold: float,
    feature_keys: List[str],
) -> Iterable[dict]:
    for symbol, items in records.items():
        orders = order_events.get(symbol) or []
        if not orders:
            continue
        order_ts = [order["timestamp"] for order in orders]
        snapshot_ts = [item["timestamp"] for item in items]
        for item in items:
            order_idx = _find_future_index(order_ts, item["timestamp"], 0)
            if order_idx is None:
                continue
            if order_ts[order_idx] > item["timestamp"] + window_sec:
                continue
            order = orders[order_idx]
            fill_price = order.get("fill_price")
            if fill_price is None:
                continue
            future_idx = _find_future_index(snapshot_ts, order_ts[order_idx] + horizon_sec, 0)
            if future_idx is None:
                continue
            future_price = items[future_idx]["price"]
            ret = (future_price - fill_price) / fill_price
            side = order.get("side")
            if side in {"sell", "short"}:
                ret = -ret
            label = _label_from_return(ret, up_threshold, down_threshold)
            row = {
                "symbol": symbol,
                "timestamp": item["timestamp"],
                "label": label,
                "return": ret,
            }
            features = item["features"]
            market_context = item["market_context"]
            for key in feature_keys:
                value = coerce_float(features.get(key))
                if value is None:
                    value = coerce_float(market_context.get(key))
                row[key] = value if value is not None else 0.0
            yield row


def _iter_order_exit_rows(
    records: Dict[str, List[dict]],
    order_events: Dict[str, List[dict]],
    up_threshold: float,
    down_threshold: float,
    feature_keys: List[str],
) -> Iterable[dict]:
    for symbol, items in records.items():
        orders = order_events.get(symbol) or []
        if not orders:
            continue
        snapshot_ts = [item["timestamp"] for item in items]
        exit_events = [
            event for event in orders if (event.get("position_effect") or "").lower() == "close"
        ]
        if exit_events:
            for event in exit_events:
                entry_ts = event.get("entry_timestamp")
                realized_pnl_pct = event.get("realized_pnl_pct")
                realized_pnl = event.get("realized_pnl")
                entry_price = event.get("entry_price")
                size = event.get("size")
                if entry_ts is None:
                    continue
                ret = None
                if realized_pnl_pct is not None:
                    ret = realized_pnl_pct / 100.0
                elif realized_pnl is not None and entry_price and size:
                    ret = realized_pnl / (entry_price * size)
                if ret is None:
                    continue
                label = _label_from_return(ret, up_threshold, down_threshold)
                snap_idx = _find_snapshot_before(snapshot_ts, entry_ts)
                if snap_idx is None:
                    continue
                snapshot = items[snap_idx]
                row = {
                    "symbol": symbol,
                    "timestamp": snapshot["timestamp"],
                    "label": label,
                    "return": ret,
                }
                features = snapshot["features"]
                market_context = snapshot["market_context"]
                for key in feature_keys:
                    value = coerce_float(features.get(key))
                    if value is None:
                        value = coerce_float(market_context.get(key))
                    row[key] = value if value is not None else 0.0
                yield row
            continue
        open_pos = None
        for order in orders:
            side = order.get("side")
            fill_price = order.get("fill_price")
            ts = order.get("timestamp")
            if fill_price is None or ts is None or not side:
                continue
            side = str(side).lower()
            if open_pos is None:
                open_pos = {"side": side, "price": fill_price, "timestamp": ts}
                continue
            if side == open_pos["side"]:
                continue
            ret = (fill_price - open_pos["price"]) / open_pos["price"]
            if open_pos["side"] in {"sell", "short"}:
                ret = -ret
            label = _label_from_return(ret, up_threshold, down_threshold)
            snap_idx = _find_snapshot_before(snapshot_ts, open_pos["timestamp"])
            if snap_idx is None:
                open_pos = None
                continue
            snapshot = items[snap_idx]
            row = {
                "symbol": symbol,
                "timestamp": snapshot["timestamp"],
                "label": label,
                "return": ret,
            }
            features = snapshot["features"]
            market_context = snapshot["market_context"]
            for key in feature_keys:
                value = coerce_float(features.get(key))
                if value is None:
                    value = coerce_float(market_context.get(key))
                row[key] = value if value is not None else 0.0
            yield row
            open_pos = None


def _find_future_index(timestamps: List[float], target_ts: float, start_idx: int) -> Optional[int]:
    lo = start_idx
    hi = len(timestamps) - 1
    if lo > hi:
        return None
    while lo <= hi:
        mid = (lo + hi) // 2
        if timestamps[mid] < target_ts:
            lo = mid + 1
        else:
            hi = mid - 1
    if lo < len(timestamps):
        return lo
    return None


def _find_snapshot_before(timestamps: List[float], target_ts: float) -> Optional[int]:
    if not timestamps:
        return None
    idx = bisect.bisect_right(timestamps, target_ts) - 1
    if idx < 0:
        return None
    return idx


def _sample_indices(
    items: List[dict],
    *,
    step_hz: float,
    sample_mode: str,
) -> List[int]:
    if not items:
        return []
    step_sec = max(0.25, 1.0 / max(step_hz, 0.01))
    chosen: List[int] = []
    next_ts = float(items[0]["timestamp"])
    for idx, item in enumerate(items):
        ts = float(item["timestamp"])
        if ts + 1e-9 < next_ts:
            continue
        if sample_mode == "candidate_only":
            features = item.get("features") or {}
            market = item.get("market_context") or {}
            candidate_hint = bool(
                features.get("candidate_state")
                or market.get("candidate_state")
                or abs(coerce_float(market.get("orderbook_imbalance")) or 0.0) >= 0.15
            )
            if not candidate_hint:
                continue
        chosen.append(idx)
        next_ts = ts + step_sec
    return chosen


def _apply_fill_price(mid: float, side: str, spread_bps: float) -> float:
    bump = spread_bps / 1e4
    if side == "long":
        return mid * (1.0 + bump)
    return mid * (1.0 - bump)


def _apply_exit_fill_price(mid: float, side: str, spread_bps: float) -> float:
    bump = spread_bps / 1e4
    if side == "long":
        return mid * (1.0 - bump)
    return mid * (1.0 + bump)


def _classify_exit(reason: str) -> tuple[bool, bool, bool, bool]:
    forced_risk = reason in _FORCED_RISK_REASONS
    forced_time = reason in _FORCED_TIME_REASONS
    strategy_exit = not forced_risk and not forced_time
    forced_exit = forced_risk or forced_time
    return forced_exit, forced_risk, forced_time, strategy_exit


def _replay_one_side(
    items: List[dict],
    start_idx: int,
    side: str,
    cfg: ReplayEngineConfig,
    costs: ReplayCostConfig,
) -> Optional[dict]:
    start = items[start_idx]
    entry_mid = coerce_float(start.get("price"))
    ts0 = coerce_float(start.get("timestamp"))
    if entry_mid is None or ts0 is None or entry_mid <= 0:
        return None
    spread_slip = costs.half_spread_bps + costs.slippage_bps
    entry_price = _apply_fill_price(entry_mid, side, spread_slip)
    qty = 1.0
    notional_entry = abs(entry_price * qty)
    fee_entry = notional_entry * (costs.fee_bps_entry / 1e4)
    step_sec = max(0.25, 1.0 / max(cfg.step_hz, 0.01))
    next_eval_ts = ts0 + step_sec
    peak_favorable_bps = 0.0
    exit_reason = "max_horizon_close"
    exit_ts = ts0
    exit_mid = entry_mid
    for idx in range(start_idx + 1, len(items)):
        item = items[idx]
        ts = coerce_float(item.get("timestamp"))
        mid = coerce_float(item.get("price"))
        if ts is None or mid is None or mid <= 0:
            continue
        if ts + 1e-9 < next_eval_ts:
            continue
        next_eval_ts += step_sec
        hold_sec = ts - ts0
        raw_ret = ((mid - entry_price) / entry_price) if side == "long" else ((entry_price - mid) / entry_price)
        pnl_bps = raw_ret * 1e4
        peak_favorable_bps = max(peak_favorable_bps, pnl_bps)
        if pnl_bps <= -(cfg.hard_stop_pct * 100.0):
            exit_reason = "hard_stop_hit"
            exit_ts = ts
            exit_mid = mid
            break
        if pnl_bps <= -cfg.stop_loss_bps:
            exit_reason = "guardian_stop_loss"
            exit_ts = ts
            exit_mid = mid
            break
        if pnl_bps >= cfg.take_profit_bps:
            exit_reason = "guardian_take_profit"
            exit_ts = ts
            exit_mid = mid
            break
        if peak_favorable_bps >= cfg.profit_lock_activation_bps and pnl_bps <= (
            peak_favorable_bps - cfg.profit_lock_retrace_bps
        ):
            exit_reason = "guardian_profit_lock"
            exit_ts = ts
            exit_mid = mid
            break
        if peak_favorable_bps >= cfg.trailing_activation_bps and pnl_bps <= (
            peak_favorable_bps - cfg.trailing_bps
        ):
            exit_reason = "guardian_trailing_stop"
            exit_ts = ts
            exit_mid = mid
            break
        if peak_favorable_bps >= cfg.breakeven_activation_bps and pnl_bps <= cfg.breakeven_buffer_bps:
            exit_reason = "guardian_breakeven_stop"
            exit_ts = ts
            exit_mid = mid
            break
        if hold_sec >= cfg.time_to_work_sec and peak_favorable_bps < cfg.mfe_min_bps:
            exit_reason = "time_to_work_fail"
            exit_ts = ts
            exit_mid = mid
            break
        if hold_sec >= cfg.max_age_sec:
            exit_reason = "max_hold_exceeded"
            exit_ts = ts
            exit_mid = mid
            break
        if hold_sec >= cfg.max_horizon_sec:
            exit_reason = "max_horizon_close"
            exit_ts = ts
            exit_mid = mid
            break
    exit_price = _apply_exit_fill_price(exit_mid, side, spread_slip)
    notional_exit = abs(exit_price * qty)
    fee_exit = notional_exit * (costs.fee_bps_exit / 1e4)
    gross_pnl = (exit_price - entry_price) if side == "long" else (entry_price - exit_price)
    net_pnl = gross_pnl - fee_entry - fee_exit
    net_return = net_pnl / max(entry_price, 1e-12)
    forced_exit, forced_risk, forced_time, strategy_exit = _classify_exit(exit_reason)
    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_ts": ts0,
        "exit_ts": exit_ts,
        "hold_sec": max(0.0, exit_ts - ts0),
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "net_return": net_return,
        "fee_entry": fee_entry,
        "fee_exit": fee_exit,
        "exit_reason": exit_reason,
        "forced_exit": forced_exit,
        "forced_risk_exit": forced_risk,
        "forced_time_exit": forced_time,
        "strategy_exit": strategy_exit,
    }


def _iter_policy_replay_rows(
    records: Dict[str, List[dict]],
    feature_keys: List[str],
    *,
    replay_cfg: ReplayEngineConfig,
    cost_cfg: ReplayCostConfig,
    sample_mode: str,
    long_only: bool = False,
) -> Iterable[dict]:
    for symbol, items in records.items():
        if len(items) < 3:
            continue
        for idx in _sample_indices(items, step_hz=replay_cfg.step_hz, sample_mode=sample_mode):
            if idx >= len(items) - 1:
                continue
            snap = items[idx]
            long_result = _replay_one_side(items, idx, "long", replay_cfg, cost_cfg)
            if not long_result:
                continue
            if long_only:
                # Spot/long-only: label based on long PnL only
                # up = long profitable, down = long unprofitable, flat = near zero
                net = long_result["net_pnl"]
                entry_p = long_result["entry_price"]
                net_ret = net / max(entry_p, 1e-12) if entry_p else 0.0
                label = _label_from_return(
                    net_ret * 10000.0,  # convert to bps
                    replay_cfg.take_profit_bps,
                    -replay_cfg.stop_loss_bps,
                )
                short_result = {
                    "net_pnl": 0.0, "exit_reason": "n/a", "forced_exit": False,
                    "forced_risk_exit": False, "forced_time_exit": False,
                    "strategy_exit": False, "fee_entry": 0.0, "fee_exit": 0.0,
                    "entry_price": 0.0, "exit_price": 0.0, "hold_sec": 0.0,
                }
            else:
                short_result = _replay_one_side(items, idx, "short", replay_cfg, cost_cfg)
                if not short_result:
                    continue
            # Derive label from net PnL
            if long_only:
                _net = long_result["net_pnl"]
                _ep = long_result["entry_price"]
            else:
                # Use the better side's PnL for labeling
                _net = long_result["net_pnl"] if long_result["net_pnl"] >= short_result["net_pnl"] else -short_result["net_pnl"]
                _ep = long_result["entry_price"] if long_result["net_pnl"] >= short_result["net_pnl"] else short_result["entry_price"]
            _ret_bps = (_net / max(_ep, 1e-12)) * 10000.0 if _ep else 0.0
            replay_label = _label_from_return(_ret_bps, replay_cfg.take_profit_bps, -replay_cfg.stop_loss_bps)
            row = {
                "symbol": symbol,
                "timestamp": snap["timestamp"],
                "label": replay_label,
                "return": _ret_bps,
                "pnl_long_net": long_result["net_pnl"],
                "pnl_short_net": short_result["net_pnl"],
                "y_long": 1 if long_result["net_pnl"] > 0 else 0,
                "y_short": 1 if short_result["net_pnl"] > 0 else 0,
                "exit_reason_long": long_result["exit_reason"],
                "exit_reason_short": short_result["exit_reason"],
                "forced_exit_long": int(long_result["forced_exit"]),
                "forced_exit_short": int(short_result["forced_exit"]),
                "forced_risk_exit_long": int(long_result["forced_risk_exit"]),
                "forced_risk_exit_short": int(short_result["forced_risk_exit"]),
                "forced_time_exit_long": int(long_result["forced_time_exit"]),
                "forced_time_exit_short": int(short_result["forced_time_exit"]),
                "strategy_exit_long": int(long_result["strategy_exit"]),
                "strategy_exit_short": int(short_result["strategy_exit"]),
                "cost_fee_entry_long": long_result["fee_entry"],
                "cost_fee_exit_long": long_result["fee_exit"],
                "cost_fee_entry_short": short_result["fee_entry"],
                "cost_fee_exit_short": short_result["fee_exit"],
                "entry_price_long": long_result["entry_price"],
                "entry_price_short": short_result["entry_price"],
                "exit_price_long": long_result["exit_price"],
                "exit_price_short": short_result["exit_price"],
                "hold_sec_long": long_result["hold_sec"],
                "hold_sec_short": short_result["hold_sec"],
            }
            features = snap.get("features") or {}
            market_context = snap.get("market_context") or {}
            for key in feature_keys:
                value = coerce_float(features.get(key))
                if value is None:
                    value = coerce_float(market_context.get(key))
                row[key] = value if value is not None else 0.0
            yield row


async def _run(args) -> None:
    # Some integration tests construct args via SimpleNamespace and may omit optional fields.
    # Use getattr defaults to keep this harness stable.
    redis_url = (
        getattr(args, "redis_url", None)
        or os.getenv("BOT_REDIS_URL")
        or os.getenv("REDIS_URL", "redis://localhost:6379")
    )
    timescale_url = (
        getattr(args, "timescale_url", None)
        or os.getenv("BOT_TIMESCALE_URL")
        or os.getenv("TIMESCALE_URL")
    )
    redis_client = redis.from_url(redis_url)
    try:
        # Most live pipelines publish namespaced feature streams:
        # `events:features:{tenant_id}:{bot_id}`. When identity is provided,
        # prefer namespaced stream if it has data, and fall back to base stream.
        stream = getattr(args, "stream", "events:features")
        tenant_id = getattr(args, "tenant_id", None)
        bot_id = getattr(args, "bot_id", None)

        stream_key = stream
        if tenant_id and bot_id:
            namespaced = f"{stream}:{tenant_id}:{bot_id}"
            try:
                base_len = await redis_client.xlen(stream)
            except Exception:
                base_len = 0
            try:
                ns_len = await redis_client.xlen(namespaced)
            except Exception:
                ns_len = 0
            if ns_len > 0:
                stream_key = namespaced
            elif base_len > 0:
                stream_key = stream

        min_ts = None
        hours = getattr(args, "hours", None)
        if hours is not None:
            min_ts = float(time.time()) - (float(hours) * 3600.0)

        records = await _load_snapshots(
            redis_client,
            stream_key,
            getattr(args, "limit", None),
            min_ts=min_ts,
            tail_count=getattr(args, "tail_count", None),
        )
        if not records and timescale_url and tenant_id and bot_id:
            records = await _load_snapshots_timescale(
                timescale_url,
                tenant_id,
                bot_id,
                limit=getattr(args, "limit", None),
                min_ts=min_ts,
            )
        order_events = {}
        label_source = getattr(args, "label_source", None)
        if label_source in {"order_fill", "order_pnl", "order_exit_pnl"}:
            order_source = getattr(args, "order_source", None)
            if order_source == "timescale":
                if not getattr(args, "timescale_url", None):
                    raise SystemExit("missing_timescale_url")
                if not tenant_id or not bot_id:
                    raise SystemExit("missing_timescale_identity")
                order_events = await _load_order_events_timescale(
                    args.timescale_url,  # required by the checks above
                    tenant_id,
                    bot_id,
                    getattr(args, "order_limit", None),
                    getattr(args, "order_status", None),
                    exchange=getattr(args, "exchange", None),
                )
            else:
                order_events = await _load_order_events(
                    redis_client,
                    getattr(args, "order_stream", "events:order"),
                    getattr(args, "order_limit", None),
                    getattr(args, "order_status", None),
                )
    finally:
        await redis_client.aclose()
    if not records:
        print(f"no_records:stream={stream_key}")
        return

    include_symbol_onehot = bool(getattr(args, "include_symbol_onehot", False))
    include_session_onehot = bool(getattr(args, "include_session_onehot", False))
    feature_keys: List[str] = list(getattr(args, "features", []))
    output_path = getattr(args, "output", "prediction_dataset.csv")
    horizon_sec = float(getattr(args, "horizon_sec", 300.0))
    up_threshold = float(getattr(args, "up_threshold", 0.001))
    down_threshold = float(getattr(args, "down_threshold", -0.001))
    order_window_sec = float(getattr(args, "order_window_sec", 30.0))
    label_source = getattr(args, "label_source", "future_return")
    replay_cfg = ReplayEngineConfig(
        step_hz=float(getattr(args, "replay_step_hz", 4.0)),
        max_horizon_sec=float(getattr(args, "replay_max_horizon_sec", horizon_sec)),
        max_age_sec=float(getattr(args, "replay_max_age_sec", 300.0)),
        stop_loss_bps=float(getattr(args, "replay_stop_loss_bps", 60.0)),
        take_profit_bps=float(getattr(args, "replay_take_profit_bps", 90.0)),
        trailing_activation_bps=float(getattr(args, "replay_trailing_activation_bps", 20.0)),
        trailing_bps=float(getattr(args, "replay_trailing_bps", 25.0)),
        breakeven_activation_bps=float(getattr(args, "replay_breakeven_activation_bps", 12.0)),
        breakeven_buffer_bps=float(getattr(args, "replay_breakeven_buffer_bps", 3.0)),
        profit_lock_activation_bps=float(getattr(args, "replay_profit_lock_activation_bps", 25.0)),
        profit_lock_retrace_bps=float(getattr(args, "replay_profit_lock_retrace_bps", 8.0)),
        hard_stop_pct=float(getattr(args, "replay_hard_stop_pct", 2.0)),
        deep_underwater_pct=float(getattr(args, "replay_deep_underwater_pct", 1.0)),
        time_to_work_sec=float(getattr(args, "replay_time_to_work_sec", 120.0)),
        mfe_min_bps=float(getattr(args, "replay_mfe_min_bps", 6.0)),
    )
    cost_cfg = ReplayCostConfig(
        half_spread_bps=float(getattr(args, "half_spread_bps", 2.0)),
        slippage_bps=float(getattr(args, "slippage_bps", 2.0)),
        fee_bps_entry=float(getattr(args, "fee_bps_entry", 5.5)),
        fee_bps_exit=float(getattr(args, "fee_bps_exit", 5.5)),
    )
    replay_sample_mode = str(getattr(args, "replay_sample_mode", "periodic")).strip().lower()

    symbols_onehot: Optional[List[str]] = None
    if include_symbol_onehot:
        symbols_onehot = sorted({str(sym).upper() for sym in records.keys() if sym})
    extra_cols: List[str] = []
    if symbols_onehot:
        extra_cols.extend([f"symbol_{sym}" for sym in symbols_onehot])
    if include_session_onehot:
        extra_cols.extend(["session_us", "session_europe", "session_asia"])

    replay_cols = []
    if label_source == "policy_replay":
        replay_cols = [
            "pnl_long_net",
            "pnl_short_net",
            "y_long",
            "y_short",
            "exit_reason_long",
            "exit_reason_short",
            "forced_exit_long",
            "forced_exit_short",
            "forced_risk_exit_long",
            "forced_risk_exit_short",
            "forced_time_exit_long",
            "forced_time_exit_short",
            "strategy_exit_long",
            "strategy_exit_short",
            "cost_fee_entry_long",
            "cost_fee_exit_long",
            "cost_fee_entry_short",
            "cost_fee_exit_short",
            "entry_price_long",
            "entry_price_short",
            "exit_price_long",
            "exit_price_short",
            "hold_sec_long",
            "hold_sec_short",
        ]
    fieldnames = ["symbol", "timestamp", "label", "return"] + replay_cols + extra_cols + feature_keys
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        if label_source == "future_return":
            iterator = _iter_labeled_rows(
                records,
                horizon_sec=horizon_sec,
                up_threshold=up_threshold,
                down_threshold=down_threshold,
                feature_keys=feature_keys,
            )
        elif label_source == "tp_sl":
            # For tp_sl labels:
            # - up_threshold is TP return threshold (e.g., 0.0008 for 8 bps)
            # - down_threshold is SL return threshold (negative, e.g., -0.0006 for 6 bps)
            iterator = _iter_tp_sl_rows(
                records,
                horizon_sec=horizon_sec,
                tp_threshold=up_threshold,
                sl_threshold=down_threshold,
                feature_keys=feature_keys,
            )
        elif label_source == "order_fill":
            iterator = _iter_order_labeled_rows(
                records,
                order_events,
                window_sec=order_window_sec,
                feature_keys=feature_keys,
            )
        elif label_source == "order_exit_pnl":
            iterator = _iter_order_exit_rows(
                records,
                order_events,
                up_threshold=up_threshold,
                down_threshold=down_threshold,
                feature_keys=feature_keys,
            )
        elif label_source == "policy_replay":
            iterator = _iter_policy_replay_rows(
                records,
                feature_keys=feature_keys,
                replay_cfg=replay_cfg,
                cost_cfg=cost_cfg,
                sample_mode=replay_sample_mode,
                long_only=bool(getattr(args, "long_only", False)),
            )
        else:
            iterator = _iter_order_pnl_rows(
                records,
                order_events,
                window_sec=order_window_sec,
                horizon_sec=horizon_sec,
                up_threshold=up_threshold,
                down_threshold=down_threshold,
                feature_keys=feature_keys,
            )
        for row in iterator:
            _inject_categoricals(
                row,
                symbols_onehot=symbols_onehot,
                session_onehot=include_session_onehot,
            )
            writer.writerow(row)
    if label_source == "policy_replay" and getattr(args, "metadata_output", None):
        metadata_payload = {
            "prediction_contract": "action_conditional_pnl_winprob",
            "output_labels": ["p_long_win", "p_short_win"],
            "replay_step_hz": replay_cfg.step_hz,
            "replay_sample_mode": replay_sample_mode,
            "fill_cost_model": dataclasses.asdict(cost_cfg),
            "replay_engine_config": dataclasses.asdict(replay_cfg),
            "forced_exit_taxonomy": {
                "forced_risk_exit": sorted(_FORCED_RISK_REASONS),
                "forced_time_exit": sorted(_FORCED_TIME_REASONS),
                "strategy_exit": "all_other_exit_reasons",
            },
        }
        Path(str(args.metadata_output)).write_text(
            json.dumps(metadata_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(f"written:{output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export feature snapshots to labeled CSV.")
    parser.add_argument("--stream", default="events:features", help="Redis stream name.")
    parser.add_argument("--output", default="prediction_dataset.csv", help="Output CSV path.")
    parser.add_argument("--limit", type=int, default=None, help="Max stream entries to read.")
    parser.add_argument(
        "--tail-count",
        type=int,
        default=50000,
        help="Load only the most recent N entries from the stream (fast). Set to 0 to disable.",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=24.0,
        help="Look back window in hours (used to filter snapshots when tailing).",
    )
    parser.add_argument("--horizon-sec", type=float, default=300.0, help="Label horizon in seconds.")
    parser.add_argument("--up-threshold", type=float, default=0.001, help="Up label return threshold.")
    parser.add_argument("--down-threshold", type=float, default=-0.001, help="Down label return threshold.")
    parser.add_argument(
        "--label-source",
        default="future_return",
        choices=["future_return", "tp_sl", "order_fill", "order_pnl", "order_exit_pnl", "policy_replay"],
        help="Label source: future_return, tp_sl, order_fill, order_pnl, order_exit_pnl, or policy_replay.",
    )
    parser.add_argument(
        "--order-stream",
        default="events:order",
        help="Order stream for order_fill labels.",
    )
    parser.add_argument("--order-limit", type=int, default=None, help="Max order events to read.")
    parser.add_argument(
        "--order-source",
        default="redis",
        choices=["redis", "timescale"],
        help="Order event source (redis or timescale).",
    )
    parser.add_argument("--timescale-url", default=None, help="Timescale URL for order events.")
    parser.add_argument("--tenant-id", default=None, help="Tenant id for Timescale order events.")
    parser.add_argument("--bot-id", default=None, help="Bot id for Timescale order events.")
    parser.add_argument("--exchange", default=None, help="Exchange filter for Timescale order events.")
    parser.add_argument(
        "--order-window-sec",
        type=float,
        default=30.0,
        help="Max seconds after snapshot to match an order fill.",
    )
    parser.add_argument(
        "--order-status",
        default="filled",
        help="Order status to match for labels (default: filled).",
    )
    parser.add_argument(
        "--features",
        default=",".join(DEFAULT_FEATURES),
        help="Comma-separated feature keys to export.",
    )
    parser.add_argument(
        "--include-symbol-onehot",
        action="store_true",
        help="Add one-hot symbol columns (symbol_<SYM>=0/1).",
    )
    parser.add_argument(
        "--include-session-onehot",
        action="store_true",
        help="Add one-hot session columns based on UTC hour (session_us/europe/asia).",
    )
    parser.add_argument(
        "--features-config",
        default=None,
        help="Path to JSON config with feature_keys/class_labels.",
    )
    parser.add_argument("--redis-url", default=None, help="Override Redis URL.")
    parser.add_argument("--metadata-output", default=None, help="Optional replay metadata JSON output path.")
    parser.add_argument(
        "--replay-step-hz",
        type=float,
        default=4.0,
        help="Deterministic replay cadence in Hz (4.0 default, 1.0 fallback).",
    )
    parser.add_argument(
        "--replay-sample-mode",
        default="periodic",
        choices=["periodic", "candidate_only"],
        help="Replay sample mode: periodic (default) or candidate_only.",
    )
    parser.add_argument("--half-spread-bps", type=float, default=2.0, help="Replay half-spread bps.")
    parser.add_argument("--slippage-bps", type=float, default=2.0, help="Replay slippage bps.")
    parser.add_argument("--fee-bps-entry", type=float, default=5.5, help="Replay entry fee bps.")
    parser.add_argument("--fee-bps-exit", type=float, default=5.5, help="Replay exit fee bps.")
    parser.add_argument("--replay-max-horizon-sec", type=float, default=300.0, help="Replay max horizon in seconds.")
    parser.add_argument("--replay-max-age-sec", type=float, default=300.0, help="Replay max age protective exit in seconds.")
    parser.add_argument("--replay-stop-loss-bps", type=float, default=60.0, help="Guardian stop-loss threshold in bps.")
    parser.add_argument("--replay-take-profit-bps", type=float, default=90.0, help="Guardian take-profit threshold in bps.")
    parser.add_argument(
        "--replay-trailing-activation-bps",
        type=float,
        default=20.0,
        help="Trailing stop activation threshold in bps.",
    )
    parser.add_argument("--replay-trailing-bps", type=float, default=25.0, help="Trailing stop retrace threshold in bps.")
    parser.add_argument(
        "--replay-breakeven-activation-bps",
        type=float,
        default=12.0,
        help="Breakeven activation threshold in bps.",
    )
    parser.add_argument(
        "--replay-breakeven-buffer-bps",
        type=float,
        default=3.0,
        help="Breakeven stop buffer threshold in bps.",
    )
    parser.add_argument(
        "--replay-profit-lock-activation-bps",
        type=float,
        default=25.0,
        help="Profit lock activation threshold in bps.",
    )
    parser.add_argument(
        "--replay-profit-lock-retrace-bps",
        type=float,
        default=8.0,
        help="Profit lock retrace threshold in bps.",
    )
    parser.add_argument("--replay-hard-stop-pct", type=float, default=2.0, help="Emergency hard stop percent.")
    parser.add_argument("--replay-deep-underwater-pct", type=float, default=1.0, help="Deep underwater emergency percent.")
    parser.add_argument("--replay-time-to-work-sec", type=float, default=120.0, help="Time-to-work forced exit seconds.")
    parser.add_argument("--replay-mfe-min-bps", type=float, default=6.0, help="Minimum favorable excursion for time-to-work exit.")
    parser.add_argument(
        "--market-type",
        choices=["perp", "spot"],
        default=None,
        help="Market type. 'spot' auto-sets --long-only and spot fee defaults (10 bps).",
    )
    parser.add_argument(
        "--long-only",
        action="store_true",
        help="Skip short-side replay (for spot markets).",
    )
    args = parser.parse_args()
    # --market-type spot implies --long-only and spot fee defaults
    if args.market_type == "spot":
        args.long_only = True
        if args.fee_bps_entry == 5.5:  # only override if user didn't set explicitly
            args.fee_bps_entry = 10.0
        if args.fee_bps_exit == 5.5:
            args.fee_bps_exit = 10.0
    if args.tail_count is not None and int(args.tail_count) <= 0:
        args.tail_count = None
    if args.features_config:
        args.features = _load_feature_keys(args.features_config)
    else:
        args.features = [item.strip() for item in args.features.split(",") if item.strip()]
    asyncio.run(_run(args))


async def _load_order_events(
    redis_client,
    stream: str,
    limit: Optional[int],
    status: str,
) -> Dict[str, List[dict]]:
    records: Dict[str, List[dict]] = {}
    cursor = "-"
    remaining = limit
    while True:
        count = 1000
        if remaining is not None:
            count = min(count, remaining)
        entries = await redis_client.xrange(stream, min=cursor, max="+", count=count)
        if not entries:
            break
        for entry_id, payload in entries:
            if cursor != "-" and entry_id == cursor:
                continue
            message = decode_message(payload)
            if message.get("event_type") != "order":
                continue
            order = message.get("payload") or {}
            if status and (order.get("status") or "").lower() != status.lower():
                continue
            symbol = message.get("symbol") or order.get("symbol")
            if not symbol:
                continue
            ts = _parse_iso_ts(message.get("timestamp"))
            if ts is None:
                continue
            side = order.get("side")
            if not side:
                continue
            fill_price = coerce_float(order.get("fill_price"))
            position_effect = order.get("position_effect")
            realized_pnl = coerce_float(order.get("realized_pnl"))
            realized_pnl_pct = coerce_float(order.get("realized_pnl_pct"))
            entry_timestamp = coerce_float(order.get("entry_timestamp"))
            entry_price = coerce_float(order.get("entry_price"))
            size = coerce_float(order.get("size"))
            records.setdefault(symbol, []).append(
                {
                    "timestamp": ts,
                    "side": str(side).lower(),
                    "fill_price": fill_price,
                    "position_effect": position_effect,
                    "realized_pnl": realized_pnl,
                    "realized_pnl_pct": realized_pnl_pct,
                    "entry_timestamp": entry_timestamp,
                    "entry_price": entry_price,
                    "size": size,
                }
            )
        cursor = entries[-1][0]
        if remaining is not None:
            remaining -= len(entries)
            if remaining <= 0:
                break
    for symbol, items in records.items():
        items.sort(key=lambda item: item["timestamp"])
    return records


async def _load_order_events_timescale(
    timescale_url: str,
    tenant_id: str,
    bot_id: str,
    limit: Optional[int],
    status: str,
    exchange: Optional[str] = None,
) -> Dict[str, List[dict]]:
    pool = await asyncpg.create_pool(timescale_url)
    try:
        query = (
            "SELECT symbol, exchange, ts, payload FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2"
        )
        params: list[object] = [tenant_id, bot_id]
        if exchange:
            query += " AND exchange=$3"
            params.append(exchange)
        if status:
            key = len(params) + 1
            query += f" AND payload->>'status'=${key}"
            params.append(status)
        query += " ORDER BY ts ASC"
        if limit:
            key = len(params) + 1
            query += f" LIMIT ${key}"
            params.append(limit)
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
    finally:
        await pool.close()
    records: Dict[str, List[dict]] = {}
    for row in rows:
        event = _parse_timescale_order_row(dict(row))
        if not event:
            continue
        symbol = event.pop("symbol", None)
        if not symbol:
            continue
        records.setdefault(symbol, []).append(event)
    for symbol, items in records.items():
        items.sort(key=lambda item: item["timestamp"])
    return records


def _parse_timescale_order_row(row: dict) -> Optional[dict]:
    payload = row.get("payload")
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    ts = row.get("ts")
    timestamp = None
    if hasattr(ts, "timestamp"):
        timestamp = float(ts.timestamp())
    elif ts is not None:
        try:
            timestamp = float(ts)
        except (TypeError, ValueError):
            timestamp = None
    return {
        "symbol": row.get("symbol") or payload.get("symbol"),
        "timestamp": timestamp,
        "side": payload.get("side"),
        "fill_price": coerce_float(payload.get("fill_price")),
        "position_effect": payload.get("position_effect"),
        "realized_pnl": coerce_float(payload.get("realized_pnl")),
        "realized_pnl_pct": coerce_float(payload.get("realized_pnl_pct")),
        "entry_timestamp": coerce_float(payload.get("entry_timestamp")),
        "entry_price": coerce_float(payload.get("entry_price")),
        "size": coerce_float(payload.get("size")),
    }


def _parse_iso_ts(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        tm = time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return float(calendar.timegm(tm))


def _label_from_orders(
    order_ts: List[float],
    orders: List[dict],
    ts: float,
    window_sec: float,
) -> Optional[str]:
    if not order_ts:
        return None
    cutoff = ts + window_sec
    idx = _find_future_index(order_ts, ts, 0)
    if idx is None:
        return None
    if order_ts[idx] > cutoff:
        return None
    side = orders[idx].get("side") or ""
    side = str(side).lower()
    if side in {"buy", "long"}:
        return "up"
    if side in {"sell", "short"}:
        return "down"
    return "flat"


if __name__ == "__main__":
    main()
