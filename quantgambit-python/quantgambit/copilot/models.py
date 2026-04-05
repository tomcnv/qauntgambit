"""Data models for the Trading Copilot Agent."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRecord:
    """Record of a single tool invocation within a conversation."""

    id: str
    tool_name: str
    parameters: dict
    result: Any | None = None
    duration_ms: float = 0.0
    success: bool = True


@dataclass
class Message:
    """A single message in a conversation."""

    role: str  # "user", "assistant", "tool"
    content: str
    tool_calls: list[ToolCallRecord] | None = None
    tool_call_id: str | None = None  # For tool result messages
    timestamp: float = field(default_factory=time.time)


@dataclass
class Conversation:
    """A conversation session between a user and the copilot."""

    id: str
    user_id: str
    created_at: float
    updated_at: float
    title: str | None = None  # Auto-generated from first message


@dataclass
class ConversationSummary:
    """Summary of a conversation for listing purposes."""

    id: str
    title: str | None
    created_at: float
    updated_at: float
    message_count: int


@dataclass
class TradeContext:
    """Context data for a specific trade, pre-loaded into a copilot session."""

    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    hold_time_seconds: float
    decision_trace_id: str | None = None
    quantity: float | None = None
    entry_time: float | None = None
    exit_time: float | None = None


@dataclass
class SettingsMutation:
    """A proposed change to user account settings."""

    id: str
    user_id: str
    conversation_id: str
    changes: dict  # { "setting_path": { "old": value, "new": value } }
    rationale: str
    status: str  # "proposed", "approved", "applied", "rejected"
    created_at: float
    constraint_violations: list[str] = field(default_factory=list)


@dataclass
class SettingsSnapshot:
    """A versioned point-in-time capture of user account settings."""

    id: str
    user_id: str
    version: int
    settings: dict  # Full settings state at time of snapshot
    actor: str  # "copilot" or "user"
    conversation_id: str | None = None
    mutation_id: str | None = None
    created_at: float = field(default_factory=time.time)


# --- Agent SSE event types ---


@dataclass
class AgentEvent:
    """Base class for SSE events."""

    type: str


@dataclass
class TextDelta(AgentEvent):
    """Streamed text content from the agent."""

    type: str = "text_delta"
    content: str = ""


@dataclass
class ToolCallStart(AgentEvent):
    """Emitted when the agent begins a tool call."""

    type: str = "tool_call_start"
    tool_name: str = ""
    parameters: dict = field(default_factory=dict)


@dataclass
class ToolCallResult(AgentEvent):
    """Emitted when a tool call completes."""

    type: str = "tool_call_result"
    tool_name: str = ""
    result: Any = None
    duration_ms: float = 0.0
    success: bool = True


@dataclass
class SettingsMutationProposal(AgentEvent):
    """Emitted when the agent proposes a settings change."""

    type: str = "settings_mutation_proposal"
    mutation: SettingsMutation | None = None


@dataclass
class ErrorEvent(AgentEvent):
    """Emitted when an error occurs during agent processing."""

    type: str = "error"
    message: str = ""


@dataclass
class DoneEvent(AgentEvent):
    """Emitted when the agent finishes processing a turn."""

    type: str = "done"


@dataclass
class ChartDataEvent(AgentEvent):
    """Emitted when candle data should be rendered as an inline chart."""

    type: str = "chart_data"
    symbol: str = ""
    timeframe_sec: int = 60
    candles: list[dict] = field(default_factory=list)  # [{ts, open, high, low, close, volume}]



# --- Tool framework types ---


@dataclass
class ToolDefinition:
    """Definition of a tool available to the copilot."""

    name: str
    description: str
    parameters_schema: dict  # JSON Schema
    handler: Callable[..., Awaitable[Any]]


@dataclass
class ToolResult:
    """Result returned from a tool execution."""

    success: bool
    data: Any  # JSON-serializable
    error: str | None = None
    duration_ms: float = 0.0


# --- LLM provider types ---


@dataclass
class LLMChunk:
    """Normalized chunk from any LLM provider."""

    type: str  # "text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "done"
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str | None = None  # JSON string, accumulated
