ALTER TABLE order_events
ADD COLUMN IF NOT EXISTS semantic_key TEXT;

UPDATE order_events
SET semantic_key = CASE
    WHEN COALESCE(payload->>'event_id', '') <> '' THEN 'ev:' || (payload->>'event_id')
    WHEN COALESCE(payload->>'order_id', '') <> '' OR COALESCE(payload->>'client_order_id', '') <> '' THEN
        concat_ws(
            '|',
            'ord',
            COALESCE(payload->>'order_id', ''),
            COALESCE(payload->>'client_order_id', ''),
            COALESCE(payload->>'status', ''),
            COALESCE(payload->>'event_type', ''),
            COALESCE(payload->>'reason', ''),
            COALESCE(payload->>'filled_size', ''),
            COALESCE(payload->>'remaining_size', ''),
            COALESCE(payload->>'fill_price', ''),
            COALESCE(payload->>'fee_usd', '')
        )
    ELSE 'raw:' || substring(md5(COALESCE(payload::text, '') || '|' || COALESCE(ts::text, '')) for 24)
END
WHERE semantic_key IS NULL;

CREATE INDEX IF NOT EXISTS order_events_semantic_key_idx
ON order_events (tenant_id, bot_id, semantic_key);
