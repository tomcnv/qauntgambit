-- Order lifecycle tables for durable execution tracking

CREATE TABLE IF NOT EXISTS order_states (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    exchange TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    order_id TEXT,
    client_order_id TEXT,
    reason TEXT,
    fill_price DOUBLE PRECISION,
    fee_usd DOUBLE PRECISION,
    filled_size DOUBLE PRECISION,
    remaining_size DOUBLE PRECISION,
    state_source TEXT,
    raw_exchange_status TEXT,
    submitted_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    open_at TIMESTAMPTZ,
    filled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS order_states_order_id_idx
    ON order_states (tenant_id, bot_id, order_id)
    WHERE order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS order_states_client_order_id_idx
    ON order_states (tenant_id, bot_id, client_order_id)
    WHERE client_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS order_lifecycle_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    exchange TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    event_type TEXT,
    order_id TEXT,
    client_order_id TEXT,
    reason TEXT,
    fill_price DOUBLE PRECISION,
    fee_usd DOUBLE PRECISION,
    filled_size DOUBLE PRECISION,
    remaining_size DOUBLE PRECISION,
    state_source TEXT,
    raw_exchange_status TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS order_lifecycle_events_tenant_bot_idx
    ON order_lifecycle_events (tenant_id, bot_id, created_at DESC);

CREATE TABLE IF NOT EXISTS order_intents (
    intent_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    decision_id TEXT,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    take_profit DOUBLE PRECISION,
    strategy_id TEXT,
    profile_id TEXT,
    status TEXT NOT NULL,
    order_id TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ,
    -- Market conditions at entry time for post-trade analysis
    snapshot_metrics JSONB
);

-- Add snapshot_metrics column if it doesn't exist (for existing tables)
ALTER TABLE order_intents ADD COLUMN IF NOT EXISTS snapshot_metrics JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS order_intents_client_order_id_idx
    ON order_intents (tenant_id, bot_id, client_order_id);

CREATE INDEX IF NOT EXISTS order_intents_status_idx
    ON order_intents (tenant_id, bot_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS order_errors (
    error_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    exchange TEXT,
    symbol TEXT,
    order_id TEXT,
    client_order_id TEXT,
    stage TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS order_errors_tenant_bot_idx
    ON order_errors (tenant_id, bot_id, created_at DESC);
