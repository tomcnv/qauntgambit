import pytest

from quantgambit.signals.pipeline import SignalStage, StageContext
from quantgambit.signals.stages.amt_calculator import AMTLevels


class CapturingRegistry:
    def __init__(self) -> None:
        self.called_with = None

    def generate_signal_with_context(self, symbol, profile_id, features, market_context, account):
        self.called_with = {
            "symbol": symbol,
            "profile_id": profile_id,
            "features": dict(features),
            "market_context": dict(market_context),
            "account": dict(account),
        }
        return None


@pytest.mark.asyncio
async def test_signal_stage_injects_amt_levels():
    registry = CapturingRegistry()
    stage = SignalStage(registry=registry)

    amt_levels = AMTLevels(
        point_of_control=100.0,
        value_area_high=110.0,
        value_area_low=90.0,
        position_in_value="inside",
        distance_to_poc=1.2,
        distance_to_vah=2.3,
        distance_to_val=3.4,
        distance_to_poc_bps=12.0,
        distance_to_vah_bps=23.0,
        distance_to_val_bps=34.0,
        rotation_factor=0.42,
    )

    ctx = StageContext(
        symbol="BTCUSDT",
        profile_id="test_profile",
        data={
            "features": {
                "rotation_factor": 0.0,
                "distance_to_poc_bps": 1.0,
            },
            "market_context": {
                "rotation_factor": 0.0,
                "distance_to_poc_bps": 1.0,
            },
            "account": {},
            "amt_levels": amt_levels,
        },
    )

    await stage.run(ctx)

    assert registry.called_with is not None
    features = registry.called_with["features"]
    market_context = registry.called_with["market_context"]

    assert features["rotation_factor"] == amt_levels.rotation_factor
    assert market_context["rotation_factor"] == amt_levels.rotation_factor
    assert features["point_of_control"] == amt_levels.point_of_control
    assert market_context["point_of_control"] == amt_levels.point_of_control
    assert features["value_area_high"] == amt_levels.value_area_high
    assert market_context["value_area_high"] == amt_levels.value_area_high
    assert features["value_area_low"] == amt_levels.value_area_low
    assert market_context["value_area_low"] == amt_levels.value_area_low
    assert features["position_in_value"] == amt_levels.position_in_value
    assert market_context["position_in_value"] == amt_levels.position_in_value
    assert features["distance_to_poc"] == amt_levels.distance_to_poc
    assert market_context["distance_to_poc"] == amt_levels.distance_to_poc
    assert features["distance_to_vah"] == amt_levels.distance_to_vah
    assert market_context["distance_to_vah"] == amt_levels.distance_to_vah
    assert features["distance_to_val"] == amt_levels.distance_to_val
    assert market_context["distance_to_val"] == amt_levels.distance_to_val
    assert features["distance_to_poc_bps"] == amt_levels.distance_to_poc_bps
    assert market_context["distance_to_poc_bps"] == amt_levels.distance_to_poc_bps
    assert features["distance_to_vah_bps"] == amt_levels.distance_to_vah_bps
    assert market_context["distance_to_vah_bps"] == amt_levels.distance_to_vah_bps
    assert features["distance_to_val_bps"] == amt_levels.distance_to_val_bps
    assert market_context["distance_to_val_bps"] == amt_levels.distance_to_val_bps
