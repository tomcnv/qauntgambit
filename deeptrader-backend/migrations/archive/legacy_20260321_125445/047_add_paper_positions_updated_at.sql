-- Migration: Add updated_at column to paper_positions
-- This column was missing and is needed by the paper_executor.py

ALTER TABLE paper_positions 
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Create an index for efficient queries on recently updated positions
CREATE INDEX IF NOT EXISTS idx_paper_positions_updated_at 
ON paper_positions(updated_at DESC);

-- Update existing rows to have a sensible updated_at value
UPDATE paper_positions 
SET updated_at = COALESCE(closed_at, opened_at, CURRENT_TIMESTAMP) 
WHERE updated_at IS NULL;


