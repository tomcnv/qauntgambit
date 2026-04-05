"""Canonical order status normalization."""

from __future__ import annotations

from typing import Optional


_PENDING_STATUSES = {"pending", "accepted", "new", "created"}
_OPEN_STATUSES = {
    "open",
    "live",
    "active",
    "triggered",
    "untriggered",
    "pending_cancel",
}
_PARTIAL_STATUSES = {
    "partially_filled",
    "partiallyfilled",
    "partial",
    "partial_fill",
}
_FILLED_STATUSES = {"filled", "complete", "done", "closed"}
_CANCELED_STATUSES = {
    "canceled",
    "cancelled",
    "canceled_by_user",
    "canceling",
    "canceled_by_system",
    "deactivated",
    "expired_canceled",
    "partially_filled_canceled",
    "partiallyfilledcanceled",
}
_REJECTED_STATUSES = {"rejected", "failed", "error"}
_EXPIRED_STATUSES = {"expired", "expired_in_match"}


def normalize_order_status(status: Optional[str]) -> str:
    if not status:
        return "unknown"
    normalized = str(status).strip().lower().replace(" ", "_")
    if normalized in _FILLED_STATUSES:
        return "filled"
    if normalized in _PARTIAL_STATUSES:
        return "partially_filled"
    if normalized in _PENDING_STATUSES:
        return "pending"
    if normalized in _OPEN_STATUSES:
        return "open"
    if normalized in _CANCELED_STATUSES:
        return "canceled"
    if normalized in _REJECTED_STATUSES:
        return "rejected"
    if normalized in _EXPIRED_STATUSES:
        return "expired"
    return normalized


def is_open_status(status: Optional[str]) -> bool:
    return normalize_order_status(status) in {"pending", "open", "partially_filled"}


def is_terminal_status(status: Optional[str]) -> bool:
    return normalize_order_status(status) in {"filled", "canceled", "rejected", "expired"}


def order_status_rank(status: Optional[str]) -> int:
    normalized = normalize_order_status(status)
    ranks = {
        "unknown": 0,
        "pending": 1,
        "open": 2,
        "partially_filled": 3,
        "filled": 4,
        "canceled": 4,
        "rejected": 4,
        "expired": 4,
    }
    return ranks.get(normalized, 0)


def is_valid_transition(previous: Optional[str], next_status: Optional[str]) -> bool:
    prev = normalize_order_status(previous)
    nxt = normalize_order_status(next_status)
    if prev == "unknown":
        return True
    if prev == nxt:
        return True
    if nxt == "unknown":
        return False
    if is_terminal_status(prev):
        return False
    if is_terminal_status(nxt):
        return True
    return order_status_rank(nxt) >= order_status_rank(prev)
