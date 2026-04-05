#!/usr/bin/env python3
"""Run replay on sample data to verify rejection logging."""

import asyncio
import json
import logging
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
    """Run replay test on sample data."""
    # Configure logging to capture rejection details
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[
            logging.FileHandler('/tmp/sample_replay.log'),
        ]
    )
    
    # Set specific loggers to INFO to capture rejection details
    logging.getLogger('quantgambit.deeptrader_core.strategies.mean_reversion_fade').setLevel(logging.INFO)
    logging.getLogger('quantgambit.deeptrader_core.strategies.vol_expansion').setLevel(logging.INFO)
    
    input_path = Path("/tmp/sample_1000.jsonl")
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1
    
    print(f"Running replay on {input_path}")
    
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
        simulate=False,
        starting_equity=10000.0,
    )
    
    print("Running replay...")
    results = await worker.run()
    
    # Analyze results
    total = len(results)
    accepted = sum(1 for r in results if r["decision"] == "accepted")
    rejected = sum(1 for r in results if r["decision"] == "rejected")
    
    print(f"\nProcessed {total} snapshots")
    print(f"Accepted: {accepted}, Rejected: {rejected}")
    print(f"\nLogs written to /tmp/sample_replay.log")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
