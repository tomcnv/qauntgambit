"""
Decision pipeline interface definitions.

These Protocol classes define the contract for each step in the
decision pipeline. Implementations must be pure (no I/O, no side effects)
to enable deterministic testing and replay.

Pipeline flow:
    DecisionInput -> FeatureFrameBuilder -> FeatureFrame
    FeatureFrame -> ModelRunner -> ModelOutput
    ModelOutput -> Calibrator -> CalibratedOutput
    CalibratedOutput -> EdgeTransform -> EdgeOutput
    DecisionInput -> VolatilityEstimator -> VolOutput
    (EdgeOutput, VolOutput, DecisionInput) -> RiskMapper -> RiskOutput
    (RiskOutput, DecisionInput) -> ExecutionPolicy -> [ExecutionIntent]
"""

from dataclasses import dataclass, field
from typing import Protocol, TypedDict, Optional, List, Dict, Any, runtime_checkable

from quantgambit.core.book.types import OrderBook


# =============================================================================
# Data Types (TypedDict for compatibility with existing code)
# =============================================================================

class FeatureFrame(TypedDict):
    """
    Feature vector for model inference.
    
    Attributes:
        symbol: Trading symbol
        ts_mono: Monotonic timestamp of feature computation
        feature_set_version_id: Version of feature set definition
        feature_names: Ordered list of feature names
        x: Ordered list of feature values (same order as names)
        quality_score: Overall quality score (0-1)
        missing: Dict of feature_name -> is_missing
    """
    
    symbol: str
    ts_mono: float
    
    feature_set_version_id: str
    feature_names: List[str]
    x: List[float]
    quality_score: float
    missing: Dict[str, bool]


class ModelOutput(TypedDict):
    """
    Raw model inference output.
    
    Attributes:
        model_version_id: Version/hash of model artifact
        p_raw: Raw probability (0-1) for primary direction
        extra: Additional outputs (logits, multiclass probs, etc.)
    """
    
    model_version_id: str
    p_raw: float
    extra: Dict[str, Any]


class CalibratedOutput(TypedDict):
    """
    Calibrated probability output.
    
    Attributes:
        calibrator_version_id: Version of calibrator
        p_hat: Calibrated probability (0-1)
        extra: Calibration diagnostics (ECE, bin_id, etc.)
    """
    
    calibrator_version_id: str
    p_hat: float
    extra: Dict[str, Any]


class EdgeOutput(TypedDict):
    """
    Edge signal output.
    
    Attributes:
        s: Edge signal in [-1, +1]
        k: Curve steepness parameter
        tau: Deadband threshold
        deadband_blocked: True if |s| < tau
    """
    
    s: float
    k: float
    tau: float
    deadband_blocked: bool


class VolOutput(TypedDict):
    """
    Volatility estimate output.
    
    Attributes:
        vol_version_id: Version of volatility estimator
        vol_hat: Estimated volatility (annualized or per-second)
        extra: Additional metrics (spread component, regime, etc.)
    """
    
    vol_version_id: str
    vol_hat: float
    extra: Dict[str, Any]


class RiskOutput(TypedDict):
    """
    Risk mapping output.
    
    Attributes:
        risk_profile_version_id: Version of risk profile
        w_current: Current position weight (signed)
        w_target: Target position weight (signed)
        delta_w: Change in weight (w_target - w_current)
        clipped: True if |w_target| was clipped to w_max
        churn_guard_blocked: True if |delta_w| < min_delta_w
        extra: Additional risk metrics
    """
    
    risk_profile_version_id: str
    w_current: float
    w_target: float
    delta_w: float
    clipped: bool
    churn_guard_blocked: bool
    extra: Dict[str, Any]


# =============================================================================
# Input/Output Dataclasses
# =============================================================================

@dataclass
class Position:
    """Current position state for a symbol."""
    
    size: float = 0.0  # Signed: positive=long, negative=short
    entry_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    
    @property
    def side(self) -> Optional[str]:
        """Get position side: 'long', 'short', or None."""
        if self.size > 0:
            return "long"
        elif self.size < 0:
            return "short"
        return None
    
    @property
    def is_open(self) -> bool:
        """Check if position is open."""
        return abs(self.size) > 0.0001


