import asyncio
import json
from pathlib import Path
import tempfile

import os

from quantgambit.backtesting.replay_worker import ReplayWorker, ReplayConfig, _cap_samples
from quantgambit.backtesting.store import BacktestStore


class FakeEngine:
    async def decide_with_context(self, decision_input):
        class Ctx:
            signal = {"side": "buy", "size": 1.0, "strategy_id": "s1", "reason": "trend"}
            rejection_reason = None
            profile_id = "p1"

        return True, Ctx()


def test_replay_worker_simulation_report_includes_fees_and_slippage():
    snapshots = [
        {
            "symbol": "BTC",
            "timestamp": 1,
            "market_context": {"price": 100.0},
            "features": {},
        },
        {
            "symbol": "BTC",
            "timestamp": 2,
            "market_context": {"price": 110.0},
            "features": {},
        },
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "snapshots.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for snap in snapshots:
                handle.write(json.dumps(snap) + "\n")
        worker = ReplayWorker(
            FakeEngine(),
            ReplayConfig(input_path=path, fee_bps=5.0, slippage_bps=10.0),
            simulate=True,
            starting_equity=10000.0,
        )

        async def run_once():
            await worker.run()

        asyncio.run(run_once())
        report = worker.get_report()
        assert report is not None
        assert report.total_fees > 0.0
        assert report.avg_slippage_bps >= 0.0
        assert report.total_return_pct != 0.0


def test_replay_worker_persists_metrics():
    class FakePool:
        def __init__(self):
            self.calls = []

        def acquire(self):
            calls = self.calls

            class Conn:
                async def execute(self, query, *args):
                    calls.append((query, args))

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return None

            return Conn()

    pool = FakePool()
    store = BacktestStore(pool)
    class ToggleEngine:
        def __init__(self):
            self.count = 0

        async def decide_with_context(self, decision_input):
            self.count += 1

            class Ctx:
                rejection_reason = None
                profile_id = "p1"

            ctx = Ctx()
            ctx.signal = {"side": "buy", "size": 1.0} if self.count == 1 else {"side": "sell", "size": 1.0}
            return True, ctx

    snapshots = [
        {"symbol": "BTC", "timestamp": 1, "market_context": {"price": 100.0}, "features": {}},
        {"symbol": "BTC", "timestamp": 2, "market_context": {"price": 110.0}, "features": {}},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "snapshots.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for snap in snapshots:
                handle.write(json.dumps(snap) + "\n")
        worker = ReplayWorker(
            ToggleEngine(),
            ReplayConfig(input_path=path, run_id="run-1", tenant_id="t1", bot_id="b1", equity_sample_every=1),
            simulate=True,
            starting_equity=10000.0,
            backtest_store=store,
        )

        async def run_once():
            await worker.run()

        asyncio.run(run_once())
    assert pool.calls
    assert any("backtest_trades" in call[0] for call in pool.calls)
    assert any("backtest_equity_curve" in call[0] for call in pool.calls)
    assert any("backtest_symbol_equity_curve" in call[0] for call in pool.calls)
    assert any("backtest_symbol_metrics" in call[0] for call in pool.calls)
    assert any("backtest_decision_snapshots" in call[0] for call in pool.calls)
    assert any("backtest_position_snapshots" in call[0] for call in pool.calls)


def test_replay_worker_latency_uses_later_snapshot_price():
    class OneShotEngine:
        def __init__(self):
            self.count = 0

        async def decide_with_context(self, decision_input):
            self.count += 1

            class Ctx:
                rejection_reason = None
                profile_id = "p1"

            ctx = Ctx()
            ctx.signal = {"side": "buy", "size": 1.0} if self.count == 1 else None
            return True, ctx

    snapshots = [
        {"symbol": "BTC", "timestamp": 1, "market_context": {"price": 100.0}, "features": {}},
        {"symbol": "BTC", "timestamp": 2, "market_context": {"price": 110.0}, "features": {}},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "snapshots.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for snap in snapshots:
                handle.write(json.dumps(snap) + "\n")
        worker = ReplayWorker(
            OneShotEngine(),
            ReplayConfig(input_path=path, latency_ms=1000),
            simulate=True,
            starting_equity=10000.0,
        )

        async def run_once():
            await worker.run()

        asyncio.run(run_once())
        assert worker.simulator.trades
        trade = worker.simulator.trades[0]
        assert trade.entry_price == 110.0


def test_replay_worker_caps_samples():
    items = list(range(10))
    assert _cap_samples(items, 3) == [0, 4, 9]


def test_replay_config_from_env():
    os.environ["BACKTEST_EQUITY_SAMPLE_EVERY"] = "5"
    os.environ["BACKTEST_MAX_EQUITY_POINTS"] = "10"
    os.environ["BACKTEST_MAX_SYMBOL_EQUITY_POINTS"] = "9"
    os.environ["BACKTEST_MAX_DECISION_SNAPSHOTS"] = "11"
    os.environ["BACKTEST_MAX_POSITION_SNAPSHOTS"] = "12"
    os.environ["BACKTEST_WARMUP_SNAPSHOTS"] = "2"
    os.environ["BACKTEST_WARMUP_REQUIRE_READY"] = "true"
    cfg = ReplayConfig.from_env(Path("snapshots.jsonl"))
    assert cfg.equity_sample_every == 5
    assert cfg.max_equity_points == 10
    assert cfg.max_symbol_equity_points == 9
    assert cfg.max_decision_snapshots == 11
    assert cfg.max_position_snapshots == 12
    assert cfg.warmup_min_snapshots == 2
    assert cfg.warmup_require_ready is True
