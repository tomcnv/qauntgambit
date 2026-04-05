-- Migration: Add leverage trading settings to user_trading_settings table
-- Date: $(date)
-- Description: Add leverage-related columns for margin trading functionality

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS leverage_enabled BOOLEAN DEFAULT FALSE;

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS max_leverage DECIMAL(5,2) DEFAULT 1.0;

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS leverage_mode VARCHAR(20) DEFAULT 'isolated'
  CHECK (leverage_mode IN ('isolated', 'cross'));

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS liquidation_buffer_percent DECIMAL(10,4) DEFAULT 0.05;

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS margin_call_threshold_percent DECIMAL(10,4) DEFAULT 0.20;

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS available_leverage_levels DECIMAL(5,2)[]
  DEFAULT ARRAY[1.0, 2.0, 3.0, 5.0, 10.0];

-- Update existing records to have default values
UPDATE user_trading_settings
SET
  leverage_enabled = COALESCE(leverage_enabled, FALSE),
  max_leverage = COALESCE(max_leverage, 1.0),
  leverage_mode = COALESCE(leverage_mode, 'isolated'),
  liquidation_buffer_percent = COALESCE(liquidation_buffer_percent, 0.05),
  margin_call_threshold_percent = COALESCE(margin_call_threshold_percent, 0.20),
  available_leverage_levels = COALESCE(available_leverage_levels, ARRAY[1.0, 2.0, 3.0, 5.0, 10.0])
WHERE leverage_enabled IS NULL
   OR max_leverage IS NULL
   OR leverage_mode IS NULL
   OR liquidation_buffer_percent IS NULL
   OR margin_call_threshold_percent IS NULL
   OR available_leverage_levels IS NULL;
