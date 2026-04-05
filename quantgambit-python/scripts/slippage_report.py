#!/usr/bin/env python3
"""
Slippage Report - summarize live slippage from order_events and suggest multipliers.

Usage:
  python scripts/slippage_report.py --days 7
  python scripts/slippage_report.py --days 1 --symbol BTCUSDT
"""

import argparse
import asyncio
import asyncpg
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


def _read_dotenv_value(key: str) -> Optional[str]:
    try:
        for line in Path(".env").read_text().splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            if not line.startswith(f"{key}="):
                continue
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def _env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key) or _read_dotenv_value(key) or default


async def _get_pool() -> asyncpg.Pool:
    timescale_url = _env_value("BOT_TIMESCALE_URL")
    if timescale_url:
        return await asyncpg.create_pool(timescale_url, min_size=1, max_size=5, timeout=10.0)
    host = _env_value("BOT_DB_HOST", _env_value("DB_HOST", "localhost"))
    port = _env_value("BOT_DB_PORT", "5432")
    name = _env_value("BOT_DB_NAME", "platform_db")
    user = _env_value("BOT_DB_USER", "platform")
    password = _env_value("BOT_DB_PASSWORD", "platform_pw")
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return await asyncpg.create_pool(dsn, min_size=1, max_size=5, timeout=10.0)


def _float_env(key: str, default: float) -> float:
    try:
        return float(_env_value(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


async def _query_slippage(pool: asyncpg.Pool, tenant_id: str, bot_id: str, days: int, symbol: Optional[str]):
    base_where = """
        WHERE tenant_id=$1 AND bot_id=$2
          AND payload->>'slippage_bps' IS NOT NULL
          AND ts >= NOW() - ($3::int * INTERVAL '1 day')
    """
    params = [tenant_id, bot_id, days]
    if symbol:
        base_where += " AND symbol=$4"
        params.append(symbol)
    query = f"""
        SELECT
            COUNT(*) as n,
            AVG((payload->>'slippage_bps')::numeric) as avg,
            PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY (payload->>'slippage_bps')::numeric) as p10,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (payload->>'slippage_bps')::numeric) as p50,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY (payload->>'slippage_bps')::numeric) as p90,
            MIN((payload->>'slippage_bps')::numeric) as min,
            MAX((payload->>'slippage_bps')::numeric) as max
        FROM order_events
        {base_where}
    """
    row = await pool.fetchrow(query, *params)
    return row


async def _query_symbol_breakdown(pool: asyncpg.Pool, tenant_id: str, bot_id: str, days: int):
    query = """
        SELECT
            symbol,
            COUNT(*) as n,
            AVG((payload->>'slippage_bps')::numeric) as avg,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (payload->>'slippage_bps')::numeric) as p50,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY (payload->>'slippage_bps')::numeric) as p90
        FROM order_events
        WHERE tenant_id=$1 AND bot_id=$2
          AND payload->>'slippage_bps' IS NOT NULL
          AND ts >= NOW() - ($3::int * INTERVAL '1 day')
        GROUP BY symbol
        ORDER BY p50 DESC NULLS LAST
    """
    return await pool.fetch(query, tenant_id, bot_id, days)


def _suggest_multiplier(observed_bps: Optional[float], baseline_bps: float) -> Optional[float]:
    if observed_bps is None or baseline_bps <= 0:
        return None
    return round(max(1.0, float(observed_bps) / baseline_bps), 2)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--tenant", type=str, default=None)
    parser.add_argument("--bot", type=str, default=None)
    args = parser.parse_args()

    tenant_id = args.tenant or _env_value("TENANT_ID") or _env_value("DEFAULT_TENANT_ID")
    bot_id = args.bot or _env_value("BOT_ID") or _env_value("DEFAULT_BOT_ID")
    if not tenant_id or not bot_id:
        print("Missing TENANT_ID/BOT_ID (set in env or pass --tenant/--bot).")
        return 1

    pool = await _get_pool()
    try:
        row = await _query_slippage(pool, tenant_id, bot_id, args.days, args.symbol)
        if not row or row["n"] == 0:
            print("No slippage data found for the given window.")
            return 0

        avg = float(row["avg"]) if row["avg"] is not None else None
        p10 = float(row["p10"]) if row["p10"] is not None else None
        p50 = float(row["p50"]) if row["p50"] is not None else None
        p90 = float(row["p90"]) if row["p90"] is not None else None
        min_v = float(row["min"]) if row["min"] is not None else None
        max_v = float(row["max"]) if row["max"] is not None else None

        print(f"Slippage summary (last {args.days} days){' for '+args.symbol if args.symbol else ''}:")
        print(f"  n={row['n']}, avg={avg:.2f}bps, p10={p10:.2f}, p50={p50:.2f}, p90={p90:.2f}, min={min_v:.2f}, max={max_v:.2f}")

        baseline = _float_env("STRATEGY_SLIPPAGE_BPS", 2.0)
        model_mult = _float_env("SLIPPAGE_MODEL_MULTIPLIER", 1.0)
        snap_mult = _float_env("SNAPSHOT_SLIPPAGE_MULTIPLIER", 1.0)
        suggested_mult = _suggest_multiplier(p50, baseline)
        suggested_floor = round(p10, 2) if p10 is not None else None

        print("\nSuggested config (based on median slippage vs STRATEGY_SLIPPAGE_BPS):")
        if suggested_mult:
            print(f"  SLIPPAGE_MODEL_MULTIPLIER: {model_mult} -> {suggested_mult}")
            print(f"  SNAPSHOT_SLIPPAGE_MULTIPLIER: {snap_mult} -> {suggested_mult}")
        if suggested_floor is not None:
            print(f"  SLIPPAGE_MODEL_FLOOR_BPS: consider >= {suggested_floor}")
            print(f"  SNAPSHOT_MIN_SLIPPAGE_BPS: consider >= {suggested_floor}")

        if not args.symbol:
            print("\nPer-symbol breakdown (p50 descending):")
            rows = await _query_symbol_breakdown(pool, tenant_id, bot_id, args.days)
            for r in rows:
                sym = r["symbol"]
                if not sym:
                    continue
                avg_s = float(r["avg"]) if r["avg"] is not None else 0.0
                p50_s = float(r["p50"]) if r["p50"] is not None else 0.0
                p90_s = float(r["p90"]) if r["p90"] is not None else 0.0
                print(f"  {sym}: n={r['n']}, avg={avg_s:.2f}bps, p50={p50_s:.2f}, p90={p90_s:.2f}")

    finally:
        await pool.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
