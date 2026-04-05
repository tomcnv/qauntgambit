from quantgambit.signals.input_builder import build_stage_inputs


def test_build_stage_inputs_adds_price_and_spread():
    inputs = build_stage_inputs(
        "BTC",
        market_context={"bid": 99.0, "ask": 101.0, "timestamp": 10.0},
        features={},
    )
    assert inputs.is_valid
    assert inputs.market_context["price"] == 100.0
    assert inputs.features["price"] == 100.0
    assert "spread" in inputs.market_context
    assert "spread_bps" in inputs.market_context


def test_build_stage_inputs_requires_price():
    inputs = build_stage_inputs("BTC", market_context={}, features={})
    assert not inputs.is_valid
    assert inputs.errors == ["missing_price", "missing_timestamp"]


def test_build_stage_inputs_rejects_invalid_price():
    inputs = build_stage_inputs("BTC", market_context={"price": "nope"}, features={})
    assert not inputs.is_valid
    assert "invalid_price" in inputs.errors
    assert "missing_timestamp" in inputs.errors
