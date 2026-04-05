-- Migration: Bot configuration profiles & versioning
-- Date: 2025-11-29
-- Description: Create tables for versioned bot configuration management

-- Ensure UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Bot profiles represent logical bots per environment
CREATE TABLE IF NOT EXISTS bot_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('dev', 'paper', 'live')),
    engine_type TEXT NOT NULL DEFAULT 'fast_scalper',
    description TEXT,
    status TEXT NOT NULL DEFAULT 'inactive' CHECK (status IN ('inactive', 'ready', 'running', 'error')),
    owner_id UUID,
    active_version_id UUID,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_profiles_environment ON bot_profiles(environment);
CREATE INDEX IF NOT EXISTS idx_bot_profiles_status ON bot_profiles(status);

-- Version table stores immutable config payloads
CREATE TABLE IF NOT EXISTS bot_profile_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_profile_id UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'testing', 'active', 'retired')),
    config_blob JSONB NOT NULL,
    checksum TEXT,
    notes TEXT,
    created_by UUID,
    promoted_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (bot_profile_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_bot_profile_versions_profile ON bot_profile_versions(bot_profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_profile_versions_status ON bot_profile_versions(status);

-- Optional section breakdowns per version (risk, allocator, per-symbol overrides, etc.)
CREATE TABLE IF NOT EXISTS bot_version_sections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_profile_version_id UUID NOT NULL REFERENCES bot_profile_versions(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bot_profile_version_id, section)
);

-- Audit log for config + control actions
CREATE TABLE IF NOT EXISTS bot_config_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_profile_id UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    bot_profile_version_id UUID REFERENCES bot_profile_versions(id) ON DELETE SET NULL,
    action TEXT NOT NULL CHECK (action IN (
        'create_profile',
        'clone_version',
        'update_version',
        'promote_version',
        'activate_version',
        'rollback_version',
        'start_bot',
        'stop_bot',
        'pause_bot',
        'resume_bot'
    )),
    metadata JSONB DEFAULT '{}'::jsonb,
    performed_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_config_actions_profile ON bot_config_actions(bot_profile_id);
CREATE INDEX IF NOT EXISTS idx_bot_config_actions_action ON bot_config_actions(action);

-- Tie active version FK now that versions table exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'bot_profiles_active_version_fk'
          AND conrelid = 'public.bot_profiles'::regclass
    ) THEN
        ALTER TABLE bot_profiles
            ADD CONSTRAINT bot_profiles_active_version_fk
            FOREIGN KEY (active_version_id)
            REFERENCES bot_profile_versions(id)
            ON DELETE SET NULL;
    END IF;
END $$;

COMMENT ON TABLE bot_profiles IS 'Logical trading bots grouped by environment';
COMMENT ON COLUMN bot_profiles.active_version_id IS 'Currently active configuration version';
COMMENT ON TABLE bot_profile_versions IS 'Immutable configuration payloads for each bot profile';
COMMENT ON TABLE bot_version_sections IS 'Optional per-section payloads extracted from config blobs';
COMMENT ON TABLE bot_config_actions IS 'Audit trail for bot configuration + control plane actions';





