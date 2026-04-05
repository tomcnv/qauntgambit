"""
Venue capability and semantics matrix.

Defines venue-specific behavior, capabilities, and guardian parameters
for each supported exchange.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class OrderCapability(str, Enum):
    """Order capabilities supported by venue."""
    
    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"
    BRACKET = "bracket"  # OCO / SL+TP combo
    TRAILING_STOP = "trailing_stop"
    REDUCE_ONLY = "reduce_only"
    CANCEL_ALL = "cancel_all"
    BATCH_CANCEL = "batch_cancel"


class BookCapability(str, Enum):
    """Order book capabilities."""
    
    SEQUENCE_ID = "sequence_id"  # Provides sequence/update ID
    CHECKSUM = "checksum"  # Provides book checksum
    DELTA_STREAM = "delta_stream"  # Incremental updates
    SNAPSHOT_ON_CONNECT = "snapshot_on_connect"  # Sends snapshot first
    DEPTH_50 = "depth_50"
    DEPTH_200 = "depth_200"
    DEPTH_500 = "depth_500"


class WSCapability(str, Enum):
    """WebSocket capabilities."""
    
    PUBLIC_BOOK = "public_book"
    PUBLIC_TRADES = "public_trades"
    PUBLIC_TICKER = "public_ticker"
    PRIVATE_ORDERS = "private_orders"
    PRIVATE_FILLS = "private_fills"
    PRIVATE_POSITIONS = "private_positions"
    PRIVATE_WALLET = "private_wallet"


@dataclass
class GuardianParams:
    """Parameters for BookGuardian per venue."""
    
    # Sequence validation
    max_sequence_gap: int = 10
    sequence_reset_threshold: int = 1000
    
    # Staleness
    staleness_threshold_s: float = 1.0
    resync_interval_s: float = 60.0
    
    # Checksum (if supported)
    verify_checksum: bool = True
    checksum_failure_action: str = "resync"  # "resync" or "ignore"
    
    # Book validation
    min_depth_required: int = 1
    crossed_book_action: str = "resync"  # "resync" or "reject"


@dataclass
class ExecutionSemantics:
    """Execution semantics for venue."""
    
    # Client order ID
    client_order_id_required: bool = True
    client_order_id_max_len: int = 36
    client_order_id_allowed_chars: str = "alphanumeric_underscore"
    client_order_id_reuse_allowed: bool = False
    
    # Order lifecycle
    ack_contains_exchange_id: bool = True
    partial_fills_emit_events: bool = True
    fill_contains_fee: bool = True
    
    # Reduce-only semantics
    reduce_only_strict: bool = True  # Rejects if no position
    
    # Rate limits
    orders_per_second: int = 10
    orders_per_minute: int = 300
    
    # Timeouts
    expected_ack_latency_ms: float = 100.0
    expected_fill_latency_ms: float = 50.0


@dataclass
class VenueProfile:
    """Complete profile for a trading venue."""
    
    venue_id: str
    name: str
    
    # Capabilities
    order_capabilities: List[OrderCapability] = field(default_factory=list)
    book_capabilities: List[BookCapability] = field(default_factory=list)
    ws_capabilities: List[WSCapability] = field(default_factory=list)
    
    # Parameters
    guardian_params: GuardianParams = field(default_factory=GuardianParams)
    execution_semantics: ExecutionSemantics = field(default_factory=ExecutionSemantics)
    
    # Endpoints
    rest_base_url: str = ""
    public_ws_url: str = ""
    private_ws_url: str = ""
    
    # Symbol format
    symbol_format: str = "BASE_QUOTE"  # e.g., "BTCUSDT", "BTC-USDT", "BTC_USDT"
    
    def has_capability(self, cap: OrderCapability) -> bool:
        """Check if venue has order capability."""
        return cap in self.order_capabilities
    
    def has_book_capability(self, cap: BookCapability) -> bool:
        """Check if venue has book capability."""
        return cap in self.book_capabilities
    
    def has_ws_capability(self, cap: WSCapability) -> bool:
        """Check if venue has WS capability."""
        return cap in self.ws_capabilities


# Venue profiles

BYBIT_LINEAR = VenueProfile(
    venue_id="bybit_linear",
    name="Bybit Linear Perpetual",
    order_capabilities=[
        OrderCapability.MARKET,
        OrderCapability.LIMIT,
        OrderCapability.POST_ONLY,
        OrderCapability.STOP_MARKET,
        OrderCapability.STOP_LIMIT,
        OrderCapability.BRACKET,  # Via position TP/SL
        OrderCapability.TRAILING_STOP,
        OrderCapability.REDUCE_ONLY,
        OrderCapability.CANCEL_ALL,
    ],
    book_capabilities=[
        BookCapability.SEQUENCE_ID,
        BookCapability.DELTA_STREAM,
        BookCapability.SNAPSHOT_ON_CONNECT,
        BookCapability.DEPTH_50,
        BookCapability.DEPTH_200,
        BookCapability.DEPTH_500,
    ],
    ws_capabilities=[
        WSCapability.PUBLIC_BOOK,
        WSCapability.PUBLIC_TRADES,
        WSCapability.PUBLIC_TICKER,
        WSCapability.PRIVATE_ORDERS,
        WSCapability.PRIVATE_FILLS,
        WSCapability.PRIVATE_POSITIONS,
        WSCapability.PRIVATE_WALLET,
    ],
    guardian_params=GuardianParams(
        max_sequence_gap=10,
        staleness_threshold_s=1.0,
        resync_interval_s=60.0,
        verify_checksum=False,  # Bybit doesn't provide checksum
    ),
    execution_semantics=ExecutionSemantics(
        client_order_id_required=False,
        client_order_id_max_len=36,
        orders_per_second=10,
        orders_per_minute=600,
        expected_ack_latency_ms=50.0,
    ),
    rest_base_url="https://api.bybit.com",
    public_ws_url="wss://stream.bybit.com/v5/public/linear",
    private_ws_url="wss://stream.bybit.com/v5/private",
    symbol_format="BASQUOTE",  # e.g., BTCUSDT
)

OKX_SWAP = VenueProfile(
    venue_id="okx_swap",
    name="OKX Perpetual Swap",
    order_capabilities=[
        OrderCapability.MARKET,
        OrderCapability.LIMIT,
        OrderCapability.POST_ONLY,
        OrderCapability.STOP_MARKET,
        OrderCapability.STOP_LIMIT,
        OrderCapability.BRACKET,  # Via algo orders
        OrderCapability.REDUCE_ONLY,
        OrderCapability.CANCEL_ALL,
        OrderCapability.BATCH_CANCEL,
    ],
    book_capabilities=[
        BookCapability.SEQUENCE_ID,
        BookCapability.CHECKSUM,
        BookCapability.DELTA_STREAM,
        BookCapability.DEPTH_50,
        BookCapability.DEPTH_200,
    ],
    ws_capabilities=[
        WSCapability.PUBLIC_BOOK,
        WSCapability.PUBLIC_TRADES,
        WSCapability.PUBLIC_TICKER,
        WSCapability.PRIVATE_ORDERS,
        WSCapability.PRIVATE_FILLS,
        WSCapability.PRIVATE_POSITIONS,
        WSCapability.PRIVATE_WALLET,
    ],
    guardian_params=GuardianParams(
        max_sequence_gap=5,
        staleness_threshold_s=1.0,
        resync_interval_s=30.0,
        verify_checksum=True,
        checksum_failure_action="resync",
    ),
    execution_semantics=ExecutionSemantics(
        client_order_id_required=False,
        client_order_id_max_len=32,
        orders_per_second=20,
        orders_per_minute=300,
        expected_ack_latency_ms=30.0,
    ),
    rest_base_url="https://www.okx.com",
    public_ws_url="wss://ws.okx.com:8443/ws/v5/public",
    private_ws_url="wss://ws.okx.com:8443/ws/v5/private",
    symbol_format="BASE-QUOTE-SWAP",  # e.g., BTC-USDT-SWAP
)

BINANCE_FUTURES = VenueProfile(
    venue_id="binance_futures",
    name="Binance USDT-M Futures",
    order_capabilities=[
        OrderCapability.MARKET,
        OrderCapability.LIMIT,
        OrderCapability.POST_ONLY,
        OrderCapability.STOP_MARKET,
        OrderCapability.STOP_LIMIT,
        OrderCapability.TRAILING_STOP,
        OrderCapability.REDUCE_ONLY,
        OrderCapability.CANCEL_ALL,
        OrderCapability.BATCH_CANCEL,
    ],
    book_capabilities=[
        BookCapability.SEQUENCE_ID,
        BookCapability.DELTA_STREAM,
        BookCapability.SNAPSHOT_ON_CONNECT,
        BookCapability.DEPTH_50,
        BookCapability.DEPTH_200,
        BookCapability.DEPTH_500,
    ],
    ws_capabilities=[
        WSCapability.PUBLIC_BOOK,
        WSCapability.PUBLIC_TRADES,
        WSCapability.PUBLIC_TICKER,
        WSCapability.PRIVATE_ORDERS,
        WSCapability.PRIVATE_FILLS,
        WSCapability.PRIVATE_POSITIONS,
        WSCapability.PRIVATE_WALLET,
    ],
    guardian_params=GuardianParams(
        max_sequence_gap=100,  # Binance has larger gaps
        staleness_threshold_s=1.0,
        resync_interval_s=60.0,
        verify_checksum=False,
    ),
    execution_semantics=ExecutionSemantics(
        client_order_id_required=False,
        client_order_id_max_len=36,
        orders_per_second=10,
        orders_per_minute=1200,
        expected_ack_latency_ms=50.0,
    ),
    rest_base_url="https://fapi.binance.com",
    public_ws_url="wss://fstream.binance.com/ws",
    private_ws_url="wss://fstream.binance.com/ws",
    symbol_format="BASQUOTE",  # e.g., BTCUSDT
)

# Registry of all venues
VENUE_PROFILES: Dict[str, VenueProfile] = {
    "bybit_linear": BYBIT_LINEAR,
    "okx_swap": OKX_SWAP,
    "binance_futures": BINANCE_FUTURES,
}


def get_venue_profile(venue_id: str) -> Optional[VenueProfile]:
    """Get venue profile by ID."""
    return VENUE_PROFILES.get(venue_id)


def get_guardian_params(venue_id: str) -> GuardianParams:
    """Get guardian parameters for venue."""
    profile = VENUE_PROFILES.get(venue_id)
    if profile:
        return profile.guardian_params
    return GuardianParams()  # Default params


def normalize_symbol(symbol: str, from_venue: str, to_venue: str) -> str:
    """
    Normalize symbol between venue formats.
    
    Args:
        symbol: Symbol in source format
        from_venue: Source venue ID
        to_venue: Target venue ID
        
    Returns:
        Symbol in target format
    """
    # Extract base and quote
    from_profile = VENUE_PROFILES.get(from_venue)
    to_profile = VENUE_PROFILES.get(to_venue)
    
    if not from_profile or not to_profile:
        return symbol
    
    # Parse from format
    base, quote = "", ""
    if from_profile.symbol_format == "BASQUOTE":
        # Assume USDT pairs for now
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            quote = "USDT"
    elif from_profile.symbol_format == "BASE-QUOTE-SWAP":
        parts = symbol.split("-")
        if len(parts) >= 2:
            base, quote = parts[0], parts[1]
    
    if not base or not quote:
        return symbol
    
    # Format for target
    if to_profile.symbol_format == "BASQUOTE":
        return f"{base}{quote}"
    elif to_profile.symbol_format == "BASE-QUOTE-SWAP":
        return f"{base}-{quote}-SWAP"
    
    return symbol
