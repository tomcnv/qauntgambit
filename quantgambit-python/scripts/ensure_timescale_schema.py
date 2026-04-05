import asyncio
import os
from pathlib import Path

import asyncpg


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


async def _connect_with_retry(*, host: str, port: int, user: str, password: str, database: str) -> asyncpg.Connection:
    last_exc: Exception | None = None
    for attempt in range(1, 31):
        try:
            return await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                timeout=10,
            )
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(min(5.0, 0.25 * attempt))
    raise RuntimeError(f"failed_to_connect_timescale after retries: {last_exc}")


async def _apply_sql_file(conn: asyncpg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    # Best-effort: many files are idempotent (IF NOT EXISTS).
    await conn.execute(sql)


async def main() -> None:
    host = _env("BOT_DB_HOST") or _env("TIMESCALE_HOST") or "localhost"
    port = int((_env("BOT_DB_PORT") or _env("TIMESCALE_PORT") or "5432"))
    user = _env("BOT_DB_USER") or _env("TIMESCALE_USER") or "quantgambit"
    password = _env("BOT_DB_PASSWORD") or _env("TIMESCALE_PASSWORD") or ""
    database = _env("BOT_DB_NAME") or _env("TIMESCALE_DB") or "quantgambit_bot"

    if not password:
        raise RuntimeError("missing_db_password_env(BOT_DB_PASSWORD)")

    root = Path("/app/quantgambit-python")
    sql_dir = root / "docs" / "sql"
    files = [
        sql_dir / "bot_configs.sql",
        sql_dir / "orders.sql",
        sql_dir / "telemetry.sql",
    ]

    print(f"connecting host={host} port={port} db={database} user={user}")
    conn = await _connect_with_retry(host=host, port=port, user=user, password=password, database=database)
    try:
        # Ensure the extension exists before telemetry hypertables.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
        for path in files:
            if not path.exists():
                raise RuntimeError(f"missing_sql_file:{path}")
            print(f"applying {path}")
            await _apply_sql_file(conn, path)
        print("schema_ensured_ok")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

