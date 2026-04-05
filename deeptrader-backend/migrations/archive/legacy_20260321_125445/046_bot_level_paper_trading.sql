-- Migration: Bot-Level Paper Trading
-- Created: 2025-12-22
-- Description: Move paper trading from exchange-account level to bot-instance level
--
-- This allows:
-- 1. Multiple paper bots testing different strategies on the same exchange
-- 2. Each bot has isolated paper balance/positions/orders
-- 3. Exchange accounts just provide credentials for market data
-- 4. Easy transition from paper to live per bot

-- =========================================================================
-- 1. Add trading_mode to bot_instances
-- =========================================================================

-- Add trading_mode column (separate from environment which is deployment context)
ALTER TABLE bot_instances 
ADD COLUMN IF NOT EXISTS trading_mode VARCHAR(16) DEFAULT 'paper'
CHECK (trading_mode IN ('paper', 'live'));

-- Add comment explaining the difference
COMMENT ON COLUMN bot_instances.trading_mode IS 
'Trading mode: paper=simulated locally, live=real exchange orders. Different from environment which is deployment context.';

COMMENT ON COLUMN bot_instances.environment IS 
'Deployment environment: dev/paper/live. For operational context, not trading mode.';

-- =========================================================================
-- 2. Add bot_instance_id to paper_balances
-- =========================================================================

-- Add bot_instance_id column
ALTER TABLE paper_balances 
ADD COLUMN IF NOT EXISTS bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE CASCADE;

-- Create index for bot_instance_id
CREATE INDEX IF NOT EXISTS idx_paper_balances_bot_instance_id 
ON paper_balances(bot_instance_id);

-- Drop old unique constraint (exchange_account_id, currency)
ALTER TABLE paper_balances 
DROP CONSTRAINT IF EXISTS paper_balances_exchange_account_id_currency_key;

-- Add new unique constraint (bot_instance_id, currency)
-- Allow NULL bot_instance_id for backwards compatibility during transition
ALTER TABLE paper_balances
DROP CONSTRAINT IF EXISTS paper_balances_bot_instance_currency_unique;

ALTER TABLE paper_balances
ADD CONSTRAINT paper_balances_bot_instance_currency_unique 
UNIQUE (bot_instance_id, currency);

-- =========================================================================
-- 3. Update paper_positions for bot-level queries
-- =========================================================================

-- Ensure bot_instance_id has an index for performance
CREATE INDEX IF NOT EXISTS idx_paper_positions_bot_instance_status 
ON paper_positions(bot_instance_id, status) WHERE status = 'open';

-- =========================================================================
-- 4. Update paper_orders for bot-level queries
-- =========================================================================

-- Ensure bot_instance_id has an index for performance
CREATE INDEX IF NOT EXISTS idx_paper_orders_bot_instance_status 
ON paper_orders(bot_instance_id, status);

-- =========================================================================
-- 5. Update paper_trades for bot-level queries  
-- =========================================================================

CREATE INDEX IF NOT EXISTS idx_paper_trades_bot_instance 
ON paper_trades(bot_instance_id, executed_at DESC);

-- =========================================================================
-- 6. Update paper_performance_snapshots for bot-level
-- =========================================================================

-- Add bot_instance_id column
ALTER TABLE paper_performance_snapshots 
ADD COLUMN IF NOT EXISTS bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE CASCADE;

-- Create index
CREATE INDEX IF NOT EXISTS idx_paper_performance_bot_instance 
ON paper_performance_snapshots(bot_instance_id, snapshot_date DESC);

-- Update unique constraint to include bot_instance_id
ALTER TABLE paper_performance_snapshots 
DROP CONSTRAINT IF EXISTS paper_performance_snapshots_exchange_account_id_snapshot_da_key;

