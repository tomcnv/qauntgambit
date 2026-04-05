#!/usr/bin/env python3
"""Shared local schema contract and Postgres helpers for local startup scripts."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_CONTAINER = "deeptrader-postgres"
POSTGRES_USER = os.getenv("DEEPTRADER_DB_USER") or os.getenv("DB_USER") or "deeptrader_user"

PLATFORM_DB = os.getenv("PLATFORM_DB_NAME") or "platform_db"
QUANT_DB = os.getenv("BOT_DB_NAME") or "quantgambit_bot"

PLATFORM_SCHEMA = ROOT / "deeptrader-backend" / "migrations" / "000_golden_platform_schema.sql"
QUANT_SCHEMA = ROOT / "quantgambit-python" / "docs" / "sql" / "migrations" / "000_golden_quant_schema.sql"
QUANT_ANALYTICS_SCHEMA = ROOT / "quantgambit-python" / "docs" / "sql" / "analytics.sql"


@dataclass(frozen=True)
class SchemaContract:
    schema_name: str
    database: str
    owner: str
    schema_path: Path
    anchor_table: str
    required_tables: tuple[str, ...] = ()


def local_schema_contracts() -> tuple[SchemaContract, ...]:
    return (
        SchemaContract(
            schema_name="platform",
            database=PLATFORM_DB,
            owner="platform",
            schema_path=PLATFORM_SCHEMA,
            anchor_table="users",
            required_tables=(
                "users",
                "exchange_accounts",
                "bot_instances",
                "user_trading_settings",
                "bot_exchange_configs",
            ),
        ),
        SchemaContract(
            schema_name="quant",
            database=QUANT_DB,
            owner="quantgambit",
            schema_path=QUANT_SCHEMA,
            anchor_table="orderbook_snapshots",
            required_tables=(
                "bot_configs",
                "orderbook_snapshots",
                "trade_records",
                "order_states",
                "order_events",
                "decision_events",
                "recorded_decisions",
                "market_context",
                "timeline_events",
                "signals",
                "risk_incidents",
                "sltp_events",
                "schema_migrations",
            ),
        ),
    )


def run_psql(
    database: str,
    sql: str,
    *,
    field_separator: str | None = None,
    db_user: str | None = None,
) -> str:
    cmd = [
        "docker",
        "exec",
        POSTGRES_CONTAINER,
        "psql",
        "-U",
        db_user or POSTGRES_USER,
        "-d",
        database,
        "-At",
    ]
    if field_separator is not None:
        cmd.extend(["-F", field_separator])
    cmd.extend(["-c", sql])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"psql_failed:{database}")
    return result.stdout.strip()


def database_exists(database: str) -> bool:
    output = run_psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{database}';")
    return output == "1"


def ensure_database(database: str, owner: str) -> None:
    if database_exists(database):
        return
    run_psql("postgres", f"CREATE DATABASE {database} OWNER {owner};")


def table_exists(database: str, table_name: str) -> bool:
    output = run_psql(
        database,
        f"SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='{table_name}';",
    )
    return output == "1"


def apply_schema(database: str, schema_path: Path, *, db_user: str | None = None) -> None:
    if not schema_path.exists():
        raise RuntimeError(f"missing_schema_file:{schema_path}")
    cmd = [
        "docker",
        "exec",
        "-i",
        POSTGRES_CONTAINER,
        "psql",
        "-U",
        db_user or POSTGRES_USER,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
    ]
    with schema_path.open("rb") as handle:
        result = subprocess.run(cmd, stdin=handle, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore").strip() or f"schema_apply_failed:{database}")


def schema_checksum(schema_path: Path) -> str:
    return hashlib.sha256(schema_path.read_bytes()).hexdigest()
