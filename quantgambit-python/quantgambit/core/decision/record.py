"""
DecisionRecord implementation.

Every decision cycle MUST emit a DecisionRecord, including blocked decisions.
This provides a complete audit trail for compliance, debugging, and replay.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.core.decision.interfaces import (
    FeatureFrame,
    ModelOutput,
    CalibratedOutput,
    EdgeOutput,
    RiskOutput,
    ExecutionIntent,
)

if TYPE_CHECKING:
    from quantgambit.core.decision.calibration import CalibrationOutput


class DecisionOutcome(str, Enum):
    """Possible outcomes of a decision cycle."""
    
    # Normal outcomes
    NO_ACTION = "no_action"  # No signal, no trade
    INTENT_EMITTED = "intent_emitted"  # Normal execution intent created
    
    # Blocked outcomes
    BLOCKED_KILL_SWITCH = "blocked_kill_switch"
    BLOCKED_BOOK_UNSAFE = "blocked_book_unsafe"  # Book not quoteable
    BLOCKED_DEADBAND = "blocked_deadband"  # Signal below tau
    BLOCKED_CHURN_GUARD = "blocked_churn_guard"  # Delta too small
    BLOCKED_MAX_POSITION = "blocked_max_position"
    BLOCKED_COOLDOWN = "blocked_cooldown"  # Per-symbol cooldown
    BLOCKED_RISK_LIMIT = "blocked_risk_limit"  # Risk budget exceeded
    BLOCKED_DATA_QUALITY = "blocked_data_quality"  # Low quality features
    BLOCKED_NO_EQUITY = "blocked_no_equity"  # No equity data
    BLOCKED_STALE_DATA = "blocked_stale_data"
    BLOCKED_SPREAD_WIDE = "blocked_spread_wide"  # Spread exceeds calibrated threshold
    BLOCKED_DEPTH_THIN = "blocked_depth_thin"  # Depth below calibrated threshold
    
    # Error outcomes
    ERROR_FEATURE_BUILD = "error_feature_build"
    ERROR_MODEL_INFER = "error_model_infer"
    ERROR_CALIBRATION = "error_calibration"
    ERROR_EDGE_TRANSFORM = "error_edge_transform"
    ERROR_VOL_ESTIMATE = "error_vol_estimate"
    ERROR_RISK_MAP = "error_risk_map"
    ERROR_INTENT_BUILD = "error_intent_build"


@dataclass
class DecisionRecord:
    """
    Complete audit record of a decision cycle.
    
    Every decision cycle MUST produce a DecisionRecord, regardless of
    whether it results in execution or is blocked/errored.
    
    This record contains:
    - Version IDs for all pipeline components
    - Inputs (features, book state, position, account)
    - Intermediate outputs from each stage
    - Final outcome and any execution intents
    - Timing information
    - Block reasons if applicable
    """
    
    # Schema version for backwards compatibility
    schema_version: int = 1
    
    # Identifiers
    record_id: str = ""  # Unique ID for this record
    trace_id: str = ""  # Correlation ID for related events
    symbol: str = ""
    
    # Timestamps
    ts_wall: float = 0.0  # Wall clock time
    ts_mono: float = 0.0  # Monotonic time
    ts_book: float = 0.0  # Book timestamp (exchange time or local)
    
    # Version bundle (all component versions)
    bundle_id: str = ""
    feature_set_version_id: str = ""
    model_version_id: str = ""
    calibrator_version_id: str = ""
    edge_transform_version_id: str = ""
    vol_estimator_version_id: str = ""
    risk_profile_version_id: str = ""
    execution_policy_version_id: str = ""
    
    # Book state at decision time
    book_bid: Optional[float] = None
    book_ask: Optional[float] = None
    book_mid: Optional[float] = None
    book_spread_bps: Optional[float] = None
    book_seq: Optional[int] = None
    book_is_quoteable: bool = False
    
    # Position state
    position_size: float = 0.0
    position_entry_price: Optional[float] = None
    position_unrealized_pnl: Optional[float] = None
    
    # Account state
    account_equity: float = 0.0
    
    # Pipeline stage outputs (optional, for debugging)
    feature_frame: Optional[FeatureFrame] = None
    model_output: Optional[ModelOutput] = None
    calibrated_output: Optional[CalibratedOutput] = None
    edge_output: Optional[EdgeOutput] = None
    vol_output: Optional[Dict[str, Any]] = None
    risk_output: Optional[RiskOutput] = None
    
    # Calibration gating output (per-symbol spread/depth thresholds)
    calibration_output: Optional["CalibrationOutput"] = None
    
    # Key derived values (always present)
    signal_s: float = 0.0  # Final edge signal
    vol_hat: float = 0.0  # Volatility estimate
    w_current: float = 0.0  # Current position weight
    w_target: float = 0.0  # Target position weight
    delta_w: float = 0.0  # Position change
    
    # Outcome
    outcome: DecisionOutcome = DecisionOutcome.NO_ACTION
    block_reason: str = ""  # Human readable block reason
    
    # Execution intents (if any)
    intents: List[ExecutionIntent] = field(default_factory=list)
    
    # Error info (if outcome is ERROR_*)
    error_stage: str = ""
    error_message: str = ""
    
    # Extra metadata
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_event_envelope(self, source: str = "quantgambit.decision") -> EventEnvelope:
        """
        Convert to EventEnvelope for publishing.
        
        Args:
            source: Event source identifier
            
        Returns:
            EventEnvelope suitable for publishing
        """
        payload = {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "symbol": self.symbol,
            "ts_book": self.ts_book,
            
            # Versions
            "bundle_id": self.bundle_id,
            "feature_set_version_id": self.feature_set_version_id,
            "model_version_id": self.model_version_id,
            "calibrator_version_id": self.calibrator_version_id,
            "edge_transform_version_id": self.edge_transform_version_id,
            "vol_estimator_version_id": self.vol_estimator_version_id,
            "risk_profile_version_id": self.risk_profile_version_id,
            "execution_policy_version_id": self.execution_policy_version_id,
            
            # Book state
            "book": {
                "bid": self.book_bid,
                "ask": self.book_ask,
                "mid": self.book_mid,
                "spread_bps": self.book_spread_bps,
                "seq": self.book_seq,
                "is_quoteable": self.book_is_quoteable,
            },
            
            # Position
            "position": {
                "size": self.position_size,
                "entry_price": self.position_entry_price,
                "unrealized_pnl": self.position_unrealized_pnl,
            },
            
            # Account
            "account_equity": self.account_equity,
            
            # Signals
            "signal_s": self.signal_s,
            "vol_hat": self.vol_hat,
            "w_current": self.w_current,
            "w_target": self.w_target,
            "delta_w": self.delta_w,
            
            # Outcome
            "outcome": self.outcome.value,
            "block_reason": self.block_reason,
            
            # Intents
            "intent_ids": [i.intent_id for i in self.intents],
            
            # Error info
            "error_stage": self.error_stage,
            "error_message": self.error_message,
            
            # Calibration output (per-symbol thresholds)
            "calibration_output": (
                self.calibration_output.to_dict() 
                if self.calibration_output else None
            ),
            
            # Extra
            "extra": self.extra,
        }
        
        return EventEnvelope(
            v=self.schema_version,
            type=EventType.DECISION,
            source=source,
            symbol=self.symbol,
            ts_wall=self.ts_wall,
            ts_mono=self.ts_mono,
            trace_id=self.trace_id,
            seq=None,
            payload=payload,
        )
    
    def is_blocked(self) -> bool:
        """Check if this decision was blocked."""
        return self.outcome.value.startswith("blocked_")
    
    def is_error(self) -> bool:
        """Check if this decision errored."""
        return self.outcome.value.startswith("error_")
    
    def produced_intents(self) -> bool:
        """Check if this decision produced execution intents."""
        return len(self.intents) > 0


class DecisionRecordBuilder:
    """
    Builder for constructing DecisionRecords.
    
    Provides a fluent interface for building records, capturing
    intermediate pipeline outputs as they become available.
    """
    
    def __init__(self):
        self._record = DecisionRecord()
    
    def with_identifiers(
        self,
        record_id: str,
        trace_id: str,
        symbol: str,
    ) -> "DecisionRecordBuilder":
        """Set identifiers."""
        self._record.record_id = record_id
        self._record.trace_id = trace_id
        self._record.symbol = symbol
        return self
    
    def with_timestamps(
        self,
        ts_wall: float,
        ts_mono: float,
        ts_book: float,
    ) -> "DecisionRecordBuilder":
        """Set timestamps."""
        self._record.ts_wall = ts_wall
        self._record.ts_mono = ts_mono
        self._record.ts_book = ts_book
        return self
    
    def with_bundle(
        self,
        bundle_id: str,
        feature_set_version_id: str,
        model_version_id: str,
        calibrator_version_id: str,
        edge_transform_version_id: str = "",
        vol_estimator_version_id: str = "",
        risk_profile_version_id: str = "",
        execution_policy_version_id: str = "",
    ) -> "DecisionRecordBuilder":
        """Set version bundle."""
        self._record.bundle_id = bundle_id
        self._record.feature_set_version_id = feature_set_version_id
        self._record.model_version_id = model_version_id
        self._record.calibrator_version_id = calibrator_version_id
        self._record.edge_transform_version_id = edge_transform_version_id
        self._record.vol_estimator_version_id = vol_estimator_version_id
        self._record.risk_profile_version_id = risk_profile_version_id
        self._record.execution_policy_version_id = execution_policy_version_id
        return self
    
    def with_book_state(
        self,
        bid: Optional[float],
        ask: Optional[float],
        mid: Optional[float],
        spread_bps: Optional[float],
        seq: Optional[int],
        is_quoteable: bool,
    ) -> "DecisionRecordBuilder":
        """Set book state at decision time."""
        self._record.book_bid = bid
        self._record.book_ask = ask
        self._record.book_mid = mid
        self._record.book_spread_bps = spread_bps
        self._record.book_seq = seq
        self._record.book_is_quoteable = is_quoteable
        return self
    
    def with_position(
        self,
        size: float,
        entry_price: Optional[float] = None,
        unrealized_pnl: Optional[float] = None,
    ) -> "DecisionRecordBuilder":
        """Set position state."""
        self._record.position_size = size
        self._record.position_entry_price = entry_price
        self._record.position_unrealized_pnl = unrealized_pnl
        return self
    
    def with_account(self, equity: float) -> "DecisionRecordBuilder":
        """Set account state."""
        self._record.account_equity = equity
        return self
    
    def with_feature_frame(self, frame: FeatureFrame) -> "DecisionRecordBuilder":
        """Record feature frame output."""
        self._record.feature_frame = frame
        self._record.feature_set_version_id = frame["feature_set_version_id"]
        return self
    
    def with_model_output(self, output: ModelOutput) -> "DecisionRecordBuilder":
        """Record model output."""
        self._record.model_output = output
        self._record.model_version_id = output["model_version_id"]
        return self
    
    def with_calibrated_output(self, output: CalibratedOutput) -> "DecisionRecordBuilder":
        """Record calibrated output."""
        self._record.calibrated_output = output
        self._record.calibrator_version_id = output["calibrator_version_id"]
        return self
    
    def with_edge_output(self, output: EdgeOutput) -> "DecisionRecordBuilder":
        """Record edge output."""
        self._record.edge_output = output
        self._record.signal_s = output["s"]
        self._record.edge_transform_version_id = output.get("extra", {}).get(
            "edge_transform_version_id", ""
        )
        return self
    
    def with_vol_output(self, vol_version_id: str, vol_hat: float, extra: Dict[str, Any] = None) -> "DecisionRecordBuilder":
        """Record volatility output."""
        self._record.vol_output = {
            "vol_version_id": vol_version_id,
            "vol_hat": vol_hat,
            "extra": extra or {},
        }
        self._record.vol_hat = vol_hat
        self._record.vol_estimator_version_id = vol_version_id
        return self
    
    def with_risk_output(self, output: RiskOutput) -> "DecisionRecordBuilder":
        """Record risk output."""
        self._record.risk_output = output
        self._record.risk_profile_version_id = output["risk_profile_version_id"]
        self._record.w_current = output["w_current"]
        self._record.w_target = output["w_target"]
        self._record.delta_w = output["delta_w"]
        return self
    
    def with_outcome(
        self,
        outcome: DecisionOutcome,
        block_reason: str = "",
    ) -> "DecisionRecordBuilder":
        """Set outcome."""
        self._record.outcome = outcome
        self._record.block_reason = block_reason
        return self
    
    def with_intents(self, intents: List[ExecutionIntent]) -> "DecisionRecordBuilder":
        """Add execution intents."""
        self._record.intents = intents
        if intents:
            self._record.outcome = DecisionOutcome.INTENT_EMITTED
        return self
    
    def with_error(
        self,
        stage: str,
        message: str,
    ) -> "DecisionRecordBuilder":
        """Set error info."""
        self._record.error_stage = stage
        self._record.error_message = message
        # Set appropriate outcome based on stage
        stage_to_outcome = {
            "feature_build": DecisionOutcome.ERROR_FEATURE_BUILD,
            "model_infer": DecisionOutcome.ERROR_MODEL_INFER,
            "calibration": DecisionOutcome.ERROR_CALIBRATION,
            "edge_transform": DecisionOutcome.ERROR_EDGE_TRANSFORM,
            "vol_estimate": DecisionOutcome.ERROR_VOL_ESTIMATE,
            "risk_map": DecisionOutcome.ERROR_RISK_MAP,
            "intent_build": DecisionOutcome.ERROR_INTENT_BUILD,
        }
        self._record.outcome = stage_to_outcome.get(stage, DecisionOutcome.ERROR_FEATURE_BUILD)
        return self
    
    def with_extra(self, extra: Dict[str, Any]) -> "DecisionRecordBuilder":
        """Add extra metadata."""
        self._record.extra.update(extra)
        return self
    
    def with_calibration_output(self, output: "CalibrationOutput") -> "DecisionRecordBuilder":
        """Record calibration gating output."""
        self._record.calibration_output = output
        return self
    
    def build(self) -> DecisionRecord:
        """Build the final DecisionRecord."""
        return self._record
