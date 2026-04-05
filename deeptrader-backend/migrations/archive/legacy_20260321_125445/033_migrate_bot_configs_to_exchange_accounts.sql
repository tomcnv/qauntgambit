-- Migration: 033_migrate_bot_configs_to_exchange_accounts.sql
-- Purpose: Transition bot_exchange_configs from user_exchange_credentials to exchange_accounts
-- This allows bots to reference the new exchange_accounts system

-- =============================================================================
-- PHASE 1: Add exchange_account_id column to bot_exchange_configs
-- =============================================================================

ALTER TABLE bot_exchange_configs 
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID REFERENCES exchange_accounts(id) ON DELETE SET NULL;

-- Create index for the new column
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_exchange_account 
    ON bot_exchange_configs(exchange_account_id);

-- =============================================================================
-- PHASE 2: Make credential_id optional (drop NOT NULL, keep FK for backward compat)
-- =============================================================================

-- First, drop the existing constraint if it exists
ALTER TABLE bot_exchange_configs 
    ALTER COLUMN credential_id DROP NOT NULL;

-- =============================================================================
-- PHASE 3: Update unique constraint to use exchange_account_id
-- =============================================================================

-- Drop old unique constraint if it exists
ALTER TABLE bot_exchange_configs 
    DROP CONSTRAINT IF EXISTS bot_exchange_configs_bot_instance_id_credential_id_environm_key;

-- Add new unique constraint that works with either credential_id or exchange_account_id
-- Using a partial index approach for flexibility
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_exchange_configs_unique_combo 
    ON bot_exchange_configs(bot_instance_id, COALESCE(exchange_account_id, credential_id), environment);

-- =============================================================================
-- PHASE 4: Add exchange column for denormalized access (useful for queries)
-- =============================================================================

ALTER TABLE bot_exchange_configs 
    ADD COLUMN IF NOT EXISTS exchange VARCHAR(32);

-- =============================================================================
-- PHASE 5: Comments
-- =============================================================================

COMMENT ON COLUMN bot_exchange_configs.exchange_account_id IS 'New: references exchange_accounts for the operating modes system';
COMMENT ON COLUMN bot_exchange_configs.credential_id IS 'Legacy: kept for backward compatibility, will be phased out';
COMMENT ON COLUMN bot_exchange_configs.exchange IS 'Denormalized exchange name (e.g., binance, okx) for quick access';

-- =============================================================================
-- DONE
-- =============================================================================





