-- Migration: 024_add_per_credential_configs.sql
-- Per-credential risk, execution, and UI configuration

-- ═══════════════════════════════════════════════════════════════
-- ADD CONFIG COLUMNS TO USER_EXCHANGE_CREDENTIALS
-- ═══════════════════════════════════════════════════════════════

-- Risk configuration per credential
-- Includes position sizing, leverage, daily loss limits, etc.
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS risk_config JSONB DEFAULT '{
  "positionSizePct": 0.10,
  "maxPositions": 4,
  "maxDailyLossPct": 0.05,
  "maxTotalExposurePct": 0.80,
  "maxLeverage": 1,
  "leverageMode": "isolated",
  "maxPositionsPerSymbol": 1,
  "maxDailyLossPerSymbolPct": 0.025
}'::jsonb;

-- Execution configuration per credential
-- Trading behavior, timeouts, order types, etc.
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS execution_config JSONB DEFAULT '{
  "defaultOrderType": "market",
  "stopLossPct": 0.02,
  "takeProfitPct": 0.05,
  "trailingStopEnabled": false,
  "trailingStopPct": 0.01,
  "maxHoldTimeHours": 24,
  "minTradeIntervalSec": 1.0,
  "executionTimeoutSec": 5.0,
  "closePositionTimeoutSec": 15.0,
  "enableVolatilityFilter": true,
  "volatilityShockCooldownSec": 30.0
}'::jsonb;

-- UI/UX preferences per credential
-- Dashboard display, notifications, theme, etc.
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS ui_preferences JSONB DEFAULT '{
  "showPnlInHeader": true,
  "notifyOnTrade": true,
  "notifyOnStopLoss": true,
  "notifyOnTakeProfit": true,
  "defaultChartTimeframe": "1h",
  "compactMode": false
}'::jsonb;

-- Config versioning for drift detection
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS config_version INTEGER DEFAULT 1;

ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS config_updated_at TIMESTAMPTZ DEFAULT NOW();

-- ═══════════════════════════════════════════════════════════════
-- ADD EXTENDED PROFILE FIELDS TO USER_TRADE_PROFILES
-- ═══════════════════════════════════════════════════════════════

-- Account balance override (for position sizing calculations)
ALTER TABLE user_trade_profiles
ADD COLUMN IF NOT EXISTS account_balance DECIMAL(20,2) DEFAULT 10000.00;

-- Global leverage settings (used when credential doesn't specify)
ALTER TABLE user_trade_profiles
ADD COLUMN IF NOT EXISTS global_max_leverage INTEGER DEFAULT 1;

ALTER TABLE user_trade_profiles
ADD COLUMN IF NOT EXISTS global_leverage_mode VARCHAR(32) DEFAULT 'isolated';

-- Active bot config snapshot (what the running bot is using)
ALTER TABLE user_trade_profiles
ADD COLUMN IF NOT EXISTS active_config_snapshot JSONB;

ALTER TABLE user_trade_profiles
ADD COLUMN IF NOT EXISTS active_config_version INTEGER;

-- ═══════════════════════════════════════════════════════════════
-- ADD BOT CONFIG AUDIT TABLE
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS credential_config_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id UUID NOT NULL REFERENCES user_exchange_credentials(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- What changed
    config_type VARCHAR(32) NOT NULL, -- risk_config, execution_config, ui_preferences
    old_value JSONB,
    new_value JSONB,
    changed_fields TEXT[], -- List of fields that changed
    
    -- Context
    change_reason TEXT, -- User-provided reason or system action
    changed_by VARCHAR(64), -- user, system, admin
    ip_address VARCHAR(64),
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_config_audit_credential ON credential_config_audit(credential_id);
CREATE INDEX IF NOT EXISTS idx_config_audit_user ON credential_config_audit(user_id);
CREATE INDEX IF NOT EXISTS idx_config_audit_created ON credential_config_audit(created_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- EXCHANGE LIMITS REFERENCE TABLE
-- ═══════════════════════════════════════════════════════════════
-- Stores exchange-imposed limits for validation

CREATE TABLE IF NOT EXISTS exchange_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange VARCHAR(32) NOT NULL,
    
    -- Leverage limits
    max_leverage INTEGER DEFAULT 125,
    default_leverage INTEGER DEFAULT 1,
    
    -- Position limits
    min_position_usd DECIMAL(20,2) DEFAULT 5.00,
    max_position_usd DECIMAL(20,2) DEFAULT 1000000.00,
    
    -- Risk limits
    min_stop_loss_pct DECIMAL(10,4) DEFAULT 0.001,
    max_daily_trades INTEGER DEFAULT 1000,
    
    -- Supported features
    supports_isolated_margin BOOLEAN DEFAULT true,
    supports_cross_margin BOOLEAN DEFAULT true,
    supports_trailing_stop BOOLEAN DEFAULT true,
    supports_bracket_orders BOOLEAN DEFAULT true,
    
    -- Metadata
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(exchange)
);

-- Insert default exchange limits
INSERT INTO exchange_limits (exchange, max_leverage, default_leverage, min_position_usd, supports_trailing_stop)
VALUES 
    ('okx', 125, 1, 5.00, true),
    ('binance', 125, 1, 5.00, true),
    ('bybit', 100, 1, 1.00, true)
ON CONFLICT (exchange) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════
-- COMMENTS
-- ═══════════════════════════════════════════════════════════════

COMMENT ON COLUMN user_exchange_credentials.risk_config IS 'Per-credential risk parameters: position sizing, leverage, loss limits';
COMMENT ON COLUMN user_exchange_credentials.execution_config IS 'Per-credential execution settings: SL/TP, timeouts, order types';
COMMENT ON COLUMN user_exchange_credentials.ui_preferences IS 'Per-credential UI preferences: notifications, display settings';
COMMENT ON COLUMN user_exchange_credentials.config_version IS 'Monotonically increasing version for config drift detection';
COMMENT ON TABLE credential_config_audit IS 'Audit trail of all configuration changes per credential';
COMMENT ON TABLE exchange_limits IS 'Exchange-imposed limits used for validation';


