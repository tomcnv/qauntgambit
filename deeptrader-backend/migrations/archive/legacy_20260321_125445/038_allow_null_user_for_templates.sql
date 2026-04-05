-- Allow null user_id for system template strategies
-- System templates are available to all users, not owned by any specific user

-- Drop the existing constraint
ALTER TABLE strategy_instances 
DROP CONSTRAINT IF EXISTS strategy_instances_user_id_name_key;

-- Make user_id nullable
ALTER TABLE strategy_instances 
ALTER COLUMN user_id DROP NOT NULL;

-- Add a partial unique constraint for user-owned strategies
CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_instances_user_name_unique 
ON strategy_instances(user_id, name) 
WHERE user_id IS NOT NULL;

-- Add a unique constraint for system templates (by template_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_instances_system_template_unique
ON strategy_instances(template_id)
WHERE is_system_template = true;

COMMENT ON COLUMN strategy_instances.user_id IS 
'Owner of the strategy instance. NULL for system templates (visible to all users)';

