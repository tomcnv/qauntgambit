-- Migration: 003_execution_diagnostics
-- Description: Adds execution_diagnostics JSONB column to backtest_runs table
-- Feature: backtest-diagnostics
-- Requirements: 1.4 - THE Execution_Diagnostics SHALL be stored with the backtest results in the database
-- Date: 2026-01-15

-- Add execution_diagnostics column to backtest_runs
-- This stores detailed diagnostics about backtest execution including:
-- - total_snapshots, snapshots_processed, snapshots_skipped
-- - global_gate_rejections with breakdown by reason
-- - profiles_selected, signals_generated, cooldown_rejections
-- - summary, primary_issue, suggestions
ALTER TABLE backtest_runs 
ADD COLUMN IF NOT EXISTS execution_diagnostics JSONB DEFAULT NULL;

-- Add comment for documentation
COMMENT ON COLUMN backtest_runs.execution_diagnostics IS 
'JSONB containing execution diagnostics: total_snapshots, snapshots_processed, snapshots_skipped, global_gate_rejections, rejection_breakdown, profiles_selected, signals_generated, cooldown_rejections, summary, primary_issue, suggestions';

-- Rollback script (run manually if needed):
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS execution_diagnostics;
