-- Migration: 029_create_bot_symbol_configs.sql
-- Per-Symbol Overrides: Granular control for each symbol within a bot-exchange config

CREATE TABLE IF NOT EXISTS bot_symbol_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Parent relationship
    bot_exchange_config_id UUID NOT NULL REFERENCES bot_exchange_configs(id) ON DELETE CASCADE,
    
    -- Symbol identification
    symbol VARCHAR(64) NOT NULL, -- e.g., BTC-USDT-SWAP
    
    -- Enable/disable for this symbol
    enabled BOOLEAN DEFAULT true,
    
    -- Position sizing overrides
    max_exposure_pct DECIMAL(10,4), -- Max exposure for this symbol (% of capital)
    max_position_size_usd DECIMAL(20,2), -- Absolute max position size
    max_positions INTEGER DEFAULT 1, -- Max concurrent positions for this symbol
    
    -- Leverage override
    max_leverage DECIMAL(5,2), -- Symbol-specific max leverage
    
    -- Risk overrides
    symbol_risk_config JSONB DEFAULT '{}'::jsonb,
    -- Example: {"stopLossPct": 1.5, "takeProfitPct": 3.0}
    
    -- Profile/strategy overrides for this symbol
    symbol_profile_overrides JSONB DEFAULT '{}'::jsonb,
    -- Example: {"profiles": ["momentum_breakout"], "indicators": {...}}
    
    -- Execution preferences
    preferred_order_type VARCHAR(32), -- market, limit, etc.
    max_slippage_bps INTEGER, -- Max acceptable slippage in basis points
    
    -- Metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- One config per symbol per bot-exchange attachment
    UNIQUE(bot_exchange_config_id, symbol)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bot_symbol_configs_parent ON bot_symbol_configs(bot_exchange_config_id);
CREATE INDEX IF NOT EXISTS idx_bot_symbol_configs_symbol ON bot_symbol_configs(symbol);
CREATE INDEX IF NOT EXISTS idx_bot_symbol_configs_enabled ON bot_symbol_configs(bot_exchange_config_id, enabled) WHERE enabled = true;

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_bot_symbol_configs_updated_at ON bot_symbol_configs;
CREATE TRIGGER update_bot_symbol_configs_updated_at
    BEFORE UPDATE ON bot_symbol_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE bot_symbol_configs IS 'Per-symbol overrides within a bot-exchange configuration';
COMMENT ON COLUMN bot_symbol_configs.max_exposure_pct IS 'Maximum exposure for this symbol as percentage of trading capital';
COMMENT ON COLUMN bot_symbol_configs.symbol_risk_config IS 'Risk parameter overrides specific to this symbol';
COMMENT ON COLUMN bot_symbol_configs.symbol_profile_overrides IS 'Strategy/profile overrides for this symbol';


