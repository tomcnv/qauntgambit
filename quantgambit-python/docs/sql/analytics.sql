-- Shared analytics/risk/signals tables for dashboard visualizations
-- Target: Timescale/PG (run after bootstrap_databases.sql)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    decision TEXT,
    reason TEXT,
    score NUMERIC,
    timeframe TEXT,
    pnl NUMERIC,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signals_tenant_bot_created_idx ON signals (tenant_id, bot_id, created_at DESC);
CREATE INDEX IF NOT EXISTS signals_symbol_idx ON signals (symbol);

CREATE TABLE IF NOT EXISTS risk_incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    type TEXT,
    symbol TEXT,
    limit_hit TEXT,
    detail JSONB,
    pnl NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS risk_incidents_tenant_bot_created_idx ON risk_incidents (tenant_id, bot_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sltp_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    event_type TEXT,
    pnl NUMERIC,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sltp_events_tenant_bot_created_idx ON sltp_events (tenant_id, bot_id, created_at DESC);

CREATE TABLE IF NOT EXISTS market_context (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    symbol TEXT,
    spread_bps NUMERIC,
    depth_usd NUMERIC,
    funding_rate NUMERIC,
    iv NUMERIC,
    vol NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS market_context_tenant_bot_created_idx ON market_context (tenant_id, bot_id, created_at DESC);
CREATE INDEX IF NOT EXISTS market_context_symbol_idx ON market_context (symbol);

CREATE TABLE IF NOT EXISTS timeline_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    event_type TEXT,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS timeline_events_tenant_bot_created_idx ON timeline_events (tenant_id, bot_id, created_at DESC);
