-- Position-level scenario impacts
CREATE TABLE IF NOT EXISTS position_impacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scenario_id UUID NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT,
    size NUMERIC,
    entry_price NUMERIC,
    shocked_price NUMERIC,
    pnl NUMERIC,
    pnl_pct NUMERIC,
    factor_impacts JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_impacts_scenario ON position_impacts(scenario_id);
CREATE INDEX IF NOT EXISTS idx_position_impacts_symbol ON position_impacts(symbol);

-- Component VaR per symbol
CREATE TABLE IF NOT EXISTS component_var (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    horizon TEXT DEFAULT '1d',
    confidence NUMERIC DEFAULT 0.95,
    var_value NUMERIC,
    es_value NUMERIC,
    sample_size INTEGER,
    method TEXT DEFAULT 'proxy',
    params JSONB,
    calculated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_component_var_symbol ON component_var(symbol);
CREATE INDEX IF NOT EXISTS idx_component_var_calc ON component_var(calculated_at DESC);







