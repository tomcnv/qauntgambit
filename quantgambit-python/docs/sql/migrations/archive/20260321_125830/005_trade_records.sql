-- Migration: 005_trade_records
-- Description: Creates trade_records hypertable for live trade data storage
-- Feature: live-orderbook-data-storage
-- Requirements: 7.2 (hypertable partitioned by timestamp), 7.4 (efficient queries by symbol, exchange, time range, trade_id),
--               5.4 (compression after 7 days, retention 90 days)
-- Date: 2026-01-15

-- Create trade_records table
-- Stores individual trade records with symbol, exchange, price, size, side, and trade_id
CREATE TABLE IF NOT EXISTS trade_records (
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    side TEXT NOT NULL,  -- 'buy' or 'sell'
    trade_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    bot_id TEXT NOT NULL DEFAULT 'default'
);

-- Convert to TimescaleDB hypertable when extension is available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('trade_records', 'ts', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for efficient queries by symbol and time range (Requirement 7.4)
CREATE INDEX IF NOT EXISTS idx_trade_records_symbol_ts 
    ON trade_records (symbol, ts DESC);

-- Create composite index for exchange + symbol + time range queries (Requirement 7.4)
CREATE INDEX IF NOT EXISTS idx_trade_records_exchange_symbol_ts 
    ON trade_records (exchange, symbol, ts DESC);

-- Create index for trade_id lookups (Requirement 7.4)
CREATE INDEX IF NOT EXISTS idx_trade_records_trade_id 
    ON trade_records (trade_id);

-- Create index for tenant-based queries
CREATE INDEX IF NOT EXISTS idx_trade_records_tenant_ts
    ON trade_records (tenant_id, ts DESC);

-- Enable compression/retention policies only when TimescaleDB is available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'add_compression_policy') THEN
        EXECUTE 'ALTER TABLE trade_records SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = ''symbol, exchange'',
            timescaledb.compress_orderby = ''ts DESC''
        )';
        PERFORM add_compression_policy('trade_records', INTERVAL '7 days', if_not_exists => TRUE);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'add_retention_policy') THEN
        PERFORM add_retention_policy('trade_records', INTERVAL '90 days', if_not_exists => TRUE);
    END IF;
END $$;

-- Add comments for documentation
COMMENT ON TABLE trade_records IS 
'TimescaleDB hypertable storing individual trade records for VWAP calculation, volume profiles, and backtest replay';

COMMENT ON COLUMN trade_records.ts IS 'Timestamp of the trade (original exchange timestamp for accurate replay)';
COMMENT ON COLUMN trade_records.symbol IS 'Trading pair symbol (e.g., BTC-USD)';
COMMENT ON COLUMN trade_records.exchange IS 'Exchange name (e.g., binance, coinbase)';
COMMENT ON COLUMN trade_records.price IS 'Trade execution price';
COMMENT ON COLUMN trade_records.size IS 'Trade size/quantity';
COMMENT ON COLUMN trade_records.side IS 'Trade side: buy or sell';
COMMENT ON COLUMN trade_records.trade_id IS 'Unique trade identifier from the exchange';
COMMENT ON COLUMN trade_records.tenant_id IS 'Multi-tenant identifier';
COMMENT ON COLUMN trade_records.bot_id IS 'Bot identifier for filtering';

-- Rollback script (run manually if needed):
-- SELECT remove_retention_policy('trade_records', if_exists => TRUE);
-- SELECT remove_compression_policy('trade_records', if_exists => TRUE);
-- DROP INDEX IF EXISTS idx_trade_records_tenant_ts;
-- DROP INDEX IF EXISTS idx_trade_records_trade_id;
-- DROP INDEX IF EXISTS idx_trade_records_exchange_symbol_ts;
-- DROP INDEX IF EXISTS idx_trade_records_symbol_ts;
-- DROP TABLE IF EXISTS trade_records;
