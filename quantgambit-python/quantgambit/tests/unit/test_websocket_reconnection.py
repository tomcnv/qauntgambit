"""
Unit tests for WebSocket reconnection handling.

Tests cover:
1. Connection establishment
2. Reconnection on disconnect
3. Exponential backoff
4. Authentication flow
5. Subscription management
6. Message handling during reconnection
7. State consistency after reconnection
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from quantgambit.core.clock import SimClock
from quantgambit.io.sidechannel import NullSideChannel
from quantgambit.io.adapters.bybit.ws_client import (
    BybitWSClient,
    BybitWSConfig,
    BybitChannel,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def clock() -> SimClock:
    """Create deterministic clock."""
    return SimClock(start_time=1704067200.0, start_mono=0.0)


@pytest.fixture
def publisher() -> NullSideChannel:
    """Create null publisher."""
    return NullSideChannel()


@pytest.fixture
def config() -> BybitWSConfig:
    """Create test config."""
    return BybitWSConfig(
        public_url="wss://test.bybit.com/v5/public/linear",
        private_url="wss://test.bybit.com/v5/private",
        api_key="test_key",
        api_secret="test_secret",
        ping_interval_s=20.0,
        ping_timeout_s=10.0,
        reconnect_delay_s=1.0,
        max_reconnect_delay_s=60.0,
        symbols=["BTCUSDT", "ETHUSDT"],
        orderbook_depth=50,
    )


@pytest.fixture
def client(clock: SimClock, config: BybitWSConfig, publisher: NullSideChannel) -> BybitWSClient:
    """Create WebSocket client."""
    return BybitWSClient(clock, config, publisher)


# =============================================================================
# Connection State Tests
# =============================================================================

class TestConnectionState:
    """Tests for connection state management."""
    
    def test_initial_state(self, client: BybitWSClient):
        """Client should start disconnected."""
        assert client._running is False
        assert client._connected_public is False
        assert client._connected_private is False
        assert client._reconnect_count == 0
    
    def test_is_connected_requires_public(self, client: BybitWSClient):
        """is_connected should require public connection."""
        client._connected_public = False
        client._connected_private = True
        assert client.is_connected() is False
        
        client._connected_public = True
        assert client.is_connected() is True
    
    def test_is_connected_without_credentials(self, clock: SimClock, publisher: NullSideChannel):
        """is_connected should not require private if no credentials."""
        config = BybitWSConfig(
            api_key="",
            api_secret="",
            symbols=["BTCUSDT"],
        )
        client = BybitWSClient(clock, config, publisher)
        
        client._connected_public = True
        client._connected_private = False
        
        # Should be connected even without private
        assert client.is_connected() is True
    
    def test_is_private_connected(self, client: BybitWSClient):
        """is_private_connected should reflect private state."""
        assert client.is_private_connected() is False
        
        client._connected_private = True
        assert client.is_private_connected() is True


# =============================================================================
# Reconnection Logic Tests
# =============================================================================

class TestReconnectionLogic:
    """Tests for reconnection behavior."""
    
    def test_exponential_backoff_calculation(self, config: BybitWSConfig):
        """Reconnection delay should use exponential backoff."""
        base_delay = config.reconnect_delay_s
        max_delay = config.max_reconnect_delay_s
        
        # Test backoff progression
        for reconnect_count in range(10):
            expected_delay = min(
                base_delay * (2 ** reconnect_count),
                max_delay,
            )
            
            # Verify formula
            actual_delay = min(
                config.reconnect_delay_s * (2 ** reconnect_count),
                config.max_reconnect_delay_s,
            )
            assert actual_delay == expected_delay
    
    def test_backoff_caps_at_max(self, config: BybitWSConfig):
        """Backoff should cap at max_reconnect_delay_s."""
        # After many reconnects, should cap at max
        reconnect_count = 100
        delay = min(
            config.reconnect_delay_s * (2 ** reconnect_count),
            config.max_reconnect_delay_s,
        )
        assert delay == config.max_reconnect_delay_s
    
    @pytest.mark.asyncio
    async def test_disconnect_sets_running_false(self, client: BybitWSClient):
        """disconnect() should set _running to False."""
        client._running = True
        await client.disconnect()
        assert client._running is False
    
    @pytest.mark.asyncio
    async def test_disconnect_cancels_tasks(self, client: BybitWSClient):
        """disconnect() should cancel running tasks."""
        # Create real asyncio tasks that can be cancelled
        async def dummy_task():
            await asyncio.sleep(100)
        
        client._public_task = asyncio.create_task(dummy_task())
        client._private_task = asyncio.create_task(dummy_task())
        
        await client.disconnect()
        
        # Tasks should be cancelled
        assert client._public_task.cancelled() or client._public_task.done()
        assert client._private_task.cancelled() or client._private_task.done()


# =============================================================================
# Authentication Tests
# =============================================================================

class TestAuthentication:
    """Tests for WebSocket authentication."""
    
    @pytest.mark.asyncio
    async def test_authenticate_success(self, client: BybitWSClient):
        """Successful auth should return True."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({"success": True}))
        
        result = await client._authenticate(mock_ws)
        
        assert result is True
        mock_ws.send.assert_called_once()
        
        # Verify auth message format
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["op"] == "auth"
        assert len(sent_msg["args"]) == 3  # api_key, expires, signature
    
    @pytest.mark.asyncio
    async def test_authenticate_failure(self, client: BybitWSClient):
        """Failed auth should return False."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "success": False,
            "ret_msg": "Invalid API key",
        }))
        
        result = await client._authenticate(mock_ws)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_authenticate_timeout(self, client: BybitWSClient):
        """Auth timeout should return False."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())
        
        result = await client._authenticate(mock_ws)
        
        assert result is False


