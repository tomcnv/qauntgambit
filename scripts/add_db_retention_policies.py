#!/usr/bin/env python3
"""
Configure TimescaleDB chunking, retention, and compression policies.

This is intended to keep high-volume local/dev environments from filling disk.

Examples:
  python scripts/add_db_retention_policies.py --profile local
  python scripts/add_db_retention_policies.py --profile local --apply-non-hypertable-cleanup
  python scripts/add_db_retention_policies.py --db-url postgresql://... --profile prod
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass

import asyncpg


DEFAULT_DB_URL = os.getenv(
    "BOT_TIMESCALE_URL",
    os.getenv("BOT_DB_URL", "postgresql://quantgambit:quantgambit_pw@localhost:5432/quantgambit_bot"),
)


@dataclass(frozen=True)
class HypertablePolicy:
    retention: str | None = None
    compression_after: str | None = None
    chunk_interval: str | None = None


POLICY_PROFILES: dict[str, dict[str, HypertablePolicy]] = {
    "local": {
        "orderbook_snapshots": HypertablePolicy(retention="3 days", compression_after="12 hours", chunk_interval="12 hours"),
        "trade_records": HypertablePolicy(retention="14 days", compression_after="1 day", chunk_interval="1 day"),
        "recorded_decisions": HypertablePolicy(retention="7 days", compression_after="12 hours", chunk_interval="1 day"),
        "decision_events": HypertablePolicy(retention="7 days", compression_after="12 hours", chunk_interval="1 day"),
        "prediction_events": HypertablePolicy(retention="7 days", compression_after="12 hours", chunk_interval="1 day"),
        "latency_events": HypertablePolicy(retention="7 days", compression_after="12 hours", chunk_interval="1 day"),
        "order_events": HypertablePolicy(retention="7 days", compression_after="1 day", chunk_interval="1 day"),
        "risk_events": HypertablePolicy(retention="7 days", compression_after="1 day", chunk_interval="1 day"),
        "position_events": HypertablePolicy(retention="14 days", compression_after="1 day", chunk_interval="1 day"),
        "guardrail_events": HypertablePolicy(retention="14 days", compression_after="1 day", chunk_interval="1 day"),
        "order_update_events": HypertablePolicy(retention="7 days", compression_after="1 day", chunk_interval="1 day"),
        "market_data_provider_events": HypertablePolicy(retention="7 days", compression_after="1 day", chunk_interval="1 day"),
        "orderbook_events": HypertablePolicy(retention="3 days", compression_after="12 hours", chunk_interval="12 hours"),
        "fee_events": HypertablePolicy(retention="30 days", compression_after="7 days", chunk_interval="1 day"),
        "market_candles": HypertablePolicy(retention="30 days", compression_after="7 days", chunk_interval="1 day"),
        "shadow_comparisons": HypertablePolicy(retention="14 days", compression_after=None, chunk_interval="1 day"),
    },
    "prod": {
        "orderbook_snapshots": HypertablePolicy(retention="14 days", compression_after="2 days", chunk_interval="1 day"),
        "trade_records": HypertablePolicy(retention="90 days", compression_after="7 days", chunk_interval="1 day"),
        "recorded_decisions": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "decision_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "prediction_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "latency_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "order_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "risk_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "position_events": HypertablePolicy(retention="60 days", compression_after="3 days", chunk_interval="1 day"),
        "guardrail_events": HypertablePolicy(retention="60 days", compression_after="3 days", chunk_interval="1 day"),
        "order_update_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "market_data_provider_events": HypertablePolicy(retention="30 days", compression_after="2 days", chunk_interval="1 day"),
        "orderbook_events": HypertablePolicy(retention="7 days", compression_after="1 day", chunk_interval="12 hours"),
        "fee_events": HypertablePolicy(retention="90 days", compression_after="7 days", chunk_interval="1 day"),
        "market_candles": HypertablePolicy(retention="180 days", compression_after="14 days", chunk_interval="1 day"),
        "shadow_comparisons": HypertablePolicy(retention="30 days", compression_after=None, chunk_interval="1 day"),
    },
}


NON_HYPERTABLE_CLEANUP = {
    "signals": ("created_at", "7 days"),
    "market_context": ("created_at", "7 days"),
}


async def fetch_existing_jobs(conn: asyncpg.Connection) -> tuple[dict[str, str], dict[str, str]]:
    rows = await conn.fetch(
        """
        SELECT hypertable_name, proc_name, config
        FROM timescaledb_information.jobs
        WHERE proc_name IN ('policy_retention', 'policy_compression')
        """
    )
    retention: dict[str, str] = {}
    compression: dict[str, str] = {}
    for row in rows:
      config = row["config"]
      if isinstance(config, str):
          config = json.loads(config)
      target = retention if row["proc_name"] == "policy_retention" else compression
      key = "drop_after" if row["proc_name"] == "policy_retention" else "compress_after"
      target[row["hypertable_name"]] = str(config.get(key))
    return retention, compression


async def fetch_columns(conn: asyncpg.Connection, table_name: str) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        table_name,
    )
    return {row["column_name"] for row in rows}


def choose_segmentby(columns: set[str]) -> str | None:
    if {"bot_id", "symbol"}.issubset(columns):
        return "bot_id,symbol"
    if {"tenant_id", "bot_id"}.issubset(columns):
        return "tenant_id,bot_id"
    if "symbol" in columns:
        return "symbol"
    if "bot_id" in columns:
        return "bot_id"
    if "tenant_id" in columns:
        return "tenant_id"
    return None


async def ensure_chunk_interval(conn: asyncpg.Connection, table_name: str, interval: str) -> None:
    await conn.execute("SELECT set_chunk_time_interval($1, INTERVAL '" + interval + "')", table_name)


async def ensure_retention_policy(
    conn: asyncpg.Connection,
    table_name: str,
    existing: dict[str, str],
    interval: str,
) -> str:
    current = existing.get(table_name)
    if current == interval:
        return f"SKIP {table_name}: retention already {interval}"
    if current is not None:
        await conn.execute(f"SELECT remove_retention_policy('{table_name}')")
    await conn.execute(f"SELECT add_retention_policy('{table_name}', INTERVAL '{interval}')")
    return f"SET  {table_name}: retention {interval}"


async def ensure_compression_policy(
    conn: asyncpg.Connection,
    table_name: str,
    existing: dict[str, str],
    interval: str,
) -> str:
    columns = await fetch_columns(conn, table_name)
    segmentby = choose_segmentby(columns)
    with_clause = "timescaledb.compress"
    if segmentby:
        with_clause += f", timescaledb.compress_segmentby = '{segmentby}'"
    await conn.execute(f"ALTER TABLE {table_name} SET ({with_clause})")
    current = existing.get(table_name)
    if current == interval:
        return f"SKIP {table_name}: compression already {interval}"
    if current is not None:
        await conn.execute(f"SELECT remove_compression_policy('{table_name}')")
    await conn.execute(f"SELECT add_compression_policy('{table_name}', INTERVAL '{interval}')")
    return f"SET  {table_name}: compress after {interval}"


async def cleanup_non_hypertables(conn: asyncpg.Connection) -> list[str]:
    messages: list[str] = []
    for table_name, (column_name, interval) in NON_HYPERTABLE_CLEANUP.items():
        try:
            result = await conn.execute(
                f"DELETE FROM {table_name} WHERE {column_name} < NOW() - INTERVAL '{interval}'"
            )
            messages.append(f"CLEAN {table_name}: {result}")
        except Exception as exc:
            messages.append(f"ERROR {table_name}: {exc}")
    return messages


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--profile", choices=sorted(POLICY_PROFILES.keys()), default="local")
    parser.add_argument("--apply-non-hypertable-cleanup", action="store_true")
    args = parser.parse_args()

    conn = await asyncpg.connect(args.db_url)
    try:
        hypertables = await conn.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertable_names = {row["hypertable_name"] for row in hypertables}
        existing_retention, existing_compression = await fetch_existing_jobs(conn)
        profile = POLICY_PROFILES[args.profile]

        print(f"Connected to {args.db_url.split('@')[-1]}")
        print(f"Profile: {args.profile}")
        print(f"Hypertables: {len(hypertable_names)}")

        print("\n=== Chunk Intervals ===")
        for table_name, policy in profile.items():
            if table_name not in hypertable_names or not policy.chunk_interval:
                continue
            try:
                await ensure_chunk_interval(conn, table_name, policy.chunk_interval)
                print(f"SET  {table_name}: chunk interval {policy.chunk_interval}")
            except Exception as exc:
                print(f"ERROR {table_name}: chunk interval -> {exc}")

        print("\n=== Retention Policies ===")
        for table_name, policy in profile.items():
            if table_name not in hypertable_names or not policy.retention:
                continue
            try:
                print(await ensure_retention_policy(conn, table_name, existing_retention, policy.retention))
            except Exception as exc:
                print(f"ERROR {table_name}: retention -> {exc}")

        print("\n=== Compression Policies ===")
        for table_name, policy in profile.items():
            if table_name not in hypertable_names or not policy.compression_after:
                continue
            try:
                print(await ensure_compression_policy(conn, table_name, existing_compression, policy.compression_after))
            except Exception as exc:
                print(f"ERROR {table_name}: compression -> {exc}")

        if args.apply_non_hypertable_cleanup:
            print("\n=== Non-Hypertable Cleanup ===")
            for message in await cleanup_non_hypertables(conn):
                print(message)

        print("\n=== Largest User Tables ===")
        rows = await conn.fetch(
            """
            SELECT schemaname, relname,
                   pg_size_pretty(pg_total_relation_size(format('%I.%I', schemaname, relname)::regclass)) AS size
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(format('%I.%I', schemaname, relname)::regclass) DESC
            LIMIT 20
            """
        )
        for row in rows:
            print(f"{row['schemaname']}.{row['relname']}: {row['size']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
