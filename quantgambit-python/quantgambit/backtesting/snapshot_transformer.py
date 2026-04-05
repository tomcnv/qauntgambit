"""Snapshot transformer for converting TimescaleDB data to feature snapshot format.

This module provides the SnapshotTransformer class that converts raw orderbook
snapshots and trade records from TimescaleDB into the feature snapshot format
expected by ReplayWorker.

Feature: backtest-timescaledb-replay
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quantgambit.storage.persistence import OrderbookSnapshot


@dataclass
class TradeContext:
    """Trade context for a snapshot interval.
    
    This dataclass aggregates trade information that occurred between
    consecutive orderbook snapshots. It provides trade-derived features
    for the feature snapshot format.
    
    Attributes:
        last_trade_price: The price of the most recent trade in the interval.
            None if no trades occurred.
        last_trade_side: The side ("buy" or "sell") of the most recent trade.
            None if no trades occurred.
        trade_count: The number of trades that occurred in the interval.
        total_volume: The total volume (sum of sizes) of all trades.
        buy_volume: The total volume of buy trades.
        sell_volume: The total volume of sell trades.
    
    Validates: Requirements 2.4
    """
    
    last_trade_price: Optional[float]
    last_trade_side: Optional[str]
    trade_count: int
    total_volume: float
    buy_volume: float
    sell_volume: float


class SnapshotTransformer:
    """Transforms OrderbookSnapshot and trades into feature snapshot format.
    
    The transformer converts raw orderbook data and trade records into the
    feature snapshot format expected by ReplayWorker. This includes:
    - Calculating mid-price from best bid/ask
    - Building market_context with depth and spread metrics
    - Including trade-derived features when available
    - Setting appropriate default values for missing fields
    
    Example:
        >>> transformer = SnapshotTransformer()
        >>> snapshot = transformer.transform(orderbook_snapshot, trade_context)
        >>> # snapshot is now ready for ReplayWorker
    
    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
    """
    
    def transform(
        self,
        orderbook: OrderbookSnapshot,
        trade_context: Optional[TradeContext] = None,
    ) -> dict:
        """Transform orderbook snapshot to feature snapshot format.
        
        Args:
            orderbook: OrderbookSnapshot from TimescaleDB
            trade_context: Optional trade context for the snapshot interval
            
        Returns:
            Feature snapshot dictionary with:
            - symbol: Trading symbol
            - timestamp: Unix timestamp
            - market_context: Price, bid/ask, spread, depth metrics
            - features: Additional computed features
            - prediction: Default prediction (confidence=0.5)
            - warmup_ready: True (historical data is always ready)
        
        Validates: Requirements 2.1, 2.3, 2.6
        """
        # Build market context with all required fields
        market_context = self.build_market_context(orderbook, trade_context)
        
        # Build features from trade context
        features = self._build_features(trade_context)
        
        # Convert timestamp to Unix timestamp
        timestamp = orderbook.timestamp.timestamp()
        
        return {
            "symbol": orderbook.symbol,
            "timestamp": timestamp,
            "market_context": market_context,
            "features": features,
            "prediction": {
                "confidence": 0.5,
                "direction": "neutral",
                "source": "backtest_default",
            },
            "warmup_ready": True,  # Historical data is always ready (Req 2.6)
        }
    
    def calculate_mid_price(self, best_bid: float, best_ask: float) -> float:
        """Calculate mid-price from best bid and ask.
        
        Args:
            best_bid: Best bid price
            best_ask: Best ask price
            
        Returns:
            Mid-price as (best_bid + best_ask) / 2
        
        Validates: Requirements 2.2
        """
        return (best_bid + best_ask) / 2.0
    
    def build_market_context(
        self,
        orderbook: OrderbookSnapshot,
        trade_context: Optional[TradeContext] = None,
    ) -> dict:
        """Build market_context dictionary from orderbook and trades.
        
        Args:
            orderbook: OrderbookSnapshot with depth and spread metrics
            trade_context: Optional trade context
            
        Returns:
            market_context dictionary with all required fields:
            - price: Mid-price (or last trade price if available)
            - bid: Best bid price
            - ask: Best ask price
            - best_bid: Alias for bid (for EV gate compatibility)
            - best_ask: Alias for ask (for EV gate compatibility)
            - spread_bps: Spread in basis points
            - bid_depth_usd: Total bid depth in USD
            - ask_depth_usd: Total ask depth in USD
            - orderbook_imbalance: Bid depth / total depth
            - last_trade_price: Optional last trade price
            - last_trade_side: Optional last trade side
        
        Validates: Requirements 2.1, 2.4, 2.5
        """
        # Extract best bid and ask from orderbook levels
        best_bid = orderbook.bids[0][0] if orderbook.bids else 0.0
        best_ask = orderbook.asks[0][0] if orderbook.asks else 0.0
        
        # Calculate mid-price (Req 2.2)
        mid_price = self.calculate_mid_price(best_bid, best_ask)
        
        # Determine price field:
        # - Use last trade price if trades exist (Req 2.4)
        # - Otherwise use mid-price (Req 2.5)
        if trade_context is not None and trade_context.last_trade_price is not None:
            price = trade_context.last_trade_price
        else:
            price = mid_price
        
        # Build market context with all required fields (Req 2.1)
        market_context = {
            "price": price,
            "bid": best_bid,
            "ask": best_ask,
            "best_bid": best_bid,  # Alias for EV gate
            "best_ask": best_ask,  # Alias for EV gate
            "spread_bps": orderbook.spread_bps,
            "bid_depth_usd": orderbook.bid_depth_usd,
            "ask_depth_usd": orderbook.ask_depth_usd,
            "orderbook_imbalance": orderbook.orderbook_imbalance,
        }
        
        # Add trade-derived fields if trade context exists (Req 2.4)
        if trade_context is not None:
            if trade_context.last_trade_price is not None:
                market_context["last_trade_price"] = trade_context.last_trade_price
            if trade_context.last_trade_side is not None:
                market_context["last_trade_side"] = trade_context.last_trade_side
        
        return market_context
    
    def _build_features(self, trade_context: Optional[TradeContext]) -> dict:
        """Build features dictionary from trade context.
        
        Args:
            trade_context: Optional trade context
            
        Returns:
            Features dictionary with trade-derived metrics
        """
        if trade_context is None:
            return {
                "trade_count": 0,
                "buy_volume": 0.0,
                "sell_volume": 0.0,
            }
        
        return {
            "trade_count": trade_context.trade_count,
            "buy_volume": trade_context.buy_volume,
            "sell_volume": trade_context.sell_volume,
        }
