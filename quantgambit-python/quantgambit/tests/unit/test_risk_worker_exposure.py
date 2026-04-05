import asyncio
import json

from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.risk.risk_worker import RiskWorker, RiskWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data, **kwargs):
        self.events.append((stream, data))
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1


class FakeOrderStore:
    def __init__(self, pending):
        self._pending = pending

    async def load_pending_intents(self):
        return self._pending


def test_risk_worker_rejects_max_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    state.add_position("BTC", "long", 1.0, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(max_total_exposure_pct=0.50, max_positions_per_symbol=2),
    )
    payload = {
        "event_id": "1",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_total_exposure_exceeded"


def test_risk_worker_counts_pending_intents_in_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    pending = [
        {
            "symbol": "BTC",
            "side": "buy",
            "size": 1.0,
            "entry_price": 100.0,
            "status": "submitted",
        }
    ]
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(max_total_exposure_pct=0.50, max_positions_per_symbol=2),
        order_store=FakeOrderStore(pending),
    )
    payload = {
        "event_id": "pending-1",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_total_exposure_exceeded"


def test_risk_worker_rejects_max_symbol_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    state.add_position("BTC", "long", 1.0, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(
            max_exposure_per_symbol_pct=0.50,
            max_total_exposure_pct=2.0,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
        ),
    )
    payload = {
        "event_id": "2",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_exposure_per_symbol_exceeded"


def test_risk_worker_rejects_max_long_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    state.add_position("BTC", "long", 0.6, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(
            max_long_exposure_pct=0.50,
            max_total_exposure_pct=2.0,
            max_positions_per_symbol=2,
        ),
    )
    payload = {
        "event_id": "3",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_long_exposure_exceeded"


def test_risk_worker_rejects_max_net_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    state.add_position("BTC", "long", 0.7, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(
            max_net_exposure_pct=0.50,
            max_total_exposure_pct=2.0,
            max_positions_per_symbol=2,
        ),
    )
    payload = {
        "event_id": "4",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 1.0, "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_net_exposure_exceeded"


def test_risk_worker_rejects_max_strategy_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    state.add_position("BTC", "long", 1.0, reference_price=100.0, strategy_id="trend")
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(
            max_exposure_per_strategy_pct=0.50,
            max_total_exposure_pct=2.0,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
        ),
    )
    payload = {
        "event_id": "10",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "ETH",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {
                "side": "buy",
                "size": 1.0,
                "entry_price": 100.0,
                "stop_loss": 90.0,
                "strategy_id": "trend",
            },
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    assert redis.events
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_exposure_per_strategy_exceeded"


def test_risk_worker_caps_size_by_exposure():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_total_exposure_pct=0.10,  # 10% of $1000 = $100 max exposure
            max_exposure_per_symbol_pct=1.0,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
            risk_per_trade_pct=0.05,  # 5% of $1000 = $50 risk budget
        ),
    )
    payload = {
        "event_id": "3",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    signal = event_payload["payload"]["signal"]
    assert event_payload["payload"]["status"] == "accepted"
    # Risk budget: $50, risk per unit: $10 (100-90), risk_units = 5.0
    # Max exposure: $100, max_units = 1.0
    # Size = min(5.0, 1.0) = 1.0 (capped by max_total_exposure_pct)
    assert signal["size"] == 1.0


def test_risk_worker_scales_size_by_portfolio_heat():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)
    # Existing position: 0.5 BTC at $100 = $50 exposure (5% of equity)
    state.add_position("BTC", "long", 0.5, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=cache,
        config=RiskWorkerConfig(
            max_total_exposure_pct=0.10,  # 10% of $1000 = $100 max exposure
            max_exposure_per_symbol_pct=1.0,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
            risk_per_trade_pct=0.05,  # 5% of $1000 = $50 risk budget
        ),
    )
    payload = {
        "event_id": "3a",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    signal = event_payload["payload"]["signal"]
    assert event_payload["payload"]["status"] == "accepted"
    # Existing exposure: $50 (5% of equity)
    # Portfolio heat: 5% / 10% = 0.5, heat_scale = 1.0 - 0.5 = 0.5
    # Risk budget: $50 * 0.5 = $25, risk_units = $25 / $10 = 2.5
    # Remaining exposure: $100 - $50 = $50, max_units = 0.5
    # Size = min(2.5, 0.5) = 0.5 (capped by remaining exposure)
    assert signal["size"] == 0.5


def test_risk_worker_scales_size_by_risk_context():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            risk_per_trade_pct=0.10,
            max_total_exposure_pct=1.0,
            max_exposure_per_symbol_pct=1.0,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
        ),
    )
    payload = {
        "event_id": "3b",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "risk_context": {
                "volatility_regime": "high",
                "liquidity_regime": "thin",
                "market_regime": "chop",
                "regime_confidence": 1.0,
            },
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    signal = event_payload["payload"]["signal"]
    assert event_payload["payload"]["status"] == "accepted"
    assert abs(signal["size"] - 1.05) < 1e-6


def test_risk_worker_rejects_missing_price():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(min_position_size_usd=0.0),
    )
    payload = {
        "event_id": "4",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy"},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "missing_price"


def test_risk_worker_rejects_stale_reference_price():
    class FakePriceCache:
        def get_reference_price_with_ts(self, symbol):
            return 100.0, 1.0

    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        price_provider=FakePriceCache(),
        config=RiskWorkerConfig(min_position_size_usd=0.0, max_reference_price_age_sec=0.001),
    )
    payload = {
        "event_id": "4a",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy"},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "stale_reference_price"


def test_risk_worker_rejects_max_positions_per_symbol():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0)
    state.add_position("BTC", "long", 1.0, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(max_positions_per_symbol=1),
    )
    payload = {
        "event_id": "5",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_positions_per_symbol_exceeded"


def test_risk_worker_counts_closing_positions_for_exposure_and_limits():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100.0)
    state.add_position("BTC", "long", 1.0, reference_price=100.0)

    async def mark_closing():
        await state.mark_closing("BTC", "exit_in_flight")

    asyncio.run(mark_closing())

    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_total_exposure_pct=0.50,
            max_positions_per_symbol=1,
            min_position_size_usd=0.0,
        ),
    )
    payload = {
        "event_id": "5b",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] in {
        "max_positions_per_symbol_exceeded",
        "max_total_exposure_exceeded",
    }


