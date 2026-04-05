import asyncio
import json
from collections import deque

from quantgambit.ingest.schemas import validate_feature_snapshot
from quantgambit.market.trades import TradeStatsCache
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.streams = {}

    async def get(self, key):
        return None

    async def xadd(self, stream, data):
        self.streams.setdefault(stream, []).append(data)
        return "1-0"

    async def xrevrange(self, stream, count=100):
        items = self.streams.get(stream, [])
        return [(f"{idx}-0", item) for idx, item in enumerate(reversed(items[-count:]), start=1)]


def test_feature_snapshot_includes_prediction():
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")
    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    validate_feature_snapshot(snapshot)
    prediction = snapshot.get("prediction")
    assert prediction is not None
    assert prediction["direction"] in {"up", "down", "flat", "unknown"}


def test_feature_worker_latency_data_includes_legacy_timestamp_aliases():
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")
    worker._feed_timestamps["BTC"] = {"orderbook": 100.5, "trade": 101.5}

    class FakeOrderbookCache:
        def get_latency_data(self, symbol):
            assert symbol == "BTC"
            return {"book_cts_ms": 100123, "trade_ts_ms": 101456}

    worker.orderbook_cache = FakeOrderbookCache()
    latency = worker._get_latency_data("BTC")

    assert latency["book_cts_ms"] == 100123
    assert latency["trade_ts_ms"] == 101456
    assert latency["book_timestamp_ms"] == 100123
    assert latency["timestamp_ms"] == 101456


def test_feature_worker_warms_indicator_state_from_candle_stream():
    redis = FakeRedis()
    client = RedisStreamsClient(redis)
    worker = FeaturePredictionWorker(client, bot_id="b1", exchange="okx")

    for idx in range(30):
        candle_event = {
            "event_id": f"c{idx}",
            "event_type": "candle",
            "schema_version": "v1",
            "timestamp": str(100 + idx),
            "payload": {
                "symbol": "BTC",
                "timestamp": 100 + idx,
                "timeframe_sec": 300,
                "open": 100.0 + idx,
                "high": 101.0 + idx,
                "low": 99.0 + idx,
                "close": 100.5 + idx,
                "volume": 10.0 + idx,
            },
        }
        redis.streams.setdefault(worker.config.candle_stream, []).append(
            {"data": json.dumps(candle_event)}
        )

    asyncio.run(worker._warmup_indicator_state_from_candle_stream())

    snapshot = asyncio.run(
        worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 200.0, "bid": 129.0, "ask": 131.0, "last": 130.0},
        )
    )

    assert snapshot is not None
    assert snapshot["features"]["ema_fast_15m"] is not None
    assert snapshot["features"]["ema_slow_15m"] is not None
    assert snapshot["features"]["atr_5m"] is not None


def test_feature_worker_emits_prediction_telemetry():
    redis = FakeRedis()
    client = RedisStreamsClient(redis)

    class FakeTelemetry:
        def __init__(self):
            self.predictions = []

        async def publish_prediction(self, ctx, symbol, payload):
            self.predictions.append((symbol, payload))

        async def publish_guardrail(self, ctx, payload):
            return None

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    worker = FeaturePredictionWorker(
        redis_client=client,
        bot_id="b1",
        exchange="okx",
        telemetry=telemetry,
        telemetry_context=ctx,
    )
    ts_us = 100 * 1_000_000
    event = {
        "event_id": "1",
        "event_type": "market_tick",
        "schema_version": "v1",
        "timestamp": "100",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 100,
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": None,
            "bid": 99.0,
            "ask": 101.0,
            "last": 100.0,
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    assert telemetry.predictions
    assert telemetry.predictions[0][0] == "BTC"
    payload = telemetry.predictions[0][1]
    assert payload.get("confidence") is not None


def test_prediction_confidence_calibration():
    class StaticProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {"timestamp": timestamp, "direction": "up", "confidence": 0.4}

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        prediction_provider=StaticProvider(),
        prediction_confidence_scale=2.0,
        prediction_confidence_bias=0.1,
    )
    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    prediction = snapshot.get("prediction")
    assert prediction is not None
    assert prediction["confidence_raw"] == 0.4
    assert prediction["confidence"] == 0.9


