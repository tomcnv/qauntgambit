-- Migration: Create tables for Data Quality & Feed Monitoring
-- This enables monitoring of data feed health and quality metrics

-- Data quality metrics: Store quality metrics per symbol/timeframe
CREATE TABLE IF NOT EXISTS data_quality_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(20) NOT NULL, -- '1m', '5m', '1h', etc.
    metric_date DATE NOT NULL,
    
    -- Quality metrics
    total_candles_expected INTEGER NOT NULL,
    total_candles_received INTEGER NOT NULL,
    missing_candles_count INTEGER DEFAULT 0,
    duplicate_candles_count INTEGER DEFAULT 0,
    
    -- Latency metrics (milliseconds)
    avg_ingest_latency_ms NUMERIC(10, 2), -- Time from exchange timestamp to our ingest
    max_ingest_latency_ms NUMERIC(10, 2),
    min_ingest_latency_ms NUMERIC(10, 2),
    
    -- Data integrity metrics
    outlier_count INTEGER DEFAULT 0, -- Price jumps > threshold
    gap_count INTEGER DEFAULT 0, -- Time gaps in data
    invalid_price_count INTEGER DEFAULT 0, -- Negative or zero prices
    
    -- Timestamp accuracy
    timestamp_drift_seconds NUMERIC(10, 2), -- Average drift from expected timestamps
    
    -- Quality score (0-100)
    quality_score NUMERIC(5, 2) DEFAULT 100.0,
    
    -- Status
    status VARCHAR(20) DEFAULT 'healthy', -- 'healthy', 'degraded', 'critical'
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Unique constraint
    CONSTRAINT data_quality_metrics_symbol_timeframe_date_idx UNIQUE (symbol, timeframe, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_data_quality_symbol_date ON data_quality_metrics(symbol, metric_date DESC);
CREATE INDEX IF NOT EXISTS idx_data_quality_status ON data_quality_metrics(status);
CREATE INDEX IF NOT EXISTS idx_data_quality_score ON data_quality_metrics(quality_score);

-- Feed gaps: Track specific gaps in data feeds
CREATE TABLE IF NOT EXISTS feed_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(20) NOT NULL,
    
    -- Gap details
    gap_start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    gap_end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    gap_duration_seconds INTEGER NOT NULL,
    
    -- Expected vs actual
    expected_candles_count INTEGER,
    missing_candles_count INTEGER,
    
    -- Detection
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE, -- When gap was backfilled or resolved
    resolution_method VARCHAR(50), -- 'backfilled', 'ignored', 'manual_fix'
    
    -- Severity
    severity VARCHAR(20) DEFAULT 'medium', -- 'low', 'medium', 'high', 'critical'
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feed_gaps_symbol ON feed_gaps(symbol);
CREATE INDEX IF NOT EXISTS idx_feed_gaps_timeframe ON feed_gaps(timeframe);
CREATE INDEX IF NOT EXISTS idx_feed_gaps_time_range ON feed_gaps(gap_start_time, gap_end_time);
CREATE INDEX IF NOT EXISTS idx_feed_gaps_severity ON feed_gaps(severity);
CREATE INDEX IF NOT EXISTS idx_feed_gaps_resolved ON feed_gaps(resolved_at);

-- Data quality alerts: Track when quality thresholds are breached
CREATE TABLE IF NOT EXISTS data_quality_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(50) NOT NULL,
    alert_type VARCHAR(50) NOT NULL, -- 'missing_data', 'high_latency', 'outlier', 'gap', 'low_quality_score'
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    
    -- Alert details
    threshold_value NUMERIC(20, 8),
    actual_value NUMERIC(20, 8),
    threshold_type VARCHAR(50), -- 'missing_candles_pct', 'latency_ms', 'quality_score', etc.
    
    -- Time window
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    
    -- Status
    status VARCHAR(20) DEFAULT 'open', -- 'open', 'acknowledged', 'resolved', 'closed'
    
    -- Metadata
    description TEXT,
    resolution_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_symbol ON data_quality_alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_type ON data_quality_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_severity ON data_quality_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_status ON data_quality_alerts(status);
CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_detected ON data_quality_alerts(detected_at DESC);

-- Symbol data health: Current health status per symbol
CREATE TABLE IF NOT EXISTS symbol_data_health (
    symbol VARCHAR(50) PRIMARY KEY,
    timeframe VARCHAR(20) NOT NULL DEFAULT '1m',
    
    -- Current status
    health_status VARCHAR(20) DEFAULT 'healthy', -- 'healthy', 'degraded', 'critical', 'unknown'
    quality_score NUMERIC(5, 2) DEFAULT 100.0,
    
    -- Last metrics
    last_metric_time TIMESTAMP WITH TIME ZONE,
    last_candle_time TIMESTAMP WITH TIME ZONE,
    last_update_time TIMESTAMP WITH TIME ZONE,
    
    -- Current issues
    active_gaps_count INTEGER DEFAULT 0,
    active_alerts_count INTEGER DEFAULT 0,
    avg_latency_ms NUMERIC(10, 2),
    
    -- Metadata
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_symbol_data_health_status ON symbol_data_health(health_status);
CREATE INDEX IF NOT EXISTS idx_symbol_data_health_score ON symbol_data_health(quality_score);

COMMENT ON TABLE data_quality_metrics IS 'Daily quality metrics per symbol/timeframe';
COMMENT ON TABLE feed_gaps IS 'Tracks gaps in data feeds';
COMMENT ON TABLE data_quality_alerts IS 'Alerts when data quality thresholds are breached';
COMMENT ON TABLE symbol_data_health IS 'Current health status per symbol';





