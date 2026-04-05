-- Migration: Enhanced Audit Logging & Decision Traces
-- Date: 2025-01-29
-- Description: Create tables for comprehensive audit logging and decision trace storage

-- Ensure UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Audit log: Comprehensive audit trail of all system actions
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action_type TEXT NOT NULL, -- 'config_change', 'trade_action', 'risk_change', 'promotion', 'manual_intervention', etc.
    action_category TEXT NOT NULL, -- 'config', 'trading', 'risk', 'promotion', 'system', 'user'
    resource_type TEXT, -- 'bot_profile', 'bot_version', 'position', 'risk_limit', 'promotion', etc.
    resource_id TEXT, -- ID of the affected resource
    action_description TEXT NOT NULL,
    action_details JSONB, -- Detailed action data
    before_state JSONB, -- State before action (for config changes)
    after_state JSONB, -- State after action (for config changes)
    ip_address INET,
    user_agent TEXT,
    severity TEXT DEFAULT 'info', -- 'info', 'warning', 'error', 'critical'
    requires_retention BOOLEAN DEFAULT true, -- Whether this log must be retained
    retention_days INTEGER, -- Days to retain (null = permanent)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action_type ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_action_category ON audit_log(action_category);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_type ON audit_log(resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_id ON audit_log(resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_severity ON audit_log(severity);

-- Decision traces: Store full decision traces for trades
CREATE TABLE IF NOT EXISTS decision_traces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    decision_type TEXT NOT NULL, -- 'entry', 'exit', 'reject', 'adjust'
    decision_outcome TEXT NOT NULL, -- 'approved', 'rejected', 'adjusted'
    signal_data JSONB, -- Original signal data
    market_context JSONB, -- Market context at decision time
    stage_results JSONB NOT NULL, -- Results from each decision stage
    rejection_reasons JSONB, -- Reasons for rejection (if rejected)
    final_decision JSONB, -- Final decision data
    execution_result JSONB, -- Execution result (if executed)
    trace_metadata JSONB, -- Additional metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decision_traces_trade_id ON decision_traces(trade_id);
CREATE INDEX IF NOT EXISTS idx_decision_traces_symbol ON decision_traces(symbol);
CREATE INDEX IF NOT EXISTS idx_decision_traces_timestamp ON decision_traces(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_decision_traces_decision_type ON decision_traces(decision_type);
CREATE INDEX IF NOT EXISTS idx_decision_traces_outcome ON decision_traces(decision_outcome);

-- Audit log exports: Track exported audit logs
CREATE TABLE IF NOT EXISTS audit_log_exports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    export_type TEXT NOT NULL, -- 'csv', 'json', 'pdf'
    date_range_start TIMESTAMP WITH TIME ZONE,
    date_range_end TIMESTAMP WITH TIME ZONE,
    filters JSONB, -- Filters applied to export
    file_path TEXT, -- Path to exported file
    file_size_bytes BIGINT,
    record_count INTEGER,
    export_status TEXT DEFAULT 'pending', -- 'pending', 'completed', 'failed'
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_audit_log_exports_user_id ON audit_log_exports(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_exports_status ON audit_log_exports(export_status);
CREATE INDEX IF NOT EXISTS idx_audit_log_exports_created_at ON audit_log_exports(created_at DESC);

-- Retention policies: Configure retention for different log types
CREATE TABLE IF NOT EXISTS retention_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    log_type TEXT NOT NULL, -- 'audit_log', 'decision_traces', 'trade_history', etc.
    action_category TEXT, -- Specific category (null = all)
    retention_days INTEGER NOT NULL, -- Days to retain
    auto_archive BOOLEAN DEFAULT false, -- Auto-archive instead of delete
    archive_location TEXT, -- Archive storage location
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(log_type, action_category)
);

CREATE INDEX IF NOT EXISTS idx_retention_policies_log_type ON retention_policies(log_type);
CREATE INDEX IF NOT EXISTS idx_retention_policies_active ON retention_policies(is_active);

-- Insert default retention policies
INSERT INTO retention_policies (log_type, action_category, retention_days, auto_archive)
VALUES
    ('audit_log', 'config', 365, true),
    ('audit_log', 'risk', 730, true),
    ('audit_log', 'promotion', 1825, true), -- 5 years
    ('audit_log', 'trading', 90, false),
    ('audit_log', 'system', 30, false),
    ('decision_traces', NULL, 90, false),
    ('trade_history', NULL, 365, true)
ON CONFLICT (log_type, action_category) DO NOTHING;