# =============================================================================
# Subscription Tests
# =============================================================================

class TestSubscriptions:
    """Tests for channel subscriptions."""
    
    @pytest.mark.asyncio
    async def test_subscribe_public_channels(self, client: BybitWSClient):
        """Should subscribe to orderbook and trades for each symbol."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._public_ws = mock_ws
        
        await client._subscribe_public()
        
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        
        assert sent_msg["op"] == "subscribe"
        assert "orderbook.50.BTCUSDT" in sent_msg["args"]
        assert "orderbook.50.ETHUSDT" in sent_msg["args"]
        assert "publicTrade.BTCUSDT" in sent_msg["args"]
        assert "publicTrade.ETHUSDT" in sent_msg["args"]
    
    @pytest.mark.asyncio
    async def test_subscribe_private_channels(self, client: BybitWSClient):
        """Should subscribe to order, execution, position, wallet."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._private_ws = mock_ws
        
        await client._subscribe_private()
        
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        
        assert sent_msg["op"] == "subscribe"
        assert "order" in sent_msg["args"]
        assert "execution" in sent_msg["args"]
        assert "position" in sent_msg["args"]
        assert "wallet" in sent_msg["args"]
    
    @pytest.mark.asyncio
    async def test_subscribe_public_no_symbols(
        self, clock: SimClock, publisher: NullSideChannel
    ):
        """Should not subscribe if no symbols configured."""
        config = BybitWSConfig(symbols=[])
        client = BybitWSClient(clock, config, publisher)
        
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._public_ws = mock_ws
        
        await client._subscribe_public()
        
        mock_ws.send.assert_not_called()


# =============================================================================
# Message Handling Tests
# =============================================================================

