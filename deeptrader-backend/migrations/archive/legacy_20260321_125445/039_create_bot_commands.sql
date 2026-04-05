-- Migration: 039_create_bot_commands.sql
-- Queue-based bot control system
-- Commands are persisted for audit trail and reliability

-- Bot command types
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'bot_command_type') THEN
    CREATE TYPE bot_command_type AS ENUM (
      'start',
      'stop',
      'restart',
      'pause',
      'resume',
      'reload_config',
      'update_symbols',
      'emergency_stop'
    );
  END IF;
END $$;

-- Bot command status
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'bot_command_status') THEN
    CREATE TYPE bot_command_status AS ENUM (
      'pending',      -- Queued, waiting to be processed
      'processing',   -- Currently being executed
      'completed',    -- Successfully executed
      'failed',       -- Execution failed
      'cancelled',    -- Cancelled before execution
      'expired'       -- Command expired (TTL exceeded)
    );
  END IF;
END $$;

-- Bot commands table
CREATE TABLE IF NOT EXISTS bot_commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Target
    bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE CASCADE,
    exchange_config_id UUID REFERENCES bot_exchange_configs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    
    -- Command details
    command_type bot_command_type NOT NULL,
    payload JSONB DEFAULT '{}',
    priority INTEGER DEFAULT 0,  -- Higher = more urgent
    
    -- Status tracking
    status bot_command_status DEFAULT 'pending',
    status_message TEXT,
    
    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- Optional TTL
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Execution details
    executed_by TEXT,  -- Which worker/process handled it
    result JSONB,
    error_details JSONB,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- Correlation
    correlation_id TEXT,  -- For tracking related commands
    parent_command_id UUID REFERENCES bot_commands(id)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_bot_commands_status ON bot_commands(status) WHERE status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS idx_bot_commands_bot_instance ON bot_commands(bot_instance_id);
CREATE INDEX IF NOT EXISTS idx_bot_commands_user ON bot_commands(user_id);
CREATE INDEX IF NOT EXISTS idx_bot_commands_created ON bot_commands(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_commands_priority ON bot_commands(priority DESC, created_at ASC) WHERE status = 'pending';

-- Function to get next pending command (FIFO with priority)
CREATE OR REPLACE FUNCTION get_next_bot_command(p_bot_instance_id UUID DEFAULT NULL)
RETURNS bot_commands AS $$
DECLARE
    v_command bot_commands;
BEGIN
    -- Lock and fetch the next pending command
    SELECT * INTO v_command
    FROM bot_commands
    WHERE status = 'pending'
      AND (p_bot_instance_id IS NULL OR bot_instance_id = p_bot_instance_id)
      AND (expires_at IS NULL OR expires_at > NOW())
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
    
    -- Mark as processing if found
    IF v_command.id IS NOT NULL THEN
        UPDATE bot_commands
        SET status = 'processing', started_at = NOW()
        WHERE id = v_command.id;
    END IF;
    
    RETURN v_command;
END;
$$ LANGUAGE plpgsql;

-- Function to complete a command
CREATE OR REPLACE FUNCTION complete_bot_command(
    p_command_id UUID,
    p_success BOOLEAN,
    p_result JSONB DEFAULT NULL,
    p_error JSONB DEFAULT NULL,
    p_message TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE bot_commands
    SET 
        status = CASE WHEN p_success THEN 'completed'::bot_command_status ELSE 'failed'::bot_command_status END,
        completed_at = NOW(),
        result = p_result,
        error_details = p_error,
        status_message = p_message
    WHERE id = p_command_id;
END;
$$ LANGUAGE plpgsql;

-- View for command history with bot details
CREATE OR REPLACE VIEW bot_command_history AS
SELECT 
    bc.id,
    bc.command_type,
    bc.status,
    bc.status_message,
    bc.priority,
    bc.created_at,
    bc.started_at,
    bc.completed_at,
    bc.retry_count,
    bc.payload,
    bc.result,
    bc.error_details,
    bi.name as bot_name,
    bec.exchange as exchange,
    bec.environment as environment,
    u.email as user_email
FROM bot_commands bc
LEFT JOIN bot_instances bi ON bc.bot_instance_id = bi.id
LEFT JOIN bot_exchange_configs bec ON bc.exchange_config_id = bec.id
LEFT JOIN users u ON bc.user_id = u.id
ORDER BY bc.created_at DESC;

-- Comments
COMMENT ON TABLE bot_commands IS 'Queue-based bot control commands with audit trail';
COMMENT ON COLUMN bot_commands.priority IS 'Higher values = higher priority. Emergency commands should use high priority.';
COMMENT ON COLUMN bot_commands.expires_at IS 'Optional TTL - command will be marked expired if not processed by this time';
COMMENT ON COLUMN bot_commands.correlation_id IS 'For tracking related commands (e.g., restart = stop + start)';

