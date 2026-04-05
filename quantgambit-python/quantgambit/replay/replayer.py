"""
Deterministic event replayer.

Replays recorded sessions through the pipeline using SimClock
for deterministic execution. No real sleep - time advances
according to event timestamps.

Usage:
    replayer = EventReplayer(config, hot_path)
    result = await replayer.replay("./recordings/20240101_120000")
    
    if result.success:
        print(f"Replayed {result.events_processed} events")
    else:
        print(f"Replay failed: {result.error}")
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, Awaitable
from pathlib import Path
import json

from quantgambit.core.clock import SimClock
from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.io.recorder import RecordingReader


@dataclass
class ReplayConfig:
    """
    Configuration for replay.
    
    Attributes:
        speed: Replay speed (0 = instant, 1 = real-time, 10 = 10x)
        record_decisions: Whether to record decisions during replay
        stop_on_divergence: Stop if decision diverges from recorded
        divergence_tolerance: Tolerance for numeric comparisons
        skip_raw: Skip raw WS messages (faster replay)
    """
    
    speed: float = 0.0  # 0 = instant (no sleep)
    record_decisions: bool = True
    stop_on_divergence: bool = False
    divergence_tolerance: float = 0.001
    skip_raw: bool = True


@dataclass
class ReplayResult:
    """
    Result of a replay run.
    
    Attributes:
        success: Whether replay completed successfully
        events_processed: Number of events processed
        decisions_made: Number of decisions made
        decisions_matched: Number of decisions matching recorded
        decisions_diverged: Number of divergent decisions
        divergences: List of divergence details
        duration_sec: Real time taken
        error: Error message if failed
    """
    
    success: bool = True
    events_processed: int = 0
    decisions_made: int = 0
    decisions_matched: int = 0
    decisions_diverged: int = 0
    divergences: List[Dict[str, Any]] = field(default_factory=list)
    duration_sec: float = 0.0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "events_processed": self.events_processed,
            "decisions_made": self.decisions_made,
            "decisions_matched": self.decisions_matched,
            "decisions_diverged": self.decisions_diverged,
            "divergences": self.divergences,
            "duration_sec": self.duration_sec,
            "error": self.error,
        }


# Type for event handler
EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class EventReplayer:
    """
    Deterministic event replayer.
    
    Replays recorded sessions through event handlers using SimClock
    for deterministic time advancement.
    """
    
    def __init__(
        self,
        config: Optional[ReplayConfig] = None,
        clock: Optional[SimClock] = None,
    ):
        """
        Initialize replayer.
        
        Args:
            config: Replay configuration
            clock: SimClock for deterministic time (created if not provided)
        """
        self._config = config or ReplayConfig()
        self._clock = clock or SimClock()
        
        # Event handlers by stream
        self._handlers: Dict[str, List[EventHandler]] = {
            "market": [],
            "decision": [],
            "execution": [],
            "ops": [],
        }
        
        # Recorded decisions for comparison
        self._recorded_decisions: List[Dict[str, Any]] = []
        
        # Replayed decisions
        self._replayed_decisions: List[Dict[str, Any]] = []
    
    def add_handler(self, stream: str, handler: EventHandler) -> None:
        """
        Add event handler for a stream.
        
        Args:
            stream: Stream name
            handler: Async handler function
        """
        if stream in self._handlers:
            self._handlers[stream].append(handler)
    
    def remove_handler(self, stream: str, handler: EventHandler) -> None:
        """Remove event handler."""
        if stream in self._handlers and handler in self._handlers[stream]:
            self._handlers[stream].remove(handler)
    
    def record_decision(self, decision: Dict[str, Any]) -> None:
        """
        Record a decision made during replay.
        
        Call this from your decision handler to enable comparison.
        """
        self._replayed_decisions.append(decision)
    
    async def replay(self, session_dir: str) -> ReplayResult:
        """
        Replay a recorded session.
        
        Args:
            session_dir: Path to session directory
            
        Returns:
            ReplayResult with outcomes
        """
        import time
        start_time = time.perf_counter()
        
        result = ReplayResult()
        
        try:
            reader = RecordingReader(session_dir)
            metadata = reader.get_metadata()
            
            # Load recorded decisions for comparison
            self._recorded_decisions = [
                r.get("decision", {})
                for r in reader.read_stream("decision")
                if "decision" in r
            ]
            
            # Initialize clock to session start time
            session_start = metadata.get("start_time", 0)
            self._clock.set_time(session_start, 0)
            
            # Process events in sequence order
            for stream, record in reader.iter_all_events():
                if self._config.skip_raw and stream == "raw":
                    continue
                
                # Get event from record
                event_data = record.get("event")
                if not event_data:
                    continue
                
                event = EventEnvelope.from_dict(event_data)
                
                # Advance clock to event time
                if self._config.speed == 0:
                    # Instant mode - jump to event time
                    self._clock.set_time(event.ts_wall, event.ts_mono)
                else:
                    # Timed mode - wait proportionally
                    delay = (event.ts_wall - self._clock.now_wall()) / self._config.speed
                    if delay > 0:
                        import asyncio
                        await asyncio.sleep(delay)
                    self._clock.set_time(event.ts_wall, event.ts_mono)
                
                # Dispatch to handlers
                await self._dispatch(stream, event)
                result.events_processed += 1
            
            # Compare decisions
            result.decisions_made = len(self._replayed_decisions)
            self._compare_decisions(result)
            
            result.success = not (
                self._config.stop_on_divergence and result.decisions_diverged > 0
            )
            
        except Exception as e:
            result.success = False
            result.error = str(e)
        
        result.duration_sec = time.perf_counter() - start_time
        return result
    
    async def _dispatch(self, stream: str, event: EventEnvelope) -> None:
        """Dispatch event to handlers."""
        handlers = self._handlers.get(stream, [])
        for handler in handlers:
            await handler(event)
    
    def _compare_decisions(self, result: ReplayResult) -> None:
        """Compare replayed decisions to recorded."""
        min_len = min(len(self._recorded_decisions), len(self._replayed_decisions))
        
        for i in range(min_len):
            recorded = self._recorded_decisions[i]
            replayed = self._replayed_decisions[i]
            
            divergence = self._check_divergence(recorded, replayed)
            if divergence:
                result.decisions_diverged += 1
                result.divergences.append({
                    "index": i,
                    "recorded": recorded,
                    "replayed": replayed,
                    "fields": divergence,
                })
            else:
                result.decisions_matched += 1
        
        # Count extra decisions as divergences
        if len(self._replayed_decisions) > len(self._recorded_decisions):
            extra = len(self._replayed_decisions) - len(self._recorded_decisions)
            result.decisions_diverged += extra
            result.divergences.append({
                "type": "extra_decisions",
                "count": extra,
            })
        elif len(self._recorded_decisions) > len(self._replayed_decisions):
            missing = len(self._recorded_decisions) - len(self._replayed_decisions)
            result.decisions_diverged += missing
            result.divergences.append({
                "type": "missing_decisions",
                "count": missing,
            })
    
    def _check_divergence(
        self,
        recorded: Dict[str, Any],
        replayed: Dict[str, Any],
    ) -> Optional[List[str]]:
        """
        Check if two decisions diverge.
        
        Returns list of divergent field names, or None if match.
        """
        divergent_fields = []
        
        # Key fields to compare
        compare_fields = [
            "symbol",
            "blocked_reason",
            "intents_count",
            "deadband_blocked",
            "churn_guard_blocked",
            "clipped",
        ]
        
        # Numeric fields with tolerance
        numeric_fields = [
            "p_raw",
            "p_hat",
            "s",
            "w_current",
            "w_target",
            "delta_w",
        ]
        
        for field in compare_fields:
            if recorded.get(field) != replayed.get(field):
                divergent_fields.append(field)
        
        for field in numeric_fields:
            rec_val = recorded.get(field)
            rep_val = replayed.get(field)
            
            if rec_val is None and rep_val is None:
                continue
            if rec_val is None or rep_val is None:
                divergent_fields.append(field)
                continue
            
            if abs(rec_val - rep_val) > self._config.divergence_tolerance:
                divergent_fields.append(field)
        
        return divergent_fields if divergent_fields else None
    
    def get_clock(self) -> SimClock:
        """Get the SimClock used for replay."""
        return self._clock
    
    def reset(self) -> None:
        """Reset replayer state for a new run."""
        self._recorded_decisions.clear()
        self._replayed_decisions.clear()
        self._clock = SimClock()


async def replay_session(
    session_dir: str,
    handlers: Dict[str, List[EventHandler]],
    config: Optional[ReplayConfig] = None,
) -> ReplayResult:
    """
    Convenience function to replay a session.
    
    Args:
        session_dir: Path to session directory
        handlers: Dict of stream -> handlers
        config: Replay configuration
        
    Returns:
        ReplayResult
    """
    replayer = EventReplayer(config)
    
    for stream, handler_list in handlers.items():
        for handler in handler_list:
            replayer.add_handler(stream, handler)
    
    return await replayer.replay(session_dir)
