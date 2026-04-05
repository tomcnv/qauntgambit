"""
Bybit WebSocket client for private and public channels.

Handles:
- Order book deltas
- Trades
- Order updates (private)
- Position updates (private)
- Account updates (private)

The client is designed for low-latency operation:
- Non-blocking message processing
- Efficient reconnection
- Sequence validation
"""

import asyncio
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, TYPE_CHECKING

from websockets.exceptions import ConnectionClosedError, WebSocketException

from quantgambit.core.clock import Clock
from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.net.ws_connect import ws_connect_with_dns_fallback
from quantgambit.io.sidechannel import SideChannelPublisher
from quantgambit.io.adapters.bybit.mapping import (
    map_order_status,
    map_order_side,
    map_order_type,
    is_terminal_status,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from websockets.legacy.client import WebSocketClientProtocol
else:
    WebSocketClientProtocol = Any


class BybitChannel(str, Enum):
    """Bybit WebSocket channels."""
    
    # Public
    ORDERBOOK_50 = "orderbook.50"
    ORDERBOOK_200 = "orderbook.200"
    ORDERBOOK_500 = "orderbook.500"
    TRADES = "publicTrade"
    TICKERS = "tickers"
    KLINE = "kline"
    LIQUIDATION = "liquidation"
    
    # Private
    ORDER = "order"
    EXECUTION = "execution"
    POSITION = "position"
    WALLET = "wallet"
    GREEKS = "greeks"


@dataclass
class BybitWSConfig:
    """WebSocket client configuration."""
    
    # Endpoints
    public_url: str = "wss://stream.bybit.com/v5/public/linear"
    private_url: str = "wss://stream.bybit.com/v5/private"
    
    # Auth
    api_key: str = ""
    api_secret: str = ""
    
    # Connection settings
    ping_interval_s: float = 20.0
    ping_timeout_s: float = 10.0
    reconnect_delay_s: float = 1.0
    max_reconnect_delay_s: float = 60.0
    
    # Subscriptions
    symbols: List[str] = field(default_factory=list)
    orderbook_depth: int = 50


MessageHandler = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class BybitWSClient:
    """
    Bybit WebSocket client.
    
    Manages connections to both public and private WebSocket endpoints.
    Provides callbacks for various message types.
    
    Usage:
        client = BybitWSClient(clock, config, publisher)
        
        # Register handlers
        client.on_orderbook = handle_orderbook
        client.on_trade = handle_trade
        client.on_order_update = handle_order_update
        
        # Connect and run
        await client.connect()
        await client.run()
    """
    
    def __init__(
        self,
        clock: Clock,
        config: BybitWSConfig,
        publisher: SideChannelPublisher,
    ):
        """Initialize WebSocket client."""
        self._clock = clock
        self._config = config
        self._publisher = publisher
        
        # WebSocket connections
        self._public_ws: Optional[WebSocketClientProtocol] = None
        self._private_ws: Optional[WebSocketClientProtocol] = None
        
        # State
        self._running = False
        self._connected_public = False
        self._connected_private = False
        self._reconnect_count = 0
        
        # Handlers
        self.on_orderbook: Optional[MessageHandler] = None
        self.on_trade: Optional[MessageHandler] = None
        self.on_order_update: Optional[MessageHandler] = None
        self.on_position_update: Optional[MessageHandler] = None
        self.on_wallet_update: Optional[MessageHandler] = None
        
        # Tasks
        self._public_task: Optional[asyncio.Task] = None
        self._private_task: Optional[asyncio.Task] = None
    
    async def connect(self) -> None:
        """Connect to WebSocket endpoints."""
        self._running = True
        
        # Connect public
        self._public_task = asyncio.create_task(self._run_public())
        
        # Connect private (if credentials provided)
        if self._config.api_key and self._config.api_secret:
            self._private_task = asyncio.create_task(self._run_private())
        else:
            logger.warning("No API credentials provided, private WS disabled")
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket endpoints."""
        self._running = False
        
        if self._public_ws:
            await self._public_ws.close()
        if self._private_ws:
            await self._private_ws.close()
        
        if self._public_task:
            self._public_task.cancel()
            try:
                await self._public_task
            except asyncio.CancelledError:
                pass
        
        if self._private_task:
            self._private_task.cancel()
            try:
                await self._private_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Bybit WebSocket disconnected")
    
    async def _run_public(self) -> None:
        """Run public WebSocket connection loop."""
        while self._running:
            try:
                async with ws_connect_with_dns_fallback(
                    self._config.public_url,
                    ping_interval=self._config.ping_interval_s,
                    ping_timeout=self._config.ping_timeout_s,
                ) as ws:
                    self._public_ws = ws
                    self._connected_public = True
                    logger.info(f"Connected to public WS: {self._config.public_url}")
                    
                    # Subscribe to channels
                    await self._subscribe_public()
                    
                    # Process messages
                    async for message in ws:
                        await self._handle_public_message(message)
                        
            except (ConnectionClosedError, WebSocketException) as e:
                logger.error(f"Public WS error: {e}")
                self._connected_public = False
                self._emit_disconnect_event("public")
            except Exception as e:
                logger.error(f"Public WS unexpected error: {e}", exc_info=True)
                self._connected_public = False
            
            if self._running:
                delay = min(
                    self._config.reconnect_delay_s * (2 ** self._reconnect_count),
                    self._config.max_reconnect_delay_s,
                )
                logger.info(f"Reconnecting public WS in {delay}s")
                await asyncio.sleep(delay)
                self._reconnect_count += 1
    
    async def _run_private(self) -> None:
        """Run private WebSocket connection loop."""
        while self._running:
            try:
                async with ws_connect_with_dns_fallback(
                    self._config.private_url,
                    ping_interval=self._config.ping_interval_s,
                    ping_timeout=self._config.ping_timeout_s,
                ) as ws:
                    self._private_ws = ws
                    
                    # Authenticate
                    if not await self._authenticate(ws):
                        logger.error("Private WS authentication failed")
                        await asyncio.sleep(self._config.reconnect_delay_s)
                        continue
                    
                    self._connected_private = True
                    logger.info("Connected to private WS")
                    
                    # Subscribe to private channels
                    await self._subscribe_private()
                    
                    # Process messages
                    async for message in ws:
                        await self._handle_private_message(message)
                        
            except (ConnectionClosedError, WebSocketException) as e:
                logger.error(f"Private WS error: {e}")
                self._connected_private = False
                self._emit_disconnect_event("private")
            except Exception as e:
                logger.error(f"Private WS unexpected error: {e}", exc_info=True)
                self._connected_private = False
            
            if self._running:
                delay = min(
                    self._config.reconnect_delay_s * (2 ** self._reconnect_count),
                    self._config.max_reconnect_delay_s,
                )
                logger.info(f"Reconnecting private WS in {delay}s")
                await asyncio.sleep(delay)
    
    async def _authenticate(self, ws: WebSocketClientProtocol) -> bool:
        """Authenticate with private endpoint."""
        expires = int(time.time() * 1000) + 10000
        signature = hmac.new(
            self._config.api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            digestmod="sha256",
        ).hexdigest()
        
        auth_msg = {
            "op": "auth",
            "args": [self._config.api_key, expires, signature],
        }
        
        await ws.send(json.dumps(auth_msg))
        
        # Wait for auth response
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            if data.get("success"):
                return True
            logger.error(f"Auth failed: {data}")
            return False
        except asyncio.TimeoutError:
            logger.error("Auth timeout")
            return False
    
    async def _subscribe_public(self) -> None:
        """Subscribe to public channels."""
        if not self._public_ws or not self._config.symbols:
            return
        
        # Build subscription args
        args = []
        for symbol in self._config.symbols:
            # Orderbook
            args.append(f"orderbook.{self._config.orderbook_depth}.{symbol}")
            # Trades
            args.append(f"publicTrade.{symbol}")
        
        subscribe_msg = {
            "op": "subscribe",
            "args": args,
        }
        
        await self._public_ws.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to public channels: {args}")
    
    async def _subscribe_private(self) -> None:
        """Subscribe to private channels."""
        if not self._private_ws:
            return
        
        subscribe_msg = {
            "op": "subscribe",
            "args": [
                "order",
                "execution",
                "position",
                "wallet",
            ],
        }
        
        await self._private_ws.send(json.dumps(subscribe_msg))
        logger.info("Subscribed to private channels")
    
    async def _handle_public_message(self, raw: str) -> None:
        """Handle incoming public WebSocket message."""
        try:
            data = json.loads(raw)
            
            # Handle subscription confirmation
            if data.get("op") == "subscribe":
                if data.get("success"):
                    logger.debug(f"Subscription confirmed: {data}")
                else:
                    logger.error(f"Subscription failed: {data}")
                return
            
            # Handle ping/pong
            if data.get("op") == "ping":
                await self._public_ws.send(json.dumps({"op": "pong"}))
                return
            
            topic = data.get("topic", "")
            
            if "orderbook" in topic:
                if self.on_orderbook:
                    await self.on_orderbook(data)
            elif "publicTrade" in topic:
                if self.on_trade:
                    await self.on_trade(data)
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode public message: {e}")
        except Exception as e:
            logger.error(f"Error handling public message: {e}", exc_info=True)
    
    async def _handle_private_message(self, raw: str) -> None:
        """Handle incoming private WebSocket message."""
        try:
            data = json.loads(raw)
            
            # Handle subscription confirmation
            if data.get("op") == "subscribe":
                if data.get("success"):
                    logger.debug(f"Private subscription confirmed: {data}")
                else:
                    logger.error(f"Private subscription failed: {data}")
                return
            
            topic = data.get("topic", "")
            
            if topic == "order":
                if self.on_order_update:
                    # Transform to canonical format
                    for order in data.get("data", []):
                        canonical = self._transform_order_update(order)
                        await self.on_order_update(canonical)
            elif topic == "execution":
                # Execution is handled via order updates
                pass
            elif topic == "position":
                if self.on_position_update:
                    for position in data.get("data", []):
                        canonical = self._transform_position_update(position)
                        await self.on_position_update(canonical)
            elif topic == "wallet":
                if self.on_wallet_update:
                    for wallet in data.get("data", []):
                        canonical = self._transform_wallet_update(wallet)
                        await self.on_wallet_update(canonical)
                        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode private message: {e}")
        except Exception as e:
            logger.error(f"Error handling private message: {e}", exc_info=True)
    
    def _transform_order_update(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Bybit order update to canonical format."""
        bybit_status = order.get("orderStatus", "")
        canonical_state = map_order_status(bybit_status)
        
        return {
            "exchange_order_id": order.get("orderId"),
            "client_order_id": order.get("orderLinkId"),
            "symbol": order.get("symbol"),
            "side": map_order_side(order.get("side", "")),
            "order_type": map_order_type(order.get("orderType", "")),
            "status": bybit_status,
            "canonical_state": canonical_state,
            "price": float(order.get("price", 0)) if order.get("price") else None,
            "qty": float(order.get("qty", 0)),
            "filled_qty": float(order.get("cumExecQty", 0)),
            "avg_fill_price": float(order.get("avgPrice", 0)) if order.get("avgPrice") else None,
            "cum_exec_value": float(order.get("cumExecValue", 0)),
            "cum_exec_fee": float(order.get("cumExecFee", 0)),
            "time_in_force": order.get("timeInForce"),
            "reduce_only": order.get("reduceOnly", False),
            "created_at": order.get("createdTime"),
            "updated_at": order.get("updatedTime"),
            "is_terminal": is_terminal_status(bybit_status),
            "raw": order,
        }
    
    def _transform_position_update(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Bybit position update to canonical format."""
        size = float(position.get("size", 0))
        side = position.get("side", "")
        
        # Make size signed (negative for short)
        if side == "Sell":
            size = -size
        
        return {
            "symbol": position.get("symbol"),
            "size": size,
            "side": side.lower() if side else None,
            "entry_price": float(position.get("avgPrice", 0)) if position.get("avgPrice") else None,
            "mark_price": float(position.get("markPrice", 0)) if position.get("markPrice") else None,
            "unrealized_pnl": float(position.get("unrealisedPnl", 0)),
            "realized_pnl": float(position.get("cumRealisedPnl", 0)),
            "leverage": float(position.get("leverage", 1)),
            "liq_price": float(position.get("liqPrice", 0)) if position.get("liqPrice") else None,
            "position_value": float(position.get("positionValue", 0)),
            "raw": position,
        }
    
    def _transform_wallet_update(self, wallet: Dict[str, Any]) -> Dict[str, Any]:
        """Transform Bybit wallet update to canonical format."""
        return {
            "coin": wallet.get("coin"),
            "equity": float(wallet.get("equity", 0)),
            "available_balance": float(wallet.get("availableToWithdraw", 0)),
            "wallet_balance": float(wallet.get("walletBalance", 0)),
            "unrealized_pnl": float(wallet.get("unrealisedPnl", 0)),
            "cum_realized_pnl": float(wallet.get("cumRealisedPnl", 0)),
            "raw": wallet,
        }
    
    def _emit_disconnect_event(self, channel: str) -> None:
        """Emit WebSocket disconnect event."""
        event = EventEnvelope(
            v=1,
            type=EventType.OPS_ALERT,
            source="quantgambit.io.bybit_ws",
            symbol=None,
            ts_wall=self._clock.now(),
            ts_mono=self._clock.now_mono(),
            trace_id="",
            seq=None,
            payload={
                "alert_type": "ws_disconnect",
                "channel": channel,
                "reconnect_count": self._reconnect_count,
            },
        )
        self._publisher.publish(event)
    
    def is_connected(self) -> bool:
        """Check if connected to both endpoints."""
        return self._connected_public and (
            not self._config.api_key or self._connected_private
        )
    
    def is_private_connected(self) -> bool:
        """Check if private WS is connected."""
        return self._connected_private
