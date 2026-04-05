-- Migration: 023_create_exchange_credentials_tables.sql
-- Per-user exchange credentials and trading profiles

-- ═══════════════════════════════════════════════════════════════
-- USER EXCHANGE CREDENTIALS
-- ═══════════════════════════════════════════════════════════════
-- Stores metadata about user's exchange connections
-- Actual secrets stored in AWS Secrets Manager / local keystore

CREATE TABLE IF NOT EXISTS user_exchange_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange VARCHAR(32) NOT NULL, -- okx, binance, bybit
    label VARCHAR(128), -- User-friendly name like "Main OKX Account"
    secret_id VARCHAR(256) NOT NULL, -- Reference to secrets manager path
    
    -- Status tracking
    status VARCHAR(32) DEFAULT 'pending', -- pending, verified, failed, disabled
    last_verified_at TIMESTAMPTZ,
    verification_error TEXT,
    permissions JSONB DEFAULT '[]'::jsonb, -- ['read', 'trade', 'withdraw']
    
    -- Metadata
    is_testnet BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(user_id, exchange, label),
    CONSTRAINT valid_exchange CHECK (exchange IN ('okx', 'binance', 'bybit'))
);

CREATE INDEX IF NOT EXISTS idx_exchange_creds_user ON user_exchange_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_exchange_creds_status ON user_exchange_credentials(status);

-- ═══════════════════════════════════════════════════════════════
-- USER TRADE PROFILES
-- ═══════════════════════════════════════════════════════════════
-- Stores user's active trading configuration

CREATE TABLE IF NOT EXISTS user_trade_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Active exchange selection
    active_credential_id UUID REFERENCES user_exchange_credentials(id) ON DELETE SET NULL,
    active_exchange VARCHAR(32), -- Denormalized for quick access
    
    -- Trading mode
    trading_mode VARCHAR(32) DEFAULT 'paper', -- paper, live
    
    -- Token configuration per exchange (JSONB for flexibility)
    -- Format: { "okx": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"], "binance": [...] }
    token_lists JSONB DEFAULT '{}'::jsonb,
    
    -- Default risk settings (can override bot profile)
    default_max_positions INTEGER DEFAULT 4,
    default_position_size_pct DECIMAL(10,4) DEFAULT 0.10,
    default_max_daily_loss_pct DECIMAL(10,4) DEFAULT 0.05,
    
    -- Bot assignment (for bot pool tracking)
    assigned_bot_id VARCHAR(128), -- Container/task ID in bot pool
    bot_assigned_at TIMESTAMPTZ,
    bot_status VARCHAR(32), -- pending, running, stopped, error
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- One profile per user
    UNIQUE(user_id)
);

CREATE INDEX IF NOT EXISTS idx_trade_profiles_user ON user_trade_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_profiles_bot ON user_trade_profiles(assigned_bot_id);

-- ═══════════════════════════════════════════════════════════════
-- BOT POOL ASSIGNMENTS
-- ═══════════════════════════════════════════════════════════════
-- Tracks bot container assignments in the pool

CREATE TABLE IF NOT EXISTS bot_pool_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id UUID REFERENCES user_exchange_credentials(id) ON DELETE SET NULL,
    
    -- Bot instance info
    bot_id VARCHAR(128) NOT NULL, -- ECS task ID, container ID, or local PID
    pool_node VARCHAR(128), -- Which pool node is running this bot
    instance_type VARCHAR(32) DEFAULT 'hot', -- hot, cold
    
    -- Status
    status VARCHAR(32) DEFAULT 'pending', -- pending, starting, running, stopping, stopped, error
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    error_message TEXT,
    
    -- Configuration snapshot (what config was used to start)
    config_snapshot JSONB,
    
    -- Metrics
    decisions_count BIGINT DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_assignments_user ON bot_pool_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_bot_assignments_status ON bot_pool_assignments(status);
CREATE INDEX IF NOT EXISTS idx_bot_assignments_bot_id ON bot_pool_assignments(bot_id);

-- ═══════════════════════════════════════════════════════════════
-- EXCHANGE TOKEN CATALOG
-- ═══════════════════════════════════════════════════════════════
-- Cache of available tokens per exchange (refreshed periodically)

CREATE TABLE IF NOT EXISTS exchange_token_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange VARCHAR(32) NOT NULL,
    symbol VARCHAR(64) NOT NULL, -- e.g., BTC-USDT-SWAP
    base_currency VARCHAR(16), -- BTC
    quote_currency VARCHAR(16), -- USDT
    contract_type VARCHAR(32), -- perpetual, quarterly, etc.
    
    -- Trading info
    min_size DECIMAL(20,8),
    tick_size DECIMAL(20,8),
    contract_value DECIMAL(20,8),
    is_active BOOLEAN DEFAULT true,
    
    -- Metadata
    exchange_symbol VARCHAR(64), -- Exchange's internal symbol
    metadata JSONB,
    
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(exchange, symbol)
);

CREATE INDEX IF NOT EXISTS idx_token_catalog_exchange ON exchange_token_catalog(exchange);
CREATE INDEX IF NOT EXISTS idx_token_catalog_active ON exchange_token_catalog(exchange, is_active);

-- ═══════════════════════════════════════════════════════════════
-- TRIGGER FOR UPDATED_AT
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_exchange_creds_updated_at ON user_exchange_credentials;
CREATE TRIGGER update_exchange_creds_updated_at
    BEFORE UPDATE ON user_exchange_credentials
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_trade_profiles_updated_at ON user_trade_profiles;
CREATE TRIGGER update_trade_profiles_updated_at
    BEFORE UPDATE ON user_trade_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_bot_assignments_updated_at ON bot_pool_assignments;
CREATE TRIGGER update_bot_assignments_updated_at
    BEFORE UPDATE ON bot_pool_assignments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ═══════════════════════════════════════════════════════════════
-- COMMENTS
-- ═══════════════════════════════════════════════════════════════

COMMENT ON TABLE user_exchange_credentials IS 'Per-user exchange API credential metadata (secrets stored externally)';
COMMENT ON TABLE user_trade_profiles IS 'User trading configuration including active exchange and token selection';
COMMENT ON TABLE bot_pool_assignments IS 'Tracks which bot instance is running for each user in the pool';
COMMENT ON TABLE exchange_token_catalog IS 'Cached catalog of available trading pairs per exchange';


