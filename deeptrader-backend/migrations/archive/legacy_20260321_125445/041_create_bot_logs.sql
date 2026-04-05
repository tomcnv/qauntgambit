-- Migration: 041_create_bot_logs.sql
-- Bot Logs: Event/error logging for bot instances
-- Allows users to see what's happening with their bots, especially errors

-- Create log level enum
DO $$ BEGIN
    CREATE TYPE bot_log_level AS ENUM ('debug', 'info', 'warn', 'error', 'fatal');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create log category enum
DO $$ BEGIN
    CREATE TYPE bot_log_category AS ENUM (
        'lifecycle',      -- Start, stop, pause, resume
        'trade',          -- Trade execution, orders
        'signal',         -- Trading signals generated
        'risk',           -- Risk limit events
        'connection',     -- Exchange connection issues
        'config',         -- Configuration changes
        'system'          -- System-level events
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS bot_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Core relationships
    bot_instance_id UUID NOT NULL REFERENCES bot_instances(id) ON DELETE CASCADE,
    bot_exchange_config_id UUID REFERENCES bot_exchange_configs(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Log content
    level bot_log_level NOT NULL DEFAULT 'info',
    category bot_log_category NOT NULL DEFAULT 'system',
    message TEXT NOT NULL,
    
    -- Structured details (stack trace, context, etc.)
    details JSONB DEFAULT '{}'::jsonb,
    
    -- Error-specific fields
    error_code VARCHAR(64),           -- e.g., "INSUFFICIENT_BALANCE", "API_TIMEOUT"
    error_type VARCHAR(128),          -- e.g., "ExchangeAPIError", "RiskLimitExceeded"
    stack_trace TEXT,                 -- Full stack trace for debugging
    
    -- Context
    symbol VARCHAR(32),               -- If related to a specific symbol
    order_id VARCHAR(128),            -- If related to a specific order
    position_id UUID,                 -- If related to a specific position
    
    -- Source info
    source VARCHAR(128),              -- Component that generated the log (e.g., "OrderExecutor", "RiskManager")
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Expiration (for auto-cleanup of old logs)
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days')
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_bot_logs_bot_instance ON bot_logs(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_bot_logs_user ON bot_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_bot_logs_level ON bot_logs(level);
CREATE INDEX IF NOT EXISTS idx_bot_logs_category ON bot_logs(category);
CREATE INDEX IF NOT EXISTS idx_bot_logs_created_at ON bot_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_logs_bot_created ON bot_logs(bot_instance_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_logs_errors ON bot_logs(bot_instance_id, level) WHERE level IN ('error', 'fatal');
CREATE INDEX IF NOT EXISTS idx_bot_logs_expires ON bot_logs(expires_at);

-- Composite index for common query pattern: recent errors for a bot
CREATE INDEX IF NOT EXISTS idx_bot_logs_recent_errors 
ON bot_logs(bot_instance_id, created_at DESC) 
WHERE level IN ('error', 'fatal');

-- Add last_error_at to bot_exchange_configs for quick access
ALTER TABLE bot_exchange_configs 
ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ;

-- Add error_count for quick display
ALTER TABLE bot_exchange_configs 
ADD COLUMN IF NOT EXISTS error_count INTEGER DEFAULT 0;

COMMENT ON TABLE bot_logs IS 'Event and error logs for bot instances - allows users to see what happened';
COMMENT ON COLUMN bot_logs.level IS 'Log severity: debug, info, warn, error, fatal';
COMMENT ON COLUMN bot_logs.category IS 'Log category for filtering: lifecycle, trade, signal, risk, connection, config, system';
COMMENT ON COLUMN bot_logs.details IS 'Structured JSON data with additional context';
COMMENT ON COLUMN bot_logs.error_code IS 'Machine-readable error code for programmatic handling';
COMMENT ON COLUMN bot_logs.expires_at IS 'Auto-cleanup: logs expire after 30 days by default';










