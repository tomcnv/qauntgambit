#!/usr/bin/env python3
"""Override local order_events with exchange execution aggregates.

Usage:
  PYTHONPATH=quantgambit-python quantgambit-python/venv/bin/python \
    scripts/override_exchange_trades.py --exchange bybit --demo --bybit-v5 \
    --secret-id <secret> --dsn <dsn> --tenant-id <tenant> --bot-id <bot> \
    --symbols BTCUSDT,ETHUSDT --since "2026-02-05T11:27:23Z"
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import asyncpg

from quantgambit.storage.secrets import SecretsProvider


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or not str(val).strip():
        return default
    return str(val)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(ts: str) -> datetime:
    raw = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)


def _bybit_v5_signature(
    api_key: str,
    api_secret: str,
    query_string: str,
    recv_window: str,
    timestamp_ms: str,
) -> str:
    payload = f"{timestamp_ms}{api_key}{recv_window}{query_string}"
    return hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _bybit_v5_get(
    base_url: str,
    api_key: str,
    api_secret: str,
    params: Dict[str, Any],
    recv_window_ms: int = 5000,
) -> dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    timestamp_ms = str(int(time.time() * 1000))
    recv_window = str(recv_window_ms)
    signature = _bybit_v5_signature(api_key, api_secret, query, recv_window, timestamp_ms)
    url = f"{base_url}/v5/execution/list?{query}"
    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp_ms,
        "X-BAPI-RECV-WINDOW": recv_window,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8"))


def _fetch_bybit_v5_execs(
    api_key: str,
    api_secret: str,
    symbols: List[str],
    category: str,
    start_ms: int,
    end_ms: int,
    limit: int,
    base_url: str,
    max_pages: int = 5,
) -> List[dict]:
    trades: List[dict] = []
    for symbol in symbols:
        cursor = None
        for _ in range(max_pages):
            params = {
                "category": category,
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": limit,
                "cursor": cursor,
            }
            payload = _bybit_v5_get(base_url, api_key, api_secret, params)
            result = payload.get("result") or {}
            items = result.get("list") or []
            for item in items:
                trades.append(
                    {
                        "order_id": item.get("orderId"),
                        "client_order_id": item.get("orderLinkId"),
                        "trade_id": item.get("execId"),
                        "symbol": item.get("symbol") or symbol,
                        "timestamp": _to_float(item.get("execTime")),
                        "price": _to_float(item.get("execPrice")),
                        "amount": _to_float(item.get("execQty")),
                        "fee": _to_float(item.get("execFee")),
                        "side": item.get("side"),
                        "exec_pnl": _to_float(item.get("execPnl")),
                    }
                )
            cursor = result.get("nextPageCursor")
            if not cursor or not items:
                break
    return trades


def _aggregate_by_order(trades: List[dict]) -> Dict[str, dict]:
    grouped: Dict[str, dict] = {}
    for trade in trades:
        order_id = trade.get("order_id")
        if not order_id:
            continue
        entry = grouped.get(order_id)
        if entry is None:
            entry = {
                "order_id": order_id,
                "client_order_id": trade.get("client_order_id"),
                "symbol": trade.get("symbol"),
                "side": trade.get("side"),
                "amount": 0.0,
                "fee": 0.0,
                "exec_pnl": 0.0,
                "notional": 0.0,
                "max_ts": trade.get("timestamp"),
            }
            grouped[order_id] = entry
        amount = trade.get("amount") or 0.0
        price = trade.get("price") or 0.0
        fee = trade.get("fee") or 0.0
        exec_pnl = trade.get("exec_pnl") or 0.0
        entry["amount"] += amount
        entry["fee"] += fee
        entry["exec_pnl"] += exec_pnl
        entry["notional"] += amount * price
        ts = trade.get("timestamp")
        if ts is not None:
            entry["max_ts"] = max(entry["max_ts"], ts) if entry["max_ts"] is not None else ts
        if not entry.get("side") and trade.get("side"):
            entry["side"] = trade.get("side")
        if not entry.get("client_order_id") and trade.get("client_order_id"):
            entry["client_order_id"] = trade.get("client_order_id")
    for entry in grouped.values():
        amount = entry["amount"]
        entry["avg_price"] = (entry["notional"] / amount) if amount else None
    return grouped


def _derive_close_updates(aggregated: Dict[str, dict]) -> Dict[str, dict]:
    """Derive close PnL per order by simulating position state from executions.

    Returns mapping of order_id -> updates dict (position_effect, gross/net pnl, exit_price).
    """
    by_symbol: Dict[str, List[dict]] = {}
    for entry in aggregated.values():
        symbol = entry.get("symbol") or ""
        by_symbol.setdefault(symbol, []).append(entry)
    updates: Dict[str, dict] = {}
    for symbol, entries in by_symbol.items():
        # Sort by execution time
        entries.sort(key=lambda e: e.get("max_ts") or 0)
        pos_size = 0.0  # positive=long, negative=short
        pos_avg = 0.0
        pos_fee = 0.0  # accumulated entry fees for current position
        for entry in entries:
            side = (entry.get("side") or "").lower()
            qty = float(entry.get("amount") or 0.0)
            price = float(entry.get("avg_price") or 0.0)
            fee = float(entry.get("fee") or 0.0)
            if qty <= 0 or price <= 0:
                continue
            signed_qty = qty if side == "buy" else -qty
            if pos_size == 0:
                pos_size = signed_qty
                pos_avg = price
                pos_fee = fee
                continue
            same_dir = (pos_size > 0 and signed_qty > 0) or (pos_size < 0 and signed_qty < 0)
            if same_dir:
                new_size = pos_size + signed_qty
                if new_size != 0:
                    pos_avg = (abs(pos_size) * pos_avg + qty * price) / abs(new_size)
                pos_size = new_size
                pos_fee += fee
                continue
            # Closing (fully or partially)
            close_qty = min(abs(pos_size), abs(signed_qty))
            gross_pnl = (price - pos_avg) * close_qty if pos_size > 0 else (pos_avg - price) * close_qty
            exit_fee = fee * (close_qty / abs(signed_qty)) if abs(signed_qty) > 0 else 0.0
            entry_fee_alloc = pos_fee * (close_qty / abs(pos_size)) if abs(pos_size) > 0 else 0.0
            net_pnl = gross_pnl - exit_fee - entry_fee_alloc
            updates[entry["order_id"]] = {
                "position_effect": "close",
                "reason": "exchange_backfill",
                "exit_price": price,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "realized_pnl": net_pnl,
            }
            # Update remaining position
            remaining = pos_size + signed_qty
            pos_fee = max(pos_fee - entry_fee_alloc, 0.0)
            if abs(remaining) < 1e-12:
                pos_size = 0.0
                pos_avg = 0.0
                pos_fee = 0.0
            else:
                # If flip, start new position with remaining size at current price
                if abs(signed_qty) > abs(pos_size):
                    new_open_qty = abs(signed_qty) - close_qty
                    pos_size = remaining
                    pos_avg = price
                    pos_fee = max(fee - exit_fee, 0.0)
                else:
                    pos_size = remaining
    return updates


async def _fetch_local_payloads(
    dsn: str,
    tenant_id: str,
    bot_id: str,
    order_ids: List[str],
) -> Dict[str, dict]:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT payload
            FROM order_events
            WHERE tenant_id=$1 AND bot_id=$2
              AND (payload->>'order_id') = ANY($3::text[])
            """,
            tenant_id,
            bot_id,
            order_ids,
        )
    finally:
        await conn.close()
    results: Dict[str, dict] = {}
    for row in rows:
        payload = row.get("payload") if isinstance(row, dict) else row[0]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        order_id = payload.get("order_id")
        if not order_id:
            continue
        # prefer payloads with pnl/close
        existing = results.get(order_id)
        if existing is None:
            results[order_id] = payload
        else:
            new_pnl = payload.get("net_pnl") or payload.get("realized_pnl")
            old_pnl = existing.get("net_pnl") or existing.get("realized_pnl")
            new_close = payload.get("position_effect") == "close"
            old_close = existing.get("position_effect") == "close"
            if new_close and not old_close:
                results[order_id] = payload
            elif new_pnl and not old_pnl:
                results[order_id] = payload
    return results


