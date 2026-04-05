import asyncio

from quantgambit.ingest.orderbook_ws import (
    BinanceOrderbookWebsocketProvider,
    BybitOrderbookWebsocketProvider,
    MultiplexOrderbookProvider,
    WebsocketOrderbookProvider,
    _classify_okx_error,
    _classify_bybit_error,
    _classify_binance_error,
)
from quantgambit.observability.telemetry import TelemetryContext


class FakeProvider:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    async def next_update(self):
        if not self.payloads:
            await asyncio.sleep(0.01)
            return None
        return self.payloads.pop(0)


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []
        self.health = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append((ctx, payload))

    async def publish_health_snapshot(self, ctx, payload):
        self.health.append((ctx, payload))


def test_multiplex_provider_fans_in_updates():
    provider = MultiplexOrderbookProvider(
        [FakeProvider([{"type": "snapshot"}]), FakeProvider([{"type": "delta"}])]
    )

    async def run_once():
        first = await provider.next_update()
        second = await provider.next_update()
        return {first["type"], second["type"]}

    results = asyncio.run(run_once())
    assert results == {"snapshot", "delta"}


def test_orderbook_error_classifiers():
    okx_error = {"event": "error", "code": "60001", "msg": "login failed"}
    bybit_error = {"retCode": 10001, "retMsg": "Invalid API key"}
    binance_error = {"e": "error", "msg": "Invalid API-key, IP, or permissions"}

    assert _classify_okx_error(okx_error)["type"] == "auth_failed"
    assert _classify_bybit_error(bybit_error)["type"] == "auth_failed"
    assert _classify_binance_error(binance_error)["type"] == "auth_failed"


def test_orderbook_auth_failure_emits_telemetry():
    provider = WebsocketOrderbookProvider(
        endpoint="ws://example",
        subscribe_payload=None,
        parse_message=lambda _: None,
        exchange="okx",
    )
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    provider.set_telemetry(telemetry, ctx)

    async def run_once():
        provider._emit_auth_failure("auth_failed", "bad_key")
        await asyncio.sleep(0)

    asyncio.run(run_once())
    assert telemetry.guardrails
    guard_ctx, guard_payload = telemetry.guardrails[0]
    assert guard_ctx == ctx
    assert guard_payload["type"] == "auth_failed"
    assert guard_payload["exchange"] == "okx"
    assert guard_payload["detail"] == "bad_key"
    assert telemetry.health
    health_ctx, health_payload = telemetry.health[0]
    assert health_ctx == ctx
    assert health_payload["status"] == "auth_failed"
    assert health_payload["exchange"] == "okx"


def test_orderbook_backoff_emits_metrics():
    provider = WebsocketOrderbookProvider(
        endpoint="ws://example",
        subscribe_payload=None,
        parse_message=lambda _: None,
        exchange="bybit",
    )
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="bybit")
    provider.set_telemetry(telemetry, ctx)

    async def run_once():
        provider._register_failure("connect_failed", "timeout")
        await asyncio.sleep(0)

    asyncio.run(run_once())
    assert telemetry.guardrails
    _, guard_payload = telemetry.guardrails[0]
    assert guard_payload["type"] == "ws_backoff"
    assert guard_payload["exchange"] == "bybit"
    assert guard_payload["reason"] == "connect_failed"
    assert guard_payload["detail"] == "timeout"
    assert guard_payload["attempt"] == 1
    assert guard_payload["delay_sec"] >= 1.0
    assert telemetry.health
    _, health_payload = telemetry.health[0]
    assert health_payload["status"] == "reconnecting"
    assert health_payload["exchange"] == "bybit"


def test_orderbook_provider_sends_heartbeat_ping():
    class FakeWs:
        def __init__(self):
            self.pings = 0

        async def ping(self):
            self.pings += 1

        async def recv(self):
            return "{}"

    provider = WebsocketOrderbookProvider(
        endpoint="ws://example",
        subscribe_payload=None,
        parse_message=lambda _: None,
        exchange="okx",
    )
    provider._ws = FakeWs()
    provider._last_heartbeat_at = 0.0

    async def run_once():
        await provider.next_update()

    asyncio.run(run_once())
    assert provider._ws.pings == 1


def test_orderbook_provider_endpoints_by_market_type():
    bybit_spot = BybitOrderbookWebsocketProvider("BTCUSDT", testnet=False, market_type="spot")
    bybit_perp = BybitOrderbookWebsocketProvider("BTCUSDT", testnet=False, market_type="perp")
    binance_spot = BinanceOrderbookWebsocketProvider("BTCUSDT", testnet=False, market_type="spot")
    binance_perp = BinanceOrderbookWebsocketProvider("BTCUSDT", testnet=False, market_type="perp")

    assert bybit_spot.endpoint.endswith("/v5/public/spot")
    assert bybit_perp.endpoint.endswith("/v5/public/linear")
    assert "stream.binance.com" in binance_spot.endpoint
    assert "fstream.binance.com" in binance_perp.endpoint


def _make_provider(exchange: str = "bybit"):
    return WebsocketOrderbookProvider(
        endpoint="ws://example",
        subscribe_payload=None,
        parse_message=lambda _: None,
        exchange=exchange,
    )


def test_bybit_seq_gap_requires_snapshot():
    provider = _make_provider("bybit")
    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 10}})
    assert action == "resync"
    assert gap == 0


def test_bybit_snapshot_resets_sequence_state():
    provider = _make_provider("bybit")
    action, gap = provider._check_seq_gap({"type": "snapshot", "payload": {"seq": 100}})
    assert action == "ok"
    assert gap == 0
    assert provider._snapshot_seq == 100
    assert provider._last_seq is None


def test_bybit_first_delta_after_snapshot():
    provider = _make_provider("bybit")
    provider._check_seq_gap({"type": "snapshot", "payload": {"seq": 100}})

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 100}})
    assert action == "drop"
    assert gap == 0

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 101}})
    assert action == "ok"
    assert gap == 0
    assert provider._last_seq == 101

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 103}})
    assert action == "resync"
    assert gap == 1


def test_bybit_delta_sequence_progression():
    provider = _make_provider("bybit")
    provider._check_seq_gap({"type": "snapshot", "payload": {"seq": 200}})
    provider._check_seq_gap({"type": "delta", "payload": {"seq": 201}})

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 201}})
    assert action == "drop"
    assert gap == 0

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 205}})
    assert action == "resync"
    assert gap == 3

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 202}})
    assert action == "ok"
    assert gap == 0
    assert provider._last_seq == 202


def test_bybit_l1_updates_do_not_affect_gap_logic():
    provider = _make_provider("bybit")
    provider._snapshot_seq = 100
    provider._last_seq = 100

    action, gap = provider._check_seq_gap({"type": "delta", "payload": {"seq": 999, "is_l1": True}})
    assert action == "ok"
    assert gap == 0
    assert provider._last_seq == 100
