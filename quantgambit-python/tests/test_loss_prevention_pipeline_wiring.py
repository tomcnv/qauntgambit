"""
Tests for loss prevention pipeline wiring.

Verifies that the loss prevention stages are correctly wired into the
decision engine pipeline in the correct order.
"""

import pytest
import asyncio
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput
from quantgambit.signals.stages.confidence_gate import ConfidenceGateConfig
from quantgambit.signals.stages.strategy_trend_alignment import StrategyTrendAlignmentConfig
from quantgambit.signals.stages.fee_aware_entry import FeeAwareEntryConfig
from quantgambit.signals.stages.session_filter import SessionFilterConfig
from quantgambit.signals.stages.confidence_position_sizer import ConfidencePositionSizerConfig
from quantgambit.signals.stages.ev_gate import EVGateConfig
from quantgambit.config.loss_prevention import load_loss_prevention_config, LossPreventionConfigManager

pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:ConfidenceGateStage is deprecated.*:DeprecationWarning"
    ),
    pytest.mark.filterwarnings(
        "ignore:FeeAwareEntryStage is deprecated.*:DeprecationWarning"
    ),
    pytest.mark.filterwarnings(
        "ignore:ConfidencePositionSizerStage is deprecated.*:DeprecationWarning"
    ),
]


class TestLossPreventionPipelineWiring:
    """Tests for loss prevention pipeline wiring."""

    @staticmethod
    def _ev_kwargs():
        config = load_loss_prevention_config()
        return {
            "ev_gate_config": config.ev_gate,
            "ev_position_sizer_config": config.ev_position_sizer,
        }
    
    def test_decision_engine_includes_loss_prevention_stages(self):
        """Legacy non-gating mode should stay on the minimal pipeline."""
        engine = DecisionEngine(
            strategy_trend_alignment_config=StrategyTrendAlignmentConfig(),
            session_filter_config=SessionFilterConfig(),
            use_gating_system=False,
        )
        
        # Get stage names from orchestrator
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        assert stage_names == [
            "data_readiness",
            "profile_routing",
            "position_evaluation",
            "prediction_gate",
            "signal_check",
            "risk_check",
            "execution",
        ]
    
    def test_decision_engine_uses_ev_gate_when_configured(self):
        """DecisionEngine should use EVGateStage when ev_gate_config is provided."""
        engine = DecisionEngine(
            ev_gate_config=EVGateConfig(mode="shadow", ev_min=0.02),
            strategy_trend_alignment_config=StrategyTrendAlignmentConfig(),
            session_filter_config=SessionFilterConfig(),
            ev_position_sizer_config=load_loss_prevention_config().ev_position_sizer,
            use_gating_system=True,
        )
        
        # Get stage names from orchestrator
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        # Verify EVGateStage is present instead of ConfidenceGateStage
        assert "ev_gate" in stage_names
        assert "confidence_gate" not in stage_names
        assert "fee_aware_entry" not in stage_names
        assert "ev_position_sizer" in stage_names
        assert "confidence_position_sizer" not in stage_names
    
    def test_stage_ordering_entry_gate_after_signal(self):
        """Entry gate (EV or confidence) should run after signal generation.
        
        This is because the EV gate needs the signal's stop_loss and take_profit
        to calculate the reward-to-risk ratio (R).
        """
        engine = DecisionEngine(
            ev_gate_config=EVGateConfig(mode="shadow"),
            ev_position_sizer_config=load_loss_prevention_config().ev_position_sizer,
            use_gating_system=True,
        )
        
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        ev_gate_idx = stage_names.index("ev_gate")
        signal_idx = stage_names.index("signal_check")
        
        assert ev_gate_idx > signal_idx, "EV gate should run after signal generation"
    
    def test_stage_ordering_fee_check_before_risk(self):
        """Legacy non-gating mode should not wire deprecated fee-aware stages."""
        engine = DecisionEngine(
            use_gating_system=False,
        )
        
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        assert "fee_aware_entry" not in stage_names
        assert stage_names.index("risk_check") > stage_names.index("signal_check")
    
    def test_stage_ordering_strategy_trend_after_signal(self):
        """Strategy-trend alignment should run after signal generation."""
        engine = DecisionEngine(
            **self._ev_kwargs(),
            strategy_trend_alignment_config=StrategyTrendAlignmentConfig(),
            use_gating_system=True,
        )
        
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        signal_idx = stage_names.index("signal_check")
        strategy_trend_idx = stage_names.index("strategy_trend_alignment")
        
        assert strategy_trend_idx > signal_idx, "Strategy-trend alignment should run after signal generation"

    def test_confirmation_stage_flag_wires_stage_after_signal(self):
        """Optional confirmation stage should be inserted after signal generation."""
        engine = DecisionEngine(
            **self._ev_kwargs(),
            enable_confirmation_stage=True,
            use_gating_system=True,
        )

        stage_names = [stage.name for stage in engine.orchestrator.stages]

        assert "confirmation" in stage_names
        assert stage_names.index("confirmation") > stage_names.index("signal_check")
    
    def test_stage_ordering_session_filter_before_risk(self):
        """Session filter should run before risk stage."""
        engine = DecisionEngine(
            **self._ev_kwargs(),
            session_filter_config=SessionFilterConfig(),
            use_gating_system=True,
        )
        
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        session_filter_idx = stage_names.index("session_filter")
        risk_idx = stage_names.index("risk_check")
        
        assert session_filter_idx < risk_idx, "Session filter should run before risk stage"
    
    def test_config_loading_from_environment(self):
        """Configuration should load from environment variables."""
        import os
        
        # Set environment variables
        os.environ["FEE_AWARE_ENTRY_FEE_RATE_BPS"] = "6.0"
        os.environ["LOSS_PREVENTION_ENABLED"] = "true"
        os.environ["EV_GATE_MODE"] = "shadow"
        os.environ["EV_GATE_EV_MIN"] = "0.03"
        os.environ["EV_SIZER_K"] = "3.5"
        
        try:
            config = load_loss_prevention_config()
            
            assert config.fee_aware_entry.fee_rate_bps == 6.0
            assert config.enabled is True
            assert config.ev_gate is not None
            assert config.ev_gate.mode == "shadow"
            assert config.ev_gate.ev_min == 0.03
            assert config.ev_position_sizer is not None
            assert config.ev_position_sizer.k == 3.5
            assert not hasattr(config, "confidence_gate")
            assert not hasattr(config, "confidence_position_sizer")
        finally:
            # Clean up environment
            os.environ.pop("FEE_AWARE_ENTRY_FEE_RATE_BPS", None)
            os.environ.pop("LOSS_PREVENTION_ENABLED", None)
            os.environ.pop("EV_GATE_MODE", None)
            os.environ.pop("EV_GATE_EV_MIN", None)
            os.environ.pop("EV_SIZER_K", None)
    
    def test_config_manager_reload(self):
        """Config manager should support reloading configuration."""
        import os
        
        manager = LossPreventionConfigManager()
        
        # Get initial config
        initial_config = manager.config
        initial_ev_min = initial_config.ev_gate.ev_min if initial_config.ev_gate else None
        
        # Change environment and reload
        os.environ["EV_GATE_EV_MIN"] = "0.75"
        
        try:
            reloaded_config = manager.reload()
            assert reloaded_config.ev_gate is not None
            assert reloaded_config.ev_gate.ev_min == 0.75
            assert reloaded_config.ev_gate.ev_min != initial_ev_min
        finally:
            os.environ.pop("EV_GATE_EV_MIN", None)
    
    def test_low_confidence_signal_rejected(self):
        """Low confidence signals should be rejected by confidence gate."""
        engine = DecisionEngine(
            use_gating_system=False,
        )
        
        decision_input = DecisionInput(
            symbol="BTCUSDT",
            market_context={"price": 50000.0},
            features={"price": 50000.0},
            prediction={"confidence": 0.30},  # Below threshold
        )
        
        result = asyncio.run(engine.decide(decision_input))
        
        # Should be rejected due to low confidence
        assert result is False
    
    def test_high_confidence_signal_passes_confidence_gate(self):
        """High confidence signals should pass confidence gate."""
        engine = DecisionEngine(
            use_gating_system=False,
        )
        
        decision_input = DecisionInput(
            symbol="BTCUSDT",
            market_context={"price": 50000.0},
            features={"price": 50000.0},
            prediction={"confidence": 0.80},  # Above threshold
        )
        
        # This will still be rejected by other stages (no signal generated),
        # but it should pass the confidence gate
        result, ctx = asyncio.run(engine.decide_with_context(decision_input))
        
        # Check that rejection was NOT due to confidence gate
        if ctx.rejection_stage:
            assert ctx.rejection_stage != "confidence_gate"


