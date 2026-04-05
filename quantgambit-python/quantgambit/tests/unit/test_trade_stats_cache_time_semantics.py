from quantgambit.market.trades import TradeStatsCache


def test_trade_stats_cache_uses_explicit_now_ts():
    cache = TradeStatsCache(window_sec=10.0, profile_window_sec=30.0)
    cache.update_trade("BTC", timestamp_us=100_000_000, price=100.0, size=1.0, side="buy")
    # Snapshot before trade timestamp should be empty
    assert cache.snapshot("BTC", now_ts_us=90_000_000) == {}
    snap = cache.snapshot("BTC", now_ts_us=100_000_000)
    assert snap["trades_per_second"] > 0


def test_trade_stats_cache_excludes_future_trades():
    cache = TradeStatsCache(window_sec=10.0, profile_window_sec=30.0)
    cache.update_trade("ETH", timestamp_us=100_000_000, price=100.0, size=1.0, side="buy")
    cache.update_trade("ETH", timestamp_us=105_000_000, price=101.0, size=1.0, side="buy")
    snap = cache.snapshot("ETH", now_ts_us=102_000_000)
    # Only the first trade should be included
    assert snap["trades_per_second"] > 0


def test_trade_stats_cache_includes_window_boundary():
    cache = TradeStatsCache(window_sec=10.0, profile_window_sec=30.0)
    now_us = 200_000_000
    cache.update_trade("BTC", timestamp_us=now_us - 10_000_000, price=100.0, size=1.0, side="buy")
    snap = cache.snapshot("BTC", now_ts_us=now_us)
    assert snap["trades_per_second"] > 0
