"""
QuantGambit I/O - External system interfaces.

This package contains all code that interacts with external systems:
- Redis (side-channel publishing, streams)
- WebSockets (exchange feeds)
- REST APIs (exchange APIs)
- Timescale (telemetry storage)
- Filesystem (recording, replay)

Key modules:
- sidechannel: Bounded async publisher for non-critical events
- recorder: Event recording for replay
- adapters/: Exchange-specific adapters (Bybit, OKX, Binance)
"""

from quantgambit.io.sidechannel import (
    SideChannelConfig,
    SideChannelPublisher,
    DropPolicy,
)

__all__ = [
    "SideChannelConfig",
    "SideChannelPublisher",
    "DropPolicy",
]
