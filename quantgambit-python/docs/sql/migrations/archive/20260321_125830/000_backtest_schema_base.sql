-- Migration: 000_backtest_schema_base
-- Description: Creates base backtest tables for research and backtesting functionality
-- Date: 2026-01-15
-- Target Database: platform_db (port 5432)
--
-- Requirements: 2.5, 2.6 (End-to-End Integration Verification)
-- - Creates all required backtest tables with proper schema
-- - Uses IF NOT EXISTS for idempotent execution (safe to run multiple times)
-- - Includes foreign key constraints for data integrity
--
-- Tables created:
--   1. backtest_runs - Stores backtest run metadata and configuration
--   2. backtest_metrics - Stores computed metrics for each backtest run
--   3. backtest_trades - Stores individual trades executed during backtest
--   4. backtest_equity_curve - Stores equity curve data points over time
--   5. wfo_runs - Stores walk-forward optimization runs
--
-- All tables use UUID primary keys and TIMESTAMPTZ for timestamps.
-- Foreign keys reference backtest_runs with ON DELETE CASCADE.

-- ============================================================================
-- Table: backtest_runs
-- Purpose: Stores metadata for each backtest run including configuration,
--          status, and timing information.
-- Columns:
--   - run_id: Unique identifier for the backtest run (UUID)
--   - tenant_id: Multi-tenant identifier
--   - bot_id: Identifier for the trading bot
--   - name: Human-readable name for the backtest (strategy name)
--   - symbol: Trading symbol (e.g., BTC-USD)
--   - status: Current status (pending, running, completed, failed)
--   - created_at: Timestamp when the run was created
-- ============================================================================
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    name TEXT,
    symbol TEXT,
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    config JSONB NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for backtest_runs (for query performance)
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_idx ON backtest_runs (tenant_id);
CREATE INDEX IF NOT EXISTS backtest_runs_status_idx ON backtest_runs (status);
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_status_idx ON backtest_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS backtest_runs_symbol_idx ON backtest_runs (symbol);
CREATE INDEX IF NOT EXISTS backtest_runs_created_at_idx ON backtest_runs (created_at DESC);

-- ============================================================================
-- Table: backtest_metrics
-- Purpose: Stores computed performance metrics for each backtest run.
--          One-to-one relationship with backtest_runs.
-- Columns:
--   - run_id: Foreign key to backtest_runs (also primary key)
--   - realized_pnl: Total realized profit/loss
--   - total_trades: Number of trades executed
--   - win_rate: Percentage of winning trades
--   - max_drawdown_pct: Maximum drawdown percentage
--   - profit_factor: Ratio of gross profit to gross loss
-- ============================================================================
CREATE TABLE IF NOT EXISTS backtest_metrics (
    run_id UUID PRIMARY KEY REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    realized_pnl FLOAT NOT NULL,
    total_fees FLOAT NOT NULL,
    total_trades INTEGER NOT NULL,
    win_rate FLOAT NOT NULL,
    max_drawdown_pct FLOAT NOT NULL,
    avg_slippage_bps FLOAT NOT NULL,
    total_return_pct FLOAT NOT NULL,
    profit_factor FLOAT NOT NULL,
    avg_trade_pnl FLOAT NOT NULL
);

-- Create index for backtest_metrics (for query performance)
CREATE INDEX IF NOT EXISTS backtest_metrics_run_id_idx ON backtest_metrics (run_id);

-- ============================================================================
-- Table: backtest_trades
-- Purpose: Stores individual trades executed during a backtest.
--          Many-to-one relationship with backtest_runs.
-- Columns:
--   - run_id: Foreign key to backtest_runs
--   - ts: Timestamp of the trade
--   - symbol: Trading symbol
--   - side: Trade side (buy/sell)
--   - entry_price: Price at entry
--   - exit_price: Price at exit
--   - pnl: Profit/loss for this trade
-- ============================================================================
CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id UUID REFERENCES backtest_runs(run_id) ON DELETE CASCADE NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size FLOAT NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT NOT NULL,
    pnl FLOAT NOT NULL,
    entry_fee FLOAT NOT NULL,
    exit_fee FLOAT NOT NULL,
    total_fees FLOAT NOT NULL,
    entry_slippage_bps FLOAT NOT NULL,
    exit_slippage_bps FLOAT NOT NULL,
    strategy_id TEXT,
    profile_id TEXT,
    reason TEXT
);

-- Create indexes for backtest_trades (for query performance)
CREATE INDEX IF NOT EXISTS backtest_trades_idx ON backtest_trades (run_id, ts DESC);
CREATE INDEX IF NOT EXISTS backtest_trades_symbol_idx ON backtest_trades (symbol);

-- ============================================================================
-- Table: backtest_equity_curve
-- Purpose: Stores equity curve data points over time for visualization.
--          Many-to-one relationship with backtest_runs.
-- Columns:
--   - run_id: Foreign key to backtest_runs
--   - ts: Timestamp of the data point
--   - equity: Total equity value at this point
--   - realized_pnl: Cumulative realized P&L
--   - open_positions: Number of open positions
-- ============================================================================
CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    run_id UUID REFERENCES backtest_runs(run_id) ON DELETE CASCADE NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    equity FLOAT NOT NULL,
    realized_pnl FLOAT NOT NULL,
    open_positions INTEGER NOT NULL
);

-- Create index for backtest_equity_curve (for query performance)
CREATE INDEX IF NOT EXISTS backtest_equity_curve_idx ON backtest_equity_curve (run_id, ts DESC);

-- ============================================================================
-- Table: wfo_runs
-- Purpose: Stores walk-forward optimization runs for strategy optimization.
-- Columns:
--   - run_id: Unique identifier for the WFO run
--   - tenant_id: Multi-tenant identifier
--   - bot_id: Identifier for the trading bot
--   - status: Current status of the optimization
--   - config: JSON configuration for the optimization
--   - results: JSON results from the optimization
-- ============================================================================
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

-- Create indexes for wfo_runs (for query performance)
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_idx ON wfo_runs (tenant_id);
CREATE INDEX IF NOT EXISTS wfo_runs_status_idx ON wfo_runs (status);
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_status_idx ON wfo_runs (tenant_id, status);

-- ============================================================================
-- Rollback script (run manually if needed):
-- ============================================================================
-- DROP TABLE IF EXISTS wfo_runs CASCADE;
-- DROP TABLE IF EXISTS backtest_equity_curve CASCADE;
-- DROP TABLE IF EXISTS backtest_trades CASCADE;
-- DROP TABLE IF EXISTS backtest_metrics CASCADE;
-- DROP TABLE IF EXISTS backtest_runs CASCADE;
