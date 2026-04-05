import asyncio
from types import SimpleNamespace

import pytest

from quantgambit.execution.manager import (
    ExchangeClient,
    ExecutionIntent,
    OrderStatus,
    PositionManager,
    PositionSnapshot,
    RealExecutionManager,
    RiskManager,
    ExchangeRouter,
    _compute_fee_bps,
    _aggregate_execution_trades,
)
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline


class FakeExchange(ExchangeClient):
    def __init__(self, should_succeed=True):
        self.should_succeed = should_succeed
        self.closed = []
        self.opened = []
        self.canceled = []

    async def close_position(
        self,
        symbol: str,
        side: str,
        size: float,
        client_order_id=None,
        order_type: str = "market",
        limit_price=None,
        post_only: bool = False,
        time_in_force=None,
    ):
        self.closed.append((symbol, side, size))
        from quantgambit.execution.manager import OrderStatus
        status = "filled" if self.should_succeed else "rejected"
        return OrderStatus(order_id="close-1", status=status, fill_price=100.0, fee_usd=0.05)

    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        limit_price=None,
        post_only: bool = False,
        time_in_force=None,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ):
        self.opened.append((symbol, side, size, stop_loss, take_profit))
        from quantgambit.execution.manager import OrderStatus
        status = "filled" if self.should_succeed else "rejected"
        return OrderStatus(order_id="open-1", status=status, fill_price=100.0, fee_usd=0.05)

    async def cancel_order(self, order_id, client_order_id, symbol):
        self.canceled.append((order_id, client_order_id, symbol))
        return OrderStatus(
            order_id=order_id or client_order_id,
            status="canceled",
            reason="manual_cancel",
        )


class FakeRejectingExchange(FakeExchange):
    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        limit_price=None,
        post_only: bool = False,
        time_in_force=None,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ):
        self.opened.append((symbol, side, size, stop_loss, take_profit))
        return OrderStatus(order_id=None, status="rejected", reason="exchange_rejected_for_test")


class FakePositions(PositionManager):
    def __init__(self, positions):
        self._positions = positions
        self.closed = []
        self.upserted = []

    async def list_open_positions(self):
        return list(self._positions)

    async def upsert_position(self, snapshot: PositionSnapshot) -> None:
        self.upserted.append(snapshot)

    async def mark_closing(self, symbol: str, reason: str) -> None:
        return None

    async def finalize_close(self, symbol: str) -> None:
        self.closed.append(symbol)


class FakeRisk(RiskManager):
    def __init__(self, should_succeed=True):
        self.should_succeed = should_succeed

    async def apply_overrides(self, overrides, ttl_seconds, scope=None):
        return self.should_succeed


class FakeRouter(ExchangeRouter):
    def __init__(self, should_succeed=True):
        self.should_succeed = should_succeed

    async def switch_to_secondary(self):
        return self.should_succeed

    async def switch_to_primary(self):
        return self.should_succeed


class FakeOrderStore:
    def __init__(self):
        self.records = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


class FakeProtectiveOrderStore(FakeOrderStore):
    def __init__(self):
        super().__init__()
        self.intent_records = []
        self._orders = []

    def list_orders(self):
        return list(self._orders)

    async def record_intent(self, **kwargs):
        self.intent_records.append(kwargs)


class FakeExchangeWithProtective(FakeExchange):
    def __init__(self):
        super().__init__(should_succeed=True)
        self.protective_calls = []

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ):
        self.protective_calls.append(
            {
                "symbol": symbol,
                "side": side,
                "size": size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "client_order_id": client_order_id,
            }
        )
        return True



def test_flatten_positions_success():
    exchange = FakeExchange()
    positions = FakePositions([
        PositionSnapshot(symbol="BTC", side="long", size=1.0),
        PositionSnapshot(symbol="ETH", side="short", size=2.0),
    ])
    manager = RealExecutionManager(exchange, positions)

    result = asyncio.run(manager.flatten_positions())
    assert result.status == "executed"
    assert len(exchange.closed) == 2


