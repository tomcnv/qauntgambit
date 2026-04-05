#!/usr/bin/env python3
"""Compare exchange trades with local order_events.

Usage (defaults to Bybit, last 48h):
  quantgambit-python/venv/bin/python scripts/compare_exchange_trades.py --hours 48 --limit 200
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from quantgambit.storage.secrets import SecretsProvider
from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client
from quantgambit.execution.ccxt_clients import _normalize_symbol as _ccxt_normalize_symbol


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or not str(val).strip():
        return default
    return str(val)


def _normalize_internal_symbol(symbol: str) -> str:
    cleaned = symbol.replace("/", "").replace("-", "").replace(":USDT", "")
    return cleaned.replace("USDTUSDT", "USDT")


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _choose_best_event(existing: dict, candidate: dict) -> dict:
    if existing is None:
        return candidate
    existing_pnl = existing.get("net_pnl") if existing.get("net_pnl") is not None else existing.get("realized_pnl")
    candidate_pnl = candidate.get("net_pnl") if candidate.get("net_pnl") is not None else candidate.get("realized_pnl")
    if candidate_pnl is not None and (existing_pnl is None or existing_pnl == 0):
        return candidate
    existing_close = existing.get("position_effect") == "close"
    candidate_close = candidate.get("position_effect") == "close"
    if candidate_close and not existing_close:
        return candidate
    existing_filled = existing.get("status") in {"filled", "closed"}
    candidate_filled = candidate.get("status") in {"filled", "closed"}
    if candidate_filled and not existing_filled:
        return candidate
    return existing


async def _fetch_local_orders(
    dsn: str,
    tenant_id: str,
    bot_id: str,
    start_ts: datetime,
) -> Dict[str, dict]:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT ts, symbol, payload
            FROM order_events
            WHERE tenant_id=$1 AND bot_id=$2 AND ts >= $3
            """,
            tenant_id,
            bot_id,
            start_ts,
        )
    finally:
        await conn.close()

    by_order: Dict[str, dict] = {}
    for row in rows:
        raw_payload = row["payload"] or {}
        if isinstance(raw_payload, dict):
            payload = dict(raw_payload)
        else:
            try:
                payload = dict(raw_payload)
            except Exception:
                try:
                    import json
                    payload = json.loads(raw_payload)
                except Exception:
                    payload = {}
        order_id = payload.get("order_id") or payload.get("client_order_id")
        if not order_id:
            continue
        entry_fee_usd = _to_float(payload.get("entry_fee_usd"))
        exit_fee_usd = _to_float(payload.get("fee_usd") or payload.get("fee"))
        total_fees_usd = _to_float(payload.get("total_fees_usd"))
        if total_fees_usd is None and (entry_fee_usd is not None or exit_fee_usd is not None):
            total_fees_usd = (entry_fee_usd or 0.0) + (exit_fee_usd or 0.0)
        event = {
            "order_id": str(order_id),
            "client_order_id": payload.get("client_order_id"),
            "symbol": row.get("symbol") or payload.get("symbol"),
            "status": (payload.get("status") or "").lower(),
            "fill_price": _to_float(payload.get("fill_price")),
            "fee_usd": exit_fee_usd,
            "entry_fee_usd": entry_fee_usd,
            "total_fees_usd": total_fees_usd,
            "filled_size": _to_float(payload.get("filled_size") or payload.get("size")),
            "position_effect": payload.get("position_effect"),
            "realized_pnl": _to_float(payload.get("realized_pnl")),
            "net_pnl": _to_float(payload.get("net_pnl")),
            "gross_pnl": _to_float(payload.get("gross_pnl")),
            "ts": row.get("ts"),
        }
        existing = by_order.get(event["order_id"])
        by_order[event["order_id"]] = _choose_best_event(existing, event)
    return by_order


async def _fetch_exchange_trades(
    exchange: str,
    secret_id: str,
    symbols: List[str],
    since_ms: int,
    limit: int,
    testnet: bool,
    demo: bool,
) -> List[dict]:
    provider = SecretsProvider()
    creds = provider.get_credentials(secret_id)
    if creds is None:
        raise RuntimeError(f"Could not load credentials for secret_id={secret_id}")
    ccxt_creds = CcxtCredentials(
        api_key=creds.api_key,
        secret_key=creds.secret_key,
        passphrase=creds.passphrase,
        testnet=testnet,
        demo=demo,
    )
    client = build_ccxt_client(exchange, ccxt_creds, market_type="perp", margin_mode="isolated")
    trades: List[dict] = []
    try:
        for symbol in symbols:
            ccxt_symbol = _ccxt_normalize_symbol(symbol, client.symbol_format)
            try:
                fetched = await client.client.fetch_my_trades(
                    symbol=ccxt_symbol,
                    since=since_ms,
                    limit=limit,
                )
                for trade in fetched or []:
                    info = trade.get("info") or {}
                    order_id = trade.get("order") or info.get("orderId") or info.get("orderID")
                    trade_id = trade.get("id") or info.get("execId") or info.get("tradeId")
                    fee = trade.get("fee") or {}
                    fee_cost = fee.get("cost") if isinstance(fee, dict) else None
                    trades.append(
                        {
                            "order_id": str(order_id) if order_id else None,
                            "trade_id": str(trade_id) if trade_id else None,
                            "symbol": _normalize_internal_symbol(trade.get("symbol") or symbol),
                            "timestamp": trade.get("timestamp"),
                            "price": _to_float(trade.get("price")),
                            "amount": _to_float(trade.get("amount")),
                            "fee": _to_float(fee_cost),
                        }
                    )
            except Exception as exc:
                print(f"[warn] fetch_my_trades failed for {ccxt_symbol}: {exc}")
    finally:
        await client.close()
    return trades


