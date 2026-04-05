import asyncio

from quantgambit.ingest.trade_ws import WebsocketTradeProvider, TradeWebsocketConfig
from quantgambit.observability.telemetry import TelemetryContext


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []
        self.health = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)

    async def publish_health_snapshot(self, ctx, payload):
        self.health.append(payload)


def test_trade_ws_backoff_emits_guardrail():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    provider = WebsocketTradeProvider(
        endpoint="wss://example.invalid",
        subscribe_payload=None,
        parse_message=lambda msg: [],
        exchange="okx",
        config=TradeWebsocketConfig(message_timeout_sec=0.1, stale_guardrail_sec=0.1),
    )
    provider.set_telemetry(telemetry, ctx)

    async def run_once():
        provider._register_failure()
        await asyncio.sleep(0)

    asyncio.run(run_once())
    assert telemetry.guardrails
