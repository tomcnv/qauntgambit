-- Migration: Create positions table for tracking open positions
-- Created: 2025-11-17

-- Positions table for tracking open positions
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    entry_order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('long', 'short')),
    quantity NUMERIC(18,8) NOT NULL CHECK (quantity > 0),
    entry_price NUMERIC(18,8) NOT NULL,
    current_price NUMERIC(18,8) NOT NULL,
    stop_loss NUMERIC(18,8) NULL,
    take_profit NUMERIC(18,8) NULL,
    unrealized_pnl NUMERIC(18,8) DEFAULT 0,
    unrealized_pnl_percent NUMERIC(5,2) DEFAULT 0,
    fees_paid NUMERIC(18,8) DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'liquidated')),
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE NULL,
    close_reason VARCHAR(50) NULL, -- 'take_profit', 'stop_loss', 'manual', 'trailing_stop', 'time_exit', etc.
    metadata JSONB NULL, -- Additional data like trailing stop config, partial exits, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_positions_user_status ON positions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_positions_portfolio_status ON positions(portfolio_id, status);
CREATE INDEX IF NOT EXISTS idx_positions_symbol_status ON positions(symbol, status);
CREATE INDEX IF NOT EXISTS idx_positions_opened_at ON positions(opened_at);

-- Position history table for tracking position updates (price changes, P&L updates)
CREATE TABLE IF NOT EXISTS position_updates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    position_id UUID NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    price NUMERIC(18,8) NOT NULL,
    unrealized_pnl NUMERIC(18,8) NOT NULL,
    unrealized_pnl_percent NUMERIC(5,2) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_position_updates_position_id ON position_updates(position_id);
CREATE INDEX IF NOT EXISTS idx_position_updates_timestamp ON position_updates(timestamp);

-- Update portfolios table to include positions summary (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='portfolios' AND column_name='open_positions_count') THEN
        ALTER TABLE portfolios ADD COLUMN open_positions_count INTEGER DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='portfolios' AND column_name='total_unrealized_pnl') THEN
        ALTER TABLE portfolios ADD COLUMN total_unrealized_pnl NUMERIC(18,8) DEFAULT 0;
    END IF;
END $$;

-- Function to update portfolio when position is opened
CREATE OR REPLACE FUNCTION update_portfolio_on_position_open()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE portfolios
    SET open_positions_count = open_positions_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.portfolio_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to update portfolio when position is closed
CREATE OR REPLACE FUNCTION update_portfolio_on_position_close()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status = 'open' THEN
        UPDATE portfolios
        SET open_positions_count = GREATEST(open_positions_count - 1, 0),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.portfolio_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers
DROP TRIGGER IF EXISTS trigger_position_opened ON positions;
CREATE TRIGGER trigger_position_opened
    AFTER INSERT ON positions
    FOR EACH ROW
    WHEN (NEW.status = 'open')
    EXECUTE FUNCTION update_portfolio_on_position_open();

DROP TRIGGER IF EXISTS trigger_position_closed ON positions;
CREATE TRIGGER trigger_position_closed
    AFTER UPDATE ON positions
    FOR EACH ROW
    EXECUTE FUNCTION update_portfolio_on_position_close();