def _aggregate_exchange_trades(trades: List[dict]) -> Dict[str, dict]:
    grouped: Dict[str, dict] = {}
    for trade in trades:
        order_id = trade.get("order_id")
        if not order_id:
            continue
        entry = grouped.get(order_id)
        if entry is None:
            entry = {
                "order_id": order_id,
                "symbol": trade.get("symbol"),
                "amount": 0.0,
                "fee": 0.0,
                "notional": 0.0,
                "min_ts": trade.get("timestamp"),
                "max_ts": trade.get("timestamp"),
            }
            grouped[order_id] = entry
        amount = trade.get("amount") or 0.0
        price = trade.get("price") or 0.0
        fee = trade.get("fee") or 0.0
        entry["amount"] += amount
        entry["fee"] += fee
        entry["notional"] += amount * price
        ts = trade.get("timestamp")
        if ts is not None:
            entry["min_ts"] = min(entry["min_ts"], ts) if entry["min_ts"] is not None else ts
            entry["max_ts"] = max(entry["max_ts"], ts) if entry["max_ts"] is not None else ts
    for entry in grouped.values():
        amount = entry["amount"]
        entry["avg_price"] = (entry["notional"] / amount) if amount else None
    return grouped


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
            ret_code = payload.get("retCode")
            if ret_code not in (0, "0"):
                # Avoid silently returning an empty list on API errors (common in demo/testnet).
                print(
                    f"[warn] bybit v5 execution/list failed for {symbol}: "
                    f"retCode={ret_code} retMsg={payload.get('retMsg')!r}"
                )
                break
            result = payload.get("result") or {}
            items = result.get("list") or []
            for item in items:
                trades.append(
                    {
                        "order_id": item.get("orderId"),
                        "trade_id": item.get("execId"),
                        "symbol": item.get("symbol") or symbol,
                        "timestamp": _to_float(item.get("execTime")),
                        "price": _to_float(item.get("execPrice")),
                        "amount": _to_float(item.get("execQty")),
                        "fee": _to_float(item.get("execFee")),
                    }
                )
            cursor = result.get("nextPageCursor")
            if not cursor or not items:
                break
    return trades


def _compare(
    local_orders: Dict[str, dict],
    exchange_orders: Dict[str, dict],
    price_tolerance_bps: float = 5.0,
    fee_tolerance_usd: float = 0.5,
    size_tolerance: float = 1e-6,
) -> Tuple[List[str], List[str]]:
    missing_local = []
    mismatches = []
    for order_id, ex in exchange_orders.items():
        local = local_orders.get(order_id)
        if local is None:
            missing_local.append(order_id)
            continue
        price_diff = None
        if ex.get("avg_price") is not None and local.get("fill_price") is not None:
            if local["fill_price"] > 0:
                price_diff = abs(ex["avg_price"] - local["fill_price"]) / local["fill_price"] * 10000.0
        fee_diff = None
        if ex.get("fee") is not None and local.get("fee_usd") is not None:
            fee_diff = abs(ex["fee"] - local["fee_usd"])
        size_diff = None
        if ex.get("amount") is not None and local.get("filled_size") is not None:
            size_diff = abs(ex["amount"] - local["filled_size"])
        if (
            (price_diff is not None and price_diff > price_tolerance_bps)
            or (fee_diff is not None and fee_diff > fee_tolerance_usd)
            or (size_diff is not None and size_diff > size_tolerance)
        ):
            mismatches.append(
                f"{order_id} symbol={ex.get('symbol')} "
                f"price_bps={price_diff:.2f} fee_diff={fee_diff:.4f} size_diff={size_diff:.8f}"
            )
    return missing_local, mismatches


