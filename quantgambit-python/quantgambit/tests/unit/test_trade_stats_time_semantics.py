from quantgambit.market.trades import TradeStatsCache


def test_trade_stats_excludes_future_trades():
    cache = TradeStatsCache(window_sec=10.0, profile_window_sec=10.0)
    cache.update_trade("BTC", 10_000_000, price=100.0, size=1.0, side="buy")
    cache.update_trade("BTC", 12_000_000, price=200.0, size=1.0, side="sell")
    snap = cache.snapshot("BTC", now_ts_us=11_000_000)
    assert snap["vwap"] == 100.0
    assert snap["trades_per_second"] > 0
