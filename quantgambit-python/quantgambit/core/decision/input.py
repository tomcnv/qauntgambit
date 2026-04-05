"""
DecisionInput construction utilities.

Provides pure builders for constructing DecisionInput objects
from various data sources (market data, state managers, etc.).
"""

from typing import Any, Dict, List, Optional

from quantgambit.core.clock import Clock
from quantgambit.core.book.types import OrderBook
from quantgambit.core.decision.interfaces import (
    DecisionInput,
    Position,
    BookSnapshot,
)


class DecisionInputBuilder:
    """
    Builder for constructing DecisionInput objects.
    
    Provides a fluent interface for building inputs from various sources.
    All methods are pure (no side effects).
    
    Usage:
        builder = DecisionInputBuilder(clock)
        
        decision_input = (
            builder
            .with_symbol("BTCUSDT")
            .with_book(order_book)
            .with_position(position)
            .with_account(equity=10000, margin=5000)
            .build()
        )
    """
    
    def __init__(self, clock: Clock):
        """Initialize builder with clock."""
        self._clock = clock
        self._symbol: Optional[str] = None
        self._book: Optional[BookSnapshot] = None
        self._recent_trades: List[Dict[str, Any]] = []
        self._position: Optional[Position] = None
        self._equity: float = 0.0
        self._margin: float = 0.0
        self._open_orders: int = 0
        self._pending_intents: int = 0
        self._max_position_size: float = 0.0
        self._max_position_value: float = 0.0
        self._max_leverage: float = 1.0
        self._config_bundle_id: Optional[str] = None
    
    def with_symbol(self, symbol: str) -> "DecisionInputBuilder":
        """Set the trading symbol."""
        self._symbol = symbol
        return self
    
    def with_book(
        self,
        book: OrderBook,
        is_quoteable: bool = True,
    ) -> "DecisionInputBuilder":
        """Set book data from OrderBook."""
        self._book = BookSnapshot.from_order_book(book, is_quoteable)
        return self
    
    def with_book_snapshot(self, snapshot: BookSnapshot) -> "DecisionInputBuilder":
        """Set book data from BookSnapshot."""
        self._book = snapshot
        return self
    
    def with_raw_book(
        self,
        bid: Optional[float],
        ask: Optional[float],
        sequence_id: Optional[int] = None,
        is_quoteable: bool = True,
    ) -> "DecisionInputBuilder":
        """Set book data from raw values."""
        mid = (bid + ask) / 2 if bid and ask else None
        spread_bps = None
        if bid and ask and mid and mid > 0:
            spread_bps = ((ask - bid) / mid) * 10000
        
        self._book = BookSnapshot(
            best_bid=bid,
            best_ask=ask,
            mid_price=mid,
            spread_bps=spread_bps,
            sequence_id=sequence_id,
            is_quoteable=is_quoteable,
            timestamp=self._clock.now_mono(),
        )
        return self
    
    def with_trades(self, trades: List[Dict[str, Any]]) -> "DecisionInputBuilder":
        """Set recent trades."""
        self._recent_trades = trades
        return self
    
    def with_position(self, position: Optional[Position]) -> "DecisionInputBuilder":
        """Set current position."""
        self._position = position
        return self
    
    def with_raw_position(
        self,
        size: float,
        entry_price: Optional[float] = None,
        unrealized_pnl: float = 0.0,
    ) -> "DecisionInputBuilder":
        """Set position from raw values."""
        if abs(size) > 0.0001:
            self._position = Position(
                size=size,
                entry_price=entry_price,
                unrealized_pnl=unrealized_pnl,
            )
        else:
            self._position = None
        return self
    
    def with_account(
        self,
        equity: float,
        margin: float = 0.0,
    ) -> "DecisionInputBuilder":
        """Set account state."""
        self._equity = equity
        self._margin = margin if margin > 0 else equity
        return self
    
    def with_order_counts(
        self,
        open_orders: int = 0,
        pending_intents: int = 0,
    ) -> "DecisionInputBuilder":
        """Set order counts."""
        self._open_orders = open_orders
        self._pending_intents = pending_intents
        return self
    
    def with_risk_limits(
        self,
        max_position_size: float = 0.0,
        max_position_value: float = 0.0,
        max_leverage: float = 1.0,
    ) -> "DecisionInputBuilder":
        """Set risk limits."""
        self._max_position_size = max_position_size
        self._max_position_value = max_position_value
        self._max_leverage = max_leverage
        return self
    
    def with_config_bundle(self, bundle_id: str) -> "DecisionInputBuilder":
        """Set config bundle ID."""
        self._config_bundle_id = bundle_id
        return self
    
    def build(self) -> DecisionInput:
        """
        Build the DecisionInput.
        
        Returns:
            Complete DecisionInput object
            
        Raises:
            ValueError: If required fields are missing
        """
        if not self._symbol:
            raise ValueError("Symbol is required")
        
        if not self._book:
            raise ValueError("Book data is required")
        
        return DecisionInput(
            symbol=self._symbol,
            ts_wall=self._clock.now(),
            ts_mono=self._clock.now_mono(),
            book=self._book,
            recent_trades=self._recent_trades,
            current_position=self._position,
            account_equity=self._equity,
            available_margin=self._margin,
            open_order_count=self._open_orders,
            pending_intent_count=self._pending_intents,
            max_position_size=self._max_position_size,
            max_position_value=self._max_position_value,
            max_leverage=self._max_leverage,
            config_bundle_id=self._config_bundle_id,
        )
    
    def reset(self) -> "DecisionInputBuilder":
        """Reset builder state."""
        self._symbol = None
        self._book = None
        self._recent_trades = []
        self._position = None
        self._equity = 0.0
        self._margin = 0.0
        self._open_orders = 0
        self._pending_intents = 0
        self._max_position_size = 0.0
        self._max_position_value = 0.0
        self._max_leverage = 1.0
        self._config_bundle_id = None
        return self


