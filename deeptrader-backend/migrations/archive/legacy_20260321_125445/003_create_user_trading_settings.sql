-- Migration: Create user trading settings table
-- Created: 2025-11-17

-- User trading settings table for customizable AI trading behavior
CREATE TABLE IF NOT EXISTS user_trading_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    enabled_order_types TEXT[] NOT NULL DEFAULT ARRAY['bracket'],
    order_type_settings JSONB NOT NULL,
    risk_profile VARCHAR(20) DEFAULT 'moderate',
    max_concurrent_positions INTEGER DEFAULT 4,
    max_position_size_percent DECIMAL(10,4) DEFAULT 0.10,
    max_total_exposure_percent DECIMAL(10,4) DEFAULT 0.40,
    ai_confidence_threshold DECIMAL(3,1) DEFAULT 7.0,
    trading_interval INTEGER DEFAULT 300000, -- 5 minutes in milliseconds
    enabled_tokens TEXT[] DEFAULT ARRAY['SOLUSDT'],
    per_token_settings JSONB DEFAULT '{}'::jsonb,
    day_trading_enabled BOOLEAN DEFAULT FALSE,
    scalping_mode BOOLEAN DEFAULT FALSE,
    trailing_stops_enabled BOOLEAN DEFAULT TRUE,
    partial_profits_enabled BOOLEAN DEFAULT TRUE,
    time_based_exits_enabled BOOLEAN DEFAULT TRUE,
    multi_timeframe_confirmation BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_trading_settings_user_id ON user_trading_settings(user_id);
CREATE INDEX IF NOT EXISTS idx_user_trading_settings_risk_profile ON user_trading_settings(risk_profile);

-- Comments for documentation
COMMENT ON TABLE user_trading_settings IS 'User-configurable settings for AI trading behavior and order type preferences';
COMMENT ON COLUMN user_trading_settings.enabled_order_types IS 'Array of order types the AI is allowed to use';
COMMENT ON COLUMN user_trading_settings.order_type_settings IS 'Detailed settings for each order type';
COMMENT ON COLUMN user_trading_settings.risk_profile IS 'Overall risk profile: conservative, moderate, aggressive';


