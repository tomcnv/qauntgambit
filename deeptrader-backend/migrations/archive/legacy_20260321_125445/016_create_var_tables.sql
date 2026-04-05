-- Migration: Value at Risk (VaR) and Expected Shortfall (ES) Tables
-- Date: 2025-01-29
-- Description: Create tables for VaR/ES calculations and scenario testing

-- Ensure UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- VaR calculations: Store historical and Monte Carlo VaR/ES metrics
CREATE TABLE IF NOT EXISTS var_calculations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    calculation_type TEXT NOT NULL, -- 'historical', 'monte_carlo', 'parametric'
    confidence_level NUMERIC NOT NULL, -- 0.95, 0.99, etc.
    time_horizon_days INTEGER NOT NULL DEFAULT 1, -- 1, 5, 10, etc.
    portfolio_id TEXT,
    symbol TEXT,
    profile_id TEXT,
    var_value NUMERIC NOT NULL, -- VaR in USD
    expected_shortfall NUMERIC NOT NULL, -- ES in USD
    var_pct NUMERIC, -- VaR as % of portfolio
    es_pct NUMERIC, -- ES as % of portfolio
    sample_size INTEGER, -- Number of observations used
    calculation_date DATE NOT NULL DEFAULT CURRENT_DATE,
    calculation_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    method_params JSONB, -- Store method-specific parameters
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_var_calculations_type ON var_calculations(calculation_type);
CREATE INDEX IF NOT EXISTS idx_var_calculations_date ON var_calculations(calculation_date DESC);
CREATE INDEX IF NOT EXISTS idx_var_calculations_portfolio ON var_calculations(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_var_calculations_symbol ON var_calculations(symbol);
CREATE INDEX IF NOT EXISTS idx_var_calculations_profile ON var_calculations(profile_id);
CREATE INDEX IF NOT EXISTS idx_var_calculations_timestamp ON var_calculations(calculation_timestamp DESC);

-- Scenario results: Store stress test and scenario analysis results
CREATE TABLE IF NOT EXISTS scenario_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scenario_name TEXT NOT NULL,
    scenario_type TEXT NOT NULL, -- 'stress', 'historical', 'custom'
    description TEXT,
    portfolio_id TEXT,
    symbol TEXT,
    profile_id TEXT,
    shock_type TEXT NOT NULL, -- 'price', 'volatility', 'correlation', 'liquidity'
    shock_value NUMERIC NOT NULL, -- e.g., -0.05 for -5% price shock
    shock_units TEXT DEFAULT 'pct', -- 'pct', 'bps', 'absolute'
    base_portfolio_value NUMERIC NOT NULL,
    shocked_portfolio_value NUMERIC NOT NULL,
    pnl_impact NUMERIC NOT NULL, -- PnL change in USD
    pnl_impact_pct NUMERIC NOT NULL, -- PnL change as %
    max_drawdown_pct NUMERIC,
    affected_positions JSONB, -- Array of positions affected
    calculation_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    scenario_params JSONB, -- Additional scenario parameters
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scenario_results_type ON scenario_results(scenario_type);
CREATE INDEX IF NOT EXISTS idx_scenario_results_name ON scenario_results(scenario_name);
CREATE INDEX IF NOT EXISTS idx_scenario_results_portfolio ON scenario_results(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_scenario_results_symbol ON scenario_results(symbol);
CREATE INDEX IF NOT EXISTS idx_scenario_results_timestamp ON scenario_results(calculation_timestamp DESC);

-- Risk metrics aggregation: Pre-aggregated risk metrics for dashboard
CREATE TABLE IF NOT EXISTS risk_metrics_aggregation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    period_type TEXT NOT NULL, -- 'daily', 'weekly', 'monthly'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    portfolio_id TEXT,
    symbol TEXT,
    profile_id TEXT,
    var_95_1d NUMERIC, -- 95% VaR, 1-day
    var_99_1d NUMERIC, -- 99% VaR, 1-day
    es_95_1d NUMERIC, -- 95% ES, 1-day
    es_99_1d NUMERIC, -- 99% ES, 1-day
    var_95_5d NUMERIC, -- 95% VaR, 5-day
    var_99_5d NUMERIC, -- 99% VaR, 5-day
    max_drawdown_pct NUMERIC,
    volatility_pct NUMERIC,
    sharpe_ratio NUMERIC,
    sortino_ratio NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_type, period_start, portfolio_id, symbol, profile_id)
);

CREATE INDEX IF NOT EXISTS idx_risk_metrics_period ON risk_metrics_aggregation(period_type, period_start);
CREATE INDEX IF NOT EXISTS idx_risk_metrics_portfolio ON risk_metrics_aggregation(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_risk_metrics_symbol_profile ON risk_metrics_aggregation(symbol, profile_id);





