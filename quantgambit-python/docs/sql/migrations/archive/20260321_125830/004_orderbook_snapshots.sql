-- Migration: 004_orderbook_snapshots
-- Description: Creates orderbook_snapshots hypertable for live orderbook data storage
-- Feature: live-orderbook-data-storage
-- Requirements: 7.1 (hypertable partitioned by timestamp), 7.3 (efficient queries by symbol, exchange, time range), 
--               7.5 (JSONB compression), 5.3 (compression after 7 days, retention 30 days)
-- Date: 2026-01-15

-- Create orderbook_snapshots table
-- Stores point-in-time orderbook snapshots with 20 levels of bids/asks and derived metrics
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    seq BIGINT NOT NULL,
    bids JSONB NOT NULL,  -- [[price, size], ...] up to 20 levels
    asks JSONB NOT NULL,  -- [[price, size], ...] up to 20 levels
    spread_bps DOUBLE PRECISION NOT NULL,
    bid_depth_usd DOUBLE PRECISION NOT NULL,
    ask_depth_usd DOUBLE PRECISION NOT NULL,
    orderbook_imbalance DOUBLE PRECISION NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    bot_id TEXT NOT NULL DEFAULT 'default'
);

-- Convert to TimescaleDB hypertable when extension is available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('orderbook_snapshots', 'ts', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for efficient queries by symbol and time range (Requirement 7.3)
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_symbol_ts 
    ON orderbook_snapshots (symbol, ts DESC);

-- Create composite index for exchange + symbol + time range queries (Requirement 7.3)
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_exchange_symbol_ts 
    ON orderbook_snapshots (exchange, symbol, ts DESC);

-- Create index for tenant-based queries
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_tenant_ts
    ON orderbook_snapshots (tenant_id, ts DESC);

-- Enable compression/retention policies only when TimescaleDB is available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'add_compression_policy') THEN
        EXECUTE 'ALTER TABLE orderbook_snapshots SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = ''symbol, exchange'',
            timescaledb.compress_orderby = ''ts DESC''
        )';
        PERFORM add_compression_policy('orderbook_snapshots', INTERVAL '7 days', if_not_exists => TRUE);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'add_retention_policy') THEN
        PERFORM add_retention_policy('orderbook_snapshots', INTERVAL '30 days', if_not_exists => TRUE);
    END IF;
END $$;

-- Add comments for documentation
COMMENT ON TABLE orderbook_snapshots IS 
'TimescaleDB hypertable storing point-in-time orderbook snapshots with 20 levels of bids/asks and derived metrics (spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance)';

COMMENT ON COLUMN orderbook_snapshots.ts IS 'Timestamp of the orderbook snapshot';
COMMENT ON COLUMN orderbook_snapshots.symbol IS 'Trading pair symbol (e.g., BTC-USD)';
COMMENT ON COLUMN orderbook_snapshots.exchange IS 'Exchange name (e.g., binance, coinbase)';
COMMENT ON COLUMN orderbook_snapshots.seq IS 'Sequence number from the exchange for gap detection';
COMMENT ON COLUMN orderbook_snapshots.bids IS 'JSONB array of bid levels [[price, size], ...] up to 20 levels';
COMMENT ON COLUMN orderbook_snapshots.asks IS 'JSONB array of ask levels [[price, size], ...] up to 20 levels';
COMMENT ON COLUMN orderbook_snapshots.spread_bps IS 'Bid-ask spread in basis points: ((best_ask - best_bid) / mid_price) * 10000';
COMMENT ON COLUMN orderbook_snapshots.bid_depth_usd IS 'Total USD value of all bid orders: sum(price * size)';
COMMENT ON COLUMN orderbook_snapshots.ask_depth_usd IS 'Total USD value of all ask orders: sum(price * size)';
COMMENT ON COLUMN orderbook_snapshots.orderbook_imbalance IS 'Ratio of bid depth to total depth: bid_depth_usd / (bid_depth_usd + ask_depth_usd)';
COMMENT ON COLUMN orderbook_snapshots.tenant_id IS 'Multi-tenant identifier';
COMMENT ON COLUMN orderbook_snapshots.bot_id IS 'Bot identifier for filtering';

-- Rollback script (run manually if needed):
-- SELECT remove_retention_policy('orderbook_snapshots', if_exists => TRUE);
-- SELECT remove_compression_policy('orderbook_snapshots', if_exists => TRUE);
-- DROP INDEX IF EXISTS idx_orderbook_snapshots_tenant_ts;
-- DROP INDEX IF EXISTS idx_orderbook_snapshots_exchange_symbol_ts;
-- DROP INDEX IF EXISTS idx_orderbook_snapshots_symbol_ts;
-- DROP TABLE IF EXISTS orderbook_snapshots;
