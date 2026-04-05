-- Migration: Trade Cost Analysis (TCA) and Capacity Analysis
-- Date: 2025-01-XX
-- Description: Create tables for transaction cost analysis and capacity curves

-- Ensure UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Trade costs: Store per-trade cost breakdown
CREATE TABLE IF NOT EXISTS trade_costs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    profile_id TEXT,
    execution_price NUMERIC NOT NULL,
    decision_mid_price NUMERIC NOT NULL,
    slippage_bps NUMERIC NOT NULL,
    fees NUMERIC NOT NULL DEFAULT 0,
    funding_cost NUMERIC NOT NULL DEFAULT 0,
    total_cost NUMERIC NOT NULL,
    entry_fee_usd NUMERIC,
    exit_fee_usd NUMERIC,
    entry_fee_bps NUMERIC,
    exit_fee_bps NUMERIC,
    entry_slippage_bps NUMERIC,
    exit_slippage_bps NUMERIC,
    spread_cost_bps NUMERIC,
    adverse_selection_bps NUMERIC,
    total_cost_bps NUMERIC,
    order_size NUMERIC,
    side TEXT CHECK (side IN ('long', 'short')),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_costs_trade_id ON trade_costs(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_costs_symbol ON trade_costs(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_costs_profile_id ON trade_costs(profile_id);
CREATE INDEX IF NOT EXISTS idx_trade_costs_timestamp ON trade_costs(timestamp);

-- Capacity analysis: Store capacity curves per profile
CREATE TABLE IF NOT EXISTS capacity_analysis (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id TEXT NOT NULL,
    notional_bucket NUMERIC NOT NULL,
    avg_pnl NUMERIC,
    avg_sharpe NUMERIC,
    avg_slippage_bps NUMERIC,
    avg_fees_pct NUMERIC,
    trade_count INTEGER NOT NULL DEFAULT 0,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (profile_id, notional_bucket, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_capacity_analysis_profile ON capacity_analysis(profile_id);
CREATE INDEX IF NOT EXISTS idx_capacity_analysis_period ON capacity_analysis(period_start, period_end);

-- Cost aggregation: Pre-aggregated costs for fast queries
CREATE TABLE IF NOT EXISTS cost_aggregation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT,
    profile_id TEXT,
    period_type TEXT NOT NULL CHECK (period_type IN ('daily', 'weekly', 'monthly')),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    total_volume NUMERIC NOT NULL DEFAULT 0,
    total_slippage_bps NUMERIC NOT NULL DEFAULT 0,
    total_fees NUMERIC NOT NULL DEFAULT 0,
    total_funding_cost NUMERIC NOT NULL DEFAULT 0,
    total_cost NUMERIC NOT NULL DEFAULT 0,
    gross_pnl NUMERIC,
    net_pnl NUMERIC,
    cost_drag_pct NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, profile_id, period_type, period_start)
);

CREATE INDEX IF NOT EXISTS idx_cost_aggregation_symbol ON cost_aggregation(symbol);
CREATE INDEX IF NOT EXISTS idx_cost_aggregation_profile ON cost_aggregation(profile_id);
CREATE INDEX IF NOT EXISTS idx_cost_aggregation_period ON cost_aggregation(period_type, period_start);

COMMENT ON TABLE trade_costs IS 'Per-trade cost breakdown (slippage, fees, funding)';
COMMENT ON TABLE capacity_analysis IS 'Capacity curves showing performance vs notional size';
COMMENT ON TABLE cost_aggregation IS 'Pre-aggregated cost metrics for fast queries';