async def _override_order_payload(
    dsn: str,
    tenant_id: str,
    bot_id: str,
    order_id: str,
    updates: Dict[str, Any],
) -> None:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        payload_expr = "payload"
        params = [tenant_id, bot_id, order_id]
        for key, value in updates.items():
            params.append(json.dumps(value))
            payload_expr = f"jsonb_set({payload_expr}, '{{{key}}}', ${len(params)}::jsonb, true)"
        query = (
            f"UPDATE order_events SET payload = {payload_expr} "
            "WHERE tenant_id=$1 AND bot_id=$2 AND (payload->>'order_id')=$3"
        )
        await conn.execute(query, *params)
    finally:
        await conn.close()


def _ts_to_epoch_seconds(ts: Optional[float]) -> float:
    if ts is None:
        return time.time()
    try:
        ts_val = float(ts)
    except (TypeError, ValueError):
        return time.time()
    # Bybit execTime is in ms
    if ts_val > 1e12:
        return ts_val / 1000.0
    return ts_val


async def _insert_order_event(
    dsn: str,
    tenant_id: str,
    bot_id: str,
    symbol: str,
    exchange: str,
    ts_sec: float,
    payload: Dict[str, Any],
) -> None:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute(
            """
            INSERT INTO order_events (tenant_id, bot_id, symbol, exchange, ts, payload)
            VALUES ($1, $2, $3, $4, to_timestamp($5), $6)
            """,
            tenant_id,
            bot_id,
            symbol,
            exchange,
            ts_sec,
            json.dumps(payload),
        )
    finally:
        await conn.close()

