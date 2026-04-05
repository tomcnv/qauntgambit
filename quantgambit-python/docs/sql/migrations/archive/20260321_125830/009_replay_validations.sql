-- Migration: 009_replay_validations.sql
-- Feature: trading-pipeline-integration
-- Requirements: 7.2 - WHEN replaying decisions THEN the System SHALL compare new
--               decisions against original decisions
-- Requirements: 7.3 - THE System SHALL report decision changes with categorization
--               (expected, unexpected, improved, degraded)
--
-- This migration creates the replay_validations table for storing replay
-- validation results. Each row represents a complete replay run with
-- aggregated statistics.

-- Replay validation results table
CREATE TABLE IF NOT EXISTS replay_validations (
    -- Primary key (auto-incrementing)
    id SERIAL PRIMARY KEY,
    
    -- Run identification
    run_id TEXT NOT NULL,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Time range that was replayed
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    
    -- Aggregated statistics
    total_replayed INT NOT NULL CHECK (total_replayed >= 0),
    matches INT NOT NULL CHECK (matches >= 0),
    changes INT NOT NULL CHECK (changes >= 0),
    match_rate FLOAT NOT NULL CHECK (match_rate >= 0.0 AND match_rate <= 1.0),
    
    -- Detailed breakdowns (stored as JSONB for flexibility)
    changes_by_category JSONB,
    changes_by_stage JSONB,
    
    -- Constraints
    CONSTRAINT replay_validations_totals_check 
        CHECK (matches + changes = total_replayed)
);

-- Index for querying by run_id
CREATE INDEX IF NOT EXISTS idx_replay_validations_run_id 
    ON replay_validations (run_id);

-- Index for querying by run_at (most recent runs)
CREATE INDEX IF NOT EXISTS idx_replay_validations_run_at 
    ON replay_validations (run_at DESC);

-- Index for querying by time range
CREATE INDEX IF NOT EXISTS idx_replay_validations_time_range 
    ON replay_validations (start_time, end_time);

-- Composite index for common query patterns
CREATE INDEX IF NOT EXISTS idx_replay_validations_run_at_match_rate 
    ON replay_validations (run_at DESC, match_rate);

-- Add comment to table
COMMENT ON TABLE replay_validations IS 
    'Stores replay validation results for comparing historical decisions against current pipeline';

-- Add comments to columns
COMMENT ON COLUMN replay_validations.run_id IS 
    'Unique identifier for this replay run';
COMMENT ON COLUMN replay_validations.run_at IS 
    'Timestamp when the replay was executed';
COMMENT ON COLUMN replay_validations.start_time IS 
    'Start of the time range that was replayed';
COMMENT ON COLUMN replay_validations.end_time IS 
    'End of the time range that was replayed';
COMMENT ON COLUMN replay_validations.total_replayed IS 
    'Total number of decisions replayed';
COMMENT ON COLUMN replay_validations.matches IS 
    'Number of decisions that matched original outcome';
COMMENT ON COLUMN replay_validations.changes IS 
    'Number of decisions that changed from original outcome';
COMMENT ON COLUMN replay_validations.match_rate IS 
    'Ratio of matches to total (0.0 to 1.0)';
COMMENT ON COLUMN replay_validations.changes_by_category IS 
    'JSON object with counts by category (expected, unexpected, improved, degraded)';
COMMENT ON COLUMN replay_validations.changes_by_stage IS 
    'JSON object with counts by stage difference (e.g., "ev_gate->amt_gate": 5)';
