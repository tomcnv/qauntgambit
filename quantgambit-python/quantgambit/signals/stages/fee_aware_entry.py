"""
FeeAwareEntryStage - Rejects signals where expected profit doesn't exceed fees.

DEPRECATED: This stage is superseded by EVGate which performs complete EV
calculations including cost modeling. When EVGate is enabled, this stage
becomes a pass-through. Use CostDataQualityStage for data freshness checks.

This stage is part of the loss prevention system that filters out trades
where transaction fees would eat all the profit (fee traps). It calculates
the expected edge and compares it against round-trip fees.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult, signal_to_dict
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class FeeAwareEntryConfig:
    """Configuration for FeeAwareEntryStage.
    
    DEPRECATED: This stage is superseded by EVGate. Use CostDataQualityStage
    for data freshness checks and EVGate for EV-based entry filtering.
    
    Attributes:
        fee_rate_bps: Taker fee rate in basis points (default 5.5 for Bybit).
        min_edge_multiplier: Edge must be this multiple of fees (default 2.0).
        slippage_bps: Expected slippage in basis points (default 2.0).
        skip_when_ev_gate_enabled: Skip this stage when EVGate is enabled (default True).
        
    Requirements: 4.5
    """
    fee_rate_bps: float = 5.5  # 0.055% Bybit taker fee
    min_edge_multiplier: float = 2.0  # Edge must be 2x fees
    slippage_bps: float = 2.0  # Expected slippage
    skip_when_ev_gate_enabled: bool = True  # Skip when EVGate handles EV calculations
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.fee_rate_bps < 0:
            raise ValueError(
                f"fee_rate_bps must be non-negative, got {self.fee_rate_bps}"
            )
        if self.min_edge_multiplier < 0:
            raise ValueError(
                f"min_edge_multiplier must be non-negative, got {self.min_edge_multiplier}"
            )
        if self.slippage_bps < 0:
            raise ValueError(
                f"slippage_bps must be non-negative, got {self.slippage_bps}"
            )


class FeeAwareEntryStage(Stage):
    """
    Pipeline stage that rejects signals where expected profit doesn't exceed fees.
    
    DEPRECATED: This stage is superseded by EVGate which performs complete EV
    calculations including cost modeling. When EVGate is enabled (detected by
    presence of ev_gate_result in context), this stage becomes a pass-through.
    
    Use CostDataQualityStage for data freshness checks before EVGate.
    
    This stage calculates the expected edge from the signal and compares it
    against the round-trip fees (entry + exit + slippage). Signals are rejected
    if the expected profit is less than min_edge_multiplier times the fees.
    
    Requirements:
    - 4.1: Calculate expected edge in dollars
    - 4.2: Calculate total round-trip fees
    - 4.3: Reject if expected edge < 2x round-trip fees
    - 4.4: Emit telemetry with edge, fee, and ratio
    - 4.6: Use proposed position size in dollars
    - 4.7: Display "Fee trap: edge $X < fees $Y"
    """
    name = "fee_aware_entry"
    
    def __init__(
        self,
        config: Optional[FeeAwareEntryConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize FeeAwareEntryStage.
        
        Args:
            config: Configuration for fee-aware entry. Uses defaults if None.
            telemetry: Optional telemetry for recording blocked signals.
        
        .. deprecated::
            This stage is superseded by EVGate. Use CostDataQualityStage for
            data freshness checks and EVGate for EV-based entry filtering.
        """
        self.config = config or FeeAwareEntryConfig()
        self.telemetry = telemetry
        
        # Emit deprecation warning
        warnings.warn(
            "FeeAwareEntryStage is deprecated. Use EVGate for EV-based entry "
            "filtering and CostDataQualityStage for data freshness checks.",
            DeprecationWarning,
            stacklevel=2,
        )
    
    def _calculate_size_usd(self, signal: dict, ctx: StageContext) -> float:
        """Calculate position size in USD from signal or context.
        
        Args:
            signal: Signal dictionary with size information.
            ctx: Stage context with market data.
            
        Returns:
            Position size in USD.
        """
        # Try to get size_usd directly from signal
        if "size_usd" in signal and signal["size_usd"]:
            return float(signal["size_usd"])
        
        # Try to calculate from size and price
        size = signal.get("size") or signal.get("quantity")
        if size:
            price = ctx.data.get("market_context", {}).get("price")
            if not price:
                features = ctx.data.get("features") or {}
                price = features.get("price")
            if price:
                return float(size) * float(price)
        
        # Fallback: try to get from risk parameters
        risk_params = ctx.data.get("risk_params") or {}
        return float(risk_params.get("position_size_usd", 0.0))
    
    def _estimate_edge(self, signal: dict, ctx: StageContext) -> float:
        """Estimate expected edge percentage from signal or market context.
        
        Args:
            signal: Signal dictionary with edge information.
            ctx: Stage context with market data.
            
        Returns:
            Expected edge as a percentage (e.g., 0.5 for 0.5%).
        """
        # Try to get expected_edge_pct directly from signal
        if "expected_edge_pct" in signal and signal["expected_edge_pct"] is not None:
            return float(signal["expected_edge_pct"])
        
        # Try to estimate from distance to target
        target_price = signal.get("target_price") or signal.get("take_profit")
        entry_price = signal.get("entry_price")
        
        if not entry_price:
            market_context = ctx.data.get("market_context") or {}
            entry_price = market_context.get("price")
            if not entry_price:
                features = ctx.data.get("features") or {}
                entry_price = features.get("price")
        
        if target_price and entry_price and entry_price > 0:
            side = signal.get("side", "").lower()
            if side == "long":
                edge_pct = (float(target_price) - float(entry_price)) / float(entry_price) * 100
            elif side == "short":
                edge_pct = (float(entry_price) - float(target_price)) / float(entry_price) * 100
            else:
                edge_pct = abs(float(target_price) - float(entry_price)) / float(entry_price) * 100
            return max(0.0, edge_pct)
        
        # Try to get from signal metadata
        if "edge_bps" in signal:
            return float(signal["edge_bps"]) / 100.0  # Convert bps to percentage
        
        # Default: no edge estimate available
        return 0.0
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Evaluate signal profitability and reject if fees exceed expected profit.
        
        Args:
            ctx: Stage context containing signal and market data.
            
        Returns:
            StageResult.REJECT if expected profit < min_edge_multiplier × fees,
            StageResult.CONTINUE otherwise.
            
        Requirements: 4.1, 4.2, 4.3, 4.6
        """
        signal = signal_to_dict(ctx.signal)
        
        # Skip if no signal to evaluate
        if not signal:
            return StageResult.CONTINUE
        
        # Skip exit signals - this stage is for entry filtering only
        side = signal.get("side", "").lower()
        if side in ("close_long", "close_short", "close"):
            return StageResult.CONTINUE
        
        # Skip when EVGate is enabled (EVGate handles EV calculations)
        # Detected by presence of ev_gate_result in context
        if self.config.skip_when_ev_gate_enabled:
            ev_gate_result = ctx.data.get("ev_gate_result")
            if ev_gate_result is not None:
                log_info(
                    "fee_aware_entry_skipped",
                    symbol=ctx.symbol,
                    reason="EVGate enabled - skipping deprecated FeeAwareEntry",
                )
                return StageResult.CONTINUE
        
        # Calculate position size in USD (Requirement 4.6)
        position_size_usd = self._calculate_size_usd(signal, ctx)
        
        if position_size_usd <= 0:
            log_warning(
                "fee_aware_entry_no_size",
                symbol=ctx.symbol,
                reason="Could not determine position size",
            )
            return StageResult.CONTINUE
        
        # Calculate expected edge percentage (Requirement 4.1)
        expected_edge_pct = self._estimate_edge(signal, ctx)
        
        # Calculate round-trip fees (Requirement 4.2)
        # Round-trip = entry fee + exit fee + slippage
        round_trip_fee_bps = self.config.fee_rate_bps * 2 + self.config.slippage_bps
        round_trip_fee_usd = position_size_usd * (round_trip_fee_bps / 10000)
        
        # Calculate expected profit in USD
        expected_profit_usd = position_size_usd * (expected_edge_pct / 100)
        
        # Calculate minimum required profit (Requirement 4.3)
        min_required_profit = round_trip_fee_usd * self.config.min_edge_multiplier
        
        # Calculate ratio for telemetry
        ratio = expected_profit_usd / round_trip_fee_usd if round_trip_fee_usd > 0 else 0.0
        
        # Check if edge exceeds fees by required margin
        if expected_profit_usd < min_required_profit:
            ctx.rejection_reason = "fee_trap"
            ctx.rejection_stage = self.name
            ctx.rejection_detail = {
                "expected_profit_usd": round(expected_profit_usd, 4),
                "round_trip_fee_usd": round(round_trip_fee_usd, 4),
                "min_required_profit": round(min_required_profit, 4),
                "ratio": round(ratio, 2),
                "position_size_usd": round(position_size_usd, 2),
                "expected_edge_pct": round(expected_edge_pct, 4),
                "fee_rate_bps": self.config.fee_rate_bps,
                "slippage_bps": self.config.slippage_bps,
                "min_edge_multiplier": self.config.min_edge_multiplier,
            }
            
            # Emit telemetry for blocked signal (Requirement 4.4)
            if self.telemetry:
                await self.telemetry.record_blocked(
                    symbol=ctx.symbol,
                    gate_name="fee_trap",
                    reason=f"Fee trap: edge ${expected_profit_usd:.2f} < fees ${round_trip_fee_usd:.2f}",
                    metrics={
                        "expected_profit_usd": round(expected_profit_usd, 4),
                        "round_trip_fee_usd": round(round_trip_fee_usd, 4),
                        "ratio": round(ratio, 2),
                        "position_size_usd": round(position_size_usd, 2),
                        "expected_edge_pct": round(expected_edge_pct, 4),
                    },
                )
            
            # Log rejection (Requirement 4.7)
            log_warning(
                "fee_aware_entry_reject",
                symbol=ctx.symbol,
                expected_profit_usd=round(expected_profit_usd, 4),
                round_trip_fee_usd=round(round_trip_fee_usd, 4),
                ratio=round(ratio, 2),
                detail=f"Fee trap: edge ${expected_profit_usd:.2f} < fees ${round_trip_fee_usd:.2f}",
            )
            
            return StageResult.REJECT
        
        # Log successful pass for debugging
        log_info(
            "fee_aware_entry_pass",
            symbol=ctx.symbol,
            expected_profit_usd=round(expected_profit_usd, 4),
            round_trip_fee_usd=round(round_trip_fee_usd, 4),
            ratio=round(ratio, 2),
        )
        
        return StageResult.CONTINUE
