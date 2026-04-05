-- Migration: 032_operating_modes_hierarchy.sql
-- Multi-Bot Operating Modes Architecture
-- Creates Exchange Account-first hierarchy with SOLO/TEAM/PROP operating modes
-- 
-- This is a CLEAN BREAK migration that restructures the credential/bot model.
-- Run with caution - existing credential data will need to be re-created.

-- =============================================================================
-- PHASE 1: Add Operating Mode to Tenants (Users)
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS operating_mode VARCHAR(16) DEFAULT 'solo';

-- Add constraint if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_operating_mode_check'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_operating_mode_check 
            CHECK (operating_mode IN ('solo', 'team', 'prop'));
    END IF;
END $$;

COMMENT ON COLUMN users.operating_mode IS 'Operating mode: solo (1 bot per exchange), team (concurrent + locks), prop (concurrent + locks + budgets required)';

-- =============================================================================
-- PHASE 2: Create Exchange Accounts Table (Risk Pool Boundary)
-- =============================================================================

CREATE TABLE IF NOT EXISTS exchange_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Venue identification
    venue VARCHAR(32) NOT NULL,              -- binance, okx, bybit
    label VARCHAR(128) NOT NULL,             -- "OKX Main", "Binance Desk-1"
    environment VARCHAR(16) NOT NULL,        -- dev, paper, live
    
    -- Credential storage (vault reference)
    secret_id VARCHAR(256),
    is_testnet BOOLEAN DEFAULT false,
    status VARCHAR(32) DEFAULT 'pending',    -- pending, verified, error, disabled
    last_verified_at TIMESTAMPTZ,
    verification_error TEXT,
    permissions JSONB,
    
    -- Balance (shared pool across all bots on this account)
    exchange_balance DECIMAL(20,8),
    available_balance DECIMAL(20,8),
    margin_used DECIMAL(20,8),
    unrealized_pnl DECIMAL(20,8),
    balance_currency VARCHAR(16) DEFAULT 'USDT',
    balance_updated_at TIMESTAMPTZ,
    
    -- SOLO mode convenience: track the single active bot
    active_bot_id UUID,  -- FK added after bot_instances exists
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- One account per (tenant, venue, label, environment) combination
    UNIQUE(tenant_id, venue, label, environment)
);

CREATE INDEX IF NOT EXISTS idx_exchange_accounts_tenant ON exchange_accounts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_exchange_accounts_venue ON exchange_accounts(venue);
CREATE INDEX IF NOT EXISTS idx_exchange_accounts_status ON exchange_accounts(tenant_id, status);

COMMENT ON TABLE exchange_accounts IS 'Exchange accounts represent the risk pool boundary - shared balance/margin across all bots';
COMMENT ON COLUMN exchange_accounts.active_bot_id IS 'SOLO mode: the single bot allowed to run on this account+env';

-- =============================================================================
-- PHASE 3: Create Exchange Policies Table (Hard Caps per Account)
-- =============================================================================

CREATE TABLE IF NOT EXISTS exchange_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    
    -- Daily loss limits
    max_daily_loss_pct DECIMAL(10,4) DEFAULT 0.10,
    max_daily_loss_usd DECIMAL(20,2),
    daily_loss_used_usd DECIMAL(20,2) DEFAULT 0,
    daily_loss_reset_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Exposure limits
    max_margin_used_pct DECIMAL(10,4) DEFAULT 0.80,
    max_gross_exposure_pct DECIMAL(10,4) DEFAULT 1.00,
    max_net_exposure_pct DECIMAL(10,4) DEFAULT 0.50,
    max_leverage DECIMAL(5,2) DEFAULT 10.0,
    
    -- Position limits
    max_open_positions INTEGER DEFAULT 10,
    
    -- Kill switch (emergency stop all trading)
    kill_switch_enabled BOOLEAN DEFAULT false,
    kill_switch_triggered_at TIMESTAMPTZ,
    kill_switch_triggered_by UUID REFERENCES users(id),
    kill_switch_reason TEXT,
    
    -- Circuit breaker (auto-triggered on loss)
    circuit_breaker_enabled BOOLEAN DEFAULT true,
    circuit_breaker_loss_pct DECIMAL(10,4) DEFAULT 0.05,
    circuit_breaker_cooldown_min INTEGER DEFAULT 60,
    circuit_breaker_triggered_at TIMESTAMPTZ,
    
    -- Environment gating
    live_trading_enabled BOOLEAN DEFAULT false,
    
    -- Versioning
    policy_version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(exchange_account_id)
);

CREATE INDEX IF NOT EXISTS idx_exchange_policies_account ON exchange_policies(exchange_account_id);

