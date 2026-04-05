from quantgambit.market.ticks import normalize_tick


def test_normalize_tick():
    raw = {"instId": "BTC-USDT-SWAP", "bestBid": "100", "bestAsk": "102", "lastPrice": "101"}
    tick = normalize_tick(raw)
    assert tick["symbol"] == "BTC-USDT-SWAP"
    assert tick["bid"] == 100.0
    assert tick["ask"] == 102.0
    assert tick["last"] == 101.0


def test_normalize_tick_filters_orderbook_levels():
    raw = {
        "symbol": "BTC",
        "bids": [[101, 1], ["bad", 2], [100, -1]],
        "asks": [[102, 1], [103, 0]],
    }
    tick = normalize_tick(raw)
    assert tick["bids"] == [[101.0, 1.0]]
    assert tick["asks"] == [[102.0, 1.0]]
