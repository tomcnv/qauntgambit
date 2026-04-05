from quantgambit.signals.feature_worker import FeaturePredictionWorker
from quantgambit.storage.redis_streams import RedisStreamsClient


class DummyRedis:
    async def xadd(self, *args, **kwargs):
        return "1-0"


def test_orderflow_window_excludes_future_events():
    worker = FeaturePredictionWorker(
        redis_client=RedisStreamsClient(DummyRedis()),
        bot_id="b1",
        exchange="okx",
    )
    symbol = "BTC-USDT-SWAP"
    # Insert an orderflow value at t=10s
    worker._update_orderflow_buffers(symbol, 10_000_000, 0.5)
    # Snapshot at t=9s should exclude the future event
    imb = worker._compute_rolling_imbalance(symbol, 9_000_000, 1.0)
    assert imb == 0.0


def test_orderflow_window_includes_boundary_events():
    worker = FeaturePredictionWorker(
        redis_client=RedisStreamsClient(DummyRedis()),
        bot_id="b1",
        exchange="okx",
    )
    symbol = "BTC-USDT-SWAP"
    now_us = 10_000_000
    # Boundary events at now and now - 5s
    worker._update_orderflow_buffers(symbol, now_us - 5_000_000, 0.2)
    worker._update_orderflow_buffers(symbol, now_us, 0.6)
    imb = worker._compute_rolling_imbalance(symbol, now_us, 5.0)
    assert abs(imb - 0.4) < 1e-6
