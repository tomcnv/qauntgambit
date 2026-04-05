-- Create trading_activity table to store all trading decisions and actions
CREATE TABLE IF NOT EXISTS trading_activity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    type VARCHAR(50) NOT NULL, -- 'decision', 'order_created', 'order_filled', 'position_opened', 'position_closed', 'trade_blocked', etc.
    token VARCHAR(20),
    action VARCHAR(20), -- 'buy', 'sell', 'hold'
    
    -- Decision data
    confidence DECIMAL(5, 2),
    reasoning TEXT,
    expected_outcome TEXT,
    
    -- Order/Position data
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    position_id UUID REFERENCES positions(id) ON DELETE SET NULL,
    quantity NUMERIC(18, 8),
    price NUMERIC(18, 8),
    
    -- Market data at time of decision
    market_data JSONB,
    
    -- Additional metadata
    metadata JSONB,
    
    -- Status/Result
    status VARCHAR(50), -- 'pending', 'executed', 'blocked', 'failed', 'completed'
    result_message TEXT
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_trading_activity_user_id ON trading_activity(user_id);
CREATE INDEX IF NOT EXISTS idx_trading_activity_timestamp ON trading_activity(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trading_activity_type ON trading_activity(type);
CREATE INDEX IF NOT EXISTS idx_trading_activity_token ON trading_activity(token);
CREATE INDEX IF NOT EXISTS idx_trading_activity_user_timestamp ON trading_activity(user_id, timestamp DESC);

-- Comment
COMMENT ON TABLE trading_activity IS 'Stores all trading decisions, orders, and activity for audit trail and analysis';

