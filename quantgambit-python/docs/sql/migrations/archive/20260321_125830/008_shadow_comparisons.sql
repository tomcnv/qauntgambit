-- Migration: 008_shadow_comparisons
-- Feature: trading-pipeline-integration
-- Requirements: 4.2 - WHEN shadow mode is enabled THEN the System SHALL record
--               both live and shadow decisions for each market event
-- Requirements: 4.3 - THE System SHALL compute decision agreement rate between
--               live and shadow pipelines
--
-- This migration creates the shadow_comparisons table for storing comparison
-- results between live and shadow pipeline decisions.

-- Shadow comparison results
CREATE TABLE IF NOT EXISTS shadow_comparisons (
    id SERIAL,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    live_decision TEXT NOT NULL,
    shadow_decision TEXT NOT NULL,
    agrees BOOLEAN NOT NULL,
    divergence_reason TEXT,
    live_config_version TEXT,
    shadow_config_version TEXT
);

-- Create hypertable when TimescaleDB is available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('shadow_comparisons', 'timestamp', if_not_exists => TRUE);
    END IF;
END $$;

-- Index for querying by symbol and time
CREATE INDEX IF NOT EXISTS idx_shadow_comparisons_symbol_time 
    ON shadow_comparisons(symbol, timestamp DESC);

-- Index for querying by agreement status
CREATE INDEX IF NOT EXISTS idx_shadow_comparisons_agrees 
    ON shadow_comparisons(agrees, timestamp DESC);

-- Index for querying divergences by reason
CREATE INDEX IF NOT EXISTS idx_shadow_comparisons_divergence 
    ON shadow_comparisons(divergence_reason, timestamp DESC) 
    WHERE divergence_reason IS NOT NULL;

-- Index for querying by config versions
CREATE INDEX IF NOT EXISTS idx_shadow_comparisons_config_versions 
    ON shadow_comparisons(live_config_version, shadow_config_version, timestamp DESC);

-- Add comment for documentation
COMMENT ON TABLE shadow_comparisons IS 
    'Stores comparison results between live and shadow pipeline decisions for shadow mode validation';

COMMENT ON COLUMN shadow_comparisons.timestamp IS 
    'When the comparison was made';

COMMENT ON COLUMN shadow_comparisons.symbol IS 
    'Trading symbol (e.g., BTCUSDT)';

COMMENT ON COLUMN shadow_comparisons.live_decision IS 
    'Decision from live pipeline (accepted or rejected)';

COMMENT ON COLUMN shadow_comparisons.shadow_decision IS 
    'Decision from shadow pipeline (accepted or rejected)';

COMMENT ON COLUMN shadow_comparisons.agrees IS 
    'True if live_decision equals shadow_decision';

COMMENT ON COLUMN shadow_comparisons.divergence_reason IS 
    'Reason for divergence if decisions differ (e.g., stage_diff:ev_gate vs data_readiness)';

COMMENT ON COLUMN shadow_comparisons.live_config_version IS 
    'Configuration version used by live pipeline';

COMMENT ON COLUMN shadow_comparisons.shadow_config_version IS 
    'Configuration version used by shadow pipeline';
