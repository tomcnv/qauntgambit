-- Migration: 025_add_exchange_balance_columns.sql
-- Add exchange balance tracking and trading capital per credential

-- ═══════════════════════════════════════════════════════════════
-- EXCHANGE BALANCE TRACKING
-- ═══════════════════════════════════════════════════════════════

-- Exchange balance fetched from the actual exchange account
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS exchange_balance DECIMAL(20,8);

-- When the balance was last successfully fetched
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS balance_updated_at TIMESTAMPTZ;

-- Whether the account is currently connected (able to fetch balance)
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS account_connected BOOLEAN DEFAULT false;

-- User-defined trading capital (must be <= exchange_balance)
-- This is what the bot uses for position sizing
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS trading_capital DECIMAL(20,8);

-- Currency of the balance (usually USDT)
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS balance_currency VARCHAR(16) DEFAULT 'USDT';

-- Last connection error if account_connected is false
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS connection_error TEXT;

-- Index for finding connected accounts quickly
CREATE INDEX IF NOT EXISTS idx_exchange_creds_connected 
ON user_exchange_credentials(user_id, account_connected) 
WHERE account_connected = true;

-- ═══════════════════════════════════════════════════════════════
-- BALANCE HISTORY FOR TRACKING
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS credential_balance_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id UUID NOT NULL REFERENCES user_exchange_credentials(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Balance snapshot
    exchange_balance DECIMAL(20,8) NOT NULL,
    trading_capital DECIMAL(20,8),
    balance_currency VARCHAR(16) DEFAULT 'USDT',
    
    -- Context
    source VARCHAR(32) DEFAULT 'api_fetch', -- api_fetch, manual, verification
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_balance_history_credential 
ON credential_balance_history(credential_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_balance_history_user 
ON credential_balance_history(user_id, created_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- COMMENTS
-- ═══════════════════════════════════════════════════════════════

COMMENT ON COLUMN user_exchange_credentials.exchange_balance IS 'Actual balance fetched from the exchange account';
COMMENT ON COLUMN user_exchange_credentials.trading_capital IS 'User-set capital for position sizing (must be <= exchange_balance)';
COMMENT ON COLUMN user_exchange_credentials.account_connected IS 'Whether we can successfully connect to the exchange';
COMMENT ON COLUMN user_exchange_credentials.balance_updated_at IS 'Last successful balance fetch timestamp';
COMMENT ON TABLE credential_balance_history IS 'Historical balance snapshots for audit and tracking';

