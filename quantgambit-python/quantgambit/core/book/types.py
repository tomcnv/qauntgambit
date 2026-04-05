"""
Order book data types.

Pure data structures for representing order book state.
No I/O or side effects.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple


class BookSide(str, Enum):
    """Order book side."""
    
    BID = "bid"
    ASK = "ask"


@dataclass
class Level:
    """
    Single price level in the order book.
    
    Attributes:
        price: Price at this level
        size: Total size at this level
        count: Number of orders at this level (if available)
    """
    
    price: float
    size: float
    count: Optional[int] = None
    
    def __post_init__(self):
        """Validate level data."""
        if self.price < 0:
            raise ValueError(f"Price cannot be negative: {self.price}")
        if self.size < 0:
            raise ValueError(f"Size cannot be negative: {self.size}")
    
    def to_tuple(self) -> Tuple[float, float]:
        """Convert to (price, size) tuple."""
        return (self.price, self.size)
    
    @classmethod
    def from_tuple(cls, data: Tuple[float, float]) -> "Level":
        """Create from (price, size) tuple."""
        return cls(price=float(data[0]), size=float(data[1]))
    
    @classmethod
    def from_list(cls, data: List) -> "Level":
        """Create from [price, size] or [price, size, count] list."""
        price = float(data[0])
        size = float(data[1])
        count = int(data[2]) if len(data) > 2 else None
        return cls(price=price, size=size, count=count)


@dataclass
class OrderBook:
    """
    Order book state for a symbol.
    
    Bids are sorted descending (best bid first).
    Asks are sorted ascending (best ask first).
    
    Attributes:
        symbol: Trading symbol
        bids: List of bid levels (descending by price)
        asks: List of ask levels (ascending by price)
        update_id: Venue-specific update/sequence ID
        timestamp: Exchange timestamp (epoch seconds)
        local_timestamp: Local receipt timestamp (epoch seconds)
    """
    
    symbol: str
    bids: List[Level] = field(default_factory=list)
    asks: List[Level] = field(default_factory=list)
    update_id: Optional[int] = None
    timestamp: Optional[float] = None
    local_timestamp: Optional[float] = None
    
    @property
    def best_bid(self) -> Optional[Level]:
        """Get best (highest) bid."""
        return self.bids[0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[Level]:
        """Get best (lowest) ask."""
        return self.asks[0] if self.asks else None
    
    @property
    def best_bid_price(self) -> Optional[float]:
        """Get best bid price."""
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask_price(self) -> Optional[float]:
        """Get best ask price."""
        return self.asks[0].price if self.asks else None
    
    @property
    def mid_price(self) -> Optional[float]:
        """Get mid price (average of best bid and ask)."""
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2
    
    @property
    def spread(self) -> Optional[float]:
        """Get spread (best ask - best bid)."""
        if not self.bids or not self.asks:
            return None
        return self.asks[0].price - self.bids[0].price
    
    @property
    def spread_bps(self) -> Optional[float]:
        """Get spread in basis points."""
        mid = self.mid_price
        spread = self.spread
        if mid is None or spread is None or mid == 0:
            return None
        return (spread / mid) * 10000
    
    def is_crossed(self) -> bool:
        """
        Check if book is crossed (best bid >= best ask).
        
        A crossed book is invalid and indicates data corruption.
        """
        if not self.bids or not self.asks:
            return False
        return self.bids[0].price >= self.asks[0].price
    
    def is_empty(self) -> bool:
        """Check if book has no levels."""
        return not self.bids and not self.asks
    
    def depth(self, side: BookSide) -> int:
        """Get number of levels on a side."""
        if side == BookSide.BID:
            return len(self.bids)
        return len(self.asks)
    
    def total_depth(self) -> int:
        """Get total number of levels."""
        return len(self.bids) + len(self.asks)
    
    def size_at_level(self, side: BookSide, level: int) -> Optional[float]:
        """Get size at a specific level (0-indexed)."""
        levels = self.bids if side == BookSide.BID else self.asks
        if level < len(levels):
            return levels[level].size
        return None
    
    def cumulative_size(self, side: BookSide, levels: int) -> float:
        """Get cumulative size across first N levels."""
        book_levels = self.bids if side == BookSide.BID else self.asks
        return sum(l.size for l in book_levels[:levels])
    
    def price_for_size(self, side: BookSide, size: float) -> Optional[float]:
        """
        Get volume-weighted average price to fill a given size.
        
        Returns None if not enough liquidity.
        """
        levels = self.bids if side == BookSide.BID else self.asks
        remaining = size
        total_value = 0.0
        total_size = 0.0
        
        for level in levels:
            fill_size = min(remaining, level.size)
            total_value += fill_size * level.price
            total_size += fill_size
            remaining -= fill_size
            
            if remaining <= 0:
                break
        
        if remaining > 0:
            return None  # Not enough liquidity
        
        return total_value / total_size if total_size > 0 else None
    
    def imbalance(self, levels: int = 5) -> Optional[float]:
        """
        Calculate order book imbalance.
        
        Returns value in [-1, 1] where:
        - Positive = more bid pressure
        - Negative = more ask pressure
        """
        bid_size = self.cumulative_size(BookSide.BID, levels)
        ask_size = self.cumulative_size(BookSide.ASK, levels)
        total = bid_size + ask_size
        
        if total == 0:
            return None
        
        return (bid_size - ask_size) / total
    
    def microprice(self) -> Optional[float]:
        """
        Calculate microprice (size-weighted mid).
        
        Microprice = (bid_size * ask_price + ask_size * bid_price) / (bid_size + ask_size)
        """
        if not self.bids or not self.asks:
            return None
        
        bid = self.bids[0]
        ask = self.asks[0]
        total_size = bid.size + ask.size
        
        if total_size == 0:
            return self.mid_price
        
        return (bid.size * ask.price + ask.size * bid.price) / total_size
    
    def apply_delta(
        self,
        side: BookSide,
        price: float,
        size: float,
    ) -> None:
        """
        Apply a delta update to the book.
        
        If size is 0, removes the level.
        Otherwise, updates or inserts the level.
        """
        levels = self.bids if side == BookSide.BID else self.asks
        
        # Find existing level
        for i, level in enumerate(levels):
            if level.price == price:
                if size == 0:
                    levels.pop(i)
                else:
                    levels[i] = Level(price=price, size=size)
                return
        
        # Level not found - insert if size > 0
        if size > 0:
            new_level = Level(price=price, size=size)
            
            # Insert in sorted order
            if side == BookSide.BID:
                # Bids: descending
                for i, level in enumerate(levels):
                    if price > level.price:
                        levels.insert(i, new_level)
                        return
                levels.append(new_level)
            else:
                # Asks: ascending
                for i, level in enumerate(levels):
                    if price < level.price:
                        levels.insert(i, new_level)
                        return
                levels.append(new_level)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "bids": [[l.price, l.size] for l in self.bids],
            "asks": [[l.price, l.size] for l in self.asks],
            "update_id": self.update_id,
            "timestamp": self.timestamp,
            "local_timestamp": self.local_timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderBook":
        """Deserialize from dictionary."""
        return cls(
            symbol=data["symbol"],
            bids=[Level.from_list(l) for l in data.get("bids", [])],
            asks=[Level.from_list(l) for l in data.get("asks", [])],
            update_id=data.get("update_id"),
            timestamp=data.get("timestamp"),
            local_timestamp=data.get("local_timestamp"),
        )
    
    def copy(self) -> "OrderBook":
        """Create a deep copy."""
        return OrderBook(
            symbol=self.symbol,
            bids=[Level(l.price, l.size, l.count) for l in self.bids],
            asks=[Level(l.price, l.size, l.count) for l in self.asks],
            update_id=self.update_id,
            timestamp=self.timestamp,
            local_timestamp=self.local_timestamp,
        )
    
    @property
    def sequence_id(self) -> Optional[int]:
        """Alias for update_id for compatibility."""
        return self.update_id


@dataclass
class BookUpdate:
    """
    Incremental book update message.
    
    Represents a snapshot or delta update to an order book.
    
    Attributes:
        symbol: Trading symbol
        bids: Bid level updates
        asks: Ask level updates
        sequence_id: Sequence/update ID
        timestamp: Exchange timestamp
        is_snapshot: True if full snapshot, False if delta
    """
    
    symbol: str
    bids: List[Level] = field(default_factory=list)
    asks: List[Level] = field(default_factory=list)
    sequence_id: Optional[int] = None
    timestamp: Optional[float] = None
    is_snapshot: bool = False
    
    def to_order_book(self) -> OrderBook:
        """Convert to OrderBook (for snapshots)."""
        return OrderBook(
            symbol=self.symbol,
            bids=list(self.bids),
            asks=list(self.asks),
            update_id=self.sequence_id,
            timestamp=self.timestamp,
        )
