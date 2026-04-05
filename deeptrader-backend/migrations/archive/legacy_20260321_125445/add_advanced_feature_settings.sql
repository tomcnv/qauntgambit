-- Add detailed configuration columns for advanced trading features
-- Migration: add_advanced_feature_settings
-- Date: 2025-11-17

-- Add columns for Day Trading Mode configuration
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS day_trading_max_holding_hours DECIMAL(10, 2) DEFAULT 8.0,
ADD COLUMN IF NOT EXISTS day_trading_force_close_time TIME DEFAULT '15:45:00';

-- Add columns for Scalping Mode configuration
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS scalping_target_profit_percent DECIMAL(10, 4) DEFAULT 0.005,
ADD COLUMN IF NOT EXISTS scalping_max_holding_minutes INTEGER DEFAULT 15,
ADD COLUMN IF NOT EXISTS scalping_min_volume_multiplier DECIMAL(10, 2) DEFAULT 2.0;

-- Add columns for Trailing Stops configuration
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS trailing_stop_activation_percent DECIMAL(10, 4) DEFAULT 0.02,
ADD COLUMN IF NOT EXISTS trailing_stop_callback_percent DECIMAL(10, 4) DEFAULT 0.01,
ADD COLUMN IF NOT EXISTS trailing_stop_step_percent DECIMAL(10, 4) DEFAULT 0.005;

-- Add columns for Partial Profit Taking configuration
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS partial_profit_levels JSONB DEFAULT '[
  {"percent": 25, "target": 0.03},
  {"percent": 25, "target": 0.05},
  {"percent": 25, "target": 0.08},
  {"percent": 25, "target": 0.12}
]'::jsonb;

-- Add columns for Time-Based Exits configuration
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS time_exit_max_holding_hours DECIMAL(10, 2) DEFAULT 24.0,
ADD COLUMN IF NOT EXISTS time_exit_break_even_hours DECIMAL(10, 2) DEFAULT 4.0,
ADD COLUMN IF NOT EXISTS time_exit_weekend_close BOOLEAN DEFAULT true;

-- Add columns for Multi-Timeframe Confirmation configuration
ALTER TABLE user_trading_settings
ADD COLUMN IF NOT EXISTS mtf_required_timeframes TEXT[] DEFAULT ARRAY['15m', '1h', '4h'],
ADD COLUMN IF NOT EXISTS mtf_min_confirmations INTEGER DEFAULT 2,
ADD COLUMN IF NOT EXISTS mtf_trend_alignment_required BOOLEAN DEFAULT true;

-- Add comment
COMMENT ON COLUMN user_trading_settings.day_trading_max_holding_hours IS 'Maximum hours to hold a position in day trading mode';
COMMENT ON COLUMN user_trading_settings.scalping_target_profit_percent IS 'Target profit percentage for scalping trades';
COMMENT ON COLUMN user_trading_settings.trailing_stop_activation_percent IS 'Profit % needed before trailing stop activates';
COMMENT ON COLUMN user_trading_settings.partial_profit_levels IS 'Array of profit taking levels with position % and target %';
COMMENT ON COLUMN user_trading_settings.time_exit_max_holding_hours IS 'Maximum hours to hold any position';
COMMENT ON COLUMN user_trading_settings.mtf_required_timeframes IS 'Timeframes required for multi-timeframe confirmation';
