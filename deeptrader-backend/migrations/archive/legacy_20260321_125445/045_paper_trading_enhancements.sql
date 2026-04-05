-- Migration: Paper Trading Enhancements
-- Adds: position price history, alerts, notes/tags, and performance tracking

-- =========================================================================
-- 1. Position Price History (for charts)
-- =========================================================================
CREATE TABLE IF NOT EXISTS paper_position_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    position_id UUID NOT NULL REFERENCES paper_positions(id) ON DELETE CASCADE,
    price NUMERIC(18, 8) NOT NULL,
    unrealized_pnl NUMERIC(18, 8) DEFAULT 0,
    unrealized_pnl_percent NUMERIC(10, 4) DEFAULT 0,
    margin_ratio NUMERIC(10, 4),
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_paper_position_history_position_id 
ON paper_position_history(position_id, recorded_at DESC);

-- =========================================================================
-- 2. Position Alerts
-- =========================================================================
CREATE TABLE IF NOT EXISTS paper_position_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    position_id UUID NOT NULL REFERENCES paper_positions(id) ON DELETE CASCADE,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL, -- 'price_target', 'price_stop', 'time_limit', 'pnl_target', 'pnl_stop'
    condition VARCHAR(20) NOT NULL, -- 'above', 'below', 'equals', 'after'
    target_value NUMERIC(18, 8), -- price or pnl value
    target_time TIMESTAMP WITH TIME ZONE, -- for time-based alerts
    is_triggered BOOLEAN DEFAULT FALSE,
    triggered_at TIMESTAMP WITH TIME ZONE,
    notification_sent BOOLEAN DEFAULT FALSE,
    message VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for checking alerts
CREATE INDEX IF NOT EXISTS idx_paper_position_alerts_active 
ON paper_position_alerts(position_id, is_triggered) WHERE is_triggered = FALSE;

CREATE INDEX IF NOT EXISTS idx_paper_position_alerts_account 
ON paper_position_alerts(exchange_account_id);

-- =========================================================================
-- 3. Position Notes/Tags
-- =========================================================================
-- Add notes and tags columns to paper_positions
ALTER TABLE paper_positions 
ADD COLUMN IF NOT EXISTS notes TEXT,
ADD COLUMN IF NOT EXISTS tags VARCHAR(50)[] DEFAULT '{}';

-- Create tags table for managing available tags
CREATE TABLE IF NOT EXISTS paper_position_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    tag_name VARCHAR(50) NOT NULL,
    color VARCHAR(20) DEFAULT '#3b82f6', -- Default blue
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange_account_id, tag_name)
);

-- =========================================================================
-- 4. Performance Analytics - Daily Snapshots
-- =========================================================================
CREATE TABLE IF NOT EXISTS paper_performance_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    
    -- Balance metrics
    starting_balance NUMERIC(18, 8) NOT NULL,
    ending_balance NUMERIC(18, 8) NOT NULL,
    equity NUMERIC(18, 8) NOT NULL,
    
    -- PnL metrics
    daily_pnl NUMERIC(18, 8) DEFAULT 0,
    daily_pnl_percent NUMERIC(10, 4) DEFAULT 0,
    cumulative_pnl NUMERIC(18, 8) DEFAULT 0,
    cumulative_pnl_percent NUMERIC(10, 4) DEFAULT 0,
    
    -- Trade metrics
    trades_opened INT DEFAULT 0,
    trades_closed INT DEFAULT 0,
    winning_trades INT DEFAULT 0,
    losing_trades INT DEFAULT 0,
    
    -- Risk metrics
    max_drawdown NUMERIC(10, 4) DEFAULT 0,
    max_drawdown_amount NUMERIC(18, 8) DEFAULT 0,
    peak_equity NUMERIC(18, 8) DEFAULT 0,
    
    -- Position metrics
    positions_open INT DEFAULT 0,
    total_exposure NUMERIC(18, 8) DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exchange_account_id, snapshot_date)
);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_paper_performance_snapshots_date 
ON paper_performance_snapshots(exchange_account_id, snapshot_date DESC);

-- =========================================================================
-- 5. Trade Analytics Extension
-- =========================================================================
-- Add analytics columns to paper_trades if not exist
ALTER TABLE paper_trades 
ADD COLUMN IF NOT EXISTS hold_time_seconds INT,
ADD COLUMN IF NOT EXISTS risk_reward_ratio NUMERIC(10, 4),
ADD COLUMN IF NOT EXISTS mae NUMERIC(18, 8), -- Maximum Adverse Excursion
ADD COLUMN IF NOT EXISTS mfe NUMERIC(18, 8); -- Maximum Favorable Excursion

