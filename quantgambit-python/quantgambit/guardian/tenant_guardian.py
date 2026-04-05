"""Per-Tenant Position Guardian.

Monitors ALL exchange accounts for a single tenant.
Starts when tenant has at least one live bot on a verified exchange.

This is the Phase 1 implementation - one process per tenant.
For Phase 2+, use the pooled worker architecture.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from quantgambit.observability.logger import log_info, log_warning, log_error
from quantgambit.storage.secrets import SecretsProvider
from quantgambit.execution.ccxt_clients import CcxtCredentials
from quantgambit.execution.symbols import to_storage_symbol


@dataclass
class ExchangeAccountInfo:
    """Info about an exchange account to monitor."""
    account_id: str
    venue: str
    is_testnet: bool
    secret_id: str
    bot_ids: List[str] = field(default_factory=list)


@dataclass
class TenantGuardianConfig:
    """Configuration for per-tenant guardian."""
    redis_url: str = "redis://localhost:6379"
    postgres_url: str = ""  # For fetching account/bot info
    tenant_id: str = ""
    
    # Guardian behavior
    poll_interval_sec: float = 5.0
    account_refresh_interval_sec: float = 60.0  # How often to refresh account list
    max_position_age_sec: float = 0.0  # 0 = disabled


def _storage_symbol_key(symbol: Any) -> str:
    return str(to_storage_symbol(symbol) or "").upper()


class TenantPositionGuardian:
    """
    Per-Tenant Guardian that monitors all exchange accounts for one tenant.
    
    Lifecycle:
    1. Starts when tenant has at least one live bot
    2. Discovers all verified exchange accounts for tenant
    3. For each account with live bot, monitors positions
    4. Stops when no more live bots exist
    """
    
    def __init__(self, config: TenantGuardianConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        self.secrets_provider = SecretsProvider()
        self._running = False
        
        # Exchange clients keyed by account_id
        self._exchange_clients: Dict[str, Any] = {}
        self._account_info: Dict[str, ExchangeAccountInfo] = {}
        self._last_account_refresh = 0.0
        
    async def start(self) -> None:
        """Initialize and start the guardian loop."""
        log_info("tenant_guardian_starting", tenant_id=self.config.tenant_id)
        
        self.redis_client = redis.from_url(self.config.redis_url)
        self._running = True
        
        # Initial account discovery
        await self._refresh_accounts()
        
        if not self._account_info:
            log_info("tenant_guardian_no_accounts", tenant_id=self.config.tenant_id)
            # Still run - accounts may be added later
            
        log_info(
            "tenant_guardian_started",
            tenant_id=self.config.tenant_id,
            account_count=len(self._account_info),
        )
        
        await self._run_loop()
        
    async def stop(self) -> None:
        """Stop the guardian gracefully."""
        self._running = False
        log_info("tenant_guardian_stopping", tenant_id=self.config.tenant_id)
        
        # Close all exchange clients
        for client in self._exchange_clients.values():
            try:
                await client.close()
            except Exception:
                pass
                
        if self.redis_client:
            await self.redis_client.close()
            
    async def _run_loop(self) -> None:
        """Main guardian loop."""
        while self._running:
            try:
                # Periodically refresh account list
                if time.time() - self._last_account_refresh > self.config.account_refresh_interval_sec:
                    await self._refresh_accounts()
                    
                # Monitor each account
                for account_id, account_info in self._account_info.items():
                    await self._monitor_account(account_info)
                    
                # Update overall health
                await self._update_health()
                
            except Exception as exc:
                log_error("tenant_guardian_tick_error", error=str(exc))
                
            await asyncio.sleep(self.config.poll_interval_sec)
            
    async def _refresh_accounts(self) -> None:
        """Refresh list of exchange accounts that need monitoring."""
        self._last_account_refresh = time.time()
        
        # Query Redis for accounts that need guardian
        # In production, this would query Postgres via an API call
        # For now, read from a Redis key that the backend maintains
        
        guardian_key = f"guardian:tenant:{self.config.tenant_id}:accounts"
        
        try:
            data = await self.redis_client.get(guardian_key)
            if data:
                import json
                accounts_data = json.loads(data)
                
                for acc in accounts_data:
                    account_id = acc.get("account_id")
                    if account_id and account_id not in self._account_info:
                        self._account_info[account_id] = ExchangeAccountInfo(
                            account_id=account_id,
                            venue=acc.get("venue", "binance"),
                            is_testnet=acc.get("is_testnet", False),
                            secret_id=acc.get("secret_id", ""),
                            bot_ids=acc.get("bot_ids", []),
                        )
                        
                        # Initialize exchange client for new account
                        await self._init_exchange_client(self._account_info[account_id])
                        
                log_info(
                    "tenant_guardian_accounts_refreshed",
                    tenant_id=self.config.tenant_id,
                    count=len(self._account_info),
                )
        except Exception as exc:
            log_warning("tenant_guardian_refresh_error", error=str(exc))
            
    async def _init_exchange_client(self, account: ExchangeAccountInfo) -> bool:
        """Initialize exchange client for an account."""
        if account.account_id in self._exchange_clients:
            return True
            
        if not account.secret_id:
            log_warning("tenant_guardian_no_secret", account_id=account.account_id)
            return False
            
        try:
            creds = self.secrets_provider.get_exchange_credentials(account.secret_id)
            if not creds:
                log_warning("tenant_guardian_creds_not_found", account_id=account.account_id)
                return False
                
            import ccxt.async_support as ccxt
            
            exchange_class = getattr(ccxt, account.venue, None)
            if not exchange_class:
                log_error("tenant_guardian_unknown_exchange", venue=account.venue)
                return False
                
            config = {
                'apiKey': creds.api_key,
                'secret': creds.secret_key,
                'password': creds.passphrase,
                'enableRateLimit': True,
            }
            
            # Handle exchange-specific testnet/demo modes
            venue_lower = account.venue.lower()
            if account.is_testnet:
                if venue_lower == "okx":
                    # OKX demo trading uses x-simulated-trading header
                    config['headers'] = {'x-simulated-trading': '1'}
                elif venue_lower == "bybit":
                    # Bybit demo: skip fetchCurrencies (not supported on demo)
                    config['options'] = config.get('options', {})
                    config['options']['fetchCurrencies'] = False
                else:
                    # Other exchanges use standard sandbox mode for testnet
                    config['sandbox'] = True
            
            client = exchange_class(config)
            
            # Bybit demo trading uses api-demo.bybit.com
            if venue_lower == "bybit" and account.is_testnet:
                # Use CCXT's built-in demo trading URLs
                demo_urls = client.urls.get("demotrading", {
                    "public": "https://api-demo.bybit.com",
                    "private": "https://api-demo.bybit.com",
                })
                client.urls["api"] = demo_urls
                log_info("tenant_guardian_bybit_demo_url_set", urls=str(demo_urls))
                
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
                log_info("tenant_guardian_bybit_markets_preloaded", count=len(client.markets))
            
            # For OKX demo, preload markets from production
            if venue_lower == "okx" and account.is_testnet:
                prod_client = ccxt.okx({'enableRateLimit': True})
                await prod_client.load_markets()
                client.markets = prod_client.markets
                client.markets_by_id = prod_client.markets_by_id
                await prod_client.close()
            else:
                await client.load_markets()
            self._exchange_clients[account.account_id] = client
            
            log_info(
                "tenant_guardian_client_ready",
                account_id=account.account_id,
                venue=account.venue,
            )
            return True
            
        except Exception as exc:
            log_error(
                "tenant_guardian_client_error",
                account_id=account.account_id,
                error=str(exc),
            )
            return False
            
    async def _monitor_account(self, account: ExchangeAccountInfo) -> None:
        """Monitor positions for a single account."""
        client = self._exchange_clients.get(account.account_id)
        if not client:
            return
            
        try:
            positions = await client.fetch_positions()
            if not positions:
                positions = []
            open_positions = [
                p for p in positions
                if abs(float(p.get('contracts', 0) or p.get('contractSize', 0) or 0)) > 0
            ]
            
            # Load SL/TP from Redis for each bot associated with this account
            redis_positions = await self._load_redis_positions(account)
            
            for pos in open_positions:
                # Merge exchange position with Redis SL/TP data
                symbol = pos.get('symbol', '')
                # Normalize symbol for matching via shared storage canonicalization.
                normalized_symbol = _storage_symbol_key(symbol)
                
                # Look up SL/TP from Redis
                redis_pos = redis_positions.get(normalized_symbol)
                if redis_pos:
                    # Use Redis SL/TP if exchange doesn't have them
                    if not pos.get('stopLoss') and redis_pos.get('stop_loss'):
                        pos['stopLoss'] = redis_pos['stop_loss']
                    if not pos.get('takeProfit') and redis_pos.get('take_profit'):
                        pos['takeProfit'] = redis_pos['take_profit']
                
                reason = self._should_close(pos)
                if reason:
                    log_info(
                        "guardian_closing_position",
                        symbol=symbol,
                        reason=reason,
                        mark_price=pos.get('markPrice'),
                        stop_loss=pos.get('stopLoss'),
                        take_profit=pos.get('takeProfit'),
                    )
                    await self._close_position(client, account, pos, reason)
                    
            # Update account-level health
            await self._update_account_health(account, len(open_positions))
            
        except Exception as exc:
            log_warning(
                "tenant_guardian_monitor_error",
                account_id=account.account_id,
                error=str(exc),
            )
    
    async def _load_redis_positions(self, account: ExchangeAccountInfo) -> Dict[str, dict]:
        """Load position SL/TP data from Redis for all bots on this account."""
        result = {}
        try:
            for bot_id in account.bot_ids:
                key = f"quantgambit:{self.config.tenant_id}:{bot_id}:positions:latest"
                data = await self.redis_client.get(key)
                if data:
                    import json
                    snapshot = json.loads(data)
                    for pos in snapshot.get('positions', []):
                        symbol = pos.get('symbol', '')
                        # Normalize symbol through the shared storage canonical form.
                        normalized = _storage_symbol_key(symbol)
                        result[normalized] = pos
        except Exception as exc:
            log_warning(
                "guardian_redis_load_error",
                account_id=account.account_id,
                error=str(exc),
            )
        return result
            
    def _should_close(self, position: dict) -> Optional[str]:
        """Check if position should be closed."""
        # Same logic as standalone guardian
        symbol = position.get('symbol', '')
        side = position.get('side', '')
        mark_price = float(position.get('markPrice', 0) or position.get('lastPrice', 0) or 0)
        
        if mark_price <= 0:
            return None
            
        # Check exchange-side SL/TP
        stop_loss = position.get('stopLoss')
        take_profit = position.get('takeProfit')
        
        if stop_loss:
            sl_price = float(stop_loss)
            if side == 'long' and mark_price <= sl_price:
                return "stop_loss_hit"
            if side == 'short' and mark_price >= sl_price:
                return "stop_loss_hit"
                
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
                age = time.time() - (timestamp / 1000.0)
                if age >= self.config.max_position_age_sec:
                    return "max_age_exceeded"
                    
        return None
        
    async def _close_position(
        self,
        client: Any,
        account: ExchangeAccountInfo,
        position: dict,
        reason: str,
    ) -> None:
        """Close a position."""
        symbol = position.get('symbol', '')
        side = position.get('side', '')
        size = abs(float(position.get('contracts', 0) or 0))
        
        log_warning(
            "tenant_guardian_closing",
            tenant_id=self.config.tenant_id,
            account_id=account.account_id,
            symbol=symbol,
            reason=reason,
        )
        
        try:
            close_side = 'sell' if side == 'long' else 'buy'
            order = await client.create_market_order(
                symbol=symbol,
                side=close_side,
                amount=size,
                params={'reduceOnly': True},
            )
            
            log_info(
                "tenant_guardian_closed",
                symbol=symbol,
                order_id=order.get('id'),
                reason=reason,
            )
            
            # Publish event
            await self._publish_close_event(account, symbol, reason, order)
            
        except Exception as exc:
            log_error(
                "tenant_guardian_close_error",
                symbol=symbol,
                error=str(exc),
            )
            
    async def _update_account_health(self, account: ExchangeAccountInfo, position_count: int) -> None:
        """Update health for a specific account."""
        if not self.redis_client:
            return
            
        key = f"guardian:account:{account.account_id}:health"
        health = {
            "status": "monitoring",
            "timestamp": time.time(),
            "venue": account.venue,
            "positions": position_count,
        }
        
        try:
            import json
            await self.redis_client.set(key, json.dumps(health), ex=30)
        except Exception:
            pass
            
    async def _update_health(self) -> None:
        """Update overall tenant guardian health."""
        if not self.redis_client:
            return
            
        key = f"guardian:tenant:{self.config.tenant_id}:health"
        health = {
            "status": "running",
            "timestamp": time.time(),
            "accounts_monitored": len(self._account_info),
            "accounts": list(self._account_info.keys()),
        }
        
        try:
            import json
            await self.redis_client.set(key, json.dumps(health), ex=30)
        except Exception:
            pass
            
    async def _publish_close_event(
        self,
        account: ExchangeAccountInfo,
        symbol: str,
        reason: str,
        order: dict,
    ) -> None:
        """Publish guardrail close event."""
        if not self.redis_client:
            return
            
        stream = f"events:guardrail:{self.config.tenant_id}"
        event = {
            "event_type": "guardian_position_close",
            "timestamp": time.time(),
            "tenant_id": self.config.tenant_id,
            "account_id": account.account_id,
            "symbol": symbol,
            "reason": reason,
            "order_id": order.get('id'),
        }
        
        try:
            import json
            await self.redis_client.xadd(stream, {"data": json.dumps(event)}, maxlen=1000)
        except Exception:
            pass


async def run_tenant_guardian() -> None:
    """Entry point for tenant guardian."""
    config = TenantGuardianConfig(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        tenant_id=os.getenv("TENANT_ID", ""),
        poll_interval_sec=float(os.getenv("GUARDIAN_POLL_SEC", "5")),
        account_refresh_interval_sec=float(os.getenv("GUARDIAN_REFRESH_SEC", "60")),
        max_position_age_sec=float(os.getenv("GUARDIAN_MAX_AGE_SEC", "0")),
    )
    
    if not config.tenant_id:
        log_error("tenant_guardian_no_tenant_id")
        return
        
    guardian = TenantPositionGuardian(config)
    
    try:
        await guardian.start()
    except KeyboardInterrupt:
        await guardian.stop()
    except Exception as exc:
        log_error("tenant_guardian_fatal", error=str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(run_tenant_guardian())
