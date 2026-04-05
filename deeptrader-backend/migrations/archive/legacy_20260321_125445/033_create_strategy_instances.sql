-- Migration: 033_create_strategy_instances.sql
-- Strategy Instances: User-parameterized versions of strategy templates
-- Users can customize parameters from the base strategy templates

CREATE TABLE IF NOT EXISTS strategy_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Template reference (e.g., "breakout_scalp", "mean_reversion_fade")
    template_id VARCHAR(100) NOT NULL,
    
    -- User-defined name for this instance
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Customized parameters (merged with template defaults at runtime)
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Example: {"stop_loss_pct": 0.5, "take_profit_pct": 1.2, "max_spread": 0.001}
    
    -- Metadata
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    -- active: can be used in profiles
    -- deprecated: still works but flagged for replacement
    -- archived: not usable, kept for history
    
    usage_count INTEGER DEFAULT 0,  -- Number of profiles using this instance
    
    -- Backtest tracking
    last_backtest_at TIMESTAMPTZ,
    last_backtest_summary JSONB,
    -- Example: {"total_trades": 150, "win_rate": 0.62, "sharpe": 1.8, "max_drawdown": -0.08}
    
    -- Versioning (increments on each param update)
    version INTEGER NOT NULL DEFAULT 1,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Each user can only have one instance with a given name
    UNIQUE(user_id, name)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_strategy_instances_user ON strategy_instances(user_id);
CREATE INDEX IF NOT EXISTS idx_strategy_instances_template ON strategy_instances(template_id);
CREATE INDEX IF NOT EXISTS idx_strategy_instances_status ON strategy_instances(status);
CREATE INDEX IF NOT EXISTS idx_strategy_instances_user_status ON strategy_instances(user_id, status);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_strategy_instance_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    -- Increment version on param changes
    IF OLD.params IS DISTINCT FROM NEW.params THEN
        NEW.version = OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_strategy_instance_timestamp ON strategy_instances;
CREATE TRIGGER trigger_update_strategy_instance_timestamp
    BEFORE UPDATE ON strategy_instances
    FOR EACH ROW
    EXECUTE FUNCTION update_strategy_instance_timestamp();

-- Comments
COMMENT ON TABLE strategy_instances IS 'User-customized instances of strategy templates with parameterized settings';
COMMENT ON COLUMN strategy_instances.template_id IS 'References the base strategy in the Python strategy registry';
COMMENT ON COLUMN strategy_instances.params IS 'User-customized parameters merged with template defaults at runtime';
COMMENT ON COLUMN strategy_instances.usage_count IS 'Number of profiles currently using this strategy instance';


