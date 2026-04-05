-- Migration: 026_create_strategy_templates.sql
-- Strategy Templates: Describes how a bot trades (logic, profile bundle, parameters)
-- This is the "what the bot does" layer, separate from runtime configuration

CREATE TABLE IF NOT EXISTS strategy_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identity
    name VARCHAR(128) NOT NULL,
    slug VARCHAR(64) NOT NULL UNIQUE, -- URL-friendly identifier
    description TEXT,
    
    -- Strategy classification
    strategy_family VARCHAR(64) NOT NULL DEFAULT 'scalper', -- scalper, swing, arb, market_making
    timeframe VARCHAR(16) DEFAULT '1m', -- Primary timeframe
    
    -- Default profile bundle (chessboard profiles, indicators, etc.)
    default_profile_bundle JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Example: {"profiles": ["micro_range_mean_reversion", "early_trend_ignition"], "indicators": {...}}
    
    -- Default parameters (can be overridden at bot instance level)
    default_risk_config JSONB DEFAULT '{
        "positionSizePct": 0.10,
        "maxPositions": 4,
        "maxDailyLossPct": 0.05,
        "maxTotalExposurePct": 0.40,
        "maxLeverage": 1,
        "leverageMode": "isolated"
    }'::jsonb,
    
    default_execution_config JSONB DEFAULT '{
        "defaultOrderType": "market",
        "stopLossPct": 0.02,
        "takeProfitPct": 0.05,
        "trailingStopEnabled": false,
        "trailingStopPct": 0.01,
        "maxHoldTimeHours": 24
    }'::jsonb,
    
    -- Supported exchanges/symbols
    supported_exchanges TEXT[] DEFAULT ARRAY['binance', 'okx', 'bybit'],
    recommended_symbols TEXT[] DEFAULT ARRAY['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP'],
    
    -- Metadata
    version INTEGER DEFAULT 1,
    is_system BOOLEAN DEFAULT false, -- System templates vs user-created
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_strategy_templates_family ON strategy_templates(strategy_family);
CREATE INDEX IF NOT EXISTS idx_strategy_templates_active ON strategy_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_strategy_templates_slug ON strategy_templates(slug);

-- Trigger for updated_at
DROP TRIGGER IF EXISTS update_strategy_templates_updated_at ON strategy_templates;
CREATE TRIGGER update_strategy_templates_updated_at
    BEFORE UPDATE ON strategy_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed some default strategy templates
INSERT INTO strategy_templates (name, slug, description, strategy_family, default_profile_bundle, is_system)
VALUES 
    ('BTC Scalper', 'btc-scalper', 'High-frequency scalping strategy optimized for BTC perpetuals', 'scalper', 
     '{"profiles": ["micro_range_mean_reversion", "spread_compression_scalp"], "primary_symbol": "BTC-USDT-SWAP"}'::jsonb, true),
    ('Multi-Asset Momentum', 'multi-asset-momentum', 'Momentum-based strategy across multiple assets', 'swing',
     '{"profiles": ["early_trend_ignition", "momentum_breakout", "trend_continuation_pullback"]}'::jsonb, true),
    ('SOL Demo Scalper', 'sol-demo-scalper', 'Conservative scalper for testnet/demo trading on SOL', 'scalper',
     '{"profiles": ["micro_range_mean_reversion"], "primary_symbol": "SOL-USDT-SWAP"}'::jsonb, true)
ON CONFLICT (slug) DO NOTHING;

COMMENT ON TABLE strategy_templates IS 'Strategy templates define trading logic and default parameters';
COMMENT ON COLUMN strategy_templates.default_profile_bundle IS 'Chessboard profiles and indicator configurations';
COMMENT ON COLUMN strategy_templates.is_system IS 'System templates are read-only for regular users';


