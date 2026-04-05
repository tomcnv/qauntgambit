#!/usr/bin/env python3
"""Backfill missing exchange trades into local order_events.

Usage:
  PYTHONPATH=quantgambit-python quantgambit-python/venv/bin/python \
    scripts/backfill_exchange_trades.py --exchange bybit --demo --bybit-v5 \
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


async def _fetch_local_order_ids(
    dsn: str,
    tenant_id: str,
    bot_id: str,
    start_ts: datetime,
) -> set[str]:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT payload
            FROM order_events
            WHERE tenant_id=$1 AND bot_id=$2 AND ts >= $3
            """,
            tenant_id,
            bot_id,
            start_ts,
        )
    finally:
        await conn.close()
    existing: set[str] = set()
    for row in rows:
        payload = row.get("payload") if isinstance(row, dict) else row[0]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        order_id = payload.get("order_id") if isinstance(payload, dict) else None
        if order_id:
            existing.add(str(order_id))
    return existing


async def _insert_backfill_event(
    dsn: str,
    tenant_id: str,
    bot_id: str,
    exchange: str,
    symbol: str,
    ts: datetime,
    payload: dict,
) -> None:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute(
            """
            INSERT INTO order_events (tenant_id, bot_id, symbol, exchange, ts, payload)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            tenant_id,
            bot_id,
            symbol,
            exchange,
            ts,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
    finally:
        await conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing exchange trades into order_events")
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
    existing = await _fetch_local_order_ids(args.dsn, args.tenant_id, args.bot_id, start_ts)

    inserted = 0
    for order_id, entry in aggregated.items():
        if order_id in existing:
            continue
        avg_price = entry.get("avg_price")
        amount = entry.get("amount") or 0.0
        fee = entry.get("fee")
        exec_pnl = entry.get("exec_pnl")
        ts_ms = entry.get("max_ts")
        ts = datetime.fromtimestamp((ts_ms or end_ms) / 1000.0, tz=timezone.utc)
        side = (entry.get("side") or "").lower()
        payload = {
            "order_id": order_id,
            "client_order_id": entry.get("client_order_id"),
            "symbol": entry.get("symbol"),
            "status": "filled",
            "reason": "exchange_backfill",
            "side": "buy" if side == "buy" else ("sell" if side == "sell" else side),
            "size": amount,
            "filled_size": amount,
            "fill_price": avg_price,
            "fee_usd": fee,
            "total_fees_usd": fee,
            "exit_price": avg_price,
            "position_effect": "close" if exec_pnl not in (None, 0.0) else None,
            "gross_pnl": exec_pnl,
        }
        if exec_pnl is not None and fee is not None:
            payload["net_pnl"] = exec_pnl - fee
            payload["realized_pnl"] = payload["net_pnl"]
        elif exec_pnl is not None:
            payload["net_pnl"] = exec_pnl
            payload["realized_pnl"] = exec_pnl
        await _insert_backfill_event(
            dsn=args.dsn,
            tenant_id=args.tenant_id,
            bot_id=args.bot_id,
            exchange=args.exchange,
            symbol=entry.get("symbol") or "",
            ts=ts,
            payload=payload,
        )
        inserted += 1

    print(f"Backfill complete. Inserted {inserted} order_events.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
