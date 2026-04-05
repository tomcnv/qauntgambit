"""Idempotency helpers for execution intents."""

from __future__ import annotations

import hashlib


def build_client_order_id(
    bot_id: str,
    event_id: str | None,
    symbol: str | None,
    side: str | None,
    size: float | None,
) -> str:
    base = f"{bot_id}:{event_id}:{symbol}:{side}:{size}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
    return f"qg-{digest[:20]}"
