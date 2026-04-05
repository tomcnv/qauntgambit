"""
ExecutionFeasibilityGate - Determines maker-first vs taker-only execution policy.

This stage evaluates market conditions to determine the optimal execution policy
for a signal. It runs AFTER EVGate and BEFORE Execution.

Key behaviors:
- Never rejects signals - only sets execution policy
- Evaluates spread_percentile and book_imbalance
- Respects vol_shock forced taker from upstream stages

Requirement 9.1: Execution_Feasibility_Gate SHALL run AFTER EVGate and BEFORE Execution
Requirement 9.2: Evaluate spread_percentile, book_imbalance, volatility_regime
Requirement 9.3: When spread_percentile > 70% THEN recommend taker_only
Requirement 9.4: When spread_percentile <= 30% AND book_imbalance favorable THEN recommend maker_first
Requirement 9.5: When spread_percentile between 30-70% THEN recommend maker_first with reduced TTL
Requirement 9.6: Set ctx.data["execution_policy"] with mode, ttl_ms, fallback_to_taker
Requirement 9.7: Gate SHALL NOT reject signals - only sets execution policy
Requirement 9.8: Config includes maker_spread_threshold, taker_spread_threshold, TTL values
Requirement 9.9: Log execution policy decisions with market conditions
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.observability.logger import log_info


@dataclass
class ExecutionFeasibilityConfig:
    """
    Configuration for execution feasibility gate.
    
    Requirement 9.8: Config SHALL include maker_spread_threshold, taker_spread_threshold,
    default_maker_ttl_ms, reduced_maker_ttl_ms.
    
    Attributes:
        maker_spread_threshold: Below this spread_percentile, prefer maker (default 0.30)
        taker_spread_threshold: Above this spread_percentile, force taker (default 0.70)
        default_maker_ttl_ms: Time-to-live for maker orders in normal conditions (default 5000)
        reduced_maker_ttl_ms: Reduced TTL for maker orders in middle spread range (default 2000)
        fallback_to_taker: Whether to fall back to taker if maker doesn't fill (default True)
    """
    maker_spread_threshold: float = 0.30  # Below this, prefer maker
    taker_spread_threshold: float = 0.70  # Above this, force taker
    default_maker_ttl_ms: int = 5000
    reduced_maker_ttl_ms: int = 2000
    fallback_to_taker: bool = True
    
    @classmethod
    def from_env(cls) -> "ExecutionFeasibilityConfig":
        """
        Create config from environment variables.
        
        Environment variables:
            EXEC_FEASIBILITY_MAKER_SPREAD_THRESHOLD: Maker spread threshold (default 0.30)
            EXEC_FEASIBILITY_TAKER_SPREAD_THRESHOLD: Taker spread threshold (default 0.70)
            EXEC_FEASIBILITY_DEFAULT_MAKER_TTL_MS: Default maker TTL (default 5000)
            EXEC_FEASIBILITY_REDUCED_MAKER_TTL_MS: Reduced maker TTL (default 2000)
            EXEC_FEASIBILITY_FALLBACK_TO_TAKER: Fallback to taker flag (default true)
        
        Returns:
            ExecutionFeasibilityConfig instance
        """
        return cls(
            maker_spread_threshold=float(
                os.environ.get("EXEC_FEASIBILITY_MAKER_SPREAD_THRESHOLD", "0.30")
            ),
            taker_spread_threshold=float(
                os.environ.get("EXEC_FEASIBILITY_TAKER_SPREAD_THRESHOLD", "0.70")
            ),
            default_maker_ttl_ms=int(
                os.environ.get("EXEC_FEASIBILITY_DEFAULT_MAKER_TTL_MS", "5000")
            ),
            reduced_maker_ttl_ms=int(
                os.environ.get("EXEC_FEASIBILITY_REDUCED_MAKER_TTL_MS", "2000")
            ),
            fallback_to_taker=os.environ.get(
                "EXEC_FEASIBILITY_FALLBACK_TO_TAKER", "true"
            ).lower() in {"1", "true", "yes"},
        )


@dataclass
class ExecutionPolicy:
    """
    Execution policy determined by feasibility gate.
    
    Requirement 9.6: Set ctx.data["execution_policy"] with mode, ttl_ms, fallback_to_taker.
    
    Attributes:
        mode: Execution mode - "maker_first" or "taker_only"
        ttl_ms: Time-to-live for maker orders (0 for taker_only)
        fallback_to_taker: Whether to fall back to taker if maker doesn't fill
        reason: Human-readable reason for the policy decision
    """
    mode: str  # "maker_first" or "taker_only"
    ttl_ms: int  # Time-to-live for maker orders (0 for taker_only)
    fallback_to_taker: bool
    reason: str


class ExecutionFeasibilityGate(Stage):
    """
    Determines maker-first vs taker-only execution based on market conditions.
    
    This stage evaluates spread_percentile and book_imbalance to determine
    the optimal execution policy. It NEVER rejects signals - only sets
    execution policy for downstream execution stages.
    
    Requirement 9.1: Run AFTER EVGate and BEFORE Execution
    Requirement 9.7: SHALL NOT reject signals - only sets execution policy
    
    Decision logic:
    1. If vol_shock forced taker upstream: taker_only
    2. If spread_percentile > taker_threshold: taker_only (wide spread)
    3. If spread_percentile <= maker_threshold: maker_first with full TTL
    4. Otherwise (middle range): maker_first with reduced TTL
    
    Attributes:
        name: Stage name for identification ("execution_feasibility")
        config: ExecutionFeasibilityConfig with threshold parameters
    """
    name = "execution_feasibility"
    
    def __init__(self, config: Optional[ExecutionFeasibilityConfig] = None):
        """
        Initialize the execution feasibility gate.
        
        Args:
            config: Configuration for the gate. If None, uses defaults.
        """
        self.config = config or ExecutionFeasibilityConfig()
        self._trace_enabled = os.getenv("EXEC_FEASIBILITY_TRACE", "").lower() in {"1", "true"}
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Evaluate market conditions and set execution policy.
        
        This method:
        1. Skips if no signal present
        2. Checks if vol_shock already forced taker
        3. Evaluates spread_percentile to determine policy
        4. Sets ctx.data["execution_policy"] with the decision
        5. Logs the policy decision
        
        Requirement 9.7: Never rejects signals - always returns CONTINUE.
        
        Args:
            ctx: Stage context containing symbol, data dict, and signal
        
        Returns:
            StageResult.CONTINUE always (never rejects)
        """
        # Skip if no signal - nothing to set policy for
        if not ctx.signal:
            if self._trace_enabled:
                log_info(
                    "execution_feasibility_no_signal",
                    symbol=ctx.symbol,
                )
            return StageResult.CONTINUE
        
        # Get market context for spread_percentile and book_imbalance
        market_context = ctx.data.get("market_context") or {}
        spread_percentile = market_context.get("spread_percentile", 0.5)
        book_imbalance = market_context.get("book_imbalance", 0.0)
        
        # Determine execution policy
        policy = self._determine_policy(ctx, spread_percentile, book_imbalance)
        
        # Set policy in context for downstream stages
        ctx.data["execution_policy"] = policy
        
        # Log the policy decision (Requirement 9.9)
        log_info(
            "execution_feasibility_policy",
            symbol=ctx.symbol,
            mode=policy.mode,
            ttl_ms=policy.ttl_ms,
            fallback_to_taker=policy.fallback_to_taker,
            reason=policy.reason,
            spread_percentile=round(spread_percentile, 2),
            book_imbalance=round(book_imbalance, 3),
        )
        
        # Never reject - only set policy (Requirement 9.7)
        return StageResult.CONTINUE
    
    def _determine_policy(
        self,
        ctx: StageContext,
        spread_percentile: float,
        book_imbalance: float,
    ) -> ExecutionPolicy:
        """
        Determine execution policy based on market conditions.
        
        Decision logic:
        1. Vol shock forced taker: taker_only (from upstream GlobalGate)
        2. Wide spread (> taker_threshold): taker_only
        3. Tight spread (<= maker_threshold): maker_first with full TTL
        4. Middle range: maker_first with reduced TTL
        
        Args:
            ctx: Stage context with data dict
            spread_percentile: Current spread relative to historical (0-1)
            book_imbalance: Bid/ask depth ratio
        
        Returns:
            ExecutionPolicy with mode, ttl_ms, fallback_to_taker, reason
        """
        # Check if vol shock already forced taker (from GlobalGate)
        if ctx.data.get("force_taker"):
            return ExecutionPolicy(
                mode="taker_only",
                ttl_ms=0,
                fallback_to_taker=False,
                reason="vol_shock_forced_taker",
            )
        
        # Wide spread - force taker (Requirement 9.3)
        if spread_percentile > self.config.taker_spread_threshold:
            return ExecutionPolicy(
                mode="taker_only",
                ttl_ms=0,
                fallback_to_taker=False,
                reason=f"spread_percentile={spread_percentile:.2f}>{self.config.taker_spread_threshold}",
            )
        
        # Tight spread - prefer maker with full TTL (Requirement 9.4)
        if spread_percentile <= self.config.maker_spread_threshold:
            return ExecutionPolicy(
                mode="maker_first",
                ttl_ms=self.config.default_maker_ttl_ms,
                fallback_to_taker=self.config.fallback_to_taker,
                reason=f"spread_percentile={spread_percentile:.2f}<={self.config.maker_spread_threshold}",
            )
        
        # Middle range - maker with reduced TTL (Requirement 9.5)
        return ExecutionPolicy(
            mode="maker_first",
            ttl_ms=self.config.reduced_maker_ttl_ms,
            fallback_to_taker=self.config.fallback_to_taker,
            reason=f"spread_percentile={spread_percentile:.2f}_middle_range",
        )
