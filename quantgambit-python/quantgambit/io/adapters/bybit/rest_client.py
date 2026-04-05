"""
Bybit REST API client for order and position management.

Handles:
- Order placement (market, limit, bracket)
- Order cancellation
- Position queries
- Account queries

Designed for:
- Idempotent operations with client order IDs
- Retry logic with exponential backoff
- Error classification
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

from quantgambit.core.clock import Clock
from quantgambit.io.adapters.bybit.mapping import (
    get_error_message,
    is_position_zero_error,
    is_insufficient_balance_error,
)

logger = logging.getLogger(__name__)


@dataclass
class BybitRESTConfig:
    """REST client configuration."""
    
    # Endpoints
    base_url: str = "https://api.bybit.com"
    
    # Auth
    api_key: str = ""
    api_secret: str = ""
    
    # Request settings
    recv_window: int = 5000
    timeout_s: float = 10.0
    
    # Retry settings
    max_retries: int = 3
    retry_delay_s: float = 0.5
    
    # Category (linear = USDT perpetual)
    category: str = "linear"


class BybitRESTError(Exception):
    """Bybit REST API error."""
    
    def __init__(self, code: int, message: str, raw_response: Dict[str, Any]):
        super().__init__(f"Bybit error {code}: {message}")
        self.code = code
        self.message = message
        self.raw_response = raw_response
    
    def is_position_zero(self) -> bool:
        """Check if error indicates no position."""
        return is_position_zero_error(self.code)
    
    def is_insufficient_balance(self) -> bool:
        """Check if error is balance-related."""
        return is_insufficient_balance_error(self.code)


class BybitRESTClient:
    """
    Bybit REST API client.
    
    Provides methods for order and position management.
    
    Usage:
        client = BybitRESTClient(clock, config)
        
        # Place market order
        result = await client.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            order_type="Market",
        )
        
        # Get positions
        positions = await client.get_positions()
    """
    
    def __init__(self, clock: Clock, config: BybitRESTConfig):
        """Initialize REST client."""
        self._clock = clock
        self._config = config
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def start(self) -> None:
        """Start the client session."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._config.timeout_s)
            self._session = aiohttp.ClientSession(timeout=timeout)
    
    async def stop(self) -> None:
        """Stop the client session."""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        sign: bool = True,
    ) -> Dict[str, Any]:
        """
        Make authenticated request to Bybit API.
        
        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint (e.g., /v5/order/create)
            params: Request parameters
            sign: Whether to sign the request
            
        Returns:
            Response data
            
        Raises:
            BybitRESTError: On API error
        """
        if not self._session:
            await self.start()
        
        url = f"{self._config.base_url}{endpoint}"
        params = params or {}
        
        headers = {}
        if sign:
            timestamp = str(int(time.time() * 1000))
            headers = self._sign_request(timestamp, params, method)
        
        last_error = None
        for attempt in range(self._config.max_retries):
            try:
                if method == "GET":
                    async with self._session.get(url, params=params, headers=headers) as resp:
                        data = await resp.json()
                else:  # POST
                    async with self._session.post(url, json=params, headers=headers) as resp:
                        data = await resp.json()
                
                # Check for API error
                ret_code = data.get("retCode", 0)
                if ret_code != 0:
                    raise BybitRESTError(
                        code=ret_code,
                        message=data.get("retMsg", get_error_message(ret_code)),
                        raw_response=data,
                    )
                
                return data.get("result", {})
                
            except aiohttp.ClientError as e:
                logger.warning(f"Request error (attempt {attempt + 1}): {e}")
                last_error = e
                if attempt < self._config.max_retries - 1:
                    await asyncio.sleep(self._config.retry_delay_s * (2 ** attempt))
            except BybitRESTError:
                raise
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                last_error = e
                if attempt < self._config.max_retries - 1:
                    await asyncio.sleep(self._config.retry_delay_s * (2 ** attempt))
        
        raise last_error or Exception("Request failed")
    
    def _sign_request(self, timestamp: str, params: Dict[str, Any], method: str) -> Dict[str, str]:
        """Generate authentication headers.

        Bybit V5 signing expects:
        - GET: query string (sorted key=value pairs)
        - POST: JSON body string
        """
        recv_window = str(self._config.recv_window)

        if method == "GET":
            # Build sorted query string for signature
            if params:
                param_str = "&".join(
                    f"{key}={str(params[key])}" for key in sorted(params.keys())
                )
            else:
                param_str = ""
        else:
            param_str = json.dumps(params, separators=(',', ':')) if params else ""
        
        sign_str = f"{timestamp}{self._config.api_key}{recv_window}{param_str}"
        signature = hmac.new(
            self._config.api_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        
        return {
            "X-BAPI-API-KEY": self._config.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json",
        }
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "Market",
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place an order.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            side: Order side (Buy, Sell)
            qty: Order quantity
            order_type: Order type (Market, Limit)
            price: Limit price (required for Limit orders)
            client_order_id: Client order ID for idempotency
            reduce_only: Whether to reduce position only
            time_in_force: Time in force (GTC, IOC, FOK, PostOnly)
            stop_loss: Stop loss price
            take_profit: Take profit price
            
        Returns:
            Order result with orderId
        """
        params = {
            "category": self._config.category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
        }
        
        if client_order_id:
            params["orderLinkId"] = client_order_id
        else:
            params["orderLinkId"] = f"qg_{uuid.uuid4().hex[:16]}"
        
        if price is not None:
            params["price"] = str(price)
        
        if reduce_only:
            params["reduceOnly"] = True
        
        if order_type != "Market":
            params["timeInForce"] = time_in_force
        
        if stop_loss is not None:
            params["stopLoss"] = str(stop_loss)
        
        if take_profit is not None:
            params["takeProfit"] = str(take_profit)
        
        return await self._request("POST", "/v5/order/create", params)
    
    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            symbol: Trading symbol
            order_id: Exchange order ID
            client_order_id: Client order ID
            
        Returns:
            Cancel result
        """
        params = {
            "category": self._config.category,
            "symbol": symbol,
        }
        
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["orderLinkId"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id required")
        
        return await self._request("POST", "/v5/order/cancel", params)
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancel all open orders.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Cancel result with verified canceled orders and any remaining survivors
        """
        params = {"category": self._config.category}

        if symbol:
            params["symbol"] = symbol
        elif self._config.category == "linear":
            # Bybit requires either symbol or settleCoin for position list
            params["settleCoin"] = "USDT"

        result = await self._request("POST", "/v5/order/cancel-all", params)
        canceled_orders = list(result.get("list") or [])

        # Bybit demo can leave TP/SL / conditional orders open even when cancel-all
        # returns success. Verify actual post-cancel state, then fall back to
        # explicit per-order cancellation for any survivors.
        await asyncio.sleep(0.25)
        remaining_orders = await self.get_open_orders(symbol=symbol, limit=200)

        survivor_cancellations: List[Dict[str, Any]] = []
        if remaining_orders:
            logger.warning(
                "bybit_cancel_all_left_survivors",
                extra={
                    "symbol": symbol,
                    "category": self._config.category,
                    "survivor_count": len(remaining_orders),
                },
            )
            for order in remaining_orders:
                order_symbol = str(order.get("symbol") or symbol or "").strip()
                order_id = str(order.get("orderId") or order.get("order_id") or "").strip() or None
                client_order_id = str(
                    order.get("orderLinkId")
                    or order.get("clientOrderId")
                    or order.get("client_order_id")
                    or ""
                ).strip() or None
                if not order_symbol or not (order_id or client_order_id):
                    continue
                try:
                    cancel_result = await self.cancel_order(
                        symbol=order_symbol,
                        order_id=order_id,
                        client_order_id=client_order_id,
                    )
                    survivor_cancellations.append(cancel_result)
                except Exception as exc:
                    logger.warning(
                        "bybit_cancel_all_survivor_cancel_failed",
                        extra={
                            "symbol": order_symbol,
                            "order_id": order_id,
                            "client_order_id": client_order_id,
                            "error": str(exc),
                        },
                    )

            await asyncio.sleep(0.25)
            remaining_orders = await self.get_open_orders(symbol=symbol, limit=200)

        if remaining_orders:
            logger.warning(
                "bybit_cancel_all_remaining_after_fallback",
                extra={
                    "symbol": symbol,
                    "category": self._config.category,
                    "remaining_count": len(remaining_orders),
                },
            )

        return {
            **result,
            "list": canceled_orders + survivor_cancellations,
            "remaining": remaining_orders,
            "verified": len(remaining_orders) == 0,
        }
    
    async def get_open_orders(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get open orders.
        
        Args:
            symbol: Optional symbol filter
            limit: Max number of orders
            
        Returns:
            List of open orders
        """
        params = {
            "category": self._config.category,
            "limit": limit,
        }
        
        if symbol:
            params["symbol"] = symbol
        
        result = await self._request("GET", "/v5/order/realtime", params)
        return result.get("list", [])
    
    async def get_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get specific order.
        
        Args:
            symbol: Trading symbol
            order_id: Exchange order ID
            client_order_id: Client order ID
            
        Returns:
            Order details or None if not found
        """
        params = {
            "category": self._config.category,
            "symbol": symbol,
        }
        
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["orderLinkId"] = client_order_id
        
        try:
            result = await self._request("GET", "/v5/order/realtime", params)
            orders = result.get("list", [])
            return orders[0] if orders else None
        except BybitRESTError as e:
            if e.code == 110001:  # Order does not exist
                return None
            raise
    
    async def get_positions(
        self,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get positions.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of positions
        """
        params = {"category": self._config.category}
        
        if symbol:
            params["symbol"] = symbol
        
        result = await self._request("GET", "/v5/position/list", params)
        positions = result.get("list", [])
        
        # Transform to canonical format
        transformed = []
        for pos in positions:
            raw_size = pos.get("size")
            try:
                size = float(raw_size) if raw_size not in (None, "") else 0.0
            except (TypeError, ValueError):
                size = 0.0
            if pos.get("side") == "Sell":
                size = -size

            raw_avg = pos.get("avgPrice")
            raw_pnl = pos.get("unrealisedPnl")
            raw_lev = pos.get("leverage")
            raw_liq = pos.get("liqPrice")

            transformed.append({
                "symbol": pos.get("symbol"),
                "size": size,
                "entry_price": float(raw_avg) if raw_avg not in (None, "") else None,
                "unrealized_pnl": float(raw_pnl) if raw_pnl not in (None, "") else 0.0,
                "leverage": float(raw_lev) if raw_lev not in (None, "") else 1.0,
                "liq_price": float(raw_liq) if raw_liq not in (None, "") else None,
                "raw": pos,
            })
        
        return transformed
    
    async def get_wallet_balance(self, coin: str = "USDT") -> Dict[str, Any]:
        """
        Get wallet balance.
        
        Args:
            coin: Coin type
            
        Returns:
            Wallet balance details
        """
        params = {
            "accountType": "UNIFIED" if self._config.category == "linear" else "CONTRACT",
            "coin": coin,
        }
        
        result = await self._request("GET", "/v5/account/wallet-balance", params)
        accounts = result.get("list", [])
        
        if not accounts:
            return {
                "equity": 0.0,
                "available_balance": 0.0,
                "wallet_balance": 0.0,
            }
        
        account = accounts[0]
        coins = account.get("coin", [])
        coin_data = next((c for c in coins if c.get("coin") == coin), {})
        
        return {
            "equity": float(coin_data.get("equity", 0)),
            "available_balance": float(coin_data.get("availableToWithdraw", 0)),
            "wallet_balance": float(coin_data.get("walletBalance", 0)),
            "unrealized_pnl": float(coin_data.get("unrealisedPnl", 0)),
            "raw": account,
        }
    
    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """
        Set leverage for a symbol.
        
        Args:
            symbol: Trading symbol
            leverage: Leverage value
            
        Returns:
            Result
        """
        params = {
            "category": self._config.category,
            "symbol": symbol,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage),
        }
        
        return await self._request("POST", "/v5/position/set-leverage", params)
    
    async def close_position(self, symbol: str) -> Dict[str, Any]:
        """
        Close entire position for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Order result
        """
        # Get current position
        positions = await self.get_positions(symbol)
        if not positions or positions[0]["size"] == 0:
            return {"message": "No position to close"}
        
        pos = positions[0]
        size = abs(pos["size"])
        side = "Sell" if pos["size"] > 0 else "Buy"
        
        return await self.place_order(
            symbol=symbol,
            side=side,
            qty=size,
            order_type="Market",
            reduce_only=True,
        )