-- New unique constraint allows both exchange-level and bot-level snapshots
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_performance_unique
ON paper_performance_snapshots(
    COALESCE(bot_instance_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(exchange_account_id, '00000000-0000-0000-0000-000000000000'::uuid),
    snapshot_date
);

-- =========================================================================
-- 7. Update paper_position_alerts for bot-level
-- =========================================================================

ALTER TABLE paper_position_alerts
ADD COLUMN IF NOT EXISTS bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_paper_position_alerts_bot
ON paper_position_alerts(bot_instance_id);

-- =========================================================================
-- 8. Update paper_position_history for bot-level queries
-- =========================================================================

-- Add bot_instance_id for direct queries without joining
ALTER TABLE paper_position_history
ADD COLUMN IF NOT EXISTS bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_paper_position_history_bot
ON paper_position_history(bot_instance_id, recorded_at DESC);

-- =========================================================================
-- 9. Update paper_position_tags for bot-level
-- =========================================================================

ALTER TABLE paper_position_tags
ADD COLUMN IF NOT EXISTS bot_instance_id UUID REFERENCES bot_instances(id) ON DELETE CASCADE;

-- Allow tags to be either exchange-level OR bot-level
ALTER TABLE paper_position_tags
DROP CONSTRAINT IF EXISTS paper_position_tags_exchange_account_id_tag_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_position_tags_unique
ON paper_position_tags(
    COALESCE(bot_instance_id, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(exchange_account_id, '00000000-0000-0000-0000-000000000000'::uuid),
    tag_name
);

-- =========================================================================
-- 10. Update trigger to create paper balance for NEW bot instances
-- =========================================================================

CREATE OR REPLACE FUNCTION create_paper_balance_for_bot_instance()
RETURNS TRIGGER AS $$
BEGIN
    -- Create paper balance when bot is set to paper trading mode
    IF NEW.trading_mode = 'paper' THEN
        INSERT INTO paper_balances (
            bot_instance_id, 
            exchange_account_id, 
            currency, 
            balance, 
            available_balance, 
            initial_balance
        )
        VALUES (
            NEW.id, 
            NEW.exchange_account_id,
            'USDT', 
            10000, 
            10000, 
            10000
        )
        ON CONFLICT (bot_instance_id, currency) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for new bot instances
DROP TRIGGER IF EXISTS trigger_create_paper_balance_for_bot ON bot_instances;
CREATE TRIGGER trigger_create_paper_balance_for_bot
    AFTER INSERT ON bot_instances
    FOR EACH ROW
    EXECUTE FUNCTION create_paper_balance_for_bot_instance();

-- Also trigger when trading_mode changes to paper
DROP TRIGGER IF EXISTS trigger_create_paper_balance_on_mode_change ON bot_instances;
CREATE TRIGGER trigger_create_paper_balance_on_mode_change
    AFTER UPDATE OF trading_mode ON bot_instances
    FOR EACH ROW
    WHEN (NEW.trading_mode = 'paper' AND (OLD.trading_mode IS NULL OR OLD.trading_mode != 'paper'))
    EXECUTE FUNCTION create_paper_balance_for_bot_instance();

-- =========================================================================
-- 11. Create paper balances for existing bot instances
-- =========================================================================

-- For any existing bot instances that don't have paper balances yet
INSERT INTO paper_balances (bot_instance_id, exchange_account_id, currency, balance, available_balance, initial_balance)
SELECT 
    bi.id as bot_instance_id,
    bi.exchange_account_id,
    'USDT',
    10000,
    10000,
    10000
FROM bot_instances bi
LEFT JOIN paper_balances pb ON pb.bot_instance_id = bi.id
WHERE pb.id IS NULL
  AND bi.exchange_account_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- =========================================================================
-- 12. View for easy bot paper trading status
-- =========================================================================

CREATE OR REPLACE VIEW v_bot_paper_status AS
SELECT 
    bi.id as bot_instance_id,
    bi.name as bot_name,
    bi.trading_mode,
    bi.exchange_account_id,
    ea.venue as exchange,
    ea.label as exchange_label,
    pb.balance,
    pb.available_balance,
    pb.total_realized_pnl,
    pb.total_fees_paid,
    (SELECT COUNT(*) FROM paper_positions pp WHERE pp.bot_instance_id = bi.id AND pp.status = 'open') as open_positions,
    (SELECT COUNT(*) FROM paper_orders po WHERE po.bot_instance_id = bi.id AND po.status IN ('pending', 'open')) as pending_orders,
    (SELECT COUNT(*) FROM paper_trades pt WHERE pt.bot_instance_id = bi.id) as total_trades
FROM bot_instances bi
LEFT JOIN exchange_accounts ea ON bi.exchange_account_id = ea.id
LEFT JOIN paper_balances pb ON pb.bot_instance_id = bi.id AND pb.currency = 'USDT'
WHERE bi.deleted_at IS NULL;

COMMENT ON VIEW v_bot_paper_status IS 
'View showing paper trading status for each bot instance';

-- =========================================================================
-- Done!
-- =========================================================================




