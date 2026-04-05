from quantgambit.execution.symbols import normalize_exchange_symbol


def test_normalize_okx_symbol():
    assert normalize_exchange_symbol("okx", "BTC/USDT:USDT") == "BTC-USDT-SWAP"
    assert normalize_exchange_symbol("okx", "ETH-USDT-SWAP") == "ETH-USDT-SWAP"


def test_normalize_okx_spot_symbol():
    assert normalize_exchange_symbol("okx", "BTC/USDT", market_type="spot") == "BTC-USDT"
    assert normalize_exchange_symbol("okx", "ETH-USDT", market_type="spot") == "ETH-USDT"


def test_normalize_bybit_binance_symbols():
    assert normalize_exchange_symbol("bybit", "btc/usdt") == "BTCUSDT"
    assert normalize_exchange_symbol("binance", "BTC-USDT") == "BTCUSDT"
