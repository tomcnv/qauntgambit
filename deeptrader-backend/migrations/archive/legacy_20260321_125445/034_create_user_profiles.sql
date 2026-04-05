-- Migration: 034_create_user_profiles.sql
-- User Chessboard Profiles: Customizable trading profiles with strategy composition
-- Supports Dev -> Paper -> Live promotion workflow with versioning

-- Create environment enum if not exists
DO $$ BEGIN
    CREATE TYPE profile_environment AS ENUM ('dev', 'paper', 'live');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create profile status enum if not exists
DO $$ BEGIN
    CREATE TYPE profile_status AS ENUM ('draft', 'active', 'disabled', 'archived');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS user_chessboard_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Identity
    name VARCHAR(255) NOT NULL,
    description TEXT,
    base_profile_id VARCHAR(100),  -- Optional: based on canonical profile (e.g., "micro_range_mean_reversion")
    
    -- Environment (Dev/Paper/Live)
    environment profile_environment NOT NULL DEFAULT 'dev',
    
    -- Composed strategies (references strategy_instances)
    strategy_composition JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Format: [
    --   {"instance_id": "uuid", "weight": 1.0, "priority": 1, "enabled": true},
    --   {"instance_id": "uuid", "weight": 0.5, "priority": 2, "enabled": true}
    -- ]
    
    -- Risk Controls
    risk_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "risk_per_trade_pct": 1.0,
    --   "max_leverage": 3.0,
    --   "max_positions": 4,
    --   "stop_loss_pct": 0.5,
    --   "take_profit_pct": 1.5,
    --   "max_drawdown_pct": 5.0,
    --   "max_daily_loss_pct": 3.0
    -- }
    
    -- Market Condition Gates
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "required_session": "us",  -- asia, europe, us, overnight, any
    --   "required_volatility": "normal",  -- low, normal, high, any
    --   "required_trend": "any",  -- up, down, flat, any
    --   "max_spread_bps": 10,
    --   "min_depth_usd": 10000,
    --   "min_volume_24h": 1000000
    -- }
    
    -- Lifecycle Rules
    lifecycle JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "cooldown_seconds": 60,
    --   "disable_after_consecutive_losses": 5,
    --   "protection_mode_threshold_pct": 50,  -- Enable protection when profit reaches this % of max daily loss
    --   "warmup_seconds": 300,
    --   "max_trades_per_hour": 20
    -- }
    
    -- Execution Preferences
    execution JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- {
    --   "order_type_preference": "bracket",  -- market, limit, bracket, oco
    --   "maker_taker_bias": 0.5,  -- 0 = full maker, 1 = full taker
    --   "max_slippage_bps": 5,
    --   "time_in_force": "GTC",
    --   "reduce_only_exits": true
    -- }
    
    -- Status
    status profile_status NOT NULL DEFAULT 'draft',
    is_active BOOLEAN DEFAULT false,  -- Whether this profile is active for trading
    
    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    promoted_from_id UUID REFERENCES user_chessboard_profiles(id),
    promoted_at TIMESTAMPTZ,
    promotion_notes TEXT,
    
    -- Paper burn-in tracking (required before Live promotion)
    paper_start_at TIMESTAMPTZ,
    paper_trades_count INTEGER DEFAULT 0,
    paper_pnl_total DECIMAL(20, 8) DEFAULT 0,
    
    -- Tags for organization
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Each user can only have one profile with a given name per environment
    UNIQUE(user_id, name, environment)
);

-- Profile version history (audit trail)
CREATE TABLE IF NOT EXISTS profile_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES user_chessboard_profiles(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    
    -- Snapshot of all config at this version
    config_snapshot JSONB NOT NULL,
    -- Contains: strategy_composition, risk_config, conditions, lifecycle, execution
    
    -- Change tracking
    change_summary TEXT,  -- Auto-generated summary of what changed
    changed_by UUID REFERENCES users(id),
    change_reason TEXT,  -- Required for Live profile changes
    
    -- Diff from previous version
    diff_from_previous JSONB,  -- {"added": [...], "removed": [...], "modified": [...]}
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(profile_id, version)
);

