-- Migration: 042_add_percentage_based_capital.sql
-- Add percentage-based trading capital configuration
-- This allows capital to scale automatically with account balance

-- Add new percentage-based capital columns
ALTER TABLE bot_exchange_configs
    ADD COLUMN IF NOT EXISTS trading_capital_pct DECIMAL(10,4) DEFAULT 0.80,
    ADD COLUMN IF NOT EXISTS min_trading_capital_usd DECIMAL(20,2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS max_trading_capital_usd DECIMAL(20,2) DEFAULT NULL;

-- Add position_size_pct if not exists (may already exist)
ALTER TABLE bot_exchange_configs
    ADD COLUMN IF NOT EXISTS position_size_pct DECIMAL(10,4) DEFAULT 0.10;

-- Update existing configs to use sensible defaults
-- If they had a fixed trading_capital_usd, set that as the max cap
UPDATE bot_exchange_configs
SET 
    trading_capital_pct = 0.80,
    max_trading_capital_usd = trading_capital_usd
WHERE trading_capital_pct IS NULL AND trading_capital_usd IS NOT NULL;

-- Add comments
COMMENT ON COLUMN bot_exchange_configs.trading_capital_pct IS 'Percentage of account balance to use as trading capital (default 80%)';
COMMENT ON COLUMN bot_exchange_configs.min_trading_capital_usd IS 'Optional minimum trading capital floor in USD';
COMMENT ON COLUMN bot_exchange_configs.max_trading_capital_usd IS 'Optional maximum trading capital ceiling in USD';
COMMENT ON COLUMN bot_exchange_configs.position_size_pct IS 'Percentage of trading capital per position (default 10%)';

-- Add check constraints
ALTER TABLE bot_exchange_configs
    DROP CONSTRAINT IF EXISTS check_trading_capital_pct_range;
ALTER TABLE bot_exchange_configs
    ADD CONSTRAINT check_trading_capital_pct_range 
    CHECK (trading_capital_pct >= 0.01 AND trading_capital_pct <= 1.00);

ALTER TABLE bot_exchange_configs
    DROP CONSTRAINT IF EXISTS check_position_size_pct_range;
ALTER TABLE bot_exchange_configs
    ADD CONSTRAINT check_position_size_pct_range 
    CHECK (position_size_pct >= 0.001 AND position_size_pct <= 1.00);

ALTER TABLE bot_exchange_configs
    DROP CONSTRAINT IF EXISTS check_min_max_capital;
ALTER TABLE bot_exchange_configs
    ADD CONSTRAINT check_min_max_capital 
    CHECK (min_trading_capital_usd IS NULL OR max_trading_capital_usd IS NULL OR min_trading_capital_usd <= max_trading_capital_usd);




