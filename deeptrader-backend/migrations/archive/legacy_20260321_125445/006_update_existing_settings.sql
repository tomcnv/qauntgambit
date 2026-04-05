-- Migration: Update existing user settings with new trading hours defaults
-- Created: 2025-11-17

-- Update any existing records that don't have the new fields
UPDATE user_trading_settings
SET 
  day_trading_start_time = COALESCE(day_trading_start_time, '09:30:00'),
  day_trading_end_time = COALESCE(day_trading_end_time, '15:30:00'),
  day_trading_days_only = COALESCE(day_trading_days_only, FALSE)
WHERE day_trading_start_time IS NULL 
   OR day_trading_end_time IS NULL 
   OR day_trading_days_only IS NULL;
