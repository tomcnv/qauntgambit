-- Migration: 001_backtest_schema_enhancements
-- Description: Adds missing columns to backtest tables and creates wfo_runs table
-- Date: 2026-01-15

-- Add missing columns to backtest_runs
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS symbol TEXT;
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ;
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS end_date TIMESTAMPTZ;
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- Add indexes for performance (run_id, tenant_id, status)
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_idx ON backtest_runs (tenant_id);
CREATE INDEX IF NOT EXISTS backtest_runs_status_idx ON backtest_runs (status);
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_status_idx ON backtest_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS backtest_runs_symbol_idx ON backtest_runs (symbol);

-- Create wfo_runs table for walk-forward optimization
CREATE TABLE IF NOT EXISTS wfo_runs (
    run_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    profile_id TEXT,
    symbol TEXT,
    status TEXT NOT NULL,
    config JSONB,
    results JSONB,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add indexes for wfo_runs
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_idx ON wfo_runs (tenant_id);
CREATE INDEX IF NOT EXISTS wfo_runs_status_idx ON wfo_runs (status);
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_status_idx ON wfo_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS wfo_runs_profile_idx ON wfo_runs (profile_id);
CREATE INDEX IF NOT EXISTS wfo_runs_symbol_idx ON wfo_runs (symbol);

-- Rollback script (run manually if needed):
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS name;
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS symbol;
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS start_date;
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS end_date;
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS error_message;
-- ALTER TABLE backtest_runs DROP COLUMN IF EXISTS created_at;
-- DROP INDEX IF EXISTS backtest_runs_tenant_idx;
-- DROP INDEX IF EXISTS backtest_runs_status_idx;
-- DROP INDEX IF EXISTS backtest_runs_tenant_status_idx;
-- DROP INDEX IF EXISTS backtest_runs_symbol_idx;
-- DROP TABLE IF EXISTS wfo_runs;