def test_feature_snapshot_includes_distance_to_poc_bps_fields():
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")

    class FakeTradeCache:
        def snapshot(self, symbol, now_ts_us=None):
            return {
                "point_of_control": 99.0,
                "value_area_low": 98.0,
                "value_area_high": 101.0,
            }

    worker.trade_cache = FakeTradeCache()

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    features = snapshot["features"]
    market_context = snapshot["market_context"]

    assert features["distance_to_poc_bps"] == 100.0
    assert features["distance_to_val_bps"] == 200.0
    assert features["distance_to_vah_bps"] == 100.0
    assert market_context["distance_to_poc_bps"] == 100.0
    assert market_context["distance_to_val_bps"] == 200.0
    assert market_context["distance_to_vah_bps"] == 100.0


def test_feature_snapshot_includes_shadow_prediction_when_configured():
    class PrimaryProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {"timestamp": timestamp, "direction": "up", "confidence": 0.6, "source": "primary"}

    class ShadowProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {"timestamp": timestamp, "direction": "down", "confidence": 0.7, "source": "shadow"}

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        prediction_provider=PrimaryProvider(),
        shadow_prediction_provider=ShadowProvider(),
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot.get("prediction") is not None
    assert snapshot.get("prediction_shadow") is not None


def test_feature_snapshot_includes_ai_context(monkeypatch):
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")
    monkeypatch.setattr(
        "quantgambit.signals.feature_worker.get_symbol_context",
        lambda symbol: {
            "sentiment": {"combined_sentiment": 0.35, "is_stale": False},
            "events": {"event_flags": ["macro_week"]},
        },
    )
    monkeypatch.setattr(
        "quantgambit.signals.feature_worker.get_global_context",
        lambda: {"sentiment": {"combined_sentiment": 0.1}},
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTCUSDT",
            {"symbol": "BTCUSDT", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    market_context = snapshot["market_context"]
    assert market_context["sentiment_score"] == 0.35
    assert market_context["context"]["sentiment"]["combined_sentiment"] == 0.35
    assert market_context["context"]["global_context"]["sentiment"]["combined_sentiment"] == 0.1


def test_feature_worker_updates_trade_cache_from_shared_trade_ticks(monkeypatch):
    monkeypatch.setenv("TRADE_SOURCE", "shared")
    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        trade_cache=TradeStatsCache(),
    )

    ts_us = 100 * 1_000_000
    event = {
        "event_id": "trade-1",
        "event_type": "market_tick",
        "schema_version": "v1",
        "timestamp": "100",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": 100.0,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 100.0,
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": 100.0,
            "last": 101.5,
            "volume": 2.0,
            "source": "trade_feed",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    snapshot = worker.trade_cache.snapshot("BTC", now_ts_us=ts_us)
    assert snapshot["vwap"] == 101.5


def test_feature_worker_blocks_prediction_on_stale_quality():
    class FakeQualityTracker:
        async def snapshot(self, symbol, now_ts=None):
            return {"status": "stale", "quality_score": 0.2, "flags": ["tick_stale"]}

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        quality_tracker=FakeQualityTracker(),
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot.get("prediction") is None
    assert snapshot["market_context"]["prediction_blocked"] == "stale_data"
    assert snapshot["market_context"]["orderbook_sync_state"] == "unknown"
    assert snapshot["market_context"]["trade_sync_state"] == "unknown"


def test_feature_worker_emits_prediction_suppressed_telemetry():
    class FakeQualityTracker:
        async def snapshot(self, symbol, now_ts=None):
            return {"status": "stale", "quality_score": 0.2, "flags": ["tick_stale"]}

    class FakeTelemetry:
        def __init__(self):
            self.predictions = []

        async def publish_prediction(self, ctx, symbol, payload):
            self.predictions.append((symbol, payload))

        async def publish_guardrail(self, ctx, payload):
            return None

    redis = FakeRedis()
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    worker = FeaturePredictionWorker(
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        quality_tracker=FakeQualityTracker(),
        telemetry=telemetry,
        telemetry_context=ctx,
    )
    ts_us = 100 * 1_000_000
    event = {
        "event_id": "1",
        "event_type": "market_tick",
        "schema_version": "v1",
        "timestamp": "100",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 100,
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": None,
            "bid": 99.0,
            "ask": 101.0,
            "last": 100.0,
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    assert telemetry.predictions
    payload = telemetry.predictions[0][1]
    assert payload["status"] == "suppressed"
    assert payload["reason"] == "stale_data"
    assert payload["reject"] is True
    assert payload["abstain"] is True


def test_feature_worker_blocks_on_orderbook_gap():
    class FakeQualityTracker:
        async def snapshot(self, symbol, now_ts=None):
            return {"status": "degraded", "quality_score": 0.7, "flags": ["orderbook_gap"]}

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(gate_on_trade_stale=True),
        quality_tracker=FakeQualityTracker(),
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    assert snapshot.get("prediction") is None
    status = snapshot.get("prediction_status") or {}
    assert status.get("reason") == "orderbook_gap"


def test_feature_worker_blocks_on_trade_stale():
    class FakeQualityTracker:
        async def snapshot(self, symbol, now_ts=None):
            return {"status": "degraded", "quality_score": 0.7, "flags": ["trade_stale"]}

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(gate_on_trade_stale=True),
        quality_tracker=FakeQualityTracker(),
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    assert snapshot.get("prediction") is None
    status = snapshot.get("prediction_status") or {}
    assert status.get("reason") == "trade_stale"


def test_feature_worker_falls_back_when_onnx_returns_none():
    from quantgambit.signals.prediction_providers import OnnxPredictionProvider

    # Build a real OnnxPredictionProvider object with missing model path so
    # _build_prediction returns None and exercises heuristic failover.
    broken_provider = OnnxPredictionProvider(
        model_path=None,
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        prediction_provider=broken_provider,
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    prediction = snapshot.get("prediction")
    assert prediction is not None
    assert prediction.get("onnx_failure_fallback") is True
    assert prediction.get("onnx_failure_reason") == "prediction_unavailable"


def test_feature_worker_blocks_on_candle_stale():
    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(gate_on_candle_stale=True, candle_stale_sec=1.0),
    )
    worker._latest_candle_ts["BTC"] = 0.0

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    assert snapshot.get("prediction") is None
    status = snapshot.get("prediction_status") or {}
    assert status.get("reason") == "candle_stale"
    assert snapshot["market_context"]["candle_sync_state"] == "stale"


def test_feature_worker_uses_any_candle_timeframe_for_staleness():
    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(gate_on_candle_stale=True, candle_stale_sec=1.0),
    )
    # AMT defaults to 300s, but this candle event is 60s. Feed staleness should still be fresh.
    candle_event = {
        "event_id": "c1",
        "event_type": "candle",
        "schema_version": "v1",
        "timestamp": "100.0",
        "ts_recv_us": 100_000_000,
        "ts_canon_us": 100_000_000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "symbol": "BTC",
        "exchange": "okx",
        "payload": {
            "symbol": "BTC",
            "timestamp": 60.0,
            "timeframe_sec": 60,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        },
    }

    async def run_once():
        await worker._handle_candle({"data": json.dumps(candle_event)})
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.5, "bid": 100.0, "ask": 101.0, "last": 100.5},
        )

    snapshot = asyncio.run(run_once())
    assert snapshot is not None
    assert snapshot["market_context"]["candle_sync_state"] == "synced"
    status = snapshot.get("prediction_status") or {}
    assert status.get("reason") != "candle_stale"


