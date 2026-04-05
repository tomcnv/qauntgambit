import asyncio

from quantgambit.execution.manager import OrderStatus
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.runtime.app import Runtime, RuntimeConfig


class FakeOrderStore:
    def __init__(self):
        self.intent_updates = []

    async def load_pending_intents(self):
        return [
            {
                "intent_id": "i1",
                "client_order_id": "c1",
                "symbol": "BTC",
                "side": "buy",
                "size": 1.0,
                "status": "submitted",
            }
        ]

    async def record_intent(self, **kwargs):
        self.intent_updates.append(kwargs)


class FakeExecutionManager:
    def __init__(self):
        self.recorded = []

    async def poll_order_status(self, order_id, symbol):
        return None

    async def poll_order_status_by_client_id(self, client_order_id, symbol):
        return OrderStatus(order_id="o1", status="filled")

    async def record_order_status(self, intent, status):
        self.recorded.append((intent, status))
        return True


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)


def test_runtime_recovers_pending_intents():
    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
    runtime.order_store = FakeOrderStore()
    runtime.execution_manager = FakeExecutionManager()
    runtime.telemetry = FakeTelemetry()
    runtime.telemetry_context = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

    async def run_once():
        await runtime._recover_pending_intents()

    asyncio.run(run_once())
    assert runtime.execution_manager.recorded
    assert runtime.order_store.intent_updates
    assert any(item.get("type") == "order_recovery_resolved" for item in runtime.telemetry.guardrails)
