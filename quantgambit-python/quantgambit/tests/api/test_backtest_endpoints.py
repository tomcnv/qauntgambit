import asyncio
from fastapi.testclient import TestClient

from quantgambit.api.app import app, _dashboard_pool
from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
    BacktestMetricsRecord,
    BacktestTradeRecord,
    BacktestEquityPoint,
    BacktestDecisionSnapshot,
)


class _FakeConn:
    def __init__(self, tables):
        self.tables = tables

    class _FakeTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def transaction(self):
        return self._FakeTx()

    async def execute(self, query, *params):
        if "INSERT INTO backtest_runs" in query:
            # Store may evolve; only validate the core fields we assert on.
            # Current store includes an additional `execution_diagnostics` param.
            if len(params) < 13:
                raise ValueError(f"expected>=13 params, got {len(params)}")
            (
                run_id, tenant_id, bot_id, status, started_at, finished_at, config,
                name, symbol, start_date, end_date, error_message, created_at, *rest
            ) = params
            self.tables["backtest_runs"][run_id] = {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "bot_id": bot_id,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "config": config,
                "name": name,
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "error_message": error_message,
                "created_at": created_at,
                "execution_diagnostics": rest[0] if rest else None,
            }
            return
        if "INSERT INTO backtest_metrics" in query:
            if len(params) < 10:
                raise ValueError(f"expected>=10 params, got {len(params)}")
            (
                run_id,
                realized_pnl,
                total_fees,
                total_trades,
                win_rate,
                max_drawdown_pct,
                avg_slippage_bps,
                total_return_pct,
                profit_factor,
                avg_trade_pnl,
                *rest,
            ) = params
            self.tables["backtest_metrics"][run_id] = {
                "run_id": run_id,
                "realized_pnl": realized_pnl,
                "total_fees": total_fees,
                "total_trades": total_trades,
                "win_rate": win_rate,
                "max_drawdown_pct": max_drawdown_pct,
                "avg_slippage_bps": avg_slippage_bps,
                "total_return_pct": total_return_pct,
                "profit_factor": profit_factor,
                "avg_trade_pnl": avg_trade_pnl,
            }
            return
        if "INSERT INTO backtest_trades" in query:
            (
                run_id,
                ts,
                symbol,
                side,
                size,
                entry_price,
                exit_price,
                pnl,
                entry_fee,
                exit_fee,
                total_fees,
                entry_slippage_bps,
                exit_slippage_bps,
                strategy_id,
                profile_id,
                reason,
            ) = params
            self.tables["backtest_trades"].append(
                {
                    "run_id": run_id,
                    "ts": ts,
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "entry_fee": entry_fee,
                    "exit_fee": exit_fee,
                    "total_fees": total_fees,
                    "entry_slippage_bps": entry_slippage_bps,
                    "exit_slippage_bps": exit_slippage_bps,
                    "strategy_id": strategy_id,
                    "profile_id": profile_id,
                    "reason": reason,
                }
            )
            return
        if "INSERT INTO backtest_equity_curve" in query:
            run_id, ts, equity, realized_pnl, open_positions = params
            self.tables["backtest_equity_curve"].append(
                {
                    "run_id": run_id,
                    "ts": ts,
                    "equity": equity,
                    "realized_pnl": realized_pnl,
                    "open_positions": open_positions,
                }
            )
            return
        if "INSERT INTO backtest_decision_snapshots" in query:
            run_id, ts, symbol, decision, rejection_reason, profile_id, payload = params
            self.tables["backtest_decision_snapshots"].append(
                {
                    "run_id": run_id,
                    "ts": ts,
                    "symbol": symbol,
                    "decision": decision,
                    "rejection_reason": rejection_reason,
                    "profile_id": profile_id,
                    "payload": payload,
                }
            )
            return
        if "INSERT INTO bot_profiles " in query:
            bot_id, name, environment, engine_type, description, status, metadata = params
            self.tables["bot_profiles"][bot_id] = {
                "id": bot_id,
                "name": name,
                "environment": environment,
                "engine_type": engine_type,
                "description": description,
                "status": status,
                "metadata": metadata,
                "active_version_id": None,
            }
            return
        if "UPDATE bot_profiles SET active_version_id=" in query:
            version_id, bot_id = params
            if bot_id in self.tables["bot_profiles"]:
                self.tables["bot_profiles"][bot_id]["active_version_id"] = version_id
            return

    async def fetch(self, query, *params):
        if "FROM backtest_runs" in query:
            tenant_id, bot_id, limit = params
            rows = []
            for row in self.tables["backtest_runs"].values():
                if row["tenant_id"] == tenant_id and row["bot_id"] == bot_id:
                    # Parse config back to dict if it's a string (as stored by the store)
                    row_copy = dict(row)
                    if isinstance(row_copy.get("config"), str):
                        import json
                        row_copy["config"] = json.loads(row_copy["config"])
                    rows.append(row_copy)
            rows.sort(key=lambda row: row["started_at"], reverse=True)
            return rows[: int(limit)]
        if "FROM backtest_equity_curve" in query:
            run_id = params[0]
            rows = [row for row in self.tables["backtest_equity_curve"] if row["run_id"] == run_id]
            rows.sort(key=lambda row: row["ts"])
            return rows
        if "FROM backtest_decision_snapshots" in query:
            run_id = params[0]
            rows = [row for row in self.tables["backtest_decision_snapshots"] if row["run_id"] == run_id]
            rows.sort(key=lambda row: row["ts"])
            return rows
        if "FROM backtest_trades" in query:
            run_id = params[0]
            rows = [row for row in self.tables["backtest_trades"] if row["run_id"] == run_id]
            rows.sort(key=lambda row: row["ts"])
            return rows
        return []

    async def fetchrow(self, query, *params):
        if "FROM backtest_runs" in query:
            run_id = params[0]
            row = self.tables["backtest_runs"].get(run_id)
            if row:
                # Ensure all fields are present for the response
                return {
                    "run_id": row.get("run_id"),
                    "tenant_id": row.get("tenant_id"),
                    "bot_id": row.get("bot_id"),
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    "finished_at": row.get("finished_at"),
                    "config": row.get("config"),
                    "name": row.get("name"),
                    "symbol": row.get("symbol"),
                    "start_date": row.get("start_date"),
                    "end_date": row.get("end_date"),
                    "error_message": row.get("error_message"),
                    "created_at": row.get("created_at"),
                }
            return None
        if "FROM backtest_metrics" in query:
            run_id = params[0]
            return self.tables["backtest_metrics"].get(run_id)
        if "SELECT id FROM bot_profiles WHERE id=$1" in query:
            bot_id = params[0]
            return {"id": bot_id} if bot_id in self.tables["bot_profiles"] else None
        if "SELECT COALESCE(MAX(version_number), 0) AS max_version" in query:
            bot_id = params[0]
            versions = self.tables["bot_profile_versions"].get(bot_id, [])
            return {"max_version": max((v["version_number"] for v in versions), default=0)}
        if "INSERT INTO bot_profile_versions " in query and "RETURNING id, version_number" in query:
            import uuid

            bot_id, version_number, status, config_blob, notes, promoted_by = params
            version_id = str(uuid.uuid4())
            self.tables["bot_profile_versions"].setdefault(bot_id, []).append(
                {
                    "id": version_id,
                    "bot_profile_id": bot_id,
                    "version_number": version_number,
                    "status": status,
                    "config_blob": config_blob,
                    "notes": notes,
                    "promoted_by": promoted_by,
                }
            )
            return {"id": version_id, "version_number": version_number}
        return None


