import asyncio

from quantgambit.execution.guards import GuardConfig, GuardedExchangeClient
from quantgambit.execution.manager import OrderStatus, ExchangeClient


class FakeExchange(ExchangeClient):
    def __init__(self, should_raise=False):
        self.should_raise = should_raise
        self.calls = 0

    async def close_position(
        self,
        symbol: str,
        side: str,
        size: float,
        client_order_id=None,
        order_type: str = "market",
        limit_price=None,
        post_only: bool = False,
        time_in_force=None,
    ) -> OrderStatus:
        return await self.open_position(
            symbol,
            side,
            size,
            order_type=order_type,
            limit_price=limit_price,
            post_only=post_only,
            time_in_force=time_in_force,
            client_order_id=client_order_id,
        )

    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        limit_price=None,
        post_only: bool = False,
        time_in_force=None,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ) -> OrderStatus:
        self.calls += 1
        if self.should_raise:
            raise RuntimeError("exchange_down")
        return OrderStatus(order_id="1", status="filled")

    async def fetch_order_status(self, order_id: str, symbol: str):
        self.calls += 1
        return OrderStatus(order_id=order_id, status="filled")

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str):
        self.calls += 1
        return OrderStatus(order_id=client_order_id, status="filled")


def test_guarded_exchange_rate_limits_calls():
    exchange = GuardedExchangeClient(FakeExchange(), GuardConfig(max_calls_per_sec=1.0, failure_threshold=5, reset_after_sec=1.0))

    async def run_once():
        first = await exchange.open_position("BTC", "buy", 1.0)
        second = await exchange.open_position("BTC", "buy", 1.0)
        return first.status, second.status

    status_first, status_second = asyncio.run(run_once())
    assert status_first == "filled"
    assert status_second == "rejected"


def test_guarded_exchange_rate_limit_sets_reason():
    exchange = GuardedExchangeClient(FakeExchange(), GuardConfig(max_calls_per_sec=1.0, failure_threshold=5, reset_after_sec=1.0))

    async def run_once():
        await exchange.open_position("BTC", "buy", 1.0)
        return await exchange.open_position("BTC", "buy", 1.0)

    second = asyncio.run(run_once())
    assert second.status == "rejected"
    assert second.reason == "rate_limited"


def test_guarded_exchange_circuit_breaker_opens():
    base = FakeExchange(should_raise=True)
    exchange = GuardedExchangeClient(base, GuardConfig(max_calls_per_sec=5.0, failure_threshold=1, reset_after_sec=10.0))

    async def run_once():
        first = await exchange.open_position("BTC", "buy", 1.0)
        second = await exchange.open_position("BTC", "buy", 1.0)
        return first.status, second.status, base.calls

    status_first, status_second, calls = asyncio.run(run_once())
    assert status_first == "rejected"
    assert status_second == "rejected"
    assert calls == 1
    

def test_guarded_exchange_circuit_breaker_sets_reason():
    base = FakeExchange(should_raise=True)
    exchange = GuardedExchangeClient(base, GuardConfig(max_calls_per_sec=5.0, failure_threshold=1, reset_after_sec=10.0))

    async def run_once():
        first = await exchange.open_position("BTC", "buy", 1.0)
        second = await exchange.open_position("BTC", "buy", 1.0)
        return first, second

    first, second = asyncio.run(run_once())
    assert first.reason == "exchange_error: exchange_down"
    assert second.reason == "circuit_open"


def test_guarded_exchange_polls_do_not_consume_order_guard_budget():
    exchange = GuardedExchangeClient(
        FakeExchange(),
        GuardConfig(max_calls_per_sec=1.0, failure_threshold=1, reset_after_sec=10.0),
    )

    async def run_once():
        poll_one = await exchange.fetch_order_status("1", "BTC")
        poll_two = await exchange.fetch_order_status_by_client_id("2", "BTC")
        order = await exchange.open_position("BTC", "buy", 1.0)
        return poll_one, poll_two, order

    poll_one, poll_two, order = asyncio.run(run_once())
    assert poll_one is not None
    assert poll_two is not None
    assert order.status == "filled"
