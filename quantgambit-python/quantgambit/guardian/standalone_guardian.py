"""Standalone Position Guardian Service.

Runs independently of bot runtimes to protect positions 24/7.

Architecture Options:
1. Per-Exchange-Account: One guardian per exchange account (current)
2. Per-Tenant: One guardian monitors all exchange accounts for a tenant
3. Pooled Workers: Shared worker pool assigns accounts dynamically

For multi-tenant scale:
- Guardian Orchestrator decides which accounts need monitoring
- Accounts need guardian when: verified credentials + live bot + positions possible
- Workers auto-scale based on account count and position count
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import redis.asyncio as redis

from quantgambit.observability.logger import log_info, log_warning, log_error
from quantgambit.storage.redis_snapshots import RedisSnapshotReader
from quantgambit.storage.secrets import SecretsProvider
from quantgambit.execution.ccxt_clients import CcxtCredentials


@dataclass
class GuardianConfig:
    """Configuration for standalone position guardian."""
    redis_url: str = "redis://localhost:6379"
    tenant_id: str = ""
    exchange_account_id: str = ""
    exchange: str = "binance"
    is_testnet: bool = False
    secret_id: Optional[str] = None
    
    # Guardian behavior
    poll_interval_sec: float = 5.0
    max_position_age_sec: float = 0.0  # 0 = disabled
    trailing_stop_bps: float = 0.0  # 0 = disabled
    
    # Health reporting
    health_key_prefix: str = "guardian"


class StandalonePositionGuardian:
    """
    Standalone Position Guardian that runs independently of bot runtimes.
    
    Features:
    - Polls exchange directly for positions (no dependency on bot state)
    - Enforces SL/TP limits set on positions
    - Time-based position exits
    - Trailing stop support
    - Reports health to Redis for dashboard visibility
    """
    
    def __init__(self, config: GuardianConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        self.exchange_client: Optional[Any] = None
        self.credentials: Optional[CcxtCredentials] = None
        self._running = False
        self._last_positions: Dict[str, Any] = {}
        
    async def start(self) -> None:
        """Initialize connections and start the guardian loop."""
        log_info(
            "guardian_starting",
            tenant_id=self.config.tenant_id,
            exchange_account_id=self.config.exchange_account_id,
            exchange=self.config.exchange,
        )
        
        # Connect to Redis
        self.redis_client = redis.from_url(self.config.redis_url)
        
        # Load credentials
        self.credentials = await self._load_credentials()
        if not self.credentials:
            log_error("guardian_no_credentials", exchange_account_id=self.config.exchange_account_id)
            raise ValueError("Failed to load exchange credentials")
        
        # Initialize exchange client
        self.exchange_client = await self._create_exchange_client()
        
        self._running = True
        log_info(
            "guardian_started",
            exchange=self.config.exchange,
            testnet=self.config.is_testnet,
        )
        
        # Run the main loop
        await self._run_loop()
        
    async def stop(self) -> None:
        """Stop the guardian gracefully."""
        self._running = False
        log_info("guardian_stopping")
        
        if self.redis_client:
            await self.redis_client.close()
            
    async def _load_credentials(self) -> Optional[CcxtCredentials]:
        """Load credentials from secrets provider."""
        if not self.config.secret_id:
            log_warning("guardian_no_secret_id")
            return None
            
        try:
            provider = SecretsProvider()
            creds = provider.get_exchange_credentials(self.config.secret_id)
            if creds:
                log_info("guardian_credentials_loaded", api_key_prefix=creds.api_key[:8] + "...")
            return creds
        except Exception as exc:
            log_error("guardian_credentials_error", error=str(exc))
            return None
            
    async def _create_exchange_client(self) -> Any:
        """Create exchange client for position management."""
        if not self.credentials:
            return None
            
        try:
            import ccxt.async_support as ccxt
            
            exchange_class = getattr(ccxt, self.config.exchange, None)
            if not exchange_class:
                log_error("guardian_unknown_exchange", exchange=self.config.exchange)
                return None
            
            config = {
                'apiKey': self.credentials.api_key,
                'secret': self.credentials.secret_key,
                'password': self.credentials.passphrase,
                'enableRateLimit': True,
            }
            
            # Handle exchange-specific testnet/demo modes
            exchange_lower = self.config.exchange.lower()
            if self.config.is_testnet:
                if exchange_lower == "okx":
                    # OKX demo trading uses x-simulated-trading header
                    config['headers'] = {'x-simulated-trading': '1'}
                elif exchange_lower == "bybit":
                    # Bybit demo: skip fetchCurrencies (not supported on demo)
                    config['options'] = config.get('options', {})
                    config['options']['fetchCurrencies'] = False
                else:
                    # Other exchanges use standard sandbox mode for testnet
                    config['sandbox'] = True
            
            client = exchange_class(config)
            
            # Bybit demo trading uses api-demo.bybit.com
            if exchange_lower == "bybit" and self.config.is_testnet:
                # Use CCXT's built-in demo trading URLs
                demo_urls = client.urls.get("demotrading", {
                    "public": "https://api-demo.bybit.com",
                    "private": "https://api-demo.bybit.com",
                })
                client.urls["api"] = demo_urls
                log_info("guardian_bybit_demo_url_set", urls=str(demo_urls))
                
                # Preload markets from mainnet (demo doesn't support all endpoints)
                prod_client = ccxt.bybit({
                    'enableRateLimit': True,
                    'options': {'fetchCurrencies': False},
                })
                await prod_client.load_markets()
                client.markets = prod_client.markets
                client.markets_by_id = prod_client.markets_by_id
                client.symbols = prod_client.symbols
                client.currencies = prod_client.currencies
                await prod_client.close()
                log_info("guardian_bybit_markets_preloaded", count=len(client.markets))
            
            # For OKX demo, preload markets from production
            if exchange_lower == "okx" and self.config.is_testnet:
                prod_client = ccxt.okx({'enableRateLimit': True})
                await prod_client.load_markets()
                client.markets = prod_client.markets
                client.markets_by_id = prod_client.markets_by_id
                await prod_client.close()
                log_info("guardian_okx_markets_preloaded")
            else:
                # Test connection
                await client.load_markets()
            
            log_info("guardian_exchange_connected", exchange=self.config.exchange, is_testnet=self.config.is_testnet)
            return client
            
        except Exception as exc:
            log_error("guardian_exchange_error", error=str(exc))
            return None
            
    async def _run_loop(self) -> None:
        """Main guardian loop."""
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                log_error("guardian_tick_error", error=str(exc))
                
            await asyncio.sleep(self.config.poll_interval_sec)
            
    async def _tick(self) -> None:
        """Single guardian tick - check positions and enforce limits."""
        if not self.exchange_client:
            return
            
        now = time.time()
        
        # Fetch positions from exchange
        positions = await self._fetch_positions()
        
        # Check each position against guardrails
        for pos in positions:
            reason = self._should_close(pos, now)
            if reason:
                await self._close_position(pos, reason)
                
        # Update health snapshot
        await self._update_health(now, len(positions))
        
    async def _fetch_positions(self) -> list:
        """Fetch open positions from exchange."""
        try:
            positions = await self.exchange_client.fetch_positions()
            if not positions:
                return []
            # Filter to only open positions with size > 0
            open_positions = [
                p for p in positions 
                if abs(float(p.get('contracts', 0) or p.get('contractSize', 0) or 0)) > 0
            ]
            return open_positions
        except Exception as exc:
            log_warning("guardian_fetch_error", error=str(exc))
            return []
            
    def _should_close(self, position: dict, now: float) -> Optional[str]:
        """Check if position should be closed based on guardrails."""
        symbol = position.get('symbol', '')
        side = position.get('side', '')
        entry_price = float(position.get('entryPrice', 0) or 0)
        mark_price = float(position.get('markPrice', 0) or position.get('lastPrice', 0) or 0)
        
        if entry_price <= 0 or mark_price <= 0:
            return None
            
        # Get SL/TP from position info (if exchange supports it)
        stop_loss = position.get('stopLoss')
        take_profit = position.get('takeProfit')
        
        # Check stop loss
        if stop_loss:
            sl_price = float(stop_loss)
            if side == 'long' and mark_price <= sl_price:
                return "stop_loss_hit"
            if side == 'short' and mark_price >= sl_price:
                return "stop_loss_hit"
                
        # Check take profit
        if take_profit:
            tp_price = float(take_profit)
            if side == 'long' and mark_price >= tp_price:
                return "take_profit_hit"
            if side == 'short' and mark_price <= tp_price:
                return "take_profit_hit"
                
        # Check max age
        if self.config.max_position_age_sec > 0:
            timestamp = position.get('timestamp')
            if timestamp:
                age = now - (timestamp / 1000.0)  # Convert ms to sec
                if age >= self.config.max_position_age_sec:
                    return "max_age_exceeded"
                    
        return None
        
    async def _close_position(self, position: dict, reason: str) -> None:
        """Close a position on the exchange."""
        symbol = position.get('symbol', '')
        side = position.get('side', '')
        size = abs(float(position.get('contracts', 0) or position.get('contractSize', 0) or 0))
        
        log_warning(
            "guardian_closing_position",
            symbol=symbol,
            side=side,
            size=size,
            reason=reason,
        )
        
        try:
            # Determine close side (opposite of position side)
            close_side = 'sell' if side == 'long' else 'buy'
            
            # Market close
            order = await self.exchange_client.create_market_order(
                symbol=symbol,
                side=close_side,
                amount=size,
                params={'reduceOnly': True},
            )
            
            log_info(
                "guardian_position_closed",
                symbol=symbol,
                reason=reason,
                order_id=order.get('id'),
            )
            
            # Publish guardrail event
            await self._publish_guardrail_event(symbol, reason, order)
            
        except Exception as exc:
            log_error(
                "guardian_close_error",
                symbol=symbol,
                error=str(exc),
            )
            
    async def _update_health(self, timestamp: float, position_count: int) -> None:
        """Update health snapshot in Redis."""
        if not self.redis_client:
            return
            
        health_key = f"{self.config.health_key_prefix}:{self.config.tenant_id}:{self.config.exchange_account_id}:health"
        
        health = {
            "status": "running",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timestamp_epoch": timestamp,
            "exchange": self.config.exchange,
            "exchange_account_id": self.config.exchange_account_id,
            "is_testnet": self.config.is_testnet,
            "positions_monitored": position_count,
            "guardian": {
                "status": "running",
                "last_check": timestamp,
            },
        }
        
        try:
            import json
            await self.redis_client.set(health_key, json.dumps(health), ex=60)
        except Exception as exc:
            log_warning("guardian_health_update_error", error=str(exc))
            
    async def _publish_guardrail_event(self, symbol: str, reason: str, order: dict) -> None:
        """Publish guardrail event to Redis stream."""
        if not self.redis_client:
            return
            
        stream_key = f"events:guardrail:{self.config.tenant_id}"
        
        event = {
            "event_type": "position_guardian_close",
            "timestamp": time.time(),
            "exchange_account_id": self.config.exchange_account_id,
            "symbol": symbol,
            "reason": reason,
            "order_id": order.get('id'),
            "fill_price": order.get('average') or order.get('price'),
        }
        
        try:
            import json
            await self.redis_client.xadd(
                stream_key,
                {"data": json.dumps(event)},
                maxlen=1000,
            )
        except Exception as exc:
            log_warning("guardian_event_publish_error", error=str(exc))


async def run_guardian() -> None:
    """Entry point for running the standalone guardian."""
    config = GuardianConfig(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        tenant_id=os.getenv("TENANT_ID", ""),
        exchange_account_id=os.getenv("EXCHANGE_ACCOUNT_ID", ""),
        exchange=os.getenv("EXCHANGE", "binance"),
        is_testnet=os.getenv("IS_TESTNET", "false").lower() in {"1", "true", "yes"},
        secret_id=os.getenv("EXCHANGE_SECRET_ID"),
        poll_interval_sec=float(os.getenv("GUARDIAN_POLL_SEC", "5")),
        max_position_age_sec=float(os.getenv("GUARDIAN_MAX_AGE_SEC", "0")),
        trailing_stop_bps=float(os.getenv("GUARDIAN_TRAILING_BPS", "0")),
    )
    
    guardian = StandalonePositionGuardian(config)
    
    try:
        await guardian.start()
    except KeyboardInterrupt:
        await guardian.stop()
    except Exception as exc:
        log_error("guardian_fatal", error=str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(run_guardian())
