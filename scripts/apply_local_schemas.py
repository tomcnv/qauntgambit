#!/usr/bin/env python3
"""Apply local platform and quant golden schemas when databases are uninitialized.

This script is intentionally conservative:
- it only applies a golden schema when the target DB is missing its anchor table
- it records which golden baseline each database was bootstrapped from
"""

from __future__ import annotations

import sys
from local_schema_support import (
    QUANT_ANALYTICS_SCHEMA,
    apply_schema,
    ensure_database,
    local_schema_contracts,
    run_psql,
    schema_checksum,
    table_exists,
)


def _ensure_schema_baseline_state_table(database: str) -> None:
    run_psql(
        database,
        """
        CREATE TABLE IF NOT EXISTS schema_baseline_state (
            schema_name TEXT PRIMARY KEY,
            schema_path TEXT NOT NULL,
            schema_checksum TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
    )


def _record_schema_baseline(database: str, schema_name: str, schema_path: Path) -> None:
    _ensure_schema_baseline_state_table(database)
    checksum = schema_checksum(schema_path)
    escaped_path = str(schema_path).replace("'", "''")
    run_psql(
        database,
        (
            "INSERT INTO schema_baseline_state (schema_name, schema_path, schema_checksum, recorded_at) "
            f"VALUES ('{schema_name}', '{escaped_path}', '{checksum}', NOW()) "
            "ON CONFLICT (schema_name) DO UPDATE "
            "SET schema_path = EXCLUDED.schema_path, "
            "    schema_checksum = EXCLUDED.schema_checksum, "
            "    recorded_at = NOW();"
        ),
    )


def _ensure_roles() -> None:
    run_psql(
        "postgres",
        (
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='platform') THEN "
            "CREATE ROLE platform WITH LOGIN PASSWORD 'platform_pw'; "
            "END IF; "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='quantgambit') THEN "
            "CREATE ROLE quantgambit WITH LOGIN PASSWORD 'quantgambit_pw'; "
            "END IF; "
            "END $$;"
        ),
    )


def bootstrap_local_schemas() -> None:
    _ensure_roles()
    for contract in local_schema_contracts():
        ensure_database(contract.database, contract.owner)
        if not table_exists(contract.database, contract.anchor_table):
            print(f"Applying {contract.schema_name} golden schema to {contract.database}")
            apply_schema(contract.database, contract.schema_path, db_user=contract.owner)
        else:
            print(f"{contract.schema_name.capitalize()} DB {contract.database} already initialized")
        _record_schema_baseline(contract.database, contract.schema_name, contract.schema_path)
        if contract.schema_name == "quant" and not table_exists(contract.database, "timeline_events"):
            print(f"Applying quant analytics schema to {contract.database}")
            apply_schema(contract.database, QUANT_ANALYTICS_SCHEMA, db_user=contract.owner)
            _record_schema_baseline(contract.database, "quant_analytics", QUANT_ANALYTICS_SCHEMA)


def main() -> int:
    try:
        bootstrap_local_schemas()
    except Exception as exc:
        sys.stderr.write(f"apply_local_schemas failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
