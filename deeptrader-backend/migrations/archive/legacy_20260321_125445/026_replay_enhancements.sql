-- Migration: Replay Studio Enhancements for Forensic-Grade Analysis
-- Created: 2025-12-21

-- Feature dictionary for UI explanations
CREATE TABLE IF NOT EXISTS feature_dictionary (
    feature_name VARCHAR(100) PRIMARY KEY,
    display_name VARCHAR(200),
    description TEXT,
    category VARCHAR(50),
    unit VARCHAR(20),
    typical_range JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed common features
INSERT INTO feature_dictionary (feature_name, display_name, description, category, unit) VALUES
    ('rsi_14', 'RSI (14)', 'Relative Strength Index over 14 periods', 'momentum', 'index'),
    ('macd_signal', 'MACD Signal', 'MACD signal line crossover value', 'momentum', 'ratio'),
    ('bollinger_position', 'Bollinger Position', 'Price position within Bollinger Bands (0-1)', 'volatility', 'ratio'),
    ('volume_ratio', 'Volume Ratio', 'Current volume vs average volume', 'volume', 'ratio'),
    ('spread_bps', 'Spread', 'Bid-ask spread in basis points', 'microstructure', 'bps'),
    ('depth_imbalance', 'Depth Imbalance', 'Order book imbalance (-1 to 1)', 'microstructure', 'ratio'),
    ('volatility_1h', 'Volatility (1h)', 'Realized volatility over 1 hour', 'volatility', 'percent'),
    ('momentum_5m', 'Momentum (5m)', 'Price momentum over 5 minutes', 'momentum', 'percent'),
    ('trend_strength', 'Trend Strength', 'ADX-based trend strength (0-1)', 'trend', 'ratio'),
    ('mean_reversion_score', 'Mean Reversion Score', 'Mean reversion signal strength (0-1)', 'signal', 'ratio')
ON CONFLICT (feature_name) DO NOTHING;

-- Timeline annotations for replay sessions
CREATE TABLE IF NOT EXISTS replay_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES replay_sessions(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    annotation_type VARCHAR(50) NOT NULL DEFAULT 'note',
    title VARCHAR(200),
    content TEXT,
    tags TEXT[],
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_replay_annotations_session ON replay_annotations(session_id);
CREATE INDEX IF NOT EXISTS idx_replay_annotations_timestamp ON replay_annotations(timestamp);

-- Expand decision_traces table for gate details and execution metrics
ALTER TABLE decision_traces ADD COLUMN IF NOT EXISTS gate_results JSONB;
ALTER TABLE decision_traces ADD COLUMN IF NOT EXISTS execution_metrics JSONB;
ALTER TABLE decision_traces ADD COLUMN IF NOT EXISTS feature_contributions JSONB;
ALTER TABLE decision_traces ADD COLUMN IF NOT EXISTS config_version INTEGER;
ALTER TABLE decision_traces ADD COLUMN IF NOT EXISTS bot_id UUID;
ALTER TABLE decision_traces ADD COLUMN IF NOT EXISTS exchange_account_id UUID;

-- Add integrity tracking to replay_sessions
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS integrity_score NUMERIC(5,2);
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS data_gaps INTEGER DEFAULT 0;
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS snapshot_coverage NUMERIC(5,2);
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS dataset_hash VARCHAR(64);
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS config_version INTEGER;
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS bot_id UUID;
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS exchange_account_id UUID;
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS outcome_summary JSONB;

-- Expand replay_snapshots with more context
ALTER TABLE replay_snapshots ADD COLUMN IF NOT EXISTS gate_states JSONB;
ALTER TABLE replay_snapshots ADD COLUMN IF NOT EXISTS regime_label VARCHAR(50);
ALTER TABLE replay_snapshots ADD COLUMN IF NOT EXISTS anomaly_flags JSONB;
ALTER TABLE replay_snapshots ADD COLUMN IF NOT EXISTS latency_ms INTEGER;
ALTER TABLE replay_snapshots ADD COLUMN IF NOT EXISTS data_quality_score NUMERIC(5,2);

-- Create index for efficient time-based lookups
CREATE INDEX IF NOT EXISTS idx_decision_traces_symbol_time ON decision_traces(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_decision_traces_bot ON decision_traces(bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_replay_snapshots_time ON replay_snapshots(timestamp);

-- Add comments for documentation
COMMENT ON TABLE feature_dictionary IS 'Dictionary of trading features with descriptions for UI display';
COMMENT ON TABLE replay_annotations IS 'User annotations on replay timeline for post-mortem analysis';
COMMENT ON COLUMN decision_traces.gate_results IS 'JSON object with pass/fail status for each gate (data, risk, microstructure)';
COMMENT ON COLUMN decision_traces.execution_metrics IS 'JSON with expected_price, submitted_price, fill_price, slippage_bps, fill_time_ms';
COMMENT ON COLUMN decision_traces.feature_contributions IS 'JSON array of top contributing features with z-scores';
COMMENT ON COLUMN replay_sessions.dataset_hash IS 'SHA256 hash of dataset for reproducibility verification';








