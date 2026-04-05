ALTER TABLE order_events
  ADD COLUMN IF NOT EXISTS order_id text,
  ADD COLUMN IF NOT EXISTS client_order_id text,
  ADD COLUMN IF NOT EXISTS event_type text,
  ADD COLUMN IF NOT EXISTS status text,
  ADD COLUMN IF NOT EXISTS reason text,
  ADD COLUMN IF NOT EXISTS fill_price double precision,
  ADD COLUMN IF NOT EXISTS filled_size double precision,
  ADD COLUMN IF NOT EXISTS fee_usd double precision;

UPDATE order_events
SET
  order_id = COALESCE(order_id, NULLIF(trim(payload->>'order_id'), '')),
  client_order_id = COALESCE(client_order_id, NULLIF(trim(payload->>'client_order_id'), '')),
  event_type = COALESCE(event_type, NULLIF(trim(payload->>'event_type'), '')),
  status = COALESCE(status, NULLIF(trim(payload->>'status'), '')),
  reason = COALESCE(reason, NULLIF(trim(payload->>'reason'), '')),
  fill_price = COALESCE(fill_price, NULLIF(payload->>'fill_price', '')::double precision),
  filled_size = COALESCE(filled_size, NULLIF(payload->>'filled_size', '')::double precision),
  fee_usd = COALESCE(fee_usd, NULLIF(payload->>'fee_usd', '')::double precision)
WHERE
  order_id IS NULL
  OR client_order_id IS NULL
  OR event_type IS NULL
  OR status IS NULL
  OR reason IS NULL
  OR fill_price IS NULL
  OR filled_size IS NULL
  OR fee_usd IS NULL;

CREATE INDEX IF NOT EXISTS order_events_order_id_idx
  ON order_events (tenant_id, bot_id, order_id, ts DESC)
  WHERE order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS order_events_status_idx
  ON order_events (tenant_id, bot_id, status, ts DESC)
  WHERE status IS NOT NULL;
