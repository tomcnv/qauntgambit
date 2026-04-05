# DeepTrader PostgreSQL Database

This directory contains the database schema and setup files for DeepTrader.

## Files

- **`init.sql`** - Original initialization script (creates base tables)
- **`schema.sql`** - Complete database schema export (auto-generated)
- **`setup-database.sh`** - Interactive script to set up the database

## Quick Setup (New Machine)

### Step 1: Start Database

```bash
cd /path/to/deeptrader
docker-compose up -d deeptrader-postgres deeptrader-redis
```

### Step 2: Apply Migrations

```bash
cd deeptrader-backend
for f in migrations/*.sql; do
  echo "Applying $f..."
  docker exec -i deeptrader-postgres psql -U deeptrader_user -d deeptrader < "$f" 2>/dev/null || true
done
```

### Step 3: Seed Essential Data

```bash
cd deeptrader-backend
node scripts/seed-all.js
```

This seeds:
- **Admin user** (`ops@deeptrader.local` / `ControlTower!23`)
- **Canonical profiles** (20+ trading profiles from Python definitions)
- **Strategy templates** (from Python strategy definitions)
- **Profile-strategy links**

## Alternative Setup Methods

### Option 1: Fresh Install with Docker (Recommended)

### Option 2: Restore from Schema Export

If you need to recreate the database from the exported schema:

```bash
# Drop and recreate database
docker exec -i deeptrader-postgres psql -U postgres -c "DROP DATABASE IF EXISTS deeptrader;"
docker exec -i deeptrader-postgres psql -U postgres -c "CREATE DATABASE deeptrader OWNER deeptrader_user;"

# Apply schema
docker exec -i deeptrader-postgres psql -U deeptrader_user -d deeptrader < docker/postgres/schema.sql
```

### Option 3: Use Setup Script

```bash
cd docker/postgres
./setup-database.sh
```

## Database Structure

### Core Tables

| Table | Description |
|-------|-------------|
| `users` | User accounts and authentication |
| `portfolios` | Trading portfolios with capital tracking |
| `trades` | Individual trades and positions |
| `exchange_accounts` | Exchange API connections |
| `bot_instances` | Trading bot configurations |
| `bot_exchange_configs` | Bot-to-exchange mappings |

### Profile & Strategy System

| Table | Description |
|-------|-------------|
| `user_chessboard_profiles` | Trading profiles (market regime configs) |
| `strategy_instances` | Strategy templates and instances |
| `profile_strategy_links` | Many-to-many profile-strategy relationships |
| `profile_versions` | Audit trail of profile changes |

### Bot Control System

| Table | Description |
|-------|-------------|
| `bot_commands` | Queue for bot start/stop/restart commands |
| `symbol_locks` | Symbol ownership locks for multi-bot setups |
| `bot_budgets` | Capital allocation per bot |

### Audit & Logging

| Table | Description |
|-------|-------------|
| `audit_log` | System-wide audit trail |
| `alerts` | User notifications |

## Migrations

Migrations are stored in `deeptrader-backend/migrations/` and should be applied in order:

```
001_initial_setup.sql
002_add_exchange_tables.sql
...
039_create_bot_commands.sql
```

## Seed Scripts

Seed scripts populate essential default data. Located in `deeptrader-backend/scripts/`:

| Script | Description |
|--------|-------------|
| `seed-all.js` | **Master script** - runs all seeds in correct order |
| `seed-admin-user.js` | Creates default admin user |
| `seed-canonical-profiles.js` | Loads trading profiles from Python definitions |
| `seed-strategies.js` | Loads strategy templates from Python definitions |
| `link-profile-strategies.js` | Links strategies to profiles |

### Why Scripts Instead of Data Exports?

The **Python codebase is the source of truth** for profiles and strategies. The seed scripts read from Python definitions, ensuring:

1. ✅ Consistency with trading bot behavior
2. ✅ Easy updates when Python code changes
3. ✅ No accidental inclusion of test data
4. ✅ Proper version control

## Updating Schema Export

To regenerate the schema export after database changes:

```bash
docker exec deeptrader-postgres pg_dump -U deeptrader_user -d deeptrader \
  --schema-only --no-owner --no-privileges \
  > docker/postgres/schema.sql
```

## Environment Variables

The database uses these environment variables (defaults shown):

```bash
POSTGRES_USER=deeptrader_user
POSTGRES_PASSWORD=deeptrader_pass
POSTGRES_DB=deeptrader
```

## TimescaleDB

The database uses TimescaleDB for time-series data (market data, equity curves).
Hypertables are automatically created by migrations.
