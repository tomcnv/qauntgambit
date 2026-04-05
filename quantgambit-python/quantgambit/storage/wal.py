"""Write-ahead log scaffolding for deterministic replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class WalEntry:
    sequence_id: int
    event_type: str
    timestamp: str
    payload: Dict[str, Any]
    symbol: Optional[str] = None
    exchange: Optional[str] = None


class WalWriter:
    def __init__(self, storage_backend):
        self.storage_backend = storage_backend

    async def append(self, entry: WalEntry) -> None:
        await self.storage_backend.write(entry)

