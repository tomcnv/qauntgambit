from quantgambit.control.command_consumer import CommandConsumer
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    async def xadd(self, *args, **kwargs):
        return "1-0"


class DummyRuntimeState:
    pass


class FakeActionHandler:
    def __init__(self):
        self.cancel_args = None
        self.replace_args = None

    async def cancel_order(self, order_id, client_order_id, symbol):
        self.cancel_args = (order_id, client_order_id, symbol)
        return "executed", "cancelled"

    async def replace_order(self, order_id, client_order_id, symbol, price, size):
        self.replace_args = (order_id, client_order_id, symbol, price, size)
        return "executed", "replaced"


def _consumer(handler: FakeActionHandler) -> CommandConsumer:
    return CommandConsumer(
        redis_client=RedisStreamsClient(FakeRedis()),
        runtime_state=DummyRuntimeState(),
        action_handler=handler,
    )


def test_cancel_order_command_calls_handler():
    handler = FakeActionHandler()
    consumer = _consumer(handler)
    command = {
        "type": "CANCEL_ORDER",
        "payload": {"order_id": "o1", "client_order_id": "c1", "symbol": "BTCUSDT"},
    }
    status, message = _run(consumer, command)
    assert (status, message) == ("executed", "cancelled")
    assert handler.cancel_args == ("o1", "c1", "BTCUSDT")


def test_replace_order_command_calls_handler():
    handler = FakeActionHandler()
    consumer = _consumer(handler)
    command = {
        "type": "REPLACE_ORDER",
        "payload": {"order_id": "o2", "client_order_id": "c2", "symbol": "ETHUSDT", "price": 2000.0, "size": 0.5},
    }
    status, message = _run(consumer, command)
    assert (status, message) == ("executed", "replaced")
    assert handler.replace_args == ("o2", "c2", "ETHUSDT", 2000.0, 0.5)


def _run(consumer: CommandConsumer, command: dict) -> tuple[str, str]:
    return _run_async(consumer._apply_command, command)


def _run_async(coro_fn, *args):
    import asyncio

    return asyncio.run(coro_fn(*args))
