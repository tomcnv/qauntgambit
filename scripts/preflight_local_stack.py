#!/usr/bin/env python3
"""Fail-closed local stack preflight for QuantGambit.

Checks that the primary Postgres container is up and that the platform and
quant schema contracts required by the local stack are present and still
match the golden baselines before PM2 services start.
"""

from __future__ import annotations

import sys
from typing import Iterable

from local_schema_support import local_schema_contracts, run_psql
from check_schema_drift import schema_drift_issues


def _missing_tables(database: str, table_names: Iterable[str]) -> list[str]:
    sql = (
        "SELECT table_name "
        "FROM (VALUES " + ",".join(f"('{name}')" for name in table_names) + ") AS required(table_name) "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM information_schema.tables t "
        "  WHERE t.table_schema='public' AND t.table_name=required.table_name"
        ") "
        "ORDER BY table_name;"
    )
    output = run_psql(database, sql)
    if not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _check_database_exists(database: str) -> None:
    sql = f"SELECT 1 FROM pg_database WHERE datname = '{database}';"
    output = run_psql("postgres", sql)
    if output != "1":
        raise RuntimeError(f"missing_database:{database}")


def collect_preflight_failures(*, include_required_tables: bool = True, include_drift: bool = True) -> list[str]:
    failures: list[str] = []
    contracts = local_schema_contracts()

    for contract in contracts:
        try:
            _check_database_exists(contract.database)
        except Exception as exc:
            failures.append(f"{contract.schema_name} database check failed: {exc}")

    if not failures and include_required_tables:
        for contract in contracts:
            try:
                if contract.required_tables:
                    missing = _missing_tables(contract.database, contract.required_tables)
                    if missing:
                        failures.append(
                            f"{contract.schema_name} schema missing required tables: "
                            + ", ".join(missing)
                        )
            except Exception as exc:
                failures.append(f"{contract.schema_name} schema check failed: {exc}")

    if not failures and include_drift:
        for contract in contracts:
            try:
                failures.extend(
                    schema_drift_issues(
                        contract.schema_name,
                        contract.database,
                        contract.schema_path,
                    )
                )
            except Exception as exc:
                failures.append(f"{contract.schema_name} schema drift check failed: {exc}")

    return failures


def main() -> int:
    failures = collect_preflight_failures()
    if failures:
        sys.stderr.write("QuantGambit local stack preflight failed.\n")
        for failure in failures:
            sys.stderr.write(f"- {failure}\n")
        sys.stderr.write(
            "Resolve schema/bootstrap issues before starting PM2 services.\n"
        )
        return 1

    print("QuantGambit local stack preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
