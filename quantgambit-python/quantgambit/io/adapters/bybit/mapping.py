"""
Bybit status and type mapping to canonical types.

Maps Bybit-specific order statuses, sides, and types to
our canonical OrderState and other enums.
"""

from typing import Optional

from quantgambit.core.lifecycle import OrderState


# Bybit order status mapping
# https://bybit-exchange.github.io/docs/v5/enum#orderstatus
BYBIT_ORDER_STATUS_MAP = {
    "Created": OrderState.NEW,
    "New": OrderState.ACKED,
    "Rejected": OrderState.REJECTED,
    "PartiallyFilled": OrderState.PARTIAL,
    "PartiallyFilledCanceled": OrderState.CANCELED,  # Partial fill then cancel
    "Filled": OrderState.FILLED,
    "Cancelled": OrderState.CANCELED,
    "Untriggered": OrderState.ACKED,  # Conditional order waiting
    "Triggered": OrderState.ACKED,  # Conditional order triggered
    "Deactivated": OrderState.CANCELED,  # Conditional order deactivated
    "Active": OrderState.ACKED,  # Active order
}


def map_order_status(bybit_status: str) -> Optional[OrderState]:
    """
    Map Bybit order status to canonical OrderState.
    
    Args:
        bybit_status: Bybit order status string
        
    Returns:
        Canonical OrderState, or None if unknown
    """
    return BYBIT_ORDER_STATUS_MAP.get(bybit_status)


def map_order_side(bybit_side: str) -> str:
    """
    Map Bybit order side to canonical side.
    
    Args:
        bybit_side: Bybit side ("Buy" or "Sell")
        
    Returns:
        Canonical side ("buy" or "sell")
    """
    return bybit_side.lower()


def map_order_type(bybit_type: str) -> str:
    """
    Map Bybit order type to canonical type.
    
    Args:
        bybit_type: Bybit order type
        
    Returns:
        Canonical order type
    """
    type_map = {
        "Market": "market",
        "Limit": "limit",
        "StopMarket": "stop_market",
        "StopLimit": "stop_limit",
        "TakeProfit": "take_profit",
        "StopLoss": "stop_loss",
        "TrailingStop": "trailing_stop",
    }
    return type_map.get(bybit_type, bybit_type.lower())


def map_time_in_force(bybit_tif: str) -> str:
    """
    Map Bybit time-in-force to canonical.
    
    Args:
        bybit_tif: Bybit TIF
        
    Returns:
        Canonical TIF
    """
    tif_map = {
        "GTC": "gtc",
        "IOC": "ioc",
        "FOK": "fok",
        "PostOnly": "post_only",
    }
    return tif_map.get(bybit_tif, bybit_tif.lower())


def is_terminal_status(bybit_status: str) -> bool:
    """
    Check if Bybit status is terminal.
    
    Args:
        bybit_status: Bybit order status
        
    Returns:
        True if order is in terminal state
    """
    terminal_statuses = {
        "Rejected",
        "Filled",
        "Cancelled",
        "PartiallyFilledCanceled",
        "Deactivated",
    }
    return bybit_status in terminal_statuses


def is_fill_status(bybit_status: str) -> bool:
    """
    Check if Bybit status indicates a fill.
    
    Args:
        bybit_status: Bybit order status
        
    Returns:
        True if order has fills
    """
    fill_statuses = {
        "PartiallyFilled",
        "PartiallyFilledCanceled",
        "Filled",
    }
    return bybit_status in fill_statuses


# Bybit error code mapping
BYBIT_ERROR_CODES = {
    10001: "Parameter error",
    10002: "Invalid request",
    10003: "Invalid api key",
    10004: "Invalid sign",
    10005: "Permission denied",
    10006: "Too many requests",
    10010: "Unmatched IP",
    10016: "Server error",
    10017: "API not found",
    10018: "Invalid access token",
    110001: "Order does not exist",
    110003: "Order price out of range",
    110004: "Insufficient wallet balance",
    110005: "Position mode error",
    110006: "Insufficient available balance",
    110007: "Order quantity exceeds limit",
    110008: "Order price exceeds limit",
    110009: "Order has been filled",
    110010: "Order has been cancelled",
    110011: "Order is being processed",
    110012: "Order does not exist",
    110013: "Order quantity is too small",
    110014: "Order quantity is too large",
    110015: "Order price is too low",
    110016: "Order price is too high",
    110017: "Current position is zero",  # Important for exit handling
    110018: "Reduce-only order rejected",
    110019: "Position side error",
    110020: "Position does not exist",
    110021: "Position is being liquidated",
    110022: "Position is being settled",
    110023: "Position mode is not supported",
    110024: "Leverage not modified",
    110025: "Cross margin is not supported",
    110026: "Position limit exceeded",
    110027: "Position is in one-way mode",
    110028: "Position is in hedge mode",
    110043: "Set margin mode failed",
    110044: "Available margin not enough",
    110045: "Wallet balance not enough",
    110046: "Insufficient available balance for order cost",
    110047: "Risk limit exceeded",
    110048: "No active position",
    110049: "Insufficient available balance",
    110050: "Any order in progress",
    110051: "Due to risk limit, cannot set leverage",
    110052: "Due to risk limit, cannot set margin mode",
    110053: "Set leverage not modified",
    110054: "Isolated margin cannot be adjusted",
    110055: "Position mode is not modified",
    110056: "Available balance not enough",
    110057: "Reduce-only order is not allowed",
    110058: "Reduce-only order rejected",
    110059: "Reduce-only order rejected",
    110060: "Reduce-only order rejected",
    110061: "Reduce-only order rejected",
    110062: "Price out of range",
    110063: "Leverage not modified",
    110064: "Cross margin mode not allowed",
    110065: "Position idx error",
    110066: "Position idx not match",
    110067: "Reduce-only order rejected",
    110068: "Close order rejected",
    110069: "Close order rejected",
    110070: "Close order rejected",
}


def get_error_message(error_code: int) -> str:
    """
    Get human-readable error message for Bybit error code.
    
    Args:
        error_code: Bybit error code
        
    Returns:
        Error message
    """
    return BYBIT_ERROR_CODES.get(error_code, f"Unknown error: {error_code}")


def is_position_zero_error(error_code: int) -> bool:
    """
    Check if error indicates position is already zero.
    
    This is important for handling stale position state.
    
    Args:
        error_code: Bybit error code
        
    Returns:
        True if error indicates no position
    """
    return error_code in {110017, 110048, 110020}


def is_insufficient_balance_error(error_code: int) -> bool:
    """
    Check if error indicates insufficient balance.
    
    Args:
        error_code: Bybit error code
        
    Returns:
        True if error is balance-related
    """
    return error_code in {110004, 110006, 110044, 110045, 110046, 110049, 110056}
