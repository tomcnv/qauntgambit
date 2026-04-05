"""CLI for backtesting operations."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="quantgambit.backtesting",
        description="Backtesting CLI for QuantGambit trading bot",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export feature snapshots to JSONL")
    export_parser.add_argument("--output", "-o", required=True, help="Output JSONL file path")
    export_parser.add_argument("--symbol", "-s", help="Filter by symbol (e.g., BTC-USDT-SWAP)")
    export_parser.add_argument("--start", help="Start time (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)")
    export_parser.add_argument("--end", help="End time (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)")
    export_parser.add_argument("--redis-url", default="redis://localhost:6379", help="Redis URL")
    export_parser.add_argument("--stream-key", default="events:feature_snapshots", help="Redis stream key")
    export_parser.add_argument("--max-snapshots", type=int, help="Maximum snapshots to export")

    # Replay command
    replay_parser = subparsers.add_parser("replay", help="Replay snapshots through decision engine")
    replay_parser.add_argument("--input", "-i", required=True, help="Input JSONL file path")
    replay_parser.add_argument("--output", "-o", help="Output JSON file for results")
    replay_parser.add_argument("--fee-bps", type=float, default=1.0, help="Fee rate in basis points")
    replay_parser.add_argument("--slippage-bps", type=float, default=0.0, help="Slippage in basis points")
    replay_parser.add_argument("--starting-equity", type=float, default=10000.0, help="Starting equity")
    replay_parser.add_argument("--simulate", action="store_true", help="Enable execution simulation")
    replay_parser.add_argument("--store-db", action="store_true", help="Store results in database")
    replay_parser.add_argument("--run-id", help="Run ID for database storage")

    # Sweep command
    sweep_parser = subparsers.add_parser("sweep", help="Run EV threshold sweep")
    sweep_parser.add_argument("--input", "-i", required=True, help="Input trades JSONL file")
    sweep_parser.add_argument("--output", "-o", help="Output JSON file for results")
    sweep_parser.add_argument("--min-trades-per-day", type=float, default=5.0, help="Minimum trades per day")
    sweep_parser.add_argument("--sweep-start", type=float, default=0.0, help="Sweep start threshold")
    sweep_parser.add_argument("--sweep-end", type=float, default=0.5, help="Sweep end threshold")
    sweep_parser.add_argument("--sweep-step", type=float, default=0.01, help="Sweep step size")
    sweep_parser.add_argument("--trading-days", type=float, help="Number of trading days (auto-calculated if not set)")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Run walk-forward validation")
    validate_parser.add_argument("--input", "-i", required=True, help="Input trades JSONL file")
    validate_parser.add_argument("--output", "-o", help="Output JSON file for results")
    validate_parser.add_argument("--n-folds", type=int, default=5, help="Number of folds")
    validate_parser.add_argument("--train-ratio", type=float, default=0.7, help="Training ratio per fold")
    validate_parser.add_argument("--min-trades-per-day", type=float, default=5.0, help="Minimum trades per day")

    # Execution sweep command
    exec_sweep_parser = subparsers.add_parser("exec-sweep", help="Run slippage/latency execution sweep")
    exec_sweep_parser.add_argument("--symbol", required=True, help="Trading symbol (e.g., BTCUSDT)")
    exec_sweep_parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    exec_sweep_parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    exec_sweep_parser.add_argument("--exchange", default="bybit", help="Exchange name")
    exec_sweep_parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    exec_sweep_parser.add_argument("--bot-id", default="default", help="Bot ID")
    exec_sweep_parser.add_argument(
        "--slippage-bps",
        default="0.5,1,2,5",
        help="Comma-separated slippage bps values",
    )
    exec_sweep_parser.add_argument(
        "--latency-ms",
        default="0,100,250,500",
        help="Comma-separated latency ms values",
    )
    exec_sweep_parser.add_argument("--output", "-o", required=True, help="Output base path for JSON/CSV report")
    exec_sweep_parser.add_argument("--seed", type=int, default=42, help="Execution simulator seed")
    exec_sweep_parser.add_argument("--name-prefix", default="execution_sweep", help="Run name prefix")
    exec_sweep_parser.add_argument(
        "--force-run",
        action="store_true",
        help="Force run even if data validation fails",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "export":
            exit_code = asyncio.run(_run_export(args))
        elif args.command == "replay":
            exit_code = asyncio.run(_run_replay(args))
        elif args.command == "sweep":
            exit_code = _run_sweep(args)
        elif args.command == "validate":
            exit_code = _run_validate(args)
        elif args.command == "exec-sweep":
            exit_code = asyncio.run(_run_execution_sweep(args))
        else:
            parser.print_help()
            exit_code = 1
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def _run_export(args) -> int:
    """Run export command."""
    from quantgambit.backtesting.snapshot_exporter import export_snapshots

    start_time = _parse_datetime(args.start) if args.start else None
    end_time = _parse_datetime(args.end) if args.end else None

    count = await export_snapshots(
        output_path=Path(args.output),
        symbol=args.symbol,
        start_time=start_time,
        end_time=end_time,
        redis_url=args.redis_url,
        stream_key=args.stream_key,
        max_snapshots=args.max_snapshots,
    )

    print(f"Exported {count} snapshots to {args.output}")
    return 0


async def _run_replay(args) -> int:
    """Run replay command."""
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

    config = ReplayConfig(
        input_path=Path(args.input),
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        run_id=args.run_id,
    )

    # Configure degradation manager for backtesting (no cooldowns, relaxed thresholds)
    degradation_config = DegradationConfig(
        # Disable staleness checks for backtesting (data is historical)
        trade_stale_reduce_sec=86400 * 365 * 10,
        trade_stale_no_entry_sec=86400 * 365 * 10,
        trade_stale_flatten_sec=86400 * 365 * 10,
        orderbook_stale_reduce_sec=86400 * 365 * 10,
        orderbook_stale_no_entry_sec=86400 * 365 * 10,
        orderbook_stale_flatten_sec=86400 * 365 * 10,
        # Disable quality checks for backtesting
        quality_reduce_threshold=0.0,
        quality_no_entry_threshold=0.0,
        quality_flatten_threshold=0.0,
        # Relax spread/depth thresholds for backtesting
        spread_reduce_bps=1000.0,
        spread_no_entry_bps=1000.0,
        depth_reduce_usd=0.0,
        depth_no_entry_usd=0.0,
        # No cooldowns for backtesting
        upgrade_cooldown_sec=0.0,
        downgrade_cooldown_sec=0.0,
        flatten_on_ws_disconnect=False,
    )
    set_degradation_manager(DegradationManager(degradation_config))

    # Configure data readiness for backtesting (allow old data)
    data_readiness_config = DataReadinessConfig(
        max_trade_age_sec=86400 * 365 * 10,  # 10 years - effectively disable staleness check
        max_clock_drift_sec=86400 * 365 * 10,
        require_ws_connected=False,
        use_cts_latency_gates=False,
    )

    # Configure global gate for backtesting (allow old snapshots)
    global_gate_config = GlobalGateConfig(
        snapshot_age_ok_ms=86400 * 365 * 10 * 1000,  # 10 years in ms
        snapshot_age_reduce_ms=86400 * 365 * 10 * 1000,
        snapshot_age_block_ms=86400 * 365 * 10 * 1000,
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
        simulate=args.simulate,
        starting_equity=args.starting_equity,
    )

    results = await worker.run()
    report = worker.get_report()

    # Print summary
    print("\n=== Replay Summary ===")
    print(f"Total snapshots: {len(results)}")
    
    accepted = sum(1 for r in results if r["decision"] == "accepted")
    rejected = sum(1 for r in results if r["decision"] == "rejected")
    warmup = sum(1 for r in results if r["decision"] == "warmup")
    
    print(f"Accepted: {accepted}")
    print(f"Rejected: {rejected}")
    print(f"Warmup: {warmup}")

    if report:
        print(f"\n=== Simulation Report ===")
        print(f"Total trades: {report.total_trades}")
        print(f"Realized PnL: ${report.realized_pnl:.2f}")
        print(f"Total return: {report.total_return_pct:.2f}%")
        print(f"Win rate: {report.win_rate:.1%}")
        print(f"Max drawdown: {report.max_drawdown_pct:.2f}%")
        print(f"Profit factor: {report.profit_factor:.2f}")
        print(f"Total fees: ${report.total_fees:.2f}")

    if args.output:
        output_data = {
            "results": results,
            "summary": {
                "total_snapshots": len(results),
                "accepted": accepted,
                "rejected": rejected,
                "warmup": warmup,
            },
        }
        if report:
            output_data["report"] = {
                "total_trades": report.total_trades,
                "realized_pnl": report.realized_pnl,
                "total_return_pct": report.total_return_pct,
                "win_rate": report.win_rate,
                "max_drawdown_pct": report.max_drawdown_pct,
                "profit_factor": report.profit_factor,
                "total_fees": report.total_fees,
            }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults written to {args.output}")

    return 0


def _run_sweep(args) -> int:
    """Run EV threshold sweep command."""
    from quantgambit.backtesting.ev_threshold_sweep import (
        EVThresholdSweeper,
        BacktestTrade,
        generate_sweep_report,
    )

    # Load trades from JSONL
    trades = _load_trades(args.input)
    if not trades:
        print("No trades found in input file", file=sys.stderr)
        return 1

    # Calculate trading days if not provided
    trading_days = args.trading_days
    if trading_days is None:
        timestamps = [t.timestamp for t in trades]
        if timestamps:
            min_ts = min(timestamps)
            max_ts = max(timestamps)
            trading_days = max((max_ts - min_ts) / 86400.0, 1.0)
        else:
            trading_days = 1.0

    sweeper = EVThresholdSweeper(
        min_trades_per_day=args.min_trades_per_day,
        sweep_start=args.sweep_start,
        sweep_end=args.sweep_end,
        sweep_step=args.sweep_step,
    )

    result = sweeper.sweep(trades, trading_days=trading_days)

    # Print summary
    print("\n=== EV Threshold Sweep Results ===")
    print(f"Trades analyzed: {len(trades)}")
    print(f"Trading days: {trading_days:.1f}")
    print(f"Thresholds tested: {len(result.metrics_by_threshold)}")
    print(f"\nOptimal EV_Min: {result.optimal_ev_min:.4f}")
    
    if result.knee_ev_min is not None:
        print(f"Knee point: {result.knee_ev_min:.4f}")

    # Find optimal metrics
    optimal_metrics = result.optimal_metrics
    if optimal_metrics:
        print(f"\n=== Optimal Threshold Metrics ===")
        print(f"Trades/day: {optimal_metrics.trades_per_day:.2f}")
        print(f"Win rate: {optimal_metrics.win_rate:.1%}")
        print(f"Sharpe ratio: {optimal_metrics.sharpe_ratio:.2f}")
        print(f"Sortino ratio: {optimal_metrics.sortino_ratio:.2f}")
        print(f"Max drawdown: {optimal_metrics.max_drawdown_bps:.1f} bps")
        print(f"Profit factor: {optimal_metrics.profit_factor:.2f}")

    if args.output:
        output_data = {
            "optimal_ev_min": result.optimal_ev_min,
            "knee_point": result.knee_ev_min,
            "trading_days": trading_days,
            "total_trades": len(trades),
            "recommendation_reason": result.recommendation_reason,
            "metrics": [
                {
                    "threshold": m.ev_min,
                    "trades_per_day": m.trades_per_day,
                    "win_rate": m.win_rate,
                    "sharpe_ratio": m.sharpe_ratio,
                    "sortino_ratio": m.sortino_ratio,
                    "max_drawdown_bps": m.max_drawdown_bps,
                    "profit_factor": m.profit_factor,
                    "cvar_95": m.cvar_95,
                }
                for m in result.metrics_by_threshold
            ],
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults written to {args.output}")

    return 0


def _run_validate(args) -> int:
    """Run walk-forward validation command."""
    from quantgambit.backtesting.ev_threshold_sweep import (
        EVThresholdSweeper,
        WalkForwardValidator,
    )

    # Load trades from JSONL
    trades = _load_trades(args.input)
    if not trades:
        print("No trades found in input file", file=sys.stderr)
        return 1

    sweeper = EVThresholdSweeper(min_trades_per_day=args.min_trades_per_day)
    validator = WalkForwardValidator(
        sweeper=sweeper,
        n_folds=args.n_folds,
        train_ratio=args.train_ratio,
    )

    result = validator.validate(trades)

    # Print summary
    print("\n=== Walk-Forward Validation Results ===")
    print(f"Trades analyzed: {len(trades)}")
    print(f"Folds: {args.n_folds}")
    print(f"Train ratio: {args.train_ratio:.0%}")
    print(f"\nIs Robust: {'Yes' if result.is_robust else 'No'}")
    print(f"Threshold stability: {result.threshold_stability:.1%}")
    print(f"Avg performance degradation: {result.avg_performance_degradation:.1%}")

    print(f"\n=== Fold Results ===")
    for i, fold in enumerate(result.fold_results, 1):
        print(f"\nFold {i}:")
        print(f"  Train threshold: {fold.in_sample_optimal_ev_min:.4f}")
        print(f"  Train Sharpe: {fold.in_sample_sharpe:.2f}")
        print(f"  Test Sharpe: {fold.out_sample_sharpe:.2f}")
        print(f"  Degradation: {fold.performance_degradation:.1%}")

    if args.output:
        output_data = {
            "is_robust": result.is_robust,
            "threshold_stability": result.threshold_stability,
            "avg_degradation": result.avg_performance_degradation,
            "fold_results": [
                {
                    "train_optimal_threshold": f.in_sample_optimal_ev_min,
                    "train_sharpe": f.in_sample_sharpe,
                    "test_sharpe": f.out_sample_sharpe,
                    "degradation": f.performance_degradation,
                }
                for f in result.fold_results
            ],
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults written to {args.output}")

    return 0


async def _run_execution_sweep(args) -> int:
    from quantgambit.backtesting.strategy_executor import StrategyBacktestExecutor, StrategyExecutorConfig
    import asyncpg

    slippage_values = _parse_float_list(args.slippage_bps)
    latency_values = _parse_float_list(args.latency_ms)

    db_host = os.getenv("DASHBOARD_DB_HOST", os.getenv("PLATFORM_DB_HOST", "localhost"))
    db_port = os.getenv("DASHBOARD_DB_PORT", "5432")
    db_name = os.getenv("DASHBOARD_DB_NAME", "platform_db")
    db_user = os.getenv("DASHBOARD_DB_USER", "platform")
    db_password = os.getenv("DASHBOARD_DB_PASSWORD", "platform_pw")

    auth = f"{db_user}:{db_password}@" if db_password else f"{db_user}@"
    dsn = f"postgresql://{auth}{db_host}:{db_port}/{db_name}"
    platform_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)

    executor = StrategyBacktestExecutor(platform_pool, StrategyExecutorConfig.from_env())

    results = []
    for slippage in slippage_values:
        for latency in latency_values:
            run_id = str(uuid.uuid4())
            config = {
                "symbol": args.symbol,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "exchange": args.exchange,
                "force_run": args.force_run,
                "execution_scenario": "realistic",
                "execution_slippage_bps": slippage,
                "execution_latency_ms": latency,
                "execution_simulator_seed": args.seed,
                "name": f"{args.name_prefix}_{slippage}bps_{latency}ms",
            }

            result = await executor.execute(
                run_id=run_id,
                tenant_id=args.tenant_id,
                bot_id=args.bot_id,
                config=config,
            )
            metrics = result.get("metrics", {})
            trades = result.get("trades", [])

            total_fees = sum(t.get("total_fees", 0.0) for t in trades)
            total_slippage_cost = sum(
                t.get("size", 0.0)
                * t.get("entry_price", 0.0)
                * (t.get("entry_slippage_bps", 0.0) / 10000.0)
                + t.get("size", 0.0)
                * t.get("exit_price", 0.0)
                * (t.get("exit_slippage_bps", 0.0) / 10000.0)
                for t in trades
            )
            net_pnl = metrics.get("realized_pnl", 0.0)
            total_costs = total_fees + total_slippage_cost
            gross_pnl = net_pnl + total_costs
            cost_pct_of_gross = (total_costs / gross_pnl * 100.0) if gross_pnl > 0 else 0.0

            turnover = sum(
                abs(t.get("size", 0.0) * t.get("entry_price", 0.0))
                + abs(t.get("size", 0.0) * t.get("exit_price", 0.0))
                for t in trades
            )

            results.append(
                {
                    "slippage_bps": slippage,
                    "latency_ms": latency,
                    "total_trades": metrics.get("total_trades", 0),
                    "net_return_pct": metrics.get("total_return_pct", 0.0),
                    "net_sharpe": metrics.get("sharpe_ratio", 0.0),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct", 0.0),
                    "turnover_usd": turnover,
                    "total_fees": total_fees,
                    "total_slippage_cost": total_slippage_cost,
                    "cost_pct_of_gross": cost_pct_of_gross,
                }
            )

    output_base = Path(args.output)
    if output_base.suffix.lower() in {".json", ".csv"}:
        output_base = output_base.with_suffix("")
    json_path = output_base.with_suffix(".json")
    csv_path = output_base.with_suffix(".csv")

    with open(json_path, "w") as f:
        json.dump({"results": results}, f, indent=2)

    if results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

    await executor.close()
    await platform_pool.close()

    print(f"Execution sweep report written to {json_path} and {csv_path}")
    return 0


def _parse_float_list(value: str) -> list[float]:
    items = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        items.append(float(part))
    return items


def _load_trades(path: str) -> list:
    """Load BacktestTrade objects from JSONL file."""
    from quantgambit.backtesting.ev_threshold_sweep import BacktestTrade

    trades = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            trades.append(BacktestTrade(
                timestamp=data.get("timestamp", 0),
                symbol=data.get("symbol", ""),
                side=data.get("side", "long"),
                entry_price=data.get("entry_price", 0.0),
                stop_loss=data.get("stop_loss", 0.0),
                take_profit=data.get("take_profit", 0.0),
                p_hat=data.get("p_hat", data.get("confidence", 0.5)),
                outcome=data.get("outcome", 1 if data.get("pnl_bps", 0) > 0 else 0),
                pnl_bps=data.get("pnl_bps", 0.0),
                spread_bps=data.get("spread_bps", 0.0),
                fee_bps=data.get("fee_bps", 0.0),
                slippage_bps=data.get("slippage_bps", 0.0),
                adverse_selection_bps=data.get("adverse_selection_bps", 1.5),
                regime_label=data.get("regime_label"),
                session=data.get("session"),
                hold_time_seconds=data.get("hold_time_seconds", 0.0),
            ))
    return trades


def _parse_datetime(value: str) -> Optional[datetime]:
    """Parse datetime from various formats."""
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value}")


if __name__ == "__main__":
    main()
