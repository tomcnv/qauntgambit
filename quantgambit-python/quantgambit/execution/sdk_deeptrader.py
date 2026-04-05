"""SDK client bridge for legacy exchange adaptors."""

from __future__ import annotations

from quantgambit.execution.sdk_clients import BaseSdkClient


class DeepTraderSdkClient(BaseSdkClient):
    """Wraps deeptrader ExchangeAdaptor objects."""

    exchange_name: str = "unknown"


class OkxDeepTraderSdkClient(DeepTraderSdkClient):
    exchange_name = "okx"


class BybitDeepTraderSdkClient(DeepTraderSdkClient):
    exchange_name = "bybit"


class BinanceDeepTraderSdkClient(DeepTraderSdkClient):
    exchange_name = "binance"
