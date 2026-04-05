"""Lightweight control manager to handle bot control commands via Redis Streams.

Listens on namespaced command streams (commands:trading[:tenant_id:bot_id]) and
publishes results to the matching result stream. This scaffolds the control
plane; hook the execute_* handlers into your runtime orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import redis.asyncio as redis

from quantgambit.config.env_loading import load_layered_env_defaults
from quantgambit.observability.logger import configure_logging, log_info, log_warning, log_error
from quantgambit.storage.redis_streams import (
    RedisStreamsClient,
    control_command_stream_name,
    control_command_result_stream_name,
    _to_json,
    decode_message,
)
from quantgambit.storage.redis_snapshots import RedisSnapshotReader

try:
    from quantgambit.config.env_schema import ENV_VARS
except Exception:
    ENV_VARS = []


@dataclass
class ControlConfig:
    redis_url: str
    tenant_id: Optional[str]
    bot_id: Optional[str]
    consumer_group: str = "quantgambit_control"
    consumer_name: str = "control_manager"
    block_ms: int = 1000


class ControlManager:
    """Consume control commands and publish command results."""

    def __init__(self, cfg: ControlConfig):
        self.cfg = cfg
        self.redis_client = RedisStreamsClient(redis.from_url(cfg.redis_url))
        self.command_stream = control_command_stream_name(cfg.tenant_id, cfg.bot_id)
        self.result_stream = control_command_result_stream_name(cfg.tenant_id, cfg.bot_id)
        self.snapshot_reader = RedisSnapshotReader(self.redis_client.redis)
        self._stream_cache: set[str] = set()
        self.require_health = os.getenv("CONTROL_REQUIRE_HEALTH", "false").lower() not in {"0", "false", "no"}
        self.enable_launcher = os.getenv("CONTROL_ENABLE_LAUNCH", "false").lower() in {"1", "true", "yes"}
        # Local dev uses PM2 to spawn a runtime process.
        # In AWS, we want to launch a per-bot ECS task instead.
        self.launch_mode = os.getenv("CONTROL_LAUNCH_MODE", "pm2").strip().lower() or "pm2"
        self.launch_cmd = os.getenv(
            "RUNTIME_LAUNCH_CMD",
            "pm2 restart quantgambit-runtime --update-env",
        )
        self.stop_cmd = os.getenv(
            "RUNTIME_STOP_CMD",
            "pm2 stop quantgambit-runtime",
        )
        self.default_env = self._load_default_env()
        self._known_env_vars = self._load_known_env_vars()
        self._normalized_env_lookup = self._build_normalized_env_lookup(self._known_env_vars)
        self.strict_config_parity = os.getenv("CONTROL_STRICT_CONFIG_PARITY", "true").lower() in {
            "1",
            "true",
            "yes",
        }
        # AWS single-host PM2 startup can take noticeably longer than local dev.
        self.ready_timeout_sec = float(os.getenv("CONTROL_READY_TIMEOUT_SEC", "45.0"))
        self.ready_poll_interval_sec = float(os.getenv("CONTROL_READY_POLL_INTERVAL_SEC", "0.5"))
        self._ecs_client = None

    def _ecs_task_key(self, tenant_id: str, bot_id: str) -> str:
        return f"control:ecs_task:{tenant_id}:{bot_id}"

    def _get_ecs_client(self):
        if self._ecs_client is not None:
            return self._ecs_client
        # Lazy import so local dev doesn't need boto3 installed.
        import boto3  # type: ignore

        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        self._ecs_client = boto3.client("ecs", region_name=region) if region else boto3.client("ecs")
        return self._ecs_client

    def _load_default_env(self) -> Dict[str, str]:
        project_root = Path(__file__).resolve().parents[3]
        defaults: Dict[str, str] = {}
        for env_file in (".env", ".env.runtime-live", ".env.spot"):
            layered, _ = load_layered_env_defaults(project_root, env_file)
            defaults.update(layered)
        return defaults

    def _load_runtime_env_defaults(self, env_file: str | None) -> Dict[str, str]:
        project_root = Path(__file__).resolve().parents[3]
        layered, _ = load_layered_env_defaults(project_root, env_file)
        return layered

    def _load_known_env_vars(self) -> set[str]:
        known: set[str] = set()
        for spec in ENV_VARS or []:
            name = getattr(spec, "name", None)
            if name:
                known.add(str(name))
        known.update(self.default_env.keys())
        known.update(os.environ.keys())
        return known

    @staticmethod
    def _normalize_key(value: str) -> str:
        return "".join(ch for ch in str(value).lower() if ch.isalnum())

    def _build_normalized_env_lookup(self, env_vars: set[str]) -> dict[str, Optional[str]]:
        lookup: dict[str, Optional[str]] = {}
        for env_var in env_vars:
            normalized = self._normalize_key(env_var)
            current = lookup.get(normalized)
            if current is None:
                lookup[normalized] = env_var
            elif current != env_var:
                # ambiguous normalized key; disable fuzzy mapping for this token
                lookup[normalized] = None
        return lookup

    @staticmethod
    def _to_env_style(key: str) -> str:
        text = str(key).strip().replace("-", "_")
        text = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
        text = re.sub(r"_+", "_", text)
        return text.upper()

    @staticmethod
    def _stringify_env_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _auto_map_env_var(self, key: str) -> Optional[str]:
        env_candidate = self._to_env_style(key)
        if env_candidate in self._known_env_vars:
            return env_candidate
        normalized = self._normalize_key(key)
        mapped = self._normalized_env_lookup.get(normalized)
        return mapped if mapped else None

    def _apply_auto_config_env_mappings(
        self,
        section_name: str,
        config: dict[str, Any],
        env: Dict[str, str],
        explicit_mappings: dict[str, str],
        unmapped_out: list[str],
    ) -> None:
        for key, raw_value in config.items():
            if raw_value is None:
                continue
            if key in explicit_mappings:
                continue
            env_var = self._auto_map_env_var(key)
            if not env_var:
                unmapped_out.append(f"{section_name}.{key}")
                continue
            if env_var in env:
                continue
            env[env_var] = self._stringify_env_value(raw_value)

    async def start(self) -> None:
        log_info(
            "control_manager_start",
            command_stream=self.command_stream,
            result_stream=self.result_stream,
            tenant_id=self.cfg.tenant_id,
            bot_id=self.cfg.bot_id,
            launcher_enabled=self.enable_launcher,
            require_health=self.require_health,
        )
        await self._ensure_streams()
        # Start background health publisher
        asyncio.create_task(self._health_publisher())
        while True:
            await self._ensure_streams()
            if not self._stream_cache:
                await asyncio.sleep(self.cfg.block_ms / 1000)
                continue
            messages = await self.redis_client.read_group(
                self.cfg.consumer_group,
                self.cfg.consumer_name,
                {stream: ">" for stream in self._stream_cache},
                block_ms=self.cfg.block_ms,
                count=10,
            )
            for stream_name, entries in messages:
                for message_id, payload in entries:
                    await self._handle_command(payload)
                    await self.redis_client.ack(stream_name, self.cfg.consumer_group, message_id)

    async def _health_publisher(self) -> None:
        """Publish platform health every few seconds so dashboard knows control manager is alive."""
        import time
        while True:
            try:
                now = time.time()
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                health_payload = {
                    "timestamp": now_iso,
                    "timestamp_epoch": now,
                    "status": "ok",
                    "position_guardian": {"status": "running", "timestamp": now},
                    "services": {
                        "python_engine": {
                            "status": "running",
                            "control": {"status": "running", "fresh": True},
                            "workers": {
                                "data_worker": {"status": "running"},
                                "position_guardian": {"status": "running"},
                            },
                        },
                        "control_manager": {"status": "running", "timestamp": now},
                    },
                }
                # Write to the platform-wide health key (empty tenant/bot for platform level)
                health_key = "quantgambit:::health:latest"
                await self.redis_client.redis.set(health_key, _to_json(health_payload), ex=30)
                # Also write control state
                control_key = "quantgambit:::control:state"
                control_payload = {
                    "trading_paused": False,
                    "pause_reason": None,
                    "failover_state": "PRIMARY_ACTIVE",
                    "primary_exchange": None,
                    "secondary_exchange": None,
                    "timestamp": now_iso,
                }
                await self.redis_client.redis.set(control_key, _to_json(control_payload), ex=30)
            except Exception as exc:
                log_warning("control_health_publish_error", error=str(exc))
            await asyncio.sleep(5)

    async def _ensure_streams(self) -> None:
        streams = {self.command_stream}
        try:
            async for key in self.redis_client.redis.scan_iter(match="commands:control:*:*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                streams.add(str(key))
        except Exception as exc:
            log_warning("control_stream_discovery_failed", error=str(exc))
        new_streams = streams - self._stream_cache
        for stream in new_streams:
            await self.redis_client.create_group(stream, self.cfg.consumer_group)
        self._stream_cache = streams

    async def _handle_command(self, payload: Dict[str, Any]) -> None:
        try:
            cmd = decode_message(payload)
            cmd_type = cmd.get("type")
            command_id = cmd.get("command_id") or str(uuid.uuid4())
            scope = cmd.get("scope") or {}
            requested_by = cmd.get("requested_by") or "dashboard"
            reason = cmd.get("reason")
            payload_data = cmd.get("payload") or {}
        except Exception as exc:
            log_warning("control_command_decode_failed", error=str(exc))
            return

        log_info("control_command_received", command_id=command_id, type=cmd_type, scope=scope)
        supported = {"start_bot", "stop_bot", "pause_bot", "halt_bot", "flatten_positions"}
        if cmd_type not in supported:
            await self._publish_result(command_id, "failed", f"unsupported_command:{cmd_type}")
            return
        tenant_id = scope.get("tenant_id") or scope.get("tenant") or self.cfg.tenant_id
        bot_id = scope.get("bot_id") or scope.get("bot") or self.cfg.bot_id
        if not tenant_id or not bot_id:
            await self._publish_result(command_id, "failed", "invalid_scope_missing_ids")
            return
        try:
            if cmd_type == "start_bot":
                await self._handle_start(command_id, scope, payload_data, requested_by, reason, tenant_id, bot_id)
            else:
                await self._handle_stop_like(command_id, cmd_type, scope, requested_by, reason, tenant_id, bot_id)
        except Exception as exc:
            log_error("control_command_error", error=str(exc), command_id=command_id, type=cmd_type)
            await self._publish_result(command_id, "failed", "internal_error")

    async def _publish_action_event(
        self, command_id: str, cmd_type: str, scope: Dict[str, Any], requested_by: str, reason: Optional[str]
    ) -> None:
        event = {
            "event_id": command_id,
            "event_type": f"control_{cmd_type}",
            "schema_version": "v1",
            "timestamp": asyncio.get_event_loop().time(),
            "bot_id": self.cfg.bot_id or scope.get("bot_id") or "unknown",
            "tenant_id": self.cfg.tenant_id or scope.get("tenant_id") or "unknown",
            "payload": {
                "command_id": command_id,
                "command_type": cmd_type,
                "scope": scope,
                "requested_by": requested_by,
                "reason": reason,
            },
        }
        action_stream = control_command_stream_name(
            scope.get("tenant_id") or self.cfg.tenant_id,
            scope.get("bot_id") or self.cfg.bot_id,
        ) + ":actions"
        await self.redis_client.redis.xadd(action_stream, {"data": _to_json(event)}, maxlen=500, approximate=True)

    async def _clear_start_lock(self, scope: Dict[str, Any], cmd_type: Optional[str]) -> None:
        # Clear BOTH lock keys used by Node backend and Python control manager.
        tenant = scope.get("tenant_id") or scope.get("tenant") or "default"
        bot = scope.get("bot_id") or scope.get("bot") or self.cfg.bot_id or "unknown"
        # Node backend uses this key to guard against duplicate starts
        start_lock_key = f"control:start_lock:{tenant}:{bot}"
        # Python control manager uses this key internally
        status_lock_key = f"control:bot_status:{tenant}:{bot}"
        try:
          # On any terminal result (success/failure), remove both locks.
          await self.redis_client.redis.delete(start_lock_key)
          await self.redis_client.redis.delete(status_lock_key)
        except Exception as exc:
          log_warning("control_lock_clear_failed", error=str(exc), keys=[start_lock_key, status_lock_key], cmd_type=cmd_type)

    async def _publish_result(self, command_id: str, status: str, message: str, scope: Optional[Dict[str, Any]] = None, cmd_type: Optional[str] = None) -> None:
        result = {
            "command_id": command_id,
            "status": status,
            "message": message,
            "scope": scope or {},
            "executed_at": asyncio.get_event_loop().time(),
        }
        result_stream = control_command_result_stream_name(
            (scope or {}).get("tenant_id") or self.cfg.tenant_id,
            (scope or {}).get("bot_id") or self.cfg.bot_id,
        )
        await self.redis_client.publish_command_result(result_stream, result)
        log_info("control_command_result", command_id=command_id, status=status, detail=message)
        
        # Only clear lock when:
        # 1. Command failed (status == "failed")
        # 2. Stop/pause/halt commands completed (status == "succeeded" and not a start)
        # For successful start_bot commands, keep the lock - it will be cleared when:
        # - The runtime reports "running" (via health snapshots), or
        # - The user stops the bot, or
        # - The lock TTL expires (90s fallback)
        should_clear = False
        if scope and cmd_type in {"start_bot", "stop_bot", "pause_bot", "halt_bot", "flatten_positions"}:
            if status == "failed":
                should_clear = True
            elif cmd_type != "start_bot" and status == "succeeded":
                should_clear = True
            # For start_bot + succeeded (launch_started), DO NOT clear - keep lock during warmup
        
        if should_clear:
            await self._clear_start_lock(scope, cmd_type)

    # ──────────────────────────────────────────────────────────
    # Command handlers
    # ──────────────────────────────────────────────────────────
    async def _handle_start(
        self,
        command_id: str,
        scope: Dict[str, Any],
        payload: Dict[str, Any],
        requested_by: str,
        reason: Optional[str],
        tenant_id: str,
        bot_id: str,
    ) -> None:
        lock_key = self._lock_key(tenant_id, bot_id)
        if await self.redis_client.redis.exists(lock_key):
            await self._publish_result(command_id, "failed", "already_starting", scope=scope, cmd_type="start_bot")
            return
        if self.require_health and not await self._is_health_ok(tenant_id, bot_id):
            await self._publish_result(command_id, "failed", "health_unavailable", scope=scope, cmd_type="start_bot")
            return

        # Lock for 300s (5 minutes) to cover warmup period - matches Node.js TTL
        await self.redis_client.redis.set(lock_key, "starting", ex=300)
        await self._publish_result(command_id, "queued", "accepted", scope=scope, cmd_type="start_bot")
        await self._publish_action_event(command_id, "start_bot", scope, requested_by, reason)

        launch_ok = await self._maybe_launch_runtime(tenant_id, bot_id, scope, payload)
        status = "succeeded" if launch_ok else "failed"
        msg = "launch_failed"
        
        if launch_ok:
            await self._publish_starting_health(tenant_id, bot_id, payload)
            ready_ok, ready_detail = await self._wait_for_runtime_ready(tenant_id, bot_id)
            if ready_ok:
                msg = "launch_started" if ready_detail == "runtime_ready" else f"launch_started:{ready_detail}"
                await self._update_control_state_started(tenant_id, bot_id, payload)
            else:
                status = "failed"
                msg = f"runtime_not_ready:{ready_detail}"
        
        await self._publish_result(command_id, status, msg, scope=scope, cmd_type="start_bot")

    async def _handle_stop_like(
        self,
        command_id: str,
        cmd_type: str,
        scope: Dict[str, Any],
        requested_by: str,
        reason: Optional[str],
        tenant_id: str,
        bot_id: str,
    ) -> None:
        lock_key = self._lock_key(tenant_id, bot_id)
        await self.redis_client.redis.set(lock_key, cmd_type, ex=90)
        await self._publish_result(command_id, "queued", "accepted", scope=scope, cmd_type=cmd_type)
        await self._publish_action_event(command_id, cmd_type, scope, requested_by, reason)

        if cmd_type == "stop_bot":
            await self._maybe_stop_runtime(tenant_id, bot_id, scope)
        await self._publish_result(command_id, "succeeded", "completed", scope=scope, cmd_type=cmd_type)

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────
    def _lock_key(self, tenant_id: str, bot_id: str) -> str:
        return f"control:bot_status:{tenant_id}:{bot_id}"

    @staticmethod
    def _runtime_process_name(tenant_id: str, bot_id: str) -> str:
        return f"runtime-{tenant_id}-{bot_id}"

    async def _pm2_process_status(self, process_name: str) -> Optional[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pm2",
                "jlist",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            log_warning("control_pm2_missing", process_name=process_name)
            return None
        except Exception as exc:
            log_warning("control_pm2_query_failed", process_name=process_name, error=str(exc))
            return None
        if proc.returncode != 0:
            log_warning(
                "control_pm2_query_failed",
                process_name=process_name,
                rc=proc.returncode,
                stderr=stderr.decode()[:1000] if stderr else "",
            )
            return None
        try:
            payload = json.loads(stdout.decode() or "[]")
        except Exception as exc:
            log_warning("control_pm2_json_invalid", process_name=process_name, error=str(exc))
            return None
        for app in payload if isinstance(payload, list) else []:
            if str(app.get("name") or "").strip() != process_name:
                continue
            pm2_env = app.get("pm2_env") if isinstance(app.get("pm2_env"), dict) else {}
            status = str(pm2_env.get("status") or "").strip().lower()
            return status or None
        return None

    async def _runtime_launch_observed(self, tenant_id: str, bot_id: str) -> bool:
        if self.launch_mode != "pm2":
            return True
        status = await self._pm2_process_status(self._runtime_process_name(tenant_id, bot_id))
        return status in {"online", "launching"}

    @staticmethod
    def _assess_runtime_health(snapshot: Optional[Dict[str, Any]]) -> tuple[bool, str]:
        if not snapshot:
            return False, "health_missing"
        status = str(snapshot.get("status") or snapshot.get("health") or "").strip().lower()
        if snapshot.get("control_synthetic"):
            return False, "runtime_health_pending"
        if status in {"starting", "launching"} and snapshot.get("warmup_pending"):
            return True, "runtime_warmup"
        if status in {"stopped", "auth_failed", "config_drift", "launch_failed", "failed", "error"}:
            return False, f"health_status:{status}"
        services = snapshot.get("services") if isinstance(snapshot.get("services"), dict) else {}
        python_engine = services.get("python_engine") if isinstance(services, dict) else {}
        python_status = str((python_engine or {}).get("status") or "").strip().lower()
        if python_status and python_status not in {"running", "ok", "healthy"}:
            return False, f"python_engine_status:{python_status}"
        if python_status in {"running", "ok", "healthy"}:
            if snapshot.get("warmup_pending"):
                return True, "runtime_warmup"
            return True, "runtime_ready"
        if status in {"ok", "degraded"}:
            if snapshot.get("warmup_pending"):
                return True, "runtime_warmup"
            return True, f"runtime_status:{status}"
        return False, "runtime_not_ready"

    async def _is_health_ok(self, tenant_id: str, bot_id: str) -> bool:
        key = f"quantgambit:{tenant_id}:{bot_id}:health:latest"
        snapshot = await self.snapshot_reader.read(key)
        if not snapshot:
            log_warning("control_health_missing", tenant_id=tenant_id, bot_id=bot_id)
            return False
        status = snapshot.get("status") or snapshot.get("health") or ""
        if status and status != "ok":
            log_warning("control_health_not_ok", status=status, tenant_id=tenant_id, bot_id=bot_id)
        ok, detail = self._assess_runtime_health(snapshot)
        if not ok:
            log_warning("control_health_unready", tenant_id=tenant_id, bot_id=bot_id, detail=detail)
        return ok

    async def _wait_for_runtime_ready(self, tenant_id: str, bot_id: str) -> tuple[bool, str]:
        deadline = time.time() + max(0.0, self.ready_timeout_sec)
        key = f"quantgambit:{tenant_id}:{bot_id}:health:latest"
        last_detail = "health_missing"
        while time.time() <= deadline:
            snapshot = await self.snapshot_reader.read(key)
            if snapshot and not snapshot.get("control_synthetic"):
                ok, detail = self._assess_runtime_health(snapshot)
                if ok:
                    return True, detail
                last_detail = detail
                await asyncio.sleep(max(0.05, self.ready_poll_interval_sec))
                continue
            if not await self._runtime_launch_observed(tenant_id, bot_id):
                last_detail = "runtime_process_missing"
                await asyncio.sleep(max(0.05, self.ready_poll_interval_sec))
                continue
            ok, detail = self._assess_runtime_health(snapshot)
            if ok:
                return True, detail
            last_detail = detail
            await asyncio.sleep(max(0.05, self.ready_poll_interval_sec))
        return False, last_detail

    async def _publish_starting_health(self, tenant_id: str, bot_id: str, payload: Dict[str, Any]) -> None:
        health_key = f"quantgambit:{tenant_id}:{bot_id}:health:latest"
        now = time.time()
        snapshot = {
            "status": "starting",
            "warmup_pending": True,
            "control_synthetic": True,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "timestamp_epoch": now,
            "services": {
                "python_engine": {
                    "status": "running",
                    "control": {"status": "running", "fresh": True},
                }
            },
            "exchange": payload.get("exchange"),
            "mode": payload.get("trading_mode"),
        }
        try:
            await self.redis_client.redis.set(health_key, _to_json(snapshot), ex=90)
        except Exception as exc:
            log_warning("control_starting_health_publish_failed", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)

    async def _maybe_launch_runtime(self, tenant_id: str, bot_id: str, scope: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        if not self.enable_launcher:
            log_info("control_launch_skipped", tenant_id=tenant_id, bot_id=bot_id)
            return True

        if self.launch_mode == "ecs":
            return await self._maybe_launch_runtime_ecs(tenant_id, bot_id, scope, payload)

        env = {
            key: os.environ[key]
            for key in (
                "PATH",
                "HOME",
                "USER",
                "LOGNAME",
                "SHELL",
                "LANG",
                "LC_ALL",
                "TMPDIR",
            )
            if key in os.environ
        }
        env.update({"TENANT_ID": tenant_id, "BOT_ID": bot_id})
        derived_env, parity = self._build_runtime_env(scope, payload, include_diagnostics=True)
        if parity.get("unmapped_keys"):
            log_warning(
                "control_config_keys_unmapped",
                tenant_id=tenant_id,
                bot_id=bot_id,
                keys=parity.get("unmapped_keys"),
            )
            if self.strict_config_parity:
                log_warning(
                    "control_launch_blocked_unmapped_config",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    keys=parity.get("unmapped_keys"),
                )
                return False
        if parity.get("missing_payload_keys"):
            log_warning(
                "control_config_missing_payload_keys",
                tenant_id=tenant_id,
                bot_id=bot_id,
                keys=parity.get("missing_payload_keys"),
            )
            if self.strict_config_parity:
                log_warning(
                    "control_launch_blocked_missing_payload_keys",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    keys=parity.get("missing_payload_keys"),
                )
                return False
        env.update(derived_env)
        if derived_env:
            log_info(
                "control_launch_env",
                tenant_id=tenant_id,
                bot_id=bot_id,
                exchange=derived_env.get("ACTIVE_EXCHANGE"),
                symbols=derived_env.get("ORDERBOOK_SYMBOLS"),
                testnet=derived_env.get("ORDERBOOK_TESTNET"),
                orderbook_stream=derived_env.get("ORDERBOOK_EVENT_STREAM"),
                trade_stream=derived_env.get("TRADE_STREAM"),
                market_stream=derived_env.get("MARKET_DATA_STREAM"),
            )
            # Log risk and execution config env vars if present
            risk_vars = {k: v for k, v in derived_env.items() if k.startswith(("MAX_", "MIN_", "RISK_", "DEFAULT_"))}
            exec_vars = {k: v for k, v in derived_env.items() if k.startswith(("BLOCK_", "ORDER_"))}
            if risk_vars or exec_vars:
                log_info(
                    "control_launch_config",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    risk_config=risk_vars,
                    execution_config=exec_vars,
                )
        # Always use configured launch script, ignore payload's runtime_launch_cmd for security
        launch_cmd = self.launch_cmd
        log_info("control_launch_attempt", tenant_id=tenant_id, bot_id=bot_id, launch_cmd=launch_cmd)
        try:
            proc = await asyncio.create_subprocess_shell(
                launch_cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            ok = proc.returncode == 0
            if not ok:
                log_warning(
                    "control_launch_failed",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    rc=proc.returncode,
                    stdout=stdout.decode()[:4000] if stdout else "",
                    stderr=stderr.decode()[:4000] if stderr else "",
                )
            else:
                log_info("control_launch_succeeded", tenant_id=tenant_id, bot_id=bot_id)
            return ok
        except Exception as exc:
            log_warning("control_launch_exception", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)
            return False

    async def _maybe_launch_runtime_ecs(self, tenant_id: str, bot_id: str, scope: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        task_def = os.getenv("ECS_RUNTIME_TASK_DEFINITION") or os.getenv("ECS_RUNTIME_TASK_DEF")
        cluster = os.getenv("ECS_CLUSTER") or os.getenv("ECS_CLUSTER_ARN")
        subnets_raw = os.getenv("ECS_SUBNETS", "")
        sgs_raw = os.getenv("ECS_SECURITY_GROUPS", "")
        if not task_def or not cluster or not subnets_raw or not sgs_raw:
            log_warning(
                "control_ecs_launch_missing_config",
                tenant_id=tenant_id,
                bot_id=bot_id,
                has_task_def=bool(task_def),
                has_cluster=bool(cluster),
                has_subnets=bool(subnets_raw),
                has_sgs=bool(sgs_raw),
            )
            return False

        subnets = [s.strip() for s in subnets_raw.split(",") if s.strip()]
        security_groups = [s.strip() for s in sgs_raw.split(",") if s.strip()]
        derived_env, parity = self._build_runtime_env(scope, payload, include_diagnostics=True)
        if parity.get("unmapped_keys"):
            log_warning(
                "control_config_keys_unmapped",
                tenant_id=tenant_id,
                bot_id=bot_id,
                keys=parity.get("unmapped_keys"),
            )
            if self.strict_config_parity:
                log_warning(
                    "control_ecs_launch_blocked_unmapped_config",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    keys=parity.get("unmapped_keys"),
                )
                return False
        if parity.get("missing_payload_keys"):
            log_warning(
                "control_config_missing_payload_keys",
                tenant_id=tenant_id,
                bot_id=bot_id,
                keys=parity.get("missing_payload_keys"),
            )
            if self.strict_config_parity:
                log_warning(
                    "control_ecs_launch_blocked_missing_payload_keys",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    keys=parity.get("missing_payload_keys"),
                )
                return False
        # Always include scope identifiers.
        derived_env["TENANT_ID"] = tenant_id
        derived_env["BOT_ID"] = bot_id

        # Store environment variables as ECS override list.
        env_list = [{"name": k, "value": str(v)} for k, v in derived_env.items() if v is not None]

        try:
            ecs = self._get_ecs_client()
            resp = ecs.run_task(
                cluster=cluster,
                taskDefinition=task_def,
                launchType="FARGATE",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": subnets,
                        "securityGroups": security_groups,
                        "assignPublicIp": "DISABLED",
                    }
                },
                overrides={
                    "containerOverrides": [
                        {
                            "name": "runtime-worker",
                            "environment": env_list,
                        }
                    ]
                },
                count=1,
                enableExecuteCommand=False,
            )
            failures = resp.get("failures") or []
            tasks = resp.get("tasks") or []
            if failures or not tasks:
                log_warning(
                    "control_ecs_launch_failed",
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    failures=failures,
                )
                return False
            task_arn = tasks[0].get("taskArn")
            if task_arn:
                await self.redis_client.redis.set(self._ecs_task_key(tenant_id, bot_id), str(task_arn), ex=24 * 3600)
            log_info("control_ecs_launch_succeeded", tenant_id=tenant_id, bot_id=bot_id, task_arn=task_arn)
            return True
        except Exception as exc:
            log_warning("control_ecs_launch_exception", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)
            return False

    def _build_runtime_env(
        self,
        scope: Dict[str, Any],
        payload: Dict[str, Any],
        *,
        include_diagnostics: bool = False,
    ) -> tuple[Dict[str, str], Dict[str, Any]]:
        env: Dict[str, str] = {}
        diagnostics: Dict[str, Any] = {
            "unmapped_keys": [],
            "mapped_env_count": 0,
        }
        tenant_id = (
            payload.get("tenant_id")
            or scope.get("tenant_id")
            or scope.get("TENANT_ID")
        )
        bot_id = (
            payload.get("bot_id")
            or scope.get("bot_id")
            or scope.get("BOT_ID")
        )
        exchange = (
            payload.get("exchange")
            or scope.get("exchange")
            or scope.get("EXCHANGE")
            or scope.get("ACTIVE_EXCHANGE")
        )
        trading_mode = payload.get("trading_mode") or scope.get("TRADING_MODE")
        execution_provider = payload.get("execution_provider") or scope.get("EXECUTION_PROVIDER")
        orderbook_source = payload.get("orderbook_source") or scope.get("ORDERBOOK_SOURCE")
        trade_source = payload.get("trade_source") or scope.get("TRADE_SOURCE")
        market_data_provider = payload.get("market_data_provider") or scope.get("MARKET_DATA_PROVIDER")
        market_type = payload.get("market_type") or scope.get("MARKET_TYPE")
        margin_mode = payload.get("margin_mode") or scope.get("MARGIN_MODE")
        config_version = payload.get("config_version")
        enabled_symbols = payload.get("enabled_symbols") or []
        is_testnet = payload.get("is_testnet")
        is_demo = payload.get("is_demo")
        streams = payload.get("streams") or {}
        selected_env_file = ".env"
        
        # Extract exchange_account info for secure credential fetching
        exchange_account = payload.get("exchange_account") or {}
        exchange_account_id = payload.get("exchange_account_id") or exchange_account.get("id")
        secret_id = exchange_account.get("secret_id")
        
        # Check is_demo from exchange_account if not in payload
        if is_demo is None:
            is_demo = exchange_account.get("is_demo")

        if market_type:
            normalized_market_type = str(market_type).strip().lower()
            if normalized_market_type == "spot":
                selected_env_file = ".env.spot"
            elif trading_mode and str(trading_mode).strip().lower() == "live":
                selected_env_file = ".env.runtime-live"
            else:
                selected_env_file = ".env"
        elif trading_mode and str(trading_mode).strip().lower() == "live":
            selected_env_file = ".env.runtime-live"

        env.update(self._load_runtime_env_defaults(selected_env_file))
        env["ENV_FILE"] = selected_env_file
        if tenant_id and bot_id:
            env["PREDICTION_SCORE_SNAPSHOT_KEY"] = (
                f"quantgambit:{tenant_id}:{bot_id}:prediction:score:latest"
            )
            env["PREDICTION_DRIFT_SNAPSHOT_KEY"] = (
                f"quantgambit:{tenant_id}:{bot_id}:prediction:drift:latest"
            )

        if exchange:
            env["ACTIVE_EXCHANGE"] = str(exchange)
            env["ORDERBOOK_EXCHANGE"] = str(exchange)
            env["ORDER_UPDATES_EXCHANGE"] = str(exchange)
        if trading_mode:
            env["TRADING_MODE"] = str(trading_mode)
        if execution_provider:
            env["EXECUTION_PROVIDER"] = str(execution_provider)
        if orderbook_source:
            env["ORDERBOOK_SOURCE"] = str(orderbook_source)
        if trade_source:
            env["TRADE_SOURCE"] = str(trade_source)
        if market_data_provider:
            env["MARKET_DATA_PROVIDER"] = str(market_data_provider)
        if market_type:
            env["MARKET_TYPE"] = str(market_type)
            env["TRADE_MARKET_TYPE"] = str(market_type)
            env["ORDER_UPDATES_MARKET_TYPE"] = str(market_type)
        if margin_mode:
            env["MARGIN_MODE"] = str(margin_mode)
        if config_version is not None:
            env["BOT_CONFIG_VERSION"] = str(config_version)
            env["CONFIG_VERSION"] = str(config_version)
        if enabled_symbols:
            symbols = ",".join(str(s) for s in enabled_symbols if str(s).strip())
            if symbols:
                env["ORDERBOOK_SYMBOLS"] = symbols
                env["TRADE_SYMBOLS"] = symbols
                env["MARKET_DATA_SYMBOLS"] = symbols
        
        # Handle demo mode (Bybit demo trading) - takes precedence over testnet
        if is_demo is not None and bool(is_demo):
            env["ORDER_UPDATES_DEMO"] = "true"
            # Demo mode uses mainnet-like data feeds but demo trading endpoint
            env["ORDERBOOK_TESTNET"] = "false"
            env["TRADE_TESTNET"] = "false"
            env["ORDER_UPDATES_TESTNET"] = "false"
            env["MARKET_DATA_TESTNET"] = "false"
            if exchange:
                env[f"{exchange.upper()}_DEMO"] = "true"
                env[f"{exchange.upper()}_TESTNET"] = "false"
        elif is_testnet is not None:
            flag = "true" if bool(is_testnet) else "false"
            env["ORDERBOOK_TESTNET"] = flag
            env["TRADE_TESTNET"] = flag
            env["ORDER_UPDATES_TESTNET"] = flag
            env["MARKET_DATA_TESTNET"] = flag
            # Set exchange-specific testnet flag (used by credential loading)
            if exchange:
                env[f"{exchange.upper()}_TESTNET"] = flag
            # Testnet has lower volume and more gaps - relax quality gates
            if bool(is_testnet):
                env["FEATURE_GATE_ORDERBOOK_GAP"] = "false"  # Don't block on orderbook gaps
                env["FEATURE_GATE_TRADE_STALE"] = "false"    # Don't block on trade staleness
                env["QUALITY_GAP_WINDOW_SEC"] = "300"        # Longer gap window for testnet
                env["QUALITY_TICK_STALE_SEC"] = "120"        # More lenient staleness thresholds
                env["QUALITY_TRADE_STALE_SEC"] = "120"
                env["QUALITY_ORDERBOOK_STALE_SEC"] = "120"
        normalized_exchange = str(exchange).strip().lower() if exchange else ""
        normalized_market_type = str(market_type).strip().lower() if market_type else ""

        def _derive_stream(stream_name: str, explicit_value: Any = None) -> str | None:
            if explicit_value:
                value = str(explicit_value).strip()
                if value:
                    return value
            if not normalized_exchange:
                return None
            suffix = (
                f":{normalized_exchange}:spot"
                if normalized_market_type == "spot"
                else f":{normalized_exchange}"
            )
            return f"events:{stream_name}{suffix}"

        orderbook_stream = _derive_stream(
            "orderbook_feed",
            streams.get("orderbook") or scope.get("ORDERBOOK_EVENT_STREAM"),
        )
        trade_stream = _derive_stream(
            "trades",
            streams.get("trades") or scope.get("TRADE_STREAM"),
        )
        market_stream = _derive_stream(
            "market_data",
            streams.get("market") or scope.get("MARKET_DATA_STREAM"),
        )
        if orderbook_stream:
            env["ORDERBOOK_EVENT_STREAM"] = orderbook_stream
        if trade_stream:
            env["TRADE_STREAM"] = trade_stream
        if market_stream:
            env["MARKET_DATA_STREAM"] = market_stream

        # Pass exchange account reference for secure credential fetching
        # (credentials are fetched by runtime directly from secrets store)
        if exchange_account_id:
            env["EXCHANGE_ACCOUNT_ID"] = str(exchange_account_id)
        if secret_id:
            env["EXCHANGE_SECRET_ID"] = str(secret_id)
        
        # Pass trading capital (user's configured amount to trade with)
        # Priority: trading_capital_usd from payload > exchange_account.trading_capital > exchange_balance
        trading_capital = payload.get("trading_capital_usd")
        if trading_capital is None:
            trading_capital = exchange_account.get("trading_capital")
        if trading_capital is None:
            trading_capital = exchange_account.get("exchange_balance")
        
        if trading_capital is not None:
            env["TRADING_CAPITAL_USD"] = str(trading_capital)
            # Also set LIVE_EQUITY for backward compatibility
            env["LIVE_EQUITY"] = str(trading_capital)
            # Set PAPER_EQUITY too so it works for both modes
            env["PAPER_EQUITY"] = str(trading_capital)
            # Override any hidden env-file cap (for example .env.spot) so the
            # runtime uses the bot's configured capital budget, not a stale
            # repo default like 10000.
            env["MAX_CAPITAL_USD"] = str(trading_capital)
        
        # For live trading, ensure EXECUTION_PROVIDER is set to enable exchange adapter
        if trading_mode and trading_mode.lower() == "live":
            if not execution_provider:
                env["EXECUTION_PROVIDER"] = "ccxt"
            # Do not rely on host dotfiles for critical live data-readiness gates.
            # The run-bar start path must carry sane defaults in the launch payload.
            env.setdefault("DATA_READINESS_TRADE_LAG_GREEN_MS", "1500")
            env.setdefault("DATA_READINESS_TRADE_LAG_YELLOW_MS", "4000")
            env.setdefault("DATA_READINESS_TRADE_LAG_RED_MS", "6000")

        # ═══════════════════════════════════════════════════════════════════════════
        # Extract risk_config and execution_config from payload and convert to env vars
        # ═══════════════════════════════════════════════════════════════════════════
        risk_config = payload.get("risk_config") or {}
        execution_config = payload.get("execution_config") or {}
        profile_overrides = payload.get("profile_overrides") or {}
        
        # Also check bot-level defaults if config-level is empty
        bot_info = payload.get("bot") or {}
        if not risk_config:
            risk_config = bot_info.get("default_risk_config") or {}
        if not execution_config:
            execution_config = bot_info.get("default_execution_config") or {}
        
        # Risk config mappings (database field -> env var)
        # Supports both snake_case and camelCase from database
        risk_env_mappings = {
            # Position limits
            "max_positions": "MAX_POSITIONS",
            "maxPositions": "MAX_POSITIONS",
            "max_positions_per_symbol": "MAX_POSITIONS_PER_SYMBOL",
            "maxPositionsPerSymbol": "MAX_POSITIONS_PER_SYMBOL",
            # Risk sizing (percentage of account to risk per trade)
            "risk_per_trade_pct": "RISK_PER_TRADE_PCT",
            "riskPerTradePct": "RISK_PER_TRADE_PCT",
            "risk_per_trade": "RISK_PER_TRADE_PCT",
            "riskPerTrade": "RISK_PER_TRADE_PCT",
            "position_size_pct": "RISK_PER_TRADE_PCT",  # Alternative name
            "positionSizePct": "RISK_PER_TRADE_PCT",    # Alternative name
            # Position sizing
            "min_position_size_usd": "MIN_POSITION_SIZE_USD",
            "minPositionSizeUsd": "MIN_POSITION_SIZE_USD",
            "min_position_size": "MIN_POSITION_SIZE_USD",
            "minPositionSize": "MIN_POSITION_SIZE_USD",
            "max_position_size_usd": "MAX_POSITION_SIZE_USD",
            "maxPositionSizeUsd": "MAX_POSITION_SIZE_USD",
            # Exposure limits
            "max_total_exposure_pct": "MAX_TOTAL_EXPOSURE_PCT",
            "maxTotalExposurePct": "MAX_TOTAL_EXPOSURE_PCT",
            "max_exposure_pct": "MAX_TOTAL_EXPOSURE_PCT",
            "maxExposurePct": "MAX_TOTAL_EXPOSURE_PCT",
            "max_exposure_per_symbol_pct": "MAX_EXPOSURE_PER_SYMBOL_PCT",
            "maxExposurePerSymbolPct": "MAX_EXPOSURE_PER_SYMBOL_PCT",
            # Leverage
            "max_leverage": "MAX_LEVERAGE",
            "maxLeverage": "MAX_LEVERAGE",
            "leverage_mode": "LEVERAGE_MODE",
            "leverageMode": "LEVERAGE_MODE",
            # Drawdown controls
            "max_daily_loss_pct": "MAX_DAILY_DRAWDOWN_PCT",
            "maxDailyLossPct": "MAX_DAILY_DRAWDOWN_PCT",
            "max_daily_drawdown_pct": "MAX_DAILY_DRAWDOWN_PCT",
            "maxDailyDrawdownPct": "MAX_DAILY_DRAWDOWN_PCT",
            "max_daily_loss_per_symbol_pct": "MAX_DAILY_LOSS_PER_SYMBOL_PCT",
            "maxDailyLossPerSymbolPct": "MAX_DAILY_LOSS_PER_SYMBOL_PCT",
            "max_drawdown_pct": "MAX_DRAWDOWN_PCT",
            "maxDrawdownPct": "MAX_DRAWDOWN_PCT",
            "max_positions_per_strategy": "MAX_POSITIONS_PER_STRATEGY",
            "maxPositionsPerStrategy": "MAX_POSITIONS_PER_STRATEGY",
            # Stop loss / Take profit defaults (from risk_config)
            "default_stop_loss_pct": "DEFAULT_STOP_LOSS_PCT",
            "defaultStopLossPct": "DEFAULT_STOP_LOSS_PCT",
            "default_take_profit_pct": "DEFAULT_TAKE_PROFIT_PCT",
            "defaultTakeProfitPct": "DEFAULT_TAKE_PROFIT_PCT",
            # Position guard settings
            "position_guard_enabled": "POSITION_GUARD_ENABLED",
            "positionGuardEnabled": "POSITION_GUARD_ENABLED",
            "position_guard_interval_sec": "POSITION_GUARD_INTERVAL_SEC",
            "positionGuardIntervalSec": "POSITION_GUARD_INTERVAL_SEC",
            "position_guard_max_age_sec": "POSITION_GUARD_MAX_AGE_SEC",
            "positionGuardMaxAgeSec": "POSITION_GUARD_MAX_AGE_SEC",
            "trailing_stop_bps": "POSITION_GUARD_TRAILING_BPS",
            "trailingStopBps": "POSITION_GUARD_TRAILING_BPS",
            # Replacement / anti-churn (risk + execution use these)
            "allow_position_replacement": "ALLOW_POSITION_REPLACEMENT",
            "allowPositionReplacement": "ALLOW_POSITION_REPLACEMENT",
            "replace_opposite_only": "REPLACE_OPPOSITE_ONLY",
            "replaceOppositeOnly": "REPLACE_OPPOSITE_ONLY",
            "replace_min_edge_bps": "REPLACE_MIN_EDGE_BPS",
            "replaceMinEdgeBps": "REPLACE_MIN_EDGE_BPS",
            "replace_min_confidence": "REPLACE_MIN_CONFIDENCE",
            "replaceMinConfidence": "REPLACE_MIN_CONFIDENCE",
            "replace_min_hold_sec": "REPLACE_MIN_HOLD_SEC",
            "replaceMinHoldSec": "REPLACE_MIN_HOLD_SEC",
            # Pending intents should count towards exposure / stacking protection
            "include_pending_intents": "INCLUDE_PENDING_INTENTS",
            "includePendingIntents": "INCLUDE_PENDING_INTENTS",
        }
        
        for key, env_var in risk_env_mappings.items():
            if key in risk_config and risk_config[key] is not None:
                env[env_var] = str(risk_config[key])
        self._apply_auto_config_env_mappings(
            "risk_config",
            risk_config,
            env,
            risk_env_mappings,
            diagnostics["unmapped_keys"],
        )
        
        # Throttle mode (scalping, swing, conservative) - controls trading frequency
        # This is a top-level payload field, not inside execution_config
        throttle_mode = payload.get("throttle_mode")
        if throttle_mode:
            env["THROTTLE_MODE"] = str(throttle_mode)
        
        # Execution config mappings
        # Supports both snake_case and camelCase from database
        execution_env_mappings = {
            # Throttle mode (also check inside execution_config for backward compatibility)
            "throttle_mode": "THROTTLE_MODE",
            "throttleMode": "THROTTLE_MODE",
            # Order throttling
            "min_order_interval_sec": "MIN_ORDER_INTERVAL_SEC",
            "minOrderIntervalSec": "MIN_ORDER_INTERVAL_SEC",
            "min_trade_interval_sec": "MIN_ORDER_INTERVAL_SEC",  # Alternative name
            "minTradeIntervalSec": "MIN_ORDER_INTERVAL_SEC",     # Alternative name
            "max_decision_age_sec": "MAX_DECISION_AGE_SEC",
            "maxDecisionAgeSec": "MAX_DECISION_AGE_SEC",
            # Order type
            "default_order_type": "DEFAULT_ORDER_TYPE",
            "defaultOrderType": "DEFAULT_ORDER_TYPE",
            # Order behavior
            "block_if_position_exists": "BLOCK_IF_POSITION_EXISTS",
            "blockIfPositionExists": "BLOCK_IF_POSITION_EXISTS",
            "enforce_exchange_position_gate": "EXECUTION_ENFORCE_EXCHANGE_POSITION_GATE",
            "enforceExchangePositionGate": "EXECUTION_ENFORCE_EXCHANGE_POSITION_GATE",
            "use_reduce_only": "USE_REDUCE_ONLY",
            "useReduceOnly": "USE_REDUCE_ONLY",
            # Slippage tolerance
            "max_slippage_bps": "MAX_SLIPPAGE_BPS",
            "maxSlippageBps": "MAX_SLIPPAGE_BPS",
            # Retry settings
            "max_retries": "MAX_ORDER_RETRIES",
            "maxRetries": "MAX_ORDER_RETRIES",
            "retry_delay_sec": "ORDER_RETRY_DELAY_SEC",
            "retryDelaySec": "ORDER_RETRY_DELAY_SEC",
            # Execution timeout
            "execution_timeout_sec": "EXECUTION_TIMEOUT_SEC",
            "executionTimeoutSec": "EXECUTION_TIMEOUT_SEC",
            # Max hold time
            "max_hold_time_hours": "MAX_HOLD_TIME_HOURS",
            "maxHoldTimeHours": "MAX_HOLD_TIME_HOURS",
            # Stop Loss / Take Profit from execution_config
            "stop_loss_pct": "DEFAULT_STOP_LOSS_PCT",
            "stopLossPct": "DEFAULT_STOP_LOSS_PCT",
            "default_stop_loss_pct": "DEFAULT_STOP_LOSS_PCT",
            "defaultStopLossPct": "DEFAULT_STOP_LOSS_PCT",
            "take_profit_pct": "DEFAULT_TAKE_PROFIT_PCT",
            "takeProfitPct": "DEFAULT_TAKE_PROFIT_PCT",
            "default_take_profit_pct": "DEFAULT_TAKE_PROFIT_PCT",
            "defaultTakeProfitPct": "DEFAULT_TAKE_PROFIT_PCT",
            # Trailing stop
            "trailing_stop_pct": "TRAILING_STOP_PCT",
            "trailingStopPct": "TRAILING_STOP_PCT",
            "trailing_stop_enabled": "TRAILING_STOP_ENABLED",
            "trailingStopEnabled": "TRAILING_STOP_ENABLED",
            # Volatility filter
            "enable_volatility_filter": "ENABLE_VOLATILITY_FILTER",
            "enableVolatilityFilter": "ENABLE_VOLATILITY_FILTER",
            # Order intent replay/age guardrails
            "order_intent_max_age_sec": "ORDER_INTENT_MAX_AGE_SEC",
            "orderIntentMaxAgeSec": "ORDER_INTENT_MAX_AGE_SEC",
            # Hard execution caps (second-line defense)
            "hard_max_order_notional_usd": "EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD",
            "hardMaxOrderNotionalUsd": "EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD",
            "hard_max_symbol_notional_usd": "EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD",
            "hardMaxSymbolNotionalUsd": "EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD",
            # Replacement toggles (execution worker reads ALLOW_/REPLACE_ env vars)
            "allow_position_replacement": "ALLOW_POSITION_REPLACEMENT",
            "allowPositionReplacement": "ALLOW_POSITION_REPLACEMENT",
            "replace_opposite_only": "REPLACE_OPPOSITE_ONLY",
            "replaceOppositeOnly": "REPLACE_OPPOSITE_ONLY",
            "replace_min_edge_bps": "REPLACE_MIN_EDGE_BPS",
            "replaceMinEdgeBps": "REPLACE_MIN_EDGE_BPS",
            "replace_min_confidence": "REPLACE_MIN_CONFIDENCE",
            "replaceMinConfidence": "REPLACE_MIN_CONFIDENCE",
            "replace_min_hold_sec": "REPLACE_MIN_HOLD_SEC",
            "replaceMinHoldSec": "REPLACE_MIN_HOLD_SEC",
        }
        
        for key, env_var in execution_env_mappings.items():
            if key in execution_config and execution_config[key] is not None:
                val = execution_config[key]
                # Convert booleans to lowercase strings
                if isinstance(val, bool):
                    val = "true" if val else "false"
                env[env_var] = str(val)
        self._apply_auto_config_env_mappings(
            "execution_config",
            execution_config,
            env,
            execution_env_mappings,
            diagnostics["unmapped_keys"],
        )
        
        # Profile overrides (strategy-specific settings)
        if profile_overrides:
            import json
            env["PROFILE_OVERRIDES"] = json.dumps(profile_overrides)
            bot_type = str(profile_overrides.get("bot_type") or "").strip().lower()
            ai_provider = str(profile_overrides.get("ai_provider") or "").strip().lower()
            ai_shadow_mode = profile_overrides.get("ai_shadow_mode")
            ai_shadow_only = bool(ai_shadow_mode)
            if bot_type == "ai_spot_swing" or ai_provider in {"deepseek_context", "context_model", "ai_spot_swing"}:
                provider_name = ai_provider or "deepseek_context"
                if ai_shadow_only:
                    env["PREDICTION_SHADOW_PROVIDER"] = provider_name
                    env.setdefault("MODEL_DIRECTION_ALIGNMENT_ALLOW_MISSING_PREDICTION", "true")
                else:
                    env["PREDICTION_PROVIDER"] = provider_name
                    env.pop("PREDICTION_MODEL_PATH", None)
                    env.pop("PREDICTION_MODEL_CONFIG", None)
                    env.pop("PREDICTION_MODEL_FEATURES", None)
                    env.pop("PREDICTION_MODEL_CLASSES", None)
                env.setdefault("AI_PROVIDER_TIMEOUT_MS", "5000")
                env.setdefault("COPILOT_LLM_TIMEOUT_SEC", "5.0")
                # Spot/swing decisions should not inherit scalp-like feed lag gates.
                env["DATA_READINESS_TRADE_LAG_GREEN_MS"] = "1000"
                env["DATA_READINESS_TRADE_LAG_YELLOW_MS"] = "2500"
                env["DATA_READINESS_TRADE_LAG_RED_MS"] = "5000"
                confidence_floor = profile_overrides.get("ai_confidence_floor")
                if confidence_floor is not None:
                    env["AI_PROVIDER_MIN_CONFIDENCE"] = str(confidence_floor)
                require_alignment = profile_overrides.get("ai_require_baseline_alignment")
                if require_alignment is not None:
                    env["AI_PROVIDER_REQUIRE_BASELINE_ALIGNMENT"] = "true" if bool(require_alignment) else "false"
                sentiment_required = profile_overrides.get("ai_sentiment_required")
                if sentiment_required is not None:
                    env["AI_SENTIMENT_REQUIRED"] = "true" if bool(sentiment_required) else "false"
                if ai_shadow_mode is not None:
                    env["AI_SHADOW_ONLY"] = "true" if bool(ai_shadow_mode) else "false"
                ai_sessions = profile_overrides.get("ai_sessions")
                if isinstance(ai_sessions, (list, tuple)):
                    sessions = ",".join(str(item).strip() for item in ai_sessions if str(item).strip())
                    if sessions:
                        env["AI_ENABLED_SESSIONS"] = sessions
            allow_all_sessions = profile_overrides.get("allow_all_sessions")
            session_filter_enabled = profile_overrides.get("session_filter_enabled")
            if allow_all_sessions is True or session_filter_enabled is False:
                env["SESSION_FILTER_ENABLED"] = "false"
                env["SESSION_FILTER_ENFORCE_PREFERENCES"] = "false"
                env["SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS"] = "false"

        runtime_env = payload.get("runtime_env") or {}
        for key, value in runtime_env.items():
            if value is None:
                continue
            env[str(key)] = str(value)
        diagnostics["mapped_env_count"] = len(env)
        return env, diagnostics

    async def _maybe_stop_runtime(self, tenant_id: str, bot_id: str, scope: Dict[str, Any]) -> None:
        if not self.enable_launcher:
            log_info("control_stop_skipped", tenant_id=tenant_id, bot_id=bot_id)
            return

        if self.launch_mode == "ecs":
            await self._maybe_stop_runtime_ecs(tenant_id, bot_id)
            return

        env = os.environ.copy()
        env.update({"TENANT_ID": tenant_id, "BOT_ID": bot_id})
        try:
            proc = await asyncio.create_subprocess_shell(
                self.stop_cmd,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode != 0:
                log_warning("control_stop_failed", tenant_id=tenant_id, bot_id=bot_id, rc=proc.returncode)
            else:
                # Update health snapshot to show bot is stopped
                await self._update_health_stopped(tenant_id, bot_id)
        except Exception as exc:
            log_warning("control_stop_exception", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)

    async def _maybe_stop_runtime_ecs(self, tenant_id: str, bot_id: str) -> None:
        cluster = os.getenv("ECS_CLUSTER") or os.getenv("ECS_CLUSTER_ARN")
        if not cluster:
            log_warning("control_ecs_stop_missing_cluster", tenant_id=tenant_id, bot_id=bot_id)
            return
        key = self._ecs_task_key(tenant_id, bot_id)
        task_arn = await self.redis_client.redis.get(key)
        if isinstance(task_arn, bytes):
            task_arn = task_arn.decode("utf-8")
        task_arn = str(task_arn or "").strip()
        if not task_arn:
            log_warning("control_ecs_stop_missing_task", tenant_id=tenant_id, bot_id=bot_id, key=key)
            # Still update health so UI doesn't hang.
            await self._update_health_stopped(tenant_id, bot_id)
            return
        try:
            ecs = self._get_ecs_client()
            ecs.stop_task(cluster=cluster, task=task_arn, reason="dashboard_stop_bot")
            await self.redis_client.redis.delete(key)
            await self._update_health_stopped(tenant_id, bot_id)
            log_info("control_ecs_stop_succeeded", tenant_id=tenant_id, bot_id=bot_id, task_arn=task_arn)
        except Exception as exc:
            log_warning("control_ecs_stop_exception", error=str(exc), tenant_id=tenant_id, bot_id=bot_id, task_arn=task_arn)

    async def _update_health_stopped(self, tenant_id: str, bot_id: str) -> None:
        """Update health and control snapshots to indicate bot is stopped."""
        import time

        health_key = f"quantgambit:{tenant_id}:{bot_id}:health:latest"
        stopped_snapshot = {
            "status": "stopped",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timestamp_epoch": time.time(),
            "services": {
                "python_engine": {
                    "status": "stopped"
                }
            },
            "position_guardian": {
                "status": "stopped",
                "timestamp": time.time()
            }
        }

        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        control_snapshot = {
            "trading_active": False,
            "trading_paused": True,
            "pause_reason": "stopped",
            "failover_state": "PRIMARY_ACTIVE",
            "primary_exchange": None,
            "secondary_exchange": None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            await self.redis_client.redis.set(health_key, _to_json(stopped_snapshot))
            await self.redis_client.redis.set(control_key, _to_json(control_snapshot))
            log_info("control_health_updated_stopped", tenant_id=tenant_id, bot_id=bot_id)
        except Exception as exc:
            log_warning("control_health_update_failed", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)

    async def _update_control_state_started(self, tenant_id: str, bot_id: str, payload: Dict[str, Any]) -> None:
        """Update control state to indicate bot is starting/active."""
        import time

        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        trading_mode = payload.get("trading_mode", "paper") if payload else "paper"
        exchange = payload.get("exchange") if payload else None

        control_snapshot = {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "trading_mode": trading_mode,
            "failover_state": "PRIMARY_ACTIVE",
            "primary_exchange": exchange,
            "secondary_exchange": None,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            await self.redis_client.redis.set(control_key, _to_json(control_snapshot))
            log_info("control_state_updated_started", tenant_id=tenant_id, bot_id=bot_id, trading_mode=trading_mode)
        except Exception as exc:
            log_warning("control_state_update_failed", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)


def preview_runtime_env_parity(scope: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a dry-run parity report for dashboard payload mapping.
    Safe to call from API diagnostics endpoints.
    """
    cfg = ControlConfig(redis_url="redis://localhost:6379", tenant_id=None, bot_id=None)
    manager = ControlManager(cfg)
    _, diagnostics = manager._build_runtime_env(scope or {}, payload or {}, include_diagnostics=True)
    diagnostics["strict_mode"] = manager.strict_config_parity
    return diagnostics


