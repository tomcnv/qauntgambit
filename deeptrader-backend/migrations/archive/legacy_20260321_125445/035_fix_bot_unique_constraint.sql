-- Migration: 035_fix_bot_unique_constraint.sql
-- Purpose: Update unique constraint on bot_instances to exclude soft-deleted bots
--
-- Problem: The unique constraint on (user_id, name) prevents creating new bots
-- with the same name as a soft-deleted bot.
--
-- Solution: Replace the unique constraint with a partial unique index that only
-- applies to non-deleted bots (deleted_at IS NULL).

-- =============================================================================
-- PHASE 1: Drop the existing unique constraint
-- =============================================================================

ALTER TABLE bot_instances 
    DROP CONSTRAINT IF EXISTS bot_instances_user_id_name_key;

-- =============================================================================
-- PHASE 2: Create a partial unique index that excludes deleted bots
-- =============================================================================

-- This allows reusing bot names after deletion while still preventing duplicates
-- among active bots
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_instances_unique_name 
    ON bot_instances(user_id, name) 
    WHERE deleted_at IS NULL;

-- =============================================================================
-- PHASE 3: Add comments
-- =============================================================================

COMMENT ON INDEX idx_bot_instances_unique_name IS 
    'Ensures unique bot names per user, excluding soft-deleted bots';

-- =============================================================================
-- DONE
-- =============================================================================