@dataclass
class BookSnapshot:
    """
    Lightweight book snapshot for decision input.
    
    Contains just the essential book data needed for decisions.
    """
    
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    best_bid_size: Optional[float] = None
    best_ask_size: Optional[float] = None
    mid_price: Optional[float] = None
    spread_bps: Optional[float] = None
    bid_depth: int = 0
    ask_depth: int = 0
    sequence_id: Optional[int] = None
    is_quoteable: bool = False
    timestamp: float = 0.0
    
    @property
    def bids(self) -> list:
        """Return a list with bid depth length (for FeatureBuilder compatibility)."""
        return [None] * self.bid_depth
    
    @property
    def asks(self) -> list:
        """Return a list with ask depth length (for FeatureBuilder compatibility)."""
        return [None] * self.ask_depth
    
    def microprice(self) -> Optional[float]:
        """
        Calculate microprice (size-weighted mid).
        
        Microprice = (bid_size * ask_price + ask_size * bid_price) / (bid_size + ask_size)
        
        Falls back to mid_price if sizes are unavailable.
        """
        if self.best_bid_size and self.best_ask_size and self.best_bid and self.best_ask:
            total_size = self.best_bid_size + self.best_ask_size
            if total_size > 0:
                return (
                    self.best_bid_size * self.best_ask + 
                    self.best_ask_size * self.best_bid
                ) / total_size
        # Fallback to mid_price
        return self.mid_price
    
    def imbalance(self, levels: int = 5) -> Optional[float]:
        """
        Calculate order book imbalance from top-of-book sizes.
        
        Returns value in [-1, 1] where:
        - Positive = more bid pressure
        - Negative = more ask pressure
        
        Note: Since BookSnapshot only has top-of-book sizes, this is
        an approximation based on best bid/ask sizes only.
        """
        if not self.best_bid_size or not self.best_ask_size:
            return None
        
        total = self.best_bid_size + self.best_ask_size
        if total <= 0:
            return None
        
        return (self.best_bid_size - self.best_ask_size) / total
    
    @classmethod
    def from_order_book(cls, book: OrderBook, is_quoteable: bool = False) -> "BookSnapshot":
        """Create snapshot from OrderBook."""
        bid = book.best_bid_price
        ask = book.best_ask_price
        mid = book.mid_price
        
        # Get top-of-book sizes
        bid_size = book.bids[0].size if book.bids else None
        ask_size = book.asks[0].size if book.asks else None
        
        spread_bps = None
        if bid and ask and mid and mid > 0:
            spread_bps = ((ask - bid) / mid) * 10000
        
        return cls(
            best_bid=bid,
            best_ask=ask,
            best_bid_size=bid_size,
            best_ask_size=ask_size,
            mid_price=mid,
            spread_bps=spread_bps,
            bid_depth=len(book.bids),
            ask_depth=len(book.asks),
            sequence_id=book.sequence_id,
            is_quoteable=is_quoteable,
            timestamp=book.timestamp,
        )


@dataclass
class DecisionInput:
    """
    Complete input for a trading decision.
    
    This bundles all data needed to make a decision for one symbol.
    It should be immutable during the decision process.
    """
    
    # Symbol and timing
    symbol: str
    ts_wall: float
    ts_mono: float
    
    # Market data
    book: BookSnapshot
    recent_trades: List[Dict[str, Any]] = field(default_factory=list)
    
    # Current position
    current_position: Optional[Position] = None
    
    # Account state
    account_equity: float = 0.0
    available_margin: float = 0.0
    
    # Open orders
    open_order_count: int = 0
    pending_intent_count: int = 0
    
    # Risk limits
    max_position_size: float = 0.0
    max_position_value: float = 0.0
    max_leverage: float = 1.0
    
    # Config references (for versioning)
    config_bundle_id: Optional[str] = None
    
    @property
    def current_position_size(self) -> float:
        """Get current position size (convenience property)."""
        if self.current_position is None:
            return 0.0
        return self.current_position.size
    
    @property
    def current_position_entry_price(self) -> Optional[float]:
        """Get current position entry price (convenience property)."""
        if self.current_position is None:
            return None
        return self.current_position.entry_price
    
    @property
    def current_position_side(self) -> Optional[str]:
        """Get current position side (convenience property)."""
        if self.current_position is None:
            return None
        return self.current_position.side.value if self.current_position.side else None
    
    def current_weight(self) -> float:
        """Calculate current position weight (position_value / equity)."""
        if self.account_equity <= 0:
            return 0.0
        mid = self.book.mid_price
        if mid is None:
            return 0.0
        if not self.current_position:
            return 0.0
        position_value = abs(self.current_position.size) * mid
        weight = position_value / self.account_equity
        # Sign based on position side
        if self.current_position.side == "short":
            weight = -weight
        return weight