COMMENT ON TABLE exchange_policies IS 'Hard risk caps per exchange account - enforced across all bots';
COMMENT ON COLUMN exchange_policies.kill_switch_enabled IS 'When true, ALL trading is blocked on this account';
COMMENT ON COLUMN exchange_policies.circuit_breaker_loss_pct IS 'Auto-trigger kill switch at this daily loss %';

-- =============================================================================
-- PHASE 4: Create Symbol Locks Table (TEAM/PROP only)
-- =============================================================================

CREATE TABLE IF NOT EXISTS symbol_locks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    environment VARCHAR(16) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    
    -- Ownership
    owner_bot_id UUID NOT NULL,  -- FK to bot_instances added later
    acquired_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,      -- NULL = permanent until released
    lease_heartbeat_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Conflict tracking
    last_conflict_bot_id UUID,
    last_conflict_at TIMESTAMPTZ,
    conflict_count INTEGER DEFAULT 0,
    
    -- One owner per (account, env, symbol)
    UNIQUE(exchange_account_id, environment, symbol)
);

CREATE INDEX IF NOT EXISTS idx_symbol_locks_owner ON symbol_locks(owner_bot_id);
CREATE INDEX IF NOT EXISTS idx_symbol_locks_account_env ON symbol_locks(exchange_account_id, environment);
CREATE INDEX IF NOT EXISTS idx_symbol_locks_heartbeat ON symbol_locks(lease_heartbeat_at);

COMMENT ON TABLE symbol_locks IS 'Symbol ownership locks for TEAM/PROP modes - prevents bot conflicts';
COMMENT ON COLUMN symbol_locks.lease_heartbeat_at IS 'Updated by running bot; expired leases can be reclaimed';

-- =============================================================================
-- PHASE 5: Update Bot Instances Table
-- =============================================================================

-- Add new columns to bot_instances
ALTER TABLE bot_instances 
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID REFERENCES exchange_accounts(id),
    ADD COLUMN IF NOT EXISTS runtime_state VARCHAR(32) DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_error TEXT,
    ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS stopped_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS environment VARCHAR(16) DEFAULT 'paper',
    ADD COLUMN IF NOT EXISTS enabled_symbols JSONB DEFAULT '[]'::jsonb;

