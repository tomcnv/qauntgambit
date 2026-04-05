-- Migration: Add recorded decisions table for decision replay
-- Feature: trading-pipeline-integration
-- Requirements: 2.1 - WHEN a live trading decision is made THEN the System SHALL record
--               the complete decision context including market snapshot, features,
--               stage results, and final decision
-- Requirements: 2.2 - THE System SHALL store decision records in TimescaleDB with
--               efficient time-range queries
-- Requirements: 2.3 - WHEN recording a decision THEN the System SHALL include all
--               pipeline stage outputs and rejection reasons
-- Requirements: 2.4 - THE System SHALL support querying decisions by time range,
--               symbol, decision outcome, and rejection stage
-- Requirements: 2.5 - WHEN a decision is recorded THEN the System SHALL include
--               the configuration version used for that decision
--
-- This migration adds a hypertable to store complete decision records for
-- replay and analysis of historical trading decisions.

-- Create the recorded_decisions table
CREATE TABLE IF NOT EXISTS recorded_decisions (
    -- Unique decision identifier
    decision_id TEXT NOT NULL,
    
    -- Timestamp when the decision was made (used for hypertable partitioning)
    timestamp TIMESTAMPTZ NOT NULL,
    
    -- Trading symbol (e.g., "BTCUSDT")
    symbol TEXT NOT NULL,
    
    -- Configuration version used for this decision
    -- References config_versions table for traceability
    config_version TEXT NOT NULL REFERENCES config_versions(version_id),
    
    -- Complete market state at decision time (prices, orderbook, etc.)
    market_snapshot JSONB NOT NULL,
    
    -- Computed features used for decision making
    features JSONB NOT NULL,
    
    -- Current open positions at decision time
    positions JSONB,
    
    -- Account state (equity, margin, etc.) at decision time
    account_state JSONB,
    
    -- Output from each pipeline stage
    stage_results JSONB,
    
    -- Name of stage that rejected (if rejected)
    rejection_stage TEXT,
    
    -- Reason for rejection (if rejected)
    rejection_reason TEXT,
    
    -- Final decision outcome: "accepted", "rejected", or "shadow"
    decision TEXT NOT NULL,
    
    -- Generated signal details (if accepted)
    signal JSONB,
    
    -- Trading profile ID used for this decision
    profile_id TEXT,
    
    -- Constraint to ensure decision is valid
    CONSTRAINT recorded_decisions_decision_check 
        CHECK (decision IN ('accepted', 'rejected', 'shadow')),
    
    -- Composite primary key including timestamp for TimescaleDB hypertable compatibility
    PRIMARY KEY (decision_id, timestamp)
);

-- Convert to TimescaleDB hypertable when extension is available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable(
            'recorded_decisions',
            'timestamp',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;

-- Index for querying by symbol and time (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_recorded_decisions_symbol 
ON recorded_decisions(symbol, timestamp DESC);

-- Index for querying by decision outcome and time
CREATE INDEX IF NOT EXISTS idx_recorded_decisions_decision 
ON recorded_decisions(decision, timestamp DESC);

-- Index for querying by rejection stage (useful for debugging)
CREATE INDEX IF NOT EXISTS idx_recorded_decisions_rejection_stage 
ON recorded_decisions(rejection_stage, timestamp DESC) 
WHERE rejection_stage IS NOT NULL;

-- Index for querying by config version (useful for replay validation)
CREATE INDEX IF NOT EXISTS idx_recorded_decisions_config_version 
ON recorded_decisions(config_version, timestamp DESC);

-- Index for querying by profile ID
CREATE INDEX IF NOT EXISTS idx_recorded_decisions_profile 
ON recorded_decisions(profile_id, timestamp DESC) 
WHERE profile_id IS NOT NULL;

-- Composite index for common filter combinations
CREATE INDEX IF NOT EXISTS idx_recorded_decisions_symbol_decision 
ON recorded_decisions(symbol, decision, timestamp DESC);

-- Add comments for documentation
COMMENT ON TABLE recorded_decisions IS 
'Stores complete decision records for replay and analysis. Each record captures 
the full context of a trading decision including market state, features, pipeline 
execution, and final outcome. Uses TimescaleDB hypertable for efficient time-range queries.';

COMMENT ON COLUMN recorded_decisions.decision_id IS 
'Unique identifier for this decision record (format: dec_XXXXXXXXXXXX)';

COMMENT ON COLUMN recorded_decisions.timestamp IS 
'Timestamp when the decision was made (UTC)';

COMMENT ON COLUMN recorded_decisions.symbol IS 
'Trading symbol (e.g., BTCUSDT)';

COMMENT ON COLUMN recorded_decisions.config_version IS 
'Version ID of the configuration used for this decision (references config_versions)';

COMMENT ON COLUMN recorded_decisions.market_snapshot IS 
'Complete market state at decision time including prices, orderbook depth, spread, etc.';

COMMENT ON COLUMN recorded_decisions.features IS 
'Computed features used for decision making (AMT, volatility, trend, etc.)';

COMMENT ON COLUMN recorded_decisions.positions IS 
'Current open positions at decision time with entry prices, sizes, and timestamps';

COMMENT ON COLUMN recorded_decisions.account_state IS 
'Account state at decision time including equity, margin, available balance';

COMMENT ON COLUMN recorded_decisions.stage_results IS 
'Output from each pipeline stage as array of {stage, passed, reason, metrics}';

COMMENT ON COLUMN recorded_decisions.rejection_stage IS 
'Name of the pipeline stage that rejected the decision (NULL if accepted)';

COMMENT ON COLUMN recorded_decisions.rejection_reason IS 
'Human-readable reason for rejection (NULL if accepted)';

COMMENT ON COLUMN recorded_decisions.decision IS 
'Final decision outcome: accepted (signal generated), rejected (filtered out), shadow (shadow mode comparison)';

COMMENT ON COLUMN recorded_decisions.signal IS 
'Generated signal details if accepted (side, size, entry, targets, etc.)';

COMMENT ON COLUMN recorded_decisions.profile_id IS 
'Trading profile ID used for this decision (from profile router)';

-- Set up retention policy (default 90 days as per requirement 2.6)
-- This can be adjusted via TimescaleDB retention policies
-- SELECT add_retention_policy('recorded_decisions', INTERVAL '90 days', if_not_exists => TRUE);
-- Note: Uncomment the above line to enable automatic retention. 
-- Keeping it commented to allow manual configuration per deployment.
