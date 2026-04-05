-- Migration: Create tables for Reporting & Portfolio Analytics
-- This enables automated reports and multi-strategy portfolio views

-- Report templates: Define report types and configurations
CREATE TABLE IF NOT EXISTS report_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    report_type VARCHAR(50) NOT NULL, -- 'daily', 'weekly', 'monthly', 'custom'
    description TEXT,
    
    -- Report configuration (JSONB for flexibility)
    config JSONB NOT NULL DEFAULT '{}', -- Sections, metrics, charts, etc.
    
    -- Schedule
    schedule_cron VARCHAR(100), -- Cron expression for automated generation
    enabled BOOLEAN DEFAULT true,
    
    -- Recipients
    recipients JSONB DEFAULT '[]', -- Array of email addresses or user IDs
    
    -- Metadata
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT report_templates_name_unique UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_report_templates_type ON report_templates(report_type);
CREATE INDEX IF NOT EXISTS idx_report_templates_enabled ON report_templates(enabled);

-- Generated reports: Store generated report instances
CREATE TABLE IF NOT EXISTS generated_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID REFERENCES report_templates(id) ON DELETE SET NULL,
    report_type VARCHAR(50) NOT NULL,
    
    -- Report period
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Report data (JSONB for flexible structure)
    report_data JSONB NOT NULL DEFAULT '{}', -- PnL, metrics, charts data, etc.
    
    -- Output formats
    pdf_path TEXT, -- Path to generated PDF
    html_path TEXT, -- Path to generated HTML
    json_path TEXT, -- Path to JSON export
    
    -- Status
    status VARCHAR(20) DEFAULT 'generating', -- 'generating', 'completed', 'failed'
    error_message TEXT,
    
    -- Generation metadata
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    generated_by UUID,
    
    -- Delivery
    sent_at TIMESTAMP WITH TIME ZONE,
    recipients JSONB DEFAULT '[]',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generated_reports_template ON generated_reports(template_id);
CREATE INDEX IF NOT EXISTS idx_generated_reports_type ON generated_reports(report_type);
CREATE INDEX IF NOT EXISTS idx_generated_reports_period ON generated_reports(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_generated_reports_status ON generated_reports(status);
CREATE INDEX IF NOT EXISTS idx_generated_reports_generated ON generated_reports(generated_at DESC);

-- Strategy portfolio: Track multi-strategy performance
CREATE TABLE IF NOT EXISTS strategy_portfolio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_name VARCHAR(100) NOT NULL,
    strategy_family VARCHAR(100), -- Group related strategies
    bot_profile_id UUID, -- Link to bot profile if applicable
    
    -- Performance metrics (snapshot at calculation time)
    calculation_date DATE NOT NULL,
    
    -- PnL metrics
    total_pnl NUMERIC(20, 8) DEFAULT 0,
    realized_pnl NUMERIC(20, 8) DEFAULT 0,
    unrealized_pnl NUMERIC(20, 8) DEFAULT 0,
    
    -- Period returns
    daily_return NUMERIC(10, 6),
    weekly_return NUMERIC(10, 6),
    monthly_return NUMERIC(10, 6),
    ytd_return NUMERIC(10, 6),
    
    -- Risk metrics
    max_drawdown NUMERIC(10, 6),
    sharpe_ratio NUMERIC(10, 4),
    sortino_ratio NUMERIC(10, 4),
    calmar_ratio NUMERIC(10, 4),
    
    -- Trade statistics
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate NUMERIC(5, 2),
    avg_win NUMERIC(20, 8),
    avg_loss NUMERIC(20, 8),
    profit_factor NUMERIC(10, 4),
    
    -- Risk usage
    current_exposure NUMERIC(20, 8),
    max_exposure NUMERIC(20, 8),
    exposure_pct NUMERIC(5, 2), -- % of allocated risk budget
    
    -- Allocation
    risk_budget_pct NUMERIC(5, 2), -- % of total portfolio risk budget
    capital_allocation NUMERIC(20, 8),
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT strategy_portfolio_strategy_date_unique UNIQUE (strategy_name, calculation_date)
);

CREATE INDEX IF NOT EXISTS idx_strategy_portfolio_name ON strategy_portfolio(strategy_name);
CREATE INDEX IF NOT EXISTS idx_strategy_portfolio_family ON strategy_portfolio(strategy_family);
CREATE INDEX IF NOT EXISTS idx_strategy_portfolio_date ON strategy_portfolio(calculation_date DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_portfolio_bot_profile ON strategy_portfolio(bot_profile_id);

-- Strategy correlation: Track correlations between strategies
CREATE TABLE IF NOT EXISTS strategy_correlation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_a VARCHAR(100) NOT NULL,
    strategy_b VARCHAR(100) NOT NULL,
    
    -- Correlation metrics
    calculation_date DATE NOT NULL,
    correlation_coefficient NUMERIC(5, 4), -- -1 to 1
    correlation_period_days INTEGER DEFAULT 30, -- Days used for calculation
    
    -- Additional metrics
    covariance NUMERIC(20, 8),
    beta NUMERIC(10, 4), -- Strategy B's beta relative to Strategy A
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT strategy_correlation_unique UNIQUE (strategy_a, strategy_b, calculation_date),
    CONSTRAINT strategy_correlation_different CHECK (strategy_a != strategy_b)
);

CREATE INDEX IF NOT EXISTS idx_strategy_correlation_a ON strategy_correlation(strategy_a);
CREATE INDEX IF NOT EXISTS idx_strategy_correlation_b ON strategy_correlation(strategy_b);
CREATE INDEX IF NOT EXISTS idx_strategy_correlation_date ON strategy_correlation(calculation_date DESC);

-- Portfolio summary: Aggregate portfolio-level metrics
CREATE TABLE IF NOT EXISTS portfolio_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    calculation_date DATE NOT NULL,
    
    -- Aggregate PnL
    total_portfolio_pnl NUMERIC(20, 8) DEFAULT 0,
    total_realized_pnl NUMERIC(20, 8) DEFAULT 0,
    total_unrealized_pnl NUMERIC(20, 8) DEFAULT 0,
    
    -- Aggregate returns
    portfolio_daily_return NUMERIC(10, 6),
    portfolio_weekly_return NUMERIC(10, 6),
    portfolio_monthly_return NUMERIC(10, 6),
    portfolio_ytd_return NUMERIC(10, 6),
    
    -- Aggregate risk
    portfolio_max_drawdown NUMERIC(10, 6),
    portfolio_sharpe_ratio NUMERIC(10, 4),
    portfolio_sortino_ratio NUMERIC(10, 4),
    
    -- Aggregate trade stats
    total_portfolio_trades INTEGER DEFAULT 0,
    portfolio_win_rate NUMERIC(5, 2),
    
    -- Risk usage
    total_exposure NUMERIC(20, 8),
    total_risk_budget NUMERIC(20, 8),
    risk_budget_utilization_pct NUMERIC(5, 2),
    
    -- Strategy count
    active_strategies_count INTEGER DEFAULT 0,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT portfolio_summary_date_unique UNIQUE (calculation_date)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_summary_date ON portfolio_summary(calculation_date DESC);

COMMENT ON TABLE report_templates IS 'Templates for automated report generation';
COMMENT ON TABLE generated_reports IS 'Generated report instances';
COMMENT ON TABLE strategy_portfolio IS 'Per-strategy performance and risk metrics';
COMMENT ON TABLE strategy_correlation IS 'Correlation metrics between strategies';
COMMENT ON TABLE portfolio_summary IS 'Aggregate portfolio-level metrics';