@dataclass
class ExecutionIntent:
    """
    Intent to execute a trade.
    
    This is the output of the decision pipeline, ready for execution.
    Contains all information needed to place an order with protections.
    """
    
    # Identity
    intent_id: str
    client_order_id: str  # For idempotency and tracking
    
    # Order parameters
    symbol: str
    side: str  # "BUY" or "SELL"
    order_type: str  # "MARKET", "LIMIT", "POST_ONLY"
    qty: float
    price: Optional[float] = None
    
    # Protection orders
    sl_price: Optional[float] = None  # Stop loss price
    tp_price: Optional[float] = None  # Take profit price
    use_bracket: bool = False  # Use bracket/OCO if supported
    
    # Flags
    reduce_only: bool = False
    
    # Metadata
    trace_id: str = ""
    strategy_id: str = ""
    decision_ts: float = 0.0
    risk_mode: str = ""
    
    # Extra data for diagnostics
    extra: Dict[str, Any] = field(default_factory=dict)
    
    # Expiry
    max_age_sec: float = 3.0  # Tight expiry for scalping
    
    def is_entry(self) -> bool:
        """Check if this is an entry order."""
        return not self.reduce_only
    
    def is_exit(self) -> bool:
        """Check if this is an exit order."""
        return self.reduce_only
    
    def has_protection(self) -> bool:
        """Check if this intent has protective orders."""
        return self.sl_price is not None or self.tp_price is not None


# =============================================================================
# Protocol Definitions
# =============================================================================

@runtime_checkable
class FeatureFrameBuilder(Protocol):
    """
    Builds feature frames from decision input.
    
    Responsible for:
    - Extracting features from market data
    - Computing derived features
    - Assessing feature quality
    - Handling missing data
    """
    
    def build(self, decision_input: DecisionInput) -> FeatureFrame:
        """
        Build feature frame from decision input.
        
        Args:
            decision_input: Complete decision input
            
        Returns:
            FeatureFrame with computed features
        """
        ...


@runtime_checkable
class ModelRunner(Protocol):
    """
    Runs model inference on feature frames.
    
    Responsible for:
    - Loading/caching model
    - Running inference
    - Returning raw probabilities
    """
    
    def infer(self, frame: FeatureFrame) -> ModelOutput:
        """
        Run model inference.
        
        Args:
            frame: Feature frame
            
        Returns:
            ModelOutput with raw probability
        """
        ...


@runtime_checkable
class Calibrator(Protocol):
    """
    Calibrates raw model probabilities.
    
    Responsible for:
    - Converting raw scores to meaningful probabilities
    - Ensuring calibration (predicted prob ≈ actual freq)
    """
    
    def calibrate(self, model_out: ModelOutput) -> CalibratedOutput:
        """
        Calibrate model output.
        
        Args:
            model_out: Raw model output
            
        Returns:
            CalibratedOutput with calibrated probability
        """
        ...


@runtime_checkable
class EdgeTransform(Protocol):
    """
    Transforms calibrated probability to edge signal.
    
    Responsible for:
    - Converting p_hat to signal s in [-1, +1]
    - Applying deadband (no-trade zone)
    """
    
    def to_edge(self, p_hat: float) -> EdgeOutput:
        """
        Transform probability to edge signal.
        
        Args:
            p_hat: Calibrated probability
            
        Returns:
            EdgeOutput with signal and deadband status
        """
        ...


@runtime_checkable
class VolatilityEstimator(Protocol):
    """
    Estimates current market volatility.
    
    Responsible for:
    - Computing realized volatility
    - Incorporating spread as volatility proxy
    - Regime detection
    """
    
    def estimate(self, decision_input: DecisionInput) -> VolOutput:
        """
        Estimate volatility from market data.
        
        Args:
            decision_input: Complete decision input
            
        Returns:
            VolOutput with volatility estimate
        """
        ...


@runtime_checkable
class RiskMapper(Protocol):
    """
    Maps signal and volatility to target position weight.
    
    Responsible for:
    - Computing target weight from signal strength
    - Volatility scaling
    - Position limits (clipping)
    - Churn guard (minimum trade size)
    """
    
    def map(
        self,
        *,
        s: float,
        vol_hat: float,
        decision_input: DecisionInput,
    ) -> RiskOutput:
        """
        Map signal to target weight.
        
        Args:
            s: Edge signal in [-1, +1]
            vol_hat: Volatility estimate
            decision_input: Complete decision input
            
        Returns:
            RiskOutput with target weight and flags
        """
        ...


@runtime_checkable
class ExecutionPolicy(Protocol):
    """
    Builds execution intents from risk output.
    
    Responsible for:
    - Deciding order type (market vs limit)
    - Setting protection orders (SL/TP)
    - Splitting large orders
    - Time-in-force selection
    """
    
    def build_intents(
        self,
        *,
        risk_out: RiskOutput,
        decision_input: DecisionInput,
    ) -> List[ExecutionIntent]:
        """
        Build execution intents.
        
        Args:
            risk_out: Risk mapping output
            decision_input: Complete decision input
            
        Returns:
            List of ExecutionIntent (may be empty if no action)
        """
        ...
