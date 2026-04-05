import asyncio

from quantgambit.signals.pipeline import (
    PredictionStage,
    StageContext,
    StageResult,
    _parse_symbol_float_map,
)


def test_prediction_stage_rejects_low_confidence():
    stage = PredictionStage(min_confidence=0.6)
    ctx = StageContext(symbol="BTC", data={"prediction": {"confidence": 0.4}})
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "prediction_low_confidence"


def test_prediction_stage_allows_when_missing():
    stage = PredictionStage(min_confidence=0.9)
    ctx = StageContext(symbol="BTC", data={})
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE


def test_prediction_stage_rejects_when_missing_and_required(monkeypatch):
    monkeypatch.setenv("PREDICTION_REQUIRE_PRESENT", "true")
    stage = PredictionStage(min_confidence=0.0)
    ctx = StageContext(symbol="BTCUSDT", data={}, signal={"side": "long", "position_effect": "open"})
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "prediction_missing"
    assert ctx.rejection_stage == "prediction_gate"


def test_prediction_stage_uses_specific_block_reason_when_prediction_missing(monkeypatch):
    monkeypatch.setenv("PREDICTION_REQUIRE_PRESENT", "true")
    stage = PredictionStage(min_confidence=0.0)
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "prediction_status": {"status": "suppressed", "reason": "score_status_blocked"},
            "market_context": {"prediction_blocked": "score_status_blocked"},
        },
        signal={"side": "long", "position_effect": "open"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "prediction_blocked"
    assert ctx.rejection_stage == "prediction_gate"
    assert isinstance(ctx.rejection_detail, dict)
    assert ctx.rejection_detail.get("prediction_blocked_reason") == "score_status_blocked"


def test_prediction_stage_applies_symbol_specific_min_confidence():
    stage = PredictionStage(
        min_confidence=0.2,
        min_confidence_by_symbol={"SOLUSDT": 0.15},
    )
    ctx = StageContext(symbol="SOLUSDT", data={"prediction": {"confidence": 0.16}})
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE


def test_parse_symbol_float_map_supports_commas_and_semicolons():
    parsed = _parse_symbol_float_map("SOLUSDT:0.16;ETHUSDT:0.2,BTCUSDT:1.5")
    assert parsed["SOLUSDT"] == 0.16
    assert parsed["ETHUSDT"] == 0.2
    assert parsed["BTCUSDT"] == 1.0


def test_prediction_stage_persists_reason_when_reject_reason_missing():
    stage = PredictionStage(min_confidence=0.0)
    ctx = StageContext(symbol="ETHUSDT", data={"prediction": {"reject": True}})
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "prediction_blocked"
    assert isinstance(ctx.rejection_detail, dict)
    assert ctx.rejection_detail.get("prediction_blocked_reason") == "prediction_reject_unspecified"
    prediction_detail = ctx.rejection_detail.get("prediction")
    assert isinstance(prediction_detail, dict)
    assert prediction_detail.get("reason") == "prediction_reject_unspecified"


def test_prediction_stage_rejects_low_directional_accuracy_from_score_metrics():
    stage = PredictionStage(min_confidence=0.0)
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {
                "source": "onnx_v1",
                "direction": "up",
                "confidence": 0.9,
            },
            "market_context": {
                "prediction_score_gate_metrics": {
                    "directional_accuracy": 0.42,
                    "ece_top1": 0.08,
                }
            },
        },
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "prediction_low_directional_accuracy"


def test_prediction_stage_allows_onnx_when_score_metrics_missing_and_fail_open():
    stage = PredictionStage(min_confidence=0.0)
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {
                "source": "onnx_v1",
                "direction": "up",
                "confidence": 0.7,
            },
            "market_context": {},
        },
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
