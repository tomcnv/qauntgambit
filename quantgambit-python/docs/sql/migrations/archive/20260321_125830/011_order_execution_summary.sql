-- Order execution summary table derived from exchange executions.
-- This is the durable, exchange-authoritative source for order-level aggregates
-- (size/avg price/fees/pnl) and is used to eliminate drift vs exchange history.

CREATE TABLE IF NOT EXISTS order_execution_summary (
  tenant_id text NOT NULL,
  bot_id text NOT NULL,
  exchange text NOT NULL,
  order_id text NOT NULL,
  client_order_id text,
  symbol text NOT NULL,
  side text,
  exec_count integer NOT NULL DEFAULT 0,
  total_qty double precision,
  avg_price double precision,
  total_fee_usd double precision,
  exec_pnl double precision,
  first_exec_time_ms bigint,
  last_exec_time_ms bigint,
  source text NOT NULL DEFAULT 'execution_reconcile',
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, bot_id, exchange, order_id)
);

CREATE INDEX IF NOT EXISTS order_execution_summary_time_idx
  ON order_execution_summary(tenant_id, bot_id, exchange, last_exec_time_ms DESC);

