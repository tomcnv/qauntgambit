"""CCXT-based exchange clients for order placement and status polling."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Optional

import ccxt.async_support as ccxt

from quantgambit.observability.logger import log_warning, log_info
from quantgambit.execution.symbols import canonical_symbol, normalize_exchange_symbol, to_ccxt_market_symbol


@dataclass(frozen=True)
class CcxtCredentials:
    api_key: str
    secret_key: str
    passphrase: Optional[str] = None
    testnet: bool = False
    demo: bool = False  # Bybit demo mode (separate from testnet)


class CcxtOrderClient:
    """Order client that uses CCXT for REST order placement and status."""

    def __init__(self, exchange_id: str, client: Any, symbol_format: str, market_type: str = "perp", margin_mode: str = "isolated", is_testnet: bool = False):
        self.exchange_id = exchange_id
        self.client = client
        self.symbol_format = symbol_format
        self.market_type = (market_type or "perp").lower()
        self.margin_mode = (margin_mode or "isolated").lower()
        self.is_testnet = is_testnet

    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str,
        price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Any:
        # Ensure markets are loaded for OKX demo trading
        if self.exchange_id == "okx" and self.is_testnet:
            if not self.client.markets or getattr(self.client, "_needs_markets_preload", False):
                await _preload_okx_markets_async(self.client)
                self.client._needs_markets_preload = False
        
        # Ensure markets are loaded for Bybit demo trading
        if self.exchange_id == "bybit" and self.is_testnet:
            if not self.client.markets or getattr(self.client, "_needs_markets_preload", False):
                await _preload_bybit_markets_async(self.client)
                self.client._needs_markets_preload = False
        
        params: dict[str, Any] = {}
        if post_only:
            params["postOnly"] = True
        if time_in_force:
            params["timeInForce"] = str(time_in_force)
        if self.market_type in {"perp", "swap", "future"}:
            params["reduceOnly"] = reduce_only
            
            # OKX demo trading doesn't support certain params - skip them
            # OKX Error 50038: "This feature is unavailable in demo trading"
            skip_okx_demo_params = self.exchange_id == "okx" and self.is_testnet
            
            if self.margin_mode in {"isolated", "cross"} and not skip_okx_demo_params:
                params["marginMode"] = self.margin_mode
            if client_order_id:
                # OKX requires alphanumeric-only clientOrderId (no hyphens)
                sanitized_coid = client_order_id.replace("-", "") if self.exchange_id == "okx" else client_order_id
                params["clientOrderId"] = sanitized_coid
            
            # Handle SL/TP params - exchange-specific logic
            # Bybit: uses takeProfit/stopLoss with tpslMode (NOT stopLossPrice/takeProfitPrice)
            # Bybit GOTCHA: reduceOnly=true prevents TP/SL attachment
            # OKX demo: doesn't support SL/TP at all
            skip_sltp = skip_okx_demo_params or (self.exchange_id == "bybit" and reduce_only)
            
            log_info(
                "ccxt_sltp_check",
                exchange=self.exchange_id,
                is_testnet=self.is_testnet,
                skip_sltp=skip_sltp,
                reduce_only=reduce_only,
                has_stop_loss=stop_loss is not None,
                has_take_profit=take_profit is not None,
                stop_loss_value=stop_loss,
                take_profit_value=take_profit,
            )
            
            # Defensive: drop SL/TP that sit on the wrong side of the entry
            # price — the exchange would reject them anyway.
            effective_price = price  # limit price, or None for market
            if effective_price and stop_loss is not None:
                norm_side = side.lower()
                if norm_side in ("buy", "long") and stop_loss >= effective_price:
                    log_warning(
                        "ccxt_sl_wrong_side",
                        side=side, entry=effective_price, stop_loss=stop_loss,
                    )
                    stop_loss = None
                elif norm_side in ("sell", "short") and stop_loss <= effective_price:
                    log_warning(
                        "ccxt_sl_wrong_side",
                        side=side, entry=effective_price, stop_loss=stop_loss,
                    )
                    stop_loss = None

            if not skip_sltp and (stop_loss is not None or take_profit is not None):
                if self.exchange_id == "bybit":
                    # Bybit-specific SL/TP params per v5 API
                    # https://bybit-exchange.github.io/docs/v5/order/create-order
                    params["tpslMode"] = "Full"  # Full position SL/TP
                    params["positionIdx"] = 0     # One-way mode
                    if stop_loss is not None:
                        params["stopLoss"] = str(stop_loss)
                        params["slTriggerBy"] = "MarkPrice"
                        params["slOrderType"] = "Market"  # SL must be market for safety
                    if take_profit is not None:
                        params["takeProfit"] = str(take_profit)
                        params["tpTriggerBy"] = "MarkPrice"
                        # Bybit Full-mode TP only supports Market
                        params["tpOrderType"] = "Market"
                else:
                    # Default CCXT params for other exchanges
                    if stop_loss is not None:
                        params["stopLossPrice"] = stop_loss
                    if take_profit is not None:
                        params["takeProfitPrice"] = take_profit
        else:
            # Spot market
            if client_order_id:
                # OKX requires alphanumeric-only clientOrderId (no hyphens)
                sanitized_coid = client_order_id.replace("-", "") if self.exchange_id == "okx" else client_order_id
                params["newClientOrderId"] = sanitized_coid

            log_info(
                "ccxt_sltp_check",
                exchange=self.exchange_id,
                market_type=self.market_type,
                order_type=order_type,
                has_stop_loss=stop_loss is not None,
                has_take_profit=take_profit is not None,
                stop_loss_value=stop_loss,
                take_profit_value=take_profit,
            )

            # Bybit spot supports SL/TP on Limit orders (not Market).
            # For market orders, SL/TP must be placed separately after fill.
            if (
                self.exchange_id == "bybit"
                and order_type == "limit"
                and (stop_loss is not None or take_profit is not None)
            ):
                if stop_loss is not None:
                    params["stopLoss"] = str(stop_loss)
                    params["slOrderType"] = "Market"  # SL must be market for safety
                if take_profit is not None:
                    params["takeProfit"] = str(take_profit)
                    # Bybit Full-mode TP only supports Market
                    params["tpOrderType"] = "Market"
        normalized_symbol = _normalize_symbol(symbol, self.symbol_format, self.market_type)
        
        # Debug: log actual params being sent
        log_info(
            "ccxt_order_params_debug",
            exchange=self.exchange_id,
            is_testnet=self.is_testnet,
            params=str(params),
        )
        
        # Normalize side: OKX expects "buy"/"sell", not "long"/"short"
        normalized_side = _normalize_order_side(side)
        
        # Enforce exchange minimum order size from market info
        adjusted_size = size
        try:
            if hasattr(self.client, 'markets') and self.client.markets:
                market = self.client.markets.get(normalized_symbol)
                if market:
                    limits = market.get('limits', {})
                    amount_limits = limits.get('amount', {})
                    min_amount = amount_limits.get('min')
                    if min_amount and size < min_amount:
                        log_warning(
                            "ccxt_size_below_minimum",
                            exchange=self.exchange_id,
                            symbol=normalized_symbol,
                            size=size,
                            min_amount=min_amount,
                            action="rejecting",
                        )
                        # Reject orders below minimum instead of rounding up
                        raise ValueError(f"Order size {size} below exchange minimum {min_amount}")
        except ValueError:
            raise
        except Exception:
            pass  # Proceed with original size if we can't check limits

        if self.market_type == "spot" and normalized_side == "sell":
            adjusted_size = await self._cap_spot_sell_size_to_free_balance(
                normalized_symbol,
                requested_size=adjusted_size,
            )
        
        log_info(
            "ccxt_place_order_start",
            exchange=self.exchange_id,
            symbol=normalized_symbol,
            side=normalized_side,
            size=adjusted_size,
            order_type=order_type,
            has_sl=stop_loss is not None,
            has_tp=take_profit is not None,
        )
        retried_with_position_idx = False
        active_params = dict(params)
        try:
            while True:
                try:
                    result = await self.client.create_order(
                        symbol=normalized_symbol,
                        type=order_type,
                        side=normalized_side,
                        amount=adjusted_size,
                        price=price,
                        params=active_params,
                    )
                    break
                except Exception as create_err:
                    # Bybit hedge-mode close gotcha:
                    # reduceOnly closes can fail with 110017 unless positionIdx is explicit.
                    should_retry_with_position_idx = (
                        self.exchange_id == "bybit"
                        and reduce_only
                        and self.market_type in {"perp", "swap", "future"}
                        and not retried_with_position_idx
                        and "positionIdx" not in active_params
                        and "110017" in str(create_err)
                    )
                    if not should_retry_with_position_idx:
                        raise
                    inferred_idx = 2 if normalized_side == "buy" else 1 if normalized_side == "sell" else None
                    if inferred_idx is None:
                        raise
                    retried_with_position_idx = True
                    active_params = dict(active_params)
                    active_params["positionIdx"] = inferred_idx
                    log_warning(
                        "ccxt_place_order_retry_with_position_idx",
                        exchange=self.exchange_id,
                        symbol=normalized_symbol,
                        side=normalized_side,
                        inferred_position_idx=inferred_idx,
                        order_type=order_type,
                        reduce_only=reduce_only,
                    )
            order_id = result.get("id") if isinstance(result, dict) else None
            log_info(
                "ccxt_place_order_success",
                exchange=self.exchange_id,
                symbol=normalized_symbol,
                order_id=order_id,
                status=result.get("status") if isinstance(result, dict) else None,
                retried_with_position_idx=retried_with_position_idx,
            )
            
            # For market orders, fetch order details to get fill price and fee data
            # OKX (and some exchanges) don't return this in the immediate response
            if order_id and order_type == "market" and isinstance(result, dict):
                has_fill_data = result.get("average") or result.get("fee")
                if not has_fill_data:
                    try:
                        import asyncio
                        await asyncio.sleep(0.5)  # Small delay to let the order settle
                        
                        # Bybit demo has limited API - use fetchClosedOrder or add acknowledged param
                        if self.exchange_id == "bybit":
                            # Try fetchClosedOrder first (more reliable on Bybit demo)
                            try:
                                order_details = await self.client.fetch_closed_order(order_id, normalized_symbol)
                            except Exception:
                                # Fallback to fetch_order with acknowledged=True
                                order_details = await self.client.fetch_order(
                                    order_id, normalized_symbol, 
                                    params={"acknowledged": True}
                                )
                        else:
                            order_details = await self.client.fetch_order(order_id, normalized_symbol)
                        
                        if isinstance(order_details, dict):
                            # Merge the fetched data into result
                            result["average"] = order_details.get("average") or result.get("average")
                            result["price"] = order_details.get("price") or result.get("price")
                            result["filled"] = order_details.get("filled") or result.get("filled")
                            result["fee"] = order_details.get("fee") or result.get("fee")
                            result["status"] = order_details.get("status") or result.get("status")
                            result["cost"] = order_details.get("cost") or result.get("cost")
                            log_info(
                                "ccxt_order_details_fetched",
                                exchange=self.exchange_id,
                                order_id=order_id,
                                average=result.get("average"),
                                fee=result.get("fee"),
                                status=result.get("status"),
                            )
                    except Exception as fetch_err:
                        log_warning(
                            "ccxt_fetch_order_details_failed",
                            exchange=self.exchange_id,
                            order_id=order_id,
                            error=str(fetch_err),
                        )
            
            # For spot market orders, SL/TP can't be attached to the order itself.
            # Place them as separate tpslOrder conditional orders after the fill.
            if (
                self.market_type == "spot"
                and self.exchange_id == "bybit"
                and order_id
                and (stop_loss is not None or take_profit is not None)
            ):
                await self._place_spot_tpsl(
                    normalized_symbol, normalized_side, adjusted_size,
                    stop_loss, take_profit, order_id,
                )

            return result
        except Exception as e:
            log_warning(
                "ccxt_place_order_error",
                exchange=self.exchange_id,
                symbol=normalized_symbol,
                error=str(e),
                error_type=type(e).__name__,
                retried_with_position_idx=retried_with_position_idx,
            )
            raise

    async def _cap_spot_sell_size_to_free_balance(
        self,
        normalized_symbol: str,
        requested_size: float,
    ) -> float:
        base_currency, _ = _split_symbol(normalized_symbol.replace("/", "-"))
        if not base_currency:
            return requested_size
        try:
            balance = await self.client.fetch_balance()
        except Exception as exc:
            log_warning(
                "ccxt_spot_sell_balance_fetch_failed",
                exchange=self.exchange_id,
                symbol=normalized_symbol,
                error=str(exc),
            )
            return requested_size

        free_balances = balance.get("free", {}) or {}
        total_balances = balance.get("total", {}) or {}
        raw_available = (
            free_balances.get(base_currency)
            or free_balances.get(base_currency.upper())
            or total_balances.get(base_currency)
            or total_balances.get(base_currency.upper())
        )
        try:
            available_size = float(raw_available or 0.0)
        except (TypeError, ValueError):
            available_size = 0.0

        if available_size <= 0:
            raise ValueError(f"spot_exit_no_free_balance:{base_currency}")

        adjusted_size = min(float(requested_size), available_size)
        adjusted_size = _round_down_amount(self.client, normalized_symbol, adjusted_size)
        if adjusted_size <= 0:
            raise ValueError(f"spot_exit_no_free_balance:{base_currency}")

        if adjusted_size + 1e-12 < float(requested_size):
            log_warning(
                "ccxt_spot_sell_size_capped",
                exchange=self.exchange_id,
                symbol=normalized_symbol,
                requested_size=requested_size,
                available_size=available_size,
                adjusted_size=adjusted_size,
                currency=base_currency,
            )
        return adjusted_size

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        return await self.client.fetch_order(
            id=order_id,
            symbol=_normalize_symbol(symbol, self.symbol_format, self.market_type),
        )

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        method = getattr(self.client, "fetch_order_by_client_id", None) or getattr(self.client, "fetchOrderByClientId", None)
        if method is None:
            return None
        return await method(
            client_order_id,
            symbol=_normalize_symbol(symbol, self.symbol_format, self.market_type),
        )

    async def cancel_order(self, order_id: str, symbol: str) -> Any:
        method = getattr(self.client, "cancel_order", None) or getattr(self.client, "cancelOrder", None)
        if method is None:
            return None
        return await method(
            order_id,
            symbol=_normalize_symbol(symbol, self.symbol_format, self.market_type),
        )

    async def fetch_positions(self, symbols: Optional[list[str]] = None) -> Optional[list]:
        # Spot: derive positions from non-zero balances
        if self.market_type == "spot":
            return await self._fetch_spot_positions(symbols)

        method = getattr(self.client, "fetch_positions", None) or getattr(self.client, "fetchPositions", None)
        if method is None:
            return None
        normalized_symbols = None
        if symbols:
            normalized_symbols = [_normalize_symbol(symbol, self.symbol_format, self.market_type) for symbol in symbols]
        params: dict[str, Any] = {}
        if self.exchange_id == "bybit":
            if self.market_type in {"perp", "swap", "future"}:
                params["category"] = "linear"
        try:
            return await method(normalized_symbols, params)
        except TypeError:
            try:
                if normalized_symbols is None:
                    return await method(params)
                return await method(normalized_symbols)
            except Exception as exc:
                log_warning(
                    "ccxt_fetch_positions_failed",
                    exchange=self.exchange_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                # Important: an empty list is ambiguous (flat vs API unsupported/failure).
                # Callers that sync local state to exchange should treat None as "unavailable"
                # and avoid destructive actions (like clearing local positions).
                return None
        except Exception as exc:
            log_warning(
                "ccxt_fetch_positions_failed",
                exchange=self.exchange_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

    async def _fetch_spot_positions(self, symbols: Optional[list[str]] = None) -> Optional[list]:
        """Derive spot 'positions' from non-zero balances of non-quote assets."""
        quote_currencies = {"USDT", "USDC", "BUSD", "USD", "EUR"}
        try:
            balance = await self.client.fetch_balance()
        except Exception as exc:
            log_warning("ccxt_spot_balance_fetch_failed", exchange=self.exchange_id, error=str(exc))
            return None
        free = balance.get("free", {}) or {}
        total = balance.get("total", {}) or {}
        positions = []
        dust_usd_threshold = 1.0  # ignore balances worth < $1
        for currency, amount in total.items():
            if currency.upper() in quote_currencies:
                continue
            try:
                total_amount = float(amount or 0.0)
            except (TypeError, ValueError):
                total_amount = 0.0
            try:
                free_amount = float(free.get(currency) or free.get(currency.upper()) or 0.0)
            except (TypeError, ValueError):
                free_amount = 0.0
            tradable_amount = free_amount if free_amount > 0 else total_amount
            if tradable_amount <= 0:
                continue
            # Filter dust: estimate USD value from ticker
            try:
                ticker = await self.client.fetch_ticker(f"{currency.upper()}/USDT")
                usd_value = tradable_amount * float(ticker.get("last") or 0)
                if usd_value < dust_usd_threshold:
                    continue
            except Exception:
                pass  # if we can't price it, keep it
            spot_symbol = f"{currency.upper()}/USDT"
            if symbols:
                normalized_req = {_normalize_symbol(s, self.symbol_format, self.market_type) for s in symbols}
                if spot_symbol not in normalized_req:
                    continue
            # Try to recover entry price from recent trades
            entry_price = await self._estimate_spot_entry_price(spot_symbol, tradable_amount)
            positions.append({
                "symbol": spot_symbol,
                "side": "long",
                "contracts": tradable_amount,
                "size": tradable_amount,
                "entryPrice": entry_price,
            })
        return positions

    async def _estimate_spot_entry_price(self, symbol: str, held_qty: float) -> Optional[float]:
        """Best-effort entry price from recent buy trades for a spot holding."""
        try:
            trades = await self.client.fetch_my_trades(symbol, limit=50)
        except Exception:
            return None
        if not trades:
            return None
        # Walk backwards through buys, accumulating until we cover held_qty
        buys = [t for t in reversed(trades) if (t.get("side") or "").lower() == "buy"]
        if not buys:
            return None
        remaining = held_qty
        cost_sum = 0.0
        qty_sum = 0.0
        for t in buys:
            qty = float(t.get("amount") or 0)
            px = float(t.get("price") or 0)
            if qty <= 0 or px <= 0:
                continue
            take = min(qty, remaining)
            cost_sum += take * px
            qty_sum += take
            remaining -= take
            if remaining <= 1e-12:
                break
        return (cost_sum / qty_sum) if qty_sum > 0 else None

    async def _place_spot_tpsl(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        parent_order_id: str,
    ) -> None:
        """Place SL/TP as separate tpslOrder conditional orders for Bybit spot."""
        # Bybit spot: SL/TP are sell-side tpslOrder orders that trigger at the given price
        exit_side = "Sell" if side.lower() in ("buy", "long") else "Buy"
        for label, trigger_price in [("sl", stop_loss), ("tp", take_profit)]:
            if trigger_price is None:
                continue
            try:
                result = await self.client.create_order(
                    symbol,
                    "market",
                    exit_side.lower(),
                    size,
                    params={
                        "category": "spot",
                        "orderFilter": "tpslOrder",
                        "triggerPrice": str(trigger_price),
                        "orderLinkId": f"{parent_order_id}:{label}",
                    },
                )
                log_info(
                    "ccxt_spot_tpsl_placed",
                    symbol=symbol,
                    type=label,
                    trigger_price=trigger_price,
                    order_id=result.get("id") if isinstance(result, dict) else None,
                    parent_order_id=parent_order_id,
                )
            except Exception as exc:
                log_warning(
                    "ccxt_spot_tpsl_failed",
                    symbol=symbol,
                    type=label,
                    trigger_price=trigger_price,
                    error=str(exc),
                    parent_order_id=parent_order_id,
                )

    async def fetch_executions(
        self,
        symbol: str,
        since_ms: Optional[int] = None,
        limit: int = 100,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> list:
        """Fetch recent executions/trades for a symbol (best-effort)."""
        method = getattr(self.client, "fetch_my_trades", None) or getattr(self.client, "fetchMyTrades", None)
        if method is None:
            return []

        # Ensure markets are loaded for demo/testnet environments
        if self.exchange_id == "okx" and self.is_testnet:
            if not self.client.markets or getattr(self.client, "_needs_markets_preload", False):
                await _preload_okx_markets_async(self.client)
                self.client._needs_markets_preload = False
        if self.exchange_id == "bybit" and self.is_testnet:
            if not self.client.markets or getattr(self.client, "_needs_markets_preload", False):
                await _preload_bybit_markets_async(self.client)
                self.client._needs_markets_preload = False

        normalized_symbol = _normalize_symbol(symbol, self.symbol_format, self.market_type)
        params: dict[str, Any] = {}
        if self.exchange_id == "bybit":
            if self.market_type in {"perp", "swap", "future"}:
                params["category"] = "linear"
            elif self.market_type == "spot":
                params["category"] = "spot"
            if order_id:
                params["orderId"] = order_id
            if client_order_id:
                params["orderLinkId"] = client_order_id
        elif self.exchange_id == "okx":
            if order_id:
                params["orderId"] = order_id
            if client_order_id:
                params["clientOrderId"] = client_order_id.replace("-", "")
        elif self.exchange_id == "binance":
            if order_id:
                params["orderId"] = order_id
            if client_order_id:
                params["origClientOrderId"] = client_order_id

        try:
            return await method(
                symbol=normalized_symbol,
                since=since_ms,
                limit=limit,
                params=params,
            )
        except Exception as exc:
            log_warning(
                "ccxt_fetch_executions_failed",
                exchange=self.exchange_id,
                symbol=normalized_symbol,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def fetch_balance(self, currency: str = "USDT") -> Optional[float]:
        """Fetch account wallet balance (cash) from the exchange.
        
        Returns the wallet balance (actual cash) for the specified currency,
        NOT total equity which includes unrealized PnL and other token values.
        For risk management, we want to know the actual USDT available.
        """
        try:
            # Bybit demo trading: Use wallet-balance endpoint directly
            # (fetch_balance calls /v5/asset/coin/query-info which is NOT supported on demo)
            if self.exchange_id == "bybit" and self.is_testnet:
                return await self._fetch_bybit_demo_balance(currency)
            
            balance = await self.client.fetch_balance()
            
            # For perpetuals/futures, look for wallet balance (cash) first
            if self.market_type in {"perp", "swap", "future"}:
                info = balance.get("info", {})
                if isinstance(info, dict):
                    # Bybit structure - prioritize wallet balance over total equity
                    result = info.get("result", {})
                    lst = result.get("list", [])
                    if lst:
                        acc = lst[0]
                        # First look for specific currency wallet balance
                        coins = acc.get("coin", [])
                        for coin in coins:
                            if coin.get("coin") == currency:
                                wallet_balance = coin.get("walletBalance")
                                if wallet_balance:
                                    return float(wallet_balance)
                        # Then try total wallet balance
                        total_wallet = acc.get("totalWalletBalance")
                        if total_wallet:
                            return float(total_wallet)
                    
                    # OKX structure - look for available balance
                    data = info.get("data", [])
                    if data and isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                # OKX: availBal is actual cash available
                                details = item.get("details", [])
                                for detail in details:
                                    if detail.get("ccy") == currency:
                                        avail = detail.get("availBal") or detail.get("cashBal")
                                        if avail:
                                            return float(avail)
                
                # Fallback to CCXT's parsed 'free' balance (available cash)
                free = balance.get("free", {}).get(currency)
                if free is not None:
                    return float(free)
                
                # Last resort: total balance
                total = balance.get("total", {}).get(currency)
                if total is not None:
                    return float(total)
            
            # Spot: use free balance (available cash)
            return float(balance.get("free", {}).get(currency, 0))
        except Exception as e:
            log_warning(
                "ccxt_fetch_balance_error",
                exchange=self.exchange_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def _fetch_bybit_demo_balance(self, currency: str = "USDT") -> Optional[float]:
        """Fetch USDT wallet balance from Bybit demo using the supported wallet-balance endpoint.
        
        Bybit demo only supports /v5/account/wallet-balance, NOT /v5/asset/coin/query-info.
        
        Returns the actual USDT wallet balance (cash), NOT total equity which includes
        unrealized PnL and other token values.
        """
        try:
            # Ensure markets are preloaded if needed
            if getattr(self.client, "_needs_markets_preload", False):
                await _preload_bybit_markets_async(self.client)
                self.client._needs_markets_preload = False
            
            # Use the supported wallet balance endpoint directly
            response = await self.client.privateGetV5AccountWalletBalance({
                "accountType": "UNIFIED",
            })
            
            result = response.get("result", {})
            lst = result.get("list", [])
            if lst:
                acc = lst[0]
                # First, look for the specific currency's wallet balance (actual cash)
                coins = acc.get("coin", [])
                for coin in coins:
                    if coin.get("coin") == currency:
                        # For spot: use availableToWithdraw (free USDT only)
                        # For perp: use walletBalance (includes margin)
                        if self.market_type == "spot":
                            free = coin.get("availableToWithdraw") or coin.get("free")
                            if free:
                                return float(free)
                        wallet_balance = coin.get("walletBalance")
                        if wallet_balance:
                            return float(wallet_balance)
            return None
        except Exception as e:
            log_warning(
                "bybit_demo_fetch_balance_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def cancel_order_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        order = await self.fetch_order_status_by_client_id(client_order_id, symbol)
        if not order:
            return None
        order_id = order.get("id") if isinstance(order, dict) else getattr(order, "id", None)
        if not order_id:
            return None
        return await self.cancel_order(order_id, symbol)

    async def replace_order(
        self,
        order_id: str,
        symbol: str,
        price: Optional[float] = None,
        size: Optional[float] = None,
    ) -> Any:
        method = getattr(self.client, "edit_order", None) or getattr(self.client, "editOrder", None)
        if method is None:
            return {"success": False, "status": "rejected", "reason": "replace_not_supported"}
        order = await self.fetch_order_status(order_id, symbol)
        if not order:
            return {"success": False, "status": "rejected", "reason": "order_not_found"}
        if isinstance(order, dict):
            order_type = order.get("type") or order.get("order_type") or "limit"
            side = order.get("side")
            amount = order.get("amount") or order.get("size")
            current_price = order.get("price")
        else:
            order_type = getattr(order, "type", None) or "limit"
            side = getattr(order, "side", None)
            amount = getattr(order, "amount", None)
            current_price = getattr(order, "price", None)
        if not side or amount is None:
            return {"success": False, "status": "rejected", "reason": "missing_order_fields"}
        return await method(
            id=order_id,
            symbol=_normalize_symbol(symbol, self.symbol_format, self.market_type),
            type=order_type,
            side=side,
            amount=size or amount,
            price=price or current_price,
            params={},
        )

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Any:
        exit_side = _exit_side(side)
        symbol_fmt = _normalize_symbol(symbol, self.symbol_format, self.market_type)
        if stop_loss is None and take_profit is None:
            return []
        
        # Bybit: Skip separate protective orders - SL/TP is attached natively to the main order
        # via tpslMode="Full" in place_order(). Placing separate orders would be redundant
        # and causes "OrderType invalid" errors.
        if self.exchange_id == "bybit":
            log_info(
                "place_protective_orders_skipped",
                exchange=self.exchange_id,
                reason="native_sltp_attached",
                symbol=symbol,
            )
            return []
        
        if self.exchange_id == "okx":
            try:
                return await _okx_native_oco(
                    self.client,
                    _native_symbol(symbol, "okx"),
                    exit_side,
                    size,
                    stop_loss,
                    take_profit,
                    client_order_id,
                    margin_mode=self.margin_mode if self.market_type != "spot" else None,
                )
            except Exception as exc:
                log_warning("protective_order_failed", exchange=self.exchange_id, error=str(exc))
                return []
        try:
            if self.exchange_id == "binance":
                return await _place_binance_protective_orders(
                    self.client,
                    _spot_symbol(symbol),
                    exit_side,
                    size,
                    stop_loss,
                    take_profit,
                    client_order_id,
                    margin_mode=self.margin_mode if self.market_type != "spot" else None,
                )
            if self.exchange_id == "bybit":
                return await _place_bybit_protective_orders(
                    self.client,
                    symbol_fmt,
                    exit_side,
                    size,
                    stop_loss,
                    take_profit,
                    client_order_id,
                    margin_mode=self.margin_mode if self.market_type != "spot" else None,
                )
        except Exception as exc:
            log_warning("protective_order_failed", exchange=self.exchange_id, error=str(exc))
        return await _place_generic_protective_orders(
            self.client,
            symbol_fmt,
            exit_side,
            size,
            stop_loss,
            take_profit,
            client_order_id,
            margin_mode=self.margin_mode if self.market_type != "spot" else None,
        )

    async def place_native_oco(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Any:
        if stop_loss is None and take_profit is None:
            return None
        if self.exchange_id == "okx":
            return await _okx_native_oco(
                self.client,
                _native_symbol(symbol, "okx"),
                _exit_side(side),
                size,
                stop_loss,
                take_profit,
                client_order_id,
                margin_mode=self.margin_mode if self.market_type != "spot" else None,
            )
        if self.exchange_id == "bybit":
            return await _bybit_native_tpsl(
                self.client,
                _native_symbol(symbol, "bybit"),
                stop_loss,
                take_profit,
                client_order_id,
                margin_mode=self.margin_mode if self.market_type != "spot" else None,
            )
        if self.exchange_id == "binance" and self.market_type == "spot":
            return await _binance_spot_oco(
                self.client,
                _native_symbol(symbol, "binance"),
                _exit_side(side),
                size,
                stop_loss,
                take_profit,
                client_order_id,
            )
        return None

    async def close(self) -> None:
        await self.client.close()


def build_ccxt_client(
    exchange: str,
    creds: CcxtCredentials,
    market_type: str = "perp",
    margin_mode: str = "isolated",
) -> CcxtOrderClient:
    exchange_id = exchange.strip().lower()
    normalized_type = (market_type or "perp").lower()
    default_type = "spot" if normalized_type == "spot" else "swap"
    if exchange_id == "okx":
        config = {
            "apiKey": creds.api_key,
            "secret": creds.secret_key,
            "password": creds.passphrase,
            "enableRateLimit": True,
            "options": {
                "defaultType": default_type,
            },
        }
        # OKX demo/testnet trading uses x-simulated-trading header, not sandbox mode
        if creds.testnet:
            config["headers"] = {"x-simulated-trading": "1"}
            # Skip currency fetch which is unavailable in demo mode
            config["options"]["fetchCurrencies"] = False
        log_info(
            "build_ccxt_client_okx",
            is_testnet=creds.testnet,
            has_demo_header="x-simulated-trading" in config.get("headers", {}),
            default_type=default_type,
            market_type=market_type,
        )
        client = ccxt.okx(config)
        # For OKX demo mode, preload markets synchronously from production
        # (demo mode disables certain private endpoints including those needed by load_markets)
        if creds.testnet and not client.markets:
            _preload_okx_markets(client)
        # Log the actual client headers for debugging
        log_info(
            "build_ccxt_client_okx_headers",
            client_headers=str(getattr(client, "headers", {})),
            is_testnet=creds.testnet,
        )
        return CcxtOrderClient(exchange_id, client, symbol_format="okx", market_type=market_type, margin_mode=margin_mode, is_testnet=creds.testnet)
    if exchange_id == "bybit":
        config = {
            "apiKey": creds.api_key,
            "secret": creds.secret_key,
            "enableRateLimit": True,
            "options": {
                "defaultType": default_type,
                "fetchCurrencies": False,  # CRITICAL: /v5/asset/coin/query-info not supported on demo
            },
        }
        client = ccxt.bybit(config)
        # Bybit has THREE environments:
        # 1. Mainnet (api.bybit.com) - production
        # 2. Testnet (api-testnet.bybit.com) - test environment with test funds
        # 3. Demo (api-demo.bybit.com) - demo trading with real market data but paper money
        if creds.demo:
            # Demo Trading uses a separate API endpoint: api-demo.bybit.com
            client.urls["api"] = {
                "public": "https://api-demo.bybit.com",
                "private": "https://api-demo.bybit.com",
            }
            log_info(
                "build_ccxt_client_bybit_demo",
                is_demo=True,
                is_testnet=creds.testnet,
                demo_urls=str(client.urls.get("api")),
            )
            # Preload markets from mainnet (demo doesn't support all market endpoints)
            _preload_bybit_markets(client)
        elif creds.testnet:
            # Testnet uses CCXT's built-in sandbox mode
            client.set_sandbox_mode(True)
            log_info(
                "build_ccxt_client_bybit_testnet",
                is_testnet=True,
                is_demo=False,
            )
        return CcxtOrderClient(exchange_id, client, symbol_format="bybit", market_type=market_type, margin_mode=margin_mode, is_testnet=creds.testnet or creds.demo)
    if exchange_id == "binance":
        binance_type = "spot" if normalized_type == "spot" else "future"
        symbol_format = "binance_spot" if normalized_type == "spot" else "binance"
        client = ccxt.binance(
            {
                "apiKey": creds.api_key,
                "secret": creds.secret_key,
                "enableRateLimit": True,
                "options": {"defaultType": binance_type},
            }
        )
        if creds.testnet:
            client.set_sandbox_mode(True)
        return CcxtOrderClient(
            exchange_id,
            client,
            symbol_format=symbol_format,
            market_type=market_type,
            margin_mode=margin_mode,
        )
    raise ValueError(f"unsupported_exchange:{exchange}")


def _split_symbol(normalized: str) -> tuple[str, str]:
    """Split a symbol into base and quote, handling both formats.
    
    Handles:
    - "BTC-USDT" (with dash) -> ("BTC", "USDT")
    - "BTCUSDT" (no dash) -> ("BTC", "USDT")
    """
    if "-" in normalized:
        return tuple(normalized.split("-", 1))  # type: ignore
    
    # No dash - try to intelligently split based on common quote currencies
    # Check from longest to shortest to avoid partial matches
    quote_currencies = ["USDT", "USDC", "BUSD", "USD", "BTC", "ETH"]
    for quote in quote_currencies:
        if normalized.endswith(quote):
            base = normalized[:-len(quote)]
            if base:  # Ensure we have a base currency
                return (base, quote)
    
    # Fallback: assume 4-character quote currency at end (like USDT)
    if len(normalized) > 4:
        return (normalized[:-4], normalized[-4:])
    
    # Can't split - return as-is
    return (normalized, "USDT")


def _round_down_amount(client: Any, symbol: str, amount: float) -> float:
    if amount <= 0:
        return 0.0
    markets = getattr(client, "markets", None) or {}
    market = markets.get(symbol) if isinstance(markets, dict) else None
    precision = ((market or {}).get("precision") or {}).get("amount") if isinstance(market, dict) else None
    if isinstance(precision, int) and precision >= 0:
        factor = 10 ** precision
        return math.floor(amount * factor) / factor
    formatter = getattr(client, "amount_to_precision", None)
    if callable(formatter):
        try:
            return float(formatter(symbol, amount))
        except Exception:
            pass
    return amount


def _normalize_symbol(symbol: str, symbol_format: str, market_type: str = "perp") -> str:
    if symbol_format == "binance_spot":
        return normalize_exchange_symbol("binance", symbol, "spot") or symbol
    if symbol_format in {"okx", "bybit", "binance"}:
        exchange_id = "binance" if symbol_format.startswith("binance") else symbol_format
        converted = to_ccxt_market_symbol(exchange_id, symbol, market_type=market_type)
        if converted:
            return converted
    return symbol


def _preload_okx_markets(demo_client: Any) -> None:
    """Preload markets from OKX production for demo trading.
    
    OKX demo mode disables certain private endpoints that CCXT's load_markets()
    depends on. We work around this by loading markets from a production client
    and copying them to the demo client.
    """
    try:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context - schedule async preload
                log_info("okx_demo_markets_preload_deferred", reason="async_context")
                # Mark that markets need to be loaded
                demo_client._needs_markets_preload = True
                return
        except RuntimeError:
            pass
        # Load markets synchronously using sync CCXT
        import ccxt as ccxt_sync
        prod_sync = ccxt_sync.okx({
            "enableRateLimit": True,
            "options": {"defaultType": demo_client.options.get("defaultType", "swap")},
        })
        prod_sync.load_markets()
        demo_client.markets = prod_sync.markets
        demo_client.markets_by_id = prod_sync.markets_by_id
        demo_client.currencies = prod_sync.currencies
        demo_client.currencies_by_id = prod_sync.currencies_by_id
        log_info("okx_demo_markets_preloaded", count=len(prod_sync.markets))
    except Exception as e:
        log_warning("okx_demo_markets_preload_failed", error=str(e))


async def _preload_okx_markets_async(demo_client: Any) -> None:
    """Async version of market preloading for OKX demo trading."""
    if demo_client.markets:
        return  # Already loaded
    try:
        # Create a temporary production client without auth (public data only)
        prod_client = ccxt.okx({
            "enableRateLimit": True,
            "options": {"defaultType": demo_client.options.get("defaultType", "swap")},
        })
        await prod_client.load_markets()
        demo_client.markets = prod_client.markets
        demo_client.markets_by_id = prod_client.markets_by_id
        demo_client.currencies = prod_client.currencies
        demo_client.currencies_by_id = prod_client.currencies_by_id
        await prod_client.close()
        log_info("okx_demo_markets_preloaded_async", count=len(demo_client.markets))
    except Exception as e:
        log_warning("okx_demo_markets_preload_async_failed", error=str(e))


def _preload_bybit_markets(demo_client: Any) -> None:
    """Preload markets from Bybit mainnet for demo trading.
    
    Bybit demo trading only supports a limited subset of v5 APIs.
    Many endpoints like /v5/asset/coin/query-info are NOT supported.
    We preload markets from mainnet (public data) to avoid hitting unsupported endpoints.
    """
    try:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context - mark for deferred loading
                log_info("bybit_demo_markets_preload_deferred", reason="async_context")
                demo_client._needs_markets_preload = True
                return
        except RuntimeError:
            pass
        # Load markets synchronously using sync CCXT
        import ccxt as ccxt_sync
        prod_sync = ccxt_sync.bybit({
            "enableRateLimit": True,
            "options": {
                "defaultType": demo_client.options.get("defaultType", "swap"),
                "fetchCurrencies": False,  # Skip the problematic endpoint
            },
        })
        prod_sync.load_markets()
        demo_client.markets = prod_sync.markets
        demo_client.markets_by_id = prod_sync.markets_by_id
        demo_client.symbols = prod_sync.symbols
        demo_client.ids = prod_sync.ids
        demo_client.currencies = prod_sync.currencies
        demo_client.currencies_by_id = prod_sync.currencies_by_id
        log_info("bybit_demo_markets_preloaded", count=len(prod_sync.markets))
    except Exception as e:
        log_warning("bybit_demo_markets_preload_failed", error=str(e))


async def _preload_bybit_markets_async(demo_client: Any) -> None:
    """Async version of market preloading for Bybit demo trading."""
    if demo_client.markets:
        return  # Already loaded
    try:
        prod_client = ccxt.bybit({
            "enableRateLimit": True,
            "options": {
                "defaultType": demo_client.options.get("defaultType", "swap"),
                "fetchCurrencies": False,
            },
        })
        await prod_client.load_markets()
        demo_client.markets = prod_client.markets
        demo_client.markets_by_id = prod_client.markets_by_id
        demo_client.symbols = prod_client.symbols
        demo_client.ids = prod_client.ids
        demo_client.currencies = prod_client.currencies
        demo_client.currencies_by_id = prod_client.currencies_by_id
        await prod_client.close()
        log_info("bybit_demo_markets_preloaded_async", count=len(demo_client.markets))
    except Exception as e:
        log_warning("bybit_demo_markets_preload_async_failed", error=str(e))


def _normalize_order_side(side: str) -> str:
    """Normalize side to buy/sell as expected by exchanges."""
    normalized = (side or "").lower()
    if normalized in {"long", "buy"}:
        return "buy"
    if normalized in {"short", "sell"}:
        return "sell"
    return side  # Return as-is if not recognized


def _exit_side(side: str) -> str:
    normalized = (side or "").lower()
    if normalized in {"long", "buy"}:
        return "sell"
    if normalized in {"short", "sell"}:
        return "buy"
    return "sell"


def _protective_client_id(base_id: Optional[str], suffix: str) -> Optional[str]:
    if not base_id:
        return None
    return f"{base_id}:{suffix}"


def _sanitize_okx_client_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", value)
    if not normalized:
        return None
    return normalized[:32]


def _okx_tagged_client_id(base_id: Optional[str], suffix: str) -> Optional[str]:
    sanitized = _sanitize_okx_client_id(base_id)
    if not sanitized:
        return None
    tagged = f"{sanitized}{suffix}"
    return tagged[:32]


def _native_symbol(symbol: str, exchange: str) -> str:
    raw = symbol.upper().replace("/", "-")
    if exchange == "okx":
        return raw
    if exchange == "bybit":
        native = normalize_exchange_symbol(exchange, symbol, "spot")
        return str(native or "").upper()
    if exchange == "binance":
        native = normalize_exchange_symbol(exchange, symbol, "spot")
        return str(native or "").upper()
    return raw


def _spot_symbol(symbol: str) -> str:
    converted = to_ccxt_market_symbol("binance", symbol, market_type="spot")
    return converted or _native_symbol(symbol, "binance")


async def _place_okx_protective_orders(
    client: Any,
    symbol: str,
    side: str,
    size: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
    margin_mode: Optional[str],
) -> list[Any]:
    results = []
    params = {"reduceOnly": True}
    if margin_mode in {"isolated", "cross"}:
        params["marginMode"] = margin_mode
    if stop_loss is not None:
        order_params = dict(params)
        tagged = _okx_tagged_client_id(client_order_id, "sl")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="stop",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": stop_loss},
            )
        )
    if take_profit is not None:
        order_params = dict(params)
        tagged = _okx_tagged_client_id(client_order_id, "tp")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="take_profit",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": take_profit},
            )
        )
    return results


async def _place_bybit_protective_orders(
    client: Any,
    symbol: str,
    side: str,
    size: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
    margin_mode: Optional[str],
) -> list[Any]:
    results = []
    params = {"reduceOnly": True}
    if margin_mode in {"isolated", "cross"}:
        params["marginMode"] = margin_mode
    if stop_loss is not None:
        order_params = dict(params)
        tagged = _protective_client_id(client_order_id, "sl")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="stop",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": stop_loss},
            )
        )
    if take_profit is not None:
        order_params = dict(params)
        tagged = _protective_client_id(client_order_id, "tp")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="take_profit",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": take_profit},
            )
        )
    return results


async def _place_binance_protective_orders(
    client: Any,
    symbol: str,
    side: str,
    size: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
    margin_mode: Optional[str],
) -> list[Any]:
    results = []
    base_params = {"reduceOnly": True, "closePosition": True}
    if margin_mode in {"isolated", "cross"}:
        base_params["marginMode"] = margin_mode
    if stop_loss is not None:
        order_params = dict(base_params)
        tagged = _protective_client_id(client_order_id, "sl")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="STOP_MARKET",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": stop_loss},
            )
        )
    if take_profit is not None:
        order_params = dict(base_params)
        tagged = _protective_client_id(client_order_id, "tp")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="TAKE_PROFIT_MARKET",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": take_profit},
            )
        )
    return results


async def _place_generic_protective_orders(
    client: Any,
    symbol: str,
    side: str,
    size: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
    margin_mode: Optional[str],
) -> list[Any]:
    results = []
    params = {"reduceOnly": True}
    if margin_mode in {"isolated", "cross"}:
        params["marginMode"] = margin_mode
    if stop_loss is not None:
        order_params = dict(params)
        tagged = _protective_client_id(client_order_id, "sl")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="stop",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": stop_loss},
            )
        )
    if take_profit is not None:
        order_params = dict(params)
        tagged = _protective_client_id(client_order_id, "tp")
        if tagged:
            order_params["clientOrderId"] = tagged
        results.append(
            await client.create_order(
                symbol=symbol,
                type="take_profit",
                side=side,
                amount=size,
                price=None,
                params={**order_params, "stopPrice": take_profit},
            )
        )
    return results


async def _okx_native_oco(
    client: Any,
    symbol: str,
    side: str,
    size: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
    margin_mode: Optional[str] = None,
) -> Any:
    method = getattr(client, "privatePostTradeOrderAlgo", None) or getattr(client, "private_post_trade_order_algo", None)
    if method is None:
        return None
    params: dict[str, Any] = {
        "instId": symbol,
        "tdMode": "isolated" if (margin_mode or "").lower() == "isolated" else "cross",
        "side": side,
        "sz": str(size),
    }
    if client_order_id:
        suffix = "oco" if (stop_loss is not None and take_profit is not None) else ("sl" if stop_loss else "tp")
        tagged = _okx_tagged_client_id(client_order_id, suffix)
        if tagged:
            params["clOrdId"] = tagged
    if stop_loss is not None and take_profit is not None:
        params.update(
            {
                "ordType": "oco",
                "slTriggerPx": str(stop_loss),
                "slOrdPx": "-1",
                "tpTriggerPx": str(take_profit),
                "tpOrdPx": "-1",
            }
        )
    else:
        trigger_px = stop_loss if stop_loss is not None else take_profit
        params.update(
            {
                "ordType": "conditional",
                "triggerPx": str(trigger_px),
                "orderPx": "-1",
            }
        )
    return await method(params)


async def _bybit_native_tpsl(
    client: Any,
    symbol: str,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
    margin_mode: Optional[str] = None,
) -> Any:
    method = getattr(client, "privatePostV5PositionTradingStop", None) or getattr(
        client, "private_post_v5_position_trading_stop", None
    )
    if method is None:
        return None
    params: dict[str, Any] = {
        "category": "linear",
        "symbol": symbol,
        "tpslMode": "Full",
    }
    if stop_loss is not None:
        params["stopLoss"] = str(stop_loss)
        params["slOrderType"] = "Market"  # SL must be market for safety
    if take_profit is not None:
        params["takeProfit"] = str(take_profit)
        # Bybit Full-mode TP only supports Market
        params["tpOrderType"] = "Market"
    if client_order_id:
        suffix = "tpsl" if (stop_loss is not None and take_profit is not None) else ("sl" if stop_loss else "tp")
        tagged = _protective_client_id(client_order_id, suffix)
        if tagged:
            params["orderLinkId"] = tagged
    return await method(params)


async def _binance_spot_oco(
    client: Any,
    symbol: str,
    side: str,
    size: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    client_order_id: Optional[str],
) -> Any:
    if stop_loss is None or take_profit is None:
        return None
    method = getattr(client, "privatePostOrderOco", None) or getattr(client, "private_post_order_oco", None)
    if method is None:
        return None
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": side.upper(),
        "quantity": str(size),
        "price": str(take_profit),
        "stopPrice": str(stop_loss),
        "stopLimitPrice": str(stop_loss),
        "stopLimitTimeInForce": "GTC",
    }
    if client_order_id:
        tagged = _protective_client_id(client_order_id, "oco")
        if tagged:
            params["listClientOrderId"] = tagged
    return await method(params)