async def main() -> int:
    parser = argparse.ArgumentParser(description="Override local order_events with exchange execution aggregates")
    parser.add_argument("--exchange", default=_env("ACTIVE_EXCHANGE", "bybit"), help="Exchange id")
    parser.add_argument("--secret-id", default=_env("EXCHANGE_SECRET_ID"), help="Secrets store id")
    parser.add_argument("--tenant-id", default=_env("TENANT_ID") or _env("DEFAULT_TENANT_ID"), help="Tenant ID")
    parser.add_argument("--bot-id", default=_env("BOT_ID") or _env("DEFAULT_BOT_ID"), help="Bot ID")
    parser.add_argument("--symbols", default=_env("ORDERBOOK_SYMBOLS", ""), help="Comma-separated symbols")
    parser.add_argument("--dsn", default=_env("BOT_TIMESCALE_URL"), help="Timescale/Postgres DSN")
    parser.add_argument("--hours", type=float, default=1.0, help="Lookback window in hours")
    parser.add_argument("--since", default="", help="ISO timestamp override")
    parser.add_argument("--demo", action="store_true", default=False, help="Bybit demo mode")
    parser.add_argument("--bybit-v5", action="store_true", default=False, help="Use Bybit v5 execution REST API (demo-compatible)")
    parser.add_argument("--bybit-category", default="linear", help="Bybit category: linear, inverse, spot, option")
    parser.add_argument("--bybit-base-url", default="", help="Override Bybit base URL")
    parser.add_argument("--bybit-max-pages", type=int, default=5, help="Max pages per symbol for Bybit v5 execution list")
    parser.add_argument("--size-eps", type=float, default=1e-6, help="Size diff threshold")
    parser.add_argument("--insert-missing", action="store_true", default=False, help="Insert missing order_events from exchange executions")
    parser.add_argument("--derive-pnl", action="store_true", default=False, help="Derive close PnL from executions when exec_pnl is missing")
    args = parser.parse_args()

    if not args.secret_id or not args.dsn or not args.tenant_id or not args.bot_id:
        print("Missing required args (secret-id, dsn, tenant-id, bot-id)")
        return 2
    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    if not symbols:
        print("No symbols provided (ORDERBOOK_SYMBOLS or --symbols).")
        return 2

    if args.since:
        start_ts = _parse_iso(args.since)
    else:
        start_ts = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    since_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(time.time() * 1000)

    provider = SecretsProvider()
    creds = provider.get_credentials(args.secret_id)
    if creds is None:
        raise RuntimeError(f"Could not load credentials for secret_id={args.secret_id}")

    base_url = args.bybit_base_url.strip()
    if not base_url:
        if args.demo:
            base_url = "https://api-demo.bybit.com"
        else:
            base_url = "https://api.bybit.com"

    trades = _fetch_bybit_v5_execs(
        api_key=creds.api_key,
        api_secret=creds.secret_key,
        symbols=symbols,
        category=args.bybit_category,
        start_ms=since_ms,
        end_ms=end_ms,
        limit=200,
        base_url=base_url,
        max_pages=args.bybit_max_pages,
    )
    aggregated = _aggregate_by_order(trades)
    derived_updates = _derive_close_updates(aggregated) if args.derive_pnl else {}
    order_ids = list(aggregated.keys())
    local_payloads = await _fetch_local_payloads(args.dsn, args.tenant_id, args.bot_id, order_ids)

    overridden = 0
    inserted = 0
    for order_id, entry in aggregated.items():
        payload = local_payloads.get(order_id)
        if not payload:
            if not args.insert_missing:
                continue
            # Insert missing order_events from exchange executions
            avg_price = entry.get("avg_price")
            fee = entry.get("fee")
            exec_pnl = entry.get("exec_pnl")
            size = entry.get("amount") or 0.0
            ts_sec = _ts_to_epoch_seconds(entry.get("max_ts"))
            position_effect = None
            exit_price = None
            entry_price = None
            gross_pnl = None
            net_pnl = None
            realized_pnl = None
            if exec_pnl is not None and abs(exec_pnl) > 0:
                position_effect = "close"
                exit_price = avg_price
                gross_pnl = exec_pnl
                if fee is not None:
                    net_pnl = exec_pnl - fee
                    realized_pnl = net_pnl
                else:
                    net_pnl = exec_pnl
                    realized_pnl = exec_pnl
            else:
                position_effect = "open"
                entry_price = avg_price
            insert_payload = {
                "tenant_id": args.tenant_id,
                "symbol": entry.get("symbol"),
                "side": (entry.get("side") or "").lower(),
                "status": "filled",
                "reason": "exchange_backfill",
                "order_id": order_id,
                "client_order_id": entry.get("client_order_id"),
                "fill_price": avg_price,
                "size": size,
                "filled_size": size,
                "fee_usd": fee,
                "total_fees_usd": fee,
                "position_effect": position_effect,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "realized_pnl": realized_pnl,
            }
            await _insert_order_event(
                dsn=args.dsn,
                tenant_id=args.tenant_id,
                bot_id=args.bot_id,
                symbol=entry.get("symbol") or "",
                exchange=args.exchange,
                ts_sec=ts_sec,
                payload=insert_payload,
            )
            inserted += 1
            continue
        local_size = _to_float(payload.get("filled_size") or payload.get("size")) or 0.0
        exchange_size = entry.get("amount") or 0.0
        fee = entry.get("fee")
        avg_price = entry.get("avg_price")
        exec_pnl = entry.get("exec_pnl")
        updates: Dict[str, Any] = {}
        if abs(exchange_size - local_size) > args.size_eps:
            updates["size"] = exchange_size
            updates["filled_size"] = exchange_size
        if avg_price is not None:
            updates["fill_price"] = avg_price
        if fee is not None:
            updates["fee_usd"] = fee
            updates["total_fees_usd"] = fee
        # If exchange reports realized PnL, treat this as a close and backfill fields
        if exec_pnl is not None and abs(exec_pnl) > 0:
            updates["position_effect"] = "close"
            updates["reason"] = "exchange_backfill"
            if avg_price is not None:
                updates["exit_price"] = avg_price
            updates["gross_pnl"] = exec_pnl
            if fee is not None:
                updates["net_pnl"] = exec_pnl - fee
                updates["realized_pnl"] = exec_pnl - fee
            else:
                updates["net_pnl"] = exec_pnl
                updates["realized_pnl"] = exec_pnl
        elif args.derive_pnl and order_id in derived_updates:
            updates.update(derived_updates[order_id])
        # Also update exit_price if it's already a close event
        elif payload.get("position_effect") == "close" or payload.get("reason") in {"position_close", "strategic_exit", "exchange_reconcile"}:
            if avg_price is not None:
                updates["exit_price"] = avg_price

        if not updates:
            continue
        await _override_order_payload(
            dsn=args.dsn,
            tenant_id=args.tenant_id,
            bot_id=args.bot_id,
            order_id=order_id,
            updates=updates,
        )
        overridden += 1

    print(f"Override complete. Updated {overridden} order_events. Inserted {inserted} missing order_events.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
