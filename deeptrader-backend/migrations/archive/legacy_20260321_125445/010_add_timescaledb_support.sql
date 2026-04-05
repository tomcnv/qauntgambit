-- Migration: Add TimescaleDB support and create hypertables for time-series data
-- Date: 2025-11-19
-- Description: Enable TimescaleDB extension and create hypertables for market data

-- Enable TimescaleDB extension
DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS timescaledb;
    EXCEPTION
        WHEN OTHERS THEN
            -- On vanilla RDS Postgres, TimescaleDB isn't installed/allowed. Keep tables as plain PG tables.
            NULL;
    END;
END $$;

-- Create hypertable for market trades
CREATE TABLE IF NOT EXISTS market_trades (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    side TEXT CHECK (side IN ('buy', 'sell')),
    trade_id TEXT,
    buyer_order_id TEXT,
    seller_order_id TEXT
);

-- Convert to hypertable (partitioned by time)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('market_trades', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for market_trades
CREATE INDEX IF NOT EXISTS idx_market_trades_symbol_time ON market_trades (symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_market_trades_exchange ON market_trades (exchange);
CREATE INDEX IF NOT EXISTS idx_market_trades_trade_id ON market_trades (trade_id);

-- Create hypertable for order book snapshots
CREATE TABLE IF NOT EXISTS order_book_snapshots (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    bids JSONB,  -- Array of [price, volume] pairs
    asks JSONB,  -- Array of [price, volume] pairs
    spread DOUBLE PRECISION,
    mid_price DOUBLE PRECISION,
    bid_volume DOUBLE PRECISION,
    ask_volume DOUBLE PRECISION
);

-- Convert to hypertable
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('order_book_snapshots', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for order_book_snapshots
CREATE INDEX IF NOT EXISTS idx_order_book_symbol_time ON order_book_snapshots (symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_order_book_exchange ON order_book_snapshots (exchange);

-- Create hypertable for candles/OHLCV data
CREATE TABLE IF NOT EXISTS market_candles (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    timeframe TEXT NOT NULL,  -- '1m', '5m', '1h', etc.
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    trades_count INTEGER
);

-- Convert to hypertable
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('market_candles', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for market_candles
CREATE INDEX IF NOT EXISTS idx_candles_symbol_timeframe_time ON market_candles (symbol, timeframe, time DESC);
CREATE INDEX IF NOT EXISTS idx_candles_exchange ON market_candles (exchange);

-- Create hypertable for AMT (Auction Market Theory) metrics
CREATE TABLE IF NOT EXISTS amt_metrics (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    value_area_low DOUBLE PRECISION,
    value_area_high DOUBLE PRECISION,
    point_of_control DOUBLE PRECISION,
    total_volume DOUBLE PRECISION,
    rotation_factor DOUBLE PRECISION,
    position_in_value TEXT CHECK (position_in_value IN ('above_value', 'below_value', 'inside_value', 'at_value')),
    auction_type TEXT CHECK (auction_type IN ('balanced', 'imbalanced_up', 'imbalanced_down'))
);

-- Convert to hypertable
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('amt_metrics', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for amt_metrics
CREATE INDEX IF NOT EXISTS idx_amt_symbol_timeframe_time ON amt_metrics (symbol, timeframe, time DESC);

-- Create hypertable for microstructure features
CREATE TABLE IF NOT EXISTS microstructure_features (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    bid_ask_spread DOUBLE PRECISION,
    bid_ask_imbalance DOUBLE PRECISION,
    order_book_depth_5 DOUBLE PRECISION,  -- Total volume in top 5 levels
    order_book_depth_10 DOUBLE PRECISION, -- Total volume in top 10 levels
    trade_flow_imbalance DOUBLE PRECISION, -- Buy vs sell volume ratio
    vwap DOUBLE PRECISION,
    vwap_deviation DOUBLE PRECISION,
    realized_volatility DOUBLE PRECISION
);

-- Convert to hypertable
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('microstructure_features', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for microstructure_features
CREATE INDEX IF NOT EXISTS idx_microstructure_symbol_time ON microstructure_features (symbol, time DESC);

-- Create hypertable for strategy signals and decisions
CREATE TABLE IF NOT EXISTS strategy_signals (
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id UUID NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('entry', 'exit', 'adjust', 'hold')),
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell', 'hold')),
    confidence DOUBLE PRECISION NOT NULL,
    reasoning JSONB,
    features JSONB,  -- Feature values that led to this signal
    risk_checks JSONB,  -- Risk evaluation results
    order_intent JSONB,  -- Intended order parameters
    executed BOOLEAN DEFAULT FALSE,
    execution_time TIMESTAMPTZ,
    execution_result JSONB
);

-- Convert to hypertable
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
        PERFORM create_hypertable('strategy_signals', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Create indexes for strategy_signals
CREATE INDEX IF NOT EXISTS idx_signals_user_symbol_time ON strategy_signals (user_id, symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_strategy ON strategy_signals (strategy_id);
CREATE INDEX IF NOT EXISTS idx_signals_executed ON strategy_signals (executed);

-- Create retention policies (optional - adjust retention periods as needed)
-- SELECT add_retention_policy('market_trades', INTERVAL '90 days');
-- SELECT add_retention_policy('order_book_snapshots', INTERVAL '30 days');
-- SELECT add_retention_policy('market_candles', INTERVAL '1 year');
-- SELECT add_retention_policy('amt_metrics', INTERVAL '90 days');
-- SELECT add_retention_policy('microstructure_features', INTERVAL '90 days');
-- SELECT add_retention_policy('strategy_signals', INTERVAL '1 year');

-- Add comments for documentation
COMMENT ON TABLE market_trades IS 'Time-series table for individual market trades from exchanges';
COMMENT ON TABLE order_book_snapshots IS 'Time-series snapshots of order book state';
COMMENT ON TABLE market_candles IS 'OHLCV candle data at various timeframes';
COMMENT ON TABLE amt_metrics IS 'Auction Market Theory metrics and value areas';
COMMENT ON TABLE microstructure_features IS 'Market microstructure and order flow features';
COMMENT ON TABLE strategy_signals IS 'Trading strategy signals and execution results';