def test_feature_worker_emits_multi_horizon_and_regime_fields():
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")
    history = worker._price_history.setdefault("BTC", deque(maxlen=600))
    history.append((1000.0, 100.0))
    history.append((4300.0, 105.0))
    history.append((4540.0, 110.0))

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 4600.0, "bid": 119.0, "ask": 121.0, "last": 120.0},
        )

    snapshot = asyncio.run(build_once())
    features = snapshot["features"]
    context = snapshot["market_context"]
    assert features["price_change_1m"] != 0.0
    assert features["price_change_5m"] != 0.0
    assert features["price_change_1h"] != 0.0
    assert context["price_change_1m"] == features["price_change_1m"]
    assert context["price_change_5m"] == features["price_change_5m"]
    assert context["price_change_1h"] == features["price_change_1h"]
    assert context["market_regime"] is not None
    assert context["regime_family"] is not None


def test_feature_worker_price_history_uses_per_second_bucketing_for_5m():
    worker = FeaturePredictionWorker(RedisStreamsClient(FakeRedis()), bot_id="b1", exchange="okx")
    symbol = "BTC"
    # Simulate high-frequency updates (20 ticks/sec) over 6 minutes.
    start_us = 1_000_000
    for sec in range(0, 360):
        for tick in range(20):
            ts_us = start_us + (sec * 1_000_000) + (tick * 50_000)
            px = 100.0 + (sec * 0.01) + (tick * 0.0001)
            worker._update_history(symbol, ts_us, px)

    async def build_once():
        return await worker._build_snapshot(
            symbol,
            {
                "symbol": symbol,
                "timestamp": (start_us / 1_000_000.0) + 360.2,
                "bid": 103.5,
                "ask": 103.6,
                "last": 103.55,
            },
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    features = snapshot["features"]
    assert features["price_change_5m"] != 0.0


def test_feature_worker_blocks_on_drift_snapshot():
    class FakeReader:
        async def read(self, key):
            return {"status": "drift"}

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
    )
    worker.snapshot_reader = FakeReader()
    worker.drift_block_enabled = True
    worker.drift_snapshot_key = "quantgambit:t1:b1:prediction:drift:latest"
    worker.config.drift_check_interval_sec = 0.0

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    assert snapshot["market_context"]["prediction_blocked"] == "drift_detected"


