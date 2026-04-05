-- Migration: Create backtest tables
-- Date: 2025-11-29
-- Description: Tables for storing backtest runs, trades, and equity curves

-- Backtest runs table
CREATE TABLE IF NOT EXISTS backtest_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'okx',
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,
    initial_capital DECIMAL(15, 2) NOT NULL DEFAULT 10000.0,
    commission_per_trade DECIMAL(5, 4) NOT NULL DEFAULT 0.001,
    slippage_model TEXT NOT NULL DEFAULT 'fixed',
    slippage_bps DECIMAL(5, 2) NOT NULL DEFAULT 5.0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    -- Results
    total_return_percent DECIMAL(10, 4),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown_percent DECIMAL(10, 4),
    win_rate DECIMAL(5, 4),
    total_trades INTEGER,
    profit_factor DECIMAL(10, 4),
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_user_id ON backtest_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_id ON backtest_runs(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_status ON backtest_runs(status);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created_at ON backtest_runs(created_at DESC);

-- Backtest trades table
CREATE TABLE IF NOT EXISTS backtest_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    entry_price DECIMAL(15, 8) NOT NULL,
    exit_price DECIMAL(15, 8),
    size DECIMAL(15, 8) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    pnl DECIMAL(15, 8),
    pnl_percent DECIMAL(10, 4),
    commission DECIMAL(15, 8) DEFAULT 0,
    slippage DECIMAL(15, 8) DEFAULT 0,
    duration_seconds INTEGER,
    exit_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id ON backtest_trades(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_entry_time ON backtest_trades(entry_time);

-- Backtest equity curve table
CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    equity DECIMAL(15, 2) NOT NULL,
    drawdown DECIMAL(10, 4),
    drawdown_percent DECIMAL(10, 4)
);

CREATE INDEX IF NOT EXISTS idx_backtest_equity_curve_run_id ON backtest_equity_curve(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_curve_timestamp ON backtest_equity_curve(timestamp);

-- Comments
COMMENT ON TABLE backtest_runs IS 'Backtest run metadata and results';
COMMENT ON TABLE backtest_trades IS 'Individual trades from backtest runs';
COMMENT ON TABLE backtest_equity_curve IS 'Equity curve data points for backtest runs';





