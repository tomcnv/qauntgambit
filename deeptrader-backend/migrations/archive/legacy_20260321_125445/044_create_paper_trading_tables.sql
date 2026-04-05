-- Migration: Create paper trading tables for simulation mode
-- Created: 2025-12-22
-- Description: Tables for local paper trading simulation (when is_testnet=false and environment=paper)

-- Simulated orders for paper trading
CREATE TABLE IF NOT EXISTS paper_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE SET NULL,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    symbol VARCHAR(30) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('market', 'limit', 'stop_loss', 'stop_limit', 'take_profit')),
    quantity NUMERIC(18,8) NOT NULL CHECK (quantity > 0),
    price NUMERIC(18,8) NULL, -- NULL for market orders
    stop_price NUMERIC(18,8) NULL, -- For stop orders
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'open', 'filled', 'partial', 'cancelled', 'rejected')),
    filled_quantity NUMERIC(18,8) DEFAULT 0 CHECK (filled_quantity >= 0),
    avg_fill_price NUMERIC(18,8) NULL,
    time_in_force VARCHAR(10) DEFAULT 'GTC' CHECK (time_in_force IN ('GTC', 'IOC', 'FOK')),
    reduce_only BOOLEAN DEFAULT FALSE,
    simulated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP WITH TIME ZONE NULL,
    cancelled_at TIMESTAMP WITH TIME ZONE NULL,
    reject_reason TEXT NULL,
    metadata JSONB NULL -- Additional simulation data (slippage, latency, etc.)
);

-- Indexes for paper_orders
CREATE INDEX IF NOT EXISTS idx_paper_orders_user_id ON paper_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_orders_bot_instance_id ON paper_orders(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_paper_orders_exchange_account_id ON paper_orders(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_paper_orders_status ON paper_orders(status);
CREATE INDEX IF NOT EXISTS idx_paper_orders_symbol ON paper_orders(symbol);
CREATE INDEX IF NOT EXISTS idx_paper_orders_simulated_at ON paper_orders(simulated_at DESC);

-- Simulated positions for paper trading
CREATE TABLE IF NOT EXISTS paper_positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE SET NULL,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    symbol VARCHAR(30) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('long', 'short')),
    size NUMERIC(18,8) NOT NULL CHECK (size >= 0),
    entry_price NUMERIC(18,8) NOT NULL,
    current_price NUMERIC(18,8) NULL,
    leverage NUMERIC(5,2) DEFAULT 1,
    margin_used NUMERIC(18,8) DEFAULT 0,
    unrealized_pnl NUMERIC(18,8) DEFAULT 0,
    unrealized_pnl_pct NUMERIC(10,4) DEFAULT 0,
    stop_loss NUMERIC(18,8) NULL,
    take_profit NUMERIC(18,8) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'liquidated')),
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE NULL,
    close_reason VARCHAR(50) NULL, -- 'take_profit', 'stop_loss', 'manual', 'trailing_stop', 'liquidation'
    realized_pnl NUMERIC(18,8) NULL, -- Set when position is closed
    fees_paid NUMERIC(18,8) DEFAULT 0,
    metadata JSONB NULL -- Additional simulation data
);

-- Indexes for paper_positions
CREATE INDEX IF NOT EXISTS idx_paper_positions_user_id ON paper_positions(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_positions_bot_instance_id ON paper_positions(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_paper_positions_exchange_account_id ON paper_positions(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status);
CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol ON paper_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_paper_positions_open ON paper_positions(exchange_account_id, status) WHERE status = 'open';

-- Simulated account balance for paper trading
CREATE TABLE IF NOT EXISTS paper_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    currency VARCHAR(10) NOT NULL DEFAULT 'USDT',
    balance NUMERIC(18,8) NOT NULL DEFAULT 10000,
    available_balance NUMERIC(18,8) NOT NULL DEFAULT 10000,
    initial_balance NUMERIC(18,8) NOT NULL DEFAULT 10000,
    total_realized_pnl NUMERIC(18,8) DEFAULT 0,
    total_fees_paid NUMERIC(18,8) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange_account_id, currency)
);

-- Index for paper_balances
CREATE INDEX IF NOT EXISTS idx_paper_balances_exchange_account_id ON paper_balances(exchange_account_id);

-- Paper trading trades/fills (record of executed fills)
CREATE TABLE IF NOT EXISTS paper_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE SET NULL,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    paper_order_id UUID REFERENCES paper_orders(id) ON DELETE SET NULL,
    paper_position_id UUID REFERENCES paper_positions(id) ON DELETE SET NULL,
    symbol VARCHAR(30) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(18,8) NOT NULL,
    price NUMERIC(18,8) NOT NULL,
    fee NUMERIC(18,8) DEFAULT 0,
    fee_currency VARCHAR(10) DEFAULT 'USDT',
    realized_pnl NUMERIC(18,8) DEFAULT 0, -- For closing trades
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB NULL -- Slippage info, market conditions, etc.
);

-- Indexes for paper_trades
CREATE INDEX IF NOT EXISTS idx_paper_trades_user_id ON paper_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_bot_instance_id ON paper_trades(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_exchange_account_id ON paper_trades(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_paper_trades_executed_at ON paper_trades(executed_at DESC);

-- Function to automatically create paper balance when exchange account is created
CREATE OR REPLACE FUNCTION create_paper_balance_on_account_insert()
RETURNS TRIGGER AS $$
BEGIN
    -- Only create paper balance for paper environment accounts
    IF NEW.environment = 'paper' THEN
        -- Guard against duplicates without relying on a specific UNIQUE constraint.
        INSERT INTO paper_balances (exchange_account_id, currency, balance, available_balance, initial_balance)
        SELECT NEW.id, 'USDT', 10000, 10000, 10000
        WHERE NOT EXISTS (
          SELECT 1 FROM paper_balances pb
          WHERE pb.exchange_account_id = NEW.id AND pb.currency = 'USDT'
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to create paper balance
DROP TRIGGER IF EXISTS trigger_create_paper_balance ON exchange_accounts;
CREATE TRIGGER trigger_create_paper_balance
    AFTER INSERT ON exchange_accounts
    FOR EACH ROW
    EXECUTE FUNCTION create_paper_balance_on_account_insert();

-- Create paper balances for existing paper environment accounts
INSERT INTO paper_balances (exchange_account_id, currency, balance, available_balance, initial_balance)
SELECT id, 'USDT', 10000, 10000, 10000
FROM exchange_accounts
WHERE environment = 'paper'
AND NOT EXISTS (
  SELECT 1 FROM paper_balances pb
  WHERE pb.exchange_account_id = exchange_accounts.id AND pb.currency = 'USDT'
);
