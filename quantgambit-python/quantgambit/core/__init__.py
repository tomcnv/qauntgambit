"""
QuantGambit Core - Pure deterministic logic.

This package contains ONLY pure, deterministic logic with no network,
Redis, WebSocket, or filesystem dependencies. All I/O is injected.

Key modules:
- clock: Time abstraction for deterministic testing/replay
- events: Canonical EventEnvelope model
- ids: Intent ID and Client Order ID generation
- lifecycle: Order lifecycle state machine
- book/: Order book types, sync, and guardian
- decision/: Decision pipeline interfaces
- execution/: Execution intents and routing
- risk/: Kill-switch and risk controls
- config/: Versioned configuration bundles
"""

from quantgambit.core.clock import Clock, WallClock, SimClock, get_clock, set_clock

__all__ = [
    "Clock",
    "WallClock",
    "SimClock",
    "get_clock",
    "set_clock",
]
