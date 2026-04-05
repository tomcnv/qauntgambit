from quantgambit.ingest.candles import CandleAggregator


def test_candle_aggregator_rolls_over():
    agg = CandleAggregator(timeframe_sec=60)
    first = agg.update("BTC", 100.0, 10.0, volume=1.0)
    assert first is None
    agg.update("BTC", 110.0, 12.0, volume=2.0)
    finalized = agg.update("BTC", 160.0, 11.0, volume=1.0)
    assert finalized is not None
    assert finalized.open == 10.0
    assert finalized.high == 12.0
    assert finalized.low == 10.0
    assert finalized.close == 12.0
    assert finalized.volume == 3.0
