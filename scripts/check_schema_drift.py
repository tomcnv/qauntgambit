#!/usr/bin/env python3
"""Compatibility wrapper for schema drift checks.

The authoritative local contract check lives in scripts/preflight_local_stack.py.
This wrapper remains for callers that still invoke check_schema_drift.py directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

from local_schema_support import local_schema_contracts, run_psql


ROOT = Path(__file__).resolve().parents[1]


def schema_drift_issues(label: str, database: str, schema_path: Path) -> list[str]:
    text = schema_path.read_text(encoding="utf-8")
    tables: dict[str, set[str]] = {}
    import re

    create_table_re = re.compile(
        r"CREATE TABLE\s+public\.(?P<table>[a-zA-Z0-9_]+)\s*\((?P<body>.*?)\);\s*",
        re.DOTALL,
    )
    column_re = re.compile(r"^\s*(?P<column>[a-zA-Z_][a-zA-Z0-9_]*)\s+", re.MULTILINE)
    for match in create_table_re.finditer(text):
        table_name = match.group("table")
        body = match.group("body")
        columns: set[str] = set()
        for column_match in column_re.finditer(body):
            candidate = column_match.group("column")
            upper = candidate.upper()
            if upper in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
                continue
            columns.add(candidate)
        tables[table_name] = columns
    expected_tables = tables

    table_names = set(expected_tables.keys())
    if not table_names:
        return []
    names_sql = ",".join(f"'{name}'" for name in sorted(table_names))
    sql = f"""
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema='public'
      AND table_name IN ({names_sql})
    ORDER BY table_name, ordinal_position
    """
    rows = run_psql(database, sql, field_separator="|")
    actual: dict[str, set[str]] = {name: set() for name in table_names}
    if not rows:
        actual = actual
    else:
        for line in rows.splitlines():
            if not line.strip():
                continue
            table_name, column_name = line.split("|", 1)
            actual.setdefault(table_name, set()).add(column_name)
    issues: list[str] = []
    for table_name, expected_columns in sorted(expected_tables.items()):
        actual_columns = actual.get(table_name, set())
        if not actual_columns:
            issues.append(f"{label}: missing table `{table_name}`")
            continue
        missing_columns = sorted(expected_columns - actual_columns)
        if missing_columns:
            issues.append(
                f"{label}: table `{table_name}` missing columns: {', '.join(missing_columns[:12])}"
            )
    return issues


def schema_contract_issues() -> list[str]:
    issues: list[str] = []
    for contract in local_schema_contracts():
        issues.extend(schema_drift_issues(contract.schema_name, contract.database, contract.schema_path))
    return issues


def main() -> int:
    try:
        from preflight_local_stack import collect_preflight_failures

        issues = collect_preflight_failures(include_required_tables=False, include_drift=True)

        if issues:
            sys.stderr.write("Schema drift detected against golden baselines.\n")
            for issue in issues[:100]:
                sys.stderr.write(f"- {issue}\n")
            sys.stderr.write(
                "Remediation: reconcile the database against the golden schema files before starting services.\n"
            )
            return 1

        print("Schema drift check passed.")
        return 0
    except Exception as exc:
        sys.stderr.write(f"schema drift check failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
