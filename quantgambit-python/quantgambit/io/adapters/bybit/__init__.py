"""
Bybit exchange adapter.

Provides:
- WebSocket client for real-time data (public + private)
- REST client for order management
- Book synchronization with sequence validation
- Status and type mapping to canonical formats
"""

from quantgambit.io.adapters.bybit.book_sync import BybitBookSync
from quantgambit.io.adapters.bybit.mapping import (
    map_order_status,
    map_order_side,
    map_order_type,
    map_time_in_force,
    is_terminal_status,
    is_fill_status,
    get_error_message,
    is_position_zero_error,
    is_insufficient_balance_error,
    BYBIT_ORDER_STATUS_MAP,
    BYBIT_ERROR_CODES,
)
from quantgambit.io.adapters.bybit.ws_client import (
    BybitWSClient,
    BybitWSConfig,
    BybitChannel,
)
from quantgambit.io.adapters.bybit.rest_client import (
    BybitRESTClient,
    BybitRESTConfig,
    BybitRESTError,
)

__all__ = [
    # Book sync
    "BybitBookSync",
    # Mapping
    "map_order_status",
    "map_order_side",
    "map_order_type",
    "map_time_in_force",
    "is_terminal_status",
    "is_fill_status",
    "get_error_message",
    "is_position_zero_error",
    "is_insufficient_balance_error",
    "BYBIT_ORDER_STATUS_MAP",
    "BYBIT_ERROR_CODES",
    # WebSocket
    "BybitWSClient",
    "BybitWSConfig",
    "BybitChannel",
    # REST
    "BybitRESTClient",
    "BybitRESTConfig",
    "BybitRESTError",
]
