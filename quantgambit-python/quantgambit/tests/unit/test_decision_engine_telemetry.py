import asyncio

from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.observability.telemetry import TelemetryContext


class FakeTelemetry:
    def __init__(self):
        self.decisions = []
        self.latencies = []
        self.predictions = []

    async def publish_decision(self, ctx, symbol, payload):
        self.decisions.append((symbol, payload))

    async def publish_latency(self, ctx, payload):
        self.latencies.append(payload)

    async def publish_prediction(self, ctx, symbol, payload):
        self.predictions.append((symbol, payload))


def test_decision_engine_emits_telemetry():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    # Use legacy pipeline for backwards compatibility with minimal test data
    engine = DecisionEngine(telemetry=telemetry, telemetry_context=ctx, use_gating_system=False)

    decision_input = DecisionInput(
        symbol="BTC",
        market_context={"profile_id": "micro_range_mean_reversion", "price": 100.0},
        features={"signal": 1, "price": 100.0},
        prediction={"prob": 0.7},
        expected_bps=2.5,
        expected_fee_usd=0.12,
    )
    result = asyncio.run(engine.decide(decision_input))

    assert result is True
    assert telemetry.decisions
    assert "decision_latency_ms" in telemetry.latencies[0]
