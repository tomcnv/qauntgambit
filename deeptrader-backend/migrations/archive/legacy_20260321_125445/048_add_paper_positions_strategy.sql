-- Add strategy tracking columns to paper_positions
-- This allows tracking which strategy/profile opened each position

ALTER TABLE paper_positions
ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(100);

ALTER TABLE paper_positions  
ADD COLUMN IF NOT EXISTS profile_id VARCHAR(100);

-- Add index for querying by strategy
CREATE INDEX IF NOT EXISTS idx_paper_positions_strategy
ON paper_positions(strategy_id) WHERE strategy_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_paper_positions_profile
ON paper_positions(profile_id) WHERE profile_id IS NOT NULL;

COMMENT ON COLUMN paper_positions.strategy_id IS 'ID of the strategy that opened this position';
COMMENT ON COLUMN paper_positions.profile_id IS 'ID of the profile that opened this position';


