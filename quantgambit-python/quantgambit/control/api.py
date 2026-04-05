"""FastAPI control plane for command submission."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import FastAPI, Depends

from quantgambit.control.models import (
    ControlRequest,
    ControlResponse,
    ControlStateResponse,
    CommandHistoryResponse,
    CommandHistoryEntry,
    FailoverArmRequest,
    FailoverExecRequest,
    RiskOverrideRequest,
)
from quantgambit.auth.jwt_auth import build_auth_dependency
from quantgambit.storage.redis_streams import Command, RedisStreamsClient
from quantgambit.storage.postgres import PostgresAuditStore, CommandAuditRecord
from quantgambit.storage.redis_snapshots import RedisSnapshotReader


class ControlAPI:
    """Control API with Redis command submission and Postgres audit."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        audit_store: Optional[PostgresAuditStore] = None,
        command_stream: str = "commands:trading",
    ):
        self.redis = redis_client
        self.audit_store = audit_store
        self.command_stream = command_stream
        self.snapshots = RedisSnapshotReader(redis_client.redis)
        self.app = FastAPI(title="QuantGambit Control API", version="v1")
        self._auth = build_auth_dependency()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.post("/control/pause", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def pause(request: ControlRequest):
            return await self._submit_command("PAUSE", request)

        @self.app.post("/control/resume", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def resume(request: ControlRequest):
            return await self._submit_command("RESUME", request)

        @self.app.post("/control/flatten", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def flatten(request: ControlRequest):
            return await self._submit_command("FLATTEN", request, confirm_required=True)

        @self.app.post("/control/halt", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def halt(request: ControlRequest):
            return await self._submit_command("HALT", request, confirm_required=True)

        @self.app.post("/control/failover/arm", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def failover_arm(request: FailoverArmRequest):
            return await self._submit_failover_arm(request)

        @self.app.post("/control/failover/execute", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def failover_exec(request: FailoverExecRequest):
            return await self._submit_failover_exec("FAILOVER_EXEC", request)

        @self.app.post("/control/recover/arm", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def recover_arm(request: FailoverArmRequest):
            return await self._submit_recover_arm(request)

        @self.app.post("/control/recover/execute", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def recover_exec(request: FailoverExecRequest):
            return await self._submit_failover_exec("RECOVER_EXEC", request)

        @self.app.post("/control/risk_override", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def risk_override(request: RiskOverrideRequest):
            return await self._submit_risk_override(request)

        @self.app.post("/control/reload_config", response_model=ControlResponse, dependencies=[Depends(self._auth)])
        async def reload_config(request: ControlRequest):
            return await self._submit_command("RELOAD_CONFIG", request)

        @self.app.get("/control/state", response_model=ControlStateResponse, dependencies=[Depends(self._auth)])
        async def control_state(tenant_id: str, bot_id: str):
            return await self._fetch_state(tenant_id, bot_id)

        @self.app.get("/control/commands", response_model=CommandHistoryResponse, dependencies=[Depends(self._auth)])
        async def command_history(tenant_id: str, bot_id: str, limit: int = 50):
            return await self._fetch_command_history(tenant_id, bot_id, limit)

    async def _submit_command(
        self,
        command_type: str,
        request: ControlRequest,
        confirm_required: bool = False,
    ) -> ControlResponse:
        command_id = _new_command_id()
        command = Command(
            command_id=command_id,
            type=command_type,
            scope=(request.scope.model_dump() if request.scope else {"bot_id": request.bot_id}),
            requested_by=request.requested_by,
            requested_at=_now_iso(),
            schema_version="v1",
            reason=request.reason,
            confirm_required=confirm_required,
            confirm_token=request.confirm_token,
        )
        await self.redis.publish_command(self.command_stream, command)
        await self._audit("accepted", command)
        return ControlResponse(command_id=command_id, status="accepted", message="queued")

    async def _submit_failover_arm(self, request: FailoverArmRequest) -> ControlResponse:
        command_id = _new_command_id()
        command = Command(
            command_id=command_id,
            type="FAILOVER_ARM",
            scope={
                "bot_id": request.bot_id,
                "symbol": request.symbol,
                "primary_exchange": request.primary_exchange,
                "secondary_exchange": request.secondary_exchange,
            },
            requested_by=request.requested_by,
            requested_at=_now_iso(),
            schema_version="v1",
        )
        await self.redis.publish_command(self.command_stream, command)
        await self._audit("accepted", command)
        return ControlResponse(command_id=command_id, status="accepted", message="queued")

    async def _submit_recover_arm(self, request: FailoverArmRequest) -> ControlResponse:
        command_id = _new_command_id()
        command = Command(
            command_id=command_id,
            type="RECOVER_ARM",
            scope={
                "bot_id": request.bot_id,
                "symbol": request.symbol,
                "primary_exchange": request.primary_exchange,
                "secondary_exchange": request.secondary_exchange,
            },
            requested_by=request.requested_by,
            requested_at=_now_iso(),
            schema_version="v1",
        )
        await self.redis.publish_command(self.command_stream, command)
        await self._audit("accepted", command)
        return ControlResponse(command_id=command_id, status="accepted", message="queued")

    async def _submit_failover_exec(self, command_type: str, request: FailoverExecRequest) -> ControlResponse:
        command_id = _new_command_id()
        command = Command(
            command_id=command_id,
            type=command_type,
            scope={"bot_id": request.bot_id, "symbol": request.symbol},
            requested_by=request.requested_by,
            requested_at=_now_iso(),
            schema_version="v1",
            confirm_required=True,
            confirm_token=request.confirm_token,
        )
        await self.redis.publish_command(self.command_stream, command)
        await self._audit("accepted", command)
        return ControlResponse(command_id=command_id, status="accepted", message="queued")

    async def _submit_risk_override(self, request: RiskOverrideRequest) -> ControlResponse:
        command_id = _new_command_id()
        command = Command(
            command_id=command_id,
            type="RISK_OVERRIDE",
            scope=(request.scope.model_dump() if request.scope else {"bot_id": request.bot_id}),
            requested_by=request.requested_by,
            requested_at=_now_iso(),
            schema_version="v1",
            confirm_required=True,
            confirm_token=request.confirm_token,
            reason="risk_override",
            payload={
                "overrides": request.overrides,
                "ttl_seconds": request.ttl_seconds,
            },
        )
        await self.redis.publish_command(self.command_stream, command)
        await self._audit("accepted", command)
        return ControlResponse(command_id=command_id, status="accepted", message="queued")

    async def _audit(self, status: str, command: Command) -> None:
        if not self.audit_store:
            return
        record = CommandAuditRecord(
            command_id=command.command_id,
            type=command.type,
            scope=command.scope,
            reason=command.reason,
            requested_by=command.requested_by,
            requested_at=command.requested_at,
            status=status,
            executed_at=None,
            result_message=None,
        )
        await self.audit_store.write_command(record)

    async def _fetch_state(self, tenant_id: str, bot_id: str) -> ControlStateResponse:
        key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        data = await self.snapshots.read(key)
        if not data:
            return ControlStateResponse(
                trading_paused=False,
                pause_reason=None,
                failover_state=None,
                primary_exchange=None,
                secondary_exchange=None,
                timestamp=None,
            )
        return ControlStateResponse(**data)

    async def _fetch_command_history(self, tenant_id: str, bot_id: str, limit: int) -> CommandHistoryResponse:
        key = f"quantgambit:{tenant_id}:{bot_id}:control:command_history"
        items = await self.snapshots.read_history(key, limit=limit)
        return CommandHistoryResponse(items=[CommandHistoryEntry(**item) for item in items])


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_command_id() -> str:
    return str(uuid.uuid4())
