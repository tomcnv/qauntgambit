-- Migration: 035_add_mounted_profile.sql
-- Add mounted profile reference to bot_exchange_configs
-- This links a specific profile (and version) to an exchange deployment

-- Add mounted profile columns
ALTER TABLE bot_exchange_configs
ADD COLUMN IF NOT EXISTS mounted_profile_id UUID REFERENCES user_chessboard_profiles(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS mounted_profile_version INTEGER,
ADD COLUMN IF NOT EXISTS mounted_at TIMESTAMPTZ;

-- Index for quick lookup of configs by mounted profile
CREATE INDEX IF NOT EXISTS idx_bot_exchange_configs_mounted_profile 
ON bot_exchange_configs(mounted_profile_id) 
WHERE mounted_profile_id IS NOT NULL;

-- Function to validate profile environment matches exchange environment
CREATE OR REPLACE FUNCTION validate_profile_environment_match()
RETURNS TRIGGER AS $$
DECLARE
    profile_env TEXT;
    config_env TEXT;
BEGIN
    IF NEW.mounted_profile_id IS NULL THEN
        RETURN NEW;
    END IF;
    
    -- Get profile environment
    SELECT environment::TEXT INTO profile_env
    FROM user_chessboard_profiles
    WHERE id = NEW.mounted_profile_id;
    
    -- Get config environment
    config_env := NEW.environment::TEXT;
    
    -- Validate: Dev profiles can only mount to dev, Paper to paper, Live to live
    -- Exception: Paper profiles can mount to dev for testing
    IF profile_env = 'live' AND config_env != 'live' THEN
        RAISE EXCEPTION 'Live profiles can only be mounted on live exchange configs';
    END IF;
    
    IF profile_env = 'dev' AND config_env = 'live' THEN
        RAISE EXCEPTION 'Dev profiles cannot be mounted on live exchange configs';
    END IF;
    
    IF profile_env = 'paper' AND config_env = 'live' THEN
        RAISE EXCEPTION 'Paper profiles cannot be mounted on live exchange configs. Promote to Live first.';
    END IF;
    
    -- Set mounted timestamp
    NEW.mounted_at = NOW();
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_validate_profile_environment ON bot_exchange_configs;
CREATE TRIGGER trigger_validate_profile_environment
    BEFORE INSERT OR UPDATE OF mounted_profile_id ON bot_exchange_configs
    FOR EACH ROW
    EXECUTE FUNCTION validate_profile_environment_match();

-- Function to update strategy instance usage counts
CREATE OR REPLACE FUNCTION update_strategy_instance_usage()
RETURNS TRIGGER AS $$
DECLARE
    old_strategy_ids UUID[];
    new_strategy_ids UUID[];
    strategy_id UUID;
BEGIN
    -- Extract strategy instance IDs from old composition
    IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN
        SELECT ARRAY_AGG((elem->>'instance_id')::UUID)
        INTO old_strategy_ids
        FROM jsonb_array_elements(OLD.strategy_composition) elem
        WHERE elem->>'instance_id' IS NOT NULL;
    END IF;
    
    -- Extract strategy instance IDs from new composition
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        SELECT ARRAY_AGG((elem->>'instance_id')::UUID)
        INTO new_strategy_ids
        FROM jsonb_array_elements(NEW.strategy_composition) elem
        WHERE elem->>'instance_id' IS NOT NULL;
    END IF;
    
    -- Decrement count for removed strategies
    IF old_strategy_ids IS NOT NULL THEN
        FOREACH strategy_id IN ARRAY old_strategy_ids LOOP
            IF new_strategy_ids IS NULL OR NOT strategy_id = ANY(new_strategy_ids) THEN
                UPDATE strategy_instances 
                SET usage_count = GREATEST(0, usage_count - 1)
                WHERE id = strategy_id;
            END IF;
        END LOOP;
    END IF;
    
    -- Increment count for added strategies
    IF new_strategy_ids IS NOT NULL THEN
        FOREACH strategy_id IN ARRAY new_strategy_ids LOOP
            IF old_strategy_ids IS NULL OR NOT strategy_id = ANY(old_strategy_ids) THEN
                UPDATE strategy_instances 
                SET usage_count = usage_count + 1
                WHERE id = strategy_id;
            END IF;
        END LOOP;
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_strategy_usage ON user_chessboard_profiles;
CREATE TRIGGER trigger_update_strategy_usage
    AFTER INSERT OR UPDATE OF strategy_composition OR DELETE ON user_chessboard_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_strategy_instance_usage();

-- Comments
COMMENT ON COLUMN bot_exchange_configs.mounted_profile_id IS 'The user profile currently mounted for trading on this exchange';
COMMENT ON COLUMN bot_exchange_configs.mounted_profile_version IS 'The specific version of the profile that was mounted';
COMMENT ON COLUMN bot_exchange_configs.mounted_at IS 'Timestamp when the profile was mounted';


