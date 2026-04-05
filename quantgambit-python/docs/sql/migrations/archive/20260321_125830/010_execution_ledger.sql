-- Canonical exchange execution ledger (idempotent, append/update by exec_id).
-- This table is the long-term source of truth for fills from exchange.

CREATE TABLE IF NOT EXISTS execution_ledger (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    exchange text NOT NULL,
    exec_id text NOT NULL,
    order_id text,
    client_order_id text,
    symbol text NOT NULL,
    side text,
    exec_price double precision,
    exec_qty double precision,
    exec_value double precision,
    exec_fee_usd double precision,
    exec_time_ms bigint,
    source text NOT NULL DEFAULT 'execution_sync',
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, bot_id, exchange, exec_id)
);

CREATE INDEX IF NOT EXISTS execution_ledger_order_idx
    ON execution_ledger(tenant_id, bot_id, exchange, order_id);

CREATE INDEX IF NOT EXISTS execution_ledger_time_idx
    ON execution_ledger(tenant_id, bot_id, exchange, exec_time_ms DESC);
