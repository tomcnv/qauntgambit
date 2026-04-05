"""
TimescaleDB writer for time-series market data
"""
import json
import asyncpg
from typing import Dict, Any, List
from datetime import datetime, timedelta
from config.config import config


class TimescaleWriter:
    """Handles writing time-series data to TimescaleDB hypertables"""

    def __init__(self):
        self.connection_string = config.database.connection_string

    async def connect(self) -> asyncpg.Connection:
        """Get database connection"""
        return await asyncpg.connect(self.connection_string)

    async def write_market_trade(self, trade_data: Dict[str, Any]) -> None:
        """Write market trade to hypertable"""
        conn = await self.connect()
        try:
            query = """
                INSERT INTO market_trades (
                    time, symbol, exchange, price, volume, side, trade_id, buyer_order_id, seller_order_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
            """

            await conn.execute(query,
                trade_data["timestamp"],
                trade_data["symbol"],
                trade_data["exchange"],
                trade_data["price"],
                trade_data["volume"],
                trade_data.get("side"),
                trade_data.get("trade_id"),
                trade_data.get("buyer_order_id"),
                trade_data.get("seller_order_id")
            )
        finally:
            await conn.close()

    async def write_order_book_snapshot(self, snapshot_data: Dict[str, Any]) -> None:
        """Write order book snapshot to hypertable"""
        conn = await self.connect()
        try:
            bids = snapshot_data["bids"]
            asks = snapshot_data["asks"]

            # Ensure orderbook depth arrays are JSON-serialized before insert
            bids_json = bids if isinstance(bids, str) else json.dumps(bids)
            asks_json = asks if isinstance(asks, str) else json.dumps(asks)

            query = """
                INSERT INTO order_book_snapshots (
                    time, symbol, exchange, bids, asks, spread, mid_price,
                    bid_volume, ask_volume
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """

            await conn.execute(query,
                snapshot_data["timestamp"],
                snapshot_data["symbol"],
                snapshot_data["exchange"],
                bids_json,
                asks_json,
                snapshot_data["spread"],
                snapshot_data["mid_price"],
                snapshot_data["bid_volume"],
                snapshot_data["ask_volume"]
            )
        finally:
            await conn.close()

    async def write_candle(self, candle_data: Dict[str, Any]) -> None:
        """Write OHLCV candle to hypertable"""
        conn = await self.connect()
        try:
            query = """
                INSERT INTO market_candles (
                    time, symbol, exchange, timeframe, open, high, low, close, volume, trades_count
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT DO NOTHING
            """

            await conn.execute(query,
                candle_data["timestamp"],
                candle_data["symbol"],
                candle_data["exchange"],
                candle_data["timeframe"],
                candle_data["open"],
                candle_data["high"],
                candle_data["low"],
                candle_data["close"],
                candle_data["volume"],
                candle_data.get("trades_count", 0)
            )
        finally:
            await conn.close()

    async def write_amt_metrics(self, metrics_data: Dict[str, Any]) -> None:
        """Write AMT metrics to hypertable"""
        conn = await self.connect()
        try:
            query = """
                INSERT INTO amt_metrics (
                    time, symbol, exchange, timeframe, value_area_low, value_area_high,
                    point_of_control, total_volume, rotation_factor, position_in_value, auction_type
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """

            await conn.execute(query,
                metrics_data["timestamp"],
                metrics_data["symbol"],
                metrics_data["exchange"],
                metrics_data["timeframe"],
                metrics_data.get("value_area_low"),
                metrics_data.get("value_area_high"),
                metrics_data.get("point_of_control"),
                metrics_data.get("total_volume"),
                metrics_data.get("rotation_factor"),
                metrics_data.get("position_in_value"),
                metrics_data.get("auction_type")
            )
        finally:
            await conn.close()

    async def write_microstructure_features(self, features_data: Dict[str, Any]) -> None:
        """Write microstructure features to hypertable"""
        conn = await self.connect()
        try:
            query = """
                INSERT INTO microstructure_features (
                    time, symbol, exchange, bid_ask_spread, bid_ask_imbalance,
                    order_book_depth_5, order_book_depth_10, trade_flow_imbalance,
                    vwap, vwap_deviation, realized_volatility
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """

            await conn.execute(query,
                features_data["timestamp"],
                features_data["symbol"],
                features_data["exchange"],
                features_data.get("bid_ask_spread"),
                features_data.get("bid_ask_imbalance"),
                features_data.get("order_book_depth_5"),
                features_data.get("order_book_depth_10"),
                features_data.get("trade_flow_imbalance"),
                features_data.get("vwap"),
                features_data.get("vwap_deviation"),
                features_data.get("realized_volatility")
            )
        finally:
            await conn.close()

    async def write_strategy_signal(self, signal_data: Dict[str, Any]) -> None:
        """Write strategy signal to hypertable"""
        conn = await self.connect()
        try:
            query = """
                INSERT INTO strategy_signals (
                    time, user_id, strategy_id, symbol, exchange, signal_type, action,
                    confidence, reasoning, features, risk_checks, order_intent,
                    executed, execution_time, execution_result
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """

            await conn.execute(query,
                signal_data["timestamp"],
                signal_data["user_id"],
                signal_data["strategy_id"],
                signal_data["symbol"],
                signal_data["exchange"],
                signal_data["signal_type"],
                signal_data["action"],
                signal_data["confidence"],
                signal_data["reasoning"],
                signal_data.get("features", {}),
                signal_data.get("risk_checks", {}),
                signal_data.get("order_intent", {}),
                signal_data.get("executed", False),
                signal_data.get("execution_time"),
                signal_data.get("execution_result", {})
            )
        finally:
            await conn.close()

    async def get_recent_trades(self, symbol: str, exchange: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades for analysis"""
        conn = await self.connect()
        try:
            query = """
                SELECT * FROM market_trades
                WHERE symbol = $1 AND exchange = $2
                ORDER BY time DESC
                LIMIT $3
            """
            rows = await conn.fetch(query, symbol, exchange, limit)
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_recent_candles(self, symbol: str, exchange: str, timeframe: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent candles for analysis"""
        conn = await self.connect()
        try:
            query = """
                SELECT * FROM market_candles
                WHERE symbol = $1 AND exchange = $2 AND timeframe = $3
                ORDER BY time DESC
                LIMIT $4
            """
            rows = await conn.fetch(query, symbol, exchange, timeframe, limit)
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_amt_metrics(self, symbol: str, exchange: str, timeframe: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent AMT metrics"""
        conn = await self.connect()
        try:
            query = """
                SELECT * FROM amt_metrics
                WHERE symbol = $1 AND exchange = $2 AND timeframe = $3
                ORDER BY time DESC
                LIMIT $4
            """
            rows = await conn.fetch(query, symbol, exchange, timeframe, limit)
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def cleanup_old_data(self, retention_days: int = 90) -> None:
        """Clean up old data (if retention policies are not set)"""
        conn = await self.connect()
        try:
            # This would be handled by TimescaleDB retention policies in production
            # But providing manual cleanup for development
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

            tables_to_clean = [
                'market_trades',
                'order_book_snapshots',
                'market_candles',
                'amt_metrics',
                'microstructure_features',
                'strategy_signals'
            ]

            for table in tables_to_clean:
                query = f"DELETE FROM {table} WHERE time < $1"
                await conn.execute(query, cutoff_date)
                print(f"🧹 Cleaned old data from {table}")

        finally:
            await conn.close()


