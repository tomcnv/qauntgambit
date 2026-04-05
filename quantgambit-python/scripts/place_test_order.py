"""Place a one-off test order via CCXT."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import os
import time
from typing import Optional

import aiohttp

from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Place a test order on an exchange.")
    parser.add_argument("--exchange", choices=["okx", "bybit", "binance"], required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", choices=["buy", "sell"])
    parser.add_argument("--order-type", choices=["market", "limit", "stop_market", "take_profit_market"], default="market")
    parser.add_argument("--size", type=float)
    parser.add_argument("--price", type=float)
    parser.add_argument("--stop-price", type=float)
    parser.add_argument("--market-type", choices=["perp", "spot"], default="perp")
    parser.add_argument("--margin-mode", choices=["isolated", "cross"], default="isolated")
    parser.add_argument("--reduce-only", action="store_true")
    parser.add_argument("--leverage", type=int, default=1)
    parser.add_argument("--client-order-id")
    parser.add_argument("--cancel-order-id")
    parser.add_argument("--cancel-client-id")
    return parser.parse_args()


async def _maybe_set_leverage(client, exchange: str, leverage: int, symbol: str) -> None:
    if leverage <= 1:
        return
    method = getattr(client, "set_leverage", None) or getattr(client, "setLeverage", None)
    if method is None:
        return
    try:
        await method(leverage, symbol)
    except Exception:
        # Some exchanges require setting leverage via separate endpoints or symbols.
        return


async def _maybe_set_margin_mode(client, margin_mode: str, symbol: str) -> None:
    method = getattr(client, "set_margin_mode", None) or getattr(client, "setMarginMode", None)
    if method is None:
        return
    try:
        await method(margin_mode, symbol)
    except Exception:
        return


async def _run(args: argparse.Namespace) -> None:
    exchange = args.exchange
    if exchange == "okx":
        creds = CcxtCredentials(
            api_key=os.environ.get("OKX_API_KEY", ""),
            secret_key=os.environ.get("OKX_SECRET_KEY", ""),
            passphrase=os.environ.get("OKX_PASSPHRASE", ""),
            testnet=os.environ.get("OKX_TESTNET", "true").lower() == "true",
        )
    elif exchange == "bybit":
        creds = CcxtCredentials(
            api_key=os.environ.get("BYBIT_API_KEY", ""),
            secret_key=os.environ.get("BYBIT_SECRET_KEY", ""),
            testnet=os.environ.get("BYBIT_TESTNET", "true").lower() == "true",
        )
    else:
        api_key = os.environ.get("BINANCE_API_KEY", "")
        secret_key = os.environ.get("BINANCE_SECRET_KEY", "")
        if args.market_type == "spot":
            api_key = os.environ.get("BINANCE_SPOT_API_KEY", api_key)
            secret_key = os.environ.get("BINANCE_SPOT_SECRET_KEY", secret_key)
        creds = CcxtCredentials(
            api_key=api_key,
            secret_key=secret_key,
            testnet=os.environ.get("BINANCE_TESTNET", "true").lower() == "true",
        )
    if exchange == "binance" and args.market_type == "perp" and creds.testnet:
        if args.cancel_order_id or args.cancel_client_id:
            response = await _cancel_binance_futures_testnet_order(args, creds)
        else:
            if args.side is None or args.size is None:
                raise RuntimeError("Missing --side/--size for order placement.")
            response = await _place_binance_futures_testnet_order(args, creds)
        print(response)
        return
    client = build_ccxt_client(
        exchange,
        creds,
        market_type=args.market_type,
        margin_mode=args.margin_mode,
    )
    try:
        if args.side is None or args.size is None:
            raise RuntimeError("Missing --side/--size for order placement.")
        await _maybe_set_margin_mode(client.client, args.margin_mode, args.symbol)
        await _maybe_set_leverage(client.client, exchange, args.leverage, args.symbol)
        response = await client.place_order(
            symbol=args.symbol,
            side=args.side,
            size=args.size,
            order_type=args.order_type,
            price=args.price,
            reduce_only=args.reduce_only,
        )
        print(response)
    finally:
        await client.close()


def _binance_futures_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("/", "").replace("-", "")
    return normalized.replace("SWAP", "")


def _binance_sign(secret: str, params: dict) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


async def _binance_futures_request(
    session: aiohttp.ClientSession,
    base_url: str,
    path: str,
    api_key: str,
    secret_key: str,
    params: dict,
    method: str = "POST",
) -> dict:
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    params["signature"] = _binance_sign(secret_key, params)
    headers = {"X-MBX-APIKEY": api_key}
    request_fn = session.post if method.upper() == "POST" else session.delete
    async with request_fn(f"{base_url}{path}", params=params, headers=headers) as response:
        data = await response.json()
        return {"status": response.status, "data": data}


async def _place_binance_futures_testnet_order(args: argparse.Namespace, creds: CcxtCredentials) -> dict:
    base_url = os.environ.get("BINANCE_FUTURES_TESTNET_URL", "https://testnet.binancefuture.com")
    symbol = _binance_futures_symbol(args.symbol)
    async with aiohttp.ClientSession() as session:
        await _binance_futures_request(
            session,
            base_url,
            "/fapi/v1/marginType",
            creds.api_key,
            creds.secret_key,
            {"symbol": symbol, "marginType": args.margin_mode.upper()},
        )
        await _binance_futures_request(
            session,
            base_url,
            "/fapi/v1/leverage",
            creds.api_key,
            creds.secret_key,
            {"symbol": symbol, "leverage": int(args.leverage)},
        )
        order_params = {
            "symbol": symbol,
            "side": args.side.upper(),
            "type": args.order_type.upper().replace("STOP_MARKET", "STOP_MARKET"),
            "quantity": args.size,
            "reduceOnly": str(args.reduce_only).lower(),
        }
        stop_price = args.stop_price
        if args.order_type.lower() in {"stop_market", "take_profit_market"}:
            if stop_price is None:
                mark = await _binance_mark_price(session, base_url, symbol)
                if mark is not None:
                    if args.order_type.lower() == "stop_market":
                        stop_price = mark * (0.999 if args.side.lower() == "sell" else 1.001)
                    else:
                        stop_price = mark * (1.001 if args.side.lower() == "sell" else 0.999)
            if stop_price is not None:
                order_params["stopPrice"] = round(stop_price, 2)
        if args.order_type.lower() == "limit":
            order_params["timeInForce"] = "GTC"
        if args.client_order_id:
            order_params["newClientOrderId"] = args.client_order_id
        if args.price is not None:
            order_params["price"] = args.price
        return await _binance_futures_request(
            session,
            base_url,
            "/fapi/v1/order",
            creds.api_key,
            creds.secret_key,
            order_params,
        )


async def _binance_mark_price(session: aiohttp.ClientSession, base_url: str, symbol: str) -> Optional[float]:
    url = f"{base_url}/fapi/v1/premiumIndex"
    async with session.get(url, params={"symbol": symbol}) as response:
        data = await response.json()
        try:
            return float(data.get("markPrice"))
        except (TypeError, ValueError, AttributeError):
            return None


async def _cancel_binance_futures_testnet_order(args: argparse.Namespace, creds: CcxtCredentials) -> dict:
    base_url = os.environ.get("BINANCE_FUTURES_TESTNET_URL", "https://testnet.binancefuture.com")
    symbol = _binance_futures_symbol(args.symbol)
    cancel_params = {"symbol": symbol}
    if args.cancel_order_id:
        cancel_params["orderId"] = args.cancel_order_id
    if args.cancel_client_id:
        cancel_params["origClientOrderId"] = args.cancel_client_id
    async with aiohttp.ClientSession() as session:
        return await _binance_futures_request(
            session,
            base_url,
            "/fapi/v1/order",
            creds.api_key,
            creds.secret_key,
            cancel_params,
            method="DELETE",
        )


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
