"""Simple runtime launcher skeleton for per-bot process orchestration.

This is a stub for future expansion; it can be wired to read bot configs from
an API/DB and start runtime processes with the correct env.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass
from typing import Dict, List

import redis.asyncio as redis

from quantgambit.observability.logger import log_info, log_warning


@dataclass
class RuntimeInstance:
    tenant_id: str
    bot_id: str
    exchange: str
    process: subprocess.Popen


class RuntimeLauncher:
    def __init__(self, redis_url: str | None = None, heartbeat_interval_sec: float = 5.0):
        self.instances: Dict[str, RuntimeInstance] = {}
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self._redis = redis.from_url(self.redis_url)
        self._stop = asyncio.Event()

    def _key(self, tenant_id: str, bot_id: str) -> str:
        return f"{tenant_id}:{bot_id}"

    def start_runtime(self, tenant_id: str, bot_id: str, exchange: str, extra_env: Dict[str, str] | None = None) -> None:
        env = os.environ.copy()
        env.update(
            {
                "TENANT_ID": tenant_id,
                "BOT_ID": bot_id,
                "ACTIVE_EXCHANGE": exchange,
            }
        )
        if extra_env:
            env.update(extra_env)
        log_info("runtime_launcher_start", tenant_id=tenant_id, bot_id=bot_id, exchange=exchange)
        proc = subprocess.Popen(
            ["python", "-m", "quantgambit.runtime.entrypoint"],
            env=env,
        )
        self.instances[self._key(tenant_id, bot_id)] = RuntimeInstance(
            tenant_id=tenant_id,
            bot_id=bot_id,
            exchange=exchange,
            process=proc,
        )
        asyncio.create_task(self._write_heartbeat(tenant_id, bot_id, proc.pid, status="starting"))

    def stop_runtime(self, tenant_id: str, bot_id: str) -> None:
        key = self._key(tenant_id, bot_id)
        inst = self.instances.get(key)
        if not inst:
            log_warning("runtime_launcher_stop_missing", tenant_id=tenant_id, bot_id=bot_id)
            return
        log_info("runtime_launcher_stop", tenant_id=tenant_id, bot_id=bot_id)
        inst.process.send_signal(signal.SIGTERM)
        inst.process.wait(timeout=10)
        self.instances.pop(key, None)
        asyncio.create_task(self._write_heartbeat(tenant_id, bot_id, inst.process.pid, status="stopped"))

    def list_runtimes(self) -> List[RuntimeInstance]:
        return list(self.instances.values())

    async def _write_heartbeat(self, tenant_id: str, bot_id: str, pid: int, status: str = "running") -> None:
        key = f"runtime:heartbeat:{tenant_id}:{bot_id}"
        await self._redis.hset(
            key,
            mapping={
                "tenant_id": tenant_id,
                "bot_id": bot_id,
                "pid": pid,
                "host": os.uname().nodename,
                "status": status,
                "ts": int(asyncio.get_event_loop().time() * 1000),
            },
        )
        await self._redis.expire(key, int(max(self.heartbeat_interval_sec * 3, 30)))

    async def heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            for inst in list(self.instances.values()):
                status = "running"
                if inst.process.poll() is not None:
                    status = f"exit:{inst.process.returncode}"
                await self._write_heartbeat(inst.tenant_id, inst.bot_id, inst.process.pid, status=status)
            await asyncio.sleep(self.heartbeat_interval_sec)

    async def stop(self) -> None:
        self._stop.set()
        for inst in list(self.instances.values()):
            self.stop_runtime(inst.tenant_id, inst.bot_id)
        await self._redis.close()


async def main():
    launcher = RuntimeLauncher()
    # Example: launcher.start_runtime("tenant", "bot", "okx")
    hb = asyncio.create_task(launcher.heartbeat_loop())
    await asyncio.Event().wait()
    hb.cancel()
    await launcher.stop()


if __name__ == "__main__":  # pragma: no cover - manual launcher
    asyncio.run(main())
