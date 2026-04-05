import pytest
import time

from quantgambit.runtime.entrypoint import ResilientMarketDataProvider


class DummyProvider:
    def __init__(self, *, fail=True):
        self.fail = fail

    async def next_tick(self):
        if self.fail:
            raise RuntimeError("no data")
        return None


class DummyTelemetry:
    def __init__(self):
        self.events = []

    async def publish_guardrail(self, ctx, payload):
        self.events.append(payload)


@pytest.mark.asyncio
async def test_resilient_provider_failure_guardrail_throttled():
    primary = DummyProvider(fail=True)
    fallback = DummyProvider(fail=True)
    provider = ResilientMarketDataProvider(
        providers=[primary, fallback],
        provider_names=["ws", "ccxt"],
        switch_threshold=1,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=10.0,
    )
    telemetry = DummyTelemetry()
    provider.set_telemetry(telemetry, object())

    provider._last_success_at = time.time()
    await provider.next_tick()
    failure_events = [event for event in telemetry.events if event.get("type") == "market_data_provider_failure"]
    assert len(failure_events) == 0

    provider._last_success_at = time.time() - 11
    await provider.next_tick()

    failure_events = [event for event in telemetry.events if event.get("type") == "market_data_provider_failure"]
    assert len(failure_events) == 1
