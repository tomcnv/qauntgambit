-- Migration: Create copilot conversation, message, and settings snapshot tables
-- Feature: trading-copilot-agent
-- Requirements: 12.1 - THE Conversation_Store SHALL persist all Conversations and Messages
--                      in PostgreSQL with no automatic expiration
--               14.4 - WHEN a Settings_Snapshot is created, THE Conversation_Store SHALL
--                      persist the snapshot with a version number, timestamp, the actor,
--                      and the associated Conversation ID
--
-- This migration creates the PostgreSQL tables for the trading copilot agent:
--   - copilot_conversations: stores conversation metadata per user
--   - copilot_messages: stores individual messages with tool call support
--   - copilot_settings_snapshots: stores versioned settings snapshots for rollback

-- ============================================================
-- Table: copilot_conversations
-- ============================================================
CREATE TABLE IF NOT EXISTS copilot_conversations (
    -- Primary key: UUID auto-generated
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Owner of the conversation
    user_id TEXT NOT NULL,

    -- Auto-generated title from first message (nullable)
    title TEXT,

    -- Timestamps for ordering and display
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for listing a user's conversations sorted by most recent activity
CREATE INDEX IF NOT EXISTS idx_copilot_conversations_user
ON copilot_conversations(user_id, updated_at DESC);

-- ============================================================
-- Table: copilot_messages
-- ============================================================
CREATE TABLE IF NOT EXISTS copilot_messages (
    -- Primary key: UUID auto-generated
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign key to parent conversation (cascade delete)
    conversation_id UUID NOT NULL
        REFERENCES copilot_conversations(id) ON DELETE CASCADE,

    -- Message role: 'user', 'assistant', or 'tool'
    role TEXT NOT NULL,

    -- Message text content
    content TEXT NOT NULL,

    -- Tool call records as JSON (nullable, only for assistant messages with tool calls)
    tool_calls JSONB,

    -- Tool call ID for tool result messages
    tool_call_id TEXT,

    -- When the message was created
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fetching messages in a conversation ordered by time
CREATE INDEX IF NOT EXISTS idx_copilot_messages_conversation
ON copilot_messages(conversation_id, timestamp);

-- GIN index for full-text search on message content
CREATE INDEX IF NOT EXISTS idx_copilot_messages_search
ON copilot_messages USING GIN (to_tsvector('english', content));

-- ============================================================
-- Table: copilot_settings_snapshots
-- ============================================================
CREATE TABLE IF NOT EXISTS copilot_settings_snapshots (
    -- Primary key: UUID auto-generated
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Owner of the snapshot
    user_id TEXT NOT NULL,

    -- Monotonically increasing version per user
    version INTEGER NOT NULL,

    -- Full settings state at time of snapshot
    settings JSONB NOT NULL,

    -- Who created the snapshot: 'copilot' or 'user'
    actor TEXT NOT NULL,

    -- Optional link to the conversation that triggered the snapshot
    conversation_id UUID REFERENCES copilot_conversations(id),

    -- Optional link to the mutation that triggered the snapshot
    mutation_id TEXT,

    -- When the snapshot was created
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for listing a user's snapshots sorted by version (newest first)
CREATE INDEX IF NOT EXISTS idx_copilot_settings_snapshots_user
ON copilot_settings_snapshots(user_id, version DESC);

-- ============================================================
-- Table and column comments
-- ============================================================
COMMENT ON TABLE copilot_conversations IS
'Stores copilot conversation metadata. Each conversation belongs to a user and persists permanently.';

COMMENT ON TABLE copilot_messages IS
'Stores individual messages within copilot conversations. Supports user, assistant, and tool roles with optional tool call data.';

COMMENT ON TABLE copilot_settings_snapshots IS
'Stores versioned point-in-time snapshots of user settings for rollback capability. Created when the copilot or user mutates settings.';
