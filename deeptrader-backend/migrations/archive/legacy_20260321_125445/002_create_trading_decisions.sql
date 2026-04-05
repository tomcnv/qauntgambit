-- Migration: Create trading decisions table
-- Created: 2025-11-17

-- Trading decisions table for AI bot decision persistence
CREATE TABLE IF NOT EXISTS trading_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    token VARCHAR(20) NOT NULL,
    decision JSONB NOT NULL, -- Full decision object from AI
    market_data JSONB NOT NULL, -- Market data used for decision
    multi_timeframe JSONB, -- Multi-timeframe analysis data
    confidence DECIMAL(5,4), -- AI confidence score 0-1
    action VARCHAR(10) NOT NULL CHECK (action IN ('buy', 'sell', 'hold')),
    executed BOOLEAN DEFAULT FALSE, -- Whether this decision led to a trade
    order_id UUID REFERENCES orders(id), -- Link to executed order if any
    reasoning TEXT, -- AI reasoning explanation
    factors JSONB, -- Detailed factor analysis
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trading_decisions_user_token ON trading_decisions(user_id, token);
CREATE INDEX IF NOT EXISTS idx_trading_decisions_created_at ON trading_decisions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_decisions_action ON trading_decisions(action);
CREATE INDEX IF NOT EXISTS idx_trading_decisions_executed ON trading_decisions(executed);
CREATE INDEX IF NOT EXISTS idx_trading_decisions_portfolio_id ON trading_decisions(portfolio_id);

-- Add confidence score for better querying
CREATE INDEX IF NOT EXISTS idx_trading_decisions_confidence ON trading_decisions(confidence) WHERE confidence >= 0.5;




