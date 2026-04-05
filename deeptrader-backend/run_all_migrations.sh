#!/usr/bin/env bash
set -euo pipefail

# Run all SQL migrations in filename order.
# This avoids drift between code and hardcoded lists.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="${SCRIPT_DIR}/migrations"

collect_migrations() {
  migrations=()
  for migration_path in "${MIGRATIONS_DIR}"/*.sql; do
    [ -e "$migration_path" ] || continue
    migration="$(basename "$migration_path")"
    [[ "$migration" == *" 2.sql" ]] && continue
    migrations+=("$migration")
  done

  if [[ ${#migrations[@]} -gt 0 ]]; then
    IFS=$'\n' sorted_migrations=($(printf '%s\n' "${migrations[@]}" | sort))
    migrations=("${sorted_migrations[@]}")
    unset sorted_migrations
  fi
}

if [[ "${1:-}" == "--status" ]]; then
  if [[ ! -d "${MIGRATIONS_DIR}" ]]; then
    echo "❌ Migrations dir not found: ${MIGRATIONS_DIR}"
    exit 1
  fi

  collect_migrations migrations
  total_migrations="${#migrations[@]}"

  applied_count="$(node --input-type=module -e "import pool from './config/database.js'; const r = await pool.query(\"select count(*)::int as n from public.schema_migrations\"); console.log(r.rows[0].n); await pool.end();" 2>/dev/null | tail -n 1 | tr -dc '0-9' || true)"
  if [[ -z "${applied_count}" ]]; then
    echo "❌ Failed to read schema_migrations count"
    exit 1
  fi

  pending_count=$((total_migrations - applied_count))
  if [[ "${pending_count}" -lt 0 ]]; then
    pending_count=0
  fi

  echo "schema_migrations_count ${applied_count}"
  echo "schema_migrations_total ${total_migrations}"
  echo "schema_migrations_pending ${pending_count}"
  exit 0
fi

if [[ ! -d "${MIGRATIONS_DIR}" ]]; then
  echo "❌ Migrations dir not found: ${MIGRATIONS_DIR}"
  exit 1
fi

collect_migrations migrations

if [[ "${#migrations[@]}" -eq 0 ]]; then
  echo "⚠️  No migration files found in ${MIGRATIONS_DIR}"
  exit 0
fi

cd "$SCRIPT_DIR"

for path in "${migrations[@]}"; do
  migration="$(basename "${path}")"
  echo "Running migration: ${migration}"
  # scripts/run-migration.js expects a filename relative to deeptrader-backend/migrations
  if node scripts/run-migration.js "migrations/${migration}"; then
    echo "✅ ${migration} completed"
  else
    echo "❌ ${migration} failed"
    exit 1
  fi
  echo ""
done

echo "Migration run complete!"
