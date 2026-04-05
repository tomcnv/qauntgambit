"""Bybit Demo Trading Smoke Test.

This test verifies end-to-end connectivity with Bybit's demo trading API:
1. Load credentials from encrypted secrets store
2. Connect to Bybit demo API (api-demo.bybit.com)
3. Fetch account balance
4. Place a small limit order (far from market to avoid fills)
5. Verify order status
6. Cancel the order
7. Verify cancellation

Prerequisites:
- Bybit demo account credentials in deeptrader-backend/.secrets/dev/
- Exchange account configured in platform_db with is_demo=true

Run with:
    pytest quantgambit-python/tests/test_bybit_demo_smoke.py -v -s
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client
from quantgambit.storage.secrets import SecretsProvider, ExchangeCredentials
from quantgambit.observability.logger import log_info, log_warning


# Test configuration
BYBIT_SECRET_ID = "deeptrader/dev/11111111-1111-1111-1111-111111111111/bybit/fb213790-5ba6-4637-bccc-25e3d68d4c0c"
TEST_SYMBOL = "BTC-USDT"  # Internal format - will be normalized to BTC/USDT:USDT by ccxt_clients
TEST_SIZE = 0.001  # Minimum BTC size for Bybit


def _load_bybit_demo_credentials() -> CcxtCredentials | None:
    """Load Bybit demo credentials from encrypted secrets store."""
    # Point to the backend secrets directory
    secrets_dir = Path(__file__).parent.parent.parent / "deeptrader-backend" / ".secrets"
    
    provider = SecretsProvider(
        secrets_dir=secrets_dir,
        environment="dev",
        master_password=os.getenv("SECRETS_MASTER_PASSWORD", "dev-master-key-change-in-prod"),
    )
    
    creds = provider.get_credentials(BYBIT_SECRET_ID)
    if not creds:
        return None
    
    return CcxtCredentials(
        api_key=creds.api_key,
        secret_key=creds.secret_key,
        passphrase=creds.passphrase,
        testnet=False,  # Not testnet
        demo=True,      # Demo mode uses api-demo.bybit.com
    )


@pytest.fixture
def bybit_credentials() -> CcxtCredentials:
    """Load and validate Bybit demo credentials."""
    creds = _load_bybit_demo_credentials()
    if not creds:
        pytest.skip(f"Bybit demo credentials not found at secret_id: {BYBIT_SECRET_ID}")
    return creds


@pytest_asyncio.fixture
async def bybit_client(bybit_credentials):
    """Create Bybit CCXT client for demo trading."""
    client = build_ccxt_client(
        exchange="bybit",
        creds=bybit_credentials,
        market_type="perp",
        margin_mode="isolated",
    )
    yield client
    await client.close()


class TestBybitDemoSmoke:
    """Smoke tests for Bybit demo trading connectivity."""

    @pytest.mark.asyncio
    async def test_credentials_load(self, bybit_credentials):
        """Test that credentials can be loaded from secrets store."""
        assert bybit_credentials.api_key, "API key should not be empty"
        assert bybit_credentials.secret_key, "Secret key should not be empty"
        assert bybit_credentials.demo is True, "Should be in demo mode"
        
        # Log masked credentials for debugging
        log_info(
            "smoke_test_credentials_loaded",
            api_key_prefix=bybit_credentials.api_key[:8] + "...",
            is_demo=bybit_credentials.demo,
            is_testnet=bybit_credentials.testnet,
        )

    @pytest.mark.asyncio
    async def test_fetch_balance(self, bybit_client):
        """Test fetching account balance from Bybit demo."""
        balance = await bybit_client.fetch_balance("USDT")
        
        log_info(
            "smoke_test_balance_fetched",
            balance=balance,
            exchange=bybit_client.exchange_id,
        )
        
        # Demo accounts should have some balance
        assert balance is not None, "Balance should not be None"
        assert balance >= 0, "Balance should be non-negative"
        print(f"\n✅ Bybit Demo USDT Balance: {balance}")

    @pytest.mark.asyncio
    async def test_place_and_cancel_limit_order(self, bybit_client):
        """Test placing and canceling a limit order on Bybit demo.
        
        Places a limit order far from market price to avoid fills,
        then cancels it to verify the full order lifecycle.
        """
        # Bybit demo doesn't support ticker endpoint, so fetch from mainnet
        import ccxt.async_support as ccxt
        mainnet_client = ccxt.bybit({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        try:
            ticker = await mainnet_client.fetch_ticker("BTC/USDT:USDT")
            current_price = ticker.get("last") or ticker.get("close")
            if not current_price:
                pytest.skip("Could not fetch current market price")
        except Exception as e:
            pytest.skip(f"Could not fetch ticker: {e}")
        finally:
            await mainnet_client.close()
        
        # Place limit buy order 20% below market (won't fill)
        limit_price = round(current_price * 0.80, 1)  # 20% below market
        
        log_info(
            "smoke_test_placing_order",
            symbol=TEST_SYMBOL,
            side="buy",
            size=TEST_SIZE,
            price=limit_price,
            current_price=current_price,
        )
        
        # Place the order
        order_result = await bybit_client.place_order(
            symbol=TEST_SYMBOL,
            side="buy",
            size=TEST_SIZE,
            order_type="limit",
            price=limit_price,
            client_order_id=f"smoke_test_{int(time.time() * 1000)}",
        )
        
        assert order_result is not None, "Order result should not be None"
        order_id = order_result.get("id")
        assert order_id, "Order should have an ID"
        
        log_info(
            "smoke_test_order_placed",
            order_id=order_id,
            status=order_result.get("status"),
            symbol=TEST_SYMBOL,
        )
        print(f"\n✅ Order placed: {order_id}")
        
        # Small delay to let order settle
        await asyncio.sleep(0.5)
        
        # Fetch order status - use fetchOpenOrder for Bybit unified accounts
        try:
            order_status = await bybit_client.client.fetch_open_order(order_id, "BTC/USDT:USDT")
        except Exception:
            # Fallback to fetch_order with acknowledged param
            order_status = await bybit_client.client.fetch_order(
                order_id, "BTC/USDT:USDT", params={"acknowledged": True}
            )
        assert order_status is not None, "Should be able to fetch order status"
        
        log_info(
            "smoke_test_order_status",
            order_id=order_id,
            status=order_status.get("status"),
            filled=order_status.get("filled"),
        )
        print(f"✅ Order status: {order_status.get('status')}")
        
        # Cancel the order
        cancel_result = await bybit_client.cancel_order(order_id, TEST_SYMBOL)
        
        log_info(
            "smoke_test_order_canceled",
            order_id=order_id,
            cancel_result=str(cancel_result)[:200],
        )
        print(f"✅ Order canceled: {order_id}")
        
        # Verify cancellation
        await asyncio.sleep(0.5)
        try:
            final_status = await bybit_client.client.fetch_closed_order(order_id, "BTC/USDT:USDT")
        except Exception:
            # Fallback to fetch_order with acknowledged param
            final_status = await bybit_client.client.fetch_order(
                order_id, "BTC/USDT:USDT", params={"acknowledged": True}
            )
        
        # Bybit returns 'canceled' or 'cancelled' depending on version
        assert final_status.get("status") in ("canceled", "cancelled", "closed"), \
            f"Order should be canceled, got: {final_status.get('status')}"
        
        print(f"✅ Order cancellation verified: {final_status.get('status')}")

    @pytest.mark.asyncio
    async def test_market_order_lifecycle(self, bybit_client):
        """Test placing a small market order on Bybit demo.
        
        This test actually executes a trade to verify:
        - Market order placement
        - Fill price and fee data
        - Position tracking
        
        WARNING: This will create a real position on the demo account.
        """
        # Check balance first
        balance = await bybit_client.fetch_balance("USDT")
        if balance is None or balance < 100:
            pytest.skip(f"Insufficient demo balance: {balance}")
        
        log_info(
            "smoke_test_market_order_start",
            symbol=TEST_SYMBOL,
            side="buy",
            size=TEST_SIZE,
        )
        
        # Place market buy order
        order_result = await bybit_client.place_order(
            symbol=TEST_SYMBOL,
            side="buy",
            size=TEST_SIZE,
            order_type="market",
            client_order_id=f"smoke_mkt_{int(time.time() * 1000)}",
        )
        
        assert order_result is not None, "Order result should not be None"
        order_id = order_result.get("id")
        assert order_id, "Order should have an ID"
        
        log_info(
            "smoke_test_market_order_placed",
            order_id=order_id,
            status=order_result.get("status"),
            average=order_result.get("average"),
            filled=order_result.get("filled"),
            fee=order_result.get("fee"),
        )
        
        print(f"\n✅ Market order placed: {order_id}")
        print(f"   Status: {order_result.get('status')}")
        print(f"   Fill price: {order_result.get('average')}")
        print(f"   Filled: {order_result.get('filled')}")
        print(f"   Fee: {order_result.get('fee')}")
        
        # Close the position with a market sell
        await asyncio.sleep(1)
        
        close_result = await bybit_client.place_order(
            symbol=TEST_SYMBOL,
            side="sell",
            size=TEST_SIZE,
            order_type="market",
            reduce_only=True,
            client_order_id=f"smoke_close_{int(time.time() * 1000)}",
        )
        
        assert close_result is not None, "Close order result should not be None"
        
        log_info(
            "smoke_test_position_closed",
            order_id=close_result.get("id"),
            status=close_result.get("status"),
            average=close_result.get("average"),
        )
        
        print(f"✅ Position closed: {close_result.get('id')}")
        print(f"   Exit price: {close_result.get('average')}")


class TestBybitDemoConnectivity:
    """Basic connectivity tests for Bybit demo API."""

    @pytest.mark.asyncio
    async def test_api_endpoint_reachable(self, bybit_client):
        """Test that Bybit demo API endpoint is reachable."""
        # The client should have demo URLs configured
        api_urls = bybit_client.client.urls.get("api", {})
        
        log_info(
            "smoke_test_api_urls",
            api_urls=str(api_urls),
            is_testnet=bybit_client.is_testnet,
        )
        
        # Verify demo endpoint is configured
        private_url = api_urls.get("private", "")
        assert "api-demo.bybit.com" in private_url, \
            f"Should use demo endpoint, got: {private_url}"
        
        print(f"\n✅ API endpoint: {private_url}")

    @pytest.mark.asyncio
    async def test_markets_loaded(self, bybit_client):
        """Test that markets can be loaded for demo trading.
        
        Note: Bybit demo doesn't support all market endpoints, so we need to
        load markets from mainnet (public data) and use them with demo API.
        """
        # For demo mode, markets need to be preloaded from mainnet
        # The ccxt_clients.py does this via _preload_bybit_markets()
        # But if not preloaded, we can fetch public market data from mainnet
        if not bybit_client.client.markets:
            # Create a temporary mainnet client to fetch markets
            import ccxt.async_support as ccxt
            mainnet_client = ccxt.bybit({
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            })
            try:
                await mainnet_client.load_markets()
                bybit_client.client.markets = mainnet_client.markets
                bybit_client.client.markets_by_id = mainnet_client.markets_by_id
            finally:
                await mainnet_client.close()
        
        markets = bybit_client.client.markets
        
        assert markets, "Markets should be loaded"
        
        # Check for BTC perpetual in CCXT format
        ccxt_symbol = "BTC/USDT:USDT"
        assert ccxt_symbol in markets, f"{ccxt_symbol} should be in markets"
        
        btc_market = markets[ccxt_symbol]
        log_info(
            "smoke_test_market_info",
            symbol=ccxt_symbol,
            min_amount=btc_market.get("limits", {}).get("amount", {}).get("min"),
            precision=btc_market.get("precision"),
        )
        
        print(f"\n✅ Markets loaded: {len(markets)} symbols")
        print(f"   BTC min amount: {btc_market.get('limits', {}).get('amount', {}).get('min')}")


if __name__ == "__main__":
    # Run with: python -m pytest quantgambit-python/tests/test_bybit_demo_smoke.py -v -s
    pytest.main([__file__, "-v", "-s"])
