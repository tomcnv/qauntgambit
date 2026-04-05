-- Add is_system_template flag to strategy_instances
-- This allows us to identify canonical strategies from the Python registry

ALTER TABLE strategy_instances
ADD COLUMN IF NOT EXISTS is_system_template BOOLEAN DEFAULT FALSE;

-- Create index for fast lookup of system templates
CREATE INDEX IF NOT EXISTS idx_strategy_instances_system_template
ON strategy_instances(is_system_template)
WHERE is_system_template = true;

COMMENT ON COLUMN strategy_instances.is_system_template IS 
'When true, this strategy is a system template visible to all users for use in profiles';

