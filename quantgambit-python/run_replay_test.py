#!/usr/bin/env python3
"""Run replay test for integration testing."""

import asyncio
import json
import sys
from pathlib import Path

from quantgambit.backtesting.replay_worker import ReplayWorker, ReplayConfig
from quantgambit.config.loss_prevention import load_loss_prevention_config
from quantgambit.signals.decision_engine import DecisionEngine
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.risk.degradation import (
    DegradationManager,
    DegradationConfig,
    set_degradation_manager,
)


async def main():
    """Run replay test."""
    input_path = Path("/tmp/last_12h_full.jsonl")
    output_path = Path("/tmp/replay_results.json")
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1
    
    print(f"Starting replay on {input_path}")
    print(f"File size: {input_path.stat().st_size / (1024**3):.2f} GB")
    
    # Configure degradation manager for backtesting
    degradation_config = DegradationConfig(
        trade_stale_reduce_sec=86400 * 365 * 10,
        trade_stale_no_entry_sec=86400 * 365 * 10,
        trade_stale_flatten_sec=86400 * 365 * 10,
        orderbook_stale_reduce_sec=86400 * 365 * 10,
        orderbook_stale_no_entry_sec=86400 * 365 * 10,
        orderbook_stale_flatten_sec=86400 * 365 * 10,
        quality_reduce_threshold=0.0,
        quality_no_entry_threshold=0.0,
        quality_flatten_threshold=0.0,
        spread_reduce_bps=1000.0,
        spread_no_entry_bps=1000.0,
        depth_reduce_usd=0.0,
        depth_no_entry_usd=0.0,
        upgrade_cooldown_sec=0.0,
        downgrade_cooldown_sec=0.0,
        flatten_on_ws_disconnect=False,
    )
    set_degradation_manager(DegradationManager(degradation_config))
    
    # Configure data readiness for backtesting
    data_readiness_config = DataReadinessConfig(
        max_trade_age_sec=86400 * 365 * 10,
        max_clock_drift_sec=86400 * 365 * 10,
        require_ws_connected=False,
        use_cts_latency_gates=False,
    )
    
    # Configure global gate for backtesting
    global_gate_config = GlobalGateConfig(
        snapshot_age_ok_ms=86400 * 365 * 10 * 1000,
        snapshot_age_reduce_ms=86400 * 365 * 10 * 1000,
        snapshot_age_block_ms=86400 * 365 * 10 * 1000,
    )
    
    config = ReplayConfig(
        input_path=input_path,
        fee_bps=1.0,
        slippage_bps=0.0,
    )

    loss_prevention_config = load_loss_prevention_config()
    
    engine = DecisionEngine(
        data_readiness_config=data_readiness_config,
        global_gate_config=global_gate_config,
        ev_gate_config=loss_prevention_config.ev_gate,
        ev_position_sizer_config=loss_prevention_config.ev_position_sizer,
        cost_data_quality_config=loss_prevention_config.cost_data_quality,
    )
    
    worker = ReplayWorker(
        engine=engine,
        config=config,
        simulate=False,  # Don't simulate execution, just check signal generation
        starting_equity=10000.0,
    )
    
    print("Running replay...")
    results = await worker.run()
    
    # Analyze results
    total = len(results)
    accepted = sum(1 for r in results if r["decision"] == "accepted")
    rejected = sum(1 for r in results if r["decision"] == "rejected")
    warmup = sum(1 for r in results if r["decision"] == "warmup")
    
    print("\n=== Replay Summary ===")
    print(f"Total snapshots: {total}")
    print(f"Accepted: {accepted}")
    print(f"Rejected: {rejected}")
    print(f"Warmup: {warmup}")
    
    # Count rejection reasons
    rejection_reasons = {}
    for r in results:
        if r["decision"] == "rejected" and "rejection_reason" in r:
            reason = r["rejection_reason"]
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    
    if rejection_reasons:
        print("\n=== Top Rejection Reasons ===")
        sorted_reasons = sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True)
        for reason, count in sorted_reasons[:10]:
            print(f"{reason}: {count} ({count/total*100:.1f}%)")
    
    # Save results
    output_data = {
        "summary": {
            "total_snapshots": total,
            "accepted": accepted,
            "rejected": rejected,
            "warmup": warmup,
            "rejection_reasons": rejection_reasons,
        },
        "results": results[:100],  # Save first 100 for inspection
    }
    
    with output_path.open("w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to {output_path}")
    
    # Verify trade count > 0 (requirement)
    if accepted > 0:
        print(f"\n✓ SUCCESS: Generated {accepted} signals (was 0 before changes)")
        return 0
    else:
        print(f"\n✗ FAILURE: No signals generated (expected > 0)")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
