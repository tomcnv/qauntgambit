"""Run a backtest directly from TimescaleDB data.

Usage:
    python scripts/run_backtest.py --symbol BTCUSDT --start 2026-02-25 --end 2026-02-26
    
    # EV gate shadow mode (skip prediction requirements):
    EV_GATE_MODE=shadow python scripts/run_backtest.py --symbol BTCUSDT --start 2026-02-25 --end 2026-02-26
"""
import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from quantgambit.config.env_loading import apply_layered_env_defaults

apply_layered_env_defaults(Path(__file__).resolve().parents[1], os.getenv("ENV_FILE"), os.environ)

os.environ["IGNORE_FEED_GAPS"] = "true"

import asyncpg
from urllib.parse import urlparse
from quantgambit.backtesting.strategy_executor import StrategyBacktestExecutor, StrategyExecutorConfig


async def run(args):
    db_url = os.getenv(
        "BOT_TIMESCALE_URL",
        "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot",
    )
    parsed = urlparse(db_url)
    os.environ.setdefault("TIMESCALE_HOST", parsed.hostname or "localhost")
    os.environ.setdefault("TIMESCALE_PORT", str(parsed.port or 5433))
    os.environ.setdefault("TIMESCALE_DB", (parsed.path or "/quantgambit_bot").lstrip("/"))
    os.environ.setdefault("TIMESCALE_USER", parsed.username or "quantgambit")
    os.environ.setdefault("TIMESCALE_PASSWORD", parsed.password or "")

    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)
    executor = StrategyBacktestExecutor(platform_pool=pool, config=StrategyExecutorConfig.from_env())

    run_id = str(uuid.uuid4())
    config = {
        "symbol": args.symbol,
        "start_date": args.start,
        "end_date": args.end,
        "exchange": "bybit",
        "fee_config": "bybit_regular",
        "starting_equity": 10000.0,
        "force_run": True,
        "minimum_completeness_pct": 5.0,
        "max_critical_gaps": 999,
        "max_gap_duration_pct": 100.0,
    }

    print(f"Backtest {run_id[:8]}  {args.symbol}  {args.start} → {args.end}")
    result = await executor.execute(
        run_id=run_id,
        tenant_id="11111111-1111-1111-1111-111111111111",
        bot_id="bf167763-fee1-4f11-ab9a-6fddadf125de",
        config=config,
    )

    status = result.get("status", "?")
    if status == "failed":
        print(f"\nFailed: {result.get('error')}")
        await pool.close()
        return

    print(f"\n{'='*60}")
    print(f"RESULTS: {args.symbol}  ({result.get('total_trades', 0)} trades)")
    print(f"{'='*60}")
    for k in ["total_trades", "win_rate", "realized_pnl", "total_fees", "sharpe_ratio",
              "sortino_ratio", "max_drawdown_pct", "profit_factor", "avg_trade_pnl",
              "trades_per_day", "fee_drag_pct", "slippage_drag_pct",
              "winning_trades", "losing_trades", "avg_win", "avg_loss",
              "largest_win", "largest_loss", "gross_profit", "gross_loss"]:
        v = result.get(k, "n/a")
        if isinstance(v, float):
            print(f"  {k:25s}: {v:.4f}")
        else:
            print(f"  {k:25s}: {v}")

    # Query per-trade details from DB
    async with pool.acquire() as conn:
        trades = await conn.fetch(
            "SELECT side, strategy_id, profile_id, pnl, total_fees, reason "
            "FROM backtest_trades WHERE run_id = $1 ORDER BY ts", uuid.UUID(run_id)
        )

    if trades:
        # Per-strategy breakdown
        strats = {}
        for t in trades:
            sid = t["strategy_id"] or "unknown"
            s = strats.setdefault(sid, {"n": 0, "w": 0, "pnl": 0.0, "fees": 0.0})
            s["n"] += 1
            s["pnl"] += float(t["pnl"] or 0)
            s["fees"] += float(t["total_fees"] or 0)
            if (t["pnl"] or 0) > 0:
                s["w"] += 1

        print(f"\n--- Per Strategy ---")
        for sid, s in sorted(strats.items(), key=lambda x: -x[1]["n"]):
            wr = s["w"] / s["n"] if s["n"] else 0
            print(f"  {sid:40s} {s['n']:4d} trades  {wr:5.0%} win  pnl=${s['pnl']:+8.2f}  fees=${s['fees']:.2f}")

        # Side breakdown
        sides = {}
        for t in trades:
            sides.setdefault(t["side"], {"n": 0, "w": 0, "pnl": 0.0})
            sides[t["side"]]["n"] += 1
            sides[t["side"]]["pnl"] += float(t["pnl"] or 0)
            if (t["pnl"] or 0) > 0:
                sides[t["side"]]["w"] += 1
        print(f"\n--- Side Breakdown ---")
        for side, s in sorted(sides.items(), key=lambda x: -x[1]["n"]):
            wr = s["w"] / s["n"] if s["n"] else 0
            print(f"  {side:10s} {s['n']:4d} trades  {wr:5.0%} win  pnl=${s['pnl']:+8.2f}")

        # Exit reason breakdown
        exits = {}
        for t in trades:
            exits[t["reason"] or "unknown"] = exits.get(t["reason"] or "unknown", 0) + 1
        print(f"\n--- Exit Reasons ---")
        for r, c in sorted(exits.items(), key=lambda x: -x[1]):
            print(f"  {r:25s}: {c}")

    await pool.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--start", default="2026-02-25")
    p.add_argument("--end", default="2026-02-26")
    asyncio.run(run(p.parse_args()))