-- Add constraint for runtime_state if not exists
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'bot_instances_runtime_state_check'
    ) THEN
        ALTER TABLE bot_instances ADD CONSTRAINT bot_instances_runtime_state_check 
            CHECK (runtime_state IN ('idle', 'starting', 'running', 'paused', 'stopping', 'error'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bot_instances_exchange ON bot_instances(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_bot_instances_state ON bot_instances(exchange_account_id, runtime_state);
CREATE INDEX IF NOT EXISTS idx_bot_instances_running ON bot_instances(exchange_account_id) WHERE runtime_state = 'running';

COMMENT ON COLUMN bot_instances.exchange_account_id IS 'The exchange account (risk pool) this bot trades on';
COMMENT ON COLUMN bot_instances.runtime_state IS 'Current execution state: idle, starting, running, paused, stopping, error';
COMMENT ON COLUMN bot_instances.enabled_symbols IS 'Symbols this bot is configured to trade';

-- =============================================================================
-- PHASE 6: Create Bot Budgets Table (TEAM optional, PROP required)
-- =============================================================================

CREATE TABLE IF NOT EXISTS bot_budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_instance_id UUID NOT NULL REFERENCES bot_instances(id) ON DELETE CASCADE,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    
    -- Budget allocations (must sum <= exchange_policy limits)
    max_daily_loss_pct DECIMAL(10,4),
    max_daily_loss_usd DECIMAL(20,2),
    max_margin_used_pct DECIMAL(10,4),
    max_exposure_pct DECIMAL(10,4),
    max_open_positions INTEGER,
    max_leverage DECIMAL(5,2),
    max_order_rate_per_min INTEGER,
    
    -- Runtime tracking
    daily_loss_used_usd DECIMAL(20,2) DEFAULT 0,
    margin_used_usd DECIMAL(20,2) DEFAULT 0,
    current_positions INTEGER DEFAULT 0,
    daily_reset_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Versioning
    budget_version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(bot_instance_id, exchange_account_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_budgets_bot ON bot_budgets(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_bot_budgets_account ON bot_budgets(exchange_account_id);

COMMENT ON TABLE bot_budgets IS 'Per-bot budget allocations within an exchange account (required in PROP mode)';

-- =============================================================================
-- PHASE 7: Add Attribution Columns to Runtime Tables
-- =============================================================================

-- Orders table
ALTER TABLE orders 
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID,
    ADD COLUMN IF NOT EXISTS bot_id UUID,
    ADD COLUMN IF NOT EXISTS profile_id UUID,
    ADD COLUMN IF NOT EXISTS profile_version INTEGER,
    ADD COLUMN IF NOT EXISTS trace_id UUID,
    ADD COLUMN IF NOT EXISTS reject_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS reject_scope VARCHAR(32),
    ADD COLUMN IF NOT EXISTS reject_details JSONB;

CREATE INDEX IF NOT EXISTS idx_orders_exchange_account ON orders(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_orders_bot ON orders(bot_id);
CREATE INDEX IF NOT EXISTS idx_orders_trace ON orders(trace_id);

-- Trades table
ALTER TABLE trades
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID,
    ADD COLUMN IF NOT EXISTS bot_id UUID,
    ADD COLUMN IF NOT EXISTS profile_id UUID,
    ADD COLUMN IF NOT EXISTS profile_version INTEGER,
    ADD COLUMN IF NOT EXISTS trace_id UUID;

CREATE INDEX IF NOT EXISTS idx_trades_exchange_account ON trades(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot_id);

-- Positions table
ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID,
    ADD COLUMN IF NOT EXISTS bot_id UUID;

CREATE INDEX IF NOT EXISTS idx_positions_exchange_account ON positions(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_positions_bot ON positions(bot_id);

-- Trading decisions table
ALTER TABLE trading_decisions
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID,
    ADD COLUMN IF NOT EXISTS bot_id UUID,
    ADD COLUMN IF NOT EXISTS trace_id UUID;

CREATE INDEX IF NOT EXISTS idx_trading_decisions_exchange_account ON trading_decisions(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_trading_decisions_bot ON trading_decisions(bot_id);

-- =============================================================================
-- PHASE 8: Add FK from exchange_accounts.active_bot_id to bot_instances
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'exchange_accounts_active_bot_fk'
    ) THEN
        ALTER TABLE exchange_accounts 
            ADD CONSTRAINT exchange_accounts_active_bot_fk 
            FOREIGN KEY (active_bot_id) REFERENCES bot_instances(id) ON DELETE SET NULL;
    END IF;
END $$;

-- =============================================================================
-- PHASE 9: Add FK from symbol_locks.owner_bot_id to bot_instances
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'symbol_locks_owner_bot_fk'
    ) THEN
        ALTER TABLE symbol_locks 
            ADD CONSTRAINT symbol_locks_owner_bot_fk 
            FOREIGN KEY (owner_bot_id) REFERENCES bot_instances(id) ON DELETE CASCADE;
    END IF;
END $$;

-- =============================================================================
-- PHASE 10: Create Triggers for updated_at
-- =============================================================================

-- Trigger function (may already exist)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- exchange_accounts
DROP TRIGGER IF EXISTS update_exchange_accounts_updated_at ON exchange_accounts;
CREATE TRIGGER update_exchange_accounts_updated_at
    BEFORE UPDATE ON exchange_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- exchange_policies
DROP TRIGGER IF EXISTS update_exchange_policies_updated_at ON exchange_policies;
CREATE TRIGGER update_exchange_policies_updated_at
    BEFORE UPDATE ON exchange_policies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- bot_budgets
DROP TRIGGER IF EXISTS update_bot_budgets_updated_at ON bot_budgets;
CREATE TRIGGER update_bot_budgets_updated_at
    BEFORE UPDATE ON bot_budgets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- PHASE 11: Create Default Exchange Policies Trigger
-- =============================================================================

-- Auto-create exchange_policies when exchange_account is created
CREATE OR REPLACE FUNCTION create_default_exchange_policy()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO exchange_policies (exchange_account_id)
    VALUES (NEW.id)
    ON CONFLICT (exchange_account_id) DO NOTHING;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS create_exchange_policy_on_account ON exchange_accounts;
CREATE TRIGGER create_exchange_policy_on_account
    AFTER INSERT ON exchange_accounts
    FOR EACH ROW EXECUTE FUNCTION create_default_exchange_policy();

-- =============================================================================
-- PHASE 12: Daily Reset Function for Loss Tracking
-- =============================================================================

-- Function to reset daily loss tracking (call via cron or scheduled job)
CREATE OR REPLACE FUNCTION reset_daily_loss_tracking()
RETURNS void AS $$
BEGIN
    -- Reset exchange policies daily loss
    UPDATE exchange_policies
    SET daily_loss_used_usd = 0,
        daily_loss_reset_at = NOW()
    WHERE daily_loss_reset_at < CURRENT_DATE;
    
    -- Reset bot budgets daily loss
    UPDATE bot_budgets
    SET daily_loss_used_usd = 0,
        daily_reset_at = NOW()
    WHERE daily_reset_at < CURRENT_DATE;
END;
$$ language 'plpgsql';

COMMENT ON FUNCTION reset_daily_loss_tracking() IS 'Call daily to reset loss tracking counters';

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Note: This migration does NOT drop old tables (user_exchange_credentials, 
-- bot_exchange_configs, user_trade_profiles). Those can be cleaned up separately
-- after data migration is confirmed successful.







