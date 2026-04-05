-- Dashboard-facing tables (control, backtesting, health, overrides)

CREATE TABLE IF NOT EXISTS command_audit (
    command_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    scope JSONB NOT NULL,
    reason TEXT,
    requested_by TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    executed_at TIMESTAMPTZ,
    result_message TEXT
);

CREATE INDEX IF NOT EXISTS command_audit_status_idx ON command_audit (status, requested_at DESC);

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

CREATE INDEX IF NOT EXISTS backtest_runs_idx ON backtest_runs (tenant_id, bot_id, started_at DESC);
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_idx ON backtest_runs (tenant_id);
CREATE INDEX IF NOT EXISTS backtest_runs_status_idx ON backtest_runs (status);
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_status_idx ON backtest_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS backtest_runs_symbol_idx ON backtest_runs (symbol);

CREATE TABLE IF NOT EXISTS backtest_metrics (
    run_id UUID PRIMARY KEY REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    realized_pnl DOUBLE PRECISION NOT NULL,
    total_fees DOUBLE PRECISION NOT NULL,
    total_trades INTEGER NOT NULL,
    win_rate DOUBLE PRECISION NOT NULL,
    max_drawdown_pct DOUBLE PRECISION NOT NULL,
    avg_slippage_bps DOUBLE PRECISION NOT NULL,
    total_return_pct DOUBLE PRECISION NOT NULL,
    profit_factor DOUBLE PRECISION NOT NULL,
    avg_trade_pnl DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION NOT NULL,
    pnl DOUBLE PRECISION NOT NULL,
    entry_fee DOUBLE PRECISION NOT NULL,
    exit_fee DOUBLE PRECISION NOT NULL,
    total_fees DOUBLE PRECISION NOT NULL,
    entry_slippage_bps DOUBLE PRECISION NOT NULL,
    exit_slippage_bps DOUBLE PRECISION NOT NULL,
    strategy_id TEXT,
    profile_id TEXT,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS backtest_trades_idx ON backtest_trades (run_id, ts DESC);

CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    run_id UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    equity DOUBLE PRECISION NOT NULL,
    realized_pnl DOUBLE PRECISION NOT NULL,
    open_positions INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS backtest_equity_curve_idx ON backtest_equity_curve (run_id, ts DESC);

CREATE TABLE IF NOT EXISTS backtest_symbol_equity_curve (
    run_id UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    equity DOUBLE PRECISION NOT NULL,
    realized_pnl DOUBLE PRECISION NOT NULL,
    open_positions INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS backtest_symbol_equity_curve_idx ON backtest_symbol_equity_curve (run_id, symbol, ts DESC);

CREATE TABLE IF NOT EXISTS backtest_symbol_metrics (
    run_id UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    realized_pnl DOUBLE PRECISION NOT NULL,
    total_fees DOUBLE PRECISION NOT NULL,
    total_trades INTEGER NOT NULL,
    win_rate DOUBLE PRECISION NOT NULL,
    avg_trade_pnl DOUBLE PRECISION NOT NULL,
    profit_factor DOUBLE PRECISION NOT NULL,
    avg_slippage_bps DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, symbol)
);

CREATE INDEX IF NOT EXISTS backtest_symbol_metrics_idx ON backtest_symbol_metrics (run_id, symbol);

CREATE TABLE IF NOT EXISTS backtest_decision_snapshots (
    run_id UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    rejection_reason TEXT,
    profile_id TEXT,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS backtest_decision_snapshots_idx ON backtest_decision_snapshots (run_id, ts DESC);

CREATE TABLE IF NOT EXISTS backtest_position_snapshots (
    run_id UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS backtest_position_snapshots_idx ON backtest_position_snapshots (run_id, ts DESC);

-- Walk-forward optimization runs
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

CREATE INDEX IF NOT EXISTS wfo_runs_tenant_idx ON wfo_runs (tenant_id);
CREATE INDEX IF NOT EXISTS wfo_runs_status_idx ON wfo_runs (status);
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_status_idx ON wfo_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS wfo_runs_profile_idx ON wfo_runs (profile_id);
CREATE INDEX IF NOT EXISTS wfo_runs_symbol_idx ON wfo_runs (symbol);

CREATE TABLE IF NOT EXISTS health_snapshots (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    exchange TEXT,
    ts TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS health_snapshots_idx ON health_snapshots (tenant_id, bot_id, ts DESC);

CREATE TABLE IF NOT EXISTS risk_override_events (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    overrides JSONB NOT NULL,
    scope JSONB,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS risk_override_events_idx ON risk_override_events (tenant_id, bot_id, ts DESC);

CREATE TABLE IF NOT EXISTS idempotency_audit (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idempotency_audit_idx ON idempotency_audit (tenant_id, bot_id, created_at DESC);

CREATE TABLE IF NOT EXISTS data_settings (
    tenant_id TEXT PRIMARY KEY,
    trade_history_retention_days INTEGER,
    replay_snapshot_retention_days INTEGER,
    backtest_history_retention_days INTEGER,
    backtest_equity_sample_every INTEGER,
    backtest_max_equity_points INTEGER,
    backtest_max_symbol_equity_points INTEGER,
    backtest_max_decision_snapshots INTEGER,
    backtest_max_position_snapshots INTEGER,
    capture_decision_traces BOOLEAN,
    capture_feature_values BOOLEAN,
    capture_orderbook BOOLEAN,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Optional hypertables if Timescale is enabled
-- SELECT create_hypertable('health_snapshots', 'ts', if_not_exists => TRUE);
-- SELECT create_hypertable('risk_override_events', 'ts', if_not_exists => TRUE);
