# Startup

## Recommended Full Local Flow

From the repository root:

```bash
./start-dev.sh --all --bot
```

This is the main local development entrypoint. It is intended to:

- start Docker-backed dependencies
- launch the backend API
- launch the dashboard
- launch the Python bot/API services when `--bot` is supplied
- optionally bring up the landing page and nginx

Useful variants:

```bash
./start-dev.sh
./start-dev.sh --no-nginx
./start-dev.sh --no-landing --bot
```

## PM2 Flow

The root `package.json` still exposes a PM2-based startup path:

```bash
npm start
npm stop
npm run status
```

This is useful when you want the legacy process manager workflow instead of the broader development script.

## Service-by-Service Startup

Dashboard:

```bash
cd deeptrader-dashhboard
npm run dev
```

Backend:

```bash
cd deeptrader-backend
npm run dev
```

Python API:

```bash
cd quantgambit-python
source venv/bin/activate
python -m quantgambit.api.app
```

## Infrastructure

Primary local Docker stack:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Minimal Redis-only stack:

```bash
docker compose up -d
```

## Shutdown

Primary shutdown paths:

```bash
./stop-dev.sh
npm stop
./stop-all.sh
```

## Useful Checks

```bash
pm2 list
docker ps
lsof -i :3001
lsof -i :5173
```

## Notes

- `start-all.sh` and `stop-all.sh` are legacy wrappers and are still referenced by some package scripts.
- spot-specific flows source `.env.spot`; keep a local copy derived from `.env.spot.example`.
