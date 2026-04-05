# DeepTrader

DeepTrader is a multi-service crypto trading platform built around a React operator dashboard, a Node.js backend, and the QuantGambit Python trading runtime.

The repository contains the full local development stack:

- `deeptrader-dashhboard/`: React dashboard and operator UI
- `deeptrader-backend/`: Node.js backend and control-plane API
- `quantgambit-python/`: Python trading runtime, FastAPI endpoints, strategies, and tests
- `market-data-service/`: market data ingestion service
- `docker/` and `docker-compose.yml`: local infrastructure for Redis and Postgres/Timescale services
- `infrastructure/`: Terraform and deployment assets

## System Overview

At a high level, the dashboard talks to the Node.js backend, the backend coordinates state and control flows, and the Python runtime executes the trading pipeline and publishes telemetry. Redis is used for streams and coordination; Postgres/Timescale stores platform and trading data.

```text
Dashboard (React)
    |
    v
Backend API (Node.js)
    |
    +--> Redis streams / control state
    |
    +--> Platform DB
    |
    v
QuantGambit Runtime (Python)
    |
    +--> Exchange adapters
    +--> Strategy / risk / execution pipeline
    +--> Timescale trading telemetry
```

## Hot Path And Cold Path

The system is split between a hot path and a cold path.

`Hot path` means the latency-sensitive trading loop. This is the path that has to stay fast and predictable because it is directly involved in live decisions and execution:

- market data intake from exchanges
- feature generation and signal staging
- risk checks and position sizing
- order intent creation and execution
- order and position state updates

In practice, the hot path mostly lives in [`quantgambit-python/`](./quantgambit-python/) with Redis streams used to move state between runtime components. This path should avoid heavy reporting queries, manual workflows, or anything that can block decision latency.

`Cold path` means the slower support workflows around the trading engine. These are important, but they are not on the critical execution loop:

- dashboard reads and operator workflows
- reporting, audits, and replay analysis
- schema migrations and retention jobs
- documentation, configuration management, and background maintenance
- backtests, model training, and historical analytics

The cold path mostly lives in [`deeptrader-backend/`](./deeptrader-backend/), [`deeptrader-dashhboard/`](./deeptrader-dashhboard/), and operational scripts under [`scripts/`](./scripts/). A core design goal of the project is to keep cold-path work from interfering with hot-path execution.

## Repository Status

This repository has been cleaned for public source control:

- removed local secrets, generated outputs, duplicate `* 2.*` files, and archived internal workspaces
- reduced top-level markdown clutter to a focused docs set
- added example environment files instead of tracked local runtime secrets

## Quick Start

### 1. Install dependencies

Frontend and backend:

```bash
npm install
cd deeptrader-backend && npm install
cd ../deeptrader-dashhboard && npm install
```

Python runtime:

```bash
cd quantgambit-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create environment files

```bash
cp env.example .env
cp .env.spot.example .env.spot
```

Then fill in any required exchange credentials and bot identifiers.

### 3. Start local infrastructure

```bash
docker compose -f docker/docker-compose.yml up -d
```

### 4. Start the app stack

Recommended:

```bash
./start-dev.sh --all --bot
```

Legacy PM2 flow:

```bash
npm start
```

## Development Entry Points

- Dashboard dev server: `cd deeptrader-dashhboard && npm run dev`
- Backend API: `cd deeptrader-backend && npm run dev`
- Python API/runtime: `cd quantgambit-python && python -m quantgambit.api.app`
- Full stack launcher: `./start-dev.sh`

## Documentation

Focused operational docs live in [`docs/README.md`](./docs/README.md).

Useful starting points:

- [`docs/SETUP.md`](./docs/SETUP.md)
- [`docs/STARTUP.md`](./docs/STARTUP.md)
- [`quantgambit-python/README.md`](./quantgambit-python/README.md)

## Testing

Representative entry points:

```bash
cd deeptrader-backend && npm test
cd quantgambit-python && pytest
```

The Python runtime contains the bulk of the automated strategy, property, and integration coverage.

## Security

Do not commit local `.env*`, `.secret-*`, `.secrets/`, runtime exports, or model registry outputs. The ignore rules in [`.gitignore`](./.gitignore) have been tightened to keep those out of source control.