-- =========================================================================
-- 6. Trigger for automatic price history recording
-- =========================================================================
CREATE OR REPLACE FUNCTION record_paper_position_history()
RETURNS TRIGGER AS $$
BEGIN
    -- Only record if price changed
    IF OLD.current_price IS DISTINCT FROM NEW.current_price THEN
        INSERT INTO paper_position_history (
            position_id, price, unrealized_pnl, unrealized_pnl_percent, margin_ratio
        ) VALUES (
            NEW.id, NEW.current_price, NEW.unrealized_pnl, 
            NEW.unrealized_pnl_percent, NEW.margin_ratio
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS paper_position_history_trigger ON paper_positions;
CREATE TRIGGER paper_position_history_trigger
AFTER UPDATE ON paper_positions
FOR EACH ROW
WHEN (OLD.status = 'open')
EXECUTE FUNCTION record_paper_position_history();

-- =========================================================================
-- 7. Function to calculate performance metrics
-- =========================================================================
CREATE OR REPLACE FUNCTION calculate_paper_performance_metrics(
    p_exchange_account_id UUID,
    p_start_date DATE DEFAULT CURRENT_DATE - INTERVAL '30 days',
    p_end_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    total_return_pct NUMERIC,
    sharpe_ratio NUMERIC,
    sortino_ratio NUMERIC,
    max_drawdown_pct NUMERIC,
    win_rate NUMERIC,
    profit_factor NUMERIC,
    avg_win NUMERIC,
    avg_loss NUMERIC,
    total_trades INT,
    avg_hold_time_hours NUMERIC
) AS $$
DECLARE
    v_risk_free_rate NUMERIC := 0.0; -- Assume 0% for crypto
    v_daily_returns NUMERIC[];
    v_negative_returns NUMERIC[];
    v_avg_return NUMERIC;
    v_std_dev NUMERIC;
    v_downside_dev NUMERIC;
BEGIN
    -- Calculate metrics from snapshots
    SELECT 
        COALESCE(SUM(s.daily_pnl_percent), 0),
        array_agg(s.daily_pnl_percent),
        array_agg(s.daily_pnl_percent) FILTER (WHERE s.daily_pnl_percent < 0)
    INTO total_return_pct, v_daily_returns, v_negative_returns
    FROM paper_performance_snapshots s
    WHERE s.exchange_account_id = p_exchange_account_id
      AND s.snapshot_date BETWEEN p_start_date AND p_end_date;

    -- Calculate average return and std dev
    SELECT AVG(x), STDDEV(x) INTO v_avg_return, v_std_dev FROM unnest(v_daily_returns) x;
    SELECT STDDEV(x) INTO v_downside_dev FROM unnest(v_negative_returns) x;
    
    -- Sharpe ratio (annualized)
    IF v_std_dev IS NOT NULL AND v_std_dev > 0 THEN
        sharpe_ratio := (v_avg_return - v_risk_free_rate) / v_std_dev * SQRT(365);
    ELSE
        sharpe_ratio := 0;
    END IF;
    
    -- Sortino ratio (annualized)
    IF v_downside_dev IS NOT NULL AND v_downside_dev > 0 THEN
        sortino_ratio := (v_avg_return - v_risk_free_rate) / v_downside_dev * SQRT(365);
    ELSE
        sortino_ratio := 0;
    END IF;
    
    -- Max drawdown
    SELECT MAX(max_drawdown) INTO max_drawdown_pct
    FROM paper_performance_snapshots
    WHERE exchange_account_id = p_exchange_account_id
      AND snapshot_date BETWEEN p_start_date AND p_end_date;
    
    -- Trade statistics
    SELECT 
        COUNT(*),
        CASE WHEN COUNT(*) > 0 THEN COUNT(*) FILTER (WHERE realized_pnl > 0)::NUMERIC / COUNT(*) * 100 ELSE 0 END,
        CASE WHEN COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl < 0), 0) != 0 
             THEN ABS(COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl > 0), 0)) / 
                  ABS(COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl < 0), 1))
             ELSE 0 END,
        AVG(realized_pnl) FILTER (WHERE realized_pnl > 0),
        AVG(realized_pnl) FILTER (WHERE realized_pnl < 0),
        AVG(hold_time_seconds) / 3600.0
    INTO total_trades, win_rate, profit_factor, avg_win, avg_loss, avg_hold_time_hours
    FROM paper_trades
    WHERE exchange_account_id = p_exchange_account_id
      AND executed_at::DATE BETWEEN p_start_date AND p_end_date;
    
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- =========================================================================
-- Done!
-- =========================================================================




