import asyncio

from quantgambit.backtesting.api import BacktestAPI


class FakePool:
    def __init__(
        self,
        runs_rows,
        metrics_rows,
        trades_rows,
        equity_rows,
        symbol_rows,
        symbol_equity_rows,
        decision_rows,
        position_rows,
    ):
        self.runs_rows = runs_rows
        self.metrics_rows = metrics_rows
        self.trades_rows = trades_rows
        self.equity_rows = equity_rows
        self.symbol_rows = symbol_rows
        self.symbol_equity_rows = symbol_equity_rows
        self.decision_rows = decision_rows
        self.position_rows = position_rows

    def acquire(self):
        runs_rows = self.runs_rows
        metrics_rows = self.metrics_rows
        trades_rows = self.trades_rows
        equity_rows = self.equity_rows
        symbol_rows = self.symbol_rows
        symbol_equity_rows = self.symbol_equity_rows
        decision_rows = self.decision_rows
        position_rows = self.position_rows

        class Conn:
            async def fetch(self, query, *args):
                if "backtest_metrics" in query:
                    return metrics_rows
                if "backtest_runs" in query:
                    return runs_rows
                if "backtest_trades" in query:
                    return trades_rows
                if "backtest_equity_curve" in query:
                    return equity_rows
                if "backtest_symbol_metrics" in query:
                    return symbol_rows
                if "backtest_symbol_equity_curve" in query:
                    return symbol_equity_rows
                if "backtest_decision_snapshots" in query:
                    return decision_rows
                if "backtest_position_snapshots" in query:
                    return position_rows
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        return Conn()


def _get_endpoint(app, path: str):
    for route in app.router.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"missing_route:{path}")


def test_backtest_api_runs_metrics_trades():
    runs_rows = [
        {
            "run_id": "run-1",
            "tenant_id": "t1",
            "bot_id": "b1",
            "status": "finished",
            "started_at": "2024-01-01T00:00:00Z",
            "finished_at": "2024-01-01T01:00:00Z",
            "config": {},
        }
    ]
    metrics_rows = [
        {
            "run_id": "run-1",
            "realized_pnl": 1.0,
            "total_fees": 0.1,
            "total_trades": 1,
            "win_rate": 1.0,
            "max_drawdown_pct": 0.0,
            "avg_slippage_bps": 0.0,
            "total_return_pct": 0.1,
            "profit_factor": 2.0,
            "avg_trade_pnl": 1.0,
        }
    ]
    trades_rows = [
        {
            "run_id": "run-1",
            "ts": "2024-01-01T00:00:00Z",
            "symbol": "BTC",
            "side": "buy",
            "size": 1.0,
            "entry_price": 100.0,
            "exit_price": 101.0,
            "pnl": 1.0,
            "entry_fee": 0.05,
            "exit_fee": 0.05,
            "total_fees": 0.1,
            "entry_slippage_bps": 0.0,
            "exit_slippage_bps": 0.0,
            "strategy_id": "s1",
            "profile_id": "p1",
            "reason": "model_signal",
        }
    ]
    equity_rows = [
        {
            "run_id": "run-1",
            "ts": "2024-01-01T00:10:00Z",
            "equity": 1001.0,
            "realized_pnl": 1.0,
            "open_positions": 0,
        }
    ]
    symbol_rows = [
        {
            "run_id": "run-1",
            "symbol": "BTC",
            "realized_pnl": 1.0,
            "total_fees": 0.1,
            "total_trades": 1,
            "win_rate": 1.0,
            "avg_trade_pnl": 1.0,
            "profit_factor": 2.0,
            "avg_slippage_bps": 0.0,
        }
    ]
    symbol_equity_rows = [
        {
            "run_id": "run-1",
            "symbol": "BTC",
            "ts": "2024-01-01T00:10:00Z",
            "equity": 1.5,
            "realized_pnl": 1.0,
            "open_positions": 0,
        }
    ]
    decision_rows = [
        {
            "run_id": "run-1",
            "ts": "2024-01-01T00:00:00Z",
            "symbol": "BTC",
            "decision": "accepted",
            "rejection_reason": None,
            "profile_id": "p1",
            "payload": {},
        }
    ]
    position_rows = [
        {
            "run_id": "run-1",
            "ts": "2024-01-01T00:01:00Z",
            "payload": {"positions": []},
        }
    ]
    api = BacktestAPI(
        FakePool(
            runs_rows,
            metrics_rows,
            trades_rows,
            equity_rows,
            symbol_rows,
            symbol_equity_rows,
            decision_rows,
            position_rows,
        )
    )

    runs_endpoint = _get_endpoint(api.app, "/backtests/runs")
    metrics_endpoint = _get_endpoint(api.app, "/backtests/metrics")
    trades_endpoint = _get_endpoint(api.app, "/backtests/trades")
    equity_endpoint = _get_endpoint(api.app, "/backtests/equity")
    symbol_equity_endpoint = _get_endpoint(api.app, "/backtests/equity/symbols")
    symbols_endpoint = _get_endpoint(api.app, "/backtests/metrics/symbols")
    decisions_endpoint = _get_endpoint(api.app, "/backtests/decisions")
    positions_endpoint = _get_endpoint(api.app, "/backtests/positions")

    import os

    os.environ["AUTH_MODE"] = "none"
    runs = asyncio.run(runs_endpoint(tenant_id="t1", bot_id="b1"))
    metrics = asyncio.run(metrics_endpoint(tenant_id="t1", bot_id="b1"))
    trades = asyncio.run(trades_endpoint(run_id="run-1"))
    equity = asyncio.run(equity_endpoint(run_id="run-1"))
    symbol_equity = asyncio.run(symbol_equity_endpoint(run_id="run-1", symbol="BTC"))
    symbols = asyncio.run(symbols_endpoint(run_id="run-1"))
    decisions = asyncio.run(decisions_endpoint(run_id="run-1", symbol="BTC"))
    positions = asyncio.run(positions_endpoint(run_id="run-1"))

    assert runs and runs[0].run_id == "run-1"
    assert metrics and metrics[0].run_id == "run-1"
    assert trades and trades[0].run_id == "run-1"
    assert equity and equity[0].run_id == "run-1"
    assert symbol_equity and symbol_equity[0].run_id == "run-1"
    assert symbols and symbols[0].run_id == "run-1"
    assert decisions and decisions[0].run_id == "run-1"
    assert positions and positions[0].run_id == "run-1"