async def main() -> int:
    parser = argparse.ArgumentParser(description="Compare exchange trades vs local order_events")
    parser.add_argument("--exchange", default=_env("ACTIVE_EXCHANGE", "bybit"), help="Exchange id")
    parser.add_argument("--secret-id", default=_env("EXCHANGE_SECRET_ID"), help="Secrets store id")
    parser.add_argument("--tenant-id", default=_env("TENANT_ID") or _env("DEFAULT_TENANT_ID"), help="Tenant ID")
    parser.add_argument("--bot-id", default=_env("BOT_ID") or _env("DEFAULT_BOT_ID"), help="Bot ID")
    parser.add_argument("--hours", type=float, default=48.0, help="Lookback window in hours")
    parser.add_argument("--limit", type=int, default=200, help="Max trades per symbol")
    parser.add_argument("--symbols", default=_env("ORDERBOOK_SYMBOLS", ""), help="Comma-separated symbols")
    parser.add_argument("--dsn", default=_env("BOT_TIMESCALE_URL"), help="Timescale/Postgres DSN")
    parser.add_argument("--testnet", action="store_true", default=_env("BYBIT_TESTNET", "false").lower() in {"1", "true", "yes"})
    parser.add_argument("--demo", action="store_true", default=False, help="Bybit demo mode")
    parser.add_argument("--bybit-v5", action="store_true", default=False, help="Use Bybit v5 execution REST API (demo-compatible)")
    parser.add_argument("--bybit-category", default="linear", help="Bybit category: linear, inverse, spot, option")
    parser.add_argument("--bybit-base-url", default="", help="Override Bybit base URL")
    parser.add_argument("--bybit-max-pages", type=int, default=5, help="Max pages per symbol for Bybit v5 execution list")
    args = parser.parse_args()

    if not args.secret_id:
        print("Missing EXCHANGE_SECRET_ID or --secret-id")
        return 2
    if not args.dsn:
        print("Missing BOT_TIMESCALE_URL or --dsn")
        return 2
    if not args.tenant_id or not args.bot_id:
        print("Missing tenant/bot id (TENANT_ID/BOT_ID or defaults)")
        return 2

    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    if not symbols:
        print("No symbols provided (ORDERBOOK_SYMBOLS or --symbols).")
        return 2

    end_ms = int(time.time() * 1000)
    window_ms = int(args.hours * 3600 * 1000)
    if window_ms <= 0:
        print("Invalid --hours (must be > 0)")
        return 2
    since_ms = end_ms - window_ms
    start_ts = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)

    # Bybit V5 execution/list enforces startTime..endTime <= 7 days (strictly).
    if args.exchange.lower() == "bybit" and (args.bybit_v5 or args.demo):
        max_range_ms = 7 * 24 * 60 * 60 * 1000
        if (end_ms - since_ms) > max_range_ms:
            requested_days = (end_ms - since_ms) / (24 * 60 * 60 * 1000)
            print(
                f"[error] Bybit v5 execution/list requires startTime..endTime <= 7 days. "
                f"Requested lookback: {args.hours}h ({requested_days:.2f}d)."
            )
            return 2

    print(f"Comparing exchange trades vs local order_events since {start_ts.isoformat()}")
    print(f"Exchange={args.exchange} symbols={symbols} limit={args.limit} testnet={args.testnet}")

    local_orders = await _fetch_local_orders(
        args.dsn, args.tenant_id, args.bot_id, start_ts
    )
    exchange_trades: List[dict] = []
    if args.exchange.lower() == "bybit" and (args.bybit_v5 or args.demo):
        base_url = args.bybit_base_url.strip()
        if not base_url:
            if args.demo:
                base_url = "https://api-demo.bybit.com"
            elif args.testnet:
                base_url = "https://api-testnet.bybit.com"
            else:
                base_url = "https://api.bybit.com"
        provider = SecretsProvider()
        creds = provider.get_credentials(args.secret_id)
        if creds is None:
            raise RuntimeError(f"Could not load credentials for secret_id={args.secret_id}")
        exchange_trades = _fetch_bybit_v5_execs(
            api_key=creds.api_key,
            api_secret=creds.secret_key,
            symbols=symbols,
            category=args.bybit_category,
            start_ms=since_ms,
            end_ms=end_ms,
            limit=args.limit,
            base_url=base_url,
            max_pages=args.bybit_max_pages,
        )
    else:
        exchange_trades = await _fetch_exchange_trades(
            args.exchange,
            args.secret_id,
            symbols,
            since_ms,
            args.limit,
            testnet=args.testnet,
            demo=args.demo,
        )
    exchange_orders = _aggregate_exchange_trades(exchange_trades)

    missing_local, mismatches = _compare(local_orders, exchange_orders)

    print(f"Local orders: {len(local_orders)}")
    print(f"Exchange orders (aggregated): {len(exchange_orders)}")
    print(f"Missing locally: {len(missing_local)}")
    print(f"Mismatches: {len(mismatches)}")

    if missing_local:
        print("Missing order_ids (first 20):")
        for oid in missing_local[:20]:
            print(f"  - {oid}")
    if mismatches:
        print("Mismatches (first 20):")
        for line in mismatches[:20]:
            print(f"  - {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
