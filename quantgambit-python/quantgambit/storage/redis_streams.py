"""Redis Streams adapters for commands and telemetry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


def _require_scope(tenant_id: Optional[str], bot_id: Optional[str], stream_kind: str) -> None:
    if not tenant_id or not bot_id:
        raise ValueError(f"{stream_kind}_scope_required")


@dataclass(frozen=True)
class Command:
    command_id: str
    type: str
    scope: Dict[str, Any]
    requested_by: str
    requested_at: str
    schema_version: str = "v1"
    reason: Optional[str] = None
    confirm_required: bool = False
    confirm_token: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    status: str
    message: str
    executed_at: str


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    schema_version: str
    timestamp: str
    bot_id: str
    payload: Dict[str, Any]
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    ts_recv_us: Optional[int] = None
    ts_canon_us: Optional[int] = None
    ts_exchange_s: Optional[float] = None


def command_stream_name(tenant_id: Optional[str] = None, bot_id: Optional[str] = None) -> str:
    """Build the command stream name with optional tenant/bot scoping."""
    _require_scope(tenant_id, bot_id, "command_stream")
    return f"commands:trading:{tenant_id}:{bot_id}"


def command_result_stream_name(tenant_id: Optional[str] = None, bot_id: Optional[str] = None) -> str:
    """Build the command result stream name with optional tenant/bot scoping."""
    _require_scope(tenant_id, bot_id, "command_result_stream")
    return f"events:command_result:{tenant_id}:{bot_id}"


def control_command_stream_name(tenant_id: Optional[str] = None, bot_id: Optional[str] = None) -> str:
    """Control-plane command stream (start/stop/pause/halt)."""
    _require_scope(tenant_id, bot_id, "control_command_stream")
    return f"commands:control:{tenant_id}:{bot_id}"


def control_command_result_stream_name(tenant_id: Optional[str] = None, bot_id: Optional[str] = None) -> str:
    """Control-plane result stream."""
    _require_scope(tenant_id, bot_id, "control_command_result_stream")
    return f"events:control_result:{tenant_id}:{bot_id}"


class RedisStreamsClient:
    """Thin wrapper to isolate Redis Streams usage."""

    # Default max entries per stream to prevent unbounded memory growth
    DEFAULT_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "10000"))

    def __init__(self, redis, maxlen: int = DEFAULT_MAXLEN):
        self.redis = redis
        self.maxlen = maxlen

    async def publish_command(self, stream: str, command: Command) -> str:
        data = {
            "command_id": command.command_id,
            "type": command.type,
            "scope": command.scope,
            "requested_by": command.requested_by,
            "requested_at": command.requested_at,
            "schema_version": command.schema_version,
            "reason": command.reason,
            "confirm_required": command.confirm_required,
            "confirm_token": command.confirm_token,
            "payload": command.payload,
        }
        return await self._xadd(stream, {"data": _to_json(data)})

    async def publish_command_result(self, stream: str, result: CommandResult) -> str:
        # Allow either CommandResult object or raw dict
        if isinstance(result, CommandResult):
            data = {
                "command_id": result.command_id,
                "status": result.status,
                "message": result.message,
                "executed_at": result.executed_at,
            }
        else:
            data = {
                "command_id": result.get("command_id"),
                "status": result.get("status"),
                "message": result.get("message"),
                "executed_at": result.get("executed_at"),
                "scope": result.get("scope"),
            }
        return await self._xadd(stream, {"data": _to_json(data)})

    async def publish_event(self, stream: str, event: Event) -> str:
        validate_event_payload(event.__dict__)
        data = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "schema_version": event.schema_version,
            "timestamp": event.timestamp,
            "ts_recv_us": event.ts_recv_us,
            "ts_canon_us": event.ts_canon_us,
            "ts_exchange_s": event.ts_exchange_s,
            "bot_id": event.bot_id,
            "symbol": event.symbol,
            "exchange": event.exchange,
            "payload": event.payload,
        }
        return await self._xadd(stream, {"data": _to_json(data)})

    async def _xadd(self, stream: str, data: Dict[str, Any]) -> str:
        """Compatibility wrapper for FakeRedis implementations in tests."""
        try:
            return await self.redis.xadd(
                stream, data, maxlen=self.maxlen, approximate=True
            )
        except TypeError:
            return await self.redis.xadd(stream, data)

    async def create_group(self, stream: str, group: str, start_id: str = "0") -> None:
        try:
            await self.redis.xgroup_create(stream, group, id=start_id, mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_group(
        self,
        group: str,
        consumer: str,
        streams: Dict[str, str],
        count: int = 10,
        block_ms: int = 1000,
    ) -> Iterable:
        return await self.redis.xreadgroup(
            group,
            consumer,
            streams,
            count=count,
            block=block_ms,
        )

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        await self.redis.xack(stream, group, message_id)

    async def stream_length(self, stream: str) -> int:
        return await self.redis.xlen(stream)


def decode_message(payload: Dict[str, str]) -> Dict[str, Any]:
    raw = payload.get("data")
    if raw is None:
        raw = payload.get(b"data")
    if raw is None:
        raise ValueError("missing_data_field")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    import json

    return json.loads(raw)


def validate_command_payload(command: Dict[str, Any]) -> None:
    required = {"command_id", "type", "scope", "requested_by", "requested_at"}
    missing = required - set(command.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")
    if command.get("schema_version") not in (None, "v1"):
        raise ValueError("unsupported_schema_version")


def validate_event_payload(event: Dict[str, Any]) -> None:
    required = {"event_id", "event_type", "schema_version", "timestamp", "bot_id", "payload", "ts_recv_us", "ts_canon_us"}
    missing = required - set(event.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")
    if event.get("ts_recv_us") is None or event.get("ts_canon_us") is None:
        raise ValueError("missing_ts_fields")
    if event.get("schema_version") != "v1":
        raise ValueError("unsupported_schema_version")


def decode_and_validate_event(payload: Dict[str, str]) -> Dict[str, Any]:
    event = decode_message(payload)
    validate_event_payload(event)
    return event


def _to_json(payload: Dict[str, Any]) -> str:
    # Local import to keep base deps light.
    import json

    return json.dumps(payload, separators=(",", ":"))


# Expose helper for tests
encode_event = _to_json
