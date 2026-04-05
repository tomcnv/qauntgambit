from quantgambit.market.source_policy import (
    SourceFusionPolicy,
    classify_tick_source,
    SOURCE_ORDERBOOK,
    SOURCE_TICKER,
    SOURCE_TRADE,
)


def test_source_policy_prefers_trade_when_fresh():
    policy = SourceFusionPolicy(priority=(SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER), stale_us=5_000_000)
    now = 10_000_000
    last_seen = {
        SOURCE_ORDERBOOK: now - 1_000_000,
        SOURCE_TRADE: now - 2_000_000,
    }
    assert policy.preferred_source(last_seen, now) == SOURCE_TRADE


def test_source_policy_falls_back_when_trade_stale():
    policy = SourceFusionPolicy(priority=(SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER), stale_us=5_000_000)
    now = 10_000_000
    last_seen = {
        SOURCE_TRADE: now - 6_000_000,
        SOURCE_ORDERBOOK: now - 1_000_000,
    }
    assert policy.preferred_source(last_seen, now) == SOURCE_ORDERBOOK


def test_source_policy_should_update_blocks_non_preferred():
    policy = SourceFusionPolicy(priority=(SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER), stale_us=5_000_000)
    now = 10_000_000
    last_seen = {
        SOURCE_TRADE: now - 1_000_000,
        SOURCE_ORDERBOOK: now - 1_000_000,
    }
    assert policy.should_update(SOURCE_ORDERBOOK, last_seen, now, has_reference=True) is False
    assert policy.should_update(SOURCE_TRADE, last_seen, now, has_reference=True) is True


def test_classify_tick_source():
    orderbook_tick = {"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]}
    trade_tick = {"last": 100.0, "source": "trade_feed"}
    ticker_tick = {"bid": 100.0, "ask": 101.0}
    assert classify_tick_source(orderbook_tick) == SOURCE_ORDERBOOK
    assert classify_tick_source(trade_tick) == SOURCE_TRADE
    assert classify_tick_source(ticker_tick) == SOURCE_TICKER
