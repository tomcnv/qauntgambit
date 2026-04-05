"""
CostDataQualityStage - Validates cost data quality before EVGate.

This stage validates that cost-related data (spread, book, slippage model)
is fresh and available before EVGate performs EV calculations. It does NOT
perform any EV calculations itself - that's EVGate's job.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.6
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class CostDataQualityConfig:
    """Configuration for CostDataQualityStage.
    
    Attributes:
        max_spread_age_ms: Maximum spread data staleness (default 500ms).
        max_book_age_ms: Maximum orderbook staleness (default 500ms).
        require_slippage_model: Whether slippage model availability is required (default False).
        enabled: Whether the stage is enabled (default True).
        
    Requirements: 5.1, 5.2, 5.3
    """
    max_spread_age_ms: int = 500
    max_book_age_ms: int = 500
    require_slippage_model: bool = False
    enabled: bool = True
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.max_spread_age_ms <= 0:
            raise ValueError(
                f"max_spread_age_ms must be positive, got {self.max_spread_age_ms}"
            )
        if self.max_book_age_ms <= 0:
            raise ValueError(
                f"max_book_age_ms must be positive, got {self.max_book_age_ms}"
            )


@dataclass
class CostDataQualityResult:
    """Result of cost data quality validation."""
    
    # Decision
    is_valid: bool
    reject_reason: Optional[str] = None
    
    # Data freshness metrics
    spread_age_ms: float = 0.0
    book_age_ms: float = 0.0
    slippage_model_available: bool = False
    
    # Data availability
    has_spread_data: bool = False
    has_book_data: bool = False
    has_bid_ask: bool = False


class CostDataQualityStage(Stage):
    """
    Pipeline stage that validates cost data quality before EVGate.
    
    This stage ensures that:
    1. Spread data is fresh (not stale)
    2. Orderbook data is fresh (not lagging)
    3. Slippage model is available (if required)
    
    It does NOT perform EV calculations - that's EVGate's responsibility.
    
    Requirements:
    - 5.1: Reject if spread data is stale (> MAX_SPREAD_AGE_MS)
    - 5.2: Reject if book lag is too high (> MAX_BOOK_AGE_MS)
    - 5.3: Reject if slippage model is unavailable (when required)
    - 5.4: Do NOT perform EV calculations
    - 5.6: Run BEFORE EVGate in pipeline
    """
    name = "cost_data_quality"
    
    def __init__(
        self,
        config: Optional[CostDataQualityConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize CostDataQualityStage.
        
        Args:
            config: Configuration for cost data quality. Uses defaults if None.
            telemetry: Optional telemetry for recording blocked signals.
        """
        self.config = config or CostDataQualityConfig()
        self.telemetry = telemetry
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Validate cost data quality and reject if data is stale or unavailable.
        
        Args:
            ctx: Stage context containing market data.
            
        Returns:
            StageResult.REJECT if cost data is invalid,
            StageResult.CONTINUE otherwise.
            
        Requirements: 5.1, 5.2, 5.3, 5.4
        """
        # Skip if disabled
        if not self.config.enabled:
            return StageResult.CONTINUE
        
        signal = ctx.signal
        
        # Skip if no signal to evaluate
        if not signal:
            return StageResult.CONTINUE
        
        # Skip exit signals - this stage is for entry filtering only
        side = getattr(signal, "side", "") or ""
        side = side.lower() if isinstance(side, str) else ""
        if side in ("close_long", "close_short", "close"):
            return StageResult.CONTINUE
        
        # Validate cost data quality
        result = self._validate(ctx)
        
        # Store result in context for downstream stages
        ctx.data["cost_data_quality_result"] = result
        
        if not result.is_valid:
            ctx.rejection_reason = "cost_data_quality"
            ctx.rejection_stage = self.name
            ctx.rejection_detail = {
                "reject_reason": result.reject_reason,
                "spread_age_ms": round(result.spread_age_ms, 1),
                "book_age_ms": round(result.book_age_ms, 1),
                "slippage_model_available": result.slippage_model_available,
                "has_spread_data": result.has_spread_data,
                "has_book_data": result.has_book_data,
                "has_bid_ask": result.has_bid_ask,
            }
            
            # Emit telemetry for blocked signal
            if self.telemetry:
                await self.telemetry.record_blocked(
                    symbol=ctx.symbol,
                    gate_name="cost_data_quality",
                    reason=result.reject_reason or "Cost data quality check failed",
                    metrics={
                        "spread_age_ms": round(result.spread_age_ms, 1),
                        "book_age_ms": round(result.book_age_ms, 1),
                        "slippage_model_available": result.slippage_model_available,
                    },
                )
            
            # Log rejection
            log_warning(
                "cost_data_quality_reject",
                symbol=ctx.symbol,
                reason=result.reject_reason,
                spread_age_ms=round(result.spread_age_ms, 1),
                book_age_ms=round(result.book_age_ms, 1),
            )
            
            return StageResult.REJECT
        
        # Log successful pass for debugging
        log_info(
            "cost_data_quality_pass",
            symbol=ctx.symbol,
            spread_age_ms=round(result.spread_age_ms, 1),
            book_age_ms=round(result.book_age_ms, 1),
        )
        
        return StageResult.CONTINUE
    
    def _validate(self, ctx: StageContext) -> CostDataQualityResult:
        """Validate cost data quality and return result.
        
        Uses the following market_context fields for timestamps:
        - book_cts_ms: Orderbook matching engine timestamp (ms)
        - book_recv_ms: When we received the orderbook update (ms)
        - trade_ts_ms: Trade timestamp from exchange (ms)
        - trade_recv_ms: When we received the trade (ms)
        - feed_staleness: Dict with per-feed staleness in seconds
        
        Falls back to spread_timestamp_ms/book_timestamp_ms for backwards compatibility.
        """
        result = CostDataQualityResult(is_valid=True)
        
        market_context = ctx.data.get("market_context") or {}
        features = ctx.data.get("features") or {}
        
        current_time_ms = time.time() * 1000
        
        # Check spread data availability and freshness (Requirement 5.1)
        # Spread freshness is tied to orderbook freshness since spread = ask - bid
        spread = market_context.get("spread") or features.get("spread")
        result.has_spread_data = spread is not None and spread > 0
        
        # Get book timestamp - prefer book_recv_ms (when we received it), fall back to book_cts_ms
        # Also check legacy field names for backwards compatibility
        book_recv_ms = market_context.get("book_recv_ms")
        book_cts_ms = market_context.get("book_cts_ms")
        spread_ts = market_context.get("spread_timestamp_ms")  # Legacy field

        # Calculate spread age from the freshest orderbook-derived source we have.
        # Spread is derived from the book, so a fresh book should not be penalized
        # just because a legacy spread timestamp is stale.
        spread_age_candidates = []
        if book_recv_ms is not None:
            spread_age_candidates.append(current_time_ms - book_recv_ms)
        if spread_ts is not None:
            spread_age_candidates.append(current_time_ms - spread_ts)
        if book_cts_ms is not None:
            # Use exchange timestamp as fallback (may have clock skew)
            spread_age_candidates.append(current_time_ms - book_cts_ms)
        if not spread_age_candidates:
            # Check feed_staleness dict for orderbook staleness
            feed_staleness = market_context.get("feed_staleness") or {}
            ob_staleness_sec = feed_staleness.get("orderbook")
            if ob_staleness_sec is not None:
                spread_age_candidates.append(ob_staleness_sec * 1000)
        if spread_age_candidates:
            result.spread_age_ms = min(spread_age_candidates)
        
        if result.spread_age_ms > self.config.max_spread_age_ms:
            result.is_valid = False
            result.reject_reason = (
                f"Spread data stale: age={result.spread_age_ms:.0f}ms > "
                f"max={self.config.max_spread_age_ms}ms"
            )
            return result
        
        # Check book data availability and freshness (Requirement 5.2)
        # Use book_recv_ms for staleness check, fall back to legacy fields
        book_ts = market_context.get("book_timestamp_ms") or market_context.get("timestamp_ms")
        book_lag = market_context.get("book_lag_ms") or market_context.get("orderbook_lag_ms")
        feed_staleness = market_context.get("feed_staleness") or {}
        ob_staleness_sec = feed_staleness.get("orderbook")
        
        # Check for bid/ask availability
        best_bid = market_context.get("best_bid") or features.get("best_bid")
        best_ask = market_context.get("best_ask") or features.get("best_ask")
        result.has_bid_ask = (
            best_bid is not None and best_bid > 0 and
            best_ask is not None and best_ask > 0
        )
        result.has_book_data = result.has_bid_ask
        
        # Calculate book age - prefer explicit lag, then recv timestamp, then legacy fields
        if book_lag is not None:
            result.book_age_ms = book_lag
        elif ob_staleness_sec is not None:
            result.book_age_ms = ob_staleness_sec * 1000
        elif book_recv_ms is not None:
            result.book_age_ms = current_time_ms - book_recv_ms
        elif book_ts is not None:
            result.book_age_ms = current_time_ms - book_ts
        elif book_cts_ms is not None:
            result.book_age_ms = current_time_ms - book_cts_ms
        
        if result.book_age_ms > self.config.max_book_age_ms:
            result.is_valid = False
            result.reject_reason = (
                f"Book data stale: age={result.book_age_ms:.0f}ms > "
                f"max={self.config.max_book_age_ms}ms"
            )
            return result
        
        # Check slippage model availability (Requirement 5.3)
        slippage_model = market_context.get("slippage_model_available")
        result.slippage_model_available = slippage_model is True
        
        if self.config.require_slippage_model and not result.slippage_model_available:
            result.is_valid = False
            result.reject_reason = "Slippage model unavailable"
            return result
        
        return result