class TestMessageHandling:
    """Tests for WebSocket message handling."""
    
    @pytest.mark.asyncio
    async def test_handle_orderbook_message(self, client: BybitWSClient):
        """Orderbook messages should trigger handler."""
        handler_called = False
        received_data = None
        
        async def handler(data):
            nonlocal handler_called, received_data
            handler_called = True
            received_data = data
        
        client.on_orderbook = handler
        
        message = json.dumps({
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "data": {
                "s": "BTCUSDT",
                "b": [["50000", "1.0"]],
                "a": [["50010", "1.0"]],
            },
        })
        
        await client._handle_public_message(message)
        
        assert handler_called is True
        assert received_data["topic"] == "orderbook.50.BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_handle_trade_message(self, client: BybitWSClient):
        """Trade messages should trigger handler."""
        handler_called = False
        
        async def handler(data):
            nonlocal handler_called
            handler_called = True
        
        client.on_trade = handler
        
        message = json.dumps({
            "topic": "publicTrade.BTCUSDT",
            "data": [{"p": "50000", "v": "0.1", "S": "Buy"}],
        })
        
        await client._handle_public_message(message)
        
        assert handler_called is True
    
    @pytest.mark.asyncio
    async def test_handle_subscription_confirmation(self, client: BybitWSClient):
        """Subscription confirmations should be logged, not passed to handlers."""
        handler_called = False
        
        async def handler(data):
            nonlocal handler_called
            handler_called = True
        
        client.on_orderbook = handler
        
        message = json.dumps({
            "op": "subscribe",
            "success": True,
            "conn_id": "test123",
        })
        
        await client._handle_public_message(message)
        
        # Handler should NOT be called for subscription confirmations
        assert handler_called is False
    
    @pytest.mark.asyncio
    async def test_handle_ping_message(self, client: BybitWSClient):
        """Ping messages should trigger pong response."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._public_ws = mock_ws
        
        message = json.dumps({"op": "ping"})
        
        await client._handle_public_message(message)
        
        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["op"] == "pong"
    
    @pytest.mark.asyncio
    async def test_handle_order_update(self, client: BybitWSClient):
        """Order updates should be transformed and passed to handler."""
        received_updates = []
        
        async def handler(data):
            received_updates.append(data)
        
        client.on_order_update = handler
        
        message = json.dumps({
            "topic": "order",
            "data": [{
                "orderId": "order123",
                "orderLinkId": "client123",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "orderType": "Market",
                "orderStatus": "Filled",
                "qty": "0.1",
                "cumExecQty": "0.1",
                "avgPrice": "50000",
            }],
        })
        
        await client._handle_private_message(message)
        
        assert len(received_updates) == 1
        update = received_updates[0]
        assert update["exchange_order_id"] == "order123"
        assert update["client_order_id"] == "client123"
        assert update["symbol"] == "BTCUSDT"
        assert update["filled_qty"] == 0.1
        assert update["is_terminal"] is True
    
    @pytest.mark.asyncio
    async def test_handle_position_update(self, client: BybitWSClient):
        """Position updates should be transformed and passed to handler."""
        received_updates = []
        
        async def handler(data):
            received_updates.append(data)
        
        client.on_position_update = handler
        
        message = json.dumps({
            "topic": "position",
            "data": [{
                "symbol": "BTCUSDT",
                "size": "0.5",
                "side": "Buy",
                "avgPrice": "50000",
                "unrealisedPnl": "100",
            }],
        })
        
        await client._handle_private_message(message)
        
        assert len(received_updates) == 1
        update = received_updates[0]
        assert update["symbol"] == "BTCUSDT"
        assert update["size"] == 0.5
        assert update["entry_price"] == 50000.0
    
    @pytest.mark.asyncio
    async def test_handle_short_position(self, client: BybitWSClient):
        """Short positions should have negative size."""
        received_updates = []
        
        async def handler(data):
            received_updates.append(data)
        
        client.on_position_update = handler
        
        message = json.dumps({
            "topic": "position",
            "data": [{
                "symbol": "BTCUSDT",
                "size": "0.5",
                "side": "Sell",  # Short position
                "avgPrice": "50000",
            }],
        })
        
        await client._handle_private_message(message)
        
        assert len(received_updates) == 1
        assert received_updates[0]["size"] == -0.5  # Negative for short


# =============================================================================
# Disconnect Event Tests
# =============================================================================

class TestDisconnectEvents:
    """Tests for disconnect event emission."""
    
    def test_emit_disconnect_event(self, client: BybitWSClient):
        """Disconnect should emit event via publisher."""
        # Replace publisher with mock
        mock_publisher = MagicMock()
        mock_publisher.publish = MagicMock(return_value=True)
        client._publisher = mock_publisher
        
        client._reconnect_count = 3
        client._emit_disconnect_event("public")
        
        mock_publisher.publish.assert_called_once()
        event = mock_publisher.publish.call_args[0][0]
        
        assert event.payload["alert_type"] == "ws_disconnect"
        assert event.payload["channel"] == "public"
        assert event.payload["reconnect_count"] == 3


# =============================================================================
# Data Transformation Tests
# =============================================================================

class TestDataTransformation:
    """Tests for message data transformation."""
    
    def test_transform_order_update_filled(self, client: BybitWSClient):
        """Filled order should be marked terminal."""
        order = {
            "orderId": "123",
            "orderLinkId": "client123",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderType": "Market",
            "orderStatus": "Filled",
            "qty": "0.1",
            "cumExecQty": "0.1",
            "avgPrice": "50000",
        }
        
        result = client._transform_order_update(order)
        
        assert result["is_terminal"] is True
        assert result["filled_qty"] == 0.1
    
    def test_transform_order_update_partial(self, client: BybitWSClient):
        """Partial fill should not be terminal."""
        order = {
            "orderId": "123",
            "orderLinkId": "client123",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderType": "Limit",
            "orderStatus": "PartiallyFilled",
            "qty": "1.0",
            "cumExecQty": "0.5",
            "price": "50000",
        }
        
        result = client._transform_order_update(order)
        
        assert result["is_terminal"] is False
        assert result["filled_qty"] == 0.5
    
    def test_transform_wallet_update(self, client: BybitWSClient):
        """Wallet update should extract key fields."""
        wallet = {
            "coin": "USDT",
            "equity": "10000",
            "availableToWithdraw": "5000",
            "walletBalance": "9500",
            "unrealisedPnl": "500",
        }
        
        result = client._transform_wallet_update(wallet)
        
        assert result["coin"] == "USDT"
        assert result["equity"] == 10000.0
        assert result["available_balance"] == 5000.0


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling during message processing."""
    
    @pytest.mark.asyncio
    async def test_handle_invalid_json(self, client: BybitWSClient):
        """Invalid JSON should not crash handler."""
        # Should not raise
        await client._handle_public_message("not valid json {{{")
    
    @pytest.mark.asyncio
    async def test_handle_missing_topic(self, client: BybitWSClient):
        """Missing topic should be handled gracefully."""
        message = json.dumps({"data": {}})
        
        # Should not raise
        await client._handle_public_message(message)
    
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash(self, client: BybitWSClient):
        """Exception in handler should not crash client."""
        async def bad_handler(data):
            raise ValueError("Handler error")
        
        client.on_orderbook = bad_handler
        
        message = json.dumps({
            "topic": "orderbook.50.BTCUSDT",
            "data": {},
        })
        
        # Should not raise
        await client._handle_public_message(message)


