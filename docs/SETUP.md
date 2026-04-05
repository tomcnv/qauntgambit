# Setup

## Prerequisites

- Node.js 18+
- Python 3.11+
- Docker or Colima
- `npm`, `pip`, and `venv`

## Install Dependencies

Root utilities:

```bash
npm install
```

Backend:

```bash
cd deeptrader-backend
npm install
```

Dashboard:

```bash
cd deeptrader-dashhboard
npm install
```

Python runtime:

```bash
cd quantgambit-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Environment Files

Create local runtime files from examples:

```bash
cp env.example .env
cp .env.spot.example .env.spot
```

Minimum fields to review before running against any real exchange:

- exchange credentials
- `BOT_ID`
- `TENANT_ID`
- `EXCHANGE_ACCOUNT_ID`
- database and Redis connection settings

## Local Infrastructure

Start the local data services:

```bash
docker compose -f docker/docker-compose.yml up -d
```

The repository also includes a small Redis-only root compose file:

```bash
docker compose up -d
```

## First Run

For the main local development flow:

```bash
./start-dev.sh --all --bot
```

For a lighter PM2-based flow:

```bash
npm start
```

## Verification

Basic checks after startup:

```bash
docker ps
pm2 list
curl http://localhost:3001/health || true
```

If you are only working on one surface area, run its native dev server directly instead of the full stack.
