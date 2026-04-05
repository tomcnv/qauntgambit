"""Control manager for UI status snapshots."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from quantgambit.control.runtime_state import ControlRuntimeState
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.storage.redis_streams import RedisStreamsClient, decode_message


@dataclass
class ControlManagerConfig:
    result_stream: str = "events:command_result"
    consumer_group: str = "quantgambit_control_results"
    consumer_name: str = "control_manager"
    state_snapshot_interval_sec: float = 2.0


class ControlManager:
    """Consumes command results and publishes control status snapshots."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        runtime_state: ControlRuntimeState,
        tenant_id: str,
        bot_id: str,
        config: Optional[ControlManagerConfig] = None,
    ):
        self.redis = redis_client
        self.runtime_state = runtime_state
        self.tenant_id = tenant_id
        self.bot_id = bot_id
        self.config = config or ControlManagerConfig()
        self.snapshots = RedisSnapshotWriter(redis_client.redis)
        self._last_state_snapshot: float = 0.0

    async def run(self) -> None:
        log_info("control_manager_start", stream=self.config.result_stream)
        await self.redis.create_group(self.config.result_stream, self.config.consumer_group)
        while True:
            messages = await self.redis.read_group(
                self.config.consumer_group,
                self.config.consumer_name,
                {self.config.result_stream: ">"},
            )
            for stream_name, entries in messages:
                for message_id, payload in entries:
                    await self._handle_message(payload)
                    await self.redis.ack(stream_name, self.config.consumer_group, message_id)
            await self._snapshot_state_if_due()

    async def _handle_message(self, payload: dict) -> None:
        try:
            result = decode_message(payload)
        except Exception as exc:
            log_warning("control_manager_invalid_result", error=str(exc))
            return
        await self._write_command_snapshot(result)

    async def _write_command_snapshot(self, result: dict) -> None:
        key = f"quantgambit:{self.tenant_id}:{self.bot_id}:control:last_command"
        history_key = f"quantgambit:{self.tenant_id}:{self.bot_id}:control:command_history"
        snapshot = {
            "command_id": result.get("command_id"),
            "status": result.get("status"),
            "message": result.get("message"),
            "executed_at": result.get("executed_at"),
        }
        await self.snapshots.write(key, snapshot)
        await self.snapshots.append_history(history_key, snapshot, max_items=200)

    async def _snapshot_state_if_due(self) -> None:
        now = time.time()
        if now - self._last_state_snapshot < self.config.state_snapshot_interval_sec:
            return
        self._last_state_snapshot = now
        probe = getattr(self.runtime_state, "execution_readiness_probe", None)
        if probe is not None:
            try:
                await probe()
            except Exception as exc:
                log_warning("control_manager_execution_probe_failed", error=str(exc))
        failover_ctx = self.runtime_state.failover_state.context
        key = f"quantgambit:{self.tenant_id}:{self.bot_id}:control:state"
        snapshot = {
            "trading_active": not self.runtime_state.trading_paused,
            "trading_paused": self.runtime_state.trading_paused,
            "pause_reason": self.runtime_state.pause_reason,
            "trading_disabled": self.runtime_state.trading_disabled,
            "kill_switch_active": self.runtime_state.kill_switch_active,
            "config_drift_active": self.runtime_state.config_drift_active,
            "exchange_credentials_configured": self.runtime_state.exchange_credentials_configured,
            "execution_ready": self.runtime_state.execution_ready,
            "execution_block_reason": self.runtime_state.execution_block_reason,
            "execution_last_checked_at": self.runtime_state.execution_last_checked_at,
            "failover_state": failover_ctx.state.value,
            "primary_exchange": failover_ctx.primary_exchange,
            "secondary_exchange": failover_ctx.secondary_exchange,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        await self.snapshots.write(key, snapshot)
