-- Migration: 027_create_bot_instances.sql
-- Bot Instances: User-facing bots that reference strategy templates
-- A user can have multiple bot instances, each with different configurations

CREATE TABLE IF NOT EXISTS bot_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Identity
    name VARCHAR(128) NOT NULL,
    description TEXT,
    
    -- Strategy reference (optional - can be null for custom bots)
    strategy_template_id UUID REFERENCES strategy_templates(id) ON DELETE SET NULL,
    
    -- Allocator role for portfolio management
    allocator_role VARCHAR(32) DEFAULT 'core', -- core, satellite, hedge, experimental
    
    -- Default risk configuration (can be overridden per exchange attachment)
    default_risk_config JSONB DEFAULT '{
        "positionSizePct": 0.10,
        "maxPositions": 4,
        "maxDailyLossPct": 0.05,
        "maxTotalExposurePct": 0.40,
        "maxLeverage": 1,
        "leverageMode": "isolated",
        "maxPositionsPerSymbol": 1,
        "maxDailyLossPerSymbolPct": 0.025
    }'::jsonb,
    
    -- Default execution configuration
    default_execution_config JSONB DEFAULT '{
        "defaultOrderType": "market",
        "stopLossPct": 0.02,
        "takeProfitPct": 0.05,
        "trailingStopEnabled": false,
        "trailingStopPct": 0.01,
        "maxHoldTimeHours": 24,
        "minTradeIntervalSec": 1,
        "executionTimeoutSec": 5,
        "enableVolatilityFilter": true
    }'::jsonb,
    
    -- Profile bundle overrides (merged with template)
    profile_overrides JSONB DEFAULT '{}'::jsonb,
    
    -- Tags for organization
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Ensure unique names per user
    UNIQUE(user_id, name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bot_instances_user ON bot_instances(user_id);
CREATE INDEX IF NOT EXISTS idx_bot_instances_template ON bot_instances(strategy_template_id);
CREATE INDEX IF NOT EXISTS idx_bot_instances_active ON bot_instances(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_bot_instances_role ON bot_instances(allocator_role);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_bot_instances_updated_at ON bot_instances;
CREATE TRIGGER update_bot_instances_updated_at
    BEFORE UPDATE ON bot_instances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE bot_instances IS 'User-facing bot configurations that reference strategy templates';
COMMENT ON COLUMN bot_instances.allocator_role IS 'Role in portfolio allocation: core, satellite, hedge, experimental';
COMMENT ON COLUMN bot_instances.default_risk_config IS 'Default risk settings, can be overridden per exchange attachment';
COMMENT ON COLUMN bot_instances.profile_overrides IS 'Overrides to merge with strategy template profile bundle';


