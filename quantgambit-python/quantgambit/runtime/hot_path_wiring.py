"""
Hot path wiring - connects WebSocket feeds to HotPath and ExecutionGateway.

This module provides:
1. BybitExecutionGateway - submits ExecutionIntents via REST
2. HotPathManager - orchestrates WS feeds, HotPath, and execution

Usage:
    manager = HotPathManager(config)
    await manager.start()
    
    # Process until stopped
    await manager.run_until_stopped()
    
    await manager.stop()
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from quantgambit.core.clock import Clock, WallClock
from quantgambit.core.book.types import OrderBook, BookUpdate
from quantgambit.core.book.guardian import BookGuardian, GuardianConfig
from quantgambit.core.risk.kill_switch import KillSwitch
from quantgambit.core.latency import LatencyTracker
from quantgambit.core.decision import (
    ExecutionIntent,
    Position,
    FeatureFrameBuilder,
    ModelRunner,
    Calibrator,
    EdgeTransform,
    VolatilityEstimator,
    RiskMapper,
    ExecutionPolicy,
)
from quantgambit.core.decision.impl.feature_builder import DefaultFeatureFrameBuilder
from quantgambit.core.decision.impl.model_runner import PassthroughModelRunner
from quantgambit.core.decision.impl.calibrator import IdentityCalibrator
from quantgambit.core.decision.impl.edge_transform import LinearEdgeTransform
from quantgambit.core.decision.impl.vol_estimator import SimpleVolatilityEstimator
from quantgambit.core.decision.impl.risk_mapper import FixedSizeRiskMapper
from quantgambit.core.decision.impl.execution_policy import MarketExecutionPolicy

from quantgambit.io.sidechannel import SideChannelPublisher, NullSideChannel
from quantgambit.io.adapters.bybit.ws_client import BybitWSClient, BybitWSConfig
from quantgambit.io.adapters.bybit.rest_client import BybitRESTClient, BybitRESTConfig
from quantgambit.io.adapters.bybit.book_sync import BybitBookSync
from quantgambit.runtime.hot_path import HotPath, HotPathConfig, ExecutionGateway

logger = logging.getLogger(__name__)


@dataclass
class HotPathManagerConfig:
    """Configuration for HotPathManager."""
    
    # Exchange credentials
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = False
    
    # Symbols to trade
    symbols: List[str] = field(default_factory=list)
    
    # Hot path settings
    max_decision_age_ms: float = 500.0
    staleness_threshold_ms: float = 1000.0
    allow_entries: bool = True
    allow_exits: bool = True
    
    # Execution settings
    order_timeout_s: float = 10.0
    max_retries: int = 3
    
    # Book settings
    orderbook_depth: int = 50
    
    # Account
    initial_equity: float = 10000.0


class BybitExecutionGateway(ExecutionGateway):
    """
    ExecutionGateway implementation using Bybit REST API.
    
    Converts ExecutionIntents to Bybit orders and submits them.
    """
    
    def __init__(
        self,
        rest_client: BybitRESTClient,
        latency_tracker: Optional[LatencyTracker] = None,
    ):
        """Initialize gateway."""
        self._client = rest_client
        self._latency = latency_tracker or LatencyTracker()
        self._pending_orders: Dict[str, ExecutionIntent] = {}
    
    async def submit_intent(self, intent: ExecutionIntent) -> bool:
        """
        Submit execution intent to Bybit.
        
        Args:
            intent: ExecutionIntent to submit
            
        Returns:
            True if order accepted by exchange
        """
        timer = self._latency.start_timer("order_submit")
        
        try:
            # Map intent to Bybit params
            side = "Buy" if intent.side.lower() == "buy" else "Sell"
            order_type = "Limit" if intent.price else "Market"
            
            result = await self._client.place_order(
                symbol=intent.symbol,
                side=side,
                qty=intent.qty,
                order_type=order_type,
                price=intent.price,
                client_order_id=intent.client_order_id,
                reduce_only=intent.reduce_only,
                stop_loss=intent.sl_price,
                take_profit=intent.tp_price,
            )
            
            order_id = result.get("orderId")
            if order_id:
                self._pending_orders[intent.client_order_id] = intent
                logger.info(
                    f"Order submitted: {intent.client_order_id} -> {order_id} "
                    f"({intent.side} {intent.qty} {intent.symbol})"
                )
                return True
            
            logger.warning(f"Order submission returned no orderId: {result}")
            return False
            
        except Exception as e:
            logger.error(f"Order submission failed: {e}", exc_info=True)
            return False
        finally:
            self._latency.end_timer("order_submit", timer)
    
    async def cancel_all(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders."""
        try:
            result = await self._client.cancel_all_orders(symbol)
            canceled = result.get("list", [])
            count = len(canceled)
            logger.info(f"Canceled {count} orders" + (f" for {symbol}" if symbol else ""))
            return count
        except Exception as e:
            logger.error(f"Cancel all failed: {e}")
            return 0
    
    async def flatten_position(self, symbol: str) -> bool:
        """Flatten position for symbol."""
        try:
            result = await self._client.close_position(symbol)
            if result.get("orderId"):
                logger.info(f"Flatten order submitted for {symbol}")
                return True
            return False
        except Exception as e:
            logger.error(f"Flatten failed for {symbol}: {e}")
            return False
    
    def on_order_update(self, update: Dict[str, Any]) -> None:
        """Handle order update from WebSocket."""
        client_order_id = update.get("client_order_id")
        status = update.get("canonical_state", "")
        
        if client_order_id and status in {"filled", "canceled", "rejected"}:
            if client_order_id in self._pending_orders:
                intent = self._pending_orders.pop(client_order_id)
                logger.debug(f"Order {client_order_id} terminal: {status}")