def test_feature_worker_blocks_on_symbol_specific_drift_snapshot():
    class FakeReader:
        async def read(self, key):
            return {
                "status": "ok",
                "symbols": {
                    "BTC": {"status": "drift"},
                    "ETH": {"status": "ok"},
                },
            }

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
    )
    worker.snapshot_reader = FakeReader()
    worker.drift_block_enabled = True
    worker.drift_snapshot_key = "quantgambit:t1:b1:prediction:drift:latest"
    worker.config.drift_check_interval_sec = 0.0

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    assert snapshot["market_context"]["prediction_blocked"] == "drift_detected"


def test_feature_worker_falls_back_to_heuristic_when_score_gate_blocks_onnx():
    class OnnxProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {"timestamp": timestamp, "direction": "up", "confidence": 0.9, "source": "onnx_v1"}

    class FakeReader:
        async def read(self, key):
            return {
                "status": "blocked",
                "timestamp": 100.0,
                "symbols": {
                    "BTC": {
                        "status": "blocked",
                        "samples": 500,
                        "ml_score": 45.0,
                        "exact_accuracy": 0.42,
                        "ece_top1": 0.31,
                    }
                },
            }

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        prediction_provider=OnnxProvider(),
    )
    worker.snapshot_reader = FakeReader()
    worker.score_gate_enabled = True
    worker.score_snapshot_key = "quantgambit:t1:b1:prediction:score:latest"
    worker._score_gate_interval_sec = 0.0
    worker._score_gate_mode = "fallback_heuristic"

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    prediction = snapshot.get("prediction")
    assert prediction is not None
    # Should no longer use ONNX for this symbol due to score gate.
    assert prediction.get("source") == "heuristic_v1"
    assert prediction.get("score_gate_fallback") is True
    assert snapshot["market_context"]["prediction_score_gate_status"] == "fallback"


