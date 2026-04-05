-- Migration: Create equity_curves table for historical equity tracking
-- Date: 2025-01-29
-- Description: Store equity curve points for performance analysis and visualization

-- Ensure UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Equity curves: Track account equity over time
CREATE TABLE IF NOT EXISTS equity_curves (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL, -- Can be profile_id or portfolio UUID
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    equity NUMERIC(18, 8) NOT NULL, -- Account equity at this point
    pnl NUMERIC(18, 8) NOT NULL, -- Cumulative PnL
    pnl_percent NUMERIC(10, 4) NOT NULL, -- PnL as percentage of starting balance
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Unique constraint: one point per user/portfolio/hour
    CONSTRAINT equity_curves_user_portfolio_timestamp_unique UNIQUE (user_id, portfolio_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_equity_curves_user_id ON equity_curves(user_id);
CREATE INDEX IF NOT EXISTS idx_equity_curves_portfolio_id ON equity_curves(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_equity_curves_timestamp ON equity_curves(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_equity_curves_user_portfolio_timestamp ON equity_curves(user_id, portfolio_id, timestamp DESC);




