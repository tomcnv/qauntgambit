-- Migration: Add AI Filter Settings to user_trading_settings
-- Description: Adds 4 new fields to control AI-driven market regime filtering
-- Date: 2025-11-19

-- Add AI filter settings columns
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS ai_filter_enabled BOOLEAN DEFAULT true,
ADD COLUMN IF NOT EXISTS ai_filter_mode VARCHAR(20) DEFAULT 'filter_only',
ADD COLUMN IF NOT EXISTS ai_swing_trading_enabled BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS strategy_selection VARCHAR(50) DEFAULT 'amt_scalping';

-- Add comments for documentation
COMMENT ON COLUMN user_trading_settings.ai_filter_enabled IS 'Enable/disable AI regime analysis filter';
COMMENT ON COLUMN user_trading_settings.ai_filter_mode IS 'AI mode: filter_only (AI filters when to scalp) or full_control (AI makes all decisions)';
COMMENT ON COLUMN user_trading_settings.ai_swing_trading_enabled IS 'Enable AI-driven swing trading (future feature)';
COMMENT ON COLUMN user_trading_settings.strategy_selection IS 'Active strategy: amt_scalping, pure_technical, or ai_swing (future)';

-- Update existing rows to have default values
UPDATE user_trading_settings
SET 
    ai_filter_enabled = true,
    ai_filter_mode = 'filter_only',
    ai_swing_trading_enabled = false,
    strategy_selection = 'amt_scalping'
WHERE ai_filter_enabled IS NULL;

-- Create index for strategy selection queries
CREATE INDEX IF NOT EXISTS idx_user_trading_settings_strategy 
ON user_trading_settings(strategy_selection);

-- Log migration
DO $$
BEGIN
    RAISE NOTICE 'Migration 012: AI filter settings added successfully';
    RAISE NOTICE '  - ai_filter_enabled: Controls whether AI regime analysis is active';
    RAISE NOTICE '  - ai_filter_mode: filter_only (default) or full_control';
    RAISE NOTICE '  - ai_swing_trading_enabled: Future feature flag';
    RAISE NOTICE '  - strategy_selection: amt_scalping (default), pure_technical, ai_swing';
END $$;

