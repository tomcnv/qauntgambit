"""
ModelDirectionAlignmentStage - Enforce signal/model side agreement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING, Dict, Any

from quantgambit.ingest.schemas import coerce_float
from quantgambit.observability.logger import log_info
from quantgambit.signals.pipeline import Stage, StageContext, StageResult, signal_to_dict

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


def _to_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ModelDirectionAlignmentConfig:
    enabled: bool = True
    min_confidence_to_enforce: float = 0.60
    min_margin_to_enforce: float = 0.02
    allow_when_prediction_missing: bool = True
    enforce_sources: tuple[str, ...] = ("onnx",)


class ModelDirectionAlignmentStage(Stage):
    name = "model_direction_alignment"
    _STRATEGY_EXEMPTIONS = {"mean_reversion_fade", "vwap_reversion"}

    def __init__(
        self,
        config: Optional[ModelDirectionAlignmentConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        cfg = config or ModelDirectionAlignmentConfig()
        self.config = ModelDirectionAlignmentConfig(
            enabled=_to_bool(os.getenv("MODEL_DIRECTION_ALIGNMENT_ENABLED"), cfg.enabled),
            min_confidence_to_enforce=float(
                os.getenv("MODEL_DIRECTION_ALIGNMENT_MIN_CONFIDENCE", str(cfg.min_confidence_to_enforce))
            ),
            min_margin_to_enforce=float(
                os.getenv("MODEL_DIRECTION_ALIGNMENT_MIN_MARGIN", str(cfg.min_margin_to_enforce))
            ),
            allow_when_prediction_missing=_to_bool(
                os.getenv("MODEL_DIRECTION_ALIGNMENT_ALLOW_MISSING_PREDICTION"),
                cfg.allow_when_prediction_missing,
            ),
            enforce_sources=tuple(
                token.strip().lower()
                for token in str(
                    os.getenv(
                        "MODEL_DIRECTION_ALIGNMENT_ENFORCE_SOURCES",
                        ",".join(cfg.enforce_sources),
                    )
                ).split(",")
                if token.strip()
            ) or cfg.enforce_sources,
        )
        self.telemetry = telemetry

    async def run(self, ctx: StageContext) -> StageResult:
        if not self.config.enabled:
            return StageResult.CONTINUE

        signal = signal_to_dict(ctx.signal)
        if not signal:
            return StageResult.CONTINUE
        if str(signal.get("position_effect") or "").lower() == "close":
            return StageResult.CONTINUE

        signal_side = self._normalize_side(signal.get("side"))
        if not signal_side:
            return StageResult.CONTINUE
        strategy_id = str(
            signal.get("strategy_id")
            or signal.get("strategy")
            or getattr(ctx.signal, "strategy_id", "")
            or (ctx.data.get("strategy") or {}).get("strategy_id")
            or ""
        ).strip().lower()

        prediction = ctx.data.get("prediction") or {}
        alignment_detail: Dict[str, Any] = {
            "enabled": True,
            "signal_side": signal_side,
            "model_side": None,
            "confidence": None,
            "margin": None,
            "enforced": False,
            "matched": None,
            "reason": None,
            "strategy_id": strategy_id or None,
        }
        if strategy_id in self._STRATEGY_EXEMPTIONS:
            alignment_detail["reason"] = "strategy_exempt"
            ctx.data["model_direction_alignment"] = alignment_detail
            return StageResult.CONTINUE
        if not isinstance(prediction, dict) or not prediction:
            alignment_detail["reason"] = "missing_prediction"
            ctx.data["model_direction_alignment"] = alignment_detail
            if self.config.allow_when_prediction_missing:
                return StageResult.CONTINUE
            return await self._reject(ctx, signal_side, None, reason="missing_prediction")

        model_side, confidence, margin = self._extract_prediction_side(prediction)
        prediction_source = str(prediction.get("source") or "").strip().lower()
        alignment_detail["model_side"] = model_side
        alignment_detail["confidence"] = confidence
        alignment_detail["margin"] = margin
        alignment_detail["prediction_source"] = prediction_source

        if self.config.enforce_sources and prediction_source:
            source_match = any(token in prediction_source for token in self.config.enforce_sources)
            if not source_match:
                alignment_detail["reason"] = "source_not_enforced"
                ctx.data["model_direction_alignment"] = alignment_detail
                return StageResult.CONTINUE

        if model_side is None:
            alignment_detail["reason"] = "missing_model_side"
            ctx.data["model_direction_alignment"] = alignment_detail
            if self.config.allow_when_prediction_missing:
                return StageResult.CONTINUE
            return await self._reject(ctx, signal_side, None, reason="missing_model_side")

        unconditional = _to_bool(
            os.getenv("MODEL_DIRECTION_ALIGNMENT_UNCONDITIONAL"),
            True,
        )
        if not unconditional:
            if confidence < self.config.min_confidence_to_enforce:
                alignment_detail["reason"] = "confidence_below_threshold"
                ctx.data["model_direction_alignment"] = alignment_detail
                return StageResult.CONTINUE
            if margin < self.config.min_margin_to_enforce:
                alignment_detail["reason"] = "margin_below_threshold"
                ctx.data["model_direction_alignment"] = alignment_detail
                return StageResult.CONTINUE

        alignment_detail["enforced"] = True
        alignment_detail["matched"] = bool(model_side == signal_side)
        if model_side != signal_side:
            alignment_detail["reason"] = "model_direction_mismatch"
            ctx.data["model_direction_alignment"] = alignment_detail
            return await self._reject(
                ctx,
                signal_side,
                model_side,
                reason="model_direction_mismatch",
                confidence=confidence,
                margin=margin,
            )
        alignment_detail["reason"] = "aligned"
        ctx.data["model_direction_alignment"] = alignment_detail
        return StageResult.CONTINUE

    def _extract_prediction_side(self, prediction: Dict[str, Any]) -> tuple[Optional[str], float, float]:
        p_long = coerce_float(prediction.get("p_long_win"))
        p_short = coerce_float(prediction.get("p_short_win"))
        if p_long is None or p_short is None:
            probs = prediction.get("probs") if isinstance(prediction.get("probs"), dict) else {}
            p_long = coerce_float(p_long if p_long is not None else probs.get("p_long_win"))
            p_short = coerce_float(p_short if p_short is not None else probs.get("p_short_win"))
        if p_long is not None and p_short is not None:
            side = "long" if p_long >= p_short else "short"
            confidence = max(float(p_long), float(p_short))
            margin = abs(float(p_long) - float(p_short))
            return side, confidence, margin

        direction = str(prediction.get("direction") or "").strip().lower()
        side = self._normalize_side(direction)
        confidence = coerce_float(prediction.get("confidence")) or 0.0
        margin = abs(
            (coerce_float(prediction.get("p_up")) or confidence)
            - (coerce_float(prediction.get("p_down")) or 0.0)
        )
        return side, float(confidence), float(margin)

    def _normalize_side(self, value: Optional[str]) -> Optional[str]:
        side = str(value or "").strip().lower()
        if side in {"long", "buy", "up"}:
            return "long"
        if side in {"short", "sell", "down"}:
            return "short"
        return None

    async def _reject(
        self,
        ctx: StageContext,
        signal_side: str,
        model_side: Optional[str],
        *,
        reason: str,
        confidence: Optional[float] = None,
        margin: Optional[float] = None,
    ) -> StageResult:
        ctx.rejection_reason = reason
        ctx.rejection_stage = self.name
        ctx.rejection_detail = {
            "signal_side": signal_side,
            "model_side": model_side,
            "confidence": confidence,
            "margin": margin,
            "min_confidence_to_enforce": self.config.min_confidence_to_enforce,
            "min_margin_to_enforce": self.config.min_margin_to_enforce,
        }
        if self.telemetry:
            await self.telemetry.record_blocked(
                symbol=ctx.symbol,
                gate_name="strategy_trend_mismatch",
                reason=reason,
                metrics=dict(ctx.rejection_detail),
            )
        log_info("model_direction_alignment_reject", symbol=ctx.symbol, **ctx.rejection_detail)
        return StageResult.REJECT
