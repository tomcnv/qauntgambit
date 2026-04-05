-- Migration: Create orders and related tables
-- Created: 2025-11-17

-- Orders table for advanced order management
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('market', 'limit', 'stop_loss', 'stop_limit', 'trailing_stop', 'take_profit', 'bracket', 'oco')),
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(18,8) NOT NULL CHECK (quantity > 0),
    price NUMERIC(18,8) NULL, -- NULL for market orders
    stop_price NUMERIC(18,8) NULL, -- For stop orders
    trailing_percent NUMERIC(5,2) NULL, -- For trailing stops
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'filled', 'cancelled', 'expired', 'rejected')),
    filled_quantity NUMERIC(18,8) DEFAULT 0 CHECK (filled_quantity >= 0),
    avg_fill_price NUMERIC(18,8) NULL,
    time_in_force VARCHAR(10) DEFAULT 'GTC' CHECK (time_in_force IN ('GTC', 'IOC', 'FOK', 'GTD')),
    post_only BOOLEAN DEFAULT FALSE,
    reduce_only BOOLEAN DEFAULT FALSE,
    linked_orders JSONB NULL, -- For bracket/OCO orders
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP WITH TIME ZONE NULL,
    expires_at TIMESTAMP WITH TIME ZONE NULL, -- For GTD orders
    exchange VARCHAR(20) DEFAULT 'binance',
    exchange_order_id VARCHAR(100) NULL,
    error_message TEXT NULL,
    metadata JSONB NULL -- Additional exchange-specific data
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_orders_user_status ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_portfolio_id ON orders(portfolio_id);

-- Trades table (enhanced for order tracking)
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(18,8) NOT NULL,
    price NUMERIC(18,8) NOT NULL,
    fees NUMERIC(18,8) NOT NULL DEFAULT 0,
    pnl NUMERIC(18,8) DEFAULT 0,
    pnl_percent NUMERIC(5,2) DEFAULT 0,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    exchange VARCHAR(20) DEFAULT 'binance',
    exchange_trade_id VARCHAR(100) NULL
);

-- Equity curves table for performance tracking
CREATE TABLE IF NOT EXISTS equity_curves (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    equity NUMERIC(18,8) NOT NULL,
    pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
    pnl_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
    UNIQUE(portfolio_id, timestamp)
);

-- Alerts table for notifications
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id UUID NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL, -- 'price', 'order', 'risk', 'whale', etc.
    symbol VARCHAR(20) NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    severity VARCHAR(20) DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    is_read BOOLEAN DEFAULT FALSE,
    metadata JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_trades_user_symbol ON trades(user_id, symbol);
CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades(executed_at);
CREATE INDEX IF NOT EXISTS idx_equity_curves_portfolio_timestamp ON equity_curves(portfolio_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_user_unread ON alerts(user_id, is_read) WHERE is_read = FALSE;