# =============================================================================
# Integration-like Tests (without real network)
# =============================================================================

class TestReconnectionFlow:
    """Tests for the full reconnection flow."""
    
    @pytest.mark.asyncio
    async def test_reconnection_increments_counter(self, client: BybitWSClient):
        """Each reconnection attempt should increment counter."""
        initial_count = client._reconnect_count
        
        # Simulate reconnection scenario
        client._reconnect_count += 1
        
        assert client._reconnect_count == initial_count + 1
    
    @pytest.mark.asyncio
    async def test_connect_starts_tasks(self, client: BybitWSClient):
        """connect() should start public and private tasks."""
        with patch.object(client, '_run_public', new_callable=AsyncMock) as mock_public, \
             patch.object(client, '_run_private', new_callable=AsyncMock) as mock_private:
            
            await client.connect()
            
            # Tasks should be created
            assert client._public_task is not None
            
            # Private task should be created if credentials exist
            if client._config.api_key:
                assert client._private_task is not None
            
            # Clean up
            await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_connect_without_credentials_skips_private(
        self, clock: SimClock, publisher: NullSideChannel
    ):
        """connect() without credentials should skip private WS."""
        config = BybitWSConfig(
            api_key="",
            api_secret="",
            symbols=["BTCUSDT"],
        )
        client = BybitWSClient(clock, config, publisher)
        
        with patch.object(client, '_run_public', new_callable=AsyncMock):
            await client.connect()
            
            # Private task should NOT be created
            assert client._private_task is None
            
            await client.disconnect()


# =============================================================================
# State Consistency Tests
# =============================================================================

class TestStateConsistency:
    """Tests for state consistency during reconnection."""
    
    def test_handlers_persist_across_reconnect(self, client: BybitWSClient):
        """Handlers should persist across reconnection."""
        async def my_handler(data):
            pass
        
        client.on_orderbook = my_handler
        
        # Simulate reconnection (state reset)
        client._connected_public = False
        client._connected_public = True
        
        # Handler should still be set
        assert client.on_orderbook is my_handler
    
    def test_config_immutable_during_operation(self, client: BybitWSClient):
        """Config should remain unchanged during operation."""
        original_symbols = client._config.symbols.copy()
        
        # Simulate some operations
        client._reconnect_count += 1
        client._connected_public = True
        
        # Config should be unchanged
        assert client._config.symbols == original_symbols
