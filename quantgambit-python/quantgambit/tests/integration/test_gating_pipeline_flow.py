"""
Integration tests for pre-trade gating pipeline flow.

Tests the full decision pipeline with the new gating stages:
- Full pipeline execution from input to decision
- Layer A (global gates) → Layer B (candidate veto) flow
- Exit classification and handling
- Telemetry emission
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from quantgambit.config.loss_prevention import load_loss_prevention_config
from quantgambit.signals.pipeline import (
    Stage,
    StageContext,
    StageResult,
    Orchestrator,
    ProfileRoutingStage,
    SignalStage,
    RiskStage,
    PredictionStage,
    PositionEvaluationStage,
    ExecutionStage,
)
from quantgambit.signals.stages import (
    DataReadinessStage,
    SnapshotBuilderStage,
    GlobalGateStage,
    CandidateGenerationStage,
    CandidateVetoStage,
    CooldownStage,
)
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.signals.stages.candidate_veto import CandidateVetoConfig
from quantgambit.signals.stages.cooldown import CooldownConfig, CooldownManager
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.deeptrader_core.types import ExitType


class RecordingStage(Stage):
    def __init__(self, name: str, result: StageResult = StageResult.CONTINUE):
        self.name = name
        self.result = result
        self.calls = 0

    async def run(self, ctx: StageContext) -> StageResult:
        self.calls += 1
        return self.result


def make_full_data(
    price=50000.0,
    spread_bps=4.0,
    orderflow_imbalance=0.0,
    trend_direction="neutral",
    trend_strength=0.1,
    volatility_regime="normal",
    timestamp=None,
):
    """Create full data dict for pipeline context."""
    ts = timestamp or time.time()
    
    features = {
        "symbol": "BTCUSDT",
        "price": price,
        "bid": price - 0.5,
        "ask": price + 0.5,
        "spread": 1.0 / price,
        "spread_bps": spread_bps,
        "bid_depth_usd": 100000.0,
        "ask_depth_usd": 100000.0,
        "orderbook_imbalance": 0.0,
        "orderflow_imbalance": orderflow_imbalance,
        "timestamp": ts,
        "rotation_factor": 0.5,
        "position_in_value": "inside",
        "distance_to_val": 100.0,
        "distance_to_vah": 100.0,
        "distance_to_poc": 50.0,
        "point_of_control": price - 50,
        "value_area_low": price - 200,
        "value_area_high": price + 100,
        "ema_fast_15m": price,
        "ema_slow_15m": price - 50,
        "trend_strength": trend_strength,
        "atr_5m": 50.0,
        "atr_5m_baseline": 45.0,
        "atr_ratio": 1.1,
        "vwap": price - 20,
        "trades_per_second": 10.0,
        "price_change_1s": 0.0001,
        "price_change_5s": 0.0003,
        "price_change_30s": 0.001,
        "price_change_1m": 0.002,
        "price_change_5m": 0.005,
        "imb_1s": orderflow_imbalance,
        "imb_5s": orderflow_imbalance,
        "imb_30s": orderflow_imbalance,
        "orderflow_persistence_sec": 5.0,
    }
    
    market_context = {
        "symbol": "BTCUSDT",
        "price": price,
        "spread_bps": spread_bps,
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
        "volatility_regime": volatility_regime,
        "orderflow_imbalance": orderflow_imbalance,
        "imb_1s": orderflow_imbalance,
        "imb_5s": orderflow_imbalance,
        "imb_30s": orderflow_imbalance,
        "data_quality_score": 0.95,
        "data_quality_status": "synced",
        "trade_sync_state": "synced",
        "orderbook_sync_state": "synced",
        "timestamp": ts,
        "position_in_value": "inside",
        "point_of_control": price - 50,
        "value_area_low": price - 200,
        "value_area_high": price + 100,
    }
    
    return {
        "features": features,
        "market_context": market_context,
        "account": {"equity": 10000.0},
        "positions": [],
        "risk_limits": {"max_position_usd": 5000.0},
    }


class FakeRouter:
    """Fake profile router for testing."""
    require_profile = True
    last_scores = None
    
    def route(self, market_context):
        return "test_profile"
    
    def route_with_context(self, symbol, market_context, features):
        return "test_profile"
    
    def set_policy(self, policy):
        pass


class FakeRegistry:
    """Fake strategy registry for testing."""
    
    def generate_signal(self, profile_id, features):
        return {
            "signal": True,
            "side": "long",
            "entry_price": features.get("price", 50000.0),
            "stop_loss": features.get("price", 50000.0) * 0.99,
            "take_profit": features.get("price", 50000.0) * 1.02,
            "strategy_id": "test_strategy",
            "meta_reason": "test signal",
            "confidence": 0.7,
        }
    
    def generate_signal_with_context(self, symbol, profile_id, features, market_context, account):
        return self.generate_signal(profile_id, features)


class FakeRiskValidator:
    """Fake risk validator for testing."""
    last_rejection_reason = None
    
    def allow(self, signal, context=None):
        return True


class TestLayerAGlobalGates:
    """Tests for Layer A (global gates) execution."""
    
    def test_data_readiness_blocks_bad_data(self):
        """Layer A should block when data is not ready."""
        stages = [
            DataReadinessStage(config=DataReadinessConfig(min_bid_depth_usd=200000.0)),
            SnapshotBuilderStage(),
            GlobalGateStage(),
        ]
        orchestrator = Orchestrator(stages=stages)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data=make_full_data(),  # Default depth is 100k, below 200k threshold
        )
        
        result = asyncio.run(orchestrator.execute(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_stage == "data_readiness"
    
    def test_global_gate_blocks_vol_shock(self):
        """Layer A should block during vol shock."""
        stages = [
            DataReadinessStage(),
            SnapshotBuilderStage(),
            GlobalGateStage(config=GlobalGateConfig(block_on_vol_shock=True)),
        ]
        orchestrator = Orchestrator(stages=stages)
        
        # Create data and manually inject vol_shock into snapshot
        data = make_full_data()
        ctx = StageContext(symbol="BTCUSDT", data=data)
        
        # Run first two stages
        asyncio.run(stages[0].run(ctx))
        asyncio.run(stages[1].run(ctx))
        
        # Modify snapshot to have vol_shock
        from dataclasses import replace
        ctx.data["snapshot"] = replace(ctx.data["snapshot"], vol_shock=True)
        
        # Run global gate
        result = asyncio.run(stages[2].run(ctx))
        
        assert result == StageResult.REJECT
        assert "vol_shock" in ctx.rejection_reason


class TestLayerBCandidatePipeline:
    """Tests for Layer B (candidate pipeline) execution."""
    
    def test_candidate_veto_blocks_adverse_orderflow(self):
        """Layer B should block when orderflow is adverse to trade direction."""
        cooldown_manager = CooldownManager()
        
        stages = [
            DataReadinessStage(),
            SnapshotBuilderStage(),
            GlobalGateStage(),
            ProfileRoutingStage(FakeRouter()),
            PositionEvaluationStage(),
            CooldownStage(manager=cooldown_manager),
            PredictionStage(),
            SignalStage(FakeRegistry()),
            CandidateGenerationStage(strategy_registry=FakeRegistry()),
            CandidateVetoStage(config=CandidateVetoConfig(orderflow_veto_base=0.5)),
            RiskStage(FakeRiskValidator()),
            ExecutionStage(),
        ]
        orchestrator = Orchestrator(stages=stages)
        
        # Strong negative orderflow should block long
        data = make_full_data(orderflow_imbalance=-0.7)
        ctx = StageContext(symbol="BTCUSDT", data=data)
        
        result = asyncio.run(orchestrator.execute(ctx))
        
        assert result == StageResult.REJECT
        assert ctx.rejection_stage == "candidate_veto"
        assert "orderflow_veto" in ctx.rejection_reason
    
    def test_candidate_veto_blocks_regime_mismatch(self, monkeypatch):
        """Layer B should block mean reversion in strong trend."""
        # Ensure this test is isolated from env-driven strategy disables used in live trading.
        monkeypatch.setenv("DISABLE_STRATEGIES", "")
        monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "")
        cooldown_manager = CooldownManager()
        
        # Registry that returns mean reversion strategy
        class MeanReversionRegistry(FakeRegistry):
            def generate_signal(self, profile_id, features):
                signal = super().generate_signal(profile_id, features)
                signal["strategy_id"] = "mean_reversion_fade"
                return signal
        
        stages = [
            DataReadinessStage(),
            SnapshotBuilderStage(),
            GlobalGateStage(),
            ProfileRoutingStage(FakeRouter()),
            PositionEvaluationStage(),
            CooldownStage(manager=cooldown_manager),
            PredictionStage(),
            SignalStage(MeanReversionRegistry()),
            CandidateGenerationStage(strategy_registry=MeanReversionRegistry()),
            CandidateVetoStage(),
            RiskStage(FakeRiskValidator()),
            ExecutionStage(),
        ]
        orchestrator = Orchestrator(stages=stages)
        
        # Strong uptrend should block mean reversion
        data = make_full_data(trend_direction="up", trend_strength=0.8)
        ctx = StageContext(symbol="BTCUSDT", data=data)
        
        result = asyncio.run(orchestrator.execute(ctx))
        
        assert result == StageResult.REJECT
        assert "regime_veto" in ctx.rejection_reason


class TestFullPipelineFlow:
    """Tests for complete pipeline execution."""
    
    def test_successful_signal_generation(self):
        """Full pipeline should produce signal with good conditions."""
        cooldown_manager = CooldownManager()
        
        stages = [
            DataReadinessStage(),
            SnapshotBuilderStage(),
            GlobalGateStage(),
            ProfileRoutingStage(FakeRouter()),
            PositionEvaluationStage(),
            CooldownStage(manager=cooldown_manager),
            PredictionStage(),
            SignalStage(FakeRegistry()),
            CandidateGenerationStage(strategy_registry=FakeRegistry()),
            CandidateVetoStage(config=CandidateVetoConfig(min_net_edge_bps=0.0)),  # Disable edge check
            RiskStage(FakeRiskValidator()),
            ExecutionStage(),
        ]
        orchestrator = Orchestrator(stages=stages)
        
        # Good conditions
        data = make_full_data(orderflow_imbalance=0.2, trend_strength=0.1)
        ctx = StageContext(symbol="BTCUSDT", data=data)
        
        result = asyncio.run(orchestrator.execute(ctx))
        
        assert result == StageResult.COMPLETE
        assert ctx.signal is not None
        assert "candidate" in ctx.data
    
    def test_pipeline_tracks_gate_decisions(self):
        """Pipeline should collect gate decisions for telemetry."""
        cooldown_manager = CooldownManager()
        
        stages = [
            DataReadinessStage(),
            SnapshotBuilderStage(),
            GlobalGateStage(),
            ProfileRoutingStage(FakeRouter()),
            PositionEvaluationStage(),
            CooldownStage(manager=cooldown_manager),
            PredictionStage(),
            SignalStage(FakeRegistry()),
            CandidateGenerationStage(strategy_registry=FakeRegistry()),
            CandidateVetoStage(config=CandidateVetoConfig(min_net_edge_bps=0.0)),
            RiskStage(FakeRiskValidator()),
            ExecutionStage(),
        ]
        orchestrator = Orchestrator(stages=stages)
        
        data = make_full_data(orderflow_imbalance=0.2)
        ctx = StageContext(symbol="BTCUSDT", data=data)
        
        result = asyncio.run(orchestrator.execute(ctx))
        
        # Should have gate decisions recorded
        gate_decisions = ctx.data.get("gate_decisions", [])
        assert len(gate_decisions) > 0
        
        # First should be data_readiness
        assert gate_decisions[0].gate_name == "data_readiness"
        assert gate_decisions[0].allowed is True

    def test_risk_stage_rejects_same_symbol_when_position_already_open(self, monkeypatch):
        """Risk stage should reject duplicate same-symbol entries when blocking is enabled."""
        monkeypatch.setenv("BLOCK_IF_POSITION_EXISTS", "true")
        monkeypatch.setenv("MAX_POSITIONS_PER_SYMBOL", "1")
        cooldown_manager = CooldownManager()

        stages = [
            DataReadinessStage(),
            SnapshotBuilderStage(),
            GlobalGateStage(),
            ProfileRoutingStage(FakeRouter()),
            PositionEvaluationStage(),
            CooldownStage(manager=cooldown_manager),
            PredictionStage(),
            SignalStage(FakeRegistry()),
            CandidateGenerationStage(strategy_registry=FakeRegistry()),
            CandidateVetoStage(config=CandidateVetoConfig(min_net_edge_bps=0.0)),
            RiskStage(FakeRiskValidator()),
            ExecutionStage(),
        ]
        orchestrator = Orchestrator(stages=stages)

        data = make_full_data(orderflow_imbalance=0.2, trend_strength=0.1)
        data["positions"] = [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "size": 0.1,
                "entry_price": 50000.0,
                "opened_at": time.time() - 30,
            }
        ]
        data["risk_limits"]["max_positions_per_symbol"] = 1
        ctx = StageContext(symbol="BTCUSDT", data=data)

        result = asyncio.run(orchestrator.execute(ctx))

        assert result == StageResult.REJECT
        assert ctx.rejection_stage == "risk_check"
        assert ctx.rejection_reason == "position_exists"


class TestExitSignalHandling:
    """Tests for exit signal handling through pipeline."""
    
    def test_safety_exit_bypasses_min_hold(self):
        """Safety exits should bypass min_hold time."""
        stage = PositionEvaluationStage(
            min_hold_time_sec=60.0,  # 60 second min hold
            hard_stop_pct=2.0,
        )
        
        # Create position that just opened but is at hard stop
        position = {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 50000.0,
            "size": 0.1,
            "opened_at": time.time(),  # Just opened
            "stop_loss": 49000.0,
        }
        
        # Price is at hard stop (-2.5%)
        market_context = {
            "price": 48750.0,  # -2.5% from entry
            "trend_direction": "down",
            "trend_confidence": 0.8,
            "orderflow_imbalance": -0.5,
            "volatility_regime": "normal",
            "data_quality_status": "synced",
            "trade_sync_state": "synced",
        }
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "positions": [position],
                "market_context": market_context,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should generate exit signal despite min_hold not met
        assert result == StageResult.SKIP_TO_EXECUTION
        assert ctx.signal is not None
        assert ctx.signal.get("exit_type") == "safety"
    
    def test_invalidation_exit_respects_min_hold(self):
        """Invalidation exits should respect min_hold time."""
        stage = PositionEvaluationStage(
            min_hold_time_sec=60.0,  # 60 second min hold
            min_confirmations_for_exit=2,
        )
        
        # Create position that just opened
        position = {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 50000.0,
            "size": 0.1,
            "opened_at": time.time(),  # Just opened
        }
        
        # Conditions that would trigger invalidation exit
        market_context = {
            "price": 49900.0,  # -0.2% (not at hard stop)
            "trend_direction": "down",
            "trend_bias": "short",
            "trend_confidence": 0.5,
            "orderflow_imbalance": -0.7,  # Would trigger orderflow exit
            "volatility_regime": "normal",
            "data_quality_status": "synced",
            "trade_sync_state": "synced",
        }
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "positions": [position],
                "market_context": market_context,
            },
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should NOT generate exit signal because min_hold not met
        assert result == StageResult.CONTINUE
        assert ctx.signal is None


class TestDecisionEngineIntegration:
    """Tests for DecisionEngine with new gating system."""
    
    def test_decision_engine_uses_gating_system(self):
        """DecisionEngine should use new gating stages by default."""
        loss_prevention_config = load_loss_prevention_config()
        engine = DecisionEngine(
            use_gating_system=True,
            ev_gate_config=loss_prevention_config.ev_gate,
            ev_position_sizer_config=loss_prevention_config.ev_position_sizer,
            cost_data_quality_config=loss_prevention_config.cost_data_quality,
        )
        
        # Check that gating stages are present
        stage_names = [s.name for s in engine.orchestrator.stages]
        
        assert "data_readiness" in stage_names
        assert "snapshot_builder" in stage_names
        assert "global_gate" in stage_names
        assert "candidate_generation" in stage_names
        assert "candidate_veto" in stage_names
        assert "cooldown" in stage_names
    
    def test_decision_engine_legacy_mode(self):
        """DecisionEngine should support legacy mode."""
        engine = DecisionEngine(use_gating_system=False)
        
        # Check that new gating stages are NOT present
        stage_names = [s.name for s in engine.orchestrator.stages]
        
        assert "snapshot_builder" not in stage_names
        assert "global_gate" not in stage_names
        assert "candidate_veto" not in stage_names


def test_orchestrator_skips_entry_generation_when_same_symbol_position_is_open(monkeypatch):
    monkeypatch.setenv("BLOCK_IF_POSITION_EXISTS", "true")
    monkeypatch.setenv("ALLOW_POSITION_REPLACEMENT", "false")

    position_eval = PositionEvaluationStage()
    profile_stage = RecordingStage("profile_routing")
    signal_stage = RecordingStage("signal_generation")
    risk_stage = RecordingStage("risk_check")
    execution_stage = RecordingStage("execution")

    orchestrator = Orchestrator(
        [position_eval, profile_stage, signal_stage, risk_stage, execution_stage],
        validate_ordering=False,
    )
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            **make_full_data(),
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 0.1,
                    "entry_price": 50000.0,
                    "opened_at": time.time() - 60,
                }
            ],
            "risk_limits": {"max_positions_per_symbol": 1},
        },
    )

    result = asyncio.run(orchestrator.execute(ctx))

    assert result == StageResult.REJECT
    assert ctx.rejection_reason == "position_exists"
    assert profile_stage.calls == 0
    assert signal_stage.calls == 0
    assert risk_stage.calls == 0
    assert execution_stage.calls == 0
