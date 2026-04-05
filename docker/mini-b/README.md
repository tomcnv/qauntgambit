# Mini-b.local infra stack

Compose bundle to run shared dev infra (platform Postgres + bot Timescale) on mini-b.local. Ports mirror local dev defaults:

- Redis: 6379 (recommended: Homebrew on host)
- Platform Postgres: 5432
- Bot/Timescale: 5433

## Quick start

```bash
cd docker/mini-b
cp .env.example .env    # adjust passwords/db names if desired
brew services start redis
docker compose up -d
```

## Connecting

- Redis: `redis://localhost:6379` (Homebrew)
- Platform DB: `postgresql://PLATFORM_DB_USER:PLATFORM_DB_PASSWORD@mini-b.local:5432/PLATFORM_DB_NAME`
- Bot/Timescale: `postgresql://BOT_DB_USER:BOT_DB_PASSWORD@mini-b.local:5433/BOT_DB_NAME`

## Optional: Redis in Docker

If you explicitly want Redis in Docker (not recommended for this repo's local dev convention):

```bash
docker compose --profile container-redis up -d redis
```

## Maintenance

- Stop: `docker compose down`
- Clean data: `docker compose down -v` (drops volumes)
- Logs: `docker compose logs -f`

## Notes

- Images are multi-arch and should run on the M4 Mac mini.
- Timescale is pinned to pg14 for compatibility with existing schemas. Adjust if you migrate.

## Load schemas

Run the helper to load platform + bot schemas from `quantgambit-python/docs/sql`:

```bash
cd docker/mini-b
chmod +x load-schemas.sh
./load-schemas.sh
```
