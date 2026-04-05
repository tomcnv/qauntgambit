"""
Correlation Guard - Blocks positions in highly correlated assets.

This guard prevents concentrated risk by blocking new positions when the
portfolio already contains positions in correlated assets (same direction).

Example:
- BTC/ETH correlation: ~85%
- If you have a BTC long, trying to open ETH long will be blocked
- Opening ETH short (hedge) is allowed

The correlation matrix is static for now - can be enhanced with dynamic
calculation from historical returns in a future iteration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from quantgambit.observability.alerts import AlertsClient

logger = logging.getLogger(__name__)


@dataclass
class CorrelationGuardConfig:
    """Configuration for correlation guard."""
    
    enabled: bool = True
    max_correlation: float = 0.70  # Block if correlation >= 70%
    # Optional side-specific overrides (fall back to max_correlation when None)
    max_correlation_long: Optional[float] = None
    max_correlation_short: Optional[float] = None
    
    # Optional: symbols to exclude from correlation checks
    excluded_symbols: Set[str] = field(default_factory=set)


# Static correlation matrix for major crypto pairs
# Based on 30-day rolling correlations (typical values)
# TODO: Future enhancement - calculate dynamically from price data
CORRELATION_MATRIX: Dict[Tuple[str, str], float] = {
    # Major pairs - high correlation
    ("BTCUSDT", "ETHUSDT"): 0.85,
    ("BTCUSDT", "SOLUSDT"): 0.75,
    ("BTCUSDT", "BNBUSDT"): 0.70,
    ("BTCUSDT", "XRPUSDT"): 0.68,
    ("BTCUSDT", "ADAUSDT"): 0.72,
    ("BTCUSDT", "AVAXUSDT"): 0.78,
    ("BTCUSDT", "LINKUSDT"): 0.74,
    ("BTCUSDT", "DOTUSDT"): 0.73,
    ("BTCUSDT", "MATICUSDT"): 0.71,
    
    # ETH ecosystem - high correlation with ETH
    ("ETHUSDT", "SOLUSDT"): 0.80,
    ("ETHUSDT", "BNBUSDT"): 0.65,
    ("ETHUSDT", "AVAXUSDT"): 0.82,
    ("ETHUSDT", "LINKUSDT"): 0.76,
    ("ETHUSDT", "DOTUSDT"): 0.75,
    ("ETHUSDT", "MATICUSDT"): 0.78,
    ("ETHUSDT", "OPUSDT"): 0.80,
    ("ETHUSDT", "ARBUSDT"): 0.81,
    
    # L1 competitors - moderate to high correlation
    ("SOLUSDT", "AVAXUSDT"): 0.76,
    ("SOLUSDT", "NEARUSDT"): 0.74,
    ("AVAXUSDT", "NEARUSDT"): 0.72,
    
    # BNB ecosystem
    ("BNBUSDT", "CAKEUSDT"): 0.65,
    
    # Meme coins - moderate correlation with each other
    ("DOGEUSDT", "SHIBUSDT"): 0.68,
    ("DOGEUSDT", "PEPEUSDT"): 0.62,
    ("SHIBUSDT", "PEPEUSDT"): 0.65,
    
    # Legacy pairs
    ("LTCUSDT", "BCHUSDT"): 0.70,
    ("XRPUSDT", "XLMUSDT"): 0.72,
}


@dataclass
class CorrelationCheckResult:
    """Result of a correlation check."""
    
    allowed: bool
    reason: Optional[str] = None
    blocking_symbol: Optional[str] = None
    correlation: Optional[float] = None


class CorrelationGuard:
    """
    Block positions if too correlated with existing holdings.
    
    Rules:
    - Same direction + high correlation = BLOCK
    - Opposite direction = ALLOW (hedge)
    - Unknown pair = ALLOW (assume uncorrelated)
    - Disabled guard = ALLOW all
    
    Example usage:
        guard = CorrelationGuard(config)
        result = await guard.check("BTCUSDT", "long", existing_positions)
        if not result.allowed:
            logger.warning(f"Position blocked: {result.reason}")
    """
    
    def __init__(
        self,
        config: Optional[CorrelationGuardConfig] = None,
        correlations: Optional[Dict[Tuple[str, str], float]] = None,
        alerts_client: Optional["AlertsClient"] = None,
        tenant_id: str = "",
        bot_id: str = "",
    ):
        self._config = config or CorrelationGuardConfig()
        self._correlations = correlations or CORRELATION_MATRIX
        self._alerts = alerts_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        
        # Stats for monitoring
        self._checks_total = 0
        self._blocks_total = 0

    def _threshold_for_side(self, side: str) -> float:
        """Resolve correlation threshold for the incoming side."""
        side_normalized = (side or "").lower()
        if side_normalized == "long" and self._config.max_correlation_long is not None:
            return self._config.max_correlation_long
        if side_normalized == "short" and self._config.max_correlation_short is not None:
            return self._config.max_correlation_short
        return self._config.max_correlation
    
    def get_correlation(self, sym1: str, sym2: str) -> float:
        """
        Get correlation between two symbols.
        
        Returns 1.0 for same symbol, 0.0 for unknown pairs.
        Looks up both orderings in the matrix.
        """
        if sym1 == sym2:
            return 1.0
        
        # Normalize to uppercase
        sym1 = sym1.upper()
        sym2 = sym2.upper()
        
        # Try both orderings
        corr = self._correlations.get((sym1, sym2))
        if corr is not None:
            return corr
        
        corr = self._correlations.get((sym2, sym1))
        if corr is not None:
            return corr
        
        # Unknown pair - assume uncorrelated
        return 0.0
    
    async def check(
        self,
        new_symbol: str,
        new_side: str,  # "long" or "short"
        existing_positions: List[Dict],
    ) -> CorrelationCheckResult:
        """
        Check if new position is allowed.
        
        Args:
            new_symbol: Symbol for the new position
            new_side: Direction ("long" or "short")
            existing_positions: List of existing positions as dicts
                                with keys: symbol, size (positive=long, negative=short)
        
        Returns:
            CorrelationCheckResult with allowed flag and details
        """
        self._checks_total += 1
        
        # Disabled guard allows all
        if not self._config.enabled:
            return CorrelationCheckResult(allowed=True)
        
        # Excluded symbols bypass check
        if new_symbol.upper() in self._config.excluded_symbols:
            return CorrelationCheckResult(allowed=True)
        
        # Normalize side
        new_side_normalized = new_side.lower()
        if new_side_normalized not in {"long", "short"}:
            # Unknown side - allow (shouldn't happen)
            logger.warning(f"Unknown side '{new_side}' for correlation check")
            return CorrelationCheckResult(allowed=True)
        
        # Check against each existing position
        for pos in existing_positions:
            pos_symbol = pos.get("symbol", "")
            pos_size = pos.get("size", 0)
            
            # Skip closed positions
            if pos_size == 0:
                continue

            # Correlation guard is for cross-asset concentration, not "same symbol" stacking.
            # Same-symbol stacking/replacement should be handled by max_positions_per_symbol
            # and other risk/position rules. Avoid self-blocking loops if position state is stale.
            if pos_symbol and pos_symbol.upper() == new_symbol.upper():
                continue
            
            # Skip excluded symbols
            if pos_symbol.upper() in self._config.excluded_symbols:
                continue
            
            # Get correlation
            corr = self.get_correlation(new_symbol, pos_symbol)
            
            # Check threshold
            threshold = self._threshold_for_side(new_side_normalized)
            if corr >= threshold:
                pos_side = "long" if pos_size > 0 else "short"
                
                # Same direction = concentrated risk = BLOCK
                if new_side_normalized == pos_side:
                    self._blocks_total += 1
                    
                    reason = (
                        f"{new_symbol} blocked: {corr:.0%} correlation with "
                        f"existing {pos_symbol} {pos_side}"
                    )
                    
                    logger.info(
                        f"correlation_guard_block",
                        extra={
                            "new_symbol": new_symbol,
                            "new_side": new_side_normalized,
                            "existing_symbol": pos_symbol,
                            "existing_side": pos_side,
                            "correlation": corr,
                        }
                    )
                    
                    # Send alert
                    await self._send_block_alert(
                        new_symbol, pos_symbol, corr
                    )
                    
                    return CorrelationCheckResult(
                        allowed=False,
                        reason=reason,
                        blocking_symbol=pos_symbol,
                        correlation=corr,
                    )
                
                # Opposite direction = hedge = ALLOW
                # (implicitly continues to next position)
        
        # No blocking condition found
        return CorrelationCheckResult(allowed=True)
    
    async def _send_block_alert(
        self,
        blocked_symbol: str,
        existing_symbol: str,
        correlation: float,
    ) -> None:
        """Send Slack/Discord alert for correlation block."""
        if not self._alerts:
            return
        
        try:
            await self._alerts.send(
                alert_type="correlation_block",
                message=(
                    f"⚠️ **Position Blocked by Correlation Guard**\n\n"
                    f"`{blocked_symbol}` blocked due to {correlation:.0%} correlation "
                    f"with existing `{existing_symbol}` position"
                ),
                metadata={
                    "tenant_id": self._tenant_id,
                    "bot_id": self._bot_id,
                    "blocked_symbol": blocked_symbol,
                    "existing_symbol": existing_symbol,
                    "correlation": correlation,
                },
                severity="info",
            )
        except Exception as e:
            logger.warning(f"Failed to send correlation block alert: {e}")
    
    def get_stats(self) -> Dict:
        """Get guard statistics."""
        return {
            "checks_total": self._checks_total,
            "blocks_total": self._blocks_total,
            "block_rate": (
                self._blocks_total / self._checks_total 
                if self._checks_total > 0 
                else 0.0
            ),
        }
    
    def get_known_correlations(self) -> Dict[str, float]:
        """Get all known correlations as a flat dict for API."""
        return {
            f"{s1}_{s2}": corr 
            for (s1, s2), corr in self._correlations.items()
        }
    
    def update_correlation(self, sym1: str, sym2: str, correlation: float) -> None:
        """
        Update correlation for a pair (for future dynamic calculation).
        
        Normalizes to uppercase and stores in canonical order.
        """
        sym1 = sym1.upper()
        sym2 = sym2.upper()
        
        # Store in consistent order (alphabetical)
        if sym1 > sym2:
            sym1, sym2 = sym2, sym1
        
        self._correlations[(sym1, sym2)] = correlation
