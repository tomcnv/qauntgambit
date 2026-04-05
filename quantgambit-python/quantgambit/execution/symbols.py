"""Exchange symbol normalization helpers."""

from __future__ import annotations

from typing import Optional


def canonical_symbol(symbol: Optional[str]) -> Optional[str]:
    if not symbol:
        return symbol
    raw = str(symbol).strip().upper()
    if not raw:
        return raw
    if ":" in raw:
        raw = raw.split(":", 1)[0]
    cleaned = raw.replace("/", "-")
    parts = [part for part in cleaned.split("-") if part]
    if not parts:
        return cleaned
    filtered = [part for part in parts if part not in {"SWAP", "PERP", "PERPETUAL", "FUTURES"}]
    compact = "".join(filtered) if filtered else "".join(parts)
    return compact.replace("USDTUSDT", "USDT")


def to_storage_symbol(symbol: Optional[str]) -> Optional[str]:
    return canonical_symbol(symbol)


def normalize_exchange_symbol(exchange: str, symbol: Optional[str], market_type: Optional[str] = None) -> Optional[str]:
    if not symbol:
        return symbol
    raw = str(symbol).strip()
    if not raw:
        return raw
    normalized = (exchange or "").lower()
    if normalized == "okx":
        if ":" in raw:
            raw = raw.split(":", 1)[0]
        raw = raw.replace("/", "-")
        if (market_type or "").lower() == "spot":
            return raw.upper()
        if raw.endswith("-SWAP"):
            return raw.upper()
        if "-" in raw:
            return f"{raw.upper()}-SWAP"
        return raw.upper()
    if normalized in {"bybit", "binance"}:
        return canonical_symbol(raw)
    return canonical_symbol(raw)


def to_ccxt_market_symbol(exchange: str, symbol: Optional[str], market_type: Optional[str] = None) -> Optional[str]:
    if not symbol:
        return symbol
    raw = str(symbol).strip()
    if not raw:
        return raw
    normalized = (exchange or "").lower()
    market_kind = (market_type or "perp").lower()
    if normalized == "okx":
        cleaned = raw.upper()
        if cleaned.endswith("-SWAP"):
            base, quote, _ = cleaned.split("-", 2)
            return f"{base}/{quote}:USDT"
        if "-" in cleaned:
            base, quote = cleaned.split("-", 1)
            return f"{base}/{quote}" if market_kind == "spot" else f"{base}/{quote}:USDT"
        return cleaned
    if normalized in {"bybit", "binance"}:
        cleaned = str(canonical_symbol(raw) or "").upper()
        if "/" in cleaned:
            return cleaned if market_kind == "spot" else f"{cleaned}:USDT"
        compact = cleaned.replace("-", "").replace("/", "")
        if len(compact) >= 6:
            base = compact[:-4]
            quote = compact[-4:]
            return f"{base}/{quote}" if market_kind == "spot" else f"{base}/{quote}:USDT"
        return compact
    return raw