def test_execute_intent_preserves_rejection_reason_in_recorded_order():
    exchange = FakeRejectingExchange()
    positions = FakePositions([])
    store = FakeOrderStore()
    manager = RealExecutionManager(exchange, positions, order_store=store)

    async def run_once():
        return await manager.execute_intent(
            ExecutionIntent(
                symbol="BTCUSDT",
                side="long",
                size=1.0,
                client_order_id="cid-1",
            )
        )

    status = asyncio.run(run_once())
    assert status.status == "rejected"
    assert store.records
    assert store.records[-1]["reason"] == "exchange_rejected_for_test"


def test_execute_intent_uses_filled_size_for_protective_orders():
    exchange = FakeExchangeWithProtective()
    positions = FakePositions([])
    manager = RealExecutionManager(exchange, positions)

    async def run_once():
        return await manager.execute_intent(
            ExecutionIntent(
                symbol="BTCUSDT",
                side="long",
                size=5.0,
                stop_loss=90.0,
                take_profit=110.0,
                client_order_id="cid-protective",
            )
        )

    # Simulate a partial/normalized fill coming back from the venue.
    original_open = exchange.open_position

    async def open_with_smaller_fill(*args, **kwargs):
        status = await original_open(*args, **kwargs)
        return OrderStatus(
            order_id=status.order_id,
            status=status.status,
            fill_price=status.fill_price,
            fee_usd=status.fee_usd,
            filled_size=1.25,
            remaining_size=status.remaining_size,
            reference_price=status.reference_price,
            timestamp=status.timestamp,
            source=status.source,
            reason=status.reason,
        )

    exchange.open_position = open_with_smaller_fill

    status = asyncio.run(run_once())
    assert status.status == "filled"
    assert exchange.protective_calls
    assert exchange.protective_calls[-1]["size"] == 1.25


def test_cleanup_protective_orders_terminalizes_intent_mirror():
    exchange = FakeExchange()
    positions = FakePositions([])
    store = FakeProtectiveOrderStore()
    store._orders.append(
        SimpleNamespace(
            order_id="protective-1",
            status="pending",
            symbol="BTCUSDT",
            side="sell",
            size=0.5,
            client_order_id="cid-1:tpl",
        )
    )
    manager = RealExecutionManager(exchange, positions, order_store=store)

    async def run_once():
        await manager._cleanup_protective_orders("BTCUSDT")

    asyncio.run(run_once())

    assert exchange.canceled == [("protective-1", "cid-1:tpl", "BTCUSDT")]
    assert store.records
    assert store.records[-1]["status"] == "canceled"
    assert store.intent_records
    assert store.intent_records[-1]["client_order_id"] == "cid-1:tpl"
    assert store.intent_records[-1]["status"] == "canceled"
    assert store.intent_records[-1]["last_error"] == "manual_cancel"


def test_flatten_positions_emits_telemetry():
    exchange = FakeExchange()
    positions = FakePositions([PositionSnapshot(symbol="BTC", side="long", size=1.0)])

    class FakeTelemetry:
        def __init__(self):
            self.events = []
            self.positions = []
            self.lifecycle = []

        async def publish_order(self, ctx, symbol, payload):
            self.events.append((symbol, payload))

        async def publish_position_lifecycle(self, ctx, symbol, event_type, payload):
            self.lifecycle.append((symbol, event_type, payload))

        async def publish_positions(self, ctx, payload):
            self.positions.append(payload)

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    result = asyncio.run(manager.flatten_positions())
    assert result.status == "executed"
    assert telemetry.events[0][0] == "BTC"
    assert telemetry.positions


def test_flatten_positions_cleans_up_protective_orders():
    exchange = FakeExchange()
    positions = FakePositions([PositionSnapshot(symbol="BTC", side="long", size=1.0)])
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="sell",
            size=1.0,
            status="open",
            order_id="sl-1",
            client_order_id="entry-1:sl",
        )
        await store.record(
            symbol="BTC",
            side="sell",
            size=1.0,
            status="open",
            order_id="tp-1",
            client_order_id="entry-1:tp",
        )

    asyncio.run(seed())
    manager = RealExecutionManager(exchange, positions, order_store=store)

    result = asyncio.run(manager.flatten_positions())

    assert result.status == "executed"
    protective_statuses = {
        record.client_order_id: record.status
        for record in store.list_orders()
        if record.client_order_id in {"entry-1:sl", "entry-1:tp"}
    }
    assert protective_statuses == {"entry-1:sl": "canceled", "entry-1:tp": "canceled"}
    assert exchange.canceled == [
        ("sl-1", "entry-1:sl", "BTC"),
        ("tp-1", "entry-1:tp", "BTC"),
    ]


