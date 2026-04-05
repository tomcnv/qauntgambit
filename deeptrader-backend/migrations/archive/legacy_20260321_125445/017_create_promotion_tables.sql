-- Migration: Change Management & Promotion Flow
-- Date: 2025-01-29
-- Description: Create tables for promotion workflow and approvals

-- Ensure UUID generation extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Promotions: Track bot/profile version promotions through environments
CREATE TABLE IF NOT EXISTS promotions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    promotion_type TEXT NOT NULL, -- 'research_to_paper', 'paper_to_live', 'rollback'
    source_environment TEXT NOT NULL, -- 'research', 'paper', 'live'
    target_environment TEXT NOT NULL, -- 'paper', 'live'
    bot_profile_id UUID, -- Reference to bot_profile
    bot_version_id UUID, -- Reference to bot_version
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'completed', 'cancelled'
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rejected_by UUID REFERENCES users(id) ON DELETE SET NULL,
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP WITH TIME ZONE,
    rejected_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,
    approval_notes TEXT,
    backtest_summary JSONB, -- Summary of backtest results
    paper_trading_stats JSONB, -- Paper trading performance stats
    config_diff JSONB, -- Differences from current active config
    risk_assessment JSONB, -- Risk assessment data
    requires_approval BOOLEAN DEFAULT true,
    auto_approved BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_promotions_status ON promotions(status);
CREATE INDEX IF NOT EXISTS idx_promotions_type ON promotions(promotion_type);
CREATE INDEX IF NOT EXISTS idx_promotions_bot_profile ON promotions(bot_profile_id);
CREATE INDEX IF NOT EXISTS idx_promotions_requested_by ON promotions(requested_by);
CREATE INDEX IF NOT EXISTS idx_promotions_requested_at ON promotions(requested_at DESC);

-- Approvals: Track approval workflow for high-risk changes
CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    promotion_id UUID REFERENCES promotions(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL, -- 'promote', 'activate', 'risk_limit_change', 'manual_trade'
    action_description TEXT NOT NULL,
    risk_level TEXT NOT NULL, -- 'low', 'medium', 'high', 'critical'
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approver_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    approval_required BOOLEAN DEFAULT true,
    requires_different_role BOOLEAN DEFAULT false, -- 4-eyes principle
    approval_notes TEXT,
    rejection_reason TEXT,
    risk_acceptance_confirmed BOOLEAN DEFAULT false,
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP WITH TIME ZONE,
    rejected_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE, -- Approval expiration
    metadata JSONB, -- Additional context
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_approvals_promotion ON approvals(promotion_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_risk_level ON approvals(risk_level);
CREATE INDEX IF NOT EXISTS idx_approvals_requested_by ON approvals(requested_by);
CREATE INDEX IF NOT EXISTS idx_approvals_requested_at ON approvals(requested_at DESC);

-- Config diffs: Store configuration differences for comparison
CREATE TABLE IF NOT EXISTS config_diffs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    promotion_id UUID REFERENCES promotions(id) ON DELETE CASCADE,
    source_config_id UUID, -- Source bot_version or config
    target_config_id UUID, -- Target bot_version or config
    diff_type TEXT NOT NULL, -- 'version_to_version', 'environment_to_environment'
    diff_summary JSONB NOT NULL, -- High-level summary of changes
    diff_details JSONB NOT NULL, -- Detailed diff (JSON patch format)
    risk_changes JSONB, -- Risk-related changes flagged
    feature_changes JSONB, -- Feature flag changes
    profile_changes JSONB, -- Profile changes
    symbol_changes JSONB, -- Symbol set changes
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_config_diffs_promotion ON config_diffs(promotion_id);
CREATE INDEX IF NOT EXISTS idx_config_diffs_source ON config_diffs(source_config_id);
CREATE INDEX IF NOT EXISTS idx_config_diffs_target ON config_diffs(target_config_id);

-- Promotion history: Audit trail of all promotions
CREATE TABLE IF NOT EXISTS promotion_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    promotion_id UUID REFERENCES promotions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL, -- 'created', 'approved', 'rejected', 'completed', 'cancelled'
    event_description TEXT,
    performed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    event_data JSONB, -- Additional event context
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_promotion_history_promotion ON promotion_history(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promotion_history_event_type ON promotion_history(event_type);
CREATE INDEX IF NOT EXISTS idx_promotion_history_created_at ON promotion_history(created_at DESC);





