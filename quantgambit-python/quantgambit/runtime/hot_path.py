"""
In-process hot path implementation.

This is the critical path from market data tick to execution intent.
All components run in the same process/event loop to minimize latency.

The hot path does NOT:
- Block on Redis
- Block on database writes
- Do any I/O on the critical path

Events are published to a side channel asynchronously (fire-and-forget).

Architecture:
    WS → BookGuardian → DecisionPipeline → ExecutionGateway
                ↓                ↓
           SideChannel    SideChannel
               (async)       (async)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from quantgambit.core.clock import Clock
from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.core.book.types import OrderBook, BookUpdate
from quantgambit.core.book.guardian import BookGuardian
from quantgambit.core.risk.kill_switch import KillSwitch, KillSwitchTrigger
from quantgambit.core.decision import (
    DecisionInput,
    BookSnapshot,
    Position,
    ExecutionIntent,
    DecisionRecord,
    DecisionRecordBuilder,
    DecisionOutcome,
    FeatureFrameBuilder,
    ModelRunner,
    Calibrator,
    EdgeTransform,
    VolatilityEstimator,
    RiskMapper,
    ExecutionPolicy,
    CalibrationOutput,
    CalibrationGate,
)
from quantgambit.core.ids import generate_trace_id
from quantgambit.core.latency import LatencyTracker
from quantgambit.io.sidechannel import SideChannelPublisher
from quantgambit.risk.symbol_calibrator import SymbolCalibrator

logger = logging.getLogger(__name__)


class ExecutionGateway(Protocol):
    """Interface for sending orders to exchange."""
    
    async def submit_intent(self, intent: ExecutionIntent) -> bool:
        """Submit execution intent. Returns True if accepted."""
        ...
    
    async def cancel_all(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders. Returns count canceled."""
        ...
    
    async def flatten_position(self, symbol: str) -> bool:
        """Flatten position for symbol. Returns True if successful."""
        ...


@dataclass
class HotPathConfig:
    """Configuration for hot path."""
    
    # Timing
    max_decision_age_ms: float = 500.0  # Max age for valid decision
    staleness_threshold_ms: float = 1000.0  # Book staleness threshold
    
    # Behavior
    allow_entries: bool = True
    allow_exits: bool = True
    
    # Pipeline
    feature_set_version_id: str = "default"
    model_version_id: str = "default"
    calibrator_version_id: str = "default"
    risk_profile_version_id: str = "default"
    execution_policy_version_id: str = "default"
    
    # Bundle
    config_bundle_id: str = "default_bundle"


@dataclass
class HotPathState:
    """Mutable state for hot path."""
    
    # Positions per symbol
    positions: Dict[str, Position] = field(default_factory=dict)
    
    # Account state
    account_equity: float = 0.0
    available_margin: float = 0.0
    
    # Pending intents (not yet confirmed)
    pending_intents: Dict[str, ExecutionIntent] = field(default_factory=dict)
    
    # Statistics
    ticks_processed: int = 0
    decisions_made: int = 0
    intents_emitted: int = 0
    blocked_count: int = 0