def test_execute_intent_replaces_existing_protective_orders_before_placing_new_ones():
    exchange = FakeExchange()
    positions = FakePositions([])
    store = InMemoryOrderStore()

    async def seed_and_execute():
        await store.record(
            symbol="BTC",
            side="sell",
            size=1.0,
            status="open",
            order_id="sl-old",
            client_order_id="entry-old:sl",
        )
        await store.record(
            symbol="BTC",
            side="sell",
            size=1.0,
            status="open",
            order_id="tp-old",
            client_order_id="entry-old:tp",
        )
        manager = RealExecutionManager(exchange, positions, order_store=store)
        await manager._place_protective_orders(
            ExecutionIntent(
                symbol="BTC",
                side="long",
                size=1.0,
                client_order_id="entry-new",
                stop_loss=99.0,
                take_profit=101.0,
            ),
            filled_size=1.0,
        )
        return manager

    asyncio.run(seed_and_execute())
    assert exchange.canceled == [
        ("sl-old", "entry-old:sl", "BTC"),
        ("tp-old", "entry-old:tp", "BTC"),
    ]


def test_emit_position_opened_includes_entry_slippage():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeTelemetry:
        def __init__(self):
            self.lifecycle = []

        async def publish_position_lifecycle(self, ctx, symbol, event_type, payload):
            self.lifecycle.append((symbol, event_type, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(
        manager._emit_position_opened(
            symbol="BTC",
            side="buy",
            size=1.0,
            entry_price=100.4,
            entry_timestamp=1000.0,
            fee_usd=0.01,
            stop_loss=95.0,
            take_profit=110.0,
            order_id="open-1",
            client_order_id="cid-open-1",
            decision_id="dec-1",
            strategy_id="strat-1",
            profile_id="profile-1",
            entry_reference_price=100.0,
        )
    )

    payload = telemetry.lifecycle[0][2]
    assert payload["entry_reference_price"] == 100.0
    assert payload["entry_slippage_bps"] == pytest.approx(40.0)


def test_emit_position_closed_includes_realized_slippage():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeTelemetry:
        def __init__(self):
            self.lifecycle = []

        async def publish_position_lifecycle(self, ctx, symbol, event_type, payload):
            self.lifecycle.append((symbol, event_type, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(
        manager._emit_position_closed(
            symbol="BTC",
            side="buy",
            size=1.0,
            entry_price=100.4,
            exit_price=101.2,
            realized_pnl=0.7,
            realized_pnl_pct=0.7,
            fee_usd=0.1,
            close_order_id="close-1",
            closed_by="trading_signal",
            entry_reference_price=100.0,
            exit_reference_price=101.0,
        )
    )

    payload = telemetry.lifecycle[0][2]
    assert payload["entry_slippage_bps"] == pytest.approx(40.0)
    assert payload["exit_slippage_bps"] == pytest.approx(19.801980198019973)
    assert payload["realized_slippage_bps"] == pytest.approx(59.80198019801997)


def test_emit_position_closed_persists_trade_cost_breakdown():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeOrderStore:
        def __init__(self):
            self.trade_cost_rows = []

        async def record_trade_cost(self, **kwargs):
            self.trade_cost_rows.append(kwargs)

    manager = RealExecutionManager(exchange, positions, order_store=FakeOrderStore())

    asyncio.run(
        manager._emit_position_closed(
            symbol="BTCUSDT",
            side="long",
            size=1.5,
            entry_price=100.0,
            exit_price=101.0,
            realized_pnl=1.0,
            realized_pnl_pct=0.66,
            fee_usd=0.04,
            entry_fee_usd=0.03,
            total_fees_usd=0.07,
            close_order_id="close-42",
            profile_id="profile-a",
            entry_reference_price=99.9,
            exit_reference_price=100.9,
        )
    )
    assert len(manager.order_store.trade_cost_rows) == 1
    row = manager.order_store.trade_cost_rows[0]
    assert row["trade_id"] == "close-42"
    assert row["symbol"] == "BTCUSDT"
    assert row["total_cost_bps"] is not None
    assert row["entry_fee_usd"] == pytest.approx(0.03)
    assert row["exit_fee_usd"] == pytest.approx(0.04)


def test_emit_order_event_close_adds_cost_fields_and_infers_maker_policy():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeTelemetry:
        def __init__(self):
            self.events = []

        async def publish_order(self, ctx, symbol, payload):
            self.events.append((symbol, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(
        manager._emit_order_event(
            symbol="BTC",
            side="sell",
            size=1.0,
            status="filled",
            reason="position_close",
            reference_price=101.0,
            fill_price=100.5,
            fee_usd=0.03,
            entry_fee_usd=0.01,
            entry_price=100.0,
            exit_price=100.5,
            position_effect="close",
            entry_client_order_id="qg-root:m0",
            entry_order_type="limit",
            entry_post_only=True,
            filled_size=1.0,
            prediction_confidence=0.74,
            prediction_direction="up",
            prediction_source="heuristic_v2",
            entry_p_hat=0.64,
            entry_p_hat_source="prediction_p_hat",
            model_side="long",
            p_up=0.64,
            p_down=0.21,
            p_flat=0.15,
        )
    )

    payload = telemetry.events[0][1]
    assert payload["execution_policy"] == "maker_first"
    assert payload["execution_cohort"] == "maker_first"
    assert payload["entry_fee_bps"] == pytest.approx(1.0)
    assert payload["exit_fee_bps"] == pytest.approx((0.03 / 100.5) * 10000.0)
    assert payload["total_cost_bps"] is not None
    assert payload["prediction_source"] == "heuristic_v2"
    assert payload["model_side"] == "long"
    assert payload["p_up"] == pytest.approx(0.64)


def test_compute_fee_bps_preserves_rebate_sign():
    assert _compute_fee_bps(-0.01, 100.0, 1.0) == pytest.approx(-1.0)
    assert _compute_fee_bps(0.01, 100.0, 1.0) == pytest.approx(1.0)


def test_aggregate_execution_trades_preserves_signed_fees():
    trades = [
        {"amount": 1.0, "price": 100.0, "fee": {"cost": -0.02}, "order": "o1"},
        {"amount": 1.0, "price": 101.0, "fee": {"cost": 0.03}, "order": "o1"},
    ]
    summary = _aggregate_execution_trades(trades, order_id="o1", client_order_id=None)
    assert summary is not None
    assert summary["total_fees_usd"] == pytest.approx(0.01)


def test_emit_position_closed_uses_exit_price_for_exit_fee_bps():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeTelemetry:
        def __init__(self):
            self.lifecycle = []

        async def publish_position_lifecycle(self, ctx, symbol, event_type, payload):
            self.lifecycle.append((symbol, event_type, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(
        manager._emit_position_closed(
            symbol="BTCUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            exit_price=200.0,
            realized_pnl=99.8,
            realized_pnl_pct=99.8,
            fee_usd=0.2,
            entry_fee_usd=0.0,
            close_order_id="close-exit-fee-bps",
            closed_by="test",
            entry_reference_price=100.0,
            exit_reference_price=200.0,
        )
    )
    payload = telemetry.lifecycle[0][2]
    assert payload["exit_fee_bps"] == pytest.approx(10.0)


def test_emit_position_closed_defaults_excursion_fields_when_missing():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeTelemetry:
        def __init__(self):
            self.lifecycle = []

        async def publish_position_lifecycle(self, ctx, symbol, event_type, payload):
            self.lifecycle.append((symbol, event_type, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(
        manager._emit_position_closed(
            symbol="ETHUSDT",
            side="long",
            size=1.0,
            entry_price=100.0,
            exit_price=100.2,
            realized_pnl=0.2,
            realized_pnl_pct=0.2,
            fee_usd=0.0,
            close_order_id="close-excursion-defaults",
            closed_by="test",
        )
    )
    payload = telemetry.lifecycle[0][2]
    assert payload["mfe_pct"] == 0.0
    assert payload["mae_pct"] == 0.0
    assert payload["mae_abs_pct"] == 0.0
    assert payload["mfe_bps"] == 0.0
    assert payload["mae_bps"] == 0.0


def test_emit_order_event_close_defaults_excursion_fields_when_missing():
    exchange = FakeExchange()
    positions = FakePositions([])

    class FakeTelemetry:
        def __init__(self):
            self.events = []

        async def publish_order(self, ctx, symbol, payload):
            self.events.append((symbol, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(
        manager._emit_order_event(
            symbol="ETHUSDT",
            side="sell",
            size=1.0,
            status="filled",
            reason="position_close",
            reference_price=100.0,
            fill_price=100.0,
            fee_usd=0.0,
            position_effect="close",
            entry_price=100.0,
            exit_price=100.0,
            realized_pnl=0.0,
            realized_pnl_pct=0.0,
        )
    )
    payload = telemetry.events[0][1]
    assert payload["mfe_pct"] == 0.0
    assert payload["mae_pct"] == 0.0
    assert payload["mae_abs_pct"] == 0.0
    assert payload["mfe_bps"] == 0.0
    assert payload["mae_bps"] == 0.0


def test_positions_snapshot_includes_guard_fields():
    exchange = FakeExchange()
    positions = FakePositions(
        [
            PositionSnapshot(
                symbol="BTC",
                side="long",
                size=1.0,
                reference_price=101.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                opened_at=1000.0,
                prediction_confidence=0.66,
            )
        ]
    )

    class FakeTelemetry:
        def __init__(self):
            self.positions = []

        async def publish_positions(self, ctx, payload):
            self.positions.append(payload)

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(manager._emit_positions_snapshot())
    snapshot = telemetry.positions[0]["positions"][0]
    assert snapshot["entry_price"] == 100.0
    assert snapshot["stop_loss"] == 95.0
    assert snapshot["take_profit"] == 110.0
    assert snapshot["guard_status"] == "protected"
    assert snapshot["prediction_confidence"] == 0.66


def test_positions_snapshot_fills_prediction_confidence_from_snapshot():
    exchange = FakeExchange()
    positions = FakePositions(
        [
            PositionSnapshot(
                symbol="BTC",
                side="long",
                size=1.0,
                reference_price=101.0,
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                opened_at=1000.0,
                prediction_confidence=None,
            )
        ]
    )

    class FakeSnapshotReader:
        def __init__(self):
            self.calls = []

        async def read(self, key):
            self.calls.append(key)
            if key.endswith(":prediction:BTC:latest"):
                return {"symbol": "BTC", "confidence": 0.55}
            if key.endswith(":prediction:latest"):
                return {"symbol": "ETH", "confidence": 0.42}
            return None

        async def read_history(self, key, limit=100):
            return []

    class FakeTelemetry:
        def __init__(self):
            self.positions = []

        async def publish_positions(self, ctx, payload):
            self.positions.append(payload)

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    reader = FakeSnapshotReader()
    manager = RealExecutionManager(
        exchange,
        positions,
        telemetry=telemetry,
        telemetry_context=ctx,
        snapshot_reader=reader,
    )

    asyncio.run(manager._emit_positions_snapshot())
    snapshot = telemetry.positions[0]["positions"][0]
    assert snapshot["prediction_confidence"] == 0.55


def test_profile_feedback_on_close():
    exchange = FakeExchange()
    positions = FakePositions(
        [
            PositionSnapshot(
                symbol="BTC",
                side="long",
                size=1.0,
                entry_price=100.0,
                profile_id="profile-1",
            )
        ]
    )
    feedback_calls = []

    def record_feedback(profile_id, symbol, pnl):
        feedback_calls.append((profile_id, symbol, pnl))

    manager = RealExecutionManager(exchange, positions, profile_feedback=record_feedback)
    intent = ExecutionIntent(symbol="BTC", side="sell", size=1.0, profile_id="profile-1")
    status = OrderStatus(order_id="close-1", status="filled", fill_price=110.0, fee_usd=0.0)

    asyncio.run(manager.record_order_status(intent, status))

    assert feedback_calls
    assert feedback_calls[0][0] == "profile-1"


def test_risk_override_rejected_without_manager():
    exchange = FakeExchange()
    positions = FakePositions([])
    manager = RealExecutionManager(exchange, positions)

    result = asyncio.run(manager.apply_risk_override({"max_positions": 2}, 60))
    assert result.status == "rejected"


def test_execute_intent_wires_protection_fields():
    exchange = FakeExchange()
    positions = FakePositions([])
    manager = RealExecutionManager(exchange, positions)
    intent = ExecutionIntent(
        symbol="BTC",
        side="buy",
        size=1.0,
        stop_loss=95.0,
        take_profit=105.0,
        prediction_confidence=0.5,
    )

    async def run_once():
        await manager.execute_intent(intent)

    asyncio.run(run_once())
    assert exchange.opened[0][3] == 95.0
    assert exchange.opened[0][4] == 105.0
    assert positions.upserted[0].stop_loss == 95.0
    assert positions.upserted[0].take_profit == 105.0
    assert positions.upserted[0].prediction_confidence == 0.5


def test_record_order_status_preserves_protection_fields():
    exchange = FakeExchange()
    positions = FakePositions([])
    manager = RealExecutionManager(exchange, positions)
    intent = ExecutionIntent(
        symbol="BTC",
        side="buy",
        size=1.0,
        stop_loss=95.0,
        take_profit=105.0,
        expected_horizon_sec=30.0,
        time_to_work_sec=5.0,
        max_hold_sec=45.0,
        mfe_min_bps=12.0,
    )
    status = OrderStatus(order_id="open-1", status="filled", fill_price=100.0, fee_usd=0.01)

    asyncio.run(manager.record_order_status(intent, status))

    snapshot = positions.upserted[0]
    assert snapshot.stop_loss == 95.0
    assert snapshot.take_profit == 105.0
    assert snapshot.expected_horizon_sec == 30.0
    assert snapshot.time_to_work_sec == 5.0
    assert snapshot.max_hold_sec == 45.0
    assert snapshot.mfe_min_bps == 12.0


def test_execute_exit_intent_propagates_meta_reason_to_lifecycle():
    exchange = FakeExchange()
    positions = FakePositions(
        [
            PositionSnapshot(
                symbol="BTC",
                side="long",
                size=1.0,
                entry_price=100.0,
                opened_at=1000.0,
            )
        ]
    )

    class FakeTelemetry:
        def __init__(self):
            self.lifecycle = []

        async def publish_order(self, ctx, symbol, payload):
            return None

        async def publish_positions(self, ctx, payload):
            return None

        async def publish_position_lifecycle(self, ctx, symbol, event_type, payload):
            self.lifecycle.append((symbol, event_type, payload))

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    manager = RealExecutionManager(exchange, positions, telemetry=telemetry, telemetry_context=ctx)

    async def run_once():
        await manager.execute_intent(
            ExecutionIntent(
                symbol="BTC",
                side="sell",
                size=1.0,
                reduce_only=True,
                is_exit_signal=True,
                exit_reason="invalidation_exit: trend_reversal_short",
            )
        )

    asyncio.run(run_once())
    closed_payloads = [item[2] for item in telemetry.lifecycle if item[1] == "closed"]
    assert closed_payloads
    assert closed_payloads[0]["closed_by"] == "invalidation_exit: trend_reversal_short"


def test_failover_router_unavailable():
    exchange = FakeExchange()
    positions = FakePositions([])
    manager = RealExecutionManager(exchange, positions)

    result = asyncio.run(manager.execute_failover())
    assert result.status == "rejected"


def test_failover_success():
    exchange = FakeExchange()
    positions = FakePositions([])
    router = FakeRouter()
    manager = RealExecutionManager(exchange, positions, exchange_router=router)

    result = asyncio.run(manager.execute_failover())
    assert result.status == "executed"
