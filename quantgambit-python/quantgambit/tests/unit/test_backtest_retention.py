import asyncio

from quantgambit.backtesting.retention import BacktestRetentionWorker, BacktestRetentionConfig


class FakePool:
    def __init__(self):
        self.calls = []
        self.fetch_calls = []

    def acquire(self):
        calls = self.calls
        fetch_calls = self.fetch_calls

        class Conn:
            async def execute(self, query, *args):
                calls.append((query, args))

            async def fetch(self, query, *args):
                fetch_calls.append((query, args))
                if "FROM backtest_runs" in query:
                    return [{"tenant_id": "t1"}]
                if "FROM data_settings" in query:
                    return [
                        {
                            "tenant_id": "t1",
                            "replay_snapshot_retention_days": 7,
                            "backtest_history_retention_days": 30,
                        }
                    ]
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        return Conn()


def test_backtest_retention_prunes_snapshots():
    pool = FakePool()
    worker = BacktestRetentionWorker(pool, config=BacktestRetentionConfig(snapshot_retention_days=7, interval_seconds=1))

    async def run_once():
        await worker.prune()

    asyncio.run(run_once())
    queries = [call[0] for call in pool.calls]
    assert any("backtest_decision_snapshots" in query for query in queries)
    assert any("backtest_position_snapshots" in query for query in queries)
    assert any("backtest_equity_curve" in query for query in queries)
    assert any("backtest_symbol_equity_curve" in query for query in queries)
    assert any("DELETE FROM backtest_runs" in query for query in queries)
    assert any("FROM backtest_runs" in query for query, _ in pool.fetch_calls)
    assert any("FROM data_settings" in query for query, _ in pool.fetch_calls)
