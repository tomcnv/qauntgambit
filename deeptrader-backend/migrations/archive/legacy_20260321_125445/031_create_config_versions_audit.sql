-- Migration: 031_create_config_versions_audit.sql
-- Versioning and Audit: Track all changes to bot configurations

-- ═══════════════════════════════════════════════════════════════
-- BOT EXCHANGE CONFIG VERSIONS
-- ═══════════════════════════════════════════════════════════════
-- Immutable snapshots of bot_exchange_configs for history/rollback

CREATE TABLE IF NOT EXISTS bot_exchange_config_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Parent reference
    bot_exchange_config_id UUID NOT NULL REFERENCES bot_exchange_configs(id) ON DELETE CASCADE,
    
    -- Version info
    version_number INTEGER NOT NULL,
    
    -- Snapshot of the config at this version
    trading_capital_usd DECIMAL(20,2),
    enabled_symbols JSONB,
    risk_config JSONB,
    execution_config JSONB,
    profile_overrides JSONB,
    
    -- What changed
    change_summary TEXT,
    change_type VARCHAR(32), -- create, update, activate, deactivate, etc.
    
    -- Who made the change
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    
    -- Whether this version was ever active
    was_activated BOOLEAN DEFAULT false,
    activated_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Unique version number per config
    UNIQUE(bot_exchange_config_id, version_number)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_config_versions_parent ON bot_exchange_config_versions(bot_exchange_config_id);
CREATE INDEX IF NOT EXISTS idx_config_versions_created ON bot_exchange_config_versions(created_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- CONFIG AUDIT LOG
-- ═══════════════════════════════════════════════════════════════
-- Comprehensive audit trail for all configuration changes

CREATE TABLE IF NOT EXISTS config_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Who
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    
    -- What resource
    resource_type VARCHAR(64) NOT NULL, -- bot_instance, bot_exchange_config, tenant_risk_policy, etc.
    resource_id UUID NOT NULL,
    
    -- What action
    action VARCHAR(64) NOT NULL, -- create, update, delete, activate, deactivate, start, stop, etc.
    
    -- Environment context
    environment VARCHAR(16), -- dev, paper, live
    
    -- Change details
    before_state JSONB, -- State before the change (null for creates)
    after_state JSONB, -- State after the change (null for deletes)
    change_diff JSONB, -- Computed diff of what changed
    
    -- Version references
    from_version INTEGER,
    to_version INTEGER,
    
    -- Request context
    ip_address INET,
    user_agent TEXT,
    request_id VARCHAR(64),
    
    -- Additional metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON config_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON config_audit_log(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON config_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_env ON config_audit_log(environment);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON config_audit_log(created_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- HELPER FUNCTION: Create config version on update
-- ═══════════════════════════════════════════════════════════════

-- Clean up legacy trigger/function (if present)
DROP TRIGGER IF EXISTS trigger_create_config_version ON bot_exchange_configs;
DROP FUNCTION IF EXISTS create_config_version_on_update();

-- BEFORE trigger: assign next version number to NEW.config_version
CREATE OR REPLACE FUNCTION assign_config_version_before()
RETURNS TRIGGER AS $$
DECLARE
    next_version INTEGER;
BEGIN
    SELECT COALESCE(MAX(version_number), 0) + 1 INTO next_version
    FROM bot_exchange_config_versions
    WHERE bot_exchange_config_id = NEW.id;

    NEW.config_version := next_version;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- AFTER trigger: write immutable snapshot using the assigned version
CREATE OR REPLACE FUNCTION insert_config_version_after()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO bot_exchange_config_versions (
        bot_exchange_config_id,
        version_number,
        trading_capital_usd,
        enabled_symbols,
        risk_config,
        execution_config,
        profile_overrides,
        change_type,
        was_activated,
        activated_at
    ) VALUES (
        NEW.id,
        NEW.config_version,
        NEW.trading_capital_usd,
        NEW.enabled_symbols,
        NEW.risk_config,
        NEW.execution_config,
        NEW.profile_overrides,
        CASE
            WHEN TG_OP = 'INSERT' THEN 'create'
            WHEN NEW.is_active = true AND (OLD.is_active IS NULL OR OLD.is_active = false) THEN 'activate'
            WHEN NEW.is_active = false AND OLD.is_active = true THEN 'deactivate'
            ELSE 'update'
        END,
        NEW.is_active,
        CASE WHEN NEW.is_active = true THEN NOW() ELSE NULL END
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_assign_config_version ON bot_exchange_configs;
CREATE TRIGGER trigger_assign_config_version
    BEFORE INSERT OR UPDATE ON bot_exchange_configs
    FOR EACH ROW
    EXECUTE FUNCTION assign_config_version_before();

DROP TRIGGER IF EXISTS trigger_insert_config_version ON bot_exchange_configs;
CREATE TRIGGER trigger_insert_config_version
    AFTER INSERT OR UPDATE ON bot_exchange_configs
    FOR EACH ROW
    EXECUTE FUNCTION insert_config_version_after();

-- ═══════════════════════════════════════════════════════════════
-- HELPER FUNCTION: Create audit log entry
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION create_audit_log_entry(
    p_user_id UUID,
    p_resource_type VARCHAR(64),
    p_resource_id UUID,
    p_action VARCHAR(64),
    p_environment VARCHAR(16),
    p_before_state JSONB,
    p_after_state JSONB,
    p_notes TEXT DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    audit_id UUID;
BEGIN
    INSERT INTO config_audit_log (
        user_id,
        resource_type,
        resource_id,
        action,
        environment,
        before_state,
        after_state,
        notes
    ) VALUES (
        p_user_id,
        p_resource_type,
        p_resource_id,
        p_action,
        p_environment,
        p_before_state,
        p_after_state,
        p_notes
    )
    RETURNING id INTO audit_id;
    
    RETURN audit_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE bot_exchange_config_versions IS 'Immutable version history of bot-exchange configurations';
COMMENT ON TABLE config_audit_log IS 'Comprehensive audit trail for all configuration changes';
COMMENT ON FUNCTION create_audit_log_entry IS 'Helper to create audit log entries from application code';