def build_decision_input(
    clock: Clock,
    symbol: str,
    book: OrderBook,
    equity: float,
    position: Optional[Position] = None,
    is_quoteable: bool = True,
    config_bundle_id: Optional[str] = None,
) -> DecisionInput:
    """
    Convenience function to build a DecisionInput.
    
    Args:
        clock: Clock for timestamps
        symbol: Trading symbol
        book: Order book
        equity: Account equity
        position: Current position (optional)
        is_quoteable: Whether book is quoteable
        config_bundle_id: Config bundle ID
        
    Returns:
        DecisionInput
    """
    return (
        DecisionInputBuilder(clock)
        .with_symbol(symbol)
        .with_book(book, is_quoteable)
        .with_position(position)
        .with_account(equity)
        .with_config_bundle(config_bundle_id or "")
        .build()
    )


def build_decision_input_from_state(
    clock: Clock,
    symbol: str,
    book_snapshot: BookSnapshot,
    position_state: Optional[Dict[str, Any]],
    account_state: Dict[str, Any],
    config_bundle_id: Optional[str] = None,
) -> DecisionInput:
    """
    Build DecisionInput from state dictionaries.
    
    Useful when reading from Redis or database.
    
    Args:
        clock: Clock for timestamps
        symbol: Trading symbol
        book_snapshot: Book snapshot
        position_state: Position state dict (or None)
        account_state: Account state dict
        config_bundle_id: Config bundle ID
        
    Returns:
        DecisionInput
    """
    builder = (
        DecisionInputBuilder(clock)
        .with_symbol(symbol)
        .with_book_snapshot(book_snapshot)
        .with_account(
            equity=account_state.get("equity", 0.0),
            margin=account_state.get("available_margin", 0.0),
        )
        .with_config_bundle(config_bundle_id or "")
    )
    
    if position_state:
        builder.with_raw_position(
            size=position_state.get("size", 0.0),
            entry_price=position_state.get("entry_price"),
            unrealized_pnl=position_state.get("unrealized_pnl", 0.0),
        )
    
    return builder.build()
