"""Chronological merger for orderbook snapshots and trade records.

This module provides the ChronologicalMerger class that merges orderbook
snapshots and trade records in chronological order using a heap-based
merge algorithm.

Feature: backtest-timescaledb-replay
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, List, Optional, Tuple, Union

from quantgambit.storage.persistence import OrderbookSnapshot, PersistenceTradeRecord


@dataclass
class _HeapItem:
    """Internal heap item for merge algorithm.
    
    The heap is ordered by (timestamp, type_priority) where:
    - timestamp: The event timestamp
    - type_priority: 0 for orderbook snapshots, 1 for trades
    
    This ensures orderbook snapshots come before trades with the same timestamp.
    """
    timestamp: datetime
    type_priority: int  # 0 = orderbook, 1 = trade
    item: Union[OrderbookSnapshot, PersistenceTradeRecord]
    source_index: int  # 0 = orderbook iterator, 1 = trade iterator
    
    def __lt__(self, other: "_HeapItem") -> bool:
        """Compare heap items for ordering.
        
        Primary sort by timestamp, secondary by type_priority.
        Orderbook snapshots (type_priority=0) come before trades (type_priority=1)
        when timestamps are equal.
        """
        if self.timestamp == other.timestamp:
            return self.type_priority < other.type_priority
        return self.timestamp < other.timestamp


class ChronologicalMerger:
    """Merges orderbook snapshots and trade records in chronological order.
    
    Uses a heap-based merge algorithm to efficiently combine two sorted
    streams of data. Orderbook snapshots are yielded with accumulated
    trade context from trades that occurred since the previous snapshot.
    
    The merge algorithm ensures:
    1. Events are yielded in chronological order by timestamp
    2. When multiple events have the same timestamp, orderbook snapshots
       are yielded before trade records (Requirement 3.2)
    3. Each orderbook snapshot is paired with all trades that occurred
       between the previous snapshot and this one
    
    Example:
        >>> merger = ChronologicalMerger()
        >>> async for snapshot, trades in merger.merge(orderbook_iter, trade_iter):
        ...     # Process snapshot with associated trades
        ...     print(f"Snapshot at {snapshot.timestamp} with {len(trades)} trades")
    
    Validates: Requirements 3.1, 3.2
    """
    
    async def merge(
        self,
        orderbook_iter: AsyncIterator[OrderbookSnapshot],
        trade_iter: AsyncIterator[PersistenceTradeRecord],
    ) -> AsyncIterator[Tuple[OrderbookSnapshot, List[PersistenceTradeRecord]]]:
        """Merge orderbook snapshots with associated trades.
        
        For each orderbook snapshot, yields the snapshot along with all
        trades that occurred between the previous snapshot and this one.
        Trades with the same timestamp as a snapshot are included with
        that snapshot (since snapshots come before trades in ordering).
        
        The algorithm uses a min-heap to efficiently merge two sorted streams:
        1. Initialize heap with first item from each iterator
        2. Pop smallest item from heap
        3. If it's a snapshot, yield previous snapshot with accumulated trades
        4. If it's a trade, accumulate it for the next snapshot
        5. Push next item from the same iterator to heap
        6. Repeat until both iterators are exhausted
        
        Args:
            orderbook_iter: Async iterator of orderbook snapshots, assumed
                to be sorted by timestamp ascending
            trade_iter: Async iterator of trade records, assumed to be
                sorted by timestamp ascending
            
        Yields:
            Tuples of (OrderbookSnapshot, List[PersistenceTradeRecord])
            where the list contains all trades that occurred between
            the previous snapshot (exclusive) and this one (inclusive of
            trades with the same timestamp as this snapshot)
        """
        # Initialize heap with first items from each iterator
        heap: List[_HeapItem] = []
        iterators_exhausted = [False, False]  # [orderbook, trade]
        
        # Try to get first orderbook snapshot
        try:
            first_orderbook = await orderbook_iter.__anext__()
            heapq.heappush(
                heap,
                _HeapItem(
                    timestamp=first_orderbook.timestamp,
                    type_priority=0,
                    item=first_orderbook,
                    source_index=0,
                ),
            )
        except StopAsyncIteration:
            iterators_exhausted[0] = True
        
        # Try to get first trade record
        try:
            first_trade = await trade_iter.__anext__()
            heapq.heappush(
                heap,
                _HeapItem(
                    timestamp=first_trade.timestamp,
                    type_priority=1,
                    item=first_trade,
                    source_index=1,
                ),
            )
        except StopAsyncIteration:
            iterators_exhausted[1] = True
        
        # Accumulated trades for the NEXT snapshot (trades that come after current snapshot)
        accumulated_trades: List[PersistenceTradeRecord] = []
        # Pending snapshot waiting to be yielded (needs to collect all trades up to next snapshot)
        pending_snapshot: Optional[OrderbookSnapshot] = None
        # Trades to yield with the pending snapshot
        pending_trades: List[PersistenceTradeRecord] = []
        
        while heap:
            # Pop smallest item
            heap_item = heapq.heappop(heap)
            
            if heap_item.source_index == 0:
                # This is an orderbook snapshot
                snapshot = heap_item.item
                assert isinstance(snapshot, OrderbookSnapshot)
                
                # If we have a pending snapshot, yield it now with its accumulated trades
                if pending_snapshot is not None:
                    yield (pending_snapshot, pending_trades)
                
                # The current snapshot becomes pending, with accumulated trades
                # (trades that came after the previous snapshot but before/at this one)
                pending_snapshot = snapshot
                pending_trades = accumulated_trades
                accumulated_trades = []
                
                # Try to get next orderbook snapshot
                if not iterators_exhausted[0]:
                    try:
                        next_orderbook = await orderbook_iter.__anext__()
                        heapq.heappush(
                            heap,
                            _HeapItem(
                                timestamp=next_orderbook.timestamp,
                                type_priority=0,
                                item=next_orderbook,
                                source_index=0,
                            ),
                        )
                    except StopAsyncIteration:
                        iterators_exhausted[0] = True
            else:
                # This is a trade record
                trade = heap_item.item
                assert isinstance(trade, PersistenceTradeRecord)
                
                # Accumulate trade for the next snapshot
                accumulated_trades.append(trade)
                
                # Try to get next trade record
                if not iterators_exhausted[1]:
                    try:
                        next_trade = await trade_iter.__anext__()
                        heapq.heappush(
                            heap,
                            _HeapItem(
                                timestamp=next_trade.timestamp,
                                type_priority=1,
                                item=next_trade,
                                source_index=1,
                            ),
                        )
                    except StopAsyncIteration:
                        iterators_exhausted[1] = True
        
        # Yield final pending snapshot with any remaining accumulated trades
        if pending_snapshot is not None:
            # Combine pending_trades with any remaining accumulated_trades
            yield (pending_snapshot, pending_trades + accumulated_trades)
