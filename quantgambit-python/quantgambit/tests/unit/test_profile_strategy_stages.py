import asyncio

from quantgambit.signals.pipeline import ProfileRoutingStage, SignalStage, StageContext, StageResult


class FakeRouter:
    def route(self, market_context):
        return "profile_a"


class FakeRegistry:
    def generate_signal(self, profile_id, features):
        return True


class FakeRegistryWithContext:
    def __init__(self):
        self.captured_features = None
        self.captured_market_context = None

    def generate_signal_with_context(self, symbol, profile_id, features, market_context, account):
        self.captured_features = dict(features)
        self.captured_market_context = dict(market_context)
        return {"side": "long", "strategy_id": "unit_test"}


def test_profile_routing_and_signal():
    ctx = StageContext(symbol="BTC", data={"features": {"signal": True}, "market_context": {}})
    routing = ProfileRoutingStage(FakeRouter())
    signal_stage = SignalStage(FakeRegistry())

    result = asyncio.run(routing.run(ctx))
    assert result == StageResult.CONTINUE
    assert ctx.profile_id == "profile_a"

    result = asyncio.run(signal_stage.run(ctx))
    assert result == StageResult.CONTINUE
    assert ctx.signal


def test_signal_stage_passes_profile_scores_to_registry_context():
    registry = FakeRegistryWithContext()
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "features": {"price": 100.0, "spread_bps": 1.0, "timestamp": 123.0},
            "market_context": {"session": "us"},
            "profile_scores": [
                {"profile_id": "value_area_rejection", "eligible": True, "score": 0.91},
                {"profile_id": "poc_magnet", "eligible": True, "score": 0.84},
            ],
        },
        profile_id="value_area_rejection",
    )
    stage = SignalStage(registry)

    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
    assert isinstance(ctx.signal, dict)
    assert registry.captured_features is not None
    assert registry.captured_market_context is not None
    assert registry.captured_features.get("profile_scores")
    assert registry.captured_market_context.get("profile_scores")
