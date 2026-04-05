"""Runtime entrypoint wiring Redis + Timescale connections."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).parent.parent.parent.parent
env_file = os.environ.get("ENV_FILE", ".env")

import asyncpg
import redis.asyncio as redis
from typing import Optional

from quantgambit.config.env_loading import apply_layered_env_defaults
from quantgambit.observability.logger import configure_logging, log_info, log_error, log_warning
from quantgambit.observability.alerts import AlertsClient
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.market.deeptrader_event_bridge import DeepTraderEventBridge
from quantgambit.market.ccxt_provider import CcxtTickerProvider
from quantgambit.market.updater import MarketDataProvider
from quantgambit.market.ws_provider import (
    OkxTickerWebsocketProvider,
    BybitTickerWebsocketProvider,
    BinanceTickerWebsocketProvider,
    MultiplexTickerProvider,
)
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client
from quantgambit.execution.live_adapters import OkxLiveAdapter, BybitLiveAdapter, BinanceLiveAdapter
from quantgambit.execution.oco_adapters import OkxOcoLiveAdapter, BybitOcoLiveAdapter, BinanceOcoLiveAdapter
from quantgambit.execution.guards import GuardConfig
from quantgambit.execution.order_updates_ws import (
    OkxWsCredentials,
    BybitWsCredentials,
    BinanceWsCredentials,
    OkxOrderUpdateProvider,
    BybitOrderUpdateProvider,
    BinanceOrderUpdateProvider,
)
from quantgambit.execution.symbols import canonical_symbol, normalize_exchange_symbol, to_ccxt_market_symbol
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
from quantgambit.market.trades import TradeStatsCache
from quantgambit.signals.prediction_providers import build_prediction_provider, OnnxPredictionProvider
from quantgambit.storage.secrets import get_exchange_credentials, ExchangeCredentials

loaded_env_paths = apply_layered_env_defaults(project_root, env_file, os.environ)
if loaded_env_paths:
    print("✅ Loaded environment defaults from " + ", ".join(str(path) for path in loaded_env_paths))


def _resolve_bool(*values: object, default: bool = False) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _apply_ai_profile_prediction_overrides(
    profile_overrides_raw: str | None,
    prediction_provider: str,
    prediction_shadow_provider: str,
    prediction_model_path: Optional[str],
    prediction_model_config: str,
    prediction_model_features: str,
    prediction_model_classes: str,
    prediction_min_confidence: Optional[float],
) -> tuple[str, str, Optional[str], str, str, str, Optional[float]]:
    if not profile_overrides_raw:
        return (
            prediction_provider,
            prediction_shadow_provider,
            prediction_model_path,
            prediction_model_config,
            prediction_model_features,
            prediction_model_classes,
            prediction_min_confidence,
        )
    try:
        profile_overrides = json.loads(profile_overrides_raw)
    except Exception:
        return (
            prediction_provider,
            prediction_shadow_provider,
            prediction_model_path,
            prediction_model_config,
            prediction_model_features,
            prediction_model_classes,
            prediction_min_confidence,
        )
    if not isinstance(profile_overrides, dict):
        return (
            prediction_provider,
            prediction_shadow_provider,
            prediction_model_path,
            prediction_model_config,
            prediction_model_features,
            prediction_model_classes,
            prediction_min_confidence,
        )
    bot_type = str(profile_overrides.get("bot_type") or "").strip().lower()
    ai_provider = str(profile_overrides.get("ai_provider") or "").strip().lower()
    if bot_type != "ai_spot_swing" and ai_provider not in {"deepseek_context", "context_model", "ai_spot_swing"}:
        return (
            prediction_provider,
            prediction_shadow_provider,
            prediction_model_path,
            prediction_model_config,
            prediction_model_features,
            prediction_model_classes,
            prediction_min_confidence,
        )
    ai_shadow_mode = _resolve_bool(
        profile_overrides.get("ai_shadow_mode"),
        os.getenv("AI_SHADOW_ONLY"),
        default=False,
    )
    confidence_floor = profile_overrides.get("ai_confidence_floor")
    provider_name = ai_provider or "deepseek_context"
    if ai_shadow_mode:
        return (
            prediction_provider,
            prediction_shadow_provider or provider_name,
            prediction_model_path,
            prediction_model_config,
            prediction_model_features,
            prediction_model_classes,
            _optional_float(str(confidence_floor)) if confidence_floor is not None else prediction_min_confidence,
        )
    return (
        provider_name,
        prediction_shadow_provider,
        None,
        "",
        "",
        "down,flat,up",
        _optional_float(str(confidence_floor)) if confidence_floor is not None else prediction_min_confidence,
    )


async def run(event_bus=None) -> None:
    configure_logging()
    tenant_id = os.getenv("TENANT_ID", "tenant")
    bot_id = os.getenv("BOT_ID", "bot")
    exchange = os.getenv("ACTIVE_EXCHANGE", "okx")
    trading_mode = os.getenv("TRADING_MODE", "live")
    trading_hours_start = int(os.getenv("TRADING_HOURS_START_UTC", "0"))
    trading_hours_end = int(os.getenv("TRADING_HOURS_END_UTC", "24"))
    market_type = os.getenv("MARKET_TYPE", "perp")
    margin_mode = os.getenv("MARGIN_MODE", "isolated")
    config_version = os.getenv("BOT_CONFIG_VERSION")
    order_intent_max_age_raw = float(os.getenv("ORDER_INTENT_MAX_AGE_SEC", "0"))
    order_intent_max_age_sec = order_intent_max_age_raw or None
    prediction_provider = os.getenv("PREDICTION_PROVIDER", "heuristic")
    prediction_model_config = os.getenv("PREDICTION_MODEL_CONFIG", "")
    prediction_model_path = os.getenv("PREDICTION_MODEL_PATH")
    prediction_model_features = os.getenv("PREDICTION_MODEL_FEATURES", "")
    prediction_model_classes = os.getenv("PREDICTION_MODEL_CLASSES", "down,flat,up")
    prediction_shadow_provider = os.getenv("PREDICTION_SHADOW_PROVIDER", "").strip()
    prediction_shadow_heuristic_version = os.getenv("PREDICTION_SHADOW_HEURISTIC_VERSION", "").strip().lower()
    prediction_shadow_model_config = os.getenv("PREDICTION_SHADOW_MODEL_CONFIG", "")
    prediction_shadow_model_path = os.getenv("PREDICTION_SHADOW_MODEL_PATH")
    prediction_shadow_model_features = os.getenv("PREDICTION_SHADOW_MODEL_FEATURES", "")
    prediction_shadow_model_classes = os.getenv("PREDICTION_SHADOW_MODEL_CLASSES", "down,flat,up")
    prediction_onnx_min_confidence = _optional_float(os.getenv("PREDICTION_ONNX_MIN_CONFIDENCE"))
    prediction_onnx_min_margin = _optional_float(os.getenv("PREDICTION_ONNX_MIN_MARGIN"))
    prediction_onnx_max_entropy = _optional_float(os.getenv("PREDICTION_ONNX_MAX_ENTROPY"))
    prediction_shadow_onnx_min_confidence = _optional_float(
        os.getenv("PREDICTION_SHADOW_ONNX_MIN_CONFIDENCE")
    )
    prediction_shadow_onnx_min_margin = _optional_float(
        os.getenv("PREDICTION_SHADOW_ONNX_MIN_MARGIN")
    )
    prediction_shadow_onnx_max_entropy = _optional_float(
        os.getenv("PREDICTION_SHADOW_ONNX_MAX_ENTROPY")
    )
    if prediction_shadow_onnx_min_confidence is None:
        prediction_shadow_onnx_min_confidence = prediction_onnx_min_confidence
    if prediction_shadow_onnx_min_margin is None:
        prediction_shadow_onnx_min_margin = prediction_onnx_min_margin
    if prediction_shadow_onnx_max_entropy is None:
        prediction_shadow_onnx_max_entropy = prediction_onnx_max_entropy
    (
        prediction_provider,
        prediction_shadow_provider,
        prediction_model_path,
        prediction_model_config,
        prediction_model_features,
        prediction_model_classes,
        prediction_onnx_min_confidence,
    ) = _apply_ai_profile_prediction_overrides(
        os.getenv("PROFILE_OVERRIDES"),
        prediction_provider,
        prediction_shadow_provider,
        prediction_model_path,
        prediction_model_config,
        prediction_model_features,
        prediction_model_classes,
        prediction_onnx_min_confidence,
    )
    config_payload = _load_prediction_config(prediction_model_config)
    if config_payload:
        if not prediction_model_path:
            prediction_model_path = config_payload.get("onnx_path") or config_payload.get("model_path")
        prediction_model_path = _resolve_prediction_model_path(
            prediction_model_path, prediction_model_config
        )
        config_feature_keys = config_payload.get("feature_keys") or []
        if config_feature_keys:
            prediction_model_features = ",".join(config_feature_keys)
        if not prediction_model_classes or prediction_model_classes == "down,flat,up":
            classes = config_payload.get("class_labels")
            if classes:
                prediction_model_classes = ",".join(classes)

    shadow_config_payload = _load_prediction_config(prediction_shadow_model_config)
    if shadow_config_payload:
        if not prediction_shadow_model_path:
            prediction_shadow_model_path = shadow_config_payload.get("onnx_path") or shadow_config_payload.get("model_path")
        prediction_shadow_model_path = _resolve_prediction_model_path(
            prediction_shadow_model_path, prediction_shadow_model_config
        )
        shadow_feature_keys = shadow_config_payload.get("feature_keys") or []
        if shadow_feature_keys:
            prediction_shadow_model_features = ",".join(shadow_feature_keys)
        if not prediction_shadow_model_classes or prediction_shadow_model_classes == "down,flat,up":
            classes = shadow_config_payload.get("class_labels")
            if classes:
                prediction_shadow_model_classes = ",".join(classes)
    if prediction_model_path:
        prediction_model_path = _resolve_prediction_model_path(
            prediction_model_path, prediction_model_config
        )
    if prediction_shadow_model_path:
        prediction_shadow_model_path = _resolve_prediction_model_path(
            prediction_shadow_model_path, prediction_shadow_model_config
        )
    prediction_provider_impl = build_prediction_provider(
        prediction_provider,
        model_path=prediction_model_path,
        feature_keys=[item.strip() for item in prediction_model_features.split(",") if item.strip()],
        class_labels=[item.strip() for item in prediction_model_classes.split(",") if item.strip()],
        provider_config=config_payload,
        min_confidence=prediction_onnx_min_confidence,
        min_margin=prediction_onnx_min_margin,
        max_entropy=prediction_onnx_max_entropy,
    )
    shadow_provider_config = shadow_config_payload or {}
    if (
        prediction_shadow_provider.lower() in {"heuristic", "legacy_heuristic"}
        and prediction_shadow_heuristic_version
    ):
        shadow_provider_config = dict(shadow_provider_config)
        shadow_provider_config["heuristic_version"] = prediction_shadow_heuristic_version

    prediction_shadow_provider_impl = (
        None
        if not prediction_shadow_provider
        else build_prediction_provider(
            prediction_shadow_provider,
            model_path=prediction_shadow_model_path,
            feature_keys=[item.strip() for item in prediction_shadow_model_features.split(",") if item.strip()],
            class_labels=[item.strip() for item in prediction_shadow_model_classes.split(",") if item.strip()],
            provider_config=shadow_provider_config,
            min_confidence=prediction_shadow_onnx_min_confidence,
            min_margin=prediction_shadow_onnx_min_margin,
            max_entropy=prediction_shadow_onnx_max_entropy,
        )
    )
    validate_onnx_on_startup = os.getenv("PREDICTION_ONNX_VALIDATE_ON_STARTUP", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    _validate_onnx_provider(
        "primary",
        prediction_provider_impl,
        provider_name=prediction_provider,
        strict=validate_onnx_on_startup,
    )
    _validate_onnx_provider(
        "shadow",
        prediction_shadow_provider_impl,
        provider_name=prediction_shadow_provider,
        strict=False,
    )
    orderbook_symbols = os.getenv("ORDERBOOK_SYMBOLS", "")
    orderbook_symbol = os.getenv("ORDERBOOK_SYMBOL", "")
    orderbook_exchange = os.getenv("ORDERBOOK_EXCHANGE", exchange)
    orderbook_testnet = os.getenv("ORDERBOOK_TESTNET", "false").lower() in {"1", "true", "yes"}
    trade_provider_name = os.getenv("TRADE_PROVIDER", "").lower()
    trade_symbols = os.getenv("TRADE_SYMBOLS", "") or orderbook_symbols or orderbook_symbol
    trade_testnet = os.getenv("TRADE_TESTNET", "false").lower() in {"1", "true", "yes"}
    trade_market_type = os.getenv("TRADE_MARKET_TYPE", market_type)
    trade_external = _is_external_source("TRADE_SOURCE", "TRADES_EXTERNAL")
    order_update_exchange = os.getenv("ORDER_UPDATES_EXCHANGE", exchange)
    order_update_testnet = os.getenv("ORDER_UPDATES_TESTNET", "false").lower() in {"1", "true", "yes"}
    order_update_demo = os.getenv("ORDER_UPDATES_DEMO", "false").lower() in {"1", "true", "yes"}
    order_update_market_type = os.getenv("ORDER_UPDATES_MARKET_TYPE", market_type)
    execution_provider = os.getenv("EXECUTION_PROVIDER", "")
    guard_rate = float(os.getenv("EXECUTION_RATE_LIMIT_PER_SEC", "5"))
    guard_threshold = int(os.getenv("EXECUTION_BREAKER_THRESHOLD", "5"))
    guard_reset = float(os.getenv("EXECUTION_BREAKER_RESET_SEC", "10"))

    redis_url = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
    timescale_url = _build_timescale_url()

    log_info("runtime_bootstrap", tenant_id=tenant_id, bot_id=bot_id, exchange=exchange)

    try:
        redis_client = redis.from_url(redis_url)
        timescale_pool = await asyncpg.create_pool(timescale_url)
    except Exception as exc:
        log_error("runtime_bootstrap_failed", error=str(exc))
        raise

    state = InMemoryStateManager()
    market_data_queue = None
    market_data_provider = None
    if event_bus is not None:
        market_data_queue = asyncio.Queue(maxsize=10000)
        DeepTraderEventBridge(event_bus, market_data_queue).attach()
    else:
        provider_name = os.getenv("MARKET_DATA_PROVIDER", "").lower()
        if provider_name in {"disabled", "none", "off"}:
            provider_name = ""
        symbols_env = os.getenv("MARKET_DATA_SYMBOLS", "")
        poll_interval = float(os.getenv("MARKET_DATA_POLL_INTERVAL_SEC", "0.5"))
        market_data_testnet = os.getenv("MARKET_DATA_TESTNET", "false").lower() in {"1", "true", "yes"}
        raw_symbols = _resolve_market_data_symbols(
            symbols_env,
            orderbook_symbols,
            orderbook_symbol,
            exchange,
        )
        symbols = _normalize_market_data_symbols(
            raw_symbols,
            exchange,
            market_type,
        )
        if not provider_name or provider_name == "auto":
            provider_name = "ccxt"
        if not raw_symbols:
            log_warning("market_data_symbols_missing", exchange=exchange)
        else:
            market_data_provider = _select_market_data_provider(
                exchange=exchange,
                market_type=market_type,
                provider_name=provider_name,
                raw_symbols=raw_symbols,
                symbols=symbols,
                poll_interval=poll_interval,
                testnet=market_data_testnet,
            )
    trade_provider = None
    trade_cache = None
    if trade_provider_name in {"ws", "websocket", "trades_ws", "trades"} or trade_symbols:
        trade_provider = _build_trade_provider(
            exchange,
            trade_symbols,
            trade_market_type,
            trade_testnet,
        )
        if trade_provider:
            trade_cache = TradeStatsCache(
                window_sec=float(os.getenv("TRADE_WINDOW_SEC", "60")),
                profile_window_sec=float(os.getenv("TRADE_PROFILE_WINDOW_SEC", "300")),
                bucket_size=float(os.getenv("TRADE_BUCKET_SIZE", "5")),
                max_trades=int(os.getenv("TRADE_MAX_TRADES", "10000")),
            )
    orderbook_external = os.getenv("ORDERBOOK_SOURCE", "").lower() in {"external", "shared"} or os.getenv(
        "ORDERBOOK_EXTERNAL", "false"
    ).lower() in {"1", "true", "yes"}
    execution_adapter = await _build_execution_adapter(exchange, execution_provider, market_type, margin_mode, demo=order_update_demo)
    runtime = Runtime(
        config=RuntimeConfig(
            tenant_id=tenant_id,
            bot_id=bot_id,
            exchange=exchange,
            orderbook_symbols=[
                s.strip()
                for s in (orderbook_symbols or orderbook_symbol).split(",")
                if s.strip()
            ] or None,
            trading_mode=trading_mode,
            trading_hours_start=trading_hours_start,
            trading_hours_end=trading_hours_end,
            market_type=market_type,
            margin_mode=margin_mode,
            order_intent_max_age_sec=order_intent_max_age_sec,
            version=int(config_version) if config_version else None,
        ),
        redis=redis_client,
        timescale_pool=timescale_pool,
        state_manager=state,
        market_data_queue=market_data_queue,
        market_data_provider=market_data_provider,
        execution_adapter=execution_adapter,
        trade_provider=trade_provider,
        trade_cache=trade_cache,
        prediction_provider=prediction_provider_impl,
        prediction_shadow_provider=prediction_shadow_provider_impl,
        guard_config=GuardConfig(
            max_calls_per_sec=guard_rate,
            failure_threshold=guard_threshold,
            reset_after_sec=guard_reset,
        ),
        orderbook_provider=(
            None
            if _is_external_source("ORDERBOOK_SOURCE", "ORDERBOOK_EXTERNAL")
            else _build_orderbook_provider(
                orderbook_exchange,
                orderbook_symbols or orderbook_symbol,
                orderbook_testnet,
                market_type,
            )
        ),
        order_update_provider=_build_order_update_provider(
            order_update_exchange,
            order_update_testnet,
            order_update_demo,
            order_update_market_type,
        ),
    )
    await runtime.start()


def _build_orderbook_provider(exchange: str, symbols: str, testnet: bool, market_type: str):
    ws_config = WebsocketConfig(
        recv_timeout_sec=float(os.getenv("ORDERBOOK_WS_RECV_TIMEOUT_SEC", "10")),
        heartbeat_interval_sec=float(os.getenv("ORDERBOOK_WS_HEARTBEAT_SEC", "20")),
        snapshot_interval_sec=float(os.getenv("ORDERBOOK_WS_SNAPSHOT_SEC", "30")),
    )
    symbols_list = [
        _normalize_orderbook_symbol(exchange, value.strip())
        for value in (symbols or "").split(",")
        if value.strip()
    ]
    if not symbols_list:
        default_symbol = _default_orderbook_symbol(exchange)
        if default_symbol:
            symbols_list = [default_symbol]
        else:
            return None
    providers = []
    normalized = (exchange or "").lower()
    for symbol in symbols_list:
        if normalized == "okx":
            providers.append(
                OkxOrderbookWebsocketProvider(
                    symbol,
                    testnet=testnet,
                    market_type=market_type,
                    config=ws_config,
                )
            )
        elif normalized == "bybit":
            use_rest = os.getenv("ORDERBOOK_USE_REST_SNAPSHOT", "true").lower() in {"1", "true", "yes"}
            providers.append(
                BybitOrderbookWebsocketProvider(
                    symbol,
                    testnet=testnet,
                    market_type=market_type,
                    config=ws_config,
                    use_rest_snapshot=use_rest,
                )
            )
        elif normalized == "binance":
            providers.append(
                BinanceOrderbookWebsocketProvider(
                    symbol,
                    testnet=testnet,
                    market_type=market_type,
                    config=ws_config,
                )
            )
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return MultiplexOrderbookProvider(providers)


def _is_external_source(source_var: str, flag_var: str, env_override: dict | None = None) -> bool:
    environ = env_override or os.environ
    source = environ.get(source_var, "").lower()
    flag = environ.get(flag_var, "false").lower()
    return source in {"external", "shared"} or flag in {"1", "true", "yes"}


def _build_trade_provider(exchange: str, symbols: str, market_type: str, testnet: bool):
    trade_config = TradeWebsocketConfig(
        reconnect_delay_sec=float(os.getenv("TRADE_WS_RECONNECT_SEC", "1")),
        max_reconnect_delay_sec=float(os.getenv("TRADE_WS_MAX_RECONNECT_SEC", "10")),
        backoff_multiplier=float(os.getenv("TRADE_WS_BACKOFF_MULTIPLIER", "2")),
        heartbeat_interval_sec=float(os.getenv("TRADE_WS_HEARTBEAT_SEC", "20")),
        message_timeout_sec=float(os.getenv("TRADE_WS_MESSAGE_TIMEOUT_SEC", "30")),
        stale_guardrail_sec=float(os.getenv("TRADE_WS_STALE_GUARDRAIL_SEC", "60")),
        rest_fallback_enabled=os.getenv("TRADE_REST_FALLBACK_ENABLED", "false").lower()
        in {"1", "true", "yes"},
        rest_fallback_interval_sec=float(os.getenv("TRADE_REST_FALLBACK_INTERVAL_SEC", "30")),
        rest_fallback_limit=int(os.getenv("TRADE_REST_FALLBACK_LIMIT", "5")),
    )
    symbols_list = [
        _normalize_orderbook_symbol(exchange, value.strip())
        for value in (symbols or "").split(",")
        if value.strip()
    ]
    if not symbols_list:
        default_symbol = _default_orderbook_symbol(exchange)
        if default_symbol:
            symbols_list = [default_symbol]
        else:
            return None
    providers = []
    normalized = (exchange or "").lower()
    for symbol in symbols_list:
        if normalized == "okx":
            providers.append(OkxTradeWebsocketProvider(symbol, testnet=testnet, config=trade_config))
        elif normalized == "bybit":
            providers.append(
                BybitTradeWebsocketProvider(symbol, market_type=market_type, testnet=testnet, config=trade_config)
            )
        elif normalized == "binance":
            providers.append(
                BinanceTradeWebsocketProvider(symbol, market_type=market_type, testnet=testnet, config=trade_config)
            )
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return MultiplexTradeProvider(providers)


def _default_orderbook_symbol(exchange: str) -> str | None:
    normalized = (exchange or "").lower()
    if normalized == "okx":
        return "BTC-USDT-SWAP"
    if normalized in {"bybit", "binance"}:
        return "BTCUSDT"
    return None


def _normalize_orderbook_symbol(exchange: str, symbol: str) -> str:
    normalized_exchange = (exchange or "").lower()
    raw = symbol.strip()
    if not raw:
        return raw
    if normalized_exchange == "okx":
        converted = normalize_exchange_symbol("okx", raw, market_type="perp")
        return str(converted or raw).upper()
    if normalized_exchange in {"bybit", "binance"}:
        converted = normalize_exchange_symbol(normalized_exchange, raw, market_type="spot")
        return str(converted or raw).upper()
    return raw


def _normalize_market_data_symbols(symbols: str, exchange: str, market_type: str) -> list[str]:
    if not symbols:
        return []
    out: list[str] = []
    for raw in symbols.split(","):
        raw = raw.strip()
        if not raw:
            continue
        out.append(to_ccxt_market_symbol(exchange, raw, market_type=market_type) or raw)
    return out


def _select_market_data_provider(
    exchange: str,
    market_type: str,
    provider_name: str,
    raw_symbols: str,
    symbols: list[str],
    poll_interval: float,
    testnet: bool,
):
    normalized = (provider_name or "").lower()
    if normalized in {"auto", "fallback"}:
        return _build_auto_market_data_provider(
            exchange=exchange,
            market_type=market_type,
            raw_symbols=raw_symbols,
            symbols=symbols,
            poll_interval=poll_interval,
            testnet=testnet,
        )
    if normalized in {"ws", "websocket", "ticker_ws"}:
        ws_symbols = _normalize_ws_market_symbols(raw_symbols, exchange, market_type)
        return _build_ws_market_data_provider(
            exchange,
            ws_symbols or symbols,
            market_type,
            testnet,
        )
    if normalized in {"ccxt", "ticker"}:
        return CcxtTickerProvider(
            exchange=exchange,
            symbols=symbols,
            market_type=market_type,
            poll_interval_sec=poll_interval,
            testnet=testnet,
        )
    return None


def _resolve_market_data_symbols(
    symbols_env: str,
    orderbook_symbols: str,
    orderbook_symbol: str,
    exchange: str,
) -> str:
    raw = symbols_env or orderbook_symbols or orderbook_symbol
    if raw:
        return raw
    default_symbol = _default_orderbook_symbol(exchange)
    return default_symbol or ""


def _normalize_ws_market_symbols(symbols: str, exchange: str, market_type: str) -> list[str]:
    if not symbols:
        return []
    normalized = (exchange or "").lower()
    out: list[str] = []
    for raw in symbols.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if normalized == "okx":
            out.append(_normalize_orderbook_symbol(exchange, raw))
            continue
        if normalized in {"bybit", "binance"}:
            out.append(_normalize_orderbook_symbol(exchange, raw))
            continue
        out.append(raw)
    return out


def _build_ws_market_data_provider(
    exchange: str,
    symbols: list[str],
    market_type: str,
    testnet: bool,
):
    normalized = (exchange or "").lower()
    providers = []
    for symbol in symbols:
        if normalized == "okx":
            providers.append(OkxTickerWebsocketProvider(symbol, testnet=testnet))
        elif normalized == "bybit":
            providers.append(BybitTickerWebsocketProvider(symbol, market_type=market_type, testnet=testnet))
        elif normalized == "binance":
            providers.append(BinanceTickerWebsocketProvider(symbol, market_type=market_type, testnet=testnet))
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return MultiplexTickerProvider(providers)


def _build_auto_market_data_provider(
    exchange: str,
    market_type: str,
    raw_symbols: str,
    symbols: list[str],
    poll_interval: float,
    testnet: bool,
):
    ws_provider = None
    ws_symbols = _normalize_ws_market_symbols(raw_symbols, exchange, market_type)
    if ws_symbols:
        ws_provider = _build_ws_market_data_provider(exchange, ws_symbols, market_type, testnet)
    ccxt_provider = None
    if symbols:
        ccxt_provider = CcxtTickerProvider(
            exchange=exchange,
            symbols=symbols,
            market_type=market_type,
            poll_interval_sec=poll_interval,
            testnet=testnet,
        )
    providers = [p for p in (ws_provider, ccxt_provider) if p]
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    names = ["ws" if i == 0 else "ccxt" for i in range(len(providers))]
    threshold = int(os.getenv("MARKET_DATA_FAILURE_THRESHOLD", "3"))
    idle_backoff = float(os.getenv("MARKET_DATA_IDLE_BACKOFF_SEC", "0.1"))
    guardrail_interval = float(os.getenv("MARKET_DATA_GUARD_INTERVAL_SEC", "60"))
    return ResilientMarketDataProvider(
        providers=providers,
        provider_names=names,
        switch_threshold=threshold,
        idle_backoff_sec=idle_backoff,
        guardrail_cooldown_sec=guardrail_interval,
    )


class ResilientMarketDataProvider(MarketDataProvider):
    """Wrap multiple providers and emit guardrails when a switch or total failure occurs."""

    def __init__(
        self,
        providers: list[MarketDataProvider],
        provider_names: list[str],
        switch_threshold: int = 3,
        idle_backoff_sec: float = 0.1,
        guardrail_cooldown_sec: float = 60.0,
    ):
        filtered = [p for p in providers if p]
        if not filtered:
            raise ValueError("resilient provider requires at least one underlying provider")
        self._providers = filtered
        self._provider_names = (
            provider_names[:len(filtered)]
            if len(provider_names) >= len(filtered)
            else [f"provider_{i}" for i in range(len(filtered))]
        )
        self._switch_threshold = max(1, switch_threshold)
        self._idle_backoff_sec = max(0.0, idle_backoff_sec)
        self._guardrail_cooldown_sec = max(0.0, guardrail_cooldown_sec)
        self._active_index = 0
        self._failure_counts = [0] * len(self._providers)
        self._switch_count = 0
        self._last_success_at = time.time()
        self._last_guardrail_at = 0.0
        self._telemetry = None
        self._telemetry_ctx = None
        self._alerts = None
        self._snapshot_writer = None
        self._snapshot_key = None
        self._timescale_writer = None
        self._timescale_table = None
        self._ts_tenant = None
        self._ts_bot = None
        self._ts_exchange = None

    @property
    def active_provider_name(self) -> str:
        return self._provider_names[self._active_index]

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        self._telemetry = telemetry
        self._telemetry_ctx = ctx

    def set_alerts(self, alerts: Optional[AlertsClient]) -> None:
        self._alerts = alerts

    def set_snapshot_writer(self, writer, key: str) -> None:
        self._snapshot_writer = writer
        self._snapshot_key = key

    def set_timescale_writer(self, writer, tenant_id: str, bot_id: str, exchange: str, table: str | None = None) -> None:
        self._timescale_writer = writer
        self._timescale_table = table or "market_data_provider_events"
        self._ts_tenant = tenant_id
        self._ts_bot = bot_id
        self._ts_exchange = exchange

    async def _write_snapshot(self) -> None:
        if not (self._snapshot_writer and self._snapshot_key):
            return
        payload = {
            "active_provider": self.active_provider_name,
            "switch_count": self._switch_count,
            "last_switch_at": self._last_guardrail_at or None,
            "last_success_at": self._last_success_at,
        }
        await self._snapshot_writer.write(self._snapshot_key, payload)

    def get_metrics_snapshot(self) -> dict:
        return {
            "active_provider": self.active_provider_name,
            "switch_count": sum(1 for c in self._failure_counts if c == 0) + 0,  # switches counted separately
            "last_switch_at": self._last_guardrail_at or None,
            "last_success_at": self._last_success_at,
        }

    async def next_tick(self) -> Optional[dict]:
        attempts = 0
        while attempts < len(self._providers):
            provider = self._providers[self._active_index]
            tick = None
            try:
                tick = await provider.next_tick()
            except Exception as exc:  # pragma: no cover - best effort
                self._failure_counts[self._active_index] += 1
                await self._maybe_trigger_switch(
                    reason=str(exc),
                    current_index=self._active_index,
                )
                attempts += 1
                continue
            if tick:
                self._record_success(self._active_index)
                return tick
            self._failure_counts[self._active_index] += 1
            await self._maybe_trigger_switch(
                reason="empty_tick", current_index=self._active_index
            )
            attempts += 1
        if self._should_publish_failure():
            await self._publish_provider_failure_guardrail()
        await self._write_snapshot()
        await asyncio.sleep(self._idle_backoff_sec)
        return None

    def _record_success(self, index: int) -> None:
        self._failure_counts[index] = 0
        self._last_success_at = time.time()

    async def _maybe_trigger_switch(self, reason: str, current_index: int) -> None:
        if not self._can_switch(current_index):
            return
        previous_index = self._active_index
        self._active_index = min(current_index + 1, len(self._providers) - 1)
        self._switch_count += 1
        await self._publish_guardrail(
            {
                "type": "market_data_provider_switch",
                "from": self._provider_names[previous_index],
                "to": self._provider_names[self._active_index],
                "reason": reason,
            },
            alert=False,
        )
        await self._write_snapshot()

    def _can_switch(self, index: int) -> bool:
        return (
            len(self._providers) > 1
            and index < len(self._providers) - 1
            and self._failure_counts[index] >= self._switch_threshold
        )

    def _should_publish_failure(self) -> bool:
        if time.time() - self._last_success_at < self._guardrail_cooldown_sec:
            return False
        return all(count >= self._switch_threshold for count in self._failure_counts)

    async def _publish_provider_failure_guardrail(self) -> None:
        payload = {
            "type": "market_data_provider_failure",
            "active_providers": self._provider_names,
            "reason": "all_providers_stalled",
            "last_success_age": round(time.time() - self._last_success_at, 2),
        }
        await self._publish_guardrail(payload, alert=True)

    async def _publish_guardrail(self, payload: dict, alert: bool = False) -> None:
        now = time.time()
        if self._telemetry and self._telemetry_ctx:
            await self._telemetry.publish_guardrail(self._telemetry_ctx, payload)
        if alert and self._alerts and now - self._last_guardrail_at >= self._guardrail_cooldown_sec:
            message = f"Market data providers {self._provider_names} are failing"
            try:
                await self._alerts.send(
                    "market_data_provider_failure",
                    message,
                    {
                        "payload": payload,
                    },
                )
            except Exception:
                pass
            self._last_guardrail_at = now
        await self._maybe_write_timescale_event(payload, ts=now)

    async def _maybe_write_timescale_event(self, payload: dict, ts: float) -> None:
        writer = getattr(self, "_timescale_writer", None)
        if not writer:
            return
        try:
            from quantgambit.storage.timescale import TelemetryRow

            event_payload = dict(payload)
            event_payload["ts"] = ts
            row = TelemetryRow(
                tenant_id=getattr(self, "_ts_tenant", "unknown"),
                bot_id=getattr(self, "_ts_bot", "unknown"),
                symbol=None,
                exchange=getattr(self, "_ts_exchange", None),
                timestamp=datetime.fromtimestamp(ts, timezone.utc),
                payload=event_payload,
            )
            await writer.write(getattr(self, "_timescale_table", "market_data_provider_events"), row)
        except Exception:
            # best-effort metrics; failures should not break the hot path
            pass


async def _build_execution_adapter(exchange: str, provider: str, market_type: str, margin_mode: str, demo: bool = False):
    normalized = (provider or "").lower()
    if normalized not in {"ccxt", "ccxt_oco"}:
        return None
    exchange_id = (exchange or "").lower()
    creds = _load_ccxt_credentials(exchange_id, demo=demo)
    if not creds:
        return None
    client = build_ccxt_client(exchange_id, creds, market_type=market_type, margin_mode=margin_mode)
    if normalized == "ccxt_oco":
        if exchange_id == "okx":
            return OkxOcoLiveAdapter(client)
        if exchange_id == "bybit":
            return BybitOcoLiveAdapter(client)
        if exchange_id == "binance":
            return BinanceOcoLiveAdapter(client)
    if exchange_id == "okx":
        return OkxLiveAdapter(client)
    if exchange_id == "bybit":
        return BybitLiveAdapter(client)
    if exchange_id == "binance":
        return BinanceLiveAdapter(client)
    return None


def _build_order_update_provider(exchange: str, testnet: bool, demo: bool, market_type: str):
    """Build order update WebSocket provider.
    
    Credential loading priority:
    1. First try EXCHANGE_SECRET_ID -> fetch from encrypted secrets store
    2. Fall back to environment variables for manual/legacy launches
    
    Args:
        exchange: Exchange identifier (bybit, okx, binance)
        testnet: Use testnet endpoint
        demo: Use demo endpoint (Bybit only - takes precedence over testnet)
        market_type: Market type (perp, spot)
    """
    normalized = (exchange or "").lower()
    
    # Try secrets store first (most secure path)
    secret_id = os.getenv("EXCHANGE_SECRET_ID")
    if secret_id:
        from quantgambit.observability.logger import log_info
        log_info(
            "order_update_provider_loading_from_secrets",
            exchange=exchange,
            secret_id_prefix=secret_id[:40] + "..." if len(secret_id) > 40 else secret_id,
        )
        credentials = get_exchange_credentials(secret_id)
        if credentials and credentials.api_key and credentials.secret_key:
            if normalized == "okx":
                if credentials.passphrase:
                    return OkxOrderUpdateProvider(
                        OkxWsCredentials(
                            api_key=credentials.api_key,
                            secret_key=credentials.secret_key,
                            passphrase=credentials.passphrase,
                            testnet=testnet,
                        ),
                        market_type=market_type,
                    )
            elif normalized == "bybit":
                return BybitOrderUpdateProvider(
                    BybitWsCredentials(
                        api_key=credentials.api_key,
                        secret_key=credentials.secret_key,
                        testnet=testnet,
                        demo=demo,
                    ),
                    market_type=market_type,
                )
            elif normalized == "binance":
                return BinanceOrderUpdateProvider(
                    BinanceWsCredentials(
                        api_key=credentials.api_key,
                        secret_key=credentials.secret_key,
                        testnet=testnet,
                    ),
                    market_type=market_type,
                )
    
    # Fall back to environment variables
    if normalized == "okx":
        api_key = os.getenv("OKX_API_KEY")
        secret_key = os.getenv("OKX_SECRET_KEY")
        passphrase = os.getenv("OKX_PASSPHRASE")
        if api_key and secret_key and passphrase:
            return OkxOrderUpdateProvider(
                OkxWsCredentials(
                    api_key=api_key,
                    secret_key=secret_key,
                    passphrase=passphrase,
                    testnet=testnet,
                ),
                market_type=market_type,
            )
        return None
    if normalized == "bybit":
        api_key = os.getenv("BYBIT_API_KEY")
        secret_key = os.getenv("BYBIT_SECRET_KEY")
        if api_key and secret_key:
            return BybitOrderUpdateProvider(
                BybitWsCredentials(
                    api_key=api_key,
                    secret_key=secret_key,
                    testnet=testnet,
                    demo=demo,
                ),
                market_type=market_type,
            )
        return None
    if normalized == "binance":
        api_key = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        if api_key and secret_key:
            return BinanceOrderUpdateProvider(
                BinanceWsCredentials(
                    api_key=api_key,
                    secret_key=secret_key,
                    testnet=testnet,
                ),
                market_type=market_type,
            )
        return None
    return None


def _load_ccxt_credentials(exchange: str, demo: bool = False) -> CcxtCredentials | None:
    """Load exchange credentials.
    
    Security priority:
    1. First try EXCHANGE_SECRET_ID -> fetch from encrypted secrets store (most secure)
    2. Fall back to environment variables (for manual/legacy launches)
    
    The secrets store approach:
    - Credentials never appear in env vars, Redis, or logs
    - Only the secret_id reference is passed through the control plane
    - Decryption happens only here, at the point of use
    
    Args:
        exchange: Exchange identifier (bybit, okx, binance)
        demo: Use demo mode (Bybit only - separate from testnet)
    """
    # Get testnet flag from environment (applies regardless of credential source)
    testnet_env_key = f"{exchange.upper()}_TESTNET"
    is_testnet_str = os.getenv(testnet_env_key, "false").lower()
    is_testnet = is_testnet_str in {"1", "true", "yes"}
    
    # Also check the generic ORDERBOOK_TESTNET which is set by control manager
    if not is_testnet:
        is_testnet = os.getenv("ORDERBOOK_TESTNET", "false").lower() in {"1", "true", "yes"}
    
    # Check for demo mode from environment if not passed explicitly
    is_demo = demo
    if not is_demo:
        is_demo = os.getenv("BYBIT_DEMO", "false").lower() in {"1", "true", "yes"}
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SECURE PATH: Fetch from encrypted secrets store
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    secret_id = os.getenv("EXCHANGE_SECRET_ID")
    if secret_id:
        log_info(
            "credentials_loading_from_secrets",
            exchange=exchange,
            secret_id_prefix=secret_id[:40] + "..." if len(secret_id) > 40 else secret_id,
            is_testnet=is_testnet,
            is_demo=is_demo,
        )
        credentials = get_exchange_credentials(secret_id)
        if credentials and credentials.api_key and credentials.secret_key:
            # For OKX, passphrase is required
            if exchange == "okx" and not credentials.passphrase:
                log_warning(
                    "credentials_missing_passphrase",
                    exchange=exchange,
                    detail="OKX requires passphrase but none found in secrets",
                )
                # Fall through to env var fallback
            else:
                log_info(
                    "credentials_loaded_from_secrets",
                    exchange=exchange,
                    api_key_prefix=credentials.api_key[:8] + "...",
                    has_passphrase=bool(credentials.passphrase),
                    is_testnet=is_testnet,
                    is_demo=is_demo,
                )
                return CcxtCredentials(
                    api_key=credentials.api_key,
                    secret_key=credentials.secret_key,
                    passphrase=credentials.passphrase,
                    testnet=is_testnet,
                    demo=is_demo,
                )
        else:
            log_warning(
                "credentials_not_found_in_secrets",
                exchange=exchange,
                secret_id_prefix=secret_id[:40] + "..." if len(secret_id) > 40 else secret_id,
            )
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # FALLBACK PATH: Load from environment variables (legacy/manual)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    log_info("credentials_loading_from_env", exchange=exchange, is_testnet=is_testnet, is_demo=is_demo)
    
    if exchange == "okx":
        api_key = os.getenv("OKX_API_KEY")
        secret_key = os.getenv("OKX_SECRET_KEY")
        passphrase = os.getenv("OKX_PASSPHRASE")
        if api_key and secret_key and passphrase:
            return CcxtCredentials(
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                testnet=is_testnet,
            )
        return None
    if exchange == "bybit":
        api_key = os.getenv("BYBIT_API_KEY")
        secret_key = os.getenv("BYBIT_SECRET_KEY")
        if api_key and secret_key:
            return CcxtCredentials(
                api_key=api_key,
                secret_key=secret_key,
                testnet=is_testnet,
                demo=is_demo,
            )
        return None
    if exchange == "binance":
        api_key = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        if api_key and secret_key:
            return CcxtCredentials(
                api_key=api_key,
                secret_key=secret_key,
                testnet=is_testnet,
            )
        return None
    return None


def _optional_float(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_timescale_url() -> str:
    explicit = os.getenv("BOT_TIMESCALE_URL") or os.getenv("TIMESCALE_URL")
    if explicit:
        return explicit
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5432")
    name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    user = os.getenv("BOT_DB_USER", "quantgambit")
    password = os.getenv("BOT_DB_PASSWORD", "")
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{name}"


def _load_prediction_config(path: str) -> dict:
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        log_warning("prediction_config_missing", path=path)
        return {}
    except Exception as exc:
        log_warning("prediction_config_invalid", path=path, error=str(exc))
        return {}
    if isinstance(payload, dict):
        out = dict(payload)
        out["__config_path"] = path
        return out
    log_warning("prediction_config_not_dict", path=path)
    return {}


def _resolve_prediction_model_path(model_path: Optional[str], config_path: str) -> Optional[str]:
    if not model_path:
        return None
    model = Path(model_path).expanduser()
    if model.is_absolute():
        return str(model)
    candidates: list[Path] = []
    if config_path:
        try:
            cfg_path = Path(config_path).expanduser().resolve()
            candidates.append((cfg_path.parent / model).resolve())
        except Exception:
            pass
    repo_root = Path(__file__).parent.parent.parent.parent
    candidates.append((repo_root / "quantgambit-python" / model).resolve())
    candidates.append((repo_root / model).resolve())
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0] if candidates else model)


def _validate_onnx_provider(
    label: str,
    provider: Optional[object],
    provider_name: Optional[str],
    strict: bool,
) -> None:
    normalized = (provider_name or "").strip().lower()
    if normalized != "onnx" or provider is None:
        return
    validate_fn = getattr(provider, "validate", None)
    if not callable(validate_fn):
        return
    model_path = getattr(provider, "model_path", None)
    if model_path is None:
        default_provider = getattr(provider, "default_provider", None)
        model_path = getattr(default_provider, "model_path", None)
    experts = getattr(provider, "experts", None)
    is_routed = isinstance(experts, list)
    enabled_experts = None
    total_experts = None
    if is_routed:
        total_experts = len(experts or [])
        enabled_experts = len([item for item in (experts or []) if not bool(getattr(item, "disabled", False))])

    if validate_fn(time.time()):
        log_info(
            "onnx_provider_validated",
            provider_label=label,
            model_path=model_path,
            routed_experts_total=total_experts,
            routed_experts_enabled=enabled_experts,
        )
        if is_routed and total_experts and enabled_experts is not None and enabled_experts < total_experts:
            log_warning(
                "onnx_provider_partially_degraded",
                provider_label=label,
                model_path=model_path,
                routed_experts_total=total_experts,
                routed_experts_enabled=enabled_experts,
            )
        return
    if strict:
        raise RuntimeError(f"{label} ONNX provider failed validation: {model_path}")
    log_warning(
        "onnx_provider_validation_failed",
        provider_label=label,
        model_path=model_path,
        routed_experts_total=total_experts,
        routed_experts_enabled=enabled_experts,
    )


if __name__ == "__main__":
    asyncio.run(run())