-- Indexes for user_chessboard_profiles
CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_chessboard_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_env ON user_chessboard_profiles(environment);
CREATE INDEX IF NOT EXISTS idx_user_profiles_status ON user_chessboard_profiles(status);
CREATE INDEX IF NOT EXISTS idx_user_profiles_active ON user_chessboard_profiles(is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_user_profiles_user_env ON user_chessboard_profiles(user_id, environment);
CREATE INDEX IF NOT EXISTS idx_user_profiles_base ON user_chessboard_profiles(base_profile_id);

-- Indexes for profile_versions
CREATE INDEX IF NOT EXISTS idx_profile_versions_profile ON profile_versions(profile_id);
CREATE INDEX IF NOT EXISTS idx_profile_versions_profile_version ON profile_versions(profile_id, version);

-- Function to create version snapshot on profile update
CREATE OR REPLACE FUNCTION create_profile_version_snapshot()
RETURNS TRIGGER AS $$
DECLARE
    config_snap JSONB;
    prev_config JSONB;
    diff_result JSONB;
BEGIN
    -- Build config snapshot
    config_snap := jsonb_build_object(
        'strategy_composition', NEW.strategy_composition,
        'risk_config', NEW.risk_config,
        'conditions', NEW.conditions,
        'lifecycle', NEW.lifecycle,
        'execution', NEW.execution,
        'status', NEW.status,
        'is_active', NEW.is_active
    );
    
    -- Get previous version's config for diff
    SELECT config_snapshot INTO prev_config
    FROM profile_versions
    WHERE profile_id = NEW.id
    ORDER BY version DESC
    LIMIT 1;
    
    -- Simple diff (just track that something changed)
    IF prev_config IS NOT NULL THEN
        diff_result := jsonb_build_object(
            'previous_version', OLD.version,
            'fields_changed', (
                SELECT jsonb_agg(key)
                FROM jsonb_each(config_snap) AS new_kv
                WHERE NOT EXISTS (
                    SELECT 1 FROM jsonb_each(prev_config) AS old_kv
                    WHERE old_kv.key = new_kv.key AND old_kv.value = new_kv.value
                )
            )
        );
    END IF;
    
    -- Insert version record
    INSERT INTO profile_versions (profile_id, version, config_snapshot, changed_by, diff_from_previous)
    VALUES (NEW.id, NEW.version, config_snap, NEW.user_id, diff_result);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update timestamp and version
CREATE OR REPLACE FUNCTION update_profile_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    
    -- Increment version if any config changed
    IF OLD.strategy_composition IS DISTINCT FROM NEW.strategy_composition
       OR OLD.risk_config IS DISTINCT FROM NEW.risk_config
       OR OLD.conditions IS DISTINCT FROM NEW.conditions
       OR OLD.lifecycle IS DISTINCT FROM NEW.lifecycle
       OR OLD.execution IS DISTINCT FROM NEW.execution THEN
        NEW.version = OLD.version + 1;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_profile_timestamp ON user_chessboard_profiles;
CREATE TRIGGER trigger_update_profile_timestamp
    BEFORE UPDATE ON user_chessboard_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_profile_timestamp();

-- Trigger to create version snapshot after update
DROP TRIGGER IF EXISTS trigger_create_profile_version ON user_chessboard_profiles;
CREATE TRIGGER trigger_create_profile_version
    AFTER UPDATE ON user_chessboard_profiles
    FOR EACH ROW
    WHEN (OLD.version IS DISTINCT FROM NEW.version)
    EXECUTE FUNCTION create_profile_version_snapshot();

-- Also create initial version on insert
CREATE OR REPLACE FUNCTION create_initial_profile_version()
RETURNS TRIGGER AS $$
DECLARE
    config_snap JSONB;
BEGIN
    config_snap := jsonb_build_object(
        'strategy_composition', NEW.strategy_composition,
        'risk_config', NEW.risk_config,
        'conditions', NEW.conditions,
        'lifecycle', NEW.lifecycle,
        'execution', NEW.execution,
        'status', NEW.status,
        'is_active', NEW.is_active
    );
    
    INSERT INTO profile_versions (profile_id, version, config_snapshot, changed_by, change_summary)
    VALUES (NEW.id, 1, config_snap, NEW.user_id, 'Initial version');
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_create_initial_profile_version ON user_chessboard_profiles;
CREATE TRIGGER trigger_create_initial_profile_version
    AFTER INSERT ON user_chessboard_profiles
    FOR EACH ROW
    EXECUTE FUNCTION create_initial_profile_version();

-- Comments
COMMENT ON TABLE user_chessboard_profiles IS 'User-customizable trading profiles with strategy composition, risk controls, and market gates';
COMMENT ON COLUMN user_chessboard_profiles.environment IS 'Dev for testing, Paper for paper trading, Live for real trading';
COMMENT ON COLUMN user_chessboard_profiles.strategy_composition IS 'Array of strategy instances with weights and priorities';
COMMENT ON COLUMN user_chessboard_profiles.risk_config IS 'Risk management settings for this profile';
COMMENT ON COLUMN user_chessboard_profiles.conditions IS 'Market condition gates that must be met for profile to trade';
COMMENT ON COLUMN user_chessboard_profiles.lifecycle IS 'Trading lifecycle rules like cooldowns and loss limits';
COMMENT ON COLUMN user_chessboard_profiles.execution IS 'Order execution preferences';
COMMENT ON TABLE profile_versions IS 'Audit trail of all profile configuration changes';


