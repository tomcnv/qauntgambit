CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Backward-compatible aliases for legacy backtest tables used by quantgambit API
ALTER TABLE public.backtest_runs
  ADD COLUMN IF NOT EXISTS name text,
  ADD COLUMN IF NOT EXISTS execution_diagnostics jsonb,
  ADD COLUMN IF NOT EXISTS tenant_id text,
  ADD COLUMN IF NOT EXISTS bot_id text,
  ADD COLUMN IF NOT EXISTS config jsonb,
  ADD COLUMN IF NOT EXISTS run_id uuid GENERATED ALWAYS AS (id) STORED;

UPDATE public.backtest_runs
SET tenant_id = COALESCE(tenant_id, user_id::text)
WHERE tenant_id IS NULL;

UPDATE public.backtest_runs
SET config = COALESCE(config, '{}'::jsonb)
WHERE config IS NULL;

CREATE INDEX IF NOT EXISTS backtest_runs_tenant_bot_idx ON public.backtest_runs (tenant_id, bot_id);
CREATE INDEX IF NOT EXISTS backtest_runs_tenant_status_idx ON public.backtest_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS backtest_runs_symbol_idx ON public.backtest_runs (symbol);

ALTER TABLE public.backtest_trades
  ADD COLUMN IF NOT EXISTS run_id uuid GENERATED ALWAYS AS (backtest_run_id) STORED,
  ADD COLUMN IF NOT EXISTS ts timestamptz GENERATED ALWAYS AS (entry_time) STORED,
  ADD COLUMN IF NOT EXISTS entry_fee numeric,
  ADD COLUMN IF NOT EXISTS exit_fee numeric,
  ADD COLUMN IF NOT EXISTS reason text,
  ADD COLUMN IF NOT EXISTS strategy_id text,
  ADD COLUMN IF NOT EXISTS profile_id text,
  ADD COLUMN IF NOT EXISTS entry_slippage_bps numeric,
  ADD COLUMN IF NOT EXISTS exit_slippage_bps numeric,
  ADD COLUMN IF NOT EXISTS total_fees numeric;

UPDATE public.backtest_trades
SET entry_fee = COALESCE(entry_fee, 0),
    exit_fee = COALESCE(exit_fee, 0),
    entry_slippage_bps = COALESCE(entry_slippage_bps, slippage),
    exit_slippage_bps = COALESCE(exit_slippage_bps, 0),
    total_fees = COALESCE(total_fees, commission)
WHERE true;

CREATE INDEX IF NOT EXISTS backtest_trades_run_id_idx ON public.backtest_trades (run_id);
CREATE INDEX IF NOT EXISTS backtest_trades_ts_idx ON public.backtest_trades (ts DESC);

ALTER TABLE public.backtest_equity_curve
  ADD COLUMN IF NOT EXISTS run_id uuid GENERATED ALWAYS AS (backtest_run_id) STORED,
  ADD COLUMN IF NOT EXISTS ts timestamptz GENERATED ALWAYS AS ("timestamp") STORED,
  ADD COLUMN IF NOT EXISTS realized_pnl numeric,
  ADD COLUMN IF NOT EXISTS open_positions integer;

CREATE INDEX IF NOT EXISTS backtest_equity_curve_run_id_idx ON public.backtest_equity_curve (run_id);
CREATE INDEX IF NOT EXISTS backtest_equity_curve_ts_idx ON public.backtest_equity_curve (ts DESC);

CREATE TABLE IF NOT EXISTS public.backtest_metrics (
    run_id uuid PRIMARY KEY,
    realized_pnl double precision NOT NULL,
    total_fees double precision NOT NULL,
    total_trades integer NOT NULL,
    win_rate double precision NOT NULL,
    max_drawdown_pct double precision NOT NULL,
    avg_slippage_bps double precision NOT NULL,
    total_return_pct double precision NOT NULL,
    profit_factor double precision NOT NULL,
    avg_trade_pnl double precision NOT NULL,
    sharpe_ratio double precision,
    sortino_ratio double precision,
    trades_per_day double precision,
    fee_drag_pct double precision,
    slippage_drag_pct double precision,
    gross_profit double precision,
    gross_loss double precision,
    avg_win double precision,
    avg_loss double precision,
    largest_win double precision,
    largest_loss double precision,
    winning_trades integer,
    losing_trades integer,
    CONSTRAINT backtest_metrics_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS backtest_metrics_run_id_idx ON public.backtest_metrics (run_id);

CREATE TABLE IF NOT EXISTS public.backtest_symbol_equity_curve (
    run_id uuid NOT NULL,
    symbol text NOT NULL,
    ts timestamptz NOT NULL,
    equity double precision NOT NULL,
    realized_pnl double precision NOT NULL,
    open_positions integer NOT NULL,
    CONSTRAINT backtest_symbol_equity_curve_pkey PRIMARY KEY (run_id, symbol, ts),
    CONSTRAINT backtest_symbol_equity_curve_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS backtest_symbol_equity_curve_run_id_symbol_idx ON public.backtest_symbol_equity_curve (run_id, symbol, ts DESC);

CREATE TABLE IF NOT EXISTS public.backtest_symbol_metrics (
    run_id uuid NOT NULL,
    symbol text NOT NULL,
    realized_pnl double precision NOT NULL,
    total_fees double precision NOT NULL,
    total_trades integer NOT NULL,
    win_rate double precision NOT NULL,
    avg_trade_pnl double precision NOT NULL,
    profit_factor double precision NOT NULL,
    avg_slippage_bps double precision,
    sharpe_ratio double precision,
    sortino_ratio double precision,
    trades_per_day double precision,
    PRIMARY KEY (run_id, symbol),
    CONSTRAINT backtest_symbol_metrics_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS backtest_symbol_metrics_run_id_symbol_idx ON public.backtest_symbol_metrics (run_id, symbol);

CREATE TABLE IF NOT EXISTS public.backtest_decision_snapshots (
    run_id uuid NOT NULL,
    ts timestamptz NOT NULL,
    symbol text NOT NULL,
    decision text NOT NULL,
    rejection_reason text,
    profile_id text,
    payload jsonb NOT NULL,
    CONSTRAINT backtest_decision_snapshots_pkey PRIMARY KEY (run_id, symbol, ts),
    CONSTRAINT backtest_decision_snapshots_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS backtest_decision_snapshots_run_id_ts_idx ON public.backtest_decision_snapshots (run_id, ts DESC);

CREATE TABLE IF NOT EXISTS public.backtest_position_snapshots (
    run_id uuid NOT NULL,
    ts timestamptz NOT NULL,
    payload jsonb NOT NULL,
    CONSTRAINT backtest_position_snapshots_pkey PRIMARY KEY (run_id, ts),
    CONSTRAINT backtest_position_snapshots_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS backtest_position_snapshots_run_id_ts_idx ON public.backtest_position_snapshots (run_id, ts DESC);

CREATE TABLE IF NOT EXISTS public.wfo_runs (
    run_id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    profile_id text,
    symbol text,
    status text NOT NULL,
    config jsonb,
    results jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_status_idx ON public.wfo_runs (tenant_id, status);
CREATE INDEX IF NOT EXISTS wfo_runs_tenant_idx ON public.wfo_runs (tenant_id);
