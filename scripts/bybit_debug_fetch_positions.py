#!/usr/bin/env python3
"""
Debug helper: fetch Bybit open positions via the same CCXT wiring used by runtime.

Prints a sanitized summary (no credentials) so we can compare:
- what Bybit API reports as open positions
- what QuantGambit believes is open (Redis positions snapshot)

Usage:
  quantgambit-python/venv/bin/python scripts/bybit_debug_fetch_positions.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys


def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    repo_root = Path(__file__).resolve().parents[1]
    dotenv_path = repo_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)


def _safe_float(raw) -> float | None:
    try:
        if raw is None:
            return None
        return float(raw)
    except Exception:
        return None


async def _main() -> int:
    _load_dotenv_if_present()

    # Allow running from repo root without installing the package.
    repo_root = Path(__file__).resolve().parents[1]
    quant_root = repo_root / "quantgambit-python"
    if str(quant_root) not in sys.path:
        sys.path.insert(0, str(quant_root))

    # Import after dotenv load so credential resolution works.
    from quantgambit.runtime.entrypoint import _load_ccxt_credentials  # type: ignore
    from quantgambit.execution.ccxt_clients import build_ccxt_client  # type: ignore

    exchange = os.getenv("EXCHANGE", "bybit").strip().lower()
    market_type = os.getenv("MARKET_TYPE", "perp")
    margin_mode = os.getenv("MARGIN_MODE", "isolated")
    demo = os.getenv("BYBIT_DEMO", "false").lower() in {"1", "true", "yes"}

    if exchange != "bybit":
        raise SystemExit(f"expected EXCHANGE=bybit, got {exchange!r}")

    creds = _load_ccxt_credentials(exchange, demo=demo)
    if not creds:
        print("ERROR: Could not load Bybit credentials (check EXCHANGE_SECRET_ID or BYBIT_API_KEY/BYBIT_SECRET_KEY).")
        return 2

    client = build_ccxt_client(exchange, creds, market_type=market_type, margin_mode=margin_mode)
    try:
        positions = await client.fetch_positions()
    finally:
        try:
            await client.client.close()
        except Exception:
            pass

    # Sanitize and print.
    out = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        sym = p.get("symbol")
        contracts = _safe_float(p.get("contracts"))
        size = _safe_float(p.get("size"))
        amt = _safe_float(p.get("positionAmt"))
        entry = _safe_float(p.get("entryPrice") or p.get("entry_price"))
        side = (p.get("side") or "").lower() or None
        ts = p.get("timestamp") or p.get("updatedTime") or p.get("createdTime")
        out.append(
            {
                "symbol": sym,
                "side": side,
                "contracts": contracts,
                "size": size,
                "positionAmt": amt,
                "entryPrice": entry,
                "timestamp": ts,
            }
        )

    print(json.dumps({"exchange": "bybit", "demo": bool(creds.demo), "testnet": bool(creds.testnet), "market_type": market_type, "count": len(out), "positions": out}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
