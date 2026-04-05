-- Migration: Expand incidents table for ops console functionality
-- Adds scope, ownership, trigger details, timeline events, and affected objects

-- ============================================================
-- 1. Add scope and ownership columns to incidents
-- ============================================================
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS exchange_account_id UUID;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS bot_id UUID;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS owner_id VARCHAR(255);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS acknowledged_by VARCHAR(255);

-- ============================================================
-- 2. Add trigger details (threshold vs actual)
-- ============================================================
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS trigger_rule VARCHAR(100);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS trigger_threshold NUMERIC(20, 8);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS trigger_actual NUMERIC(20, 8);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS action_taken VARCHAR(50);

-- ============================================================
-- 3. Add additional impact metrics
-- ============================================================
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS exposure_peak NUMERIC(20, 8);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS drawdown_peak NUMERIC(20, 8);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS unrealized_pnl_impact NUMERIC(20, 8);
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS reject_count INTEGER DEFAULT 0;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS latency_p99_ms INTEGER;

-- ============================================================
-- 4. Incident timeline events table (audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS incident_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    -- Types: 'created', 'acknowledged', 'assigned', 'escalated', 'action_taken',
    --        'config_changed', 'bot_paused', 'bot_resumed', 'resolved', 'closed',
    --        'note_added', 'threshold_breached', 'recovery_started'
    actor VARCHAR(255), -- who/what triggered the event (user id, 'system', 'bot')
    event_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_events_incident_id ON incident_events(incident_id);
CREATE INDEX IF NOT EXISTS idx_incident_events_created_at ON incident_events(incident_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_events_type ON incident_events(event_type);

-- ============================================================
-- 5. Affected positions/orders (denormalized for fast queries)
-- ============================================================
CREATE TABLE IF NOT EXISTS incident_affected_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    object_type VARCHAR(20) NOT NULL, -- 'position' or 'order'
    object_id UUID NOT NULL,
    symbol VARCHAR(50),
    side VARCHAR(10),
    quantity NUMERIC(20, 8),
    entry_price NUMERIC(20, 8),
    exit_price NUMERIC(20, 8),
    pnl_impact NUMERIC(20, 8),
    fees NUMERIC(20, 8),
    reject_reason VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_affected_incident_id ON incident_affected_objects(incident_id);
CREATE INDEX IF NOT EXISTS idx_incident_affected_object_type ON incident_affected_objects(object_type);
CREATE INDEX IF NOT EXISTS idx_incident_affected_symbol ON incident_affected_objects(symbol);

-- ============================================================
-- 6. Add additional indexes for common queries
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_incidents_exchange_account ON incidents(exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_incidents_bot_id ON incidents(bot_id);
CREATE INDEX IF NOT EXISTS idx_incidents_owner ON incidents(owner_id);
CREATE INDEX IF NOT EXISTS idx_incidents_trigger_rule ON incidents(trigger_rule);
CREATE INDEX IF NOT EXISTS idx_incidents_action_taken ON incidents(action_taken);

-- ============================================================
-- 7. Update status enum to include more states
-- ============================================================
-- Note: PostgreSQL doesn't easily allow adding values to enums used in columns,
-- so we use VARCHAR. The valid statuses are:
-- 'open', 'acknowledged', 'investigating', 'mitigated', 'resolved', 'closed'

COMMENT ON TABLE incidents IS 'Risk incidents with full audit trail for ops console';
COMMENT ON TABLE incident_events IS 'Timeline events for incident audit trail';
COMMENT ON TABLE incident_affected_objects IS 'Positions and orders affected by an incident';








