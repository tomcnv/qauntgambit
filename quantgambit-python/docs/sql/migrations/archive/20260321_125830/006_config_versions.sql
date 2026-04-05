-- Migration: Add configuration version tracking table
-- Feature: trading-pipeline-integration
-- Requirements: 1.6 - THE System SHALL version all configuration changes with timestamps
--               and store them in the database for historical comparison
-- 
-- This migration adds a table to store versioned configuration snapshots
-- for ensuring parity between live trading and backtest systems.

-- Create the config_versions table
CREATE TABLE IF NOT EXISTS config_versions (
    -- Primary key: unique version identifier
    version_id TEXT PRIMARY KEY,
    
    -- Timestamp when this version was created
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Source of the configuration: "live", "backtest", or "optimizer"
    created_by TEXT NOT NULL,
    
    -- Deterministic hash of parameters for quick comparison
    config_hash TEXT NOT NULL,
    
    -- Full configuration parameters as JSON
    parameters JSONB NOT NULL,
    
    -- Whether this is the currently active configuration
    is_active BOOLEAN DEFAULT FALSE,
    
    -- Constraint to ensure created_by is valid
    CONSTRAINT config_versions_created_by_check 
        CHECK (created_by IN ('live', 'backtest', 'optimizer'))
);

-- Index for efficient retrieval of latest versions by created_at
CREATE INDEX IF NOT EXISTS idx_config_versions_created 
ON config_versions(created_at DESC);

-- Partial index for efficient lookup of active configuration
CREATE INDEX IF NOT EXISTS idx_config_versions_active 
ON config_versions(is_active) WHERE is_active = TRUE;

-- Index for filtering by source (created_by)
CREATE INDEX IF NOT EXISTS idx_config_versions_created_by 
ON config_versions(created_by, created_at DESC);

-- Index for looking up configurations by hash
CREATE INDEX IF NOT EXISTS idx_config_versions_hash 
ON config_versions(config_hash);

-- Add comments for documentation
COMMENT ON TABLE config_versions IS 
'Stores versioned configuration snapshots for trading pipeline integration. 
Each version represents a point-in-time snapshot of trading configuration parameters.';

COMMENT ON COLUMN config_versions.version_id IS 
'Unique identifier for this configuration version';

COMMENT ON COLUMN config_versions.created_at IS 
'Timestamp when this version was created';

COMMENT ON COLUMN config_versions.created_by IS 
'Source of the configuration: live (from live trading), backtest (from backtest run), or optimizer (from parameter optimization)';

COMMENT ON COLUMN config_versions.config_hash IS 
'16-character SHA256 hash of parameters for quick comparison';

COMMENT ON COLUMN config_versions.parameters IS 
'Full configuration parameters as JSON object';

COMMENT ON COLUMN config_versions.is_active IS 
'Whether this is the currently active configuration for live trading';
