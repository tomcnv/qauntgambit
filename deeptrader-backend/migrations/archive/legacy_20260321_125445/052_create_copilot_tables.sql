-- Migration: Create copilot conversation/message/snapshot tables
-- Created: 2026-02-18
-- Description:
--   The bot-api copilot endpoints persist conversations + messages in the *platform*
--   database (dashboard_pool). In AWS we were missing these tables, causing:
--     asyncpg.exceptions.UndefinedTableError: relation "copilot_conversations" does not exist
--
--   This migration is idempotent.

-- gen_random_uuid() comes from pgcrypto.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- Table: copilot_conversations
-- ============================================================
CREATE TABLE IF NOT EXISTS copilot_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_copilot_conversations_user
ON copilot_conversations(user_id, updated_at DESC);

-- ============================================================
-- Table: copilot_messages
-- ============================================================
CREATE TABLE IF NOT EXISTS copilot_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL
        REFERENCES copilot_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls JSONB,
    tool_call_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_copilot_messages_conversation
ON copilot_messages(conversation_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_copilot_messages_search
ON copilot_messages USING GIN (to_tsvector('english', content));

-- ============================================================
-- Table: copilot_settings_snapshots
-- ============================================================
CREATE TABLE IF NOT EXISTS copilot_settings_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    settings JSONB NOT NULL,
    actor TEXT NOT NULL,
    conversation_id UUID REFERENCES copilot_conversations(id),
    mutation_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_copilot_settings_snapshots_user
ON copilot_settings_snapshots(user_id, version DESC);

COMMENT ON TABLE copilot_conversations IS
'Stores copilot conversation metadata. Each conversation belongs to a user and persists permanently.';

COMMENT ON TABLE copilot_messages IS
'Stores individual messages within copilot conversations. Supports user, assistant, and tool roles with optional tool call data.';

COMMENT ON TABLE copilot_settings_snapshots IS
'Stores versioned point-in-time snapshots of user settings for rollback capability.';