class TestLossPreventionStageIntegration:
    """Integration tests for loss prevention stages in the pipeline."""
    
    def test_full_pipeline_with_all_loss_prevention_stages(self):
        """Full gating pipeline should use the modern EV-based loss prevention stages."""
        engine = DecisionEngine(
            ev_gate_config=load_loss_prevention_config().ev_gate,
            strategy_trend_alignment_config=StrategyTrendAlignmentConfig(),
            session_filter_config=SessionFilterConfig(),
            ev_position_sizer_config=load_loss_prevention_config().ev_position_sizer,
            use_gating_system=True,
        )
        
        # Verify all stages are present
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        expected_stages = [
            "data_readiness",
            "amt_calculator",
            "symbol_characteristics",
            "snapshot_builder",
            "global_gate",
            "profile_routing",
            "position_evaluation",
            "cooldown",
            "prediction_gate",
            "signal_check",
            "strategy_trend_alignment",
            "model_direction_alignment",
            "cost_data_quality",
            "ev_gate",
            "session_filter",
            "ev_position_sizer",
            "candidate_generation",
            "candidate_veto",
            "risk_check",
            "execution",
        ]
        
        for expected in expected_stages:
            assert expected in stage_names, f"Missing stage: {expected}"
    
    def test_full_pipeline_with_ev_gate(self):
        """Full pipeline should work with EVGateStage instead of ConfidenceGateStage."""
        engine = DecisionEngine(
            ev_gate_config=EVGateConfig(mode="shadow", ev_min=0.02),
            strategy_trend_alignment_config=StrategyTrendAlignmentConfig(),
            session_filter_config=SessionFilterConfig(),
            ev_position_sizer_config=load_loss_prevention_config().ev_position_sizer,
            use_gating_system=True,
        )
        
        # Verify all stages are present
        stage_names = [stage.name for stage in engine.orchestrator.stages]
        
        expected_stages = [
            "data_readiness",
            "symbol_characteristics",
            "snapshot_builder",
            "global_gate",
            "profile_routing",
            "position_evaluation",
            "cooldown",
            "prediction_gate",
            "signal_check",
            "ev_gate",  # EVGateStage instead of confidence_gate
            "strategy_trend_alignment",
            "session_filter",
            "ev_position_sizer",
            "candidate_generation",
            "candidate_veto",
            "risk_check",
            "execution",
        ]
        
        for expected in expected_stages:
            assert expected in stage_names, f"Missing stage: {expected}"
        
        # Verify confidence_gate is NOT present
        assert "confidence_gate" not in stage_names
        assert "fee_aware_entry" not in stage_names
