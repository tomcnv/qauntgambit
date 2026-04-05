"""Simple backtest executor that uses historical candle data.

This is a simplified executor that:
1. Fetches historical candles from TimescaleDB
2. Runs a basic simulation
3. Stores results to the database

For production use, this should be replaced with a full strategy backtesting engine.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
    BacktestMetricsRecord,
    BacktestTradeRecord,
    BacktestEquityPoint,
)

logger = logging.getLogger(__name__)


@dataclass
class SimpleExecutorConfig:
    """Configuration for the simple executor."""
    timescale_host: str = "localhost"
    timescale_port: int = 5433
    timescale_db: str = "quantgambit_bot"
    timescale_user: str = "quantgambit"
    timescale_password: str = ""
    
    @classmethod
    def from_env(cls) -> "SimpleExecutorConfig":
        """Create config from environment variables."""
        return cls(
            timescale_host=os.getenv("TIMESCALE_HOST", os.getenv("BOT_DB_HOST", "localhost")),
            timescale_port=int(os.getenv("TIMESCALE_PORT", os.getenv("BOT_DB_PORT", "5433"))),
            timescale_db=os.getenv("TIMESCALE_DB", os.getenv("BOT_DB_NAME", "quantgambit_bot")),
            timescale_user=os.getenv("TIMESCALE_USER", os.getenv("BOT_DB_USER", "quantgambit")),
            timescale_password=os.getenv("TIMESCALE_PASSWORD", os.getenv("BOT_DB_PASSWORD", "")),
        )


class SimpleBacktestExecutor:
    """Simple backtest executor using historical candle data."""
    
    def __init__(
        self,
        platform_pool,
        config: Optional[SimpleExecutorConfig] = None,
    ):
        """Initialize the executor.
        
        Args:
            platform_pool: asyncpg connection pool for platform_db
            config: Optional executor configuration
        """
        self.platform_pool = platform_pool
        self.config = config or SimpleExecutorConfig.from_env()
        self.store = BacktestStore(platform_pool)
        self._timescale_pool = None
    
    async def _get_timescale_pool(self):
        """Get or create TimescaleDB connection pool."""
        if self._timescale_pool is None:
            import asyncpg
            auth = f"{self.config.timescale_user}:{self.config.timescale_password}@" if self.config.timescale_password else f"{self.config.timescale_user}@"
            dsn = f"postgresql://{auth}{self.config.timescale_host}:{self.config.timescale_port}/{self.config.timescale_db}"
            self._timescale_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        return self._timescale_pool
    
    async def execute(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a backtest.
        
        Args:
            run_id: Unique identifier for this backtest run
            tenant_id: Tenant ID
            bot_id: Bot ID
            config: Backtest configuration
            
        Returns:
            Dict with execution results
        """
        started_at = datetime.now(timezone.utc).isoformat()
        
        try:
            # Update status to running
            await self._update_status(run_id, tenant_id, bot_id, "running", config, started_at)
            logger.info(f"Starting backtest {run_id} for {config.get('symbol')}")
            
            # Fetch historical candles
            candles = await self._fetch_candles(
                symbol=config.get("symbol"),
                start_date=config.get("start_date"),
                end_date=config.get("end_date"),
            )
            
            if not candles:
                raise ValueError(f"No candle data found for {config.get('symbol')} in the specified date range")
            
            logger.info(f"Fetched {len(candles)} candles for backtest {run_id}")
            
            # Run simulation
            results = await self._run_simulation(
                run_id=run_id,
                candles=candles,
                config=config,
            )
            
            # Store results
            await self._store_results(run_id, results)
            
            # Update status to completed
            finished_at = datetime.now(timezone.utc).isoformat()
            await self._update_status(
                run_id, tenant_id, bot_id, "completed", config, started_at, finished_at
            )
            
            logger.info(f"Backtest {run_id} completed successfully")
            return {"status": "completed", "run_id": run_id, **results["metrics"]}
            
        except Exception as e:
            logger.exception(f"Backtest {run_id} failed: {e}")
            finished_at = datetime.now(timezone.utc).isoformat()
            await self._update_status(
                run_id, tenant_id, bot_id, "failed", config, started_at, finished_at, str(e)
            )
            return {"status": "failed", "run_id": run_id, "error": str(e)}
    
    async def _fetch_candles(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """Fetch historical candles from TimescaleDB."""
        pool = await self._get_timescale_pool()
        
        query = """
            SELECT ts, open, high, low, close, volume
            FROM market_candles
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
            ORDER BY ts ASC
        """
        
        # Parse dates
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00')) if 'T' in start_date else datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00')) if 'T' in end_date else datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, start_dt, end_dt)
            return [
                {
                    "ts": row["ts"].isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]) if row["volume"] else 0,
                }
                for row in rows
            ]
    
    async def _run_simulation(
        self,
        run_id: str,
        candles: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run a simple trading simulation.
        
        Uses a basic mean-reversion strategy that buys dips and sells rallies.
        """
        initial_capital = config.get("initial_capital", 10000.0)
        maker_fee_bps = config.get("maker_fee_bps", 2.0)
        taker_fee_bps = config.get("taker_fee_bps", 5.5)
        slippage_bps = config.get("slippage_bps", 5.0) if config.get("slippage_model") != "none" else 0
        
        # Fee calculation (use taker fee for market orders)
        fee_rate = taker_fee_bps / 10000
        slippage_rate = slippage_bps / 10000
        
        # Simulation state
        equity = initial_capital
        peak_equity = initial_capital
        max_drawdown = 0.0
        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        
        # Position tracking
        position = 0  # 0 = flat, 1 = long, -1 = short
        entry_price = 0.0
        entry_time = None
        bars_in_trade = 0
        
        # Sample equity every N candles
        sample_interval = max(1, len(candles) // 500)
        
        # Calculate simple moving averages for mean reversion
        lookback = 20
        
        for i, candle in enumerate(candles):
            price = candle["close"]
            ts = candle["ts"]
            
            if i >= lookback:
                # Calculate SMA
                sma = sum(c["close"] for c in candles[i-lookback:i]) / lookback
                
                # Calculate price deviation from SMA
                deviation = (price - sma) / sma
                
                # Entry logic - mean reversion
                if position == 0:
                    # Buy when price is significantly below SMA (oversold)
                    if deviation < -0.005:  # 0.5% below SMA
                        position = 1
                        entry_price = price * (1 + slippage_rate)  # Slippage makes entry worse
                        entry_time = ts
                        bars_in_trade = 0
                    # Short when price is significantly above SMA (overbought)
                    elif deviation > 0.005:  # 0.5% above SMA
                        position = -1
                        entry_price = price * (1 - slippage_rate)  # Slippage makes entry worse
                        entry_time = ts
                        bars_in_trade = 0
                
                # Exit logic
                elif position != 0:
                    bars_in_trade += 1
                    
                    # Calculate unrealized PnL
                    if position == 1:  # Long
                        exit_price_with_slip = price * (1 - slippage_rate)
                        pnl_pct = (exit_price_with_slip - entry_price) / entry_price
                    else:  # Short
                        exit_price_with_slip = price * (1 + slippage_rate)
                        pnl_pct = (entry_price - exit_price_with_slip) / entry_price
                    
                    # Exit conditions
                    should_exit = False
                    
                    # Take profit at 0.8%
                    if pnl_pct > 0.008:
                        should_exit = True
                    # Stop loss at 0.5%
                    elif pnl_pct < -0.005:
                        should_exit = True
                    # Mean reversion target: exit when price returns to SMA
                    elif position == 1 and deviation > 0:  # Long and price above SMA
                        should_exit = True
                    elif position == -1 and deviation < 0:  # Short and price below SMA
                        should_exit = True
                    # Time-based exit: max 50 bars
                    elif bars_in_trade > 50:
                        should_exit = True
                    
                    if should_exit:
                        # Calculate final exit price with slippage
                        if position == 1:
                            exit_price = price * (1 - slippage_rate)
                        else:
                            exit_price = price * (1 + slippage_rate)
                        
                        # Calculate PnL
                        trade_size = equity * 0.1  # 10% position size
                        if position == 1:
                            gross_pnl = trade_size * (exit_price - entry_price) / entry_price
                        else:
                            gross_pnl = trade_size * (entry_price - exit_price) / entry_price
                        
                        fees = trade_size * fee_rate * 2  # Entry + exit fees
                        net_pnl = gross_pnl - fees
                        
                        equity += net_pnl
                        
                        # Record trade
                        trades.append({
                            "ts": ts,
                            "symbol": config.get("symbol"),
                            "side": "buy" if position == 1 else "sell",
                            "size": trade_size / entry_price,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": net_pnl,
                            "entry_fee": trade_size * fee_rate,
                            "exit_fee": trade_size * fee_rate,
                            "total_fees": fees,
                            "entry_slippage_bps": slippage_bps,
                            "exit_slippage_bps": slippage_bps,
                        })
                        
                        # Reset position
                        position = 0
                        entry_price = 0.0
                        entry_time = None
                        bars_in_trade = 0
            
            # Track drawdown
            if equity > peak_equity:
                peak_equity = equity
            drawdown = (peak_equity - equity) / peak_equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            
            # Sample equity curve
            if i % sample_interval == 0:
                equity_curve.append({
                    "ts": ts,
                    "equity": equity,
                    "realized_pnl": equity - initial_capital,
                    "open_positions": 1 if position != 0 else 0,
                })
        
        # Calculate metrics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["pnl"] > 0)
        losing_trades = sum(1 for t in trades if t["pnl"] < 0)
        
        total_pnl = sum(t["pnl"] for t in trades)
        total_fees = sum(t["total_fees"] for t in trades)
        
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        avg_trade_pnl = (total_pnl / total_trades) if total_trades > 0 else 0
        total_return_pct = ((equity - initial_capital) / initial_capital) * 100
        
        # Calculate average win/loss
        winning_pnls = [t["pnl"] for t in trades if t["pnl"] > 0]
        losing_pnls = [t["pnl"] for t in trades if t["pnl"] < 0]
        avg_win = (sum(winning_pnls) / len(winning_pnls)) if winning_pnls else 0
        avg_loss = (sum(losing_pnls) / len(losing_pnls)) if losing_pnls else 0
        largest_win = max(winning_pnls) if winning_pnls else 0
        largest_loss = min(losing_pnls) if losing_pnls else 0
        
        # Calculate trades per day
        if candles and len(candles) > 1:
            start_ts = datetime.fromisoformat(candles[0]["ts"].replace('Z', '+00:00'))
            end_ts = datetime.fromisoformat(candles[-1]["ts"].replace('Z', '+00:00'))
            days = (end_ts - start_ts).total_seconds() / 86400
            trades_per_day = total_trades / days if days > 0 else 0
        else:
            trades_per_day = 0
        
        # Calculate fee drag and slippage drag (as % of initial capital)
        fee_drag_pct = (total_fees / initial_capital) * 100 if initial_capital > 0 else 0
        
        # Estimate slippage cost (entry + exit slippage per trade)
        total_slippage_cost = sum(
            t["size"] * t["entry_price"] * (t["entry_slippage_bps"] / 10000) +
            t["size"] * t["exit_price"] * (t["exit_slippage_bps"] / 10000)
            for t in trades
        )
        slippage_drag_pct = (total_slippage_cost / initial_capital) * 100 if initial_capital > 0 else 0
        
        # Calculate Sharpe ratio (annualized)
        sharpe = 0.0
        sortino = 0.0
        if trades:
            trade_returns = [t["pnl"] / initial_capital for t in trades]
            avg_return = sum(trade_returns) / len(trade_returns)
            std_return = (sum((r - avg_return) ** 2 for r in trade_returns) / len(trade_returns)) ** 0.5
            sharpe = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
            
            # Sortino ratio (only downside deviation)
            downside_returns = [r for r in trade_returns if r < 0]
            if downside_returns:
                downside_std = (sum(r ** 2 for r in downside_returns) / len(downside_returns)) ** 0.5
                sortino = (avg_return / downside_std * (252 ** 0.5)) if downside_std > 0 else 0
        
        return {
            "metrics": {
                "realized_pnl": total_pnl,
                "total_fees": total_fees,
                "total_trades": total_trades,
                "win_rate": win_rate,
                "max_drawdown_pct": max_drawdown * 100,
                "avg_slippage_bps": slippage_bps,
                "total_return_pct": total_return_pct,
                "profit_factor": profit_factor,
                "avg_trade_pnl": avg_trade_pnl,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "trades_per_day": trades_per_day,
                "fee_drag_pct": fee_drag_pct,
                "slippage_drag_pct": slippage_drag_pct,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "largest_win": largest_win,
                "largest_loss": largest_loss,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
            },
            "trades": trades,
            "equity_curve": equity_curve,
        }
    
    async def _store_results(self, run_id: str, results: Dict[str, Any]) -> None:
        """Store backtest results to the database."""
        metrics = results["metrics"]
        
        # Store metrics
        metrics_record = BacktestMetricsRecord(
            run_id=run_id,
            realized_pnl=metrics["realized_pnl"],
            total_fees=metrics["total_fees"],
            total_trades=metrics["total_trades"],
            win_rate=metrics["win_rate"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            avg_slippage_bps=metrics["avg_slippage_bps"],
            total_return_pct=metrics["total_return_pct"],
            profit_factor=metrics["profit_factor"],
            avg_trade_pnl=metrics["avg_trade_pnl"],
            sharpe_ratio=metrics.get("sharpe_ratio", 0),
            sortino_ratio=metrics.get("sortino_ratio", 0),
            trades_per_day=metrics.get("trades_per_day", 0),
            fee_drag_pct=metrics.get("fee_drag_pct", 0),
            slippage_drag_pct=metrics.get("slippage_drag_pct", 0),
            gross_profit=metrics.get("gross_profit", 0),
            gross_loss=metrics.get("gross_loss", 0),
            avg_win=metrics.get("avg_win", 0),
            avg_loss=metrics.get("avg_loss", 0),
            largest_win=metrics.get("largest_win", 0),
            largest_loss=metrics.get("largest_loss", 0),
            winning_trades=metrics.get("winning_trades", 0),
            losing_trades=metrics.get("losing_trades", 0),
        )
        await self.store.write_metrics(metrics_record)
        
        # Store trades (limit to 1000)
        for trade in results["trades"][:1000]:
            trade_record = BacktestTradeRecord(
                run_id=run_id,
                ts=trade["ts"],
                symbol=trade["symbol"],
                side=trade["side"],
                size=trade["size"],
                entry_price=trade["entry_price"],
                exit_price=trade["exit_price"],
                pnl=trade["pnl"],
                entry_fee=trade["entry_fee"],
                exit_fee=trade["exit_fee"],
                total_fees=trade["total_fees"],
                entry_slippage_bps=trade["entry_slippage_bps"],
                exit_slippage_bps=trade["exit_slippage_bps"],
            )
            await self.store.write_trade(trade_record)
        
        # Store equity curve (limit to 500 points)
        for point in results["equity_curve"][:500]:
            curve_record = BacktestEquityPoint(
                run_id=run_id,
                ts=point["ts"],
                equity=point["equity"],
                realized_pnl=point["realized_pnl"],
                open_positions=point["open_positions"],
            )
            await self.store.write_equity_point(curve_record)
    
    async def _update_status(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        status: str,
        config: Dict[str, Any],
        started_at: str,
        finished_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update backtest run status."""
        record = BacktestRunRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            config=config,
            name=config.get("name"),
            symbol=config.get("symbol"),
            start_date=config.get("start_date"),
            end_date=config.get("end_date"),
            error_message=error_message,
        )
        await self.store.write_run(record)
    
    async def close(self):
        """Close database connections."""
        if self._timescale_pool:
            await self._timescale_pool.close()
            self._timescale_pool = None


async def create_simple_executor_function(platform_pool, config: Optional[SimpleExecutorConfig] = None):
    """Create an executor function for use with BacktestJobQueue.
    
    Args:
        platform_pool: asyncpg connection pool for platform_db
        config: Optional executor configuration
        
    Returns:
        An async function with signature (run_id: str, config: dict) -> None
    """
    executor = SimpleBacktestExecutor(platform_pool, config)
    
    async def execute_backtest(run_id: str, job_config: Dict[str, Any]) -> None:
        """Execute a backtest job."""
        tenant_id = job_config.get("tenant_id", "default")
        bot_id = job_config.get("bot_id", "default")
        backtest_config = job_config.get("config", job_config)
        
        result = await executor.execute(
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
            config=backtest_config,
        )
        
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error", "Backtest failed"))
    
    return execute_backtest