class _FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.tables = {
            "backtest_runs": {},
            "backtest_metrics": {},
            "backtest_trades": [],
            "backtest_equity_curve": [],
            "backtest_decision_snapshots": [],
            "bot_profiles": {},
            "bot_profile_versions": {},
        }
        self.conn = _FakeConn(self.tables)

    def acquire(self):
        return _FakeAcquire(self.conn)


def test_backtest_endpoints_roundtrip():
    pool = FakePool()
    store = BacktestStore(pool)
    run_id = "run-1"

    async def seed():
        await store.write_run(
            BacktestRunRecord(
                run_id=run_id,
                tenant_id="t1",
                bot_id="b1",
                status="completed",
                started_at="2024-01-01T00:00:00Z",
                finished_at="2024-01-01T00:05:00Z",
                config={"name": "Test Run"},
                name="Test Run",
                symbol="BTCUSDT",
                start_date="2024-01-01",
                end_date="2024-01-02",
            )
        )
        await store.write_metrics(
            BacktestMetricsRecord(
                run_id=run_id,
                realized_pnl=100.0,
                total_fees=1.5,
                total_trades=1,
                win_rate=1.0,
                max_drawdown_pct=0.5,
                avg_slippage_bps=2.0,
                total_return_pct=1.0,
                profit_factor=2.0,
                avg_trade_pnl=100.0,
            )
        )
        await store.write_equity_points(
            [
                BacktestEquityPoint(
                    run_id=run_id,
                    ts=1.0,
                    equity=10000.0,
                    realized_pnl=100.0,
                    open_positions=0,
                )
            ]
        )
        await store.write_decision_snapshots(
            [
                BacktestDecisionSnapshot(
                    run_id=run_id,
                    ts=1.0,
                    symbol="BTCUSDT",
                    decision="accepted",
                    rejection_reason=None,
                    profile_id="profile-1",
                    payload={"decision": "accepted"},
                )
            ]
        )
        await store.write_trades(
            [
                BacktestTradeRecord(
                    run_id=run_id,
                    ts=1.0,
                    symbol="BTCUSDT",
                    side="buy",
                    size=0.01,
                    entry_price=89000.0,
                    exit_price=89100.0,
                    pnl=100.0,
                    entry_fee=0.5,
                    exit_fee=1.0,
                    total_fees=1.5,
                    entry_slippage_bps=1.0,
                    exit_slippage_bps=1.0,
                    strategy_id="strat-1",
                    profile_id="profile-1",
                    reason="signal",
                )
            ]
        )

    asyncio.run(seed())

    async def _fake_pool_dep():
        try:
            yield pool
        finally:
            pass

    app.dependency_overrides[_dashboard_pool] = _fake_pool_dep
    client = TestClient(app)

    res = client.get("/api/backtests", params={"tenant_id": "t1", "bot_id": "b1"})
    assert res.status_code == 200
    payload = res.json()
    assert payload
    assert payload[0]["id"] == run_id
    assert payload[0]["name"] == "Test Run"

    res = client.get(f"/api/backtests/{run_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["id"] == run_id
    assert detail["metrics"]["total_trades"] == 1
    assert detail["equity_curve"][0]["equity"] == 10000.0
    assert detail["decisions"][0]["decision"] == "accepted"
    assert detail["fills"][0]["symbol"] == "BTCUSDT"


def test_promote_backtest_creates_version_and_activates():
    pool = FakePool()
    store = BacktestStore(pool)
    run_id = "run-promote-1"

    async def seed():
        await store.write_run(
            BacktestRunRecord(
                run_id=run_id,
                tenant_id="t1",
                bot_id="b1",
                status="completed",
                started_at="2024-01-01T00:00:00Z",
                finished_at="2024-01-01T00:05:00Z",
                config={"strategy_id": "s1", "symbol": "BTC-USDT-SWAP"},
                name="Promote Run",
                symbol="BTC-USDT-SWAP",
                start_date="2024-01-01",
                end_date="2024-01-02",
            )
        )

    asyncio.run(seed())

    async def _fake_pool_dep():
        try:
            yield pool
        finally:
            pass

    app.dependency_overrides[_dashboard_pool] = _fake_pool_dep
    client = TestClient(app)

    res = client.post(
        f"/api/research/backtests/{run_id}/promote",
        json={"bot_id": "bot-123", "activate": True, "notes": "promote test"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert body["run_id"] == run_id
    assert body["bot_id"] == "bot-123"
    assert body["activated"] is True
    assert pool.tables["bot_profiles"]["bot-123"]["active_version_id"] == body["version_id"]
    assert len(pool.tables["bot_profile_versions"]["bot-123"]) == 1
