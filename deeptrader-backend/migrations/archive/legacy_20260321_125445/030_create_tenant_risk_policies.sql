-- Migration: 030_create_tenant_risk_policies.sql
-- Global Risk Envelope: Account-level risk limits that cap all bot configurations
-- Effective risk = min(global_policy, per_bot_config)

CREATE TABLE IF NOT EXISTS tenant_risk_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- ═══════════════════════════════════════════════════════════════
    -- DAILY LOSS LIMITS
    -- ═══════════════════════════════════════════════════════════════
    max_daily_loss_pct DECIMAL(10,4) DEFAULT 0.10, -- Max daily drawdown %
    max_daily_loss_usd DECIMAL(20,2), -- Absolute daily loss cap (optional)
    
    -- ═══════════════════════════════════════════════════════════════
    -- EXPOSURE LIMITS
    -- ═══════════════════════════════════════════════════════════════
    max_total_exposure_pct DECIMAL(10,4) DEFAULT 1.00, -- Max total exposure %
    max_single_position_pct DECIMAL(10,4) DEFAULT 0.25, -- Max size of any single position
    max_per_symbol_exposure_pct DECIMAL(10,4) DEFAULT 0.50, -- Max exposure to any one symbol
    
    -- ═══════════════════════════════════════════════════════════════
    -- LEVERAGE LIMITS
    -- ═══════════════════════════════════════════════════════════════
    max_leverage DECIMAL(5,2) DEFAULT 10.00, -- Global leverage cap
    allowed_leverage_levels INTEGER[] DEFAULT ARRAY[1, 2, 3, 5, 10], -- Allowed leverage options
    
    -- ═══════════════════════════════════════════════════════════════
    -- CONCURRENCY LIMITS
    -- ═══════════════════════════════════════════════════════════════
    max_concurrent_positions INTEGER DEFAULT 10, -- Max open positions globally
    max_concurrent_bots INTEGER DEFAULT 1, -- Max bots running simultaneously
    max_symbols INTEGER DEFAULT 20, -- Max symbols traded across all bots
    
    -- ═══════════════════════════════════════════════════════════════
    -- CAPITAL LIMITS
    -- ═══════════════════════════════════════════════════════════════
    total_capital_limit_usd DECIMAL(20,2), -- Max capital across all exchanges
    min_reserve_pct DECIMAL(10,4) DEFAULT 0.10, -- Min % to keep as reserve
    
    -- ═══════════════════════════════════════════════════════════════
    -- ENVIRONMENT RESTRICTIONS
    -- ═══════════════════════════════════════════════════════════════
    live_trading_enabled BOOLEAN DEFAULT false, -- Must explicitly enable live
    allowed_environments TEXT[] DEFAULT ARRAY['dev', 'paper'], -- Which envs user can trade in
    allowed_exchanges TEXT[] DEFAULT ARRAY['binance', 'okx', 'bybit'],
    
    -- ═══════════════════════════════════════════════════════════════
    -- TIME-BASED RESTRICTIONS
    -- ═══════════════════════════════════════════════════════════════
    trading_hours_enabled BOOLEAN DEFAULT false,
    trading_start_time TIME,
    trading_end_time TIME,
    trading_days TEXT[] DEFAULT ARRAY['mon', 'tue', 'wed', 'thu', 'fri'],
    timezone VARCHAR(64) DEFAULT 'UTC',
    
    -- ═══════════════════════════════════════════════════════════════
    -- CIRCUIT BREAKERS
    -- ═══════════════════════════════════════════════════════════════
    circuit_breaker_enabled BOOLEAN DEFAULT true,
    circuit_breaker_loss_pct DECIMAL(10,4) DEFAULT 0.05, -- Pause trading after this % loss
    circuit_breaker_cooldown_minutes INTEGER DEFAULT 60, -- Cooldown period
    
    -- ═══════════════════════════════════════════════════════════════
    -- METADATA
    -- ═══════════════════════════════════════════════════════════════
    policy_version INTEGER DEFAULT 1,
    notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_reviewed_at TIMESTAMPTZ,
    
    -- One policy per user
    UNIQUE(user_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tenant_risk_policies_user ON tenant_risk_policies(user_id);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_tenant_risk_policies_updated_at ON tenant_risk_policies;
CREATE TRIGGER update_tenant_risk_policies_updated_at
    BEFORE UPDATE ON tenant_risk_policies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to create default policy for new users
CREATE OR REPLACE FUNCTION create_default_risk_policy()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO tenant_risk_policies (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Auto-create risk policy when user is created
DROP TRIGGER IF EXISTS trigger_create_default_risk_policy ON users;
CREATE TRIGGER trigger_create_default_risk_policy
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION create_default_risk_policy();

COMMENT ON TABLE tenant_risk_policies IS 'Account-level risk limits that cap all bot configurations';
COMMENT ON COLUMN tenant_risk_policies.max_daily_loss_pct IS 'Global daily drawdown limit - bots cannot exceed this';
COMMENT ON COLUMN tenant_risk_policies.max_leverage IS 'Global leverage cap - per-bot leverage cannot exceed this';
COMMENT ON COLUMN tenant_risk_policies.live_trading_enabled IS 'User must explicitly enable live trading';
COMMENT ON COLUMN tenant_risk_policies.circuit_breaker_enabled IS 'Auto-pause trading after significant loss';


