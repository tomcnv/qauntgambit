"""Decision engine stub with telemetry hooks."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from quantgambit.observability.logger import log_warning
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.signals.input_builder import build_stage_inputs
from quantgambit.signals.pipeline import (
    Orchestrator,
    Stage,
    StageContext,
    StageResult,
    DataReadinessStage as LegacyDataReadinessStage,
    PredictionStage,
    RiskStage,
    SignalStage,
    ProfileRoutingStage,
    ExecutionStage,
    PositionEvaluationStage,
)
# Import new gating stages
from quantgambit.signals.stages import (
    DataReadinessStage,
    SnapshotBuilderStage,
    SymbolCharacteristicsStage,
    GlobalGateStage,
    CandidateGenerationStage,
    CandidateVetoStage,
    CooldownStage,
    StrategyTrendAlignmentStage,
    StrategyTrendAlignmentConfig,
    ModelDirectionAlignmentStage,
    ModelDirectionAlignmentConfig,
    SessionFilterStage,
    SessionFilterConfig,
    # EV-based entry gate (replaces ConfidenceGateStage)
    EVGateStage,
    EVGateConfig,
    # EV-based position sizer (replaces ConfidencePositionSizer)
    EVPositionSizerStage,
    EVPositionSizerConfig,
    # Cost data quality stage (runs before EVGate)
    CostDataQualityStage,
    CostDataQualityConfig,
    # Optional confirmation stage
    ConfirmationStage,
    ConfirmationConfig,
    # Execution feasibility stage
    ExecutionFeasibilityGate,
    ExecutionFeasibilityConfig,
    # AMT calculator stage (calculates volume profile metrics)
    AMTCalculatorStage,
    AMTCalculatorConfig,
    CandleCache,
)
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.symbol_characteristics_stage import SymbolCharacteristicsStageConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.signals.stages.candidate_veto import CandidateVetoConfig
from quantgambit.signals.stages.cooldown import CooldownConfig, CooldownManager
from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService
from quantgambit.signals.services.parameter_resolver import AdaptiveParameterResolver
from quantgambit.profiles.router import DeepTraderProfileRouter
from quantgambit.strategies.registry import DeepTraderStrategyRegistry
from quantgambit.risk.validator import DeepTraderRiskValidator
from quantgambit.risk.fee_model import FeeModel
from quantgambit.core.risk.correlation_guard import CorrelationGuard
from quantgambit.signals.confirmation import (
    ConfirmationPolicyConfig,
    ConfirmationPolicyEngine,
    default_policy_config_from_env,
)

if TYPE_CHECKING:
    from quantgambit.config.trading_mode import TradingModeManager
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry
    from quantgambit.observability.decision_recorder import DecisionRecorder


@dataclass
class DecisionInput:
    symbol: str
    market_context: dict
    features: dict
    account_state: Optional[dict] = None
    positions: Optional[list] = None
    risk_limits: Optional[dict] = None
    profile_settings: Optional[dict] = None
    prediction: Optional[dict] = None
    rejection_reason: Optional[str] = None
    expected_bps: Optional[float] = None
    expected_fee_usd: Optional[float] = None
    risk_ok: bool = True


class DecisionEngine:
    """Minimal decision engine interface with telemetry emission.
    
    Implements a two-layer gating system with loss prevention stages:
    
    Layer A - Global Gates (side-agnostic, run before signal generation):
    - DataReadinessStage: Sanity checks (book/trades present, clock sync)
    - SnapshotBuilderStage: Freeze immutable MarketSnapshot
    - GlobalGateStage: Side-agnostic rejection (spread, depth, staleness, vol shock)
    - ConfidenceGateStage: Reject signals below minimum confidence threshold (Requirement 1)
    
    Layer B - Candidate Pipeline (side-aware, run after signal generation):
    - StrategyTrendAlignmentStage: Reject signals that conflict with market trend (Requirement 2)
    - FeeAwareEntryStage: Reject signals where expected profit < fees (Requirement 4)
    - SessionFilterStage: Filter signals based on trading session (Requirement 5)
    - CandidateGenerationStage: Wraps strategy + prediction to produce TradeCandidate
    - CandidateVetoStage: Side-aware vetoes (orderflow, regime, tradeability)
    - CooldownStage: Per-symbol-strategy cooldown and hysteresis
    """

    def __init__(
        self,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        stages: Optional[list[Stage]] = None,
        prediction_min_confidence: float = 0.0,
        prediction_allowed_directions: Optional[set[str]] = None,
        # Position evaluation config (tighter defaults for scalping)
        position_eval_min_confirmations: int = 2,
        position_eval_underwater_threshold_pct: float = -0.3,  # Exit faster when underwater
        position_eval_max_underwater_hold_sec: float = 600.0,  # 10 min max (was 1 hour)
        # Fee-aware exit config
        fee_model: Optional[FeeModel] = None,
        min_profit_buffer_bps: float = 5.0,
        fee_check_grace_period_sec: float = 30.0,
        # Global gate config
        global_gate_config: Optional[GlobalGateConfig] = None,
        # Candidate veto config
        candidate_veto_config: Optional[CandidateVetoConfig] = None,
        # Cooldown config
        cooldown_config: Optional[CooldownConfig] = None,
        # Data readiness config
        data_readiness_config: Optional[DataReadinessConfig] = None,
        # Symbol characteristics config
        symbol_characteristics_service: Optional[SymbolCharacteristicsService] = None,
        symbol_characteristics_config: Optional[SymbolCharacteristicsStageConfig] = None,
        # Trading mode manager for mode-aware throttling
        trading_mode_manager: Optional["TradingModeManager"] = None,
        # Loss prevention stage configs (Requirements 1, 2, 4, 5)
        strategy_trend_alignment_config: Optional[StrategyTrendAlignmentConfig] = None,
        model_direction_alignment_config: Optional[ModelDirectionAlignmentConfig] = None,
        session_filter_config: Optional[SessionFilterConfig] = None,
        # EV gate config (replaces confidence_gate)
        ev_gate_config: Optional[EVGateConfig] = None,
        # EV position sizer config (replaces confidence_position_sizer)
        ev_position_sizer_config: Optional[EVPositionSizerConfig] = None,
        # Cost data quality config (runs before EVGate)
        cost_data_quality_config: Optional[CostDataQualityConfig] = None,
        # Optional confirmation stage (disabled by default)
        confirmation_config: Optional[ConfirmationConfig] = None,
        enable_confirmation_stage: Optional[bool] = None,
        # Execution feasibility config
        execution_feasibility_config: Optional[ExecutionFeasibilityConfig] = None,
        # Unified confirmation policy config (entries + non-emergency exits)
        confirmation_policy_config: Optional[ConfirmationPolicyConfig] = None,
        enable_unified_confirmation_policy: Optional[bool] = None,
        # AMT calculator config (calculates volume profile metrics)
        amt_calculator_config: Optional[AMTCalculatorConfig] = None,
        # Candle cache for AMT calculations
        candle_cache: Optional[CandleCache] = None,
        # Blocked signal telemetry for loss prevention stages
        blocked_signal_telemetry: Optional["BlockedSignalTelemetry"] = None,
        # Decision recorder for recording decision context
        decision_recorder: Optional["DecisionRecorder"] = None,
        # Use new gating system (set False for backwards compatibility)
        use_gating_system: bool = True,
        # Backtesting mode - disables data freshness checks in profile router
        backtesting_mode: bool = False,
        # Correlation guard for exposure control
        correlation_guard: Optional[CorrelationGuard] = None,
    ):
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self._trading_mode_manager = trading_mode_manager
        self._blocked_signal_telemetry = blocked_signal_telemetry
        self._decision_recorder = decision_recorder
        profile_router = DeepTraderProfileRouter(backtesting_mode=backtesting_mode)
        strategy_registry = DeepTraderStrategyRegistry()
        risk_validator = DeepTraderRiskValidator()
        self.profile_router = profile_router
        
        # Shared cooldown manager (persists across decisions)
        self._cooldown_manager = CooldownManager()
        
        # Symbol characteristics service (shared across decisions)
        self._symbol_characteristics_service = symbol_characteristics_service or SymbolCharacteristicsService()
        
        if stages:
            # Use provided stages (custom configuration)
            self.orchestrator = Orchestrator(
                stages=stages,
                telemetry=telemetry,
                telemetry_context=telemetry_context,
            )
        elif use_gating_system:
            if ev_gate_config is None:
                raise ValueError(
                    "DecisionEngine(use_gating_system=True) requires explicit ev_gate_config. "
                    "Pass ev_gate_config, or use stages=... / use_gating_system=False explicitly."
                )
            if ev_position_sizer_config is None:
                raise ValueError(
                    "DecisionEngine(use_gating_system=True) requires explicit ev_position_sizer_config. "
                    "Pass ev_position_sizer_config, or use stages=... / use_gating_system=False explicitly."
                )
            # New two-layer gating system with loss prevention stages
            self.orchestrator = Orchestrator(
                stages=self._build_gating_pipeline(
                    profile_router=profile_router,
                    strategy_registry=strategy_registry,
                    risk_validator=risk_validator,
                    position_eval_min_confirmations=position_eval_min_confirmations,
                    position_eval_underwater_threshold_pct=position_eval_underwater_threshold_pct,
                    position_eval_max_underwater_hold_sec=position_eval_max_underwater_hold_sec,
                    fee_model=fee_model,
                    min_profit_buffer_bps=min_profit_buffer_bps,
                    fee_check_grace_period_sec=fee_check_grace_period_sec,
                    prediction_min_confidence=prediction_min_confidence,
                    prediction_allowed_directions=prediction_allowed_directions,
                    global_gate_config=global_gate_config,
                    candidate_veto_config=candidate_veto_config,
                    cooldown_config=cooldown_config,
                    data_readiness_config=data_readiness_config,
                    symbol_characteristics_config=symbol_characteristics_config,
                    trading_mode_manager=trading_mode_manager,
                    # Loss prevention stage configs
                    strategy_trend_alignment_config=strategy_trend_alignment_config,
                    model_direction_alignment_config=model_direction_alignment_config,
                    session_filter_config=session_filter_config,
                    ev_gate_config=ev_gate_config,
                    ev_position_sizer_config=ev_position_sizer_config,
                    cost_data_quality_config=cost_data_quality_config,
                    confirmation_config=confirmation_config,
                    enable_confirmation_stage=enable_confirmation_stage,
                    execution_feasibility_config=execution_feasibility_config,
                    confirmation_policy_config=confirmation_policy_config,
                    enable_unified_confirmation_policy=enable_unified_confirmation_policy,
                    amt_calculator_config=amt_calculator_config,
                    candle_cache=candle_cache,
                    blocked_signal_telemetry=blocked_signal_telemetry,
                    correlation_guard=correlation_guard,
                ),
                telemetry=telemetry,
                telemetry_context=telemetry_context,
            )
        else:
            # Legacy pipeline (backwards compatibility)
            self.orchestrator = Orchestrator(
                stages=[
                    LegacyDataReadinessStage(),
                    PositionEvaluationStage(
                        min_confirmations_for_exit=position_eval_min_confirmations,
                        exit_underwater_threshold_pct=position_eval_underwater_threshold_pct,
                        max_underwater_hold_sec=position_eval_max_underwater_hold_sec,
                        hard_stop_pct=float(os.getenv("HARD_STOP_PCT", "2.0")),
                        fee_model=fee_model,
                        min_profit_buffer_bps=min_profit_buffer_bps,
                        fee_check_grace_period_sec=fee_check_grace_period_sec,
                    ),
                    ProfileRoutingStage(profile_router),
                    PredictionStage(
                        min_confidence=prediction_min_confidence,
                        allowed_directions=prediction_allowed_directions,
                    ),
                    SignalStage(strategy_registry),
                    RiskStage(risk_validator, correlation_guard=correlation_guard),
                    ExecutionStage(),
                ],
                telemetry=telemetry,
                telemetry_context=telemetry_context,
            )
    
    def _build_gating_pipeline(
        self,
        profile_router,
        strategy_registry,
        risk_validator,
        position_eval_min_confirmations: int,
        position_eval_underwater_threshold_pct: float,
        position_eval_max_underwater_hold_sec: float,
        fee_model: Optional[FeeModel],
        min_profit_buffer_bps: float,
        fee_check_grace_period_sec: float,
        prediction_min_confidence: float,
        prediction_allowed_directions: Optional[set[str]],
        global_gate_config: Optional[GlobalGateConfig],
        candidate_veto_config: Optional[CandidateVetoConfig],
        cooldown_config: Optional[CooldownConfig],
        data_readiness_config: Optional[DataReadinessConfig],
        symbol_characteristics_config: Optional[SymbolCharacteristicsStageConfig],
        trading_mode_manager: Optional["TradingModeManager"] = None,
        # Loss prevention stage configs (Requirements 1, 2, 4, 5)
        strategy_trend_alignment_config: Optional[StrategyTrendAlignmentConfig] = None,
        model_direction_alignment_config: Optional[ModelDirectionAlignmentConfig] = None,
        session_filter_config: Optional[SessionFilterConfig] = None,
        ev_gate_config: Optional[EVGateConfig] = None,
        ev_position_sizer_config: Optional[EVPositionSizerConfig] = None,
        cost_data_quality_config: Optional[CostDataQualityConfig] = None,
        confirmation_config: Optional[ConfirmationConfig] = None,
        enable_confirmation_stage: Optional[bool] = None,
        execution_feasibility_config: Optional[ExecutionFeasibilityConfig] = None,
        confirmation_policy_config: Optional[ConfirmationPolicyConfig] = None,
        enable_unified_confirmation_policy: Optional[bool] = None,
        amt_calculator_config: Optional[AMTCalculatorConfig] = None,
        candle_cache: Optional[CandleCache] = None,
        blocked_signal_telemetry: Optional["BlockedSignalTelemetry"] = None,
        correlation_guard: Optional[CorrelationGuard] = None,
    ) -> list[Stage]:
        """Build the two-layer gating pipeline with loss prevention stages.
        
        Pipeline Order (with loss prevention stages integrated):
        
        Layer A - Global Gates (side-agnostic, run before signal generation):
        1. DataReadinessStage - Sanity checks (book/trades present, clock sync)
        2. AMTCalculatorStage - Calculate AMT metrics (POC, VAH, VAL) from candles
        3. SymbolCharacteristicsStage - Inject symbol characteristics and resolved params
        4. SnapshotBuilderStage - Freeze immutable MarketSnapshot
        5. GlobalGateStage - Side-agnostic rejection (spread, depth, staleness, vol shock)
        6. ProfileRoutingStage - Select profile/strategy set
        7. PositionEvaluationStage - Evaluate exits (with SAFETY/INVALIDATION classification)
        8. CooldownStage - Block entries in cooldown
        9. PredictionStage - ML predictions / confidence gate
        10. SignalStage - Strategy signal generation
        
        Layer B - Candidate Pipeline (side-aware, run after signal generation):
        11. StrategyTrendAlignmentStage - Reject signals conflicting with trend (Requirement 2)
        12. ModelDirectionAlignmentStage - Hybrid veto for model/signal side mismatch
        13. CostDataQualityStage - Validate cost data freshness (before EVGate)
        14. EVGateStage - EV-based entry filtering
        15. SessionFilterStage - Filter by trading session (Requirement 5)
        16. EVPositionSizerStage - Scale position size based on EV margin
        17. CandidateGenerationStage - Wrap signal into TradeCandidate
        18. CandidateVetoStage - Side-aware vetoes (orderflow, regime, tradeability)
        19. RiskStage - Final sizing, portfolio exposure
        20. ExecutionStage - Submit to exchange
        
        CostDataQualityStage runs before EVGate to validate cost data freshness.
        AMTCalculatorStage runs after DataReadinessStage and before SnapshotBuilderStage
        to ensure AMT fields are available when building the MarketSnapshot.
        """
        # Determine which entry gate to use
        use_ev_gate = ev_gate_config is not None
        if enable_confirmation_stage is None:
            enable_confirmation_stage = os.getenv("ENABLE_CONFIRMATION_STAGE", "").lower() in {"1", "true", "yes"}
        if enable_unified_confirmation_policy is None:
            enable_unified_confirmation_policy = os.getenv("ENABLE_UNIFIED_CONFIRMATION_POLICY", "true").lower() in {"1", "true", "yes"}
        if confirmation_policy_config is None:
            confirmation_policy_config = default_policy_config_from_env()
        if not enable_unified_confirmation_policy:
            confirmation_policy_config = ConfirmationPolicyConfig(
                enabled=False,
                mode=confirmation_policy_config.mode,
                version=confirmation_policy_config.version,
                weights=confirmation_policy_config.weights,
                entry=confirmation_policy_config.entry,
                exit_non_emergency=confirmation_policy_config.exit_non_emergency,
                override_bounds=confirmation_policy_config.override_bounds,
                strategy_overrides=confirmation_policy_config.strategy_overrides,
            )
        confirmation_policy_engine = ConfirmationPolicyEngine(config=confirmation_policy_config)
        
        stages = [
            # Layer A: Global Gates (side-agnostic)
            DataReadinessStage(config=data_readiness_config),
            
            # AMT Calculator - Calculate volume profile metrics (POC, VAH, VAL)
            # Runs after DataReadinessStage and before SnapshotBuilderStage
            # to ensure AMT fields are available when building MarketSnapshot
            AMTCalculatorStage(
                config=amt_calculator_config,
                candle_cache=candle_cache,
            ),
            
            SymbolCharacteristicsStage(
                characteristics_service=self._symbol_characteristics_service,
                resolver=AdaptiveParameterResolver(),
                config=symbol_characteristics_config,
            ),
            SnapshotBuilderStage(),
            GlobalGateStage(config=global_gate_config),

            # Position Management (with fee-aware exits)
            PositionEvaluationStage(
                min_confirmations_for_exit=position_eval_min_confirmations,
                exit_underwater_threshold_pct=position_eval_underwater_threshold_pct,
                max_underwater_hold_sec=position_eval_max_underwater_hold_sec,
                hard_stop_pct=float(os.getenv("HARD_STOP_PCT", "2.0")),
                fee_model=fee_model,
                min_profit_buffer_bps=min_profit_buffer_bps,
                fee_check_grace_period_sec=fee_check_grace_period_sec,
                trading_mode_manager=trading_mode_manager,
                confirmation_policy_engine=confirmation_policy_engine,
            ),

            # Routing
            ProfileRoutingStage(profile_router),
            CooldownStage(
                config=cooldown_config,
                manager=self._cooldown_manager,
                trading_mode_manager=trading_mode_manager,
            ),
            
            # Signal Generation
            PredictionStage(
                min_confidence=prediction_min_confidence,
                allowed_directions=prediction_allowed_directions,
            ),
            SignalStage(strategy_registry),
        ]
        
        # Layer B: Loss Prevention Stages (side-aware, after signal generation)
        
        # Remaining loss prevention stages
        stages.extend([
            # Optional extra confirmation gate (flow + trend checks).
            *([ConfirmationStage(config=confirmation_config, policy_engine=confirmation_policy_engine)] if enable_confirmation_stage else []),
            # Strategy-Trend Alignment - reject signals conflicting with trend (Requirement 2)
            StrategyTrendAlignmentStage(
                config=strategy_trend_alignment_config,
                telemetry=blocked_signal_telemetry,
            ),
            # Model-direction alignment - reject side mismatches when prediction is strong
            ModelDirectionAlignmentStage(
                config=model_direction_alignment_config,
                telemetry=blocked_signal_telemetry,
            ),
        ])

        if not use_ev_gate or ev_gate_config is None or ev_position_sizer_config is None:
            raise ValueError(
                "Gating pipeline requires explicit EV gate and EV position sizer configs; "
                "legacy confidence-based fallbacks are no longer supported."
            )

        # Cost Data Quality - validate cost data freshness before EVGate
        stages.append(
            CostDataQualityStage(
                config=cost_data_quality_config,
                telemetry=blocked_signal_telemetry,
            )
        )

        stages.append(
            EVGateStage(
                config=ev_gate_config,
                telemetry=blocked_signal_telemetry,
            )
        )

        stages.append(
            SessionFilterStage(
                config=session_filter_config,
                telemetry=blocked_signal_telemetry,
            )
        )
        
        stages.append(
            EVPositionSizerStage(
                config=ev_position_sizer_config,
                telemetry=blocked_signal_telemetry,
            )
        )

        # Candidate Pipeline
        stages.extend([
            CandidateGenerationStage(strategy_registry=strategy_registry),
            CandidateVetoStage(config=candidate_veto_config),
            
            # Risk & Execution
            RiskStage(risk_validator, correlation_guard=correlation_guard),
            ExecutionFeasibilityGate(
                config=execution_feasibility_config or ExecutionFeasibilityConfig.from_env(),
            ),
            ExecutionStage(),
        ])
        
        return stages

    async def _record_decision(
        self,
        decision_input: DecisionInput,
        ctx: StageContext,
        result: StageResult,
    ) -> None:
        """Record a decision with full context.
        
        Args:
            decision_input: The input to the decision
            ctx: The stage context after execution
            result: The stage result (COMPLETE, REJECTED, etc.)
        """
        try:
            decision_outcome = "accepted" if result == StageResult.COMPLETE else "rejected"
            
            # Build market snapshot from context
            market_snapshot = ctx.data.get("market_context", {})
            features = ctx.data.get("features", {})
            
            await self._decision_recorder.record(
                symbol=decision_input.symbol,
                snapshot=market_snapshot,
                features=features,
                ctx=ctx,
                decision=decision_outcome,
            )
        except Exception as exc:
            # Log but don't fail the decision
            log_warning("decision_recording_failed", error=str(exc))

    async def decide(self, decision_input: DecisionInput) -> bool:
        if self.telemetry and self.telemetry_context and decision_input.prediction:
            await self.telemetry.publish_prediction(
                ctx=self.telemetry_context,
                symbol=decision_input.symbol,
                payload=decision_input.prediction,
            )
        stage_inputs = build_stage_inputs(
            decision_input.symbol,
            decision_input.market_context,
            decision_input.features,
        )
        calibration_data = stage_inputs.market_context.get("calibration")
        ctx = StageContext(
            symbol=decision_input.symbol,
            data={
                "features": stage_inputs.features,
                "market_context": stage_inputs.market_context,
                "risk_ok": decision_input.risk_ok,
                "account": decision_input.account_state,
                "positions": decision_input.positions,
                "risk_limits": decision_input.risk_limits,
                "profile_settings": decision_input.profile_settings,
                "prediction": decision_input.prediction,
                **({"calibration": calibration_data} if calibration_data is not None else {}),
            },
            rejection_reason=decision_input.rejection_reason or (stage_inputs.errors[0] if stage_inputs.errors else None),
        )
        result = await self.orchestrator.execute(ctx)
        
        # Record decision if recorder is available
        if self._decision_recorder:
            await self._record_decision(decision_input, ctx, result)
        
        return result == StageResult.COMPLETE

    async def decide_with_context(self, decision_input: DecisionInput) -> tuple[bool, StageContext]:
        if self.telemetry and self.telemetry_context and decision_input.prediction:
            await self.telemetry.publish_prediction(
                ctx=self.telemetry_context,
                symbol=decision_input.symbol,
                payload=decision_input.prediction,
            )
        stage_inputs = build_stage_inputs(
            decision_input.symbol,
            decision_input.market_context,
            decision_input.features,
        )
        calibration_data = stage_inputs.market_context.get("calibration")
        amt_levels_data = stage_inputs.market_context.pop("amt_levels", None)
        ctx = StageContext(
            symbol=decision_input.symbol,
            data={
                "features": stage_inputs.features,
                "market_context": stage_inputs.market_context,
                "risk_ok": decision_input.risk_ok,
                "account": decision_input.account_state,
                "positions": decision_input.positions,
                "risk_limits": decision_input.risk_limits,
                "profile_settings": decision_input.profile_settings,
                "prediction": decision_input.prediction,
                **({"calibration": calibration_data} if calibration_data is not None else {}),
                **({"amt_levels": amt_levels_data} if amt_levels_data is not None else {}),
            },
            rejection_reason=decision_input.rejection_reason or (stage_inputs.errors[0] if stage_inputs.errors else None),
        )
        result = await self.orchestrator.execute(ctx)
        
        # Record decision if recorder is available
        if self._decision_recorder:
            await self._record_decision(decision_input, ctx, result)
        
        return result == StageResult.COMPLETE, ctx
