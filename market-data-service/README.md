Market Data Service (shared ingestion)
======================================

Purpose
-------
- Maintain shared orderbook/trade/ticker ingestion per exchange/market-type.
- Publish normalized snapshots + deltas to tenant-neutral streams (Redis Streams).
- Expose health (staleness, reconnects, checksum drift) via Redis keys and an optional HTTP endpoint.
- Keep runtime/trading processes consumer-only; they never own ingestion.

Responsibilities
----------------
- Manage WS connections per exchange/market-type for a curated symbol set.
- Periodic snapshots (e.g., 30–60s) plus deltas to `orderbook:{exchange}:{symbol}`.
- Health keys: `orderbook_health:{exchange}:{symbol}` with last_ts, staleness_ms, reconnects, checksum_status.
- Symbol registry/quota: load symbols from config; enforce max per exchange.
- Fan-out model: collect once, share many.

Config sketch (env)
-------------------
- EXCHANGE=okx|bybit|binance (can run multiple processes for multiple exchanges)
- MARKET_TYPE=perp|spot
- SYMBOLS=BTC-USDT-SWAP,ETH-USDT-SWAP (normalized per exchange)
- REDIS_URL=redis://localhost:6379
- SNAPSHOT_INTERVAL_SEC=30
- HEALTH_STALENESS_MS=5000
- MAX_SYMBOLS_PER_PROCESS=25

Design notes
------------
- Use `quantgambit.ingest.orderbook_ws` providers for WS ingestion.
- Writer publishes to Redis Streams and a Redis hash for “latest book”.
- Consumers (bot runtimes, dashboard) hydrate from snapshot+delta.
- Trades/tickers optional: `trades:{exchange}:{symbol}`, `ticker:{exchange}:{symbol}`.

Run (dev)
---------
- `python -m market_data_service.app` (from repo root ensure PYTHONPATH includes quantgambit-python).
- Or Docker: `docker build -t mds . && docker run --env EXCHANGE=okx --env SYMBOLS=BTC-USDT-SWAP -p 8081:8081 mds`.
  - Optional: `-e PUBLISH_MODE=both -e ORDERBOOK_EVENT_STREAM=events:orderbook_feed -e TRADES_ENABLED=true -e TICKERS_ENABLED=true`

Deps
----
- See `market-data-service/requirements.txt`. Dockerfile provided (assumes repo context includes quantgambit-python).

Status
------
- Skeleton only. Implement the writer/health loop and CLI args next.