def test_risk_worker_allows_replace_for_opposite_side():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=100000.0)
    state.add_position("BTC", "long", 1.0, reference_price=100.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_positions_per_symbol=1,
            max_positions=10,
            max_total_exposure_pct=5.0,
            min_position_size_usd=0.0,
            allow_position_replacement=True,
            replace_min_edge_bps=10.0,
        ),
    )
    payload = {
        "event_id": "5a",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "sell", "entry_price": 100.0, "stop_loss": 110.0},
            "candidate": {"expected_edge_bps": 50.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["status"] == "accepted"
    assert event_payload["payload"]["signal"]["replace_position"] is True


def test_risk_worker_rejects_drawdown_limit():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=900.0, peak_balance=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_drawdown_pct=0.05,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
            max_total_exposure_pct=2.0,
        ),
    )
    payload = {
        "event_id": "6",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_drawdown_exceeded"


def test_risk_worker_rejects_daily_loss_limit():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0, daily_pnl=-60.0, peak_balance=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_daily_loss_pct=0.05,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
            max_total_exposure_pct=2.0,
        ),
    )
    payload = {
        "event_id": "7",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_daily_loss_exceeded"


def test_risk_worker_rejects_consecutive_losses_limit():
    redis = FakeRedis()
    state = InMemoryStateManager()
    state.update_account_state(equity=1000.0, consecutive_losses=3, peak_balance=1000.0)
    worker = RiskWorker(
        redis_client=RedisStreamsClient(redis),
        state_manager=state,
        bot_id="b1",
        exchange="okx",
        config=RiskWorkerConfig(
            max_consecutive_losses=3,
            min_position_size_usd=0.0,
            max_positions_per_symbol=2,
            max_total_exposure_pct=2.0,
        ),
    )
    payload = {
        "event_id": "8",
        "event_type": "decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1000000,
        "ts_canon_us": 1000000,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "decision": "accepted",
            "signal": {"side": "buy", "entry_price": 100.0, "stop_loss": 90.0},
            "status": "accepted",
        },
    }

    async def run_once():
        await worker._handle_message({"data": json.dumps(payload)})

    asyncio.run(run_once())
    event_payload = json.loads(redis.events[0][1]["data"])
    assert event_payload["payload"]["rejection_reason"] == "max_consecutive_losses_exceeded"
