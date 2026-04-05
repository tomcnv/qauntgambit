"""
SessionFilterStage - Filters signals based on trading session and strategy preferences.

This stage is part of the loss prevention system that ensures strategies only
trade during their optimal sessions and applies session-based risk adjustments.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
import time

from quantgambit.signals.pipeline import Stage, StageContext, StageResult, signal_to_dict
from quantgambit.signals.stages.session_risk import (
    classify_session_risk,
    get_utc_hour_from_timestamp,
    is_strategy_allowed_in_session,
    is_strategy_preferred_for_session_risk,
    SessionRiskResult,
)
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class SessionFilterConfig:
    """Configuration for SessionFilterStage.
    
    Attributes:
        enforce_session_preferences: If True, reject signals from strategies
                                    not preferred for the current session.
        enforce_strategy_sessions: If True, reject signals from strategies
                                  not allowed in the current session.
        apply_position_size_multiplier: If True, apply session-based position
                                       size multiplier to signals.
    """
    enforce_session_preferences: bool = True
    enforce_strategy_sessions: bool = True
    apply_position_size_multiplier: bool = True
    enabled: bool = True


class SessionFilterStage(Stage):
    """
    Pipeline stage that filters signals based on trading session.
    
    This stage evaluates the current trading session and applies session-based
    risk adjustments. It can reject signals from strategies that are not
    appropriate for the current session.
    
    Requirements:
    - 5.1: Overnight session sets risk_mode to "off" (no trading)
    - 5.2: Asia low volatility prefers trend following
    - 5.3: US session 0-6 UTC reduces position sizes by 50%
    - 5.4: Strategies can define preferred_sessions
    - 5.5: Check session match before signal generation
    """
    name = "session_filter"
    
    def __init__(
        self,
        config: Optional[SessionFilterConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize SessionFilterStage.
        
        Args:
            config: Configuration for the session filter. Uses defaults if None.
            telemetry: Optional telemetry for recording blocked signals.
        """
        self.config = config or SessionFilterConfig()
        self.telemetry = telemetry
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Evaluate session compatibility and filter signals accordingly.
        
        Args:
            ctx: Stage context containing signal and market data.
            
        Returns:
            StageResult.REJECT if session mismatch detected,
            StageResult.CONTINUE otherwise.
            
        Requirements: 5.1, 5.4, 5.5
        """
        # Get session and volatility from market context
        market_context = ctx.data.get("market_context", {}) if ctx.data else {}
        if not self.config.enabled:
            session = market_context.get("session", "unknown")
            ctx.data["session_risk"] = SessionRiskResult(
                risk_mode="normal",
                position_size_multiplier=1.0,
                preferred_strategies=None,
                session=session,
                reason="session_filter_disabled",
            )
            log_info(
                "session_filter_disabled",
                symbol=ctx.symbol,
                session=session,
            )
            return StageResult.CONTINUE
        
        session = market_context.get("session", "unknown")
        volatility = market_context.get("volatility", "normal")
        
        # Get UTC hour from market timestamp whenever possible.
        # Falling back to wall-clock can misclassify delayed snapshots.
        timestamp = (
            market_context.get("timestamp")
            or market_context.get("timestamp_ms")
            or market_context.get("book_timestamp_ms")
            or market_context.get("quote_timestamp_ms")
        )
        if timestamp:
            utc_hour = get_utc_hour_from_timestamp(timestamp)
        else:
            utc_hour = int(time.gmtime().tm_hour)
            log_warning(
                "session_filter_missing_market_timestamp",
                symbol=ctx.symbol,
                fallback_utc_hour=utc_hour,
            )
        
        # Classify session risk
        session_risk = classify_session_risk(session, volatility, utc_hour)
        
        # Store session risk result in context for downstream stages
        ctx.data["session_risk"] = session_risk
        
        # Requirement 5.1: Overnight session = no trading
        if session_risk.risk_mode == "off":
            ctx.rejection_reason = "session_mismatch"
            ctx.rejection_stage = self.name
            ctx.rejection_detail = {
                "session": session,
                "risk_mode": session_risk.risk_mode,
                "reason": session_risk.reason,
            }
            
            if self.telemetry:
                await self.telemetry.record_blocked(
                    symbol=ctx.symbol,
                    gate_name="session_mismatch",
                    reason=f"Session {session}: risk_mode is off ({session_risk.reason})",
                    metrics={
                        "session": session,
                        "risk_mode": session_risk.risk_mode,
                        "utc_hour": utc_hour,
                    },
                )
            
            log_warning(
                "session_filter_reject_risk_off",
                symbol=ctx.symbol,
                session=session,
                risk_mode=session_risk.risk_mode,
                reason=session_risk.reason,
            )
            
            return StageResult.REJECT
        
        # Get strategy_id from signal or context
        signal = signal_to_dict(ctx.signal)
        strategy_id = signal.get("strategy_id")
        if not strategy_id:
            strategy_id = ctx.data.get("strategy_id")
        if not strategy_id:
            strategy_id = market_context.get("strategy_id")
        
        # Check strategy session preferences (Requirements 5.4, 5.5)
        if strategy_id and self.config.enforce_strategy_sessions:
            if not is_strategy_allowed_in_session(strategy_id, session):
                ctx.rejection_reason = "session_mismatch"
                ctx.rejection_stage = self.name
                ctx.rejection_detail = {
                    "strategy_id": strategy_id,
                    "session": session,
                    "reason": "strategy_not_allowed_in_session",
                }
                
                if self.telemetry:
                    await self.telemetry.record_blocked(
                        symbol=ctx.symbol,
                        gate_name="session_mismatch",
                        reason=f"Strategy {strategy_id} not allowed in {session} session",
                        metrics={
                            "strategy_id": strategy_id,
                            "session": session,
                            "utc_hour": utc_hour,
                        },
                    )
                
                log_warning(
                    "session_filter_reject_strategy_session",
                    symbol=ctx.symbol,
                    strategy_id=strategy_id,
                    session=session,
                )
                
                return StageResult.REJECT
        
        # Check if strategy is preferred for current session risk
        if strategy_id and self.config.enforce_session_preferences:
            if not is_strategy_preferred_for_session_risk(strategy_id, session_risk):
                market_type = str(
                    ctx.data.get("market_type")
                    or market_context.get("market_type")
                    or ""
                ).strip().lower()
                is_spot_strategy = strategy_id.startswith("spot_") or market_type == "spot"
                if is_spot_strategy:
                    ctx.data["session_not_preferred"] = True
                    ctx.data["session_not_preferred_detail"] = {
                        "strategy_id": strategy_id,
                        "session": session,
                        "preferred_strategies": session_risk.preferred_strategies,
                        "reason": "strategy_not_preferred_for_session",
                    }
                    log_info(
                        "session_filter_downgrade_not_preferred_spot",
                        symbol=ctx.symbol,
                        strategy_id=strategy_id,
                        session=session,
                        preferred_strategies=session_risk.preferred_strategies,
                        position_size_multiplier=session_risk.position_size_multiplier,
                    )
                    return StageResult.CONTINUE
                ctx.rejection_reason = "session_mismatch"
                ctx.rejection_stage = self.name
                ctx.rejection_detail = {
                    "strategy_id": strategy_id,
                    "session": session,
                    "preferred_strategies": session_risk.preferred_strategies,
                    "reason": "strategy_not_preferred_for_session",
                }
                
                if self.telemetry:
                    await self.telemetry.record_blocked(
                        symbol=ctx.symbol,
                        gate_name="session_mismatch",
                        reason=f"Strategy {strategy_id} not preferred in {session} session",
                        metrics={
                            "strategy_id": strategy_id,
                            "session": session,
                            "preferred_strategies": session_risk.preferred_strategies,
                            "utc_hour": utc_hour,
                        },
                    )
                
                log_warning(
                    "session_filter_reject_not_preferred",
                    symbol=ctx.symbol,
                    strategy_id=strategy_id,
                    session=session,
                    preferred_strategies=session_risk.preferred_strategies,
                )
                
                return StageResult.REJECT
        
        # Apply position size multiplier (Requirement 5.3)
        if self.config.apply_position_size_multiplier and session_risk.position_size_multiplier < 1.0:
            if signal and isinstance(signal, dict):
                if "size" in signal and signal["size"] is not None:
                    signal["size"] = signal["size"] * session_risk.position_size_multiplier
                if "size_usd" in signal and signal["size_usd"] is not None:
                    signal["size_usd"] = signal["size_usd"] * session_risk.position_size_multiplier
                signal["session_size_multiplier"] = session_risk.position_size_multiplier
                
                log_info(
                    "session_filter_size_adjusted",
                    symbol=ctx.symbol,
                    session=session,
                    multiplier=session_risk.position_size_multiplier,
                    reason=session_risk.reason,
                )
        
        # Log successful pass
        log_info(
            "session_filter_pass",
            symbol=ctx.symbol,
            session=session,
            risk_mode=session_risk.risk_mode,
            position_size_multiplier=session_risk.position_size_multiplier,
        )
        
        return StageResult.CONTINUE
