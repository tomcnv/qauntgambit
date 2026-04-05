"""
PostgreSQL models for interfacing with existing database schema
"""
import asyncpg
from typing import Dict, Any, List, Optional
from datetime import datetime
from config.config import config


class UserTradingSettings:
    """Model for user_trading_settings table"""

    @staticmethod
    async def get_settings(user_id: str) -> Optional[Dict[str, Any]]:
        """Get user trading settings by user ID"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                SELECT * FROM user_trading_settings
                WHERE user_id = $1
            """
            row = await conn.fetchrow(query, user_id)

            if row:
                # Convert to dict and handle JSONB fields
                settings = dict(row)
                # JSONB fields are already parsed by asyncpg
                return settings
            return None
        finally:
            await conn.close()

    @staticmethod
    async def create_default_settings(user_id: str) -> Dict[str, Any]:
        """Create default settings for a new user"""
        from quantgambit.deeptrader_core.storage.default_settings import get_default_trading_settings

        default_settings = get_default_trading_settings()
        default_settings["user_id"] = user_id

        conn = await asyncpg.connect(config.database.connection_string)
        try:
            # Build dynamic INSERT query
            columns = list(default_settings.keys())
            placeholders = [f"${i+1}" for i in range(len(columns))]
            values = list(default_settings.values())

            query = f"""
                INSERT INTO user_trading_settings ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                RETURNING *
            """

            row = await conn.fetchrow(query, *values)
            return dict(row)
        finally:
            await conn.close()

    @staticmethod
    async def update_settings(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user trading settings"""
        if not updates:
            raise ValueError("No fields to update")

        conn = await asyncpg.connect(config.database.connection_string)
        try:
            # Check if settings exist
            existing = await UserTradingSettings.get_settings(user_id)
            if not existing:
                await UserTradingSettings.create_default_settings(user_id)
                existing = await UserTradingSettings.get_settings(user_id)

            # Build UPDATE query
            set_parts = []
            values = [user_id]
            param_index = 2

            for key, value in updates.items():
                if key in existing:  # Only update existing columns
                    set_parts.append(f"{key} = ${param_index}")
                    values.append(value)
                    param_index += 1

            if not set_parts:
                return existing

            set_parts.append("updated_at = CURRENT_TIMESTAMP")

            query = f"""
                UPDATE user_trading_settings
                SET {', '.join(set_parts)}
                WHERE user_id = $1
                RETURNING *
            """

            row = await conn.fetchrow(query, *values)
            return dict(row)
        finally:
            await conn.close()


class TradingDecision:
    """Model for trading_decisions table"""

    @staticmethod
    async def create(decision_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new trading decision"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                INSERT INTO trading_decisions (
                    user_id, portfolio_id, token, decision, market_data,
                    multi_timeframe, confidence, action, executed, reasoning, factors
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING *
            """

            values = [
                decision_data["user_id"],
                decision_data.get("portfolio_id"),
                decision_data["token"],
                decision_data["decision"],
                decision_data.get("market_data", {}),
                decision_data.get("multi_timeframe", {}),
                decision_data.get("confidence", 0),
                decision_data.get("action", "hold"),
                decision_data.get("executed", False),
                decision_data.get("reasoning"),
                decision_data.get("factors")
            ]

            row = await conn.fetchrow(query, *values)
            return dict(row)
        finally:
            await conn.close()

    @staticmethod
    async def mark_executed(decision_id: int, order_id: str) -> None:
        """Mark a decision as executed"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                UPDATE trading_decisions
                SET executed = true, executed_at = CURRENT_TIMESTAMP
                WHERE id = $1
            """
            await conn.execute(query, decision_id)
        finally:
            await conn.close()


class TradingActivity:
    """Model for trading_activity table"""

    @staticmethod
    async def log_decision(user_id: str, decision: Dict[str, Any], token: str, market_data: Dict[str, Any], details: Dict[str, Any]) -> None:
        """Log a trading decision"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                INSERT INTO trading_activity (
                    user_id, activity_type, token, decision, market_data, details
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """

            await conn.execute(query, user_id, "decision", token, decision, market_data, details)
        finally:
            await conn.close()

    @staticmethod
    async def log_trade_blocked(user_id: str, token: str, trade_data: Dict[str, Any], reason: str, details: Dict[str, Any]) -> None:
        """Log a blocked trade"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                INSERT INTO trading_activity (
                    user_id, activity_type, token, trade_data, details, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """

            await conn.execute(query, user_id, "trade_blocked", token, trade_data, details, {"reason": reason})
        finally:
            await conn.close()


class Portfolio:
    """Model for portfolios table"""

    @staticmethod
    async def find_by_user_id(user_id: str) -> List[Dict[str, Any]]:
        """Find portfolios for a user"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = "SELECT * FROM portfolios WHERE user_id = $1"
            rows = await conn.fetch(query, user_id)
            return [dict(row) for row in rows]
        finally:
            await conn.close()


class Position:
    """Model for positions table"""

    @staticmethod
    async def find_open_by_portfolio_id(portfolio_id: int) -> List[Dict[str, Any]]:
        """Find open positions for a portfolio"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                SELECT * FROM positions
                WHERE portfolio_id = $1 AND status = 'open'
                ORDER BY created_at DESC
            """
            rows = await conn.fetch(query, portfolio_id)
            return [dict(row) for row in rows]
        finally:
            await conn.close()


class Order:
    """Model for orders table"""

    @staticmethod
    async def create(order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new order"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                INSERT INTO orders (
                    user_id, symbol, order_type, side, quantity, price,
                    stop_price, time_in_force, status, exchange
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
            """

            values = [
                order_data["user_id"],
                order_data["symbol"],
                order_data["order_type"],
                order_data["side"],
                order_data["quantity"],
                order_data.get("price"),
                order_data.get("stop_price"),
                order_data.get("time_in_force", "GTC"),
                order_data.get("status", "pending"),
                order_data.get("exchange", "binance")
            ]

            row = await conn.fetchrow(query, *values)
            return dict(row)
        finally:
            await conn.close()

    @staticmethod
    async def find_by_id(order_id: str) -> Optional[Dict[str, Any]]:
        """Find order by ID"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = "SELECT * FROM orders WHERE id = $1"
            row = await conn.fetchrow(query, order_id)
            return dict(row) if row else None
        finally:
            await conn.close()

    @staticmethod
    async def update_status(order_id: str, status: str, execution_data: Dict[str, Any] = None) -> None:
        """Update order status"""
        conn = await asyncpg.connect(config.database.connection_string)
        try:
            query = """
                UPDATE orders
                SET status = $1, executed_quantity = $2, executed_price = $3,
                    executed_at = CURRENT_TIMESTAMP
                WHERE id = $1
            """

            await conn.execute(query,
                status,
                execution_data.get("executed_quantity"),
                execution_data.get("executed_price")
            )
        finally:
            await conn.close()