def export_runtime_env(scope: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build mapped runtime env variables from a dashboard config payload.
    Safe for API diagnostics/export endpoints.
    """
    cfg = ControlConfig(redis_url="redis://localhost:6379", tenant_id=None, bot_id=None)
    manager = ControlManager(cfg)
    runtime_env, diagnostics = manager._build_runtime_env(scope or {}, payload or {}, include_diagnostics=True)
    diagnostics["strict_mode"] = manager.strict_config_parity
    env_lines = [f"{k}={runtime_env[k]}" for k in sorted(runtime_env.keys())]
    return {
        "runtime_env": runtime_env,
        "env_text": "\n".join(env_lines),
        "diagnostics": diagnostics,
    }

    async def _update_health_stopped(self, tenant_id: str, bot_id: str) -> None:
        """Update health and control snapshots to indicate bot is stopped."""
        import time
        
        # Update health snapshot
        health_key = f"quantgambit:{tenant_id}:{bot_id}:health:latest"
        stopped_snapshot = {
            "status": "stopped",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timestamp_epoch": time.time(),
            "services": {
                "python_engine": {
                    "status": "stopped"
                }
            },
            "position_guardian": {
                "status": "stopped",
                "timestamp": time.time()
            }
        }
        
        # Update control state to show not active
        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        control_snapshot = {
            "trading_active": False,
            "trading_paused": True,
            "pause_reason": "stopped",
            "failover_state": "PRIMARY_ACTIVE",
            "primary_exchange": None,
            "secondary_exchange": None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        
        try:
            await self.redis_client.redis.set(health_key, _to_json(stopped_snapshot))
            await self.redis_client.redis.set(control_key, _to_json(control_snapshot))
            log_info("control_health_updated_stopped", tenant_id=tenant_id, bot_id=bot_id)
        except Exception as exc:
            log_warning("control_health_update_failed", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)

    async def _update_control_state_started(self, tenant_id: str, bot_id: str, payload: Dict[str, Any]) -> None:
        """Update control state to indicate bot is starting/active."""
        import time
        
        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        trading_mode = payload.get("trading_mode", "paper") if payload else "paper"
        exchange = payload.get("exchange") if payload else None
        
        control_snapshot = {
            "trading_active": True,
            "trading_paused": False,
            "pause_reason": None,
            "trading_mode": trading_mode,
            "failover_state": "PRIMARY_ACTIVE",
            "primary_exchange": exchange,
            "secondary_exchange": None,
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        
        try:
            await self.redis_client.redis.set(control_key, _to_json(control_snapshot))
            log_info("control_state_updated_started", tenant_id=tenant_id, bot_id=bot_id, trading_mode=trading_mode)
        except Exception as exc:
            log_warning("control_state_update_failed", error=str(exc), tenant_id=tenant_id, bot_id=bot_id)


async def run() -> None:
    # Ensure logs reach stdout/stderr in ECS.
    configure_logging()
    cfg = ControlConfig(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        tenant_id=os.getenv("TENANT_ID"),
        bot_id=os.getenv("BOT_ID"),
        consumer_group=os.getenv("CONTROL_GROUP", "quantgambit_control"),
        consumer_name=os.getenv("CONTROL_CONSUMER", "control_manager"),
    )
    manager = ControlManager(cfg)
    try:
        await manager.start()
    except Exception as exc:
        log_error("control_manager_failed", error=str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(run())
