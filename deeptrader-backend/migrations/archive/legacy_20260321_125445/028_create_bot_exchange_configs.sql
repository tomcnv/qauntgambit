-- Migration: 028_create_bot_exchange_configs.sql
-- Bot-Exchange Attachments: Runtime binding of bot instance + credential + environment
-- This is the primary runtime unit that the engine reads

-- Create environment enum type
DO $$ BEGIN
    CREATE TYPE bot_environment AS ENUM ('dev', 'paper', 'live');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create state enum type
DO $$ BEGIN
    CREATE TYPE bot_config_state AS ENUM ('created', 'ready', 'running', 'paused', 'error', 'decommissioned');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS bot_exchange_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Core relationships
    bot_instance_id UUID NOT NULL REFERENCES bot_instances(id) ON DELETE CASCADE,
    credential_id UUID NOT NULL REFERENCES user_exchange_credentials(id) ON DELETE CASCADE,
    
    -- Environment is first-class
    environment bot_environment NOT NULL DEFAULT 'paper',
    
    -- Trading capital for this exchange attachment
    trading_capital_usd DECIMAL(20,2),
    
    -- Enabled symbols for this attachment
    enabled_symbols JSONB DEFAULT '[]'::jsonb, -- ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    
    -- Risk configuration overrides (merged with bot instance defaults)
    risk_config JSONB DEFAULT '{}'::jsonb,
    
    -- Execution configuration overrides
    execution_config JSONB DEFAULT '{}'::jsonb,
    
    -- Profile overrides for this exchange
    profile_overrides JSONB DEFAULT '{}'::jsonb,
    
    -- Lifecycle state
    state bot_config_state NOT NULL DEFAULT 'created',
    last_state_change TIMESTAMPTZ DEFAULT NOW(),
    last_error TEXT,
    
    -- Active flag (only one can be active per user at a time)
    is_active BOOLEAN DEFAULT false,
    activated_at TIMESTAMPTZ,
    
    -- Runtime metrics
    last_heartbeat_at TIMESTAMPTZ,
    decisions_count BIGINT DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    
    -- Versioning
    config_version INTEGER DEFAULT 1,
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Unique constraint: one config per bot + credential + environment
    UNIQUE(bot_instance_id, credential_id, environment)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_bot ON bot_exchange_configs(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_credential ON bot_exchange_configs(credential_id);
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_env ON bot_exchange_configs(environment);
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_state ON bot_exchange_configs(state);
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_active ON bot_exchange_configs(is_active) WHERE is_active = true;

-- Function to ensure only one active config per user
CREATE OR REPLACE FUNCTION ensure_single_active_bot_config()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_active = true THEN
        -- Deactivate all other configs for the same user
        UPDATE bot_exchange_configs bec
        SET is_active = false, updated_at = NOW()
        FROM bot_instances bi
        WHERE bec.bot_instance_id = bi.id
          AND bi.user_id = (SELECT user_id FROM bot_instances WHERE id = NEW.bot_instance_id)
          AND bec.id != NEW.id
          AND bec.is_active = true;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_ensure_single_active_bot_config ON bot_exchange_configs;
CREATE TRIGGER trigger_ensure_single_active_bot_config
    BEFORE INSERT OR UPDATE OF is_active ON bot_exchange_configs
    FOR EACH ROW
    WHEN (NEW.is_active = true)
    EXECUTE FUNCTION ensure_single_active_bot_config();

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_bot_exchange_configs_updated_at ON bot_exchange_configs;
CREATE TRIGGER update_bot_exchange_configs_updated_at
    BEFORE UPDATE ON bot_exchange_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Update user_trade_profiles to reference active_bot_exchange_config_id
ALTER TABLE user_trade_profiles
    ADD COLUMN IF NOT EXISTS active_bot_exchange_config_id UUID REFERENCES bot_exchange_configs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_trade_profiles_active_config ON user_trade_profiles(active_bot_exchange_config_id);

COMMENT ON TABLE bot_exchange_configs IS 'Runtime binding of bot instance + exchange credential + environment';
COMMENT ON COLUMN bot_exchange_configs.environment IS 'Trading environment: dev (local testing), paper (simulated), live (real money)';
COMMENT ON COLUMN bot_exchange_configs.state IS 'Lifecycle state: created -> ready -> running/paused/error -> decommissioned';
COMMENT ON COLUMN bot_exchange_configs.is_active IS 'Only one config can be active per user at a time';



