-- Migration: 034_add_deleted_at_column.sql
-- Purpose: Add proper soft delete support with deleted_at timestamp

-- =============================================================================
-- PHASE 1: Add deleted_at column to bot_instances
-- =============================================================================

ALTER TABLE bot_instances 
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_bot_instances_deleted ON bot_instances(deleted_at) WHERE deleted_at IS NOT NULL;

COMMENT ON COLUMN bot_instances.deleted_at IS 'Soft delete timestamp - when set, bot is considered deleted';
COMMENT ON COLUMN bot_instances.deleted_by IS 'User who deleted the bot';

-- =============================================================================
-- PHASE 2: Add deleted_at to bot_exchange_configs
-- =============================================================================

ALTER TABLE bot_exchange_configs 
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_deleted ON bot_exchange_configs(deleted_at) WHERE deleted_at IS NOT NULL;

COMMENT ON COLUMN bot_exchange_configs.deleted_at IS 'Soft delete timestamp';

-- =============================================================================
-- DONE
-- =============================================================================





