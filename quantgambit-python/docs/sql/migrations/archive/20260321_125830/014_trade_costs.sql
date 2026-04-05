-- Trade cost breakdown for maker/taker attribution and rollout gating.
CREATE TABLE IF NOT EXISTS trade_costs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
    side TEXT CHECK (side IN ('long', 'short', 'buy', 'sell')),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_costs_trade_id ON trade_costs(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_costs_symbol ON trade_costs(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_costs_profile_id ON trade_costs(profile_id);
CREATE INDEX IF NOT EXISTS idx_trade_costs_timestamp ON trade_costs(timestamp DESC);