class HotPath:
    """
    In-process hot path for tick-to-decision-to-execution.
    
    This is the performance-critical path. All operations must be:
    - Non-blocking
    - In-process (no IPC)
    - Low-latency
    
    I/O (Redis, DB) happens asynchronously via side channel.
    
    Usage:
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=features,
            model_runner=model,
            calibrator=calibrator,
            edge_transform=edge,
            vol_estimator=vol,
            risk_mapper=risk,
            execution_policy=policy,
            execution_gateway=gateway,
            publisher=publisher,
        )
        
        # Process incoming book updates
        hot_path.on_book_update(update)
        
        # Process incoming trades
        hot_path.on_trade(trade)
    """
    
    def __init__(
        self,
        clock: Clock,
        book_guardian: BookGuardian,
        kill_switch: KillSwitch,
        feature_builder: FeatureFrameBuilder,
        model_runner: ModelRunner,
        calibrator: Calibrator,
        edge_transform: EdgeTransform,
        vol_estimator: VolatilityEstimator,
        risk_mapper: RiskMapper,
        execution_policy: ExecutionPolicy,
        execution_gateway: ExecutionGateway,
        publisher: SideChannelPublisher,
        config: Optional[HotPathConfig] = None,
        latency_tracker: Optional[LatencyTracker] = None,
        symbol_calibrator: Optional[SymbolCalibrator] = None,
        calibration_gate: Optional[CalibrationGate] = None,
    ):
        """Initialize hot path with all pipeline components."""
        self._clock = clock
        self._guardian = book_guardian
        self._kill_switch = kill_switch
        
        # Pipeline components
        self._feature_builder = feature_builder
        self._model_runner = model_runner
        self._calibrator = calibrator
        self._edge_transform = edge_transform
        self._vol_estimator = vol_estimator
        self._risk_mapper = risk_mapper
        self._exec_policy = execution_policy
        self._gateway = execution_gateway
        
        # Side channel
        self._publisher = publisher
        
        # Config and state
        self._config = config or HotPathConfig()
        self._state = HotPathState()
        
        # Latency tracking
        self._latency = latency_tracker or LatencyTracker()
        
        # Recent trades per symbol (for features)
        self._recent_trades: Dict[str, List[Dict[str, Any]]] = {}
        
        # Symbol calibrator for per-symbol spread/depth thresholds
        self._symbol_calibrator = symbol_calibrator
        self._calibration_gate = calibration_gate
        
        # Create gate if calibrator provided but gate not
        if self._symbol_calibrator and not self._calibration_gate:
            self._calibration_gate = CalibrationGate(self._symbol_calibrator)
    
    def on_book_update(self, symbol: str, update: BookUpdate) -> None:
        """
        Process incoming book update.
        
        This is the primary entry point for the hot path.
        Must be fast and non-blocking.
        
        Args:
            symbol: Trading symbol
            update: Book update from exchange
        """
        tick_start = self._latency.start_timer("tick_to_decision")
        self._state.ticks_processed += 1
        
        try:
            # Update book guardian (handles sequence validation, resync, etc.)
            book = self._guardian.handle_update(symbol, update)
            
            if book is None:
                # Book is incoherent, skip decision
                self._latency.end_timer("tick_to_decision", tick_start)
                return
            
            # Check quoteability
            if not self._guardian.is_quoteable(symbol):
                # Not quoteable, trigger kill switch if too long
                self._maybe_trigger_stale_kill_switch(symbol)
                self._latency.end_timer("tick_to_decision", tick_start)
                return
            
            # Run decision pipeline
            self._run_decision_pipeline(symbol, book)
            
        except Exception as e:
            logger.error(f"Hot path error for {symbol}: {e}", exc_info=True)
        finally:
            self._latency.end_timer("tick_to_decision", tick_start)
    
    def on_trade(self, symbol: str, trade: Dict[str, Any]) -> None:
        """
        Process incoming trade.
        
        Accumulates recent trades for feature computation.
        
        Args:
            symbol: Trading symbol
            trade: Trade data
        """
        if symbol not in self._recent_trades:
            self._recent_trades[symbol] = []
        
        trades = self._recent_trades[symbol]
        trades.append(trade)
        
        # Keep only last 100 trades
        if len(trades) > 100:
            self._recent_trades[symbol] = trades[-100:]
    
    def update_position(self, symbol: str, position: Position) -> None:
        """Update position state from exchange."""
        self._state.positions[symbol] = position
    
    def update_account(self, equity: float, margin: float) -> None:
        """Update account state from exchange."""
        self._state.account_equity = equity
        self._state.available_margin = margin
    
    def _run_decision_pipeline(self, symbol: str, book: OrderBook) -> None:
        """
        Run the full decision pipeline for a symbol.
        
        Pipeline:
            BookSnapshot → FeatureFrame → ModelOutput → CalibratedOutput
            → EdgeOutput → VolOutput → RiskOutput → [ExecutionIntent]
        """
        trace_id = generate_trace_id()
        ts_wall = self._clock.now()
        ts_mono = self._clock.now_mono()
        
        # Check kill switch first
        if self._kill_switch.is_active():
            self._emit_blocked_record(
                trace_id, symbol, ts_wall, ts_mono, book,
                DecisionOutcome.BLOCKED_KILL_SWITCH,
                "Kill switch active"
            )
            self._state.blocked_count += 1
            return
        
        # Build decision input
        decision_input = self._build_decision_input(symbol, book, ts_wall, ts_mono)
        
        # Start building decision record
        record_builder = (
            DecisionRecordBuilder()
            .with_identifiers(f"rec_{trace_id}", trace_id, symbol)
            .with_timestamps(ts_wall, ts_mono, book.timestamp)
            .with_bundle(
                bundle_id=self._config.config_bundle_id,
                feature_set_version_id=self._config.feature_set_version_id,
                model_version_id=self._config.model_version_id,
                calibrator_version_id=self._config.calibrator_version_id,
                risk_profile_version_id=self._config.risk_profile_version_id,
                execution_policy_version_id=self._config.execution_policy_version_id,
            )
            .with_book_state(
                bid=book.best_bid_price,
                ask=book.best_ask_price,
                mid=book.mid_price,
                spread_bps=decision_input.book.spread_bps,
                seq=book.sequence_id,
                is_quoteable=True,
            )
            .with_account(equity=decision_input.account_equity)
        )
        
        if decision_input.current_position:
            record_builder.with_position(
                size=decision_input.current_position.size,
                entry_price=decision_input.current_position.entry_price,
                unrealized_pnl=decision_input.current_position.unrealized_pnl,
            )
        
        # Calibration size multiplier (default 1.0 if no calibration gate)
        calibration_size_multiplier = 1.0
        
        try:
            # Feed symbol calibrator with observation (continuous learning)
            if self._symbol_calibrator:
                spread_bps = decision_input.book.spread_bps or 0
                bid_depth = getattr(decision_input.book, 'bid_depth_usd', None) or 0
                ask_depth = getattr(decision_input.book, 'ask_depth_usd', None) or 0
                self._symbol_calibrator.observe(
                    symbol=symbol,
                    spread_bps=spread_bps,
                    bid_depth_usd=bid_depth,
                    ask_depth_usd=ask_depth,
                )
            
            # Calibration gating (before expensive feature computation)
            calibration_output = None
            if self._calibration_gate:
                spread_bps = decision_input.book.spread_bps or 0
                bid_depth = getattr(decision_input.book, 'bid_depth_usd', None) or 0
                ask_depth = getattr(decision_input.book, 'ask_depth_usd', None) or 0
                
                calibration_output = self._calibration_gate.check(
                    symbol=symbol,
                    spread_bps=spread_bps,
                    bid_depth_usd=bid_depth,
                    ask_depth_usd=ask_depth,
                )
                
                record_builder.with_calibration_output(calibration_output)
                
                # Log warning if using fallback thresholds
                if calibration_output.using_fallback:
                    logger.warning(
                        f"Using fallback thresholds for {symbol} "
                        f"(calibration_quality={calibration_output.calibration_quality}, "
                        f"samples={calibration_output.sample_count})"
                    )
                
                # Check spread blocking
                if calibration_output.spread_blocked:
                    record = record_builder.with_outcome(
                        DecisionOutcome.BLOCKED_SPREAD_WIDE,
                        f"Spread {spread_bps:.1f} bps > block threshold {calibration_output.spread_block_bps:.1f} bps"
                    ).build()
                    self._publish_decision_record(record)
                    self._state.blocked_count += 1
                    return
                
                # Check depth blocking
                if calibration_output.depth_blocked:
                    record = record_builder.with_outcome(
                        DecisionOutcome.BLOCKED_DEPTH_THIN,
                        f"Depth ${calibration_output.depth_current_usd:.0f} < block threshold ${calibration_output.depth_block_usd:.0f}"
                    ).build()
                    self._publish_decision_record(record)
                    self._state.blocked_count += 1
                    return
                
                # Store size multiplier for risk mapping
                calibration_size_multiplier = calibration_output.size_multiplier
            
            # Feature building
            feature_start = self._latency.start_timer("feature_build")
            features = self._feature_builder.build(decision_input)
            self._latency.end_timer("feature_build", feature_start)
            record_builder.with_feature_frame(features)
            
            # Model inference
            model_start = self._latency.start_timer("model_infer")
            model_out = self._model_runner.infer(features)
            self._latency.end_timer("model_infer", model_start)
            record_builder.with_model_output(model_out)
            
            # Calibration
            cal_start = self._latency.start_timer("calibrate")
            calibrated = self._calibrator.calibrate(model_out)
            self._latency.end_timer("calibrate", cal_start)
            record_builder.with_calibrated_output(calibrated)
            
            # Edge transform
            edge_start = self._latency.start_timer("edge_transform")
            edge = self._edge_transform.to_edge(calibrated["p_hat"])
            self._latency.end_timer("edge_transform", edge_start)
            record_builder.with_edge_output(edge)
            
            # Check deadband
            if edge["deadband_blocked"]:
                record = record_builder.with_outcome(
                    DecisionOutcome.BLOCKED_DEADBAND,
                    f"Signal {edge['s']:.4f} below tau={edge['tau']}"
                ).build()
                self._publish_decision_record(record)
                self._state.blocked_count += 1
                return
            
            # Volatility estimation
            vol_start = self._latency.start_timer("vol_estimate")
            vol = self._vol_estimator.estimate(decision_input)
            self._latency.end_timer("vol_estimate", vol_start)
            record_builder.with_vol_output(vol["vol_version_id"], vol["vol_hat"], vol.get("extra"))
            
            # Risk mapping
            risk_start = self._latency.start_timer("risk_map")
            risk = self._risk_mapper.map(
                s=edge["s"],
                vol_hat=vol["vol_hat"],
                decision_input=decision_input,
            )
            self._latency.end_timer("risk_map", risk_start)
            
            # Apply calibration size multiplier if degraded conditions
            if calibration_size_multiplier < 1.0:
                # Scale down w_target and delta_w
                original_w_target = risk["w_target"]
                risk["w_target"] = risk["w_target"] * calibration_size_multiplier
                risk["delta_w"] = risk["w_target"] - risk["w_current"]
                risk["extra"] = risk.get("extra", {})
                risk["extra"]["calibration_size_multiplier"] = calibration_size_multiplier
                risk["extra"]["original_w_target"] = original_w_target
            
            record_builder.with_risk_output(risk)
            
            # Check churn guard
            if risk["churn_guard_blocked"]:
                record = record_builder.with_outcome(
                    DecisionOutcome.BLOCKED_CHURN_GUARD,
                    f"Delta {risk['delta_w']:.4f} below min threshold"
                ).build()
                self._publish_decision_record(record)
                self._state.blocked_count += 1
                return
            
            # Check if we should allow this action
            is_entry = risk["delta_w"] * (decision_input.current_weight() or 0) >= 0
            if is_entry and not self._config.allow_entries:
                record = record_builder.with_outcome(
                    DecisionOutcome.NO_ACTION,
                    "Entries disabled"
                ).build()
                self._publish_decision_record(record)
                return
            
            if not is_entry and not self._config.allow_exits:
                record = record_builder.with_outcome(
                    DecisionOutcome.NO_ACTION,
                    "Exits disabled"
                ).build()
                self._publish_decision_record(record)
                return
            
            # Build execution intents
            policy_start = self._latency.start_timer("exec_policy")
            intents = self._exec_policy.build_intents(
                risk_out=risk,
                decision_input=decision_input,
            )
            self._latency.end_timer("exec_policy", policy_start)
            
            if not intents:
                record = record_builder.with_outcome(
                    DecisionOutcome.NO_ACTION,
                    "No intents generated"
                ).build()
                self._publish_decision_record(record)
                return
            
            # Submit intents
            for intent in intents:
                intent.trace_id = trace_id
                self._submit_intent(intent)
            
            self._state.decisions_made += 1
            self._state.intents_emitted += len(intents)
            
            # Build and emit record
            record = record_builder.with_intents(intents).build()
            self._publish_decision_record(record)
            
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            record = record_builder.with_error("pipeline", str(e)).build()
            self._publish_decision_record(record)
    
    def _build_decision_input(
        self,
        symbol: str,
        book: OrderBook,
        ts_wall: float,
        ts_mono: float,
    ) -> DecisionInput:
        """Build DecisionInput from current state."""
        # Use from_order_book to capture sizes for imbalance/microprice
        book_snapshot = BookSnapshot.from_order_book(book, is_quoteable=True)
        
        position = self._state.positions.get(symbol)
        
        return DecisionInput(
            symbol=symbol,
            ts_wall=ts_wall,
            ts_mono=ts_mono,
            book=book_snapshot,
            recent_trades=self._recent_trades.get(symbol, []),
            current_position=position,
            account_equity=self._state.account_equity,
            available_margin=self._state.available_margin,
            pending_intent_count=len(self._state.pending_intents),
            config_bundle_id=self._config.config_bundle_id,
        )
    
    def _compute_spread_bps(self, book: OrderBook) -> Optional[float]:
        """Compute bid-ask spread in basis points."""
        bid = book.best_bid_price
        ask = book.best_ask_price
        mid = book.mid_price
        
        if bid is None or ask is None or mid is None or mid <= 0:
            return None
        
        return ((ask - bid) / mid) * 10000
    
    def _submit_intent(self, intent: ExecutionIntent) -> None:
        """Submit execution intent (fire and forget)."""
        # Track pending
        self._state.pending_intents[intent.intent_id] = intent
        
        # Submit asynchronously
        asyncio.create_task(self._gateway.submit_intent(intent))
        
        # Emit event
        self._emit_intent_event(intent)
    
    def _emit_intent_event(self, intent: ExecutionIntent) -> None:
        """Emit execution intent event to side channel."""
        event = EventEnvelope(
            v=1,
            type=EventType.EXEC_INTENT,
            source="quantgambit.hot_path",
            symbol=intent.symbol,
            ts_wall=self._clock.now(),
            ts_mono=self._clock.now_mono(),
            trace_id=intent.trace_id,
            seq=None,
            payload={
                "intent_id": intent.intent_id,
                "client_order_id": intent.client_order_id,
                "side": intent.side,
                "order_type": intent.order_type,
                "qty": intent.qty,
                "price": intent.price,
                "sl_price": intent.sl_price,
                "tp_price": intent.tp_price,
                "reduce_only": intent.reduce_only,
            },
        )
        self._publisher.publish(event)
    
    def _emit_blocked_record(
        self,
        trace_id: str,
        symbol: str,
        ts_wall: float,
        ts_mono: float,
        book: OrderBook,
        outcome: DecisionOutcome,
        reason: str,
    ) -> None:
        """Emit a blocked decision record."""
        record = (
            DecisionRecordBuilder()
            .with_identifiers(f"rec_{trace_id}", trace_id, symbol)
            .with_timestamps(ts_wall, ts_mono, book.timestamp)
            .with_outcome(outcome, reason)
            .build()
        )
        self._publish_decision_record(record)
    
    def _publish_decision_record(self, record: DecisionRecord) -> None:
        """Publish decision record to side channel."""
        event = record.to_event_envelope()
        self._publisher.publish(event)
    
    def _maybe_trigger_stale_kill_switch(self, symbol: str) -> None:
        """Trigger kill switch if book is stale too long."""
        # This is a simplified check - in production, track staleness duration
        if not self._guardian.is_quoteable(symbol):
            # Don't trigger immediately - let BookGuardian handle resync
            pass
    
    def on_order_update(self, client_order_id: str, status: str, filled_qty: float) -> None:
        """Handle order update from exchange."""
        # Remove from pending if filled/canceled/rejected
        if status in {"FILLED", "CANCELED", "REJECTED"}:
            for intent_id, intent in list(self._state.pending_intents.items()):
                if intent.client_order_id == client_order_id:
                    del self._state.pending_intents[intent_id]
                    break
    
    def stats(self) -> Dict[str, Any]:
        """Get hot path statistics."""
        latencies = self._latency.get_all_percentiles()
        return {
            "ticks_processed": self._state.ticks_processed,
            "decisions_made": self._state.decisions_made,
            "intents_emitted": self._state.intents_emitted,
            "blocked_count": self._state.blocked_count,
            "pending_intents": len(self._state.pending_intents),
            "positions": len(self._state.positions),
            "latencies": latencies,
        }
