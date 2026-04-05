-- Migration: 014a_telemetry_events
-- Description: Creates core telemetry Timescale/Postgres tables used by the runtime
--              (decision/order/prediction/etc event tables) before semantic-key
--              migrations run.
-- Date: 2026-02-18
--
-- Notes:
-- - This is intentionally idempotent (IF NOT EXISTS) because environments may
--   already have subsets of these tables.
-- - Extension creation is wrapped so non-Timescale Postgres doesn't hard-fail.

DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS timescaledb;
    EXCEPTION
        WHEN OTHERS THEN
            -- Extension not available (e.g. vanilla Postgres). Tables still work as plain tables.
            NULL;
    END;
END $$;

CREATE TABLE IF NOT EXISTS decision_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS order_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    semantic_key TEXT
);

CREATE TABLE IF NOT EXISTS prediction_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS latency_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS fee_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS position_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS orderbook_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS guardrail_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS order_update_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

-- Market data provider metrics (switch/failure events)
CREATE TABLE IF NOT EXISTS market_data_provider_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS market_candles (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    timeframe_sec INT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL
);

-- Convert to hypertables (Timescale) when available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('decision_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('order_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('prediction_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('latency_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('fee_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('risk_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('position_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('market_candles', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('orderbook_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('guardrail_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('order_update_events', 'ts', if_not_exists => TRUE);
        PERFORM create_hypertable('market_data_provider_events', 'ts', if_not_exists => TRUE);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS decision_events_idx ON decision_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS order_events_idx ON order_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS order_events_semantic_key_idx ON order_events (tenant_id, bot_id, semantic_key);
CREATE INDEX IF NOT EXISTS prediction_events_idx ON prediction_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS latency_events_idx ON latency_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS fee_events_idx ON fee_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS risk_events_idx ON risk_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS position_events_idx ON position_events (tenant_id, bot_id, ts DESC);
CREATE INDEX IF NOT EXISTS market_candles_idx ON market_candles (tenant_id, bot_id, symbol, timeframe_sec, ts DESC);
CREATE INDEX IF NOT EXISTS orderbook_events_idx ON orderbook_events (tenant_id, bot_id, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS guardrail_events_idx ON guardrail_events (tenant_id, bot_id, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS order_update_events_idx ON order_update_events (tenant_id, bot_id, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS market_data_provider_events_idx ON market_data_provider_events (tenant_id, bot_id, ts DESC);

