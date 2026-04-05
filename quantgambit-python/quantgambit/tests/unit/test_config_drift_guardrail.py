import asyncio

from quantgambit.config.repository import ConfigRepository
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.runtime.app import Runtime, RuntimeConfig


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []
        self.health = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append((ctx, payload))

    async def publish_health_snapshot(self, ctx, payload):
        self.health.append((ctx, payload))


class FakeSnapshots:
    def __init__(self):
        self.writes = []

    async def write(self, key, payload):
        self.writes.append((key, payload))


class FakeAlerts:
    def __init__(self):
        self.calls = []

    async def send(self, alert_type, message, metadata=None):
        self.calls.append((alert_type, message, metadata))


class FakeConfigStore:
    def __init__(self, version):
        self.version = version

    async def get_latest(self, tenant_id, bot_id):
        class Record:
            def __init__(self, version):
                self.version = version

        return Record(self.version)


def test_config_drift_emits_guardrail():
    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx", version=1)
    runtime.config_store = FakeConfigStore(version=2)
    runtime.config_repository = ConfigRepository()
    runtime.telemetry = FakeTelemetry()
    runtime.telemetry_context = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    runtime.snapshots = FakeSnapshots()
    runtime.alerts = FakeAlerts()

    async def run_once():
        await runtime._check_config_drift()

    asyncio.run(run_once())
    assert runtime.telemetry.guardrails
    _, payload = runtime.telemetry.guardrails[0]
    assert payload["type"] == "config_drift"
    assert payload["stored_version"] == 2
    assert payload["runtime_version"] == 1
    assert runtime.telemetry.health
    assert runtime.snapshots.writes
    assert runtime.alerts.calls
