"""Telemetry schema helpers for consistent payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional


def decision_payload(
    result: str,
    latency_ms: float,
    rejection_reason: Optional[str] = None,
    expected_bps: Optional[float] = None,
    expected_fee_usd: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "result": result,
        "latency_ms": latency_ms,
        "rejection_reason": rejection_reason,
        "expected_bps": expected_bps,
        "expected_fee_usd": expected_fee_usd,
    }


def order_payload(
    side: str,
    size: float,
    status: str,
    reason: str,
    slippage_bps: Optional[float],
    fee_usd: Optional[float],
    entry_fee_usd: Optional[float] = None,
    total_fees_usd: Optional[float] = None,
    fill_price: Optional[float] = None,
    order_id: Optional[str] = None,
    client_order_id: Optional[str] = None,
    position_effect: Optional[str] = None,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    realized_pnl: Optional[float] = None,
    realized_pnl_pct: Optional[float] = None,
    gross_pnl: Optional[float] = None,
    net_pnl: Optional[float] = None,
    filled_size: Optional[float] = None,
    entry_timestamp: Optional[float] = None,
    exit_timestamp: Optional[float] = None,
    hold_time_sec: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "side": side,
        "size": size,
        "status": status,
        "reason": reason,
        "slippage_bps": slippage_bps,
        "fee_usd": fee_usd,
        "entry_fee_usd": entry_fee_usd,
        "total_fees_usd": total_fees_usd,
        "fill_price": fill_price,
        "order_id": order_id,
        "client_order_id": client_order_id,
        "position_effect": position_effect,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "filled_size": filled_size,
        "entry_timestamp": entry_timestamp,
        "exit_timestamp": exit_timestamp,
        "hold_time_sec": hold_time_sec,
    }


def prediction_payload(score: float, label: Optional[str] = None) -> Dict[str, Any]:
    return {
        "score": score,
        "label": label,
    }
