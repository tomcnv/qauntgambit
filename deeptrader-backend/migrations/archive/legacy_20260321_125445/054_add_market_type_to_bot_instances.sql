-- Add market_type column to bot_instances
-- Values: 'perp' (default, scalping/futures), 'spot' (spot trading)
ALTER TABLE bot_instances ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) NOT NULL DEFAULT 'perp';

-- Index for filtering bots by market type
CREATE INDEX IF NOT EXISTS idx_bot_instances_market_type ON bot_instances(market_type);

COMMENT ON COLUMN bot_instances.market_type IS 'Trading market type: perp (futures/scalping) or spot';
