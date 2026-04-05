-- Migration: Add trading hours configuration for day trading mode
-- Created: 2025-11-17

-- Add trading hours fields to user_trading_settings
ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS day_trading_start_time TIME DEFAULT '09:30:00';

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS day_trading_end_time TIME DEFAULT '15:30:00';

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS day_trading_force_close_time TIME DEFAULT '15:45:00';

ALTER TABLE user_trading_settings
  ADD COLUMN IF NOT EXISTS day_trading_days_only BOOLEAN DEFAULT FALSE;

-- Add comments for clarity
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='user_trading_settings' AND column_name='day_trading_start_time'
  ) THEN
    COMMENT ON COLUMN user_trading_settings.day_trading_start_time IS 'Time to start opening new positions (day trading mode)';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='user_trading_settings' AND column_name='day_trading_end_time'
  ) THEN
    COMMENT ON COLUMN user_trading_settings.day_trading_end_time IS 'Time to stop opening new positions (day trading mode)';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='user_trading_settings' AND column_name='day_trading_force_close_time'
  ) THEN
    COMMENT ON COLUMN user_trading_settings.day_trading_force_close_time IS 'Time to force close all positions (day trading mode)';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='user_trading_settings' AND column_name='day_trading_days_only'
  ) THEN
    COMMENT ON COLUMN user_trading_settings.day_trading_days_only IS 'Only trade Monday-Friday (skip weekends)';
  END IF;
END $$;

