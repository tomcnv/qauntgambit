#!/usr/bin/env python3
"""Compare all strategies over a time period to find the best performer."""

import asyncio
import json
import httpx
import time
from typing import Dict, List, Any

API_BASE = "http://localhost:3002/api/research"
TENANT_ID = "11111111-1111-1111-1111-111111111111"

STRATEGIES = [
    "amt_value_area_rejection_scalp",
    "poc_magnet_scalp",
    "breakout_scalp",
    "mean_reversion_fade",
    "trend_pullback",
    "chop_zone_avoid",
    "opening_range_breakout",
    "asia_range_scalp",
    "europe_open_vol",
    "us_open_momentum",
    "overnight_thin",
    "high_vol_breakout",
    "low_vol_grind",
    "vol_expansion",
    "liquidity_hunt",
    "order_flow_imbalance",
    "spread_compression",
    "vwap_reversion",
    "volume_profile_cluster",
    "drawdown_recovery",
    "max_profit_protection",
]


async def submit_backtest(client: httpx.AsyncClient, strategy_id: str) -> str:
    """Submit a backtest for a strategy and return run_id."""
    payload = {
        "name": f"Strategy Comparison - {strategy_id}",
        "strategy_id": strategy_id,
        "symbol": "BTCUSDT",
        "start_date": "2026-01-13",
        "end_date": "2026-01-14",
        "initial_capital": 10000,
        "config": {
            "maker_fee_bps": 2,
            "taker_fee_bps": 5.5,
            "slippage_model": "fixed",
            "slippage_bps": 5
        }
    }
    
    resp = await client.post(
        f"{API_BASE}/backtests",
        json=payload,
        headers={"X-Tenant-ID": TENANT_ID}
    )
    data = resp.json()
    return data.get("run_id")


async def wait_for_completion(client: httpx.AsyncClient, run_id: str, timeout: int = 120) -> Dict[str, Any]:
    """Wait for backtest to complete and return results."""
    start = time.time()
    while time.time() - start < timeout:
        resp = await client.get(
            f"{API_BASE}/backtests/{run_id}",
            headers={"X-Tenant-ID": TENANT_ID}
        )
        data = resp.json()
        status = data.get("status")
        if status in ("completed", "failed"):
            return data
        await asyncio.sleep(2)
    return {"status": "timeout", "run_id": run_id}


async def run_comparison():
    """Run backtests for all strategies and compare results."""
    results = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Submit all backtests
        print("Submitting backtests for all strategies...")
        run_ids = {}
        for strategy_id in STRATEGIES:
            try:
                run_id = await submit_backtest(client, strategy_id)
                run_ids[strategy_id] = run_id
                print(f"  ✓ {strategy_id}: {run_id}")
            except Exception as e:
                print(f"  ✗ {strategy_id}: {e}")
        
        print(f"\nWaiting for {len(run_ids)} backtests to complete...")
        
        # Wait for all to complete
        for strategy_id, run_id in run_ids.items():
            print(f"  Waiting for {strategy_id}...", end=" ", flush=True)
            data = await wait_for_completion(client, run_id)
            metrics = data.get("metrics", {})
            results.append({
                "strategy_id": strategy_id,
                "status": data.get("status"),
                "total_return_pct": metrics.get("total_return_pct", 0),
                "total_trades": metrics.get("total_trades", 0),
                "win_rate": metrics.get("win_rate", 0),
                "profit_factor": metrics.get("profit_factor", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "avg_trade_pnl": metrics.get("avg_trade_pnl", 0),
            })
            print(f"{metrics.get('total_return_pct', 0):.2f}%")
    
    # Sort by return
    results.sort(key=lambda x: x["total_return_pct"], reverse=True)
    
    # Print results table
    print("\n" + "=" * 100)
    print("STRATEGY COMPARISON RESULTS (sorted by return)")
    print("=" * 100)
    print(f"{'Strategy':<35} {'Return':>10} {'Trades':>8} {'Win%':>8} {'PF':>8} {'DD%':>8} {'Sharpe':>8}")
    print("-" * 100)
    
    for r in results:
        pf = r['profit_factor']
        pf_str = f"{pf:.2f}" if pf < 100 else "∞"
        print(f"{r['strategy_id']:<35} {r['total_return_pct']:>9.2f}% {r['total_trades']:>8} {r['win_rate']:>7.1f}% {pf_str:>8} {r['max_drawdown_pct']:>7.2f}% {r['sharpe_ratio']:>8.2f}")
    
    print("=" * 100)
    
    # Best performer
    if results:
        best = results[0]
        print(f"\n🏆 BEST STRATEGY: {best['strategy_id']}")
        print(f"   Return: {best['total_return_pct']:.2f}%")
        print(f"   Trades: {best['total_trades']}")
        print(f"   Win Rate: {best['win_rate']:.1f}%")
        print(f"   Profit Factor: {best['profit_factor']:.2f}")


if __name__ == "__main__":
    asyncio.run(run_comparison())
