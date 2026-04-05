"""
ArbitrationStage - Select best candidate when multiple strategies emit signals.

This stage collects CandidateSignal objects from ctx.data["candidates"] and
uses CandidateArbitrator to select the best one based on setup_score and
strategy priority.

Requirement 4.5: When multiple strategies emit candidates for the same symbol,
the Candidate_Arbitrator SHALL select the best candidate based on:
- setup_score (higher is better)
- expected_ev (if available)
- strategy_priority (configurable per strategy)

Requirement 8.1: Pipeline SHALL execute stages in order including Arbitration
after Strategy and before Confirmation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import CandidateSignal, CandidateArbitrator
from quantgambit.observability.logger import log_info, log_warning


@dataclass
class ArbitrationConfig:
    """
    Configuration for ArbitrationStage.
    
    Attributes:
        strategy_priorities: Dict mapping strategy_id to priority (higher is better)
        log_all_candidates: Whether to log all candidates, not just the selected one
    """
    strategy_priorities: Dict[str, int] = None
    log_all_candidates: bool = False
    
    def __post_init__(self):
        if self.strategy_priorities is None:
            self.strategy_priorities = {}


class ArbitrationStage(Stage):
    """
    Select best candidate when multiple strategies emit signals.
    
    This stage:
    1. Collects candidates from ctx.data["candidates"]
    2. Uses CandidateArbitrator to select the best candidate
    3. Sets ctx.data["candidate_signal"] with the selected candidate
    4. Always returns CONTINUE (never blocks the pipeline)
    
    If no candidates are available, the stage sets candidate_signal to None
    and continues. Downstream stages (ConfirmationStage) should handle this.
    
    Requirement 4.5: Candidate arbitration based on setup_score and priority
    Requirement 8.1: Stage ordering - Arbitration after Strategy, before Confirmation
    
    Attributes:
        name: Stage name for identification ("arbitration")
        config: ArbitrationConfig with strategy priorities
        _arbitrator: CandidateArbitrator instance
    """
    name = "arbitration"
    
    def __init__(
        self,
        config: Optional[ArbitrationConfig] = None,
    ):
        """
        Initialize the arbitration stage.
        
        Args:
            config: Configuration with strategy priorities. If None, uses defaults.
        """
        self.config = config or ArbitrationConfig()
        self._arbitrator = CandidateArbitrator(
            strategy_priorities=self.config.strategy_priorities
        )
        self._trace_enabled = os.getenv("ARBITRATION_TRACE", "").lower() in {"1", "true"}
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Select best candidate from available candidates.
        
        This method:
        1. Gets candidates from ctx.data["candidates"]
        2. Uses arbitrator to select best candidate
        3. Sets ctx.data["candidate_signal"] with selected candidate
        4. Returns CONTINUE (never blocks pipeline)
        
        Args:
            ctx: Stage context containing symbol, data dict, and other state
        
        Returns:
            StageResult.CONTINUE always - this stage never blocks the pipeline
        """
        symbol = ctx.symbol
        
        # Get candidates from context
        # Candidates can be a list or a single CandidateSignal
        candidates_data = ctx.data.get("candidates")
        
        # Normalize to list
        if candidates_data is None:
            candidates = []
        elif isinstance(candidates_data, list):
            candidates = candidates_data
        elif isinstance(candidates_data, CandidateSignal):
            candidates = [candidates_data]
        else:
            # Unknown type - try to use as-is
            candidates = [candidates_data] if candidates_data else []
        
        # Filter to only CandidateSignal instances
        valid_candidates: List[CandidateSignal] = [
            c for c in candidates if isinstance(c, CandidateSignal)
        ]
        
        # Log if we have candidates
        if self._trace_enabled or self.config.log_all_candidates:
            if valid_candidates:
                log_info(
                    "arbitration_candidates_received",
                    symbol=symbol,
                    candidate_count=len(valid_candidates),
                    strategies=[c.strategy_id for c in valid_candidates],
                    scores=[round(c.setup_score, 3) for c in valid_candidates],
                )
        
        # No candidates - set candidate_signal to None and continue
        if not valid_candidates:
            ctx.data["candidate_signal"] = None
            if self._trace_enabled:
                log_info(
                    "arbitration_no_candidates",
                    symbol=symbol,
                )
            return StageResult.CONTINUE
        
        # Select best candidate
        selected = self._arbitrator.select_best(valid_candidates)
        
        # Set selected candidate in context
        ctx.data["candidate_signal"] = selected
        
        # Log selection
        if selected:
            log_info(
                "arbitration_selected",
                symbol=symbol,
                strategy_id=selected.strategy_id,
                setup_score=round(selected.setup_score, 3),
                side=selected.side,
                entry_price=round(selected.entry_price, 2),
                candidate_count=len(valid_candidates),
            )
        
        return StageResult.CONTINUE
    
    def set_priority(self, strategy_id: str, priority: int) -> None:
        """
        Set priority for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            priority: Priority value (higher is better)
        """
        self._arbitrator.set_priority(strategy_id, priority)
        self.config.strategy_priorities[strategy_id] = priority
    
    def get_priority(self, strategy_id: str) -> int:
        """
        Get priority for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            Priority value, or 0 if not set
        """
        return self._arbitrator.get_priority(strategy_id)
