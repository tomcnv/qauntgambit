"""Shared market-data ingestion service (orderbook-focused).

Wires exchange WS providers from quantgambit, publishes tenant-neutral snapshots/deltas
to Redis Streams, and exposes basic health (Redis + HTTP).
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
try:
    import orjson as _orjson
except ImportError:
    _orjson = None
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import redis.asyncio as redis
from aiohttp import web

from quantgambit.ingest.orderbook_ws import (
    WebsocketConfig,
    OkxOrderbookWebsocketProvider,
    BybitOrderbookWebsocketProvider,
    BinanceOrderbookWebsocketProvider,
    MultiplexOrderbookProvider,
)
from quantgambit.ingest.trade_ws import (
    TradeWebsocketConfig,
    OkxTradeWebsocketProvider,
    BybitTradeWebsocketProvider,
    BinanceTradeWebsocketProvider,
    MultiplexTradeProvider,
)
from quantgambit.ingest.time_utils import now_recv_us, us_to_sec, normalize_exchange_ts_to_sec
from quantgambit.market.ws_provider import (
    OkxTickerWebsocketProvider,
    BybitTickerWebsocketProvider,
    BinanceTickerWebsocketProvider,
    MultiplexTickerProvider,
)
from quantgambit.observability.logger import configure_logging, log_info, log_error, log_warning


@dataclass
class ServiceConfig:
    exchange: str
    market_type: str
    symbols: list[str]
    redis_url: str = "redis://localhost:6379"
    snapshot_interval_sec: float = 30.0
    health_staleness_ms: int = 5000
    max_symbols: int = 25
    testnet: bool = False
    heartbeat_key: Optional[str] = None
    service_id: str = "mds"
    publish_mode: str = "streams"  # streams|events|both
    orderbook_stream_prefix: str = "orderbook"
    orderbook_event_stream: str = "events:orderbook_feed"
    trades_enabled: bool = False
    tickers_enabled: bool = False
    seq_start: int = 1_000_000
    seq_state: dict = field(default_factory=dict)
    book_state: dict = field(default_factory=dict)  # Accumulated orderbook state per symbol
    trade_stream_prefix: str = "trades"
    market_data_stream: str = "events:market_data"
    trade_event_stream: str = "events:trades"
    ticker_stream_prefix: str = "ticker"
    publish_maxlen: int = 50000  # Increased for better retention
    max_stream_length: int = 50000  # Match publish_maxlen
    backpressure_sleep_ms: int = 10  # Reduced for better throughput
    tenant_id: str = "shared"
    bot_id: str = "shared"
    # Separate public data WS from private/demo endpoints
    # Public market data always uses mainnet for stability (orderbook/trades)
    # Private/demo endpoints only for orders/positions
    use_mainnet_public_ws: bool = True  # Always use mainnet for public data
    # WS-only snapshot mode (disable REST snapshots for orderbook)
    orderbook_ws_only_snapshot: bool = False
    # Health tracking
    health_key: str = ""  # Redis key for MDS health metrics
    # Staleness thresholds for watchdog
    trade_stale_sec: float = 30.0  # Trigger resync if no trade for this long
    orderbook_stale_sec: float = 30.0  # Trigger resync if no orderbook for this long
    resync_cooldown_sec: float = 5.0  # Minimum seconds between resyncs per symbol
    # Crossed book handling
    crossed_resync_threshold: int = 3  # Consecutive crosses before resync
    crossed_resync_window_sec: float = 2.0  # Window to count consecutive crosses
    # Skip stale deltas by exchange timestamp age to avoid book pollution
    orderbook_delta_max_age_sec: float = 5.0
    # Backoff configuration
    backoff_trigger_count: int = 3  # Number of failures before entering backoff
    backoff_window_sec: float = 120.0  # Window to count failures
    backoff_duration_sec: float = 60.0  # How long to stay in backoff mode
    # Flow control - pacing and batching
    coalesce_orderbook_ms: float = 50.0  # Coalesce orderbook updates within this window
    coalesce_trades_ms: float = 0.0  # Don't coalesce trades (need every one)
    batch_publish_size: int = 10  # Batch this many updates before publishing
    batch_publish_timeout_ms: float = 100.0  # Max wait before publishing batch
    # Backlog tiers for flow control
    soft_backlog_threshold: int = 10000  # Warn and reduce publish rate
    hard_backlog_threshold: int = 30000  # Aggressive trimming
    # Orderbook compaction
    orderbook_top_n_levels: int = 20  # Keep top N levels when compacting


def _normalize_symbol(exchange: str, symbol: str) -> str:
    normalized_exchange = (exchange or "").lower()
    raw = symbol.strip()
    if normalized_exchange == "okx":
        if "/" in raw:
            base, quote = raw.replace(":USDT", "").split("/", 1)
            return f"{base}-{quote}-SWAP"
        return raw
    if normalized_exchange in {"bybit", "binance"}:
        clean = raw.replace("-SWAP", "").replace("-", "").replace("/", "")
        return clean.upper()
    return raw


def _build_orderbook_provider(cfg: ServiceConfig):
    ws_cfg = WebsocketConfig(
        recv_timeout_sec=float(os.getenv("ORDERBOOK_WS_RECV_TIMEOUT_SEC", "10")),
        heartbeat_interval_sec=float(os.getenv("ORDERBOOK_WS_HEARTBEAT_SEC", "20")),
        snapshot_interval_sec=float(os.getenv("ORDERBOOK_WS_SNAPSHOT_SEC", str(cfg.snapshot_interval_sec))),
    )
    providers = []
    normalized = (cfg.exchange or "").lower()
    # CRITICAL: For public market data, always use mainnet WS for stability
    # testnet/demo is only for private/order endpoints
    use_testnet_for_data = cfg.testnet and not cfg.use_mainnet_public_ws
    bybit_include_l1 = os.getenv("BYBIT_ORDERBOOK_INCLUDE_L1", "false").lower() in {"1", "true", "yes"}
    bybit_ws_only_snapshot = os.getenv("BYBIT_ORDERBOOK_WS_ONLY", "false").lower() in {"1", "true", "yes"}
    
    log_info(
        "mds_orderbook_provider_config",
        exchange=normalized,
        symbols=cfg.symbols[:cfg.max_symbols],
        use_mainnet_public_ws=cfg.use_mainnet_public_ws,
        testnet_config=cfg.testnet,
        effective_testnet=use_testnet_for_data,
        ws_only_snapshot=bybit_ws_only_snapshot if normalized == "bybit" else False,
    )
    
    for sym in cfg.symbols[: cfg.max_symbols]:
        if normalized == "okx":
            providers.append(OkxOrderbookWebsocketProvider(sym, testnet=use_testnet_for_data, market_type=cfg.market_type, config=ws_cfg))
        elif normalized == "bybit":
            # Keep L1 and L2 on separate sockets when enabled to avoid L1 throughput
            # impacting depth stream latency/quality.
            if bybit_include_l1:
                providers.append(
                    BybitOrderbookWebsocketProvider(
                        sym,
                        testnet=use_testnet_for_data,
                        market_type=cfg.market_type,
                        config=ws_cfg,
                        include_l1_heartbeat=False,
                        include_l2_depth=True,
                        use_rest_snapshot=not bybit_ws_only_snapshot,
                    )
                )
                providers.append(
                    BybitOrderbookWebsocketProvider(
                        sym,
                        testnet=use_testnet_for_data,
                        market_type=cfg.market_type,
                        config=ws_cfg,
                        include_l1_heartbeat=True,
                        include_l2_depth=False,
                        use_rest_snapshot=False,
                    )
                )
            else:
                providers.append(
                    BybitOrderbookWebsocketProvider(
                        sym,
                        testnet=use_testnet_for_data,
                        market_type=cfg.market_type,
                        config=ws_cfg,
                        include_l1_heartbeat=False,
                        include_l2_depth=True,
                        use_rest_snapshot=not bybit_ws_only_snapshot,
                    )
                )
        elif normalized == "binance":
            providers.append(BinanceOrderbookWebsocketProvider(sym, testnet=use_testnet_for_data, market_type=cfg.market_type, config=ws_cfg))
    if not providers:
        log_warning("mds_no_orderbook_providers", exchange=normalized)
        return None
    log_info("mds_orderbook_providers_built", exchange=normalized, count=len(providers))
    if len(providers) == 1:
        return providers[0]
    return MultiplexOrderbookProvider(providers)


def _build_trade_provider(cfg: ServiceConfig):
    trade_cfg = TradeWebsocketConfig(
        reconnect_delay_sec=float(os.getenv("TRADE_WS_RECONNECT_SEC", "1")),
        max_reconnect_delay_sec=float(os.getenv("TRADE_WS_MAX_RECONNECT_SEC", "10")),
        backoff_multiplier=float(os.getenv("TRADE_WS_BACKOFF_MULTIPLIER", "2")),
        heartbeat_interval_sec=float(os.getenv("TRADE_WS_HEARTBEAT_SEC", "20")),
        message_timeout_sec=float(os.getenv("TRADE_WS_MESSAGE_TIMEOUT_SEC", "10")),
        stale_guardrail_sec=float(os.getenv("TRADE_WS_STALE_GUARDRAIL_SEC", "60")),
        stale_watchdog_sec=float(os.getenv("TRADE_WS_STALE_WATCHDOG_SEC", "45")),
        # REST fallback only for seeding/gap-fill, not continuous polling
        rest_fallback_enabled=os.getenv("TRADE_REST_FALLBACK_ENABLED", "false").lower() in {"1", "true", "yes"},
        rest_fallback_interval_sec=float(os.getenv("TRADE_REST_FALLBACK_INTERVAL_SEC", "30")),
        rest_fallback_limit=int(os.getenv("TRADE_REST_FALLBACK_LIMIT", "5")),
    )
    providers = []
    normalized = (cfg.exchange or "").lower()
    # CRITICAL: For public market data, always use mainnet WS for stability
    # testnet/demo is only for private/order endpoints
    use_testnet_for_data = cfg.testnet and not cfg.use_mainnet_public_ws
    
    log_info(
        "mds_trade_provider_config",
        exchange=normalized,
        symbols=cfg.symbols[:cfg.max_symbols],
        use_mainnet_public_ws=cfg.use_mainnet_public_ws,
        testnet_config=cfg.testnet,
        effective_testnet=use_testnet_for_data,
        rest_fallback_enabled=trade_cfg.rest_fallback_enabled,
        stale_watchdog_sec=trade_cfg.stale_watchdog_sec,
    )
    
    for sym in cfg.symbols[: cfg.max_symbols]:
        if normalized == "okx":
            providers.append(OkxTradeWebsocketProvider(sym, testnet=use_testnet_for_data, config=trade_cfg))
        elif normalized == "bybit":
            providers.append(BybitTradeWebsocketProvider(sym, market_type=cfg.market_type, testnet=use_testnet_for_data, config=trade_cfg))
        elif normalized == "binance":
            providers.append(BinanceTradeWebsocketProvider(sym, market_type=cfg.market_type, testnet=use_testnet_for_data, config=trade_cfg))
    if not providers:
        log_warning("mds_no_trade_providers", exchange=normalized)
        return None
    log_info("mds_trade_providers_built", exchange=normalized, count=len(providers))
    if len(providers) == 1:
        return providers[0]
    return MultiplexTradeProvider(providers)


def _build_ticker_provider(cfg: ServiceConfig):
    providers = []
    normalized = (cfg.exchange or "").lower()
    for sym in cfg.symbols[: cfg.max_symbols]:
        if normalized == "okx":
            providers.append(OkxTickerWebsocketProvider(sym, testnet=cfg.testnet))
        elif normalized == "bybit":
            providers.append(BybitTickerWebsocketProvider(sym, market_type=cfg.market_type, testnet=cfg.testnet))
        elif normalized == "binance":
            providers.append(BinanceTickerWebsocketProvider(sym, market_type=cfg.market_type, testnet=cfg.testnet))
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return MultiplexTickerProvider(providers)


async def _start_http_health(app_state, redis_client):
    async def handle(_request):
        depths = {"orderbook": {}, "trades": {}, "tickers": {}}
        cfg = app_state["cfg"]
        try:
            # Limit to configured symbols to avoid expensive scans
            for sym in cfg.symbols[: cfg.max_symbols]:
                ob_stream = f"{cfg.orderbook_stream_prefix}:{cfg.exchange}:{cfg.market_type}:{sym}"
                depths["orderbook"][sym] = await redis_client.xlen(ob_stream)
                if cfg.trades_enabled:
                    trade_stream = f"{cfg.trade_stream_prefix}:{cfg.exchange}:{cfg.market_type}:{sym}"
                    depths["trades"][sym] = await redis_client.xlen(trade_stream)
                if cfg.tickers_enabled:
                    ticker_stream = f"{cfg.ticker_stream_prefix}:{cfg.exchange}:{cfg.market_type}:{sym}"
                    depths["tickers"][sym] = await redis_client.xlen(ticker_stream)
        except Exception as exc:
            app_state["last_error"] = str(exc)
        return web.json_response(
            {
                "status": "ok",
                "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                "market_type": cfg.market_type,
                "symbols": cfg.symbols,
                "publish_mode": cfg.publish_mode,
                "orderbook_stream_prefix": cfg.orderbook_stream_prefix,
                "orderbook_event_stream": cfg.orderbook_event_stream,
                "trades_enabled": cfg.trades_enabled,
                "tickers_enabled": cfg.tickers_enabled,
                "counts": {
                    "orderbook": app_state["counters"].get("orderbook", 0),
                    "trades": app_state["counters"].get("trades", 0),
                    "tickers": app_state["counters"].get("tickers", 0),
                },
                "depths": depths,
                "last_error": app_state.get("last_error"),
            }
        )

    app = web.Application()
    app.add_routes([web.get("/health", handle), web.get("/live", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=int(os.getenv("PORT", "8081")))
    await site.start()
    return runner


def _parse_env() -> ServiceConfig:
    exchange = os.getenv("EXCHANGE", "").strip()
    market_type = os.getenv("MARKET_TYPE", "perp").strip() or "perp"
    raw_symbols = os.getenv("SYMBOLS", "")
    if not exchange:
        raise ValueError("EXCHANGE is required (okx|bybit|binance)")
    symbols = [_normalize_symbol(exchange, s) for s in raw_symbols.split(",") if s.strip()]
    if not symbols:
        raise ValueError("SYMBOLS is required (comma-separated)")
    exchange_lower = exchange.lower()
    bybit_ws_only = os.getenv("BYBIT_ORDERBOOK_WS_ONLY", "false").lower() in {"1", "true", "yes"}
    ws_only_global = os.getenv("ORDERBOOK_WS_ONLY_SNAPSHOT", "false").lower() in {"1", "true", "yes"}
    orderbook_ws_only = ws_only_global or (exchange_lower == "bybit" and bybit_ws_only)
    return ServiceConfig(
        exchange=exchange,
        market_type=market_type,
        symbols=symbols,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        snapshot_interval_sec=float(os.getenv("SNAPSHOT_INTERVAL_SEC", "10")),
        health_staleness_ms=int(os.getenv("HEALTH_STALENESS_MS", "5000")),
        max_symbols=int(os.getenv("MAX_SYMBOLS_PER_PROCESS", "25")),
        testnet=os.getenv("TESTNET", "false").lower() in {"1", "true", "yes"},
        heartbeat_key=f"mds:heartbeat:{exchange}:{os.getpid()}",
        service_id=os.getenv("SERVICE_ID", "mds"),
        publish_mode=os.getenv("PUBLISH_MODE", "streams").lower(),
        orderbook_stream_prefix=os.getenv("ORDERBOOK_STREAM_PREFIX", "orderbook"),
        orderbook_event_stream=os.getenv("ORDERBOOK_EVENT_STREAM", "events:orderbook_feed"),
        trades_enabled=os.getenv("TRADES_ENABLED", "false").lower() in {"1", "true", "yes"},
        tickers_enabled=os.getenv("TICKERS_ENABLED", "false").lower() in {"1", "true", "yes"},
        market_data_stream=os.getenv("MARKET_DATA_STREAM", "events:market_data"),
        trade_event_stream=os.getenv("TRADE_EVENT_STREAM", "events:trades"),
        seq_start=int(os.getenv("SEQ_START", "1000000")),
        max_stream_length=int(os.getenv("MAX_STREAM_LENGTH", "10000")),
        # Keep a larger backlog so the runtime consumer doesn't miss deltas and mark gaps.
        publish_maxlen=int(os.getenv("PUBLISH_MAXLEN", "10000")),
        backpressure_sleep_ms=int(os.getenv("BACKPRESSURE_SLEEP_MS", "10")),
        tenant_id=(os.getenv("TENANT_ID", "shared").strip() or "shared"),
        bot_id=(os.getenv("BOT_ID", "shared").strip() or "shared"),
        # Public data WS: always use mainnet for stability (default True)
        use_mainnet_public_ws=os.getenv("USE_MAINNET_PUBLIC_WS", "true").lower() in {"1", "true", "yes"},
        orderbook_ws_only_snapshot=orderbook_ws_only,
        # Health tracking
        health_key=os.getenv("MDS_HEALTH_KEY", f"mds:health:{exchange}"),
        # Staleness thresholds
        trade_stale_sec=float(os.getenv("TRADE_STALE_SEC", "30")),
        orderbook_stale_sec=float(os.getenv("ORDERBOOK_STALE_SEC", "30")),
        resync_cooldown_sec=float(os.getenv("ORDERBOOK_RESYNC_COOLDOWN_SEC", "5.0")),
        crossed_resync_threshold=int(os.getenv("CROSSED_RESYNC_THRESHOLD", "3")),
        crossed_resync_window_sec=float(os.getenv("CROSSED_RESYNC_WINDOW_SEC", "2.0")),
        orderbook_delta_max_age_sec=float(os.getenv("ORDERBOOK_DELTA_MAX_AGE_SEC", "5.0")),
        # Backoff configuration
        backoff_trigger_count=int(os.getenv("BACKOFF_TRIGGER_COUNT", "3")),
        backoff_window_sec=float(os.getenv("BACKOFF_WINDOW_SEC", "120")),
        backoff_duration_sec=float(os.getenv("BACKOFF_DURATION_SEC", "60")),
        # Flow control - pacing and batching
        coalesce_orderbook_ms=float(os.getenv("COALESCE_ORDERBOOK_MS", "50")),
        coalesce_trades_ms=float(os.getenv("COALESCE_TRADES_MS", "0")),
        batch_publish_size=int(os.getenv("BATCH_PUBLISH_SIZE", "10")),
        batch_publish_timeout_ms=float(os.getenv("BATCH_PUBLISH_TIMEOUT_MS", "100")),
        # Backlog tiers
        soft_backlog_threshold=int(os.getenv("SOFT_BACKLOG_THRESHOLD", "10000")),
        hard_backlog_threshold=int(os.getenv("HARD_BACKLOG_THRESHOLD", "30000")),
        # Orderbook compaction
        orderbook_top_n_levels=int(os.getenv("ORDERBOOK_TOP_N_LEVELS", "20")),
    )


def _compact_levels(levels):
    out = []
    for lvl in levels or []:
        try:
            price = float(lvl[0])
            size = float(lvl[1])
        except Exception:
            continue
        out.append([price, size])
    return out


async def run() -> None:
    configure_logging()
    try:
        cfg = _parse_env()
    except Exception as exc:
        log_error("mds_config_invalid", error=str(exc))
        sys.exit(1)

    log_info("mds_starting", exchange=cfg.exchange, market_type=cfg.market_type, symbols=cfg.symbols)

    provider = _build_orderbook_provider(cfg)
    if provider is None:
        log_error("mds_no_orderbook_provider_built", exchange=cfg.exchange)
        sys.exit(1)
    trade_provider = _build_trade_provider(cfg) if cfg.trades_enabled else None
    ticker_provider = _build_ticker_provider(cfg) if cfg.tickers_enabled else None

    redis_client = redis.from_url(cfg.redis_url)
    stop_event = asyncio.Event()

    def _handle_stop(*_args):
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    def _next_canon_us(symbol: str, recv_us: int) -> int:
        """Ensure per-symbol monotonic canonical timestamps (microseconds)."""
        last_map = app_state.setdefault("last_event_ts_us", {})
        last_val = last_map.get(symbol)
        if last_val is None or recv_us > last_val:
            canon = recv_us
        else:
            canon = last_val + 1
        last_map[symbol] = canon
        return canon

    def _merge_orderbook_state(symbol: str, update_type: str, new_bids: list, new_asks: list, compact: bool = False) -> tuple:
        """
        Merge delta updates into accumulated orderbook state.
        
        For snapshots: replace entire state
        For deltas: update/remove levels by price (size=0 means remove)
        
        CRITICAL FIX: Detects and auto-resets crossed orderbooks (bid > ask)
        which can occur when stale delta levels accumulate.
        
        Args:
            symbol: Trading pair symbol
            update_type: "snapshot" or "delta"
            new_bids: List of [price, size] bid updates
            new_asks: List of [price, size] ask updates
            compact: If True, use cfg.orderbook_top_n_levels instead of 50
        
        Returns: (merged_bids, merged_asks) as sorted lists
        """
        # Always capture previous state so we can fall back on crossed updates.
        state = cfg.book_state.get(symbol, {"bids": {}, "asks": {}})
        prev_bid_dict = dict(state["bids"])
        prev_ask_dict = dict(state["asks"])
        if update_type == "snapshot":
            # Snapshot: replace entire state
            bid_dict = {float(b[0]): float(b[1]) for b in new_bids if len(b) >= 2}
            ask_dict = {float(a[0]): float(a[1]) for a in new_asks if len(a) >= 2}
        else:
            # Delta: merge into existing state
            bid_dict = dict(prev_bid_dict)
            ask_dict = dict(prev_ask_dict)
            
            # Apply bid updates
            for b in new_bids:
                if len(b) < 2:
                    continue
                price, size = float(b[0]), float(b[1])
                if size == 0:
                    bid_dict.pop(price, None)  # Remove level
                else:
                    bid_dict[price] = size  # Update level
            
            # Apply ask updates
            for a in new_asks:
                if len(a) < 2:
                    continue
                price, size = float(a[0]), float(a[1])
                if size == 0:
                    ask_dict.pop(price, None)  # Remove level
                else:
                    ask_dict[price] = size  # Update level
        
        # CRITICAL: Detect crossed orderbook (bid > ask) and auto-reset
        # This happens when stale delta levels accumulate
        if bid_dict and ask_dict:
            best_bid = max(bid_dict.keys())
            best_ask = min(ask_dict.keys())
            
            if best_bid > best_ask:
                # Crossed market detected! Log and reset to incoming data only
                spread_bps = ((best_bid - best_ask) / best_ask) * 10000
                now = time.time()
                streaks = app_state.setdefault("crossed_streak", {})
                last_info = streaks.get(symbol, {"count": 0, "last_ts": 0.0})
                if now - last_info.get("last_ts", 0.0) > getattr(cfg, "crossed_resync_window_sec", 2.0):
                    crossed_count = 1
                else:
                    crossed_count = last_info.get("count", 0) + 1
                streaks[symbol] = {"count": crossed_count, "last_ts": now}
                should_resync = crossed_count >= getattr(cfg, "crossed_resync_threshold", 3)
                
                # Track crossed market occurrences
                if "crossed_market_count" not in app_state:
                    app_state["crossed_market_count"] = {}
                app_state["crossed_market_count"][symbol] = app_state["crossed_market_count"].get(symbol, 0) + 1
                
                # Log at most once per 10 seconds per symbol to avoid spam
                last_log_key = f"last_crossed_log_{symbol}"
                last_log = app_state.get(last_log_key, 0)
                if now - last_log > 10:
                    app_state[last_log_key] = now
                    log_warning(
                        "mds_crossed_orderbook_detected",
                        symbol=symbol,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        spread_bps=round(spread_bps, 2),
                        bid_levels=len(bid_dict),
                        ask_levels=len(ask_dict),
                        update_type=update_type,
                        action="resync" if should_resync else "holding_last_good",
                        crossed_count=crossed_count,
                        resync_threshold=getattr(cfg, "crossed_resync_threshold", 3),
                    )
                
                # Keep the last known good state; only trigger resync after threshold.
                if prev_bid_dict is not None and prev_ask_dict is not None:
                    bid_dict = prev_bid_dict
                    ask_dict = prev_ask_dict
                if should_resync:
                    if "resync_pending" not in app_state:
                        app_state["resync_pending"] = {}
                    app_state["resync_pending"][symbol] = {
                        "reason": "crossed_orderbook",
                        "ts": now,
                    }
                
                # If still crossed after reset (bad incoming data), use only best levels
                if bid_dict and ask_dict:
                    new_best_bid = max(bid_dict.keys())
                    new_best_ask = min(ask_dict.keys())
                    if new_best_bid > new_best_ask:
                        # Incoming data itself is crossed - keep only non-overlapping levels
                        # Remove bids >= best_ask and asks <= best_bid
                        mid_price = (new_best_bid + new_best_ask) / 2
                        bid_dict = {p: s for p, s in bid_dict.items() if p < mid_price}
                        ask_dict = {p: s for p, s in ask_dict.items() if p > mid_price}
        
        else:
            # Clear crossed streak on healthy updates
            streaks = app_state.get("crossed_streak")
            if isinstance(streaks, dict):
                streaks.pop(symbol, None)

        # Prune levels that are too far from best bid/ask (stale level cleanup)
        # This prevents accumulation of stale levels over time
        if bid_dict and ask_dict:
            best_bid = max(bid_dict.keys()) if bid_dict else 0
            best_ask = min(ask_dict.keys()) if ask_dict else float('inf')
            mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask != float('inf') else best_bid or best_ask
            
            # Allow 2% deviation from mid price (generous for volatile markets)
            max_deviation = mid_price * 0.02
            
            # Prune bids that are too far below best bid
            min_valid_bid = best_bid - max_deviation
            bid_dict = {p: s for p, s in bid_dict.items() if p >= min_valid_bid}
            
            # Prune asks that are too far above best ask
            max_valid_ask = best_ask + max_deviation
            ask_dict = {p: s for p, s in ask_dict.items() if p <= max_valid_ask}
        
        # Store updated state
        cfg.book_state[symbol] = {"bids": bid_dict, "asks": ask_dict}
        
        # Determine how many levels to keep based on backlog tier
        # Under load (soft/hard tier), compact to top-N to reduce publish volume
        if compact or app_state.get("backlog_tier") == "hard":
            top_n = cfg.orderbook_top_n_levels  # Default 20
            if "compacted_count" not in app_state:
                app_state["compacted_count"] = 0
            app_state["compacted_count"] += 1
        elif app_state.get("backlog_tier") == "soft":
            top_n = 30  # Slightly reduced under soft tier
        else:
            top_n = 50  # Full depth when healthy
        
        # Convert to sorted lists (bids descending, asks ascending)
        merged_bids = sorted([[p, s] for p, s in bid_dict.items()], key=lambda x: -x[0])[:top_n]
        merged_asks = sorted([[p, s] for p, s in ask_dict.items()], key=lambda x: x[0])[:top_n]
        
        return merged_bids, merged_asks

    async def _publish_update(update: dict):
        payload = update.get("payload") if isinstance(update, dict) else None
        if not payload:
            return
        update_type = update.get("type") or "snapshot"
        symbol = payload.get("symbol")
        if not symbol:
            return
        stream_prefix = f"{cfg.orderbook_stream_prefix}:{cfg.exchange}:{cfg.market_type}"
        stream = f"{stream_prefix}:{symbol}"
        seq = payload.get("seq")
        if seq is None:
            seq = cfg.seq_state.get(symbol, cfg.seq_start)
        cfg.seq_state[symbol] = (seq or cfg.seq_start) + 1
        
        now = time.time()
        exchange_ts = payload.get("timestamp") or payload.get("ts")
        exchange_ts_s = normalize_exchange_ts_to_sec(exchange_ts)
        # Use current time as canonical publish timestamp; preserve exchange ts separately.
        timestamp = now
        
        # Merge delta into accumulated state (or replace on snapshot)
        raw_bids = _compact_levels(payload.get("bids"))
        raw_asks = _compact_levels(payload.get("asks"))
        is_l1 = bool(payload.get("is_l1")) or payload.get("book_level") == 1
        if is_l1:
            if "orderbook_l1_total_count" not in app_state:
                app_state["orderbook_l1_total_count"] = {}
            if "orderbook_l1_cts_count" not in app_state:
                app_state["orderbook_l1_cts_count"] = {}
            app_state["orderbook_l1_total_count"][symbol] = (
                app_state["orderbook_l1_total_count"].get(symbol, 0) + 1
            )
            if payload.get("cts_ms") is not None:
                app_state["orderbook_l1_cts_count"][symbol] = (
                    app_state["orderbook_l1_cts_count"].get(symbol, 0) + 1
                )
            # L1 updates should never mutate the full book; emit only market ticks.
            if raw_bids and raw_asks:
                try:
                    best_bid = float(raw_bids[0][0])
                    best_ask = float(raw_asks[0][0])
                except (IndexError, TypeError, ValueError):
                    best_bid = None
                    best_ask = None
                if best_bid and best_ask:
                    last_tick_ts = app_state.get("last_l1_tick_ts", {}).get(symbol, 0)
                    if time.time() - last_tick_ts >= 0.1:  # 100ms throttle
                        if "last_l1_tick_ts" not in app_state:
                            app_state["last_l1_tick_ts"] = {}
                        app_state["last_l1_tick_ts"][symbol] = time.time()
                        recv_us = now_recv_us()
                        ts_canon_us = _next_canon_us(symbol, recv_us)
                        ts_canon_s = us_to_sec(ts_canon_us)
                        exchange_ts_s = normalize_exchange_ts_to_sec(exchange_ts)
                        market_tick = {
                            "event_id": f"{cfg.service_id}:{symbol}:{seq}:l1",
                            "event_type": "market_tick",
                            "schema_version": "v1",
                            "timestamp": str(ts_canon_s),
                            "ts_recv_us": recv_us,
                            "ts_canon_us": ts_canon_us,
                            "ts_exchange_s": exchange_ts_s,
                            "bot_id": cfg.bot_id,
                            "tenant_id": cfg.tenant_id,
                            "symbol": symbol,
                            "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                            "market_type": cfg.market_type,
                            "payload": {
                                "symbol": symbol,
                                "timestamp": ts_canon_s,
                                "ts_recv_us": recv_us,
                                "ts_canon_us": ts_canon_us,
                                "ts_exchange_s": exchange_ts_s,
                                "cts_ms": payload.get("cts_ms"),
                                "bid": best_bid,
                                "ask": best_ask,
                                "last": (best_bid + best_ask) / 2,
                                "source": "orderbook_l1",
                            },
                        }
                        await redis_client.xadd(
                            cfg.market_data_stream,
                            {"data": _to_json(market_tick)},
                            maxlen=cfg.publish_maxlen,
                            approximate=True,
                        )
            app_state["last_orderbook_l1_ts"][symbol] = time.time()
            if exchange_ts_s is not None:
                app_state["last_orderbook_exchange_l1_ts"][symbol] = float(exchange_ts_s)
            return
        if "orderbook_l2_total_count" not in app_state:
            app_state["orderbook_l2_total_count"] = {}
        if "orderbook_l2_cts_count" not in app_state:
            app_state["orderbook_l2_cts_count"] = {}
        app_state["orderbook_l2_total_count"][symbol] = (
            app_state["orderbook_l2_total_count"].get(symbol, 0) + 1
        )
        if payload.get("cts_ms") is not None:
            app_state["orderbook_l2_cts_count"][symbol] = (
                app_state["orderbook_l2_cts_count"].get(symbol, 0) + 1
            )

        delta_cts_ms = payload.get("cts_ms")
        delta_age_sec = None
        if delta_cts_ms is not None:
            try:
                delta_age_sec = (now * 1000.0 - float(delta_cts_ms)) / 1000.0
            except (TypeError, ValueError):
                delta_age_sec = None
        if (
            update_type == "delta"
            and delta_age_sec is not None
            and cfg.orderbook_delta_max_age_sec > 0
            and delta_age_sec > cfg.orderbook_delta_max_age_sec
        ):
            if "stale_delta_skipped_count" not in app_state:
                app_state["stale_delta_skipped_count"] = {}
            app_state["stale_delta_skipped_count"][symbol] = (
                app_state["stale_delta_skipped_count"].get(symbol, 0) + 1
            )
            log_warning(
                "mds_stale_delta_skipped",
                symbol=symbol,
                age_sec=round(delta_age_sec, 3),
                max_age_sec=cfg.orderbook_delta_max_age_sec,
                skipped_count=app_state["stale_delta_skipped_count"][symbol],
            )
            return

        merged_bids, merged_asks = _merge_orderbook_state(symbol, update_type, raw_bids, raw_asks)
        
        # If a crossed book was detected during merge, trigger a resync and skip publish.
        pending = app_state.get("resync_pending", {})
        pending_info = pending.pop(symbol, None) if isinstance(pending, dict) else None
        if pending_info:
            reason = pending_info.get("reason") if isinstance(pending_info, dict) else "crossed_orderbook"
            now = time.time()
            last_resync = app_state.get("last_resync_ts", {}).get(symbol, 0.0)
            cooldown = cfg.resync_cooldown_sec
            if now - last_resync >= cooldown:
                if "last_resync_ts" not in app_state:
                    app_state["last_resync_ts"] = {}
                app_state["last_resync_ts"][symbol] = now
                log_warning(
                    "mds_orderbook_resync_requested",
                    exchange=cfg.exchange,
                    symbol=symbol,
                    reason=reason or "crossed_orderbook",
                )
                await _resync_orderbook(reason or "crossed_orderbook")
                return
            log_warning(
                "mds_orderbook_resync_cooldown",
                exchange=cfg.exchange,
                symbol=symbol,
                reason=reason or "crossed_orderbook",
                cooldown_sec=cooldown,
                since_last_sec=round(now - last_resync, 3),
            )
        
        # FINAL SAFETY CHECK: Skip publishing if book is still crossed
        # This prevents bad data from reaching downstream consumers
        if merged_bids and merged_asks:
            final_best_bid = merged_bids[0][0]
            final_best_ask = merged_asks[0][0]
            if final_best_bid > final_best_ask:
                # Still crossed after merge - skip this update and wait for snapshot
                if "skipped_crossed_count" not in app_state:
                    app_state["skipped_crossed_count"] = {}
                app_state["skipped_crossed_count"][symbol] = app_state["skipped_crossed_count"].get(symbol, 0) + 1
                
                # Log at most once per 30 seconds
                now = time.time()
                skip_log_key = f"last_skip_log_{symbol}"
                last_skip_log = app_state.get(skip_log_key, 0)
                if now - last_skip_log > 30:
                    app_state[skip_log_key] = now
                    log_warning(
                        "mds_skipping_crossed_orderbook",
                        symbol=symbol,
                        best_bid=final_best_bid,
                        best_ask=final_best_ask,
                        skipped_count=app_state["skipped_crossed_count"].get(symbol, 0),
                    )
                return  # Skip publishing this update
        
        recv_us = now_recv_us()
        ts_canon_us = _next_canon_us(symbol, recv_us)
        ts_canon_s = us_to_sec(ts_canon_us)
        timestamp = ts_canon_s
        # Keep cts_ms strictly as matching-engine time when provided by exchange.
        # Do not derive from gateway/server timestamp fallback to avoid false "exchange lag".
        cts_ms = payload.get("cts_ms")
        cts_source = "matching_engine" if cts_ms is not None else "none"

        built_payload = {
            "symbol": symbol,
            "exchange": cfg.exchange,
                "market_type": cfg.market_type,
            "timestamp": timestamp,
            "ts": timestamp,
            "bids": merged_bids,
            "asks": merged_asks,
            "checksum": payload.get("checksum"),
            "type": "snapshot",  # Always publish as snapshot (full state)
            "seq": seq,
            "ts_recv_us": recv_us,
            "ts_canon_us": ts_canon_us,
            "ts_exchange_s": exchange_ts_s,
            "cts_ms": cts_ms,
            "cts_source": cts_source,
        }
        mode = cfg.publish_mode
        if mode in {"streams", "both"}:
            length = await redis_client.xlen(stream)
            if length and length > cfg.max_stream_length:
                await asyncio.sleep(cfg.backpressure_sleep_ms / 1000.0)
            await redis_client.xadd(
                stream, {"data": _to_json(built_payload)}, maxlen=cfg.publish_maxlen, approximate=True
            )
            if built_payload["type"] == "snapshot":
                now_ts = time.time()
                if "last_snapshot_log_ts" not in app_state:
                    app_state["last_snapshot_log_ts"] = {}
                last_log = app_state["last_snapshot_log_ts"].get(symbol, 0.0)
                if now_ts - last_log >= 5.0:
                    app_state["last_snapshot_log_ts"][symbol] = now_ts
                    log_info("mds_snapshot_published", symbol=symbol, stream=stream)
        if mode in {"events", "both"}:
            event = {
                "event_id": f"{cfg.service_id}:{symbol}:{built_payload['seq']}",
                "event_type": "orderbook_snapshot",  # Always snapshot (merged state)
                "schema_version": "v1",
                "timestamp": str(built_payload["timestamp"]),
                "ts_recv_us": recv_us,
                "ts_canon_us": ts_canon_us,
                "ts_exchange_s": exchange_ts_s,
                "bot_id": cfg.bot_id,
                "tenant_id": cfg.tenant_id,
                "symbol": symbol,
                "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                "payload": built_payload,
            }
            await redis_client.xadd(
                cfg.orderbook_event_stream,
                {"data": _to_json(event)},
                maxlen=cfg.publish_maxlen,
                approximate=True,
            )
        # Emit enriched market tick with bid/ask from orderbook
        # THROTTLE: Only emit orderbook ticks at most once per 100ms per symbol
        # to prevent flooding the market data stream
        bids = built_payload.get("bids") or []
        asks = built_payload.get("asks") or []
        if bids and asks:
            try:
                best_bid = float(bids[0][0]) if bids else None
                best_ask = float(asks[0][0]) if asks else None
                if best_bid and best_ask:
                    # Throttle check
                    last_tick_ts = app_state.get("last_orderbook_tick_ts", {}).get(symbol, 0)
                    now = time.time()
                    if now - last_tick_ts >= 0.1:  # 100ms throttle
                        if "last_orderbook_tick_ts" not in app_state:
                            app_state["last_orderbook_tick_ts"] = {}
                        app_state["last_orderbook_tick_ts"][symbol] = now
                        
                        market_tick = {
                            "event_id": f"{cfg.service_id}:{symbol}:{built_payload['seq']}:tick",
                            "event_type": "market_tick",
                            "schema_version": "v1",
                            "timestamp": str(built_payload["timestamp"]),
                            "ts_recv_us": recv_us,
                            "ts_canon_us": ts_canon_us,
                            "ts_exchange_s": exchange_ts_s,
                            "bot_id": cfg.bot_id,
                            "tenant_id": cfg.tenant_id,
                            "symbol": symbol,
                            "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                            "payload": {
                                "symbol": symbol,
                                "timestamp": built_payload["timestamp"],
                                "ts_recv_us": recv_us,
                                "ts_canon_us": ts_canon_us,
                                "ts_exchange_s": exchange_ts_s,
                                "cts_ms": cts_ms,
                                "bid": best_bid,
                                "ask": best_ask,
                                "last": (best_bid + best_ask) / 2,
                                "source": "orderbook_feed",
                            },
                        }
                        await redis_client.xadd(
                            cfg.market_data_stream,
                            {"data": _to_json(market_tick)},
                            maxlen=cfg.publish_maxlen,
                            approximate=True,
                        )
            except (IndexError, TypeError, ValueError):
                pass  # Skip if bid/ask extraction fails
        app_state["counters"]["orderbook"] += 1
        # Track last orderbook timestamp for health monitoring
        app_state["last_orderbook_ts"][symbol] = time.time()
        app_state["last_orderbook_l2_ts"][symbol] = app_state["last_orderbook_ts"][symbol]
        if cts_ms is not None:
            app_state["last_orderbook_exchange_ts"][symbol] = float(cts_ms) / 1000.0
            app_state["last_orderbook_exchange_l2_ts"][symbol] = app_state["last_orderbook_exchange_ts"][symbol]
            if "last_orderbook_exchange_source" not in app_state:
                app_state["last_orderbook_exchange_source"] = {}
            app_state["last_orderbook_exchange_source"][symbol] = cts_source
        app_state["ws_state"]["orderbook"] = "connected"

    def _force_snapshot_fetches():
        updates = []
        # Handle multiplex explicitly
        inner_providers = getattr(provider, "providers", None)
        targets = inner_providers if inner_providers else [provider]
        for p in targets:
            snapshot_fetcher = getattr(p, "snapshot_fetcher", None)
            if snapshot_fetcher:
                try:
                    snap = snapshot_fetcher()
                except Exception:
                    log_error("mds_snapshot_fetch_error", provider=str(p))
                    continue
                if not snap or not isinstance(snap, dict):
                    continue
                payload = snap.get("payload") if isinstance(snap, dict) and snap.get("payload") else snap
                # Keep provider sequence tracking aligned with forced snapshots
                if isinstance(payload, dict):
                    seq_val = payload.get("seq")
                    if seq_val is not None:
                        try:
                            p._snapshot_seq = int(seq_val)
                        except (TypeError, ValueError):
                            p._snapshot_seq = seq_val
                        p._last_seq = None
                updates.append({"type": "snapshot", "payload": payload})
        if updates:
            log_info("mds_snapshot_seed", count=len(updates), symbols=[u["payload"].get("symbol") for u in updates if u.get("payload")])
        return updates

    def _record_failure(feed_type: str, reason: str, symbol: str = None):
        """Record a failure for backoff tracking with detailed metrics."""
        now = time.time()
        app_state["failure_timestamps"].append(now)
        # Clean old failures outside the window
        cutoff = now - cfg.backoff_window_sec
        app_state["failure_timestamps"] = [ts for ts in app_state["failure_timestamps"] if ts > cutoff]
        
        # Track failure reasons (histogram)
        if "failure_reasons" not in app_state:
            app_state["failure_reasons"] = {}
        key = f"{feed_type}:{reason}"
        app_state["failure_reasons"][key] = app_state["failure_reasons"].get(key, 0) + 1
        
        # Track per-symbol failures
        if symbol:
            if "symbol_failures" not in app_state:
                app_state["symbol_failures"] = {}
            app_state["symbol_failures"][symbol] = app_state["symbol_failures"].get(symbol, 0) + 1
        
        # Check if we should enter backoff
        recent_failures = len(app_state["failure_timestamps"])
        if recent_failures >= cfg.backoff_trigger_count and app_state["mode"] != "backoff":
            app_state["mode"] = "backoff"
            app_state["backoff_until"] = now + cfg.backoff_duration_sec
            log_warning(
                "mds_entering_backoff",
                exchange=cfg.exchange,
                feed_type=feed_type,
                reason=reason,
                symbol=symbol,
                failure_count=recent_failures,
                backoff_sec=cfg.backoff_duration_sec,
                failure_histogram=app_state.get("failure_reasons", {}),
            )
        
        app_state["resync_count"][feed_type] = app_state["resync_count"].get(feed_type, 0) + 1
    
    async def _resync_orderbook(reason: str):
        """Resync orderbook via REST snapshot (one-shot, no thrash)."""
        if app_state["mode"] == "resyncing":
            return  # Already resyncing, don't thrash
        
        app_state["mode"] = "resyncing"
        log_info("mds_orderbook_resync_start", exchange=cfg.exchange, reason=reason)
        
        try:
            if cfg.orderbook_ws_only_snapshot:
                if hasattr(provider, "force_reconnect"):
                    await provider.force_reconnect()
            else:
                await provider.request_snapshot()
                for snap in _force_snapshot_fetches():
                    await _publish_update(snap)
            log_info("mds_orderbook_resync_complete", exchange=cfg.exchange)
            app_state["mode"] = "normal"
        except Exception as exc:
            log_error("mds_orderbook_resync_failed", exchange=cfg.exchange, error=str(exc))
            _record_failure("orderbook", reason)
            app_state["mode"] = "normal"  # Exit resyncing state even on failure

    async def _publish_loop():
        stream_prefix = f"{cfg.orderbook_stream_prefix}:{cfg.exchange}"
        backoff = 1.0
        app_state["ws_state"]["orderbook"] = "connecting"
        
        # seed an initial snapshot so downstream consumers don't see deltas first
        if not cfg.orderbook_ws_only_snapshot:
            try:
                await provider.request_snapshot()
                for snap in _force_snapshot_fetches():
                    await _publish_update(snap)
                log_info("mds_orderbook_initial_seed_complete", exchange=cfg.exchange)
            except Exception as exc:
                log_warning("mds_orderbook_initial_seed_failed", exchange=cfg.exchange, error=str(exc))
        # periodic snapshot refresh to keep consumers aligned
        async def _snapshot_refresher():
            while not stop_event.is_set():
                await asyncio.sleep(cfg.snapshot_interval_sec)
                if cfg.orderbook_ws_only_snapshot:
                    continue
                try:
                    await provider.request_snapshot()
                    for snap in _force_snapshot_fetches():
                        await _publish_update(snap)
                except Exception:
                    continue
        asyncio.create_task(_snapshot_refresher())
        last_checksum_fail_log = 0.0
        
        while not stop_event.is_set():
            try:
                update = await provider.next_update()
                if not update:
                    continue
                
                # Check for checksum failures or gaps that need resync
                payload = update.get("payload") if isinstance(update, dict) else None
                if payload:
                    symbol = payload.get("symbol")
                    checksum_status = payload.get("checksum_status")
                    if checksum_status == "failed":
                        now = time.time()
                        # Log at most once per 30 seconds to avoid spam
                        if now - last_checksum_fail_log > 30:
                            last_checksum_fail_log = now
                            log_warning("mds_checksum_failed", exchange=cfg.exchange, symbol=symbol)
                        _record_failure("orderbook", "checksum_failed", symbol=symbol)
                        # Trigger resync (one-shot)
                        await _resync_orderbook("checksum_failed")
                        continue
                    
                    # Check for sequence gaps (if provider supports it)
                    if payload.get("gap_detected"):
                        gap_size = payload.get("gap_size", 0)
                        log_warning("mds_sequence_gap", exchange=cfg.exchange, symbol=symbol, gap_size=gap_size)
                        _record_failure("orderbook", "sequence_gap", symbol=symbol)
                        # Track gap histogram
                        if "gap_histogram" not in app_state:
                            app_state["gap_histogram"] = {"small": 0, "medium": 0, "large": 0}
                        if gap_size < 10:
                            app_state["gap_histogram"]["small"] += 1
                        elif gap_size < 100:
                            app_state["gap_histogram"]["medium"] += 1
                        else:
                            app_state["gap_histogram"]["large"] += 1
                        await _resync_orderbook("sequence_gap")
                        continue
                    
                    # Do not run staleness checks on an incoming update path.
                    # A separate monitor loop handles feed staleness based on last
                    # published timestamps; checking here can self-trigger an
                    # infinite resync loop (drop update -> timestamp never refreshes).
                
                backoff = 1.0  # reset backoff on success
                app_state["ws_state"]["orderbook"] = "connected"
                await _publish_update(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_error("mds_publish_error", error=str(exc))
                app_state["last_error"] = str(exc)
                app_state["ws_state"]["orderbook"] = "error"
                _record_failure("orderbook", "publish_error", symbol=None)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _publish_trades():
        """
        Publish trades with HIGHEST PRIORITY.
        
        CRITICAL: Trades are never dropped or delayed, even under backlog.
        They are essential for:
        - Exit signal generation (orderflow imbalance)
        - Price discovery
        - VWAP/POC calculations
        
        Unlike orderbook, trades have NO backpressure sleep and NO compaction.
        """
        if not trade_provider:
            log_warning("mds_trade_provider_disabled", exchange=cfg.exchange)
            return
        stream_prefix = f"{cfg.trade_stream_prefix}:{cfg.exchange}:{cfg.market_type}"
        event_stream = cfg.trade_event_stream
        market_data_stream = cfg.market_data_stream
        backoff = 1.0
        
        log_info("mds_trade_loop_starting", exchange=cfg.exchange, symbols=cfg.symbols)
        app_state["ws_state"]["trade"] = "connecting"
        
        while not stop_event.is_set():
            try:
                trade = await trade_provider.next_trade()
                if not trade:
                    continue
                backoff = 1.0
                app_state["ws_state"]["trade"] = "connected"
                symbol = trade.get("symbol")
                
                # Track last trade timestamp for health monitoring
                now = time.time()
                app_state["last_trade_ts"][symbol] = now
                recv_us = now_recv_us()
                ts_canon_us = _next_canon_us(symbol, recv_us)
                ts_canon_s = us_to_sec(ts_canon_us)
                exchange_ts_s = normalize_exchange_ts_to_sec(trade.get("timestamp"))
                
                stream = f"{stream_prefix}:{symbol}"
                payload = {
                    "symbol": symbol,
                    "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                    "timestamp": ts_canon_s,
                    "price": trade.get("price"),
                    "size": trade.get("size"),
                    "side": trade.get("side"),
                    "ts_recv_us": recv_us,
                    "ts_canon_us": ts_canon_us,
                    "ts_exchange_s": exchange_ts_s,
                    "raw": trade,
                }
                event = {
                    "event_id": f"{cfg.service_id}:{symbol}:{ts_canon_us}",
                    "event_type": "trade",
                    "schema_version": "v1",
                    "timestamp": str(payload.get("timestamp")),
                    "ts_recv_us": recv_us,
                    "ts_canon_us": ts_canon_us,
                    "ts_exchange_s": exchange_ts_s,
                    "bot_id": cfg.bot_id,
                    "tenant_id": cfg.tenant_id,
                    "symbol": symbol,
                    "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                    "payload": payload,
                }
                # PRIORITY: No backpressure for trades - they are critical for exits
                # Only check length for metrics, don't sleep
                length = await redis_client.xlen(stream)
                if length and length > cfg.max_stream_length:
                    # Log but don't delay - trades are too important
                    if "trade_backlog_warnings" not in app_state:
                        app_state["trade_backlog_warnings"] = 0
                    app_state["trade_backlog_warnings"] += 1
                await redis_client.xadd(stream, {"data": _to_json(event)}, maxlen=cfg.publish_maxlen, approximate=True)
                if event_stream:
                    await redis_client.xadd(
                        event_stream,
                        {"data": _to_json(event)},
                        maxlen=cfg.publish_maxlen,
                        approximate=True,
                    )
                if market_data_stream:
                    # Throttle trade-based market ticks to reduce load on feature worker
                    # Individual trades go to trade stream for orderflow; market_tick is for features
                    last_trade_tick_ts = app_state.get("last_trade_tick_ts", {}).get(symbol, 0)
                    if now - last_trade_tick_ts >= 0.2:  # 200ms throttle (5 ticks/sec per symbol)
                        if "last_trade_tick_ts" not in app_state:
                            app_state["last_trade_tick_ts"] = {}
                        app_state["last_trade_tick_ts"][symbol] = now
                        
                        market_tick = {
                            "event_id": f"{cfg.service_id}:{symbol}:{ts_canon_us}:tick",
                            "event_type": "market_tick",
                            "schema_version": "v1",
                            "timestamp": str(payload.get("timestamp")),
                            "ts_recv_us": recv_us,
                            "ts_canon_us": ts_canon_us,
                            "ts_exchange_s": exchange_ts_s,
                            "bot_id": cfg.bot_id,
                            "tenant_id": cfg.tenant_id,
                            "symbol": symbol,
                            "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                            "payload": {
                                "symbol": symbol,
                                "timestamp": payload.get("timestamp"),
                                "ts_recv_us": recv_us,
                                "ts_canon_us": ts_canon_us,
                                "ts_exchange_s": exchange_ts_s,
                                "last": payload.get("price"),
                                "volume": payload.get("size"),
                                "source": "trade_feed",
                            },
                        }
                        await redis_client.xadd(
                            market_data_stream,
                            {"data": _to_json(market_tick)},
                            maxlen=cfg.publish_maxlen,
                            approximate=True,
                        )
                app_state["counters"]["trades"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_error("mds_trade_error", error=str(exc))
                app_state["last_error"] = str(exc)
                app_state["ws_state"]["trade"] = "error"
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _publish_tickers():
        if not ticker_provider:
            return
        stream_prefix = f"{cfg.ticker_stream_prefix}:{cfg.exchange}:{cfg.market_type}"
        backoff = 1.0
        while not stop_event.is_set():
            try:
                tick = await ticker_provider.next_tick()
                if not tick:
                    continue
                backoff = 1.0
                symbol = tick.get("symbol")
                stream = f"{stream_prefix}:{symbol}"
                payload = {
                    "symbol": symbol,
                    "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                    "timestamp": tick.get("timestamp"),
                    "bid": tick.get("bid"),
                    "ask": tick.get("ask"),
                    "last": tick.get("last"),
                    "raw": tick,
                }
                length = await redis_client.xlen(stream)
                if length and length > cfg.max_stream_length:
                    await asyncio.sleep(cfg.backpressure_sleep_ms / 1000.0)
                await redis_client.xadd(stream, {"data": _to_json(payload)}, maxlen=cfg.publish_maxlen, approximate=True)
                app_state["counters"]["tickers"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_error("mds_ticker_error", error=str(exc))
                app_state["last_error"] = str(exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _health_loop():
        key_prefix = f"orderbook_health:{cfg.exchange}"
        _gc_counter = 0
        while not stop_event.is_set():
            now = time.time()
            # Periodic GC to prevent memory growth from websocket message churn
            _gc_counter += 1
            if _gc_counter % 6 == 0:  # ~every 30s (health loop runs every ~5s)
                gc.collect()
            health = provider.health() if hasattr(provider, "health") else {}
            
            # Track orderbook health per symbol
            for symbol, meta in (health or {}).items():
                key = f"{key_prefix}:{symbol}"
                # Track exchange-side timestamp separately; do not overwrite
                # receive-time staleness with exchange clock/queueing lag.
                if meta.get("last_ts"):
                    app_state["last_orderbook_exchange_ts"][symbol] = meta.get("last_ts") / 1000.0
                await redis_client.hset(
                    key,
                    mapping={
                        "last_ts": meta.get("last_ts"),
                        "staleness_ms": meta.get("staleness_ms"),
                        "reconnects": meta.get("reconnects"),
                        "checksum_status": meta.get("checksum_status"),
                    },
                )
            
            # Compute staleness for each feed
            trade_staleness = {}
            orderbook_staleness = {}
            orderbook_l1_staleness = {}
            orderbook_l2_staleness = {}
            orderbook_exchange_lag = {}
            orderbook_exchange_lag_l1 = {}
            orderbook_exchange_lag_l2 = {}
            orderbook_exchange_lag_source = {}
            orderbook_cts_present_rate_l1 = {}
            orderbook_cts_present_rate_l2 = {}
            orderbook_event_rate_l1_eps = {}
            orderbook_event_rate_l2_eps = {}
            for symbol in cfg.symbols:
                last_trade = app_state["last_trade_ts"].get(symbol)
                last_ob = app_state["last_orderbook_ts"].get(symbol)
                last_ob_l1 = app_state["last_orderbook_l1_ts"].get(symbol)
                last_ob_l2 = app_state["last_orderbook_l2_ts"].get(symbol)
                last_ob_exchange = app_state["last_orderbook_exchange_ts"].get(symbol)
                last_ob_exchange_l1 = app_state["last_orderbook_exchange_l1_ts"].get(symbol)
                last_ob_exchange_l2 = app_state["last_orderbook_exchange_l2_ts"].get(symbol)
                last_ob_exchange_source = app_state.get("last_orderbook_exchange_source", {}).get(symbol)
                trade_staleness[symbol] = round(now - last_trade, 2) if last_trade else None
                orderbook_staleness[symbol] = round(now - last_ob, 2) if last_ob else None
                orderbook_l1_staleness[symbol] = round(now - last_ob_l1, 2) if last_ob_l1 else None
                orderbook_l2_staleness[symbol] = round(now - last_ob_l2, 2) if last_ob_l2 else None
                orderbook_exchange_lag[symbol] = round(now - last_ob_exchange, 2) if last_ob_exchange else None
                orderbook_exchange_lag_l1[symbol] = (
                    round(now - last_ob_exchange_l1, 2) if last_ob_exchange_l1 else None
                )
                orderbook_exchange_lag_l2[symbol] = (
                    round(now - last_ob_exchange_l2, 2) if last_ob_exchange_l2 else None
                )
                orderbook_exchange_lag_source[symbol] = last_ob_exchange_source
                l1_total = app_state.get("orderbook_l1_total_count", {}).get(symbol, 0)
                l1_with_cts = app_state.get("orderbook_l1_cts_count", {}).get(symbol, 0)
                l2_total = app_state.get("orderbook_l2_total_count", {}).get(symbol, 0)
                l2_with_cts = app_state.get("orderbook_l2_cts_count", {}).get(symbol, 0)
                orderbook_cts_present_rate_l1[symbol] = (
                    round((l1_with_cts / l1_total) * 100.0, 1) if l1_total > 0 else None
                )
                orderbook_cts_present_rate_l2[symbol] = (
                    round((l2_with_cts / l2_total) * 100.0, 1) if l2_total > 0 else None
                )

                prev_ts = app_state.get("orderbook_rate_prev_ts", {}).get(symbol)
                prev_l1_total = app_state.get("orderbook_l1_prev_count", {}).get(symbol)
                prev_l2_total = app_state.get("orderbook_l2_prev_count", {}).get(symbol)
                if (
                    prev_ts is not None
                    and prev_l1_total is not None
                    and prev_l2_total is not None
                    and now > prev_ts
                ):
                    dt = now - prev_ts
                    l1_eps = max(0.0, (l1_total - prev_l1_total) / dt)
                    l2_eps = max(0.0, (l2_total - prev_l2_total) / dt)
                    orderbook_event_rate_l1_eps[symbol] = round(l1_eps, 3)
                    orderbook_event_rate_l2_eps[symbol] = round(l2_eps, 3)
                else:
                    orderbook_event_rate_l1_eps[symbol] = None
                    orderbook_event_rate_l2_eps[symbol] = None

                app_state["orderbook_rate_prev_ts"][symbol] = now
                app_state["orderbook_l1_prev_count"][symbol] = l1_total
                app_state["orderbook_l2_prev_count"][symbol] = l2_total
            
            # Determine overall health status
            status = "healthy"
            stale_feeds = []
            for symbol in cfg.symbols:
                if trade_staleness.get(symbol) is not None and trade_staleness[symbol] > cfg.trade_stale_sec:
                    stale_feeds.append(f"trade:{symbol}")
                    status = "degraded"
                if orderbook_staleness.get(symbol) is not None and orderbook_staleness[symbol] > cfg.orderbook_stale_sec:
                    stale_feeds.append(f"orderbook:{symbol}")
                    status = "degraded"
                if (
                    orderbook_exchange_lag.get(symbol) is not None
                    and cfg.orderbook_delta_max_age_sec > 0
                    and orderbook_exchange_lag[symbol] > cfg.orderbook_delta_max_age_sec
                ):
                    stale_feeds.append(f"orderbook_exchange:{symbol}")
                    status = "degraded"
            
            # Check backoff state
            if app_state["backoff_until"] > now:
                status = "backoff"
                app_state["mode"] = "backoff"
            elif app_state["mode"] == "backoff" and app_state["backoff_until"] <= now:
                app_state["mode"] = "normal"
                log_info("mds_backoff_ended", exchange=cfg.exchange)
            
            # Check stream depths for backlog tier
            try:
                market_data_depth = await redis_client.xlen(f"{cfg.market_data_stream}:{cfg.exchange}")
            except Exception:
                market_data_depth = 0
            
            # Determine backlog tier
            if market_data_depth >= cfg.hard_backlog_threshold:
                app_state["backlog_tier"] = "hard"
                if status == "healthy":
                    status = "degraded"
            elif market_data_depth >= cfg.soft_backlog_threshold:
                app_state["backlog_tier"] = "soft"
            else:
                app_state["backlog_tier"] = "normal"

            # Compute an aggregate MDS quality score (0-100) from:
            # freshness + integrity + throughput + cts availability.
            quality_by_symbol = {}
            for symbol in cfg.symbols:
                trade_age = trade_staleness.get(symbol)
                l2_age = orderbook_l2_staleness.get(symbol)
                l2_eps = orderbook_event_rate_l2_eps.get(symbol)
                cts_rate_l2 = orderbook_cts_present_rate_l2.get(symbol)

                trade_threshold = max(float(cfg.trade_stale_sec), 1.0)
                l2_threshold = max(float(cfg.orderbook_stale_sec), 1.0)
                trade_fresh = (
                    max(0.0, min(1.0, 1.0 - (float(trade_age) / trade_threshold)))
                    if trade_age is not None
                    else 0.0
                )
                l2_fresh = (
                    max(0.0, min(1.0, 1.0 - (float(l2_age) / l2_threshold)))
                    if l2_age is not None
                    else 0.0
                )
                freshness_score = ((trade_fresh + l2_fresh) / 2.0) * 100.0

                # 2.5 L2 events/sec ~= full throughput score for this quality index.
                throughput_score = (
                    max(0.0, min(100.0, (float(l2_eps) / 2.5) * 100.0))
                    if l2_eps is not None
                    else 0.0
                )

                integrity_score = 100.0
                if (
                    (trade_age is not None and trade_age > cfg.trade_stale_sec)
                    or (l2_age is not None and l2_age > cfg.orderbook_stale_sec)
                ):
                    integrity_score = 40.0

                cts_score = 50.0
                if cts_rate_l2 is not None:
                    if cts_rate_l2 >= 50.0:
                        cts_score = 100.0
                    elif cts_rate_l2 > 0.0:
                        cts_score = 70.0

                score = (
                    0.45 * freshness_score
                    + 0.30 * throughput_score
                    + 0.15 * integrity_score
                    + 0.10 * cts_score
                )
                quality_by_symbol[symbol] = round(max(0.0, min(100.0, score)), 1)

            quality_values = [v for v in quality_by_symbol.values() if v is not None]
            mds_quality_score = (
                round(sum(quality_values) / len(quality_values), 1) if quality_values else 0.0
            )
            
            # Publish comprehensive health to Redis
            health_payload = {
                "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                "timestamp": now,
                "status": status,
                "mode": app_state["mode"],
                "ws_state": app_state["ws_state"],
                "trade_staleness": trade_staleness,
                "orderbook_staleness": orderbook_staleness,
                "orderbook_l1_staleness": orderbook_l1_staleness,
                "orderbook_l2_staleness": orderbook_l2_staleness,
                "orderbook_exchange_lag": orderbook_exchange_lag,
                "orderbook_exchange_lag_l1": orderbook_exchange_lag_l1,
                "orderbook_exchange_lag_l2": orderbook_exchange_lag_l2,
                "orderbook_exchange_lag_source": orderbook_exchange_lag_source,
                "orderbook_cts_present_rate_l1": orderbook_cts_present_rate_l1,
                "orderbook_cts_present_rate_l2": orderbook_cts_present_rate_l2,
                "orderbook_event_rate_l1_eps": orderbook_event_rate_l1_eps,
                "orderbook_event_rate_l2_eps": orderbook_event_rate_l2_eps,
                "stale_feeds": stale_feeds,
                "counters": app_state["counters"],
                "resync_count": app_state["resync_count"],
                "backoff_until": app_state["backoff_until"],
                "last_error": app_state["last_error"],
                # Flow control metrics
                "backlog_tier": app_state["backlog_tier"],
                "coalesced_count": app_state.get("coalesced_count", {}),
                "batched_count": app_state.get("batched_count", {}),
                "market_data_depth": market_data_depth,
                "soft_threshold": cfg.soft_backlog_threshold,
                "hard_threshold": cfg.hard_backlog_threshold,
                # Gap resilience metrics
                "gap_histogram": app_state.get("gap_histogram", {}),
                "failure_reasons": app_state.get("failure_reasons", {}),
                "symbol_failures": app_state.get("symbol_failures", {}),
                "recent_failure_count": len(app_state.get("failure_timestamps", [])),
                "stale_delta_skipped_count": app_state.get("stale_delta_skipped_count", {}),
                "skipped_crossed_count": app_state.get("skipped_crossed_count", {}),
                "mds_quality_score": mds_quality_score,
                "mds_quality_score_by_symbol": quality_by_symbol,
            }
            
            if cfg.health_key:
                await redis_client.set(
                    cfg.health_key,
                    _to_json(health_payload),
                    ex=30,  # Expire in 30 seconds
                )
            
            # Legacy heartbeat
            if cfg.heartbeat_key:
                await redis_client.hset(
                    cfg.heartbeat_key,
                    mapping={
                        "exchange": cfg.exchange,
                "market_type": cfg.market_type,
                        "market_type": cfg.market_type,
                        "symbols": ",".join(cfg.symbols),
                        "ts": int(now * 1000),
                        "status": status,
                        "mode": app_state["mode"],
                    },
                )
                await redis_client.expire(cfg.heartbeat_key, 30)
            
            await asyncio.sleep(1.0)

    app_state = {
        "cfg": cfg,
        "counters": {"orderbook": 0, "trades": 0, "tickers": 0},
        "last_error": None,
        # Health tracking for watchdog and telemetry
        "last_trade_ts": {},  # symbol -> timestamp
        "last_orderbook_ts": {},  # symbol -> timestamp
        "last_orderbook_l1_ts": {},  # symbol -> timestamp (l1 updates)
        "last_orderbook_l2_ts": {},  # symbol -> timestamp (l2 depth updates)
        "last_orderbook_exchange_ts": {},  # symbol -> exchange timestamp (sec)
        "last_orderbook_exchange_l1_ts": {},  # symbol -> l1 exchange timestamp (sec)
        "last_orderbook_exchange_l2_ts": {},  # symbol -> l2 exchange timestamp (sec)
        "last_orderbook_exchange_source": {},  # symbol -> exchange timestamp source
        "orderbook_l1_total_count": {},  # symbol -> total l1 updates seen
        "orderbook_l1_cts_count": {},  # symbol -> l1 updates with cts
        "orderbook_l2_total_count": {},  # symbol -> total l2 updates seen
        "orderbook_l2_cts_count": {},  # symbol -> l2 updates with cts
        "orderbook_rate_prev_ts": {},  # symbol -> last rate sample timestamp
        "orderbook_l1_prev_count": {},  # symbol -> previous l1 total counter
        "orderbook_l2_prev_count": {},  # symbol -> previous l2 total counter
        "last_resync_ts": {},  # symbol -> timestamp
        "ws_state": {
            "trade": "unknown",  # connected, disconnected, reconnecting
            "orderbook": "unknown",
        },
        "resync_count": {"trade": 0, "orderbook": 0},
        "failure_timestamps": [],  # For backoff tracking
        "backoff_until": 0.0,  # Timestamp when backoff ends
        "mode": "normal",  # normal, resyncing, backoff
        # Flow control metrics
        "coalesced_count": {"orderbook": 0, "trades": 0},
        "batched_count": {"orderbook": 0, "trades": 0},
        "backlog_tier": "normal",  # normal, soft, hard
        "last_backlog_check": 0.0,
        # Coalescing buffers (symbol -> latest update)
        "orderbook_coalesce": {},
        "last_orderbook_coalesce_flush": 0.0,
    }
    http_runner = await _start_http_health(app_state, redis_client)
    try:
        await asyncio.gather(
            _publish_loop(),
            _health_loop(),
            _publish_trades(),
            _publish_tickers(),
            stop_event.wait(),
        )
    finally:
        await http_runner.cleanup()


def _to_json(payload):
    if _orjson is not None:
        return _orjson.dumps(payload)
    return json.dumps(payload, separators=(",", ":")).encode()


if __name__ == "__main__":
    asyncio.run(run())
