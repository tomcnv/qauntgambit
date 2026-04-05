"""Place OKX testnet orders using the CCXT adapter (run locally)."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import uuid

from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Place OKX testnet orders via CCXT.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--market-type", choices=["perp", "spot"], default="perp")
    parser.add_argument("--margin-mode", choices=["isolated", "cross"], default="isolated")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    parser.add_argument("--size", type=float, default=0.002)
    parser.add_argument("--order-type", choices=["market", "limit"], default="market")
    parser.add_argument("--price", type=float, default=None)
    parser.add_argument("--reduce-only", action="store_true")
    parser.add_argument("--stop-loss", type=float, default=None)
    parser.add_argument("--take-profit", type=float, default=None)
    parser.add_argument("--auto-protective-pct", type=float, default=None)
    parser.add_argument("--client-order-id", default=None)
    parser.add_argument("--cancel-order-id", default=None)
    parser.add_argument("--cancel-client-id", default=None)
    parser.add_argument("--place-protective", action="store_true")
    return parser.parse_args()


def _normalize_symbol(raw: str, market_type: str) -> str:
    symbol = raw.strip().upper().replace("/", "")
    if "-" in raw:
        return raw.upper()
    if symbol.endswith("USDT"):
        base = symbol[:-4]
        if market_type == "spot":
            return f"{base}-USDT"
        return f"{base}-USDT-SWAP"
    return raw.upper()


def _normalize_client_order_id(value: str | None) -> str:
    base = value or f"qg{uuid.uuid4().hex[:18]}"
    normalized = re.sub(r"[^A-Za-z0-9]", "", base)
    if not normalized:
        normalized = f"qg{uuid.uuid4().hex[:18]}"
    return normalized[:32]


async def _run(args: argparse.Namespace) -> None:
    creds = CcxtCredentials(
        api_key=os.environ.get("OKX_API_KEY", ""),
        secret_key=os.environ.get("OKX_SECRET_KEY", ""),
        passphrase=os.environ.get("OKX_PASSPHRASE", ""),
        testnet=os.environ.get("OKX_TESTNET", "true").lower() == "true",
    )
    if not (creds.api_key and creds.secret_key and creds.passphrase):
        raise RuntimeError("Missing OKX_API_KEY/OKX_SECRET_KEY/OKX_PASSPHRASE in env.")

    symbol = _normalize_symbol(args.symbol, args.market_type)
    client = build_ccxt_client("okx", creds, market_type=args.market_type, margin_mode=args.margin_mode)
    try:
        if args.cancel_order_id or args.cancel_client_id:
            cancel_client_id = args.cancel_client_id
            cancel_order_id = args.cancel_order_id
            if cancel_order_id and any(ch.isalpha() for ch in cancel_order_id):
                cancel_client_id = cancel_order_id
                cancel_order_id = None
            if cancel_client_id:
                response = await client.cancel_order_by_client_id(cancel_client_id, symbol)
            else:
                response = await client.cancel_order(cancel_order_id, symbol)
            print({"action": "cancel", "response": response})
            return

        client_order_id = _normalize_client_order_id(args.client_order_id)
        attach_protection = args.place_protective and (args.stop_loss or args.take_profit or args.auto_protective_pct)
        stop_loss = args.stop_loss
        take_profit = args.take_profit
        if attach_protection:
            try:
                ticker = await client.client.fetch_ticker(symbol)
            except Exception:
                ticker = {}
            last = (
                ticker.get("last")
                or ticker.get("close")
                or (ticker.get("info") or {}).get("last")
            )
            if last:
                last = float(last)
                pct = args.auto_protective_pct
                if pct and not stop_loss:
                    stop_loss = last * (1 - pct) if args.side == "buy" else last * (1 + pct)
                if pct and not take_profit:
                    take_profit = last * (1 + pct) if args.side == "buy" else last * (1 - pct)
                if take_profit:
                    if args.side == "buy" and take_profit <= last:
                        take_profit = last * 1.01
                    if args.side == "sell" and take_profit >= last:
                        take_profit = last * 0.99
                if stop_loss:
                    if args.side == "buy" and stop_loss >= last:
                        stop_loss = last * 0.99
                    if args.side == "sell" and stop_loss <= last:
                        stop_loss = last * 1.01
        response = await client.place_order(
            symbol=symbol,
            side=args.side,
            size=args.size,
            order_type=args.order_type,
            price=args.price,
            client_order_id=client_order_id,
            reduce_only=args.reduce_only,
            stop_loss=None if attach_protection else stop_loss,
            take_profit=None if attach_protection else take_profit,
        )
        print({"action": "place_order", "client_order_id": client_order_id, "response": response})

        if attach_protection:
            protect = await client.place_protective_orders(
                symbol=symbol,
                side=args.side,
                size=args.size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=f"{client_order_id}:tpsl",
            )
            print({"action": "place_protective", "response": protect})
    finally:
        await client.close()


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
