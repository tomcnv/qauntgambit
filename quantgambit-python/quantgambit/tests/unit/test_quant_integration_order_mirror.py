from quantgambit.runtime.quant_integration import OrderStoreAdapter


class _FakeStore:
    def __init__(self):
        self.records = []
        self.intents = []

    async def record(self, **kwargs):
        self.records.append(kwargs)

    async def record_intent(self, **kwargs):
        self.intents.append(kwargs)


def test_reconciliation_terminal_status_mirrors_into_intents():
    adapter = OrderStoreAdapter(_FakeStore())

    adapter._submit_record(
        symbol="BTCUSDT",
        side="sell",
        size=1.0,
        status="canceled",
        order_id="o1",
        client_order_id="cid-1",
        reason="reconciliation_heal",
        source="reconciliation",
        event_type="reconciliation_heal",
    )

    assert len(adapter._store.records) == 1
    assert len(adapter._store.intents) == 1
    assert adapter._store.intents[0]["client_order_id"] == "cid-1"
    assert adapter._store.intents[0]["status"] == "canceled"
    assert adapter._store.intents[0]["last_error"] == "reconciliation_heal"


def test_reconciliation_pending_status_does_not_mirror_into_intents():
    adapter = OrderStoreAdapter(_FakeStore())

    adapter._submit_record(
        symbol="BTCUSDT",
        side="buy",
        size=1.0,
        status="pending",
        order_id=None,
        client_order_id="cid-2",
        reason="reconciliation_add",
        source="reconciliation",
        event_type="reconciliation_add",
    )

    assert len(adapter._store.records) == 1
    assert adapter._store.intents == []
