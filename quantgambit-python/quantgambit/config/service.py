"""Configuration service with hot-reload notifications."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException

from quantgambit.config.models import (
    BotConfig,
    ConfigHistoryResponse,
    ConfigResponse,
    ConfigRollbackRequest,
    ConfigUpdateRequest,
    ConfigVersionDetail,
)
from quantgambit.config.store import ConfigStore
from quantgambit.storage.redis_streams import Event, RedisStreamsClient
from quantgambit.ingest.time_utils import now_recv_us


class ConfigService:
    """Config API + hot reload publisher."""

    def __init__(
        self,
        store: ConfigStore,
        redis_client: Optional[RedisStreamsClient] = None,
        event_stream: str = "events:config",
    ):
        self.store = store
        self.redis = redis_client
        self.event_stream = event_stream
        self.app = FastAPI(title="QuantGambit Config API", version="v1")
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.get("/config/{tenant_id}/{bot_id}", response_model=ConfigResponse)
        async def get_config(tenant_id: str, bot_id: str):
            record = await self.store.get_latest(tenant_id, bot_id)
            if not record:
                raise HTTPException(status_code=404, detail="config_not_found")
            return ConfigResponse(
                tenant_id=record.tenant_id,
                bot_id=record.bot_id,
                version=record.version,
                status="ok",
                message="latest",
            )

        @self.app.get("/config/{tenant_id}/{bot_id}/versions", response_model=ConfigHistoryResponse)
        async def list_versions(tenant_id: str, bot_id: str, limit: int = 50):
            records = await self.store.list_versions(tenant_id, bot_id, limit=limit)
            versions = [
                ConfigVersionDetail(
                    tenant_id=record.tenant_id,
                    bot_id=record.bot_id,
                    version=record.version,
                    created_at=record.created_at,
                    config=record.config,
                )
                for record in records
            ]
            return ConfigHistoryResponse(tenant_id=tenant_id, bot_id=bot_id, versions=versions)

        @self.app.get("/config/{tenant_id}/{bot_id}/versions/{version}", response_model=ConfigVersionDetail)
        async def get_version(tenant_id: str, bot_id: str, version: int):
            record = await self.store.get_version(tenant_id, bot_id, version)
            if not record:
                raise HTTPException(status_code=404, detail="config_version_not_found")
            return ConfigVersionDetail(
                tenant_id=record.tenant_id,
                bot_id=record.bot_id,
                version=record.version,
                created_at=record.created_at,
                config=record.config,
            )

        @self.app.post("/config/update", response_model=ConfigResponse)
        async def update_config(request: ConfigUpdateRequest):
            existing = await self.store.get_latest(request.tenant_id, request.bot_id)
            incoming = request.config
            if existing and incoming.version <= existing.version:
                raise HTTPException(status_code=409, detail="version_conflict")
            record = await self.store.upsert(incoming)
            await self._publish_update(record.config, request.requested_by, request.reason)
            return ConfigResponse(
                tenant_id=record.tenant_id,
                bot_id=record.bot_id,
                version=record.version,
                status="accepted",
                message="config_updated",
            )

        @self.app.post("/config/rollback", response_model=ConfigResponse)
        async def rollback_config(request: ConfigRollbackRequest):
            latest = await self.store.get_latest(request.tenant_id, request.bot_id)
            target = await self.store.get_version(request.tenant_id, request.bot_id, request.target_version)
            if not target:
                raise HTTPException(status_code=404, detail="rollback_target_not_found")
            next_version = (latest.version if latest else 0) + 1
            rollback_config = target.config.model_copy(update={"version": next_version})
            record = await self.store.upsert(rollback_config)
            await self._publish_update(
                record.config,
                request.requested_by,
                request.reason or f"rollback_to_{request.target_version}",
                rollback_from_version=request.target_version,
            )
            return ConfigResponse(
                tenant_id=record.tenant_id,
                bot_id=record.bot_id,
                version=record.version,
                status="accepted",
                message="config_rolled_back",
            )

    async def _publish_update(
        self,
        config: BotConfig,
        requested_by: str,
        reason: Optional[str],
        rollback_from_version: Optional[int] = None,
    ) -> None:
        if not self.redis:
            return
        ts_recv_us = now_recv_us()
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="config_update",
            schema_version="v1",
            timestamp=_now_iso(),
            ts_recv_us=ts_recv_us,
            ts_canon_us=ts_recv_us,
            ts_exchange_s=None,
            bot_id=config.bot_id,
            payload={
                "tenant_id": config.tenant_id,
                "bot_id": config.bot_id,
                "version": config.version,
                "requested_by": requested_by,
                "reason": reason,
                "rollback_from_version": rollback_from_version,
                "config": config.model_dump(mode="json"),
            },
        )
        await self.redis.publish_event(self.event_stream, event)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
