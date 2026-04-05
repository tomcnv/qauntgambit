"""
Event recorder for deterministic replay.

Records all events to JSONL files for:
- Post-mortem analysis
- Deterministic replay
- Golden test corpus
- Debugging

Recorded streams:
- raw: Raw venue WebSocket messages
- market: Normalized market events (book, trades)
- decision: Decision records
- execution: Order lifecycle events
- ops: Kill-switch, health, alerts

File format: JSONL (one EventEnvelope per line)
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, TextIO
from pathlib import Path
import json
import gzip
import asyncio
from datetime import datetime

from quantgambit.core.clock import Clock, get_clock
from quantgambit.core.events import EventEnvelope, EventType


@dataclass
class RecorderConfig:
    """
    Configuration for event recorder.
    
    Attributes:
        output_dir: Directory for recording files
        session_id: Unique session identifier
        compress: Whether to gzip output files
        buffer_size: Events to buffer before flush
        flush_interval_sec: Maximum time between flushes
        record_raw: Whether to record raw WS messages
        record_market: Whether to record market events
        record_decision: Whether to record decisions
        record_execution: Whether to record execution events
        record_ops: Whether to record ops events
    """
    
    output_dir: str = "./recordings"
    session_id: Optional[str] = None
    compress: bool = False
    buffer_size: int = 100
    flush_interval_sec: float = 5.0
    record_raw: bool = True
    record_market: bool = True
    record_decision: bool = True
    record_execution: bool = True
    record_ops: bool = True


class EventRecorder:
    """
    Records events to JSONL files for replay.
    
    Usage:
        recorder = EventRecorder(config)
        await recorder.start()
        
        # Record events
        recorder.record(event)
        recorder.record_raw("bybit", raw_bytes)
        
        # Shutdown
        await recorder.stop()
    """
    
    def __init__(
        self,
        config: Optional[RecorderConfig] = None,
        clock: Optional[Clock] = None,
    ):
        """
        Initialize recorder.
        
        Args:
            config: Recorder configuration
            clock: Clock for timestamps
        """
        self._config = config or RecorderConfig()
        self._clock = clock or get_clock()
        
        # Generate session ID if not provided
        if self._config.session_id is None:
            self._config.session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # File handles
        self._files: Dict[str, TextIO] = {}
        
        # Buffers
        self._buffers: Dict[str, List[str]] = {
            "raw": [],
            "market": [],
            "decision": [],
            "execution": [],
            "ops": [],
        }
        
        # Statistics
        self._event_counts: Dict[str, int] = {
            "raw": 0,
            "market": 0,
            "decision": 0,
            "execution": 0,
            "ops": 0,
        }
        
        # Control
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._sequence = 0
    
    async def start(self) -> None:
        """Start the recorder."""
        # Create output directory
        output_dir = Path(self._config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Open files
        session_dir = output_dir / self._config.session_id
        session_dir.mkdir(exist_ok=True)
        
        for stream in self._buffers.keys():
            filename = f"{stream}.jsonl"
            if self._config.compress:
                filename += ".gz"
            
            filepath = session_dir / filename
            
            if self._config.compress:
                self._files[stream] = gzip.open(filepath, "wt", encoding="utf-8")
            else:
                self._files[stream] = open(filepath, "w", encoding="utf-8")
        
        # Write session metadata
        metadata = {
            "session_id": self._config.session_id,
            "start_time": self._clock.now_wall(),
            "config": {
                "compress": self._config.compress,
                "record_raw": self._config.record_raw,
                "record_market": self._config.record_market,
                "record_decision": self._config.record_decision,
                "record_execution": self._config.record_execution,
                "record_ops": self._config.record_ops,
            },
        }
        
        metadata_path = session_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        # Start flush task
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
    
    async def stop(self) -> None:
        """Stop the recorder and flush remaining events."""
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush
        await self._flush_all()
        
        # Close files
        for f in self._files.values():
            f.close()
        self._files.clear()
    
    def record(self, event: EventEnvelope) -> None:
        """
        Record an event.
        
        Routes to appropriate stream based on event type.
        
        Args:
            event: Event to record
        """
        # Determine stream
        stream = self._get_stream(event.type)
        
        # Check if recording this stream
        if not self._should_record(stream):
            return
        
        # Add sequence number
        self._sequence += 1
        record = {
            "seq": self._sequence,
            "event": event.to_dict(),
        }
        
        # Buffer
        self._buffers[stream].append(json.dumps(record))
        self._event_counts[stream] += 1
        
        # Check buffer size
        if len(self._buffers[stream]) >= self._config.buffer_size:
            self._flush_buffer(stream)
    
    def record_raw(self, venue: str, data: bytes) -> None:
        """
        Record raw WebSocket message.
        
        Args:
            venue: Venue name (e.g., "bybit")
            data: Raw message bytes
        """
        if not self._config.record_raw:
            return
        
        self._sequence += 1
        record = {
            "seq": self._sequence,
            "ts_wall": self._clock.now_wall(),
            "ts_mono": self._clock.now_mono(),
            "venue": venue,
            "data": data.decode("utf-8", errors="replace"),
        }
        
        self._buffers["raw"].append(json.dumps(record))
        self._event_counts["raw"] += 1
        
        if len(self._buffers["raw"]) >= self._config.buffer_size:
            self._flush_buffer("raw")
    
    def record_decision(self, decision_record: Dict[str, Any]) -> None:
        """
        Record a decision record.
        
        Args:
            decision_record: Decision record dictionary
        """
        if not self._config.record_decision:
            return
        
        self._sequence += 1
        record = {
            "seq": self._sequence,
            "ts_wall": self._clock.now_wall(),
            "decision": decision_record,
        }
        
        self._buffers["decision"].append(json.dumps(record))
        self._event_counts["decision"] += 1
        
        if len(self._buffers["decision"]) >= self._config.buffer_size:
            self._flush_buffer("decision")
    
    def _get_stream(self, event_type: str) -> str:
        """Determine stream for event type."""
        if event_type.startswith("book.") or event_type in {"trades", "tick"}:
            return "market"
        elif event_type == "decision" or event_type == "features":
            return "decision"
        elif event_type.startswith("exec.") or event_type.startswith("position."):
            return "execution"
        elif event_type.startswith("ops.") or event_type.startswith("reconciliation."):
            return "ops"
        else:
            return "ops"  # Default to ops
    
    def _should_record(self, stream: str) -> bool:
        """Check if stream should be recorded."""
        if stream == "raw":
            return self._config.record_raw
        elif stream == "market":
            return self._config.record_market
        elif stream == "decision":
            return self._config.record_decision
        elif stream == "execution":
            return self._config.record_execution
        elif stream == "ops":
            return self._config.record_ops
        return False
    
    def _flush_buffer(self, stream: str) -> None:
        """Flush a single buffer to file."""
        if stream not in self._files or not self._buffers[stream]:
            return
        
        f = self._files[stream]
        for line in self._buffers[stream]:
            f.write(line + "\n")
        f.flush()
        self._buffers[stream].clear()
    
    async def _flush_all(self) -> None:
        """Flush all buffers."""
        for stream in self._buffers.keys():
            self._flush_buffer(stream)
    
    async def _flush_loop(self) -> None:
        """Background task to periodically flush buffers."""
        while self._running:
            try:
                await asyncio.sleep(self._config.flush_interval_sec)
                await self._flush_all()
            except asyncio.CancelledError:
                break
    
    def stats(self) -> Dict[str, Any]:
        """Get recorder statistics."""
        return {
            "session_id": self._config.session_id,
            "running": self._running,
            "sequence": self._sequence,
            "event_counts": dict(self._event_counts),
            "buffer_sizes": {k: len(v) for k, v in self._buffers.items()},
        }
    
    @property
    def session_id(self) -> str:
        """Get session ID."""
        return self._config.session_id or ""
    
    @property
    def output_dir(self) -> Path:
        """Get output directory for this session."""
        return Path(self._config.output_dir) / self.session_id


class RecordingReader:
    """
    Reader for recorded sessions.
    
    Usage:
        reader = RecordingReader("./recordings/20240101_120000")
        
        for event in reader.read_stream("market"):
            print(event)
    """
    
    def __init__(self, session_dir: str):
        """
        Initialize reader.
        
        Args:
            session_dir: Path to session directory
        """
        self._session_dir = Path(session_dir)
        self._metadata: Optional[Dict[str, Any]] = None
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get session metadata."""
        if self._metadata is None:
            metadata_path = self._session_dir / "metadata.json"
            with open(metadata_path) as f:
                self._metadata = json.load(f)
        return self._metadata
    
    def read_stream(self, stream: str) -> List[Dict[str, Any]]:
        """
        Read all events from a stream.
        
        Args:
            stream: Stream name (raw, market, decision, execution, ops)
            
        Returns:
            List of event records
        """
        events = []
        
        # Try compressed first
        filepath = self._session_dir / f"{stream}.jsonl.gz"
        if filepath.exists():
            with gzip.open(filepath, "rt", encoding="utf-8") as f:
                for line in f:
                    events.append(json.loads(line))
        else:
            # Try uncompressed
            filepath = self._session_dir / f"{stream}.jsonl"
            if filepath.exists():
                with open(filepath, encoding="utf-8") as f:
                    for line in f:
                        events.append(json.loads(line))
        
        return events
    
    def iter_stream(self, stream: str):
        """
        Iterate over events in a stream.
        
        Args:
            stream: Stream name
            
        Yields:
            Event records
        """
        filepath = self._session_dir / f"{stream}.jsonl.gz"
        if filepath.exists():
            with gzip.open(filepath, "rt", encoding="utf-8") as f:
                for line in f:
                    yield json.loads(line)
        else:
            filepath = self._session_dir / f"{stream}.jsonl"
            if filepath.exists():
                with open(filepath, encoding="utf-8") as f:
                    for line in f:
                        yield json.loads(line)
    
    def iter_all_events(self):
        """
        Iterate over all events in sequence order.
        
        Yields:
            (stream, event_record) tuples
        """
        # Read all streams
        all_events = []
        for stream in ["raw", "market", "decision", "execution", "ops"]:
            for record in self.iter_stream(stream):
                all_events.append((stream, record))
        
        # Sort by sequence number
        all_events.sort(key=lambda x: x[1].get("seq", 0))
        
        for stream, record in all_events:
            yield stream, record
    
    def get_event_count(self, stream: str) -> int:
        """Get count of events in a stream."""
        count = 0
        for _ in self.iter_stream(stream):
            count += 1
        return count
    
    def list_streams(self) -> List[str]:
        """List available streams in this recording."""
        streams = []
        for stream in ["raw", "market", "decision", "execution", "ops"]:
            filepath = self._session_dir / f"{stream}.jsonl"
            filepath_gz = self._session_dir / f"{stream}.jsonl.gz"
            if filepath.exists() or filepath_gz.exists():
                streams.append(stream)
        return streams
