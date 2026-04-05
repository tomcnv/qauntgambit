-- Migration: 025_add_balance_columns.sql
-- Add exchange balance tracking and trading capital per credential

-- ═══════════════════════════════════════════════════════════════
-- ADD BALANCE COLUMNS TO USER_EXCHANGE_CREDENTIALS
-- ═══════════════════════════════════════════════════════════════

-- Exchange balance fetched from API
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS exchange_balance DECIMAL(20,8);

-- When we last successfully fetched balance
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS balance_updated_at TIMESTAMPTZ;

-- Whether account is currently connected (can fetch balance)
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS account_connected BOOLEAN DEFAULT false;

-- User-set trading capital (must be <= exchange_balance)
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS trading_capital DECIMAL(20,8);

-- Balance fetch error message (if any)
ALTER TABLE user_exchange_credentials
ADD COLUMN IF NOT EXISTS balance_error TEXT;

-- Index for quick lookup of connected accounts
CREATE INDEX IF NOT EXISTS idx_exchange_creds_connected 
ON user_exchange_credentials(user_id, account_connected) 
WHERE account_connected = true;

-- ═══════════════════════════════════════════════════════════════
-- ADD BALANCE HISTORY TABLE FOR TRACKING
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS credential_balance_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id UUID NOT NULL REFERENCES user_exchange_credentials(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Balance snapshot
    exchange_balance DECIMAL(20,8) NOT NULL,
    trading_capital DECIMAL(20,8),
    available_balance DECIMAL(20,8),
    margin_used DECIMAL(20,8),
    unrealized_pnl DECIMAL(20,8),
    
    -- Context
    currency VARCHAR(16) DEFAULT 'USDT',
    fetch_source VARCHAR(32), -- 'verification', 'manual_refresh', 'scheduled'
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_balance_history_credential 
ON credential_balance_history(credential_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_balance_history_user 
ON credential_balance_history(user_id, created_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- COMMENTS
-- ═══════════════════════════════════════════════════════════════

COMMENT ON COLUMN user_exchange_credentials.exchange_balance IS 'Last fetched balance from exchange API';
COMMENT ON COLUMN user_exchange_credentials.balance_updated_at IS 'Timestamp of last successful balance fetch';
COMMENT ON COLUMN user_exchange_credentials.account_connected IS 'Whether we can reach the exchange account';
COMMENT ON COLUMN user_exchange_credentials.trading_capital IS 'User-set trading capital (must be <= exchange_balance)';
COMMENT ON TABLE credential_balance_history IS 'Historical balance snapshots for trend analysis';



