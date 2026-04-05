import asyncio

from quantgambit.signals.pipeline import Orchestrator, Stage, StageContext, StageResult
from quantgambit.observability.telemetry import TelemetryContext


class DummyStage(Stage):
    name = "dummy"

    async def run(self, ctx: StageContext) -> StageResult:
        ctx.rejection_reason = "no_signal"
        return StageResult.REJECT


class ConfirmationShadowStage(Stage):
    name = "confirmation"

    async def run(self, ctx: StageContext) -> StageResult:
        ctx.data["confirmation_shadow_comparisons"] = [
            {
                "source_stage": "confirmation",
                "decision_context": "entry_live_signal",
                "mode": "shadow",
                "legacy_decision": True,
                "unified_decision": False,
                "final_decision": True,
                "diff": True,
                "diff_reason": "decision_mismatch",
                "unified_confidence": 0.41,
                "strategy_id": "mean_reversion_fade",
                "side": "long",
            }
        ]
        ctx.rejection_reason = "no_signal"
        return StageResult.REJECT


class FakeTelemetry:
    def __init__(self):
        self.decisions = []
        self.latencies = []

    async def publish_decision(self, ctx, symbol, payload):
        self.decisions.append(payload)

    async def publish_latency(self, ctx, payload):
        self.latencies.append(payload)


class PredictionBlockedStage(Stage):
    name = "prediction_gate"

    async def run(self, ctx: StageContext) -> StageResult:
        ctx.rejection_reason = "prediction_blocked"
        ctx.rejection_detail = {"prediction_blocked_reason": "heuristic_low_net_edge"}
        ctx.data["prediction"] = {
            "source": "heuristic_v2",
            "reject": True,
            "reason": "heuristic_low_net_edge",
            "confidence": 0.52,
            "direction": "up",
        }
        return StageResult.REJECT


def test_pipeline_emits_telemetry():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    orchestrator = Orchestrator([DummyStage()], telemetry=telemetry, telemetry_context=ctx)

    result = asyncio.run(orchestrator.execute(StageContext(symbol="BTC", data={})))
    assert result == StageResult.REJECT
    assert telemetry.decisions
    assert telemetry.latencies


def test_pipeline_emits_confirmation_shadow_summary():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    orchestrator = Orchestrator([ConfirmationShadowStage()], telemetry=telemetry, telemetry_context=ctx)

    result = asyncio.run(orchestrator.execute(StageContext(symbol="BTC", data={})))

    assert result == StageResult.REJECT
    assert telemetry.decisions
    payload = telemetry.decisions[-1]
    assert payload.get("confirmation_shadow_total") == 1
    assert payload.get("confirmation_shadow_mismatches") == 1
    assert payload.get("confirmation_shadow_disagreement_rate") == 1.0


def test_pipeline_surfaces_prediction_block_reason_as_rejection_reason():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    orchestrator = Orchestrator([PredictionBlockedStage()], telemetry=telemetry, telemetry_context=ctx)

    result = asyncio.run(orchestrator.execute(StageContext(symbol="BTC", data={})))
    assert result == StageResult.REJECT
    payload = telemetry.decisions[-1]
    assert payload.get("rejection_reason") == "heuristic_low_net_edge"
    assert payload.get("rejection_reason_base") == "prediction_blocked"
    assert payload.get("prediction_blocked_reason") == "heuristic_low_net_edge"
