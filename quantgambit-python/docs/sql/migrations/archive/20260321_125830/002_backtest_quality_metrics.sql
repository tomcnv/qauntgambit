-- Migration: Add backtest quality metrics table
-- Feature: backtest-data-validation
-- Requirements: 5.1, 5.2, 5.3, 7.5
-- 
-- This migration adds a table to store data quality metrics for backtest runs.
-- Quality metrics include pre-flight validation results and runtime quality tracking.

-- Create the backtest_quality_metrics table
CREATE TABLE IF NOT EXISTS backtest_quality_metrics (
    run_id UUID PRIMARY KEY REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    
    -- Pre-flight validation metrics
    data_quality_grade VARCHAR(1) NOT NULL DEFAULT 'A',  -- A, B, C, D, F
    data_completeness_pct FLOAT NOT NULL DEFAULT 100.0,
    total_gaps INT NOT NULL DEFAULT 0,
    critical_gaps INT NOT NULL DEFAULT 0,
    
    -- Runtime quality metrics
    missing_price_count INT NOT NULL DEFAULT 0,
    missing_depth_count INT NOT NULL DEFAULT 0,
    
    -- Warnings and metadata
    quality_warnings JSONB DEFAULT '[]'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create index for filtering by grade
CREATE INDEX IF NOT EXISTS idx_backtest_quality_metrics_grade 
ON backtest_quality_metrics(data_quality_grade);

-- Create index for filtering by completeness
CREATE INDEX IF NOT EXISTS idx_backtest_quality_metrics_completeness 
ON backtest_quality_metrics(data_completeness_pct);

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_backtest_quality_metrics_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_backtest_quality_metrics_updated_at 
ON backtest_quality_metrics;

CREATE TRIGGER trigger_update_backtest_quality_metrics_updated_at
    BEFORE UPDATE ON backtest_quality_metrics
    FOR EACH ROW
    EXECUTE FUNCTION update_backtest_quality_metrics_updated_at();

-- Add comment for documentation
COMMENT ON TABLE backtest_quality_metrics IS 
'Stores data quality metrics for backtest runs including pre-flight validation and runtime tracking';

COMMENT ON COLUMN backtest_quality_metrics.data_quality_grade IS 
'Quality grade: A (>=95%), B (>=85%), C (>=70%), D (>=50%), F (<50%)';

COMMENT ON COLUMN backtest_quality_metrics.data_completeness_pct IS 
'Overall data completeness percentage from pre-flight validation';

COMMENT ON COLUMN backtest_quality_metrics.total_gaps IS 
'Total number of data gaps detected during validation';

COMMENT ON COLUMN backtest_quality_metrics.critical_gaps IS 
'Number of critical gaps (during trading hours, >15 minutes)';

COMMENT ON COLUMN backtest_quality_metrics.missing_price_count IS 
'Count of snapshots missing price data during runtime';

COMMENT ON COLUMN backtest_quality_metrics.missing_depth_count IS 
'Count of snapshots missing depth data during runtime';

COMMENT ON COLUMN backtest_quality_metrics.quality_warnings IS 
'JSON array of warning messages from validation';
