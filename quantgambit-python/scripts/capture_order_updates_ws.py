"""Capture private WS order updates for OKX/Bybit/Binance."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from quantgambit.execution.order_updates_ws import (
    OkxOrderUpdateProvider,
    OkxWsCredentials,
    BybitOrderUpdateProvider,
    BybitWsCredentials,
    BinanceOrderUpdateProvider,
    BinanceWsCredentials,
    _parse_okx_order_update,
    _parse_bybit_order_update,
    _parse_binance_order_update,
    _parse_binance_spot_order_update,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture private order update payloads.")
    parser.add_argument("--exchange", choices=["okx", "bybit", "binance"], required=True)
    parser.add_argument("--market-type", choices=["perp", "spot"], default="perp")
    parser.add_argument("--output", default="exports/order_updates_ws.jsonl")
    parser.add_argument("--max-messages", type=int, default=50)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--okx-algo", action="store_true", help="Also subscribe to OKX orders-algo (if supported)")
    # Optional: place a test order (useful to trigger updates while capturing)
    parser.add_argument("--place-order", action="store_true", help="Place a quick market order to generate updates")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    parser.add_argument("--size", type=float, default=0.002)
    parser.add_argument("--leverage", type=int, default=5)
    parser.add_argument("--margin-mode", choices=["isolated", "cross"], default="isolated")
    return parser.parse_args()


async def _capture_okx(args: argparse.Namespace, writer) -> None:
    creds = OkxWsCredentials(
        api_key=os.environ.get("OKX_API_KEY", ""),
        secret_key=os.environ.get("OKX_SECRET_KEY", ""),
        passphrase=os.environ.get("OKX_PASSPHRASE", ""),
        testnet=os.environ.get("OKX_TESTNET", "true").lower() == "true",
    )
    provider = OkxOrderUpdateProvider(creds, market_type=args.market_type)
    await provider._ensure_connection()
    if not provider._ws:
        raise RuntimeError("okx_ws_connect_failed")
    if args.okx_algo:
        inst_type = "SPOT" if args.market_type == "spot" else "SWAP"
        await provider._ws.send(
            json.dumps({"op": "subscribe", "args": [{"channel": "orders-algo", "instType": inst_type}]})
        )
    await _recv_loop(provider._ws, "okx", args, writer, _parse_okx_order_update)


async def _capture_bybit(args: argparse.Namespace, writer) -> None:
    creds = BybitWsCredentials(
        api_key=os.environ.get("BYBIT_API_KEY", ""),
        secret_key=os.environ.get("BYBIT_SECRET_KEY", ""),
        testnet=os.environ.get("BYBIT_TESTNET", "true").lower() == "true",
    )
    provider = BybitOrderUpdateProvider(creds, market_type=args.market_type)
    await provider._ensure_connection()
    if not provider._ws:
        raise RuntimeError("bybit_ws_connect_failed")
    await _recv_loop(provider._ws, "bybit", args, writer, _parse_bybit_order_update)


async def _capture_binance(args: argparse.Namespace, writer) -> None:
    api_key = os.environ.get("BINANCE_API_KEY", "")
    secret_key = os.environ.get("BINANCE_SECRET_KEY", "")
    if args.market_type == "spot":
        api_key = os.environ.get("BINANCE_SPOT_API_KEY", api_key)
        secret_key = os.environ.get("BINANCE_SPOT_SECRET_KEY", secret_key)
    creds = BinanceWsCredentials(
        api_key=api_key,
        secret_key=secret_key,
        testnet=os.environ.get("BINANCE_TESTNET", "true").lower() == "true",
    )
    provider = BinanceOrderUpdateProvider(creds, market_type=args.market_type)
    await provider._ensure_connection()
    if not provider._ws:
        raise RuntimeError("binance_ws_connect_failed")
    parser = _parse_binance_spot_order_update if args.market_type == "spot" else _parse_binance_order_update
    if args.place_order and args.market_type != "spot":
        await _place_binance_futures_order(args, creds)
    await _recv_loop(provider._ws, "binance", args, writer, parser)


async def _recv_loop(ws, exchange: str, args: argparse.Namespace, writer, parser) -> None:
    max_messages = args.max_messages
    timeout_sec = args.timeout_sec
    received = 0
    while received < max_messages:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            if args.verbose:
                print(f"[{exchange}] timeout after {timeout_sec}s, received={received}")
            break
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            if args.verbose:
                print(f"[{exchange}] non-json frame received")
            continue
        parsed = parser(message)
        payload = {
            "timestamp": time.time(),
            "exchange": exchange,
            "market_type": args.market_type,
            "raw": message,
            "parsed": parsed.to_payload() if parsed else None,
        }
        writer.write(json.dumps(payload) + "\n")
        writer.flush()
        received += 1
        if args.verbose:
            print(f"[{exchange}] captured message {received}/{max_messages}")


async def _run(args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.verbose:
        print(f"Writing captures to {output_path.resolve()}")
    with output_path.open("a", encoding="utf-8") as writer:
        if args.exchange == "okx":
            await _capture_okx(args, writer)
        elif args.exchange == "bybit":
            await _capture_bybit(args, writer)
        else:
            await _capture_binance(args, writer)


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))

# Helpers for binance futures testnet orders (best-effort; skips on errors)
import time, hmac, hashlib, urllib.parse, requests  # noqa: E402


async def _place_binance_futures_order(args: argparse.Namespace, creds: BinanceWsCredentials) -> None:
    base_url = os.environ.get("BINANCE_FUTURES_TESTNET_URL", "https://testnet.binancefuture.com")
    params = {
        "symbol": args.symbol.upper(),
        "side": args.side.upper(),
        "type": "MARKET",
        "quantity": args.size,
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    # Set margin mode and leverage best-effort
    try:
        _ = await _binance_signed_request(
            base_url,
            "/fapi/v1/marginType",
            creds.api_key,
            creds.secret_key,
            {"symbol": args.symbol.upper(), "marginType": args.margin_mode.upper()},
        )
        _ = await _binance_signed_request(
            base_url,
            "/fapi/v1/leverage",
            creds.api_key,
            creds.secret_key,
            {"symbol": args.symbol.upper(), "leverage": int(args.leverage)},
        )
    except Exception:
        pass
    await _binance_signed_request(base_url, "/fapi/v1/order", creds.api_key, creds.secret_key, params)


async def _binance_signed_request(base_url: str, path: str, api_key: str, secret_key: str, params: dict):
    params = dict(params)
    params["timestamp"] = params.get("timestamp", int(time.time() * 1000))
    params["recvWindow"] = params.get("recvWindow", 5000)
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(secret_key.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"{base_url}{path}?{qs}&signature={sig}"
    headers = {"X-MBX-APIKEY": api_key}
    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()


if __name__ == "__main__":
    main()
