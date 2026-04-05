import asyncio
import pytest

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.model_direction_alignment import (
    ModelDirectionAlignmentStage,
    ModelDirectionAlignmentConfig,
)


def _ctx(signal: dict, prediction: dict) -> StageContext:
    payload = dict(prediction)
    payload.setdefault("source", "onnx_v1")
    return StageContext(
        symbol="BTCUSDT",
        data={"prediction": payload, "market_context": {}, "features": {}},
        signal=signal,
    )


def test_model_direction_alignment_blocks_mismatch_when_confident():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.6,
            min_margin_to_enforce=0.05,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open"},
        {"p_long_win": 0.20, "p_short_win": 0.80, "confidence": 0.8, "direction": "down"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "model_direction_mismatch"
    assert ctx.rejection_stage == "model_direction_alignment"
    assert isinstance(ctx.data.get("model_direction_alignment"), dict)
    assert ctx.data["model_direction_alignment"].get("matched") is False


def test_model_direction_alignment_rejects_mismatch_when_low_confidence_by_default():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.8,
            min_margin_to_enforce=0.05,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open"},
        {"p_long_win": 0.45, "p_short_win": 0.55, "confidence": 0.55, "direction": "down"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "model_direction_mismatch"


def test_model_direction_alignment_allows_when_low_confidence_legacy_toggle(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODEL_DIRECTION_ALIGNMENT_UNCONDITIONAL", "false")
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.8,
            min_margin_to_enforce=0.05,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open"},
        {"p_long_win": 0.45, "p_short_win": 0.55, "confidence": 0.55, "direction": "down"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE


def test_model_direction_alignment_allows_aligned_direction():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.55,
            min_margin_to_enforce=0.01,
        )
    )
    ctx = _ctx(
        {"side": "short", "position_effect": "open"},
        {"p_long_win": 0.25, "p_short_win": 0.75, "confidence": 0.75, "direction": "down"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE


def test_model_direction_alignment_skips_non_enforced_sources():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.6,
            min_margin_to_enforce=0.02,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open"},
        {"p_long_win": 0.10, "p_short_win": 0.90, "confidence": 0.9, "direction": "down", "source": "heuristic_v1"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
    detail = ctx.data.get("model_direction_alignment") or {}
    assert detail.get("reason") == "source_not_enforced"


def test_model_direction_alignment_exempts_mean_reversion_from_ctx_strategy():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.6,
            min_margin_to_enforce=0.02,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open"},
        {"p_long_win": 0.10, "p_short_win": 0.90, "confidence": 0.9, "direction": "down"},
    )
    ctx.data["strategy"] = {"strategy_id": "mean_reversion_fade"}
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
    detail = ctx.data.get("model_direction_alignment") or {}
    assert detail.get("reason") == "strategy_exempt"


def test_model_direction_alignment_exempts_mean_reversion_fade():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.6,
            min_margin_to_enforce=0.02,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open", "strategy_id": "mean_reversion_fade"},
        {"p_long_win": 0.10, "p_short_win": 0.90, "confidence": 0.9, "direction": "down"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
    detail = ctx.data.get("model_direction_alignment") or {}
    assert detail.get("reason") == "strategy_exempt"


def test_model_direction_alignment_exempts_vwap_reversion():
    stage = ModelDirectionAlignmentStage(
        config=ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.6,
            min_margin_to_enforce=0.02,
        )
    )
    ctx = _ctx(
        {"side": "long", "position_effect": "open", "strategy_id": "vwap_reversion"},
        {"p_long_win": 0.10, "p_short_win": 0.90, "confidence": 0.9, "direction": "down"},
    )
    result = asyncio.run(stage.run(ctx))
    assert result == StageResult.CONTINUE
    detail = ctx.data.get("model_direction_alignment") or {}
    assert detail.get("reason") == "strategy_exempt"
