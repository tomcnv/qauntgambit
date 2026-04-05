-- Migration: Create tables for Incident Replay & Analysis
-- This enables "time machine" investigation of trading incidents

-- Replay snapshots: Store complete market state + decision context at decision points
CREATE TABLE IF NOT EXISTS replay_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Market data snapshot (candles, orderbook, trades)
    market_data JSONB NOT NULL,
    
    -- Decision context (signals, profiles, allocator state)
    decision_context JSONB NOT NULL,
    
    -- Position state at this moment
    position_state JSONB,
    
    -- PnL state
    pnl_state JSONB,
    
    -- Metadata
    snapshot_type VARCHAR(50) DEFAULT 'decision_point', -- 'decision_point', 'incident', 'periodic'
    incident_id UUID, -- Link to incidents table if this is an incident snapshot
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Indexes for fast time-range queries
    CONSTRAINT replay_snapshots_symbol_timestamp_idx UNIQUE (symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_replay_snapshots_symbol_timestamp ON replay_snapshots(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_replay_snapshots_incident_id ON replay_snapshots(incident_id);
CREATE INDEX IF NOT EXISTS idx_replay_snapshots_type ON replay_snapshots(snapshot_type);

-- Incidents: Track significant events that need investigation
CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_type VARCHAR(50) NOT NULL, -- 'large_loss', 'unexpected_behavior', 'data_issue', 'system_error'
    severity VARCHAR(20) NOT NULL DEFAULT 'medium', -- 'low', 'medium', 'high', 'critical'
    
    -- Time window
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Affected symbols
    affected_symbols TEXT[] NOT NULL,
    
    -- Description
    title VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Impact metrics
    pnl_impact NUMERIC(20, 8),
    positions_affected INTEGER,
    trades_affected INTEGER,
    
    -- Status
    status VARCHAR(20) DEFAULT 'open', -- 'open', 'investigating', 'resolved', 'closed'
    resolution_notes TEXT,
    
    -- Metadata
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents(incident_type);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_time_range ON incidents(start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_incidents_detected_at ON incidents(detected_at DESC);

-- Replay sessions: Track investigation sessions
CREATE TABLE IF NOT EXISTS replay_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    
    -- Session parameters
    symbol VARCHAR(50) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Session metadata
    created_by VARCHAR(255),
    session_name VARCHAR(255),
    notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_accessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_replay_sessions_incident_id ON replay_sessions(incident_id);
CREATE INDEX IF NOT EXISTS idx_replay_sessions_symbol_time ON replay_sessions(symbol, start_time, end_time);

COMMENT ON TABLE replay_snapshots IS 'Stores complete market and decision state at decision points for replay';
COMMENT ON TABLE incidents IS 'Tracks significant events requiring investigation';
COMMENT ON TABLE replay_sessions IS 'Tracks investigation sessions for incident analysis';





