"""Redis Streams command consumer with guarded execution."""

from __future__ import annotations

import time
from typing import Dict, Optional

from quantgambit.storage.redis_streams import (
    RedisStreamsClient,
    CommandResult,
    decode_message,
    validate_command_payload,
    command_stream_name,
    command_result_stream_name,
)
from quantgambit.storage.postgres import PostgresAuditStore, CommandAuditRecord
from quantgambit.control.runtime_state import ControlRuntimeState
from quantgambit.execution.actions import ExecutionActionHandler
from quantgambit.execution.manager import ExecutionManager


class CommandConsumer:
    """Consume commands from Redis Streams and apply to runtime state."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        runtime_state: ControlRuntimeState,
        action_handler: Optional[ExecutionActionHandler] = None,
        execution_manager: Optional[ExecutionManager] = None,
        audit_store: Optional[PostgresAuditStore] = None,
        command_stream: str = "commands:trading",
        result_stream: str = "events:command_result",
        tenant_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        consumer_group: str = "quantgambit_control",
        consumer_name: str = "control_manager",
    ):
        self.redis = redis_client
        self.runtime_state = runtime_state
        self.audit_store = audit_store
        self.command_stream = command_stream or command_stream_name(tenant_id, bot_id)
        self.result_stream = result_stream or command_result_stream_name(tenant_id, bot_id)
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.action_handler = action_handler or ExecutionActionHandler(
            runtime_state,
            execution_manager=execution_manager,
        )

    async def start(self) -> None:
        await self.redis.create_group(self.command_stream, self.consumer_group)
        while True:
            messages = await self.redis.read_group(
                self.consumer_group,
                self.consumer_name,
                {self.command_stream: ">"},
            )
            for stream_name, entries in messages:
                for message_id, payload in entries:
                    await self._handle_message(stream_name, message_id, payload)
                    await self.redis.ack(stream_name, self.consumer_group, message_id)

    async def _handle_message(self, stream_name: str, message_id: str, payload: Dict[str, str]) -> None:
        try:
            command = decode_message(payload)
            validate_command_payload(command)
        except Exception:
            await self._publish_result(
                command_id="unknown",
                status="failed",
                message="invalid_json",
            )
            return

        command_id = command.get("command_id", "unknown")
        command_type = command.get("type", "unknown")
        status, message = await self._apply_command(command)

        await self._publish_result(command_id, status, message)

        if self.audit_store:
            record = CommandAuditRecord(
                command_id=command_id,
                type=command_type,
                scope=command.get("scope", {}),
                reason=command.get("reason"),
                requested_by=command.get("requested_by", "unknown"),
                requested_at=command.get("requested_at", _now_iso()),
                status=status,
                executed_at=_now_iso(),
                result_message=message,
            )
            await self.audit_store.write_command(record)

    async def _apply_command(self, command: Dict[str, str]) -> tuple[str, str]:
        command_type = command.get("type", "unknown")
        confirm_required = bool(command.get("confirm_required"))
        confirm_token = command.get("confirm_token")
        scope = command.get("scope") or {}
        payload = command.get("payload") or {}

        if confirm_required and not confirm_token:
            return "rejected", "confirm_token_required"

        if command_type == "PAUSE":
            return await self.action_handler.pause(command.get("reason"))

        if command_type == "RESUME":
            return await self.action_handler.resume()

        if command_type == "FAILOVER_ARM":
            return await self.action_handler.failover_arm(
                scope.get("primary_exchange"),
                scope.get("secondary_exchange"),
            )

        if command_type == "FAILOVER_EXEC":
            return await self.action_handler.failover_exec()

        if command_type == "RECOVER_ARM":
            return await self.action_handler.recover_arm(
                scope.get("primary_exchange"),
                scope.get("secondary_exchange"),
            )

        if command_type == "RECOVER_EXEC":
            return await self.action_handler.recover_exec()

        if command_type == "HALT":
            return await self.action_handler.halt()

        if command_type == "FLATTEN":
            return await self.action_handler.flatten(scope.get("symbol"))

        if command_type == "RISK_OVERRIDE":
            overrides = payload.get("overrides") or {}
            ttl_seconds = int(payload.get("ttl_seconds") or 0)
            if ttl_seconds <= 0:
                return "rejected", "invalid_ttl_seconds"
            return await self.action_handler.risk_override(overrides, ttl_seconds, scope=scope)

        if command_type == "RELOAD_CONFIG":
            return await self.action_handler.reload_config()

        if command_type == "CANCEL_ORDER":
            return await self.action_handler.cancel_order(
                order_id=payload.get("order_id"),
                client_order_id=payload.get("client_order_id"),
                symbol=payload.get("symbol"),
            )

        if command_type == "REPLACE_ORDER":
            return await self.action_handler.replace_order(
                order_id=payload.get("order_id"),
                client_order_id=payload.get("client_order_id"),
                symbol=payload.get("symbol"),
                price=payload.get("price"),
                size=payload.get("size"),
            )

        return "rejected", "unknown_command"

    async def _publish_result(self, command_id: str, status: str, message: str) -> None:
        result = CommandResult(
            command_id=command_id,
            status=status,
            message=message,
            executed_at=_now_iso(),
        )
        await self.redis.publish_command_result(self.result_stream, result)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