class HotPathManager:
    """
    Orchestrates the hot path with WebSocket feeds and execution.
    
    Connects:
    - BybitWSClient (market data + private updates)
    - BookGuardian (book integrity)
    - HotPath (decision pipeline)
    - BybitExecutionGateway (order submission)
    
    Usage:
        manager = HotPathManager(config)
        
        # Optional: set custom pipeline components
        manager.set_model_runner(my_model)
        
        await manager.start()
        await manager.run_until_stopped()
        await manager.stop()
    """
    
    def __init__(
        self,
        config: HotPathManagerConfig,
        clock: Optional[Clock] = None,
        publisher: Optional[SideChannelPublisher] = None,
        kill_switch: Optional[KillSwitch] = None,
    ):
        """Initialize manager."""
        self._config = config
        self._clock = clock or WallClock()
        self._publisher = publisher or NullSideChannel()
        self._kill_switch = kill_switch or KillSwitch(self._clock)
        self._latency = LatencyTracker()
        
        # Components (initialized in start())
        self._ws_client: Optional[BybitWSClient] = None
        self._rest_client: Optional[BybitRESTClient] = None
        self._book_guardian: Optional[BookGuardian] = None
        self._hot_path: Optional[HotPath] = None
        self._gateway: Optional[BybitExecutionGateway] = None
        
        # Single book sync instance (handles all symbols)
        self._book_sync: Optional[BybitBookSync] = None
        
        # Pipeline components (can be overridden)
        self._feature_builder: Optional[FeatureFrameBuilder] = None
        self._model_runner: Optional[ModelRunner] = None
        self._calibrator: Optional[Calibrator] = None
        self._edge_transform: Optional[EdgeTransform] = None
        self._vol_estimator: Optional[VolatilityEstimator] = None
        self._risk_mapper: Optional[RiskMapper] = None
        self._exec_policy: Optional[ExecutionPolicy] = None
        
        # State
        self._running = False
        self._account_equity = config.initial_equity
        self._account_margin = config.initial_equity
    
    # Pipeline component setters
    def set_feature_builder(self, builder: FeatureFrameBuilder) -> None:
        self._feature_builder = builder
    
    def set_model_runner(self, runner: ModelRunner) -> None:
        self._model_runner = runner
    
    def set_calibrator(self, calibrator: Calibrator) -> None:
        self._calibrator = calibrator
    
    def set_edge_transform(self, transform: EdgeTransform) -> None:
        self._edge_transform = transform
    
    def set_vol_estimator(self, estimator: VolatilityEstimator) -> None:
        self._vol_estimator = estimator
    
    def set_risk_mapper(self, mapper: RiskMapper) -> None:
        self._risk_mapper = mapper
    
    def set_exec_policy(self, policy: ExecutionPolicy) -> None:
        self._exec_policy = policy
    
    async def start(self) -> None:
        """Start all components."""
        logger.info("Starting HotPathManager...")
        
        # Initialize REST client
        rest_config = BybitRESTConfig(
            api_key=self._config.api_key,
            api_secret=self._config.api_secret,
            base_url="https://api-testnet.bybit.com" if self._config.testnet else "https://api.bybit.com",
        )
        self._rest_client = BybitRESTClient(self._clock, rest_config)
        await self._rest_client.start()
        
        # Initialize execution gateway
        self._gateway = BybitExecutionGateway(self._rest_client, self._latency)
        
        # Initialize book sync (single instance handles all symbols)
        self._book_sync = BybitBookSync(
            max_stale_sec=self._config.staleness_threshold_ms / 1000.0,
        )
        
        # Initialize book guardian with the sync
        guardian_config = GuardianConfig(
            max_book_age_sec=self._config.staleness_threshold_ms / 1000.0,
        )
        self._book_guardian = BookGuardian(
            book_sync=self._book_sync,
            clock=self._clock,
            config=guardian_config,
        )
        
        # Build pipeline components (use defaults if not set)
        feature_builder = self._feature_builder or DefaultFeatureFrameBuilder()
        model_runner = self._model_runner or PassthroughModelRunner()
        calibrator = self._calibrator or IdentityCalibrator()
        edge_transform = self._edge_transform or LinearEdgeTransform()
        vol_estimator = self._vol_estimator or SimpleVolatilityEstimator()
        risk_mapper = self._risk_mapper or FixedSizeRiskMapper()
        exec_policy = self._exec_policy or MarketExecutionPolicy()
        
        # Initialize hot path
        hot_path_config = HotPathConfig(
            max_decision_age_ms=self._config.max_decision_age_ms,
            staleness_threshold_ms=self._config.staleness_threshold_ms,
            allow_entries=self._config.allow_entries,
            allow_exits=self._config.allow_exits,
        )
        
        self._hot_path = HotPath(
            clock=self._clock,
            book_guardian=self._book_guardian,
            kill_switch=self._kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=self._gateway,
            publisher=self._publisher,
            config=hot_path_config,
            latency_tracker=self._latency,
        )
        
        # Initialize WebSocket client
        ws_config = BybitWSConfig(
            api_key=self._config.api_key,
            api_secret=self._config.api_secret,
            public_url="wss://stream-testnet.bybit.com/v5/public/linear" if self._config.testnet else "wss://stream.bybit.com/v5/public/linear",
            private_url="wss://stream-testnet.bybit.com/v5/private" if self._config.testnet else "wss://stream.bybit.com/v5/private",
            symbols=self._config.symbols,
            orderbook_depth=self._config.orderbook_depth,
        )
        
        self._ws_client = BybitWSClient(self._clock, ws_config, self._publisher)
        
        # Wire up callbacks
        self._ws_client.on_orderbook = self._handle_orderbook
        self._ws_client.on_trade = self._handle_trade
        self._ws_client.on_order_update = self._handle_order_update
        self._ws_client.on_position_update = self._handle_position_update
        self._ws_client.on_wallet_update = self._handle_wallet_update
        
        # Fetch initial state
        await self._fetch_initial_state()
        
        # Connect WebSocket
        await self._ws_client.connect()
        
        self._running = True
        logger.info("HotPathManager started")
    
    async def stop(self) -> None:
        """Stop all components."""
        logger.info("Stopping HotPathManager...")
        self._running = False
        
        if self._ws_client:
            await self._ws_client.disconnect()
        
        if self._rest_client:
            await self._rest_client.stop()
        
        logger.info("HotPathManager stopped")
    
    async def run_until_stopped(self) -> None:
        """Run until stop() is called."""
        while self._running:
            await asyncio.sleep(1)
    
    async def _fetch_initial_state(self) -> None:
        """Fetch initial account and position state."""
        try:
            # Fetch wallet balance
            wallet = await self._rest_client.get_wallet_balance()
            self._account_equity = wallet.get("equity", self._config.initial_equity)
            self._account_margin = wallet.get("available_balance", self._account_equity)
            
            self._hot_path.update_account(self._account_equity, self._account_margin)
            logger.info(f"Initial equity: ${self._account_equity:.2f}")
            
            # Fetch positions
            for symbol in self._config.symbols:
                positions = await self._rest_client.get_positions(symbol)
                if positions:
                    pos = positions[0]
                    size = pos.get("size", 0)
                    if abs(size) > 0.0001:
                        position = Position(
                            size=size,
                            entry_price=pos.get("entry_price"),
                            unrealized_pnl=pos.get("unrealized_pnl", 0),
                        )
                        self._hot_path.update_position(symbol, position)
                        logger.info(f"Initial position {symbol}: {size}")
                        
        except Exception as e:
            logger.error(f"Failed to fetch initial state: {e}")
    
    async def _handle_orderbook(self, data: Dict[str, Any]) -> None:
        """Handle orderbook update from WebSocket."""
        timer = self._latency.start_timer("ws_to_hotpath")
        
        try:
            # Parse message using BybitBookSync
            symbol, msg_type, bids, asks, sequence, timestamp = BybitBookSync.parse_message(data)
            
            if not symbol or symbol not in self._config.symbols:
                return
            
            # Create book update for the guardian (which handles sync internally)
            from quantgambit.core.book.types import Level
            
            # Convert raw bid/ask lists to Level objects
            bid_levels = [Level(price=float(b[0]), size=float(b[1])) for b in bids]
            ask_levels = [Level(price=float(a[0]), size=float(a[1])) for a in asks]
            
            update = BookUpdate(
                symbol=symbol,
                bids=bid_levels,
                asks=ask_levels,
                sequence_id=sequence,
                timestamp=timestamp,
                is_snapshot=(msg_type == "snapshot"),
            )
            
            # Feed to hot path (guardian handles sync + quoteability)
            self._hot_path.on_book_update(symbol, update)
            
        except Exception as e:
            logger.error(f"Error handling orderbook: {e}", exc_info=True)
        finally:
            self._latency.end_timer("ws_to_hotpath", timer)
    
    async def _handle_trade(self, data: Dict[str, Any]) -> None:
        """Handle trade update from WebSocket."""
        try:
            topic = data.get("topic", "")
            # Extract symbol from topic: "publicTrade.BTCUSDT"
            parts = topic.split(".")
            if len(parts) < 2:
                return
            symbol = parts[1]
            
            for trade in data.get("data", []):
                self._hot_path.on_trade(symbol, {
                    "price": float(trade.get("p", 0)),
                    "size": float(trade.get("v", 0)),
                    "side": trade.get("S", "").lower(),
                    "timestamp": int(trade.get("T", 0)),
                })
                
        except Exception as e:
            logger.error(f"Error handling trade: {e}", exc_info=True)
    
    async def _handle_order_update(self, update: Dict[str, Any]) -> None:
        """Handle order update from WebSocket."""
        try:
            # Forward to gateway
            if self._gateway:
                self._gateway.on_order_update(update)
            
            # Update hot path pending state
            client_order_id = update.get("client_order_id")
            status = update.get("canonical_state", "")
            filled_qty = update.get("filled_qty", 0)
            
            if client_order_id:
                self._hot_path.on_order_update(client_order_id, status, filled_qty)
            
            logger.debug(f"Order update: {client_order_id} -> {status}")
            
        except Exception as e:
            logger.error(f"Error handling order update: {e}", exc_info=True)
    
    async def _handle_position_update(self, update: Dict[str, Any]) -> None:
        """Handle position update from WebSocket."""
        try:
            symbol = update.get("symbol")
            if not symbol:
                return
            
            size = update.get("size", 0)
            entry_price = update.get("entry_price")
            unrealized_pnl = update.get("unrealized_pnl", 0)
            
            if abs(size) > 0.0001:
                position = Position(
                    size=size,
                    entry_price=entry_price,
                    unrealized_pnl=unrealized_pnl,
                )
                self._hot_path.update_position(symbol, position)
            else:
                # Position closed
                self._hot_path.update_position(symbol, Position(size=0))
            
            logger.debug(f"Position update: {symbol} -> {size}")
            
        except Exception as e:
            logger.error(f"Error handling position update: {e}", exc_info=True)
    
    async def _handle_wallet_update(self, update: Dict[str, Any]) -> None:
        """Handle wallet update from WebSocket."""
        try:
            equity = update.get("equity", 0)
            available = update.get("available_balance", 0)
            
            if equity > 0:
                self._account_equity = equity
                self._account_margin = available if available > 0 else equity
                self._hot_path.update_account(self._account_equity, self._account_margin)
                
                logger.debug(f"Wallet update: equity=${equity:.2f}")
                
        except Exception as e:
            logger.error(f"Error handling wallet update: {e}", exc_info=True)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        stats = {
            "running": self._running,
            "ws_connected": self._ws_client.is_connected() if self._ws_client else False,
            "account_equity": self._account_equity,
            "account_margin": self._account_margin,
        }
        
        if self._hot_path:
            stats["hot_path"] = self._hot_path.stats()
        
        return stats
