-- Allow null user_id for system profile templates
-- System templates are available to all users, not owned by any specific user

-- Drop the existing foreign key constraint
ALTER TABLE user_chessboard_profiles 
DROP CONSTRAINT IF EXISTS user_chessboard_profiles_user_id_fkey;

-- Make user_id nullable
ALTER TABLE user_chessboard_profiles 
ALTER COLUMN user_id DROP NOT NULL;

-- Re-add the foreign key constraint but allow NULL
ALTER TABLE user_chessboard_profiles 
ADD CONSTRAINT user_chessboard_profiles_user_id_fkey 
FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Drop the existing unique constraint that includes user_id
ALTER TABLE user_chessboard_profiles 
DROP CONSTRAINT IF EXISTS user_chessboard_profiles_user_id_name_environment_key;

-- Add a partial unique constraint for user-owned profiles (where user_id is NOT NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_user_name_env_unique 
ON user_chessboard_profiles(user_id, name, environment) 
WHERE user_id IS NOT NULL;

-- Add a unique constraint for system templates (by name + environment, where user_id IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_system_template_unique
ON user_chessboard_profiles(name, environment)
WHERE is_system_template = true AND user_id IS NULL;

COMMENT ON COLUMN user_chessboard_profiles.user_id IS 
'Owner of the profile. NULL for system templates (visible to all users)';

COMMENT ON COLUMN user_chessboard_profiles.is_system_template IS 
'System templates are read-only and available to all users as a starting point for creating custom profiles';










