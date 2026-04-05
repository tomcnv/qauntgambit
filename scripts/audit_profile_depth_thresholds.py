#!/usr/bin/env python3
"""Audit profile depth thresholds against current orderbook depth levels.

This script reads symbol characteristics from Redis and compares the
canonical profile depth thresholds (absolute or multiplier-based) against
the current typical depth. It helps validate whether the profile depth
gates remain realistic after ORDERBOOK_DEPTH_LEVELS changes.
"""

from __future__ import annotations

import argparse
import os
from typing import Dict, List, Optional, Tuple

import redis


def _load_profiles():
    try:
        from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
            ALL_CANONICAL_PROFILES,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Failed to load canonical profiles: {exc}") from exc
    return ALL_CANONICAL_PROFILES


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _load_symbol_characteristics(
    client: redis.Redis,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Dict[str, float]]:
    prefix = "quantgambit:symbol_chars:"
    results: Dict[str, Dict[str, float]] = {}
    if symbols:
        keys = [f"{prefix}{symbol}" for symbol in symbols]
    else:
        keys = list(client.scan_iter(match=f"{prefix}*"))
    for key in keys:
        key_str = _decode(key)
        symbol = key_str.split(":")[-1]
        data = client.hgetall(key_str)
        if not data:
            continue
        try:
            typical_depth = float(_decode(data.get(b"typical_depth_usd") or data.get("typical_depth_usd")))
        except (TypeError, ValueError):
            continue
        results[symbol] = {
            "typical_depth_usd": typical_depth,
        }
    return results


def _format_row(row: Tuple[str, str, str, str, str, str]) -> str:
    return "  ".join(value.ljust(width) for value, width in zip(row, [10, 26, 10, 14, 14, 10]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit profile depth thresholds vs orderbook depth levels")
    parser.add_argument("--redis", default=os.getenv("REDIS_URL", "redis://localhost:6379"))
    parser.add_argument("--symbols", nargs="*", help="Symbols to audit (default: scan Redis)")
    args = parser.parse_args()

    client = redis.from_url(args.redis, decode_responses=False)
    symbols_data = _load_symbol_characteristics(client, args.symbols)
    if not symbols_data:
        print("No symbol characteristics found in Redis.")
        return

    profiles = _load_profiles()
    orderbook_levels = int(os.getenv("ORDERBOOK_DEPTH_LEVELS", "50"))

    print(f"ORDERBOOK_DEPTH_LEVELS={orderbook_levels}")
    print("Depth thresholds are compared against typical_depth_usd (min bid/ask depth).")
    print()

    header = ("symbol", "profile_id", "mult", "min_depth", "typ_depth", "ratio")
    print(_format_row(header))
    print(_format_row(tuple("-" * len(h) for h in header)))

    for symbol, sym_data in sorted(symbols_data.items()):
        typical_depth = sym_data["typical_depth_usd"]
        for profile in profiles:
            profile_id = getattr(profile, "profile_id", "unknown")
            conditions = getattr(profile, "conditions", None)
            risk = getattr(profile, "risk", None)

            min_depth_abs = None
            depth_multiplier = None
            if conditions is not None:
                min_depth_abs = getattr(conditions, "min_orderbook_depth", None)
            if risk is not None:
                depth_multiplier = getattr(risk, "depth_typical_multiplier", None)

            if min_depth_abs is None and depth_multiplier is None:
                continue

            resolved_min = None
            if min_depth_abs is not None:
                resolved_min = float(min_depth_abs)
            elif depth_multiplier is not None:
                resolved_min = float(depth_multiplier) * typical_depth

            if resolved_min is None:
                continue

            ratio = resolved_min / typical_depth if typical_depth > 0 else 0.0
            row = (
                symbol,
                str(profile_id),
                f"{depth_multiplier:.2f}" if depth_multiplier is not None else "abs",
                f"{resolved_min:,.0f}",
                f"{typical_depth:,.0f}",
                f"{ratio:.2f}x",
            )
            print(_format_row(row))


if __name__ == "__main__":
    main()
