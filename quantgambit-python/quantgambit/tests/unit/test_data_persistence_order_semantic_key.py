from datetime import datetime, timezone

from quantgambit.workers.data_persistence_worker import _build_order_event_semantic_key


def test_close_order_semantic_key_ignores_reason_churn():
    ts = datetime.now(timezone.utc)
    base = {
        "order_id": "ord-123",
        "client_order_id": "coid-1",
        "status": "filled",
        "position_effect": "close",
        "filled_size": 0.1,
        "fill_price": 100.0,
        "fee_usd": 0.01,
    }
    payload_a = dict(base, reason="position_close")
    payload_b = dict(base, reason="invalidation_exit: orderflow_sell_pressure (imb=-0.80)")
    key_a = _build_order_event_semantic_key(payload_a, ts)
    key_b = _build_order_event_semantic_key(payload_b, ts)
    assert key_a == key_b
    assert key_a.startswith("ord_close|")


def test_non_close_order_semantic_key_keeps_reason_dimension():
    ts = datetime.now(timezone.utc)
    base = {
        "order_id": "ord-123",
        "client_order_id": "coid-1",
        "status": "filled",
        "position_effect": "open",
        "filled_size": 0.1,
        "fill_price": 100.0,
        "fee_usd": 0.01,
    }
    key_a = _build_order_event_semantic_key(dict(base, reason="execution_intent"), ts)
    key_b = _build_order_event_semantic_key(dict(base, reason="exchange_reconcile"), ts)
    assert key_a != key_b
    assert key_a.startswith("ord|")