def test_feature_worker_emits_shadow_when_score_gate_blocks():
    class OnnxProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {"timestamp": timestamp, "direction": "up", "confidence": 0.9, "source": "onnx_v1"}

    class ShadowProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {"timestamp": timestamp, "direction": "down", "confidence": 0.7, "source": "onnx_v1_shadow"}

    class FakeReader:
        async def read(self, key):
            return {
                "status": "blocked",
                "timestamp": 100.0,
                "symbols": {
                    "BTC": {
                        "status": "blocked",
                        "samples": 500,
                        "ml_score": 45.0,
                        "exact_accuracy": 0.42,
                        "ece_top1": 0.31,
                    }
                },
            }

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        prediction_provider=OnnxProvider(),
        shadow_prediction_provider=ShadowProvider(),
    )
    worker.snapshot_reader = FakeReader()
    worker.score_gate_enabled = True
    worker.score_snapshot_key = "quantgambit:t1:b1:prediction:score:latest"
    worker._score_gate_interval_sec = 0.0
    worker._score_gate_mode = "block"

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot.get("prediction") is None
    assert snapshot.get("prediction_shadow") is not None
    assert snapshot["prediction_shadow"]["source"] == "onnx_v1_shadow"
    assert snapshot["market_context"]["prediction_score_gate_status"] == "blocked"
    assert snapshot["prediction_status"]["reason"] == "score_status_blocked"


def test_feature_worker_ignores_foreign_score_snapshot_key(monkeypatch):
    monkeypatch.setenv("TENANT_ID", "t1")
    monkeypatch.setenv(
        "PREDICTION_SCORE_SNAPSHOT_KEY",
        "quantgambit:foreign-tenant:foreign-bot:prediction:score:latest",
    )
    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
    )
    assert worker.score_snapshot_key == "quantgambit:t1:b1:prediction:score:latest"


def test_feature_worker_does_not_proxy_orderflow_imbalance():
    from quantgambit.market.reference_prices import ReferencePriceCache

    cache = ReferencePriceCache()
    cache.update_orderbook("BTC", bids=[[100, 1]], asks=[[101, 1]], timestamp=100.0)
    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        orderbook_cache=cache,
        trade_cache=None,
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 100.0, "ask": 101.0, "last": 100.5},
        )

    snapshot = asyncio.run(build_once())
    assert snapshot is not None
    assert snapshot["features"]["orderbook_imbalance"] != 0.0
    assert snapshot["features"]["orderflow_imbalance"] is None


def test_feature_worker_sets_reason_for_reject_without_reason():
    class RejectingProvider:
        def build_prediction(self, features, market_context, timestamp):
            return {
                "timestamp": timestamp,
                "direction": "up",
                "confidence": 0.7,
                "source": "onnx_v1",
                "reject": True,
            }

    worker = FeaturePredictionWorker(
        RedisStreamsClient(FakeRedis()),
        bot_id="b1",
        exchange="okx",
        prediction_provider=RejectingProvider(),
    )

    async def build_once():
        return await worker._build_snapshot(
            "BTC",
            {"symbol": "BTC", "timestamp": 100.0, "bid": 99.0, "ask": 101.0, "last": 100.0},
        )

    snapshot = asyncio.run(build_once())
    prediction = snapshot.get("prediction")
    assert prediction is not None
    assert prediction.get("reject") is True
    assert prediction.get("reason") == "provider_reject_unspecified"
