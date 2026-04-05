"""StageRejectionDiagnostics - Tracks rejections by pipeline stage.

This module provides utilities for tracking and reporting which pipeline
stages rejected signals during backtesting.

Requirements: 4.1, 4.2, 4.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StageRejectionDiagnostics:
    """Tracks rejections by pipeline stage.
    
    Provides detailed breakdown of which stages rejected signals and why,
    enabling users to understand why trades were or weren't taken.
    
    Requirements:
    - 4.1: Record rejection reason and stage name
    - 4.2: Include stage-level rejection counts in execution_diagnostics
    - 4.3: Include breakdown by stage
    """
    
    # Total rejections
    total_rejections: int = 0
    
    # Rejections by stage name
    by_stage: Dict[str, int] = field(default_factory=dict)
    
    # Rejections by reason
    by_reason: Dict[str, int] = field(default_factory=dict)
    
    # Detailed rejection records (limited to last N for memory)
    recent_rejections: List[Dict[str, Any]] = field(default_factory=list)
    max_recent_rejections: int = 100
    
    # Known stage counters for quick access
    data_readiness: int = 0
    global_gate: int = 0
    strategy_trend_alignment: int = 0
    ev_gate: int = 0
    fee_aware_entry: int = 0
    session_filter: int = 0
    candidate_veto: int = 0
    cooldown: int = 0
    confidence_gate: int = 0
    risk_stage: int = 0
    
    def record_rejection(
        self,
        stage_name: str,
        reason: Optional[str] = None,
        symbol: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Record a rejection from a pipeline stage.
        
        Args:
            stage_name: Name of the stage that rejected
            reason: Reason for rejection
            symbol: Trading symbol
            details: Additional details about the rejection
        """
        self.total_rejections += 1
        
        # Update by_stage counter
        self.by_stage[stage_name] = self.by_stage.get(stage_name, 0) + 1
        
        # Update by_reason counter
        if reason:
            self.by_reason[reason] = self.by_reason.get(reason, 0) + 1
        
        # Update specific stage counter if known
        stage_attr = stage_name.replace("-", "_").lower()
        if hasattr(self, stage_attr):
            setattr(self, stage_attr, getattr(self, stage_attr) + 1)
        
        # Record detailed rejection (limited)
        if len(self.recent_rejections) < self.max_recent_rejections:
            self.recent_rejections.append({
                "stage": stage_name,
                "reason": reason,
                "symbol": symbol,
                "details": details,
            })
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of rejections for execution_diagnostics.
        
        Returns dict suitable for inclusion in backtest results.
        """
        return {
            "total_rejections": self.total_rejections,
            "by_stage": dict(self.by_stage),
            "by_reason": dict(self.by_reason),
            # Include known stage counters
            "stage_breakdown": {
                "data_readiness": self.data_readiness,
                "global_gate": self.global_gate,
                "strategy_trend_alignment": self.strategy_trend_alignment,
                "ev_gate": self.ev_gate,
                "fee_aware_entry": self.fee_aware_entry,
                "session_filter": self.session_filter,
                "candidate_veto": self.candidate_veto,
                "cooldown": self.cooldown,
                "confidence_gate": self.confidence_gate,
                "risk_stage": self.risk_stage,
            },
        }
    
    def get_top_rejection_stages(self, n: int = 5) -> List[tuple]:
        """Get top N stages by rejection count.
        
        Returns list of (stage_name, count) tuples sorted by count descending.
        """
        sorted_stages = sorted(
            self.by_stage.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_stages[:n]
    
    def get_top_rejection_reasons(self, n: int = 5) -> List[tuple]:
        """Get top N reasons by rejection count.
        
        Returns list of (reason, count) tuples sorted by count descending.
        """
        sorted_reasons = sorted(
            self.by_reason.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_reasons[:n]
    
    def get_human_readable_summary(self) -> str:
        """Get human-readable summary of rejections.
        
        Returns a formatted string suitable for logging or display.
        """
        if self.total_rejections == 0:
            return "No signals were rejected by pipeline stages."
        
        lines = [f"Total rejections: {self.total_rejections}"]
        
        # Top stages
        top_stages = self.get_top_rejection_stages(5)
        if top_stages:
            lines.append("\nTop rejection stages:")
            for stage, count in top_stages:
                pct = (count / self.total_rejections) * 100
                lines.append(f"  - {stage}: {count} ({pct:.1f}%)")
        
        # Top reasons
        top_reasons = self.get_top_rejection_reasons(5)
        if top_reasons:
            lines.append("\nTop rejection reasons:")
            for reason, count in top_reasons:
                pct = (count / self.total_rejections) * 100
                lines.append(f"  - {reason}: {count} ({pct:.1f}%)")
        
        return "\n".join(lines)
    
    def merge(self, other: "StageRejectionDiagnostics"):
        """Merge another diagnostics instance into this one.
        
        Useful for combining results from multiple backtest runs.
        """
        self.total_rejections += other.total_rejections
        
        for stage, count in other.by_stage.items():
            self.by_stage[stage] = self.by_stage.get(stage, 0) + count
        
        for reason, count in other.by_reason.items():
            self.by_reason[reason] = self.by_reason.get(reason, 0) + count
        
        # Merge known stage counters
        self.data_readiness += other.data_readiness
        self.global_gate += other.global_gate
        self.strategy_trend_alignment += other.strategy_trend_alignment
        self.ev_gate += other.ev_gate
        self.fee_aware_entry += other.fee_aware_entry
        self.session_filter += other.session_filter
        self.candidate_veto += other.candidate_veto
        self.cooldown += other.cooldown
        self.confidence_gate += other.confidence_gate
        self.risk_stage += other.risk_stage
    
    def reset(self):
        """Reset all counters."""
        self.total_rejections = 0
        self.by_stage = {}
        self.by_reason = {}
        self.recent_rejections = []
        self.data_readiness = 0
        self.global_gate = 0
        self.strategy_trend_alignment = 0
        self.ev_gate = 0
        self.fee_aware_entry = 0
        self.session_filter = 0
        self.candidate_veto = 0
        self.cooldown = 0
        self.confidence_gate = 0
        self.risk_stage = 0


def create_diagnostics_from_context(ctx) -> Optional[Dict[str, Any]]:
    """Extract rejection info from a StageContext.
    
    Helper function to extract rejection information from a context
    after pipeline processing.
    
    Args:
        ctx: StageContext after pipeline processing
        
    Returns:
        Dict with rejection info, or None if not rejected
    """
    if not ctx:
        return None
    
    if not ctx.rejection_reason:
        return None
    
    return {
        "stage": getattr(ctx, "rejection_stage", "unknown"),
        "reason": ctx.rejection_reason,
        "detail": getattr(ctx, "rejection_detail", None),
    }
