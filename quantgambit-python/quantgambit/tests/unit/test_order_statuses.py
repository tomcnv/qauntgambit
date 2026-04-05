from quantgambit.execution.order_statuses import normalize_order_status


def test_normalize_order_status_exchange_variants():
    cases = {
        "NEW": "pending",
        "Created": "pending",
        "Accepted": "pending",
        "LIVE": "open",
        "Untriggered": "open",
        "Triggered": "open",
        "PENDING_CANCEL": "open",
        "PartiallyFilled": "partially_filled",
        "PARTIALLY_FILLED": "partially_filled",
        "PARTIALLY_FILLED_CANCELED": "canceled",
        "FILLED": "filled",
        "Done": "filled",
        "Canceled": "canceled",
        "Cancelled": "canceled",
        "Deactivated": "canceled",
        "Expired": "expired",
        "EXPIRED_IN_MATCH": "expired",
        "Rejected": "rejected",
        "Failed": "rejected",
    }
    for raw, expected in cases.items():
        assert normalize_order_status(raw) == expected
