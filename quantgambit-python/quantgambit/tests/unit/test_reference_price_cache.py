from quantgambit.market.reference_prices import ReferencePriceCache


def test_reference_price_cache():
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    assert cache.get_reference_price("BTC") == 100.0
    assert cache.get_reference_price("ETH") is None

