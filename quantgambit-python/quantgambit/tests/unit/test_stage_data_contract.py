import asyncio

from quantgambit.signals.pipeline import Orchestrator, Stage, StageContext, StageResult


class PassSignalStage(Stage):
    name = "signal_check"

    async def run(self, ctx: StageContext) -> StageResult:
        ctx.signal = {"side": "long", "strategy_id": "unit_test"}
        return StageResult.CONTINUE


class BadProfileRoutingStage(Stage):
    name = "profile_routing"

    async def run(self, ctx: StageContext) -> StageResult:
        # Intentionally do not set ctx.profile_id to trigger post-condition failure.
        return StageResult.CONTINUE


def test_stage_data_contract_non_strict_allows_and_records_warning(monkeypatch):
    monkeypatch.setenv("PIPELINE_STAGE_DATA_VALIDATION", "true")
    monkeypatch.setenv("PIPELINE_STAGE_DATA_VALIDATION_STRICT", "false")
    orchestrator = Orchestrator(stages=[PassSignalStage()], validate_ordering=False)
    ctx = StageContext(symbol="ETHUSDT", data={"market_context": {}}, profile_id="p1")

    result = asyncio.run(orchestrator.execute(ctx))

    assert result == StageResult.COMPLETE
    assert isinstance(ctx.stage_trace, list)
    assert ctx.stage_trace[0]["stage"] == "signal_check"
    assert "contract_warnings_pre" in ctx.stage_trace[0]


def test_stage_data_contract_strict_rejects_missing_pre_data(monkeypatch):
    monkeypatch.setenv("PIPELINE_STAGE_DATA_VALIDATION", "true")
    monkeypatch.setenv("PIPELINE_STAGE_DATA_VALIDATION_STRICT", "true")
    orchestrator = Orchestrator(stages=[PassSignalStage()], validate_ordering=False)
    ctx = StageContext(symbol="ETHUSDT", data={"market_context": {}}, profile_id="p1")

    result = asyncio.run(orchestrator.execute(ctx))

    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "stage_data_contract_violation"
    assert ctx.rejection_stage == "signal_check"
    assert isinstance(ctx.rejection_detail, dict)
    assert ctx.rejection_detail.get("phase") == "pre"


def test_stage_data_contract_strict_rejects_missing_post_data(monkeypatch):
    monkeypatch.setenv("PIPELINE_STAGE_DATA_VALIDATION", "true")
    monkeypatch.setenv("PIPELINE_STAGE_DATA_VALIDATION_STRICT", "true")
    orchestrator = Orchestrator(stages=[BadProfileRoutingStage()], validate_ordering=False)
    ctx = StageContext(symbol="ETHUSDT", data={"market_context": {"price": 100.0}}, profile_id=None)

    result = asyncio.run(orchestrator.execute(ctx))

    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "stage_data_contract_violation"
    assert ctx.rejection_stage == "profile_routing"
    assert isinstance(ctx.rejection_detail, dict)
    assert ctx.rejection_detail.get("phase") == "post"
