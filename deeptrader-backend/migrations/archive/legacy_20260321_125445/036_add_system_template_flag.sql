-- Add system template flag to profiles
-- System templates are visible to all users and can be cloned

-- Add the flag column
ALTER TABLE user_chessboard_profiles
ADD COLUMN IF NOT EXISTS is_system_template BOOLEAN DEFAULT FALSE;

-- Add index for efficient querying
CREATE INDEX IF NOT EXISTS idx_profiles_system_template 
ON user_chessboard_profiles(is_system_template) 
WHERE is_system_template = true;

-- Comment
COMMENT ON COLUMN user_chessboard_profiles.is_system_template IS 
'When true, this profile is a system template visible to all users for cloning';


