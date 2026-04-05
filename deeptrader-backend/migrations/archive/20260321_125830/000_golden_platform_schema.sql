

SELECT pg_catalog.set_config('search_path', '', false);


CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;



COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';



CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;



COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';



CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;



COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';



CREATE TYPE public.bot_command_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'cancelled',
    'expired'
);



CREATE TYPE public.bot_command_type AS ENUM (
    'start',
    'stop',
    'restart',
    'pause',
    'resume',
    'reload_config',
    'update_symbols',
    'emergency_stop'
);



CREATE TYPE public.bot_config_state AS ENUM (
    'created',
    'ready',
    'running',
    'paused',
    'error',
    'decommissioned'
);



CREATE TYPE public.bot_environment AS ENUM (
    'dev',
    'paper',
    'live'
);



CREATE TYPE public.bot_log_category AS ENUM (
    'lifecycle',
    'trade',
    'signal',
    'risk',
    'connection',
    'config',
    'system'
);



CREATE TYPE public.bot_log_level AS ENUM (
    'debug',
    'info',
    'warn',
    'error',
    'fatal'
);



CREATE TYPE public.profile_environment AS ENUM (
    'dev',
    'paper',
    'live'
);



CREATE TYPE public.profile_status AS ENUM (
    'draft',
    'active',
    'disabled',
    'archived'
);



CREATE FUNCTION public.assign_config_version_before() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    next_version INTEGER;
BEGIN
    SELECT COALESCE(MAX(version_number), 0) + 1 INTO next_version
    FROM bot_exchange_config_versions
    WHERE bot_exchange_config_id = NEW.id;

    NEW.config_version := next_version;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.calculate_mae_mfe(p_entry_price numeric, p_high_price numeric, p_low_price numeric, p_side character varying) RETURNS TABLE(mae numeric, mfe numeric, mae_bps numeric, mfe_bps numeric)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_mae NUMERIC;
    v_mfe NUMERIC;
    v_mae_bps NUMERIC;
    v_mfe_bps NUMERIC;
BEGIN
    IF p_side IN ('long', 'buy', 'LONG', 'BUY') THEN
        -- For long positions:
        -- MAE = how far price dropped below entry (adverse)
        -- MFE = how far price rose above entry (favorable)
        v_mae := p_entry_price - COALESCE(p_low_price, p_entry_price);
        v_mfe := COALESCE(p_high_price, p_entry_price) - p_entry_price;
    ELSE
        -- For short positions:
        -- MAE = how far price rose above entry (adverse)
        -- MFE = how far price dropped below entry (favorable)
        v_mae := COALESCE(p_high_price, p_entry_price) - p_entry_price;
        v_mfe := p_entry_price - COALESCE(p_low_price, p_entry_price);
    END IF;
    
    -- Convert to basis points (relative to entry price)
    IF p_entry_price > 0 THEN
        v_mae_bps := (v_mae / p_entry_price) * 10000;
        v_mfe_bps := (v_mfe / p_entry_price) * 10000;
    ELSE
        v_mae_bps := 0;
        v_mfe_bps := 0;
    END IF;
    
    -- Ensure non-negative values
    v_mae := GREATEST(v_mae, 0);
    v_mfe := GREATEST(v_mfe, 0);
    v_mae_bps := GREATEST(v_mae_bps, 0);
    v_mfe_bps := GREATEST(v_mfe_bps, 0);
    
    mae := v_mae;
    mfe := v_mfe;
    mae_bps := v_mae_bps;
    mfe_bps := v_mfe_bps;
    
    RETURN NEXT;
END;
$$;



CREATE FUNCTION public.calculate_paper_performance_metrics(p_exchange_account_id uuid, p_start_date date DEFAULT (CURRENT_DATE - '30 days'::interval), p_end_date date DEFAULT CURRENT_DATE) RETURNS TABLE(total_return_pct numeric, sharpe_ratio numeric, sortino_ratio numeric, max_drawdown_pct numeric, win_rate numeric, profit_factor numeric, avg_win numeric, avg_loss numeric, total_trades integer, avg_hold_time_hours numeric)
    LANGUAGE plpgsql
    AS $$
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
$$;



CREATE FUNCTION public.complete_bot_command(p_command_id uuid, p_success boolean, p_result jsonb DEFAULT NULL::jsonb, p_error jsonb DEFAULT NULL::jsonb, p_message text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql
    AS $$
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
$$;



CREATE FUNCTION public.create_audit_log_entry(p_user_id uuid, p_resource_type character varying, p_resource_id uuid, p_action character varying, p_environment character varying, p_before_state jsonb, p_after_state jsonb, p_notes text DEFAULT NULL::text) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
    audit_id UUID;
BEGIN
    INSERT INTO config_audit_log (
        user_id,
        resource_type,
        resource_id,
        action,
        environment,
        before_state,
        after_state,
        notes
    ) VALUES (
        p_user_id,
        p_resource_type,
        p_resource_id,
        p_action,
        p_environment,
        p_before_state,
        p_after_state,
        p_notes
    )
    RETURNING id INTO audit_id;
    
    RETURN audit_id;
END;
$$;



COMMENT ON FUNCTION public.create_audit_log_entry(p_user_id uuid, p_resource_type character varying, p_resource_id uuid, p_action character varying, p_environment character varying, p_before_state jsonb, p_after_state jsonb, p_notes text) IS 'Helper to create audit log entries from application code';



CREATE FUNCTION public.create_default_exchange_policy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO exchange_policies (exchange_account_id)
    VALUES (NEW.id)
    ON CONFLICT (exchange_account_id) DO NOTHING;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.create_default_risk_policy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO tenant_risk_policies (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.create_initial_profile_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    config_snap JSONB;
BEGIN
    config_snap := jsonb_build_object(
        'strategy_composition', NEW.strategy_composition,
        'risk_config', NEW.risk_config,
        'conditions', NEW.conditions,
        'lifecycle', NEW.lifecycle,
        'execution', NEW.execution,
        'status', NEW.status,
        'is_active', NEW.is_active
    );
    
    INSERT INTO profile_versions (profile_id, version, config_snapshot, changed_by, change_summary)
    VALUES (NEW.id, 1, config_snap, NEW.user_id, 'Initial version');
    
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.create_paper_balance_for_bot_instance() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.trading_mode = 'paper' THEN
    INSERT INTO public.paper_balances (
      bot_instance_id,
      currency,
      balance,
      available_balance,
      initial_balance
    )
    VALUES (
      NEW.id,
      'USDT',
      10000,
      10000,
      10000
    )
    ON CONFLICT (bot_instance_id, currency) DO NOTHING;
  END IF;
  RETURN NEW;
END;
$$;



CREATE FUNCTION public.create_profile_version_snapshot() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    config_snap JSONB;
    prev_config JSONB;
    diff_result JSONB;
BEGIN
    -- Build config snapshot
    config_snap := jsonb_build_object(
        'strategy_composition', NEW.strategy_composition,
        'risk_config', NEW.risk_config,
        'conditions', NEW.conditions,
        'lifecycle', NEW.lifecycle,
        'execution', NEW.execution,
        'status', NEW.status,
        'is_active', NEW.is_active
    );
    
    -- Get previous version's config for diff
    SELECT config_snapshot INTO prev_config
    FROM profile_versions
    WHERE profile_id = NEW.id
    ORDER BY version DESC
    LIMIT 1;
    
    -- Simple diff (just track that something changed)
    IF prev_config IS NOT NULL THEN
        diff_result := jsonb_build_object(
            'previous_version', OLD.version,
            'fields_changed', (
                SELECT jsonb_agg(key)
                FROM jsonb_each(config_snap) AS new_kv
                WHERE NOT EXISTS (
                    SELECT 1 FROM jsonb_each(prev_config) AS old_kv
                    WHERE old_kv.key = new_kv.key AND old_kv.value = new_kv.value
                )
            )
        );
    END IF;
    
    -- Insert version record
    INSERT INTO profile_versions (profile_id, version, config_snapshot, changed_by, diff_from_previous)
    VALUES (NEW.id, NEW.version, config_snap, NEW.user_id, diff_result);
    
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.ensure_single_active_bot_config() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.is_active = true THEN
        -- Deactivate all other configs for the same user
        UPDATE bot_exchange_configs bec
        SET is_active = false, updated_at = NOW()
        FROM bot_instances bi
        WHERE bec.bot_instance_id = bi.id
          AND bi.user_id = (SELECT user_id FROM bot_instances WHERE id = NEW.bot_instance_id)
          AND bec.id != NEW.id
          AND bec.is_active = true;
    END IF;
    RETURN NEW;
END;
$$;





CREATE TABLE public.bot_commands (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_instance_id uuid,
    exchange_config_id uuid,
    user_id uuid NOT NULL,
    command_type public.bot_command_type NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb,
    priority integer DEFAULT 0,
    status public.bot_command_status DEFAULT 'pending'::public.bot_command_status,
    status_message text,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    executed_by text,
    result jsonb,
    error_details jsonb,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    correlation_id text,
    parent_command_id uuid
);



COMMENT ON TABLE public.bot_commands IS 'Queue-based bot control commands with audit trail';



COMMENT ON COLUMN public.bot_commands.priority IS 'Higher values = higher priority. Emergency commands should use high priority.';



COMMENT ON COLUMN public.bot_commands.expires_at IS 'Optional TTL - command will be marked expired if not processed by this time';



COMMENT ON COLUMN public.bot_commands.correlation_id IS 'For tracking related commands (e.g., restart = stop + start)';



CREATE FUNCTION public.get_next_bot_command(p_bot_instance_id uuid DEFAULT NULL::uuid) RETURNS public.bot_commands
    LANGUAGE plpgsql
    AS $$
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
$$;



CREATE FUNCTION public.insert_config_version_after() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO bot_exchange_config_versions (
        bot_exchange_config_id,
        version_number,
        trading_capital_usd,
        enabled_symbols,
        risk_config,
        execution_config,
        profile_overrides,
        change_type,
        was_activated,
        activated_at
    ) VALUES (
        NEW.id,
        NEW.config_version,
        NEW.trading_capital_usd,
        NEW.enabled_symbols,
        NEW.risk_config,
        NEW.execution_config,
        NEW.profile_overrides,
        CASE
            WHEN TG_OP = 'INSERT' THEN 'create'
            WHEN NEW.is_active = true AND (OLD.is_active IS NULL OR OLD.is_active = false) THEN 'activate'
            WHEN NEW.is_active = false AND OLD.is_active = true THEN 'deactivate'
            ELSE 'update'
        END,
        NEW.is_active,
        CASE WHEN NEW.is_active = true THEN NOW() ELSE NULL END
    );

    RETURN NEW;
END;
$$;



CREATE FUNCTION public.normalize_percent_jsonb(payload jsonb, key text) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
  raw text;
  num numeric;
BEGIN
  IF payload IS NULL OR NOT (payload ? key) THEN
    RETURN payload;
  END IF;
  raw := payload->>key;
  IF raw IS NULL OR raw = '' THEN
    RETURN payload;
  END IF;
  BEGIN
    num := raw::numeric;
  EXCEPTION WHEN others THEN
    RETURN payload;
  END;
  IF num > 1 THEN
    RETURN jsonb_set(payload, ARRAY[key], to_jsonb(num / 100), true);
  END IF;
  RETURN payload;
END;
$$;



CREATE FUNCTION public.normalize_percent_value(value numeric) RETURNS numeric
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF value IS NULL THEN
    RETURN NULL;
  END IF;
  IF value > 1 THEN
    RETURN value / 100;
  END IF;
  RETURN value;
END;
$$;



CREATE FUNCTION public.record_paper_position_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;



CREATE FUNCTION public.reset_daily_loss_tracking() RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Reset exchange policies daily loss
    UPDATE exchange_policies
    SET daily_loss_used_usd = 0,
        daily_loss_reset_at = NOW()
    WHERE daily_loss_reset_at < CURRENT_DATE;
    
    -- Reset bot budgets daily loss
    UPDATE bot_budgets
    SET daily_loss_used_usd = 0,
        daily_reset_at = NOW()
    WHERE daily_reset_at < CURRENT_DATE;
END;
$$;



COMMENT ON FUNCTION public.reset_daily_loss_tracking() IS 'Call daily to reset loss tracking counters';



CREATE FUNCTION public.update_paper_position_high_low() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Update high_price if current price is higher
    IF NEW.current_price IS NOT NULL THEN
        NEW.high_price := GREATEST(COALESCE(NEW.high_price, NEW.current_price), NEW.current_price);
        NEW.low_price := LEAST(COALESCE(NEW.low_price, NEW.current_price), NEW.current_price);
    END IF;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.update_portfolio_on_position_close() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status = 'open' THEN
        UPDATE portfolios
        SET open_positions_count = GREATEST(open_positions_count - 1, 0),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.portfolio_id;
    END IF;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.update_portfolio_on_position_open() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE portfolios
    SET open_positions_count = open_positions_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.portfolio_id;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.update_profile_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    
    -- Increment version if any config changed
    IF OLD.strategy_composition IS DISTINCT FROM NEW.strategy_composition
       OR OLD.risk_config IS DISTINCT FROM NEW.risk_config
       OR OLD.conditions IS DISTINCT FROM NEW.conditions
       OR OLD.lifecycle IS DISTINCT FROM NEW.lifecycle
       OR OLD.execution IS DISTINCT FROM NEW.execution THEN
        NEW.version = OLD.version + 1;
    END IF;
    
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.update_strategy_instance_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    -- Increment version on param changes
    IF OLD.params IS DISTINCT FROM NEW.params THEN
        NEW.version = OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.update_strategy_instance_usage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    old_strategy_ids UUID[];
    new_strategy_ids UUID[];
    strategy_id UUID;
BEGIN
    -- Extract strategy instance IDs from old composition
    IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN
        SELECT ARRAY_AGG((elem->>'instance_id')::UUID)
        INTO old_strategy_ids
        FROM jsonb_array_elements(OLD.strategy_composition) elem
        WHERE elem->>'instance_id' IS NOT NULL;
    END IF;
    
    -- Extract strategy instance IDs from new composition
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        SELECT ARRAY_AGG((elem->>'instance_id')::UUID)
        INTO new_strategy_ids
        FROM jsonb_array_elements(NEW.strategy_composition) elem
        WHERE elem->>'instance_id' IS NOT NULL;
    END IF;
    
    -- Decrement count for removed strategies
    IF old_strategy_ids IS NOT NULL THEN
        FOREACH strategy_id IN ARRAY old_strategy_ids LOOP
            IF new_strategy_ids IS NULL OR NOT strategy_id = ANY(new_strategy_ids) THEN
                UPDATE strategy_instances 
                SET usage_count = GREATEST(0, usage_count - 1)
                WHERE id = strategy_id;
            END IF;
        END LOOP;
    END IF;
    
    -- Increment count for added strategies
    IF new_strategy_ids IS NOT NULL THEN
        FOREACH strategy_id IN ARRAY new_strategy_ids LOOP
            IF old_strategy_ids IS NULL OR NOT strategy_id = ANY(old_strategy_ids) THEN
                UPDATE strategy_instances 
                SET usage_count = usage_count + 1
                WHERE id = strategy_id;
            END IF;
        END LOOP;
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;



CREATE FUNCTION public.validate_profile_environment_match() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    profile_env TEXT;
    config_env TEXT;
BEGIN
    IF NEW.mounted_profile_id IS NULL THEN
        RETURN NEW;
    END IF;
    
    -- Get profile environment
    SELECT environment::TEXT INTO profile_env
    FROM user_chessboard_profiles
    WHERE id = NEW.mounted_profile_id;
    
    -- Get config environment
    config_env := NEW.environment::TEXT;
    
    -- Validate: Dev profiles can only mount to dev, Paper to paper, Live to live
    -- Exception: Paper profiles can mount to dev for testing
    IF profile_env = 'live' AND config_env != 'live' THEN
        RAISE EXCEPTION 'Live profiles can only be mounted on live exchange configs';
    END IF;
    
    IF profile_env = 'dev' AND config_env = 'live' THEN
        RAISE EXCEPTION 'Dev profiles cannot be mounted on live exchange configs';
    END IF;
    
    IF profile_env = 'paper' AND config_env = 'live' THEN
        RAISE EXCEPTION 'Paper profiles cannot be mounted on live exchange configs. Promote to Live first.';
    END IF;
    
    -- Set mounted timestamp
    NEW.mounted_at = NOW();
    
    RETURN NEW;
END;
$$;



CREATE TABLE public.alerts (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    portfolio_id uuid,
    type character varying(50) NOT NULL,
    symbol character varying(20),
    title character varying(255) NOT NULL,
    message text NOT NULL,
    severity character varying(20) DEFAULT 'info'::character varying,
    is_read boolean DEFAULT false,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT alerts_severity_check CHECK (((severity)::text = ANY ((ARRAY['info'::character varying, 'warning'::character varying, 'error'::character varying, 'critical'::character varying])::text[])))
);



CREATE TABLE public.amt_metrics (
    "time" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    timeframe text NOT NULL,
    value_area_low double precision,
    value_area_high double precision,
    point_of_control double precision,
    total_volume double precision,
    rotation_factor double precision,
    position_in_value text,
    auction_type text,
    CONSTRAINT amt_metrics_auction_type_check CHECK ((auction_type = ANY (ARRAY['balanced'::text, 'imbalanced_up'::text, 'imbalanced_down'::text]))),
    CONSTRAINT amt_metrics_position_in_value_check CHECK ((position_in_value = ANY (ARRAY['above_value'::text, 'below_value'::text, 'inside_value'::text, 'at_value'::text])))
);



COMMENT ON TABLE public.amt_metrics IS 'Auction Market Theory metrics and value areas';



CREATE TABLE public.approvals (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    promotion_id uuid,
    action_type text NOT NULL,
    action_description text NOT NULL,
    risk_level text NOT NULL,
    requested_by uuid,
    approver_id uuid,
    status text DEFAULT 'pending'::text NOT NULL,
    approval_required boolean DEFAULT true,
    requires_different_role boolean DEFAULT false,
    approval_notes text,
    rejection_reason text,
    risk_acceptance_confirmed boolean DEFAULT false,
    requested_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    approved_at timestamp with time zone,
    rejected_at timestamp with time zone,
    expires_at timestamp with time zone,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.audit_log (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    action_type text NOT NULL,
    action_category text NOT NULL,
    resource_type text,
    resource_id text,
    action_description text NOT NULL,
    action_details jsonb,
    before_state jsonb,
    after_state jsonb,
    ip_address inet,
    user_agent text,
    severity text DEFAULT 'info'::text,
    requires_retention boolean DEFAULT true,
    retention_days integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.audit_log_exports (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    export_type text NOT NULL,
    date_range_start timestamp with time zone,
    date_range_end timestamp with time zone,
    filters jsonb,
    file_path text,
    file_size_bytes bigint,
    record_count integer,
    export_status text DEFAULT 'pending'::text,
    error_message text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    completed_at timestamp with time zone
);



CREATE TABLE public.backtest_decision_snapshots (
    run_id uuid NOT NULL,
    ts timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    decision text NOT NULL,
    rejection_reason text,
    profile_id text,
    payload jsonb NOT NULL
);



CREATE TABLE public.backtest_equity_curve (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    backtest_run_id uuid NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    equity numeric(15,2) NOT NULL,
    drawdown numeric(10,4),
    drawdown_percent numeric(10,4),
    run_id uuid GENERATED ALWAYS AS (backtest_run_id) STORED,
    ts timestamp with time zone GENERATED ALWAYS AS ("timestamp") STORED,
    realized_pnl numeric,
    open_positions integer
);



COMMENT ON TABLE public.backtest_equity_curve IS 'Equity curve data points for backtest runs';



CREATE TABLE public.backtest_metrics (
    run_id uuid NOT NULL,
    realized_pnl double precision NOT NULL,
    total_fees double precision NOT NULL,
    total_trades integer NOT NULL,
    win_rate double precision NOT NULL,
    max_drawdown_pct double precision NOT NULL,
    avg_slippage_bps double precision NOT NULL,
    total_return_pct double precision NOT NULL,
    profit_factor double precision NOT NULL,
    avg_trade_pnl double precision NOT NULL,
    sharpe_ratio double precision,
    sortino_ratio double precision,
    trades_per_day double precision,
    fee_drag_pct double precision,
    slippage_drag_pct double precision,
    gross_profit double precision,
    gross_loss double precision,
    avg_win double precision,
    avg_loss double precision,
    largest_win double precision,
    largest_loss double precision,
    winning_trades integer,
    losing_trades integer
);



CREATE TABLE public.backtest_position_snapshots (
    run_id uuid NOT NULL,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);



CREATE TABLE public.backtest_runs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    strategy_id text NOT NULL,
    symbol text NOT NULL,
    exchange text DEFAULT 'okx'::text NOT NULL,
    start_date timestamp with time zone NOT NULL,
    end_date timestamp with time zone NOT NULL,
    initial_capital numeric(15,2) DEFAULT 10000.0 NOT NULL,
    commission_per_trade numeric(5,4) DEFAULT 0.001 NOT NULL,
    slippage_model text DEFAULT 'fixed'::text NOT NULL,
    slippage_bps numeric(5,2) DEFAULT 5.0 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    total_return_percent numeric(10,4),
    sharpe_ratio numeric(10,4),
    max_drawdown_percent numeric(10,4),
    win_rate numeric(5,4),
    total_trades integer,
    profit_factor numeric(10,4),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    error_message text,
    name text,
    execution_diagnostics jsonb,
    tenant_id text,
    bot_id text,
    config jsonb,
    run_id uuid GENERATED ALWAYS AS (id) STORED,
    started_at timestamp with time zone GENERATED ALWAYS AS (start_date) STORED,
    finished_at timestamp with time zone GENERATED ALWAYS AS (completed_at) STORED,
    CONSTRAINT backtest_runs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'cancelled'::text])))
);



COMMENT ON TABLE public.backtest_runs IS 'Backtest run metadata and results';



CREATE TABLE public.backtest_symbol_equity_curve (
    run_id uuid NOT NULL,
    symbol text NOT NULL,
    ts timestamp with time zone NOT NULL,
    equity double precision NOT NULL,
    realized_pnl double precision NOT NULL,
    open_positions integer NOT NULL
);



CREATE TABLE public.backtest_symbol_metrics (
    run_id uuid NOT NULL,
    symbol text NOT NULL,
    realized_pnl double precision NOT NULL,
    total_fees double precision NOT NULL,
    total_trades integer NOT NULL,
    win_rate double precision NOT NULL,
    avg_trade_pnl double precision NOT NULL,
    profit_factor double precision NOT NULL,
    avg_slippage_bps double precision,
    sharpe_ratio double precision,
    sortino_ratio double precision,
    trades_per_day double precision
);



CREATE TABLE public.backtest_trades (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    backtest_run_id uuid NOT NULL,
    symbol text NOT NULL,
    side text NOT NULL,
    entry_price numeric(15,8) NOT NULL,
    exit_price numeric(15,8),
    size numeric(15,8) NOT NULL,
    entry_time timestamp with time zone NOT NULL,
    exit_time timestamp with time zone,
    pnl numeric(15,8),
    pnl_percent numeric(10,4),
    commission numeric(15,8) DEFAULT 0,
    slippage numeric(15,8) DEFAULT 0,
    duration_seconds integer,
    exit_reason text,
    run_id uuid GENERATED ALWAYS AS (backtest_run_id) STORED,
    ts timestamp with time zone GENERATED ALWAYS AS (entry_time) STORED,
    entry_fee numeric,
    exit_fee numeric,
    reason text,
    strategy_id text,
    profile_id text,
    entry_slippage_bps numeric,
    exit_slippage_bps numeric,
    total_fees numeric,
    CONSTRAINT backtest_trades_side_check CHECK ((side = ANY (ARRAY['buy'::text, 'sell'::text])))
);



COMMENT ON TABLE public.backtest_trades IS 'Individual trades from backtest runs';



CREATE TABLE public.bot_budgets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_instance_id uuid NOT NULL,
    exchange_account_id uuid NOT NULL,
    max_daily_loss_pct numeric(10,4),
    max_daily_loss_usd numeric(20,2),
    max_margin_used_pct numeric(10,4),
    max_exposure_pct numeric(10,4),
    max_open_positions integer,
    max_leverage numeric(5,2),
    max_order_rate_per_min integer,
    daily_loss_used_usd numeric(20,2) DEFAULT 0,
    margin_used_usd numeric(20,2) DEFAULT 0,
    current_positions integer DEFAULT 0,
    daily_reset_at timestamp with time zone DEFAULT now(),
    budget_version integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.bot_budgets IS 'Per-bot budget allocations within an exchange account (required in PROP mode)';



CREATE TABLE public.bot_exchange_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_instance_id uuid NOT NULL,
    credential_id uuid,
    environment public.bot_environment DEFAULT 'paper'::public.bot_environment NOT NULL,
    trading_capital_usd numeric(20,2),
    enabled_symbols jsonb DEFAULT '[]'::jsonb,
    risk_config jsonb DEFAULT '{}'::jsonb,
    execution_config jsonb DEFAULT '{}'::jsonb,
    profile_overrides jsonb DEFAULT '{}'::jsonb,
    state public.bot_config_state DEFAULT 'created'::public.bot_config_state NOT NULL,
    last_state_change timestamp with time zone DEFAULT now(),
    last_error text,
    is_active boolean DEFAULT false,
    activated_at timestamp with time zone,
    last_heartbeat_at timestamp with time zone,
    decisions_count bigint DEFAULT 0,
    trades_count integer DEFAULT 0,
    config_version integer DEFAULT 1,
    metadata jsonb DEFAULT '{}'::jsonb,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    exchange_account_id uuid,
    exchange character varying(32),
    deleted_at timestamp with time zone,
    mounted_profile_id uuid,
    mounted_profile_version integer,
    mounted_at timestamp with time zone,
    last_error_at timestamp with time zone,
    error_count integer DEFAULT 0,
    trading_capital_pct numeric(10,4) DEFAULT 0.80,
    min_trading_capital_usd numeric(20,2) DEFAULT NULL::numeric,
    max_trading_capital_usd numeric(20,2) DEFAULT NULL::numeric,
    position_size_pct numeric(10,4) DEFAULT 0.10,
    CONSTRAINT check_min_max_capital CHECK (((min_trading_capital_usd IS NULL) OR (max_trading_capital_usd IS NULL) OR (min_trading_capital_usd <= max_trading_capital_usd))),
    CONSTRAINT check_position_size_pct_range CHECK (((position_size_pct >= 0.001) AND (position_size_pct <= 1.00))),
    CONSTRAINT check_trading_capital_pct_range CHECK (((trading_capital_pct >= 0.01) AND (trading_capital_pct <= 1.00)))
);



COMMENT ON TABLE public.bot_exchange_configs IS 'Runtime binding of bot instance + exchange credential + environment';



COMMENT ON COLUMN public.bot_exchange_configs.credential_id IS 'Legacy: kept for backward compatibility, will be phased out';



COMMENT ON COLUMN public.bot_exchange_configs.environment IS 'Trading environment: dev (local testing), paper (simulated), live (real money)';



COMMENT ON COLUMN public.bot_exchange_configs.state IS 'Lifecycle state: created -> ready -> running/paused/error -> decommissioned';



COMMENT ON COLUMN public.bot_exchange_configs.is_active IS 'Only one config can be active per user at a time';



COMMENT ON COLUMN public.bot_exchange_configs.exchange_account_id IS 'New: references exchange_accounts for the operating modes system';



COMMENT ON COLUMN public.bot_exchange_configs.exchange IS 'Denormalized exchange name (e.g., binance, okx) for quick access';



COMMENT ON COLUMN public.bot_exchange_configs.deleted_at IS 'Soft delete timestamp';



COMMENT ON COLUMN public.bot_exchange_configs.mounted_profile_id IS 'The user profile currently mounted for trading on this exchange';



COMMENT ON COLUMN public.bot_exchange_configs.mounted_profile_version IS 'The specific version of the profile that was mounted';



COMMENT ON COLUMN public.bot_exchange_configs.mounted_at IS 'Timestamp when the profile was mounted';



COMMENT ON COLUMN public.bot_exchange_configs.trading_capital_pct IS 'Percentage of account balance to use as trading capital (default 80%)';



COMMENT ON COLUMN public.bot_exchange_configs.min_trading_capital_usd IS 'Optional minimum trading capital floor in USD';



COMMENT ON COLUMN public.bot_exchange_configs.max_trading_capital_usd IS 'Optional maximum trading capital ceiling in USD';



COMMENT ON COLUMN public.bot_exchange_configs.position_size_pct IS 'Percentage of trading capital per position (default 10%)';



CREATE TABLE public.bot_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    description text,
    strategy_template_id uuid,
    allocator_role character varying(32) DEFAULT 'core'::character varying,
    default_risk_config jsonb DEFAULT '{"maxLeverage": 1, "leverageMode": "isolated", "maxPositions": 4, "maxDailyLossPct": 0.05, "positionSizePct": 0.10, "maxTotalExposurePct": 0.40, "maxPositionsPerSymbol": 1, "maxDailyLossPerSymbolPct": 0.025}'::jsonb,
    default_execution_config jsonb DEFAULT '{"stopLossPct": 0.02, "takeProfitPct": 0.05, "trailingStopPct": 0.01, "defaultOrderType": "market", "maxHoldTimeHours": 24, "executionTimeoutSec": 5, "minTradeIntervalSec": 1, "trailingStopEnabled": false, "enableVolatilityFilter": true}'::jsonb,
    profile_overrides jsonb DEFAULT '{}'::jsonb,
    tags text[] DEFAULT ARRAY[]::text[],
    is_active boolean DEFAULT true,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    exchange_account_id uuid,
    runtime_state character varying(32) DEFAULT 'idle'::character varying,
    last_heartbeat_at timestamp with time zone,
    last_error text,
    last_error_code character varying(64),
    started_at timestamp with time zone,
    stopped_at timestamp with time zone,
    environment character varying(16) DEFAULT 'paper'::character varying,
    enabled_symbols jsonb DEFAULT '[]'::jsonb,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    trading_mode character varying(16) DEFAULT 'paper'::character varying,
    market_type character varying(20) DEFAULT 'perp'::character varying NOT NULL,
    CONSTRAINT bot_instances_runtime_state_check CHECK (((runtime_state)::text = ANY ((ARRAY['idle'::character varying, 'starting'::character varying, 'running'::character varying, 'paused'::character varying, 'stopping'::character varying, 'error'::character varying])::text[]))),
    CONSTRAINT bot_instances_trading_mode_check CHECK (((trading_mode)::text = ANY ((ARRAY['paper'::character varying, 'live'::character varying])::text[])))
);



COMMENT ON TABLE public.bot_instances IS 'User-facing bot configurations that reference strategy templates';



COMMENT ON COLUMN public.bot_instances.allocator_role IS 'Role in portfolio allocation: core, satellite, hedge, experimental';



COMMENT ON COLUMN public.bot_instances.default_risk_config IS 'Default risk settings, can be overridden per exchange attachment';



COMMENT ON COLUMN public.bot_instances.profile_overrides IS 'Overrides to merge with strategy template profile bundle';



COMMENT ON COLUMN public.bot_instances.exchange_account_id IS 'The exchange account (risk pool) this bot trades on';



COMMENT ON COLUMN public.bot_instances.runtime_state IS 'Current execution state: idle, starting, running, paused, stopping, error';



COMMENT ON COLUMN public.bot_instances.environment IS 'Deployment environment: dev/paper/live. For operational context, not trading mode.';



COMMENT ON COLUMN public.bot_instances.enabled_symbols IS 'Symbols this bot is configured to trade';



COMMENT ON COLUMN public.bot_instances.deleted_at IS 'Soft delete timestamp - when set, bot is considered deleted';



COMMENT ON COLUMN public.bot_instances.deleted_by IS 'User who deleted the bot';



COMMENT ON COLUMN public.bot_instances.trading_mode IS 'Trading mode: paper=simulated locally, live=real exchange orders. Different from environment which is deployment context.';



COMMENT ON COLUMN public.bot_instances.market_type IS 'Trading market type: perp (futures/scalping) or spot';



CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(255) NOT NULL,
    encrypted_password character varying(255),
    name character varying(255),
    avatar_url text,
    role character varying(50) DEFAULT 'user'::character varying,
    is_active boolean DEFAULT true,
    email_confirmed_at timestamp with time zone,
    last_sign_in_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    two_factor_secret text,
    two_factor_enabled boolean DEFAULT false,
    two_factor_backup_codes jsonb,
    operating_mode character varying(16) DEFAULT 'solo'::character varying,
    settings jsonb DEFAULT '{}'::jsonb,
    metadata jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT users_operating_mode_check CHECK (((operating_mode)::text = ANY ((ARRAY['solo'::character varying, 'team'::character varying, 'prop'::character varying])::text[])))
);



COMMENT ON COLUMN public.users.operating_mode IS 'Operating mode: solo (1 bot per exchange), team (concurrent + locks), prop (concurrent + locks + budgets required)';



CREATE VIEW public.bot_command_history AS
 SELECT bc.id,
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
    bi.name AS bot_name,
    bec.exchange,
    bec.environment,
    u.email AS user_email
   FROM (((public.bot_commands bc
     LEFT JOIN public.bot_instances bi ON ((bc.bot_instance_id = bi.id)))
     LEFT JOIN public.bot_exchange_configs bec ON ((bc.exchange_config_id = bec.id)))
     LEFT JOIN public.users u ON ((bc.user_id = u.id)))
  ORDER BY bc.created_at DESC;



CREATE TABLE public.bot_config_actions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    bot_profile_id uuid NOT NULL,
    bot_profile_version_id uuid,
    action text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    performed_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bot_config_actions_action_check CHECK ((action = ANY (ARRAY['create_profile'::text, 'clone_version'::text, 'update_version'::text, 'promote_version'::text, 'activate_version'::text, 'rollback_version'::text, 'start_bot'::text, 'stop_bot'::text, 'pause_bot'::text, 'resume_bot'::text])))
);



COMMENT ON TABLE public.bot_config_actions IS 'Audit trail for bot configuration + control plane actions';



CREATE TABLE public.bot_exchange_config_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_exchange_config_id uuid NOT NULL,
    version_number integer NOT NULL,
    trading_capital_usd numeric(20,2),
    enabled_symbols jsonb,
    risk_config jsonb,
    execution_config jsonb,
    profile_overrides jsonb,
    change_summary text,
    change_type character varying(32),
    created_by uuid,
    was_activated boolean DEFAULT false,
    activated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.bot_exchange_config_versions IS 'Immutable version history of bot-exchange configurations';



CREATE TABLE public.bot_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_instance_id uuid NOT NULL,
    bot_exchange_config_id uuid,
    user_id uuid NOT NULL,
    level public.bot_log_level DEFAULT 'info'::public.bot_log_level NOT NULL,
    category public.bot_log_category DEFAULT 'system'::public.bot_log_category NOT NULL,
    message text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb,
    error_code character varying(64),
    error_type character varying(128),
    stack_trace text,
    symbol character varying(32),
    order_id character varying(128),
    position_id uuid,
    source character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '30 days'::interval)
);



COMMENT ON TABLE public.bot_logs IS 'Event and error logs for bot instances - allows users to see what happened';



COMMENT ON COLUMN public.bot_logs.level IS 'Log severity: debug, info, warn, error, fatal';



COMMENT ON COLUMN public.bot_logs.category IS 'Log category for filtering: lifecycle, trade, signal, risk, connection, config, system';



COMMENT ON COLUMN public.bot_logs.details IS 'Structured JSON data with additional context';



COMMENT ON COLUMN public.bot_logs.error_code IS 'Machine-readable error code for programmatic handling';



COMMENT ON COLUMN public.bot_logs.expires_at IS 'Auto-cleanup: logs expire after 30 days by default';



CREATE TABLE public.bot_pool_assignments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    credential_id uuid,
    bot_id character varying(128) NOT NULL,
    pool_node character varying(128),
    instance_type character varying(32) DEFAULT 'hot'::character varying,
    status character varying(32) DEFAULT 'pending'::character varying,
    started_at timestamp with time zone,
    stopped_at timestamp with time zone,
    last_heartbeat_at timestamp with time zone,
    error_message text,
    config_snapshot jsonb,
    decisions_count bigint DEFAULT 0,
    trades_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.bot_pool_assignments IS 'Tracks which bot instance is running for each user in the pool';



CREATE TABLE public.bot_profile_versions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    bot_profile_id uuid NOT NULL,
    version_number integer NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    config_blob jsonb NOT NULL,
    checksum text,
    notes text,
    created_by uuid,
    promoted_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    activated_at timestamp with time zone,
    CONSTRAINT bot_profile_versions_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'testing'::text, 'active'::text, 'retired'::text])))
);



COMMENT ON TABLE public.bot_profile_versions IS 'Immutable configuration payloads for each bot profile';



CREATE TABLE public.bot_profiles (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    name text NOT NULL,
    environment text NOT NULL,
    engine_type text DEFAULT 'fast_scalper'::text NOT NULL,
    description text,
    status text DEFAULT 'inactive'::text NOT NULL,
    owner_id uuid,
    active_version_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bot_profiles_environment_check CHECK ((environment = ANY (ARRAY['dev'::text, 'paper'::text, 'live'::text]))),
    CONSTRAINT bot_profiles_status_check CHECK ((status = ANY (ARRAY['inactive'::text, 'ready'::text, 'running'::text, 'error'::text])))
);



COMMENT ON TABLE public.bot_profiles IS 'Logical trading bots grouped by environment';



COMMENT ON COLUMN public.bot_profiles.active_version_id IS 'Currently active configuration version';



CREATE TABLE public.bot_symbol_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_exchange_config_id uuid NOT NULL,
    symbol character varying(64) NOT NULL,
    enabled boolean DEFAULT true,
    max_exposure_pct numeric(10,4),
    max_position_size_usd numeric(20,2),
    max_positions integer DEFAULT 1,
    max_leverage numeric(5,2),
    symbol_risk_config jsonb DEFAULT '{}'::jsonb,
    symbol_profile_overrides jsonb DEFAULT '{}'::jsonb,
    preferred_order_type character varying(32),
    max_slippage_bps integer,
    notes text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.bot_symbol_configs IS 'Per-symbol overrides within a bot-exchange configuration';



COMMENT ON COLUMN public.bot_symbol_configs.max_exposure_pct IS 'Maximum exposure for this symbol as percentage of trading capital';



COMMENT ON COLUMN public.bot_symbol_configs.symbol_risk_config IS 'Risk parameter overrides specific to this symbol';



COMMENT ON COLUMN public.bot_symbol_configs.symbol_profile_overrides IS 'Strategy/profile overrides for this symbol';



CREATE TABLE public.bot_version_sections (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    bot_profile_version_id uuid NOT NULL,
    section text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.bot_version_sections IS 'Optional per-section payloads extracted from config blobs';



CREATE TABLE public.capacity_analysis (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    profile_id text NOT NULL,
    notional_bucket numeric NOT NULL,
    avg_pnl numeric,
    avg_sharpe numeric,
    avg_slippage_bps numeric,
    avg_fees_pct numeric,
    trade_count integer DEFAULT 0 NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.capacity_analysis IS 'Capacity curves showing performance vs notional size';



CREATE TABLE public.component_var (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    symbol text NOT NULL,
    horizon text DEFAULT '1d'::text,
    confidence numeric DEFAULT 0.95,
    var_value numeric,
    es_value numeric,
    sample_size integer,
    method text DEFAULT 'proxy'::text,
    params jsonb,
    calculated_at timestamp with time zone DEFAULT now()
);



CREATE TABLE public.config_audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    resource_type character varying(64) NOT NULL,
    resource_id uuid NOT NULL,
    action character varying(64) NOT NULL,
    environment character varying(16),
    before_state jsonb,
    after_state jsonb,
    change_diff jsonb,
    from_version integer,
    to_version integer,
    ip_address inet,
    user_agent text,
    request_id character varying(64),
    notes text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.config_audit_log IS 'Comprehensive audit trail for all configuration changes';



CREATE TABLE public.config_diffs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    promotion_id uuid,
    source_config_id uuid,
    target_config_id uuid,
    diff_type text NOT NULL,
    diff_summary jsonb NOT NULL,
    diff_details jsonb NOT NULL,
    risk_changes jsonb,
    feature_changes jsonb,
    profile_changes jsonb,
    symbol_changes jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.copilot_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    title text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.copilot_conversations IS 'Stores copilot conversation metadata. Each conversation belongs to a user and persists permanently.';



CREATE TABLE public.copilot_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    tool_calls jsonb,
    tool_call_id text,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.copilot_messages IS 'Stores individual messages within copilot conversations. Supports user, assistant, and tool roles with optional tool call data.';



CREATE TABLE public.copilot_settings_snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    version integer NOT NULL,
    settings jsonb NOT NULL,
    actor text NOT NULL,
    conversation_id uuid,
    mutation_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.copilot_settings_snapshots IS 'Stores versioned point-in-time snapshots of user settings for rollback capability.';



CREATE TABLE public.cost_aggregation (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    symbol text,
    profile_id text,
    period_type text NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL,
    total_trades integer DEFAULT 0 NOT NULL,
    total_volume numeric DEFAULT 0 NOT NULL,
    total_slippage_bps numeric DEFAULT 0 NOT NULL,
    total_fees numeric DEFAULT 0 NOT NULL,
    total_funding_cost numeric DEFAULT 0 NOT NULL,
    total_cost numeric DEFAULT 0 NOT NULL,
    gross_pnl numeric,
    net_pnl numeric,
    cost_drag_pct numeric,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cost_aggregation_period_type_check CHECK ((period_type = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text])))
);



COMMENT ON TABLE public.cost_aggregation IS 'Pre-aggregated cost metrics for fast queries';



CREATE TABLE public.credential_balance_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    credential_id uuid NOT NULL,
    user_id uuid NOT NULL,
    exchange_balance numeric(20,8) NOT NULL,
    trading_capital numeric(20,8),
    available_balance numeric(20,8),
    margin_used numeric(20,8),
    unrealized_pnl numeric(20,8),
    currency character varying(16) DEFAULT 'USDT'::character varying,
    fetch_source character varying(32),
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.credential_balance_history IS 'Historical balance snapshots for audit and tracking';



CREATE TABLE public.credential_config_audit (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    credential_id uuid NOT NULL,
    user_id uuid NOT NULL,
    config_type character varying(32) NOT NULL,
    old_value jsonb,
    new_value jsonb,
    changed_fields text[],
    change_reason text,
    changed_by character varying(64),
    ip_address character varying(64),
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.credential_config_audit IS 'Audit trail of all configuration changes per credential';



CREATE TABLE public.data_quality_alerts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(50) NOT NULL,
    alert_type character varying(50) NOT NULL,
    severity character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    threshold_value numeric(20,8),
    actual_value numeric(20,8),
    threshold_type character varying(50),
    detected_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone,
    status character varying(20) DEFAULT 'open'::character varying,
    description text,
    resolution_notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.data_quality_alerts IS 'Alerts when data quality thresholds are breached';



CREATE TABLE public.data_quality_metrics (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(50) NOT NULL,
    timeframe character varying(20) NOT NULL,
    metric_date date NOT NULL,
    total_candles_expected integer NOT NULL,
    total_candles_received integer NOT NULL,
    missing_candles_count integer DEFAULT 0,
    duplicate_candles_count integer DEFAULT 0,
    avg_ingest_latency_ms numeric(10,2),
    max_ingest_latency_ms numeric(10,2),
    min_ingest_latency_ms numeric(10,2),
    outlier_count integer DEFAULT 0,
    gap_count integer DEFAULT 0,
    invalid_price_count integer DEFAULT 0,
    timestamp_drift_seconds numeric(10,2),
    quality_score numeric(5,2) DEFAULT 100.0,
    status character varying(20) DEFAULT 'healthy'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.data_quality_metrics IS 'Daily quality metrics per symbol/timeframe';



CREATE TABLE public.decision_traces (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    trade_id text NOT NULL,
    symbol text NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    decision_type text NOT NULL,
    decision_outcome text NOT NULL,
    signal_data jsonb,
    market_context jsonb,
    stage_results jsonb NOT NULL,
    rejection_reasons jsonb,
    final_decision jsonb,
    execution_result jsonb,
    trace_metadata jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    gate_results jsonb,
    execution_metrics jsonb,
    feature_contributions jsonb,
    config_version integer,
    bot_id uuid,
    exchange_account_id uuid
);



COMMENT ON COLUMN public.decision_traces.gate_results IS 'JSON object with pass/fail status for each gate (data, risk, microstructure)';



COMMENT ON COLUMN public.decision_traces.execution_metrics IS 'JSON with expected_price, submitted_price, fill_price, slippage_bps, fill_time_ms';



COMMENT ON COLUMN public.decision_traces.feature_contributions IS 'JSON array of top contributing features with z-scores';



CREATE TABLE public.equity_curves (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    equity numeric(18,8) NOT NULL,
    pnl numeric(18,8) DEFAULT 0 NOT NULL,
    pnl_percent numeric(5,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.exchange_accounts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    venue character varying(32) NOT NULL,
    label character varying(128) NOT NULL,
    environment character varying(16) NOT NULL,
    secret_id character varying(256),
    is_demo boolean DEFAULT false,
    status character varying(32) DEFAULT 'pending'::character varying,
    last_verified_at timestamp with time zone,
    verification_error text,
    permissions jsonb,
    exchange_balance numeric(20,8),
    available_balance numeric(20,8),
    margin_used numeric(20,8),
    unrealized_pnl numeric(20,8),
    balance_currency character varying(16) DEFAULT 'USDT'::character varying,
    balance_updated_at timestamp with time zone,
    active_bot_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.exchange_accounts IS 'Exchange accounts represent the risk pool boundary - shared balance/margin across all bots';



COMMENT ON COLUMN public.exchange_accounts.is_demo IS 'True if using exchange demo trading (Bybit api-demo, OKX simulated). Not available for Binance.';



COMMENT ON COLUMN public.exchange_accounts.active_bot_id IS 'SOLO mode: the single bot allowed to run on this account+env';



CREATE TABLE public.exchange_limits (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange character varying(32) NOT NULL,
    max_leverage integer DEFAULT 125,
    default_leverage integer DEFAULT 1,
    min_position_usd numeric(20,2) DEFAULT 5.00,
    max_position_usd numeric(20,2) DEFAULT 1000000.00,
    min_stop_loss_pct numeric(10,4) DEFAULT 0.001,
    max_daily_trades integer DEFAULT 1000,
    supports_isolated_margin boolean DEFAULT true,
    supports_cross_margin boolean DEFAULT true,
    supports_trailing_stop boolean DEFAULT true,
    supports_bracket_orders boolean DEFAULT true,
    last_updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.exchange_limits IS 'Exchange-imposed limits used for validation';



CREATE TABLE public.exchange_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange_account_id uuid NOT NULL,
    max_daily_loss_pct numeric(10,4) DEFAULT 0.10,
    max_daily_loss_usd numeric(20,2),
    daily_loss_used_usd numeric(20,2) DEFAULT 0,
    daily_loss_reset_at timestamp with time zone DEFAULT now(),
    max_margin_used_pct numeric(10,4) DEFAULT 0.80,
    max_gross_exposure_pct numeric(10,4) DEFAULT 1.00,
    max_net_exposure_pct numeric(10,4) DEFAULT 0.50,
    max_leverage numeric(5,2) DEFAULT 10.0,
    max_open_positions integer DEFAULT 10,
    kill_switch_enabled boolean DEFAULT false,
    kill_switch_triggered_at timestamp with time zone,
    kill_switch_triggered_by uuid,
    kill_switch_reason text,
    circuit_breaker_enabled boolean DEFAULT true,
    circuit_breaker_loss_pct numeric(10,4) DEFAULT 0.05,
    circuit_breaker_cooldown_min integer DEFAULT 60,
    circuit_breaker_triggered_at timestamp with time zone,
    live_trading_enabled boolean DEFAULT false,
    policy_version integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.exchange_policies IS 'Hard risk caps per exchange account - enforced across all bots';



COMMENT ON COLUMN public.exchange_policies.kill_switch_enabled IS 'When true, ALL trading is blocked on this account';



COMMENT ON COLUMN public.exchange_policies.circuit_breaker_loss_pct IS 'Auto-trigger kill switch at this daily loss %';



CREATE TABLE public.exchange_token_catalog (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange character varying(32) NOT NULL,
    symbol character varying(64) NOT NULL,
    base_currency character varying(16),
    quote_currency character varying(16),
    contract_type character varying(32),
    min_size numeric(20,8),
    tick_size numeric(20,8),
    contract_value numeric(20,8),
    is_active boolean DEFAULT true,
    exchange_symbol character varying(64),
    metadata jsonb,
    last_updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.exchange_token_catalog IS 'Cached catalog of available trading pairs per exchange';



CREATE TABLE public.fast_scalper_positions (
    id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    user_id text NOT NULL,
    symbol text NOT NULL,
    exchange text DEFAULT 'okx'::text NOT NULL,
    side text NOT NULL,
    size numeric NOT NULL,
    entry_price numeric NOT NULL,
    current_price numeric,
    entry_time timestamp with time zone NOT NULL,
    stop_loss numeric,
    take_profit numeric,
    unrealized_pnl numeric,
    strategy_id text,
    profile_id text,
    status text DEFAULT 'open'::text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    bot_id uuid,
    CONSTRAINT fast_scalper_positions_side_check CHECK ((side = ANY (ARRAY['long'::text, 'short'::text, 'net'::text])))
);



COMMENT ON COLUMN public.fast_scalper_positions.bot_id IS 'Bot instance managing this position';



CREATE SEQUENCE public.fast_scalper_positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.fast_scalper_positions_id_seq OWNED BY public.fast_scalper_positions.id;



CREATE TABLE public.fast_scalper_trades (
    id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    user_id text NOT NULL,
    symbol text NOT NULL,
    exchange text DEFAULT 'okx'::text NOT NULL,
    side text NOT NULL,
    size numeric NOT NULL,
    entry_price numeric NOT NULL,
    exit_price numeric NOT NULL,
    entry_time timestamp with time zone NOT NULL,
    exit_time timestamp with time zone NOT NULL,
    pnl numeric NOT NULL,
    pnl_pct numeric,
    fees numeric DEFAULT 0,
    strategy_id text,
    profile_id text,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    bot_id uuid,
    CONSTRAINT fast_scalper_trades_side_check CHECK ((side = ANY (ARRAY['long'::text, 'short'::text, 'buy'::text, 'sell'::text, 'net'::text])))
);



COMMENT ON COLUMN public.fast_scalper_trades.bot_id IS 'Bot instance that executed this trade';



CREATE SEQUENCE public.fast_scalper_trades_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.fast_scalper_trades_id_seq OWNED BY public.fast_scalper_trades.id;



CREATE TABLE public.feature_dictionary (
    feature_name character varying(100) NOT NULL,
    display_name character varying(200),
    description text,
    category character varying(50),
    unit character varying(20),
    typical_range jsonb,
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.feature_dictionary IS 'Dictionary of trading features with descriptions for UI display';



CREATE TABLE public.feed_gaps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(50) NOT NULL,
    timeframe character varying(20) NOT NULL,
    gap_start_time timestamp with time zone NOT NULL,
    gap_end_time timestamp with time zone NOT NULL,
    gap_duration_seconds integer NOT NULL,
    expected_candles_count integer,
    missing_candles_count integer,
    detected_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone,
    resolution_method character varying(50),
    severity character varying(20) DEFAULT 'medium'::character varying,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.feed_gaps IS 'Tracks gaps in data feeds';



CREATE TABLE public.generated_reports (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    template_id uuid,
    report_type character varying(50) NOT NULL,
    period_start timestamp with time zone NOT NULL,
    period_end timestamp with time zone NOT NULL,
    report_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    pdf_path text,
    html_path text,
    json_path text,
    status character varying(20) DEFAULT 'generating'::character varying,
    error_message text,
    generated_at timestamp with time zone DEFAULT now(),
    generated_by uuid,
    sent_at timestamp with time zone,
    recipients jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.generated_reports IS 'Generated report instances';



CREATE TABLE public.incident_affected_objects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_id uuid NOT NULL,
    object_type character varying(20) NOT NULL,
    object_id uuid NOT NULL,
    symbol character varying(50),
    side character varying(10),
    quantity numeric(20,8),
    entry_price numeric(20,8),
    exit_price numeric(20,8),
    pnl_impact numeric(20,8),
    fees numeric(20,8),
    reject_reason character varying(255),
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.incident_affected_objects IS 'Positions and orders affected by an incident';



CREATE TABLE public.incident_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_id uuid NOT NULL,
    event_type character varying(50) NOT NULL,
    actor character varying(255),
    event_data jsonb,
    created_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.incident_events IS 'Timeline events for incident audit trail';



CREATE TABLE public.incidents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_type character varying(50) NOT NULL,
    severity character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    affected_symbols text[] NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    pnl_impact numeric(20,8),
    positions_affected integer,
    trades_affected integer,
    status character varying(20) DEFAULT 'open'::character varying,
    resolution_notes text,
    detected_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    exchange_account_id uuid,
    bot_id uuid,
    owner_id character varying(255),
    acknowledged_at timestamp with time zone,
    acknowledged_by character varying(255),
    trigger_rule character varying(100),
    trigger_threshold numeric(20,8),
    trigger_actual numeric(20,8),
    action_taken character varying(50),
    exposure_peak numeric(20,8),
    drawdown_peak numeric(20,8),
    unrealized_pnl_impact numeric(20,8),
    reject_count integer DEFAULT 0,
    latency_p99_ms integer
);



COMMENT ON TABLE public.incidents IS 'Risk incidents with full audit trail for ops console';



CREATE TABLE public.market_candles (
    "time" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    timeframe text NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    trades_count integer
);



COMMENT ON TABLE public.market_candles IS 'OHLCV candle data at various timeframes';



CREATE TABLE public.market_trades (
    "time" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    price double precision NOT NULL,
    volume double precision NOT NULL,
    side text,
    trade_id text,
    buyer_order_id text,
    seller_order_id text,
    CONSTRAINT market_trades_side_check CHECK ((side = ANY (ARRAY['buy'::text, 'sell'::text])))
);



COMMENT ON TABLE public.market_trades IS 'Time-series table for individual market trades from exchanges';



CREATE TABLE public.microstructure_features (
    "time" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    bid_ask_spread double precision,
    bid_ask_imbalance double precision,
    order_book_depth_5 double precision,
    order_book_depth_10 double precision,
    trade_flow_imbalance double precision,
    vwap double precision,
    vwap_deviation double precision,
    realized_volatility double precision
);



COMMENT ON TABLE public.microstructure_features IS 'Market microstructure and order flow features';



CREATE TABLE public.order_book_snapshots (
    "time" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    bids jsonb,
    asks jsonb,
    spread double precision,
    mid_price double precision,
    bid_volume double precision,
    ask_volume double precision
);



COMMENT ON TABLE public.order_book_snapshots IS 'Time-series snapshots of order book state';



CREATE TABLE public.orders (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    order_type character varying(20) NOT NULL,
    side character varying(10) NOT NULL,
    quantity numeric(18,8) NOT NULL,
    price numeric(18,8),
    stop_price numeric(18,8),
    trailing_percent numeric(5,2),
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    filled_quantity numeric(18,8) DEFAULT 0,
    avg_fill_price numeric(18,8),
    time_in_force character varying(10) DEFAULT 'GTC'::character varying,
    post_only boolean DEFAULT false,
    reduce_only boolean DEFAULT false,
    linked_orders jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    filled_at timestamp with time zone,
    expires_at timestamp with time zone,
    exchange character varying(20) DEFAULT 'binance'::character varying,
    exchange_order_id character varying(100),
    error_message text,
    metadata jsonb,
    exchange_account_id uuid,
    bot_id uuid,
    profile_id uuid,
    profile_version integer,
    trace_id uuid,
    reject_code character varying(64),
    reject_scope character varying(32),
    reject_details jsonb,
    CONSTRAINT orders_filled_quantity_check CHECK ((filled_quantity >= (0)::numeric)),
    CONSTRAINT orders_order_type_check CHECK (((order_type)::text = ANY ((ARRAY['market'::character varying, 'limit'::character varying, 'stop_loss'::character varying, 'stop_limit'::character varying, 'trailing_stop'::character varying, 'take_profit'::character varying, 'bracket'::character varying, 'oco'::character varying])::text[]))),
    CONSTRAINT orders_quantity_check CHECK ((quantity > (0)::numeric)),
    CONSTRAINT orders_side_check CHECK (((side)::text = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::text[]))),
    CONSTRAINT orders_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'active'::character varying, 'filled'::character varying, 'cancelled'::character varying, 'expired'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT orders_time_in_force_check CHECK (((time_in_force)::text = ANY ((ARRAY['GTC'::character varying, 'IOC'::character varying, 'FOK'::character varying, 'GTD'::character varying])::text[])))
);



CREATE TABLE public.paper_balances (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    exchange_account_id uuid,
    currency character varying(10) DEFAULT 'USDT'::character varying NOT NULL,
    balance numeric(18,8) DEFAULT 10000 NOT NULL,
    available_balance numeric(18,8) DEFAULT 10000 NOT NULL,
    initial_balance numeric(18,8) DEFAULT 10000 NOT NULL,
    total_realized_pnl numeric(18,8) DEFAULT 0,
    total_fees_paid numeric(18,8) DEFAULT 0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    bot_instance_id uuid
);



CREATE TABLE public.paper_orders (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    bot_instance_id uuid,
    exchange_account_id uuid NOT NULL,
    symbol character varying(30) NOT NULL,
    side character varying(10) NOT NULL,
    order_type character varying(20) NOT NULL,
    quantity numeric(18,8) NOT NULL,
    price numeric(18,8),
    stop_price numeric(18,8),
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    filled_quantity numeric(18,8) DEFAULT 0,
    avg_fill_price numeric(18,8),
    time_in_force character varying(10) DEFAULT 'GTC'::character varying,
    reduce_only boolean DEFAULT false,
    simulated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    filled_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    reject_reason text,
    metadata jsonb,
    CONSTRAINT paper_orders_filled_quantity_check CHECK ((filled_quantity >= (0)::numeric)),
    CONSTRAINT paper_orders_order_type_check CHECK (((order_type)::text = ANY ((ARRAY['market'::character varying, 'limit'::character varying, 'stop_loss'::character varying, 'stop_limit'::character varying, 'take_profit'::character varying])::text[]))),
    CONSTRAINT paper_orders_quantity_check CHECK ((quantity > (0)::numeric)),
    CONSTRAINT paper_orders_side_check CHECK (((side)::text = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::text[]))),
    CONSTRAINT paper_orders_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'open'::character varying, 'filled'::character varying, 'partial'::character varying, 'cancelled'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT paper_orders_time_in_force_check CHECK (((time_in_force)::text = ANY ((ARRAY['GTC'::character varying, 'IOC'::character varying, 'FOK'::character varying])::text[])))
);



CREATE TABLE public.paper_performance_snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange_account_id uuid NOT NULL,
    snapshot_date date NOT NULL,
    starting_balance numeric(18,8) NOT NULL,
    ending_balance numeric(18,8) NOT NULL,
    equity numeric(18,8) NOT NULL,
    daily_pnl numeric(18,8) DEFAULT 0,
    daily_pnl_percent numeric(10,4) DEFAULT 0,
    cumulative_pnl numeric(18,8) DEFAULT 0,
    cumulative_pnl_percent numeric(10,4) DEFAULT 0,
    trades_opened integer DEFAULT 0,
    trades_closed integer DEFAULT 0,
    winning_trades integer DEFAULT 0,
    losing_trades integer DEFAULT 0,
    max_drawdown numeric(10,4) DEFAULT 0,
    max_drawdown_amount numeric(18,8) DEFAULT 0,
    peak_equity numeric(18,8) DEFAULT 0,
    positions_open integer DEFAULT 0,
    total_exposure numeric(18,8) DEFAULT 0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    bot_instance_id uuid
);



CREATE TABLE public.paper_position_alerts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    position_id uuid NOT NULL,
    exchange_account_id uuid NOT NULL,
    alert_type character varying(50) NOT NULL,
    condition character varying(20) NOT NULL,
    target_value numeric(18,8),
    target_time timestamp with time zone,
    is_triggered boolean DEFAULT false,
    triggered_at timestamp with time zone,
    notification_sent boolean DEFAULT false,
    message character varying(500),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    bot_instance_id uuid
);



CREATE TABLE public.paper_position_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    position_id uuid NOT NULL,
    price numeric(18,8) NOT NULL,
    unrealized_pnl numeric(18,8) DEFAULT 0,
    unrealized_pnl_percent numeric(10,4) DEFAULT 0,
    margin_ratio numeric(10,4),
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    bot_instance_id uuid
);



CREATE TABLE public.paper_position_tags (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange_account_id uuid NOT NULL,
    tag_name character varying(50) NOT NULL,
    color character varying(20) DEFAULT '#3b82f6'::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    bot_instance_id uuid
);



CREATE TABLE public.paper_positions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    bot_instance_id uuid,
    exchange_account_id uuid NOT NULL,
    symbol character varying(30) NOT NULL,
    side character varying(10) NOT NULL,
    size numeric(18,8) NOT NULL,
    entry_price numeric(18,8) NOT NULL,
    current_price numeric(18,8),
    leverage numeric(5,2) DEFAULT 1,
    margin_used numeric(18,8) DEFAULT 0,
    unrealized_pnl numeric(18,8) DEFAULT 0,
    unrealized_pnl_pct numeric(10,4) DEFAULT 0,
    stop_loss numeric(18,8),
    take_profit numeric(18,8),
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    opened_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    closed_at timestamp with time zone,
    close_reason character varying(50),
    realized_pnl numeric(18,8),
    fees_paid numeric(18,8) DEFAULT 0,
    metadata jsonb,
    notes text,
    tags character varying(50)[] DEFAULT '{}'::character varying[],
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    strategy_id character varying(100),
    profile_id character varying(100),
    high_price numeric(18,8) DEFAULT NULL::numeric,
    low_price numeric(18,8) DEFAULT NULL::numeric,
    CONSTRAINT paper_positions_side_check CHECK (((side)::text = ANY ((ARRAY['long'::character varying, 'short'::character varying])::text[]))),
    CONSTRAINT paper_positions_size_check CHECK ((size >= (0)::numeric)),
    CONSTRAINT paper_positions_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'closed'::character varying, 'liquidated'::character varying])::text[])))
);



COMMENT ON COLUMN public.paper_positions.strategy_id IS 'ID of the strategy that opened this position';



COMMENT ON COLUMN public.paper_positions.profile_id IS 'ID of the profile that opened this position';



COMMENT ON COLUMN public.paper_positions.high_price IS 'Highest price reached since position opened (for MFE calculation)';



COMMENT ON COLUMN public.paper_positions.low_price IS 'Lowest price reached since position opened (for MAE calculation)';



CREATE TABLE public.paper_trades (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    bot_instance_id uuid,
    exchange_account_id uuid NOT NULL,
    paper_order_id uuid,
    paper_position_id uuid,
    symbol character varying(30) NOT NULL,
    side character varying(10) NOT NULL,
    quantity numeric(18,8) NOT NULL,
    price numeric(18,8) NOT NULL,
    fee numeric(18,8) DEFAULT 0,
    fee_currency character varying(10) DEFAULT 'USDT'::character varying,
    realized_pnl numeric(18,8) DEFAULT 0,
    executed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    metadata jsonb,
    hold_time_seconds integer,
    risk_reward_ratio numeric(10,4),
    mae numeric(18,8),
    mfe numeric(18,8),
    mae_bps numeric(10,2) DEFAULT NULL::numeric,
    mfe_bps numeric(10,2) DEFAULT NULL::numeric,
    CONSTRAINT paper_trades_side_check CHECK (((side)::text = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::text[])))
);



COMMENT ON COLUMN public.paper_trades.mae_bps IS 'Max Adverse Excursion in basis points';



COMMENT ON COLUMN public.paper_trades.mfe_bps IS 'Max Favorable Excursion in basis points';



CREATE TABLE public.portfolio_summary (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    calculation_date date NOT NULL,
    total_portfolio_pnl numeric(20,8) DEFAULT 0,
    total_realized_pnl numeric(20,8) DEFAULT 0,
    total_unrealized_pnl numeric(20,8) DEFAULT 0,
    portfolio_daily_return numeric(10,6),
    portfolio_weekly_return numeric(10,6),
    portfolio_monthly_return numeric(10,6),
    portfolio_ytd_return numeric(10,6),
    portfolio_max_drawdown numeric(10,6),
    portfolio_sharpe_ratio numeric(10,4),
    portfolio_sortino_ratio numeric(10,4),
    total_portfolio_trades integer DEFAULT 0,
    portfolio_win_rate numeric(5,2),
    total_exposure numeric(20,8),
    total_risk_budget numeric(20,8),
    risk_budget_utilization_pct numeric(5,2),
    active_strategies_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.portfolio_summary IS 'Aggregate portfolio-level metrics';



CREATE TABLE public.portfolios (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    name character varying(100) DEFAULT 'Main Portfolio'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    open_positions_count integer DEFAULT 0,
    total_unrealized_pnl numeric(18,8) DEFAULT 0
);



CREATE TABLE public.position_impacts (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    scenario_id uuid NOT NULL,
    symbol text NOT NULL,
    side text,
    size numeric,
    entry_price numeric,
    shocked_price numeric,
    pnl numeric,
    pnl_pct numeric,
    factor_impacts jsonb,
    created_at timestamp with time zone DEFAULT now()
);



CREATE TABLE public.position_updates (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    position_id uuid NOT NULL,
    price numeric(18,8) NOT NULL,
    unrealized_pnl numeric(18,8) NOT NULL,
    unrealized_pnl_percent numeric(5,2) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.positions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    entry_order_id uuid,
    symbol character varying(20) NOT NULL,
    side character varying(10) NOT NULL,
    quantity numeric(18,8) NOT NULL,
    entry_price numeric(18,8) NOT NULL,
    current_price numeric(18,8) NOT NULL,
    stop_loss numeric(18,8),
    take_profit numeric(18,8),
    unrealized_pnl numeric(18,8) DEFAULT 0,
    unrealized_pnl_percent numeric(5,2) DEFAULT 0,
    fees_paid numeric(18,8) DEFAULT 0,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    opened_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    closed_at timestamp with time zone,
    close_reason character varying(50),
    metadata jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    leverage numeric(5,2) DEFAULT 1.0,
    initial_margin numeric(18,8) DEFAULT 0,
    maintenance_margin numeric(18,8) DEFAULT 0,
    liquidation_price numeric(18,8),
    margin_ratio numeric(8,2) DEFAULT 0,
    margin_mode character varying(20) DEFAULT 'isolated'::character varying,
    exchange_account_id uuid,
    bot_id uuid,
    CONSTRAINT positions_margin_mode_check CHECK (((margin_mode)::text = ANY ((ARRAY['isolated'::character varying, 'cross'::character varying])::text[]))),
    CONSTRAINT positions_quantity_check CHECK ((quantity > (0)::numeric)),
    CONSTRAINT positions_side_check CHECK (((side)::text = ANY ((ARRAY['long'::character varying, 'short'::character varying])::text[]))),
    CONSTRAINT positions_status_check CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'closed'::character varying, 'liquidated'::character varying])::text[])))
);



CREATE TABLE public.profile_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    profile_id uuid NOT NULL,
    version integer NOT NULL,
    config_snapshot jsonb NOT NULL,
    change_summary text,
    changed_by uuid,
    change_reason text,
    diff_from_previous jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



COMMENT ON TABLE public.profile_versions IS 'Audit trail of all profile configuration changes';



CREATE TABLE public.promotion_history (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    promotion_id uuid,
    event_type text NOT NULL,
    event_description text,
    performed_by uuid,
    event_data jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.promotions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    promotion_type text NOT NULL,
    source_environment text NOT NULL,
    target_environment text NOT NULL,
    bot_profile_id uuid,
    bot_version_id uuid,
    status text DEFAULT 'pending'::text NOT NULL,
    requested_by uuid,
    approved_by uuid,
    rejected_by uuid,
    requested_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    approved_at timestamp with time zone,
    rejected_at timestamp with time zone,
    completed_at timestamp with time zone,
    rejection_reason text,
    approval_notes text,
    backtest_summary jsonb,
    paper_trading_stats jsonb,
    config_diff jsonb,
    risk_assessment jsonb,
    requires_approval boolean DEFAULT true,
    auto_approved boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.replay_annotations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid,
    "timestamp" timestamp with time zone NOT NULL,
    annotation_type character varying(50) DEFAULT 'note'::character varying NOT NULL,
    title character varying(200),
    content text,
    tags text[],
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.replay_annotations IS 'User annotations on replay timeline for post-mortem analysis';



CREATE TABLE public.replay_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_id uuid,
    symbol character varying(50) NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    created_by character varying(255),
    session_name character varying(255),
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    last_accessed_at timestamp with time zone DEFAULT now(),
    integrity_score numeric(5,2),
    data_gaps integer DEFAULT 0,
    snapshot_coverage numeric(5,2),
    dataset_hash character varying(64),
    config_version integer,
    bot_id uuid,
    exchange_account_id uuid,
    outcome_summary jsonb
);



COMMENT ON TABLE public.replay_sessions IS 'Tracks investigation sessions for incident analysis';



COMMENT ON COLUMN public.replay_sessions.dataset_hash IS 'SHA256 hash of dataset for reproducibility verification';



CREATE TABLE public.replay_snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(50) NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    market_data jsonb NOT NULL,
    decision_context jsonb NOT NULL,
    position_state jsonb,
    pnl_state jsonb,
    snapshot_type character varying(50) DEFAULT 'decision_point'::character varying,
    incident_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    gate_states jsonb,
    regime_label character varying(50),
    anomaly_flags jsonb,
    latency_ms integer,
    data_quality_score numeric(5,2)
);



COMMENT ON TABLE public.replay_snapshots IS 'Stores complete market and decision state at decision points for replay';



CREATE TABLE public.report_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    report_type character varying(50) NOT NULL,
    description text,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    schedule_cron character varying(100),
    enabled boolean DEFAULT true,
    recipients jsonb DEFAULT '[]'::jsonb,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.report_templates IS 'Templates for automated report generation';



CREATE TABLE public.retention_policies (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    log_type text NOT NULL,
    action_category text,
    retention_days integer NOT NULL,
    auto_archive boolean DEFAULT false,
    archive_location text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.risk_metrics_aggregation (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    period_type text NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    portfolio_id text,
    symbol text,
    profile_id text,
    var_95_1d numeric,
    var_99_1d numeric,
    es_95_1d numeric,
    es_99_1d numeric,
    var_95_5d numeric,
    var_99_5d numeric,
    max_drawdown_pct numeric,
    volatility_pct numeric,
    sharpe_ratio numeric,
    sortino_ratio numeric,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.scenario_results (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    scenario_name text NOT NULL,
    scenario_type text NOT NULL,
    description text,
    portfolio_id text,
    symbol text,
    profile_id text,
    shock_type text NOT NULL,
    shock_value numeric NOT NULL,
    shock_units text DEFAULT 'pct'::text,
    base_portfolio_value numeric NOT NULL,
    shocked_portfolio_value numeric NOT NULL,
    pnl_impact numeric NOT NULL,
    pnl_impact_pct numeric NOT NULL,
    max_drawdown_pct numeric,
    affected_positions jsonb,
    calculation_timestamp timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    scenario_params jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.schema_migrations (
    id bigint NOT NULL,
    filename text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);



CREATE SEQUENCE public.schema_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



ALTER SEQUENCE public.schema_migrations_id_seq OWNED BY public.schema_migrations.id;



CREATE TABLE public.strategy_correlation (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_a character varying(100) NOT NULL,
    strategy_b character varying(100) NOT NULL,
    calculation_date date NOT NULL,
    correlation_coefficient numeric(5,4),
    correlation_period_days integer DEFAULT 30,
    covariance numeric(20,8),
    beta numeric(10,4),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT strategy_correlation_different CHECK (((strategy_a)::text <> (strategy_b)::text))
);



COMMENT ON TABLE public.strategy_correlation IS 'Correlation metrics between strategies';



CREATE TABLE public.strategy_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    template_id character varying(100) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    usage_count integer DEFAULT 0,
    last_backtest_at timestamp with time zone,
    last_backtest_summary jsonb,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_system_template boolean DEFAULT false
);



COMMENT ON TABLE public.strategy_instances IS 'User-customized instances of strategy templates with parameterized settings';



COMMENT ON COLUMN public.strategy_instances.user_id IS 'Owner of the strategy instance. NULL for system templates (visible to all users)';



COMMENT ON COLUMN public.strategy_instances.template_id IS 'References the base strategy in the Python strategy registry';



COMMENT ON COLUMN public.strategy_instances.params IS 'User-customized parameters merged with template defaults at runtime';



COMMENT ON COLUMN public.strategy_instances.usage_count IS 'Number of profiles currently using this strategy instance';



COMMENT ON COLUMN public.strategy_instances.is_system_template IS 'When true, this strategy is a system template visible to all users for use in profiles';



CREATE TABLE public.strategy_portfolio (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_name character varying(100) NOT NULL,
    strategy_family character varying(100),
    bot_profile_id uuid,
    calculation_date date NOT NULL,
    total_pnl numeric(20,8) DEFAULT 0,
    realized_pnl numeric(20,8) DEFAULT 0,
    unrealized_pnl numeric(20,8) DEFAULT 0,
    daily_return numeric(10,6),
    weekly_return numeric(10,6),
    monthly_return numeric(10,6),
    ytd_return numeric(10,6),
    max_drawdown numeric(10,6),
    sharpe_ratio numeric(10,4),
    sortino_ratio numeric(10,4),
    calmar_ratio numeric(10,4),
    total_trades integer DEFAULT 0,
    winning_trades integer DEFAULT 0,
    losing_trades integer DEFAULT 0,
    win_rate numeric(5,2),
    avg_win numeric(20,8),
    avg_loss numeric(20,8),
    profit_factor numeric(10,4),
    current_exposure numeric(20,8),
    max_exposure numeric(20,8),
    exposure_pct numeric(5,2),
    risk_budget_pct numeric(5,2),
    capital_allocation numeric(20,8),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.strategy_portfolio IS 'Per-strategy performance and risk metrics';



CREATE TABLE public.strategy_signals (
    "time" timestamp with time zone DEFAULT now() NOT NULL,
    user_id uuid NOT NULL,
    strategy_id text NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    signal_type text NOT NULL,
    action text NOT NULL,
    confidence double precision NOT NULL,
    reasoning jsonb,
    features jsonb,
    risk_checks jsonb,
    order_intent jsonb,
    executed boolean DEFAULT false,
    execution_time timestamp with time zone,
    execution_result jsonb,
    CONSTRAINT strategy_signals_action_check CHECK ((action = ANY (ARRAY['buy'::text, 'sell'::text, 'hold'::text]))),
    CONSTRAINT strategy_signals_signal_type_check CHECK ((signal_type = ANY (ARRAY['entry'::text, 'exit'::text, 'adjust'::text, 'hold'::text])))
);



COMMENT ON TABLE public.strategy_signals IS 'Trading strategy signals and execution results';



CREATE TABLE public.strategy_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    slug character varying(64) NOT NULL,
    description text,
    strategy_family character varying(64) DEFAULT 'scalper'::character varying NOT NULL,
    timeframe character varying(16) DEFAULT '1m'::character varying,
    default_profile_bundle jsonb DEFAULT '{}'::jsonb NOT NULL,
    default_risk_config jsonb DEFAULT '{"maxLeverage": 1, "leverageMode": "isolated", "maxPositions": 4, "maxDailyLossPct": 0.05, "positionSizePct": 0.10, "maxTotalExposurePct": 0.40}'::jsonb,
    default_execution_config jsonb DEFAULT '{"stopLossPct": 0.02, "takeProfitPct": 0.05, "trailingStopPct": 0.01, "defaultOrderType": "market", "maxHoldTimeHours": 24, "trailingStopEnabled": false}'::jsonb,
    supported_exchanges text[] DEFAULT ARRAY['binance'::text, 'okx'::text, 'bybit'::text],
    recommended_symbols text[] DEFAULT ARRAY['BTC-USDT-SWAP'::text, 'ETH-USDT-SWAP'::text, 'SOL-USDT-SWAP'::text],
    version integer DEFAULT 1,
    is_system boolean DEFAULT false,
    is_active boolean DEFAULT true,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid
);



COMMENT ON TABLE public.strategy_templates IS 'Strategy templates define trading logic and default parameters';



COMMENT ON COLUMN public.strategy_templates.default_profile_bundle IS 'Chessboard profiles and indicator configurations';



COMMENT ON COLUMN public.strategy_templates.is_system IS 'System templates are read-only for regular users';



CREATE TABLE public.symbol_data_health (
    symbol character varying(50) NOT NULL,
    timeframe character varying(20) DEFAULT '1m'::character varying NOT NULL,
    health_status character varying(20) DEFAULT 'healthy'::character varying,
    quality_score numeric(5,2) DEFAULT 100.0,
    last_metric_time timestamp with time zone,
    last_candle_time timestamp with time zone,
    last_update_time timestamp with time zone,
    active_gaps_count integer DEFAULT 0,
    active_alerts_count integer DEFAULT 0,
    avg_latency_ms numeric(10,2),
    updated_at timestamp with time zone DEFAULT now()
);



COMMENT ON TABLE public.symbol_data_health IS 'Current health status per symbol';



CREATE TABLE public.symbol_locks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange_account_id uuid NOT NULL,
    environment character varying(16) NOT NULL,
    symbol character varying(64) NOT NULL,
    owner_bot_id uuid NOT NULL,
    acquired_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone,
    lease_heartbeat_at timestamp with time zone DEFAULT now(),
    last_conflict_bot_id uuid,
    last_conflict_at timestamp with time zone,
    conflict_count integer DEFAULT 0
);



COMMENT ON TABLE public.symbol_locks IS 'Symbol ownership locks for TEAM/PROP modes - prevents bot conflicts';



COMMENT ON COLUMN public.symbol_locks.lease_heartbeat_at IS 'Updated by running bot; expired leases can be reclaimed';



CREATE TABLE public.tenant_risk_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    max_daily_loss_pct numeric(10,4) DEFAULT 0.10,
    max_daily_loss_usd numeric(20,2),
    max_total_exposure_pct numeric(10,4) DEFAULT 1.00,
    max_single_position_pct numeric(10,4) DEFAULT 0.25,
    max_per_symbol_exposure_pct numeric(10,4) DEFAULT 0.50,
    max_leverage numeric(5,2) DEFAULT 10.00,
    allowed_leverage_levels integer[] DEFAULT ARRAY[1, 2, 3, 5, 10],
    max_concurrent_positions integer DEFAULT 10,
    max_concurrent_bots integer DEFAULT 1,
    max_symbols integer DEFAULT 20,
    total_capital_limit_usd numeric(20,2),
    min_reserve_pct numeric(10,4) DEFAULT 0.10,
    live_trading_enabled boolean DEFAULT false,
    allowed_environments text[] DEFAULT ARRAY['dev'::text, 'paper'::text],
    allowed_exchanges text[] DEFAULT ARRAY['binance'::text, 'okx'::text, 'bybit'::text],
    trading_hours_enabled boolean DEFAULT false,
    trading_start_time time without time zone,
    trading_end_time time without time zone,
    trading_days text[] DEFAULT ARRAY['mon'::text, 'tue'::text, 'wed'::text, 'thu'::text, 'fri'::text],
    timezone character varying(64) DEFAULT 'UTC'::character varying,
    circuit_breaker_enabled boolean DEFAULT true,
    circuit_breaker_loss_pct numeric(10,4) DEFAULT 0.05,
    circuit_breaker_cooldown_minutes integer DEFAULT 60,
    policy_version integer DEFAULT 1,
    notes text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_reviewed_at timestamp with time zone
);



COMMENT ON TABLE public.tenant_risk_policies IS 'Account-level risk limits that cap all bot configurations';



COMMENT ON COLUMN public.tenant_risk_policies.max_daily_loss_pct IS 'Global daily drawdown limit - bots cannot exceed this';



COMMENT ON COLUMN public.tenant_risk_policies.max_leverage IS 'Global leverage cap - per-bot leverage cannot exceed this';



COMMENT ON COLUMN public.tenant_risk_policies.live_trading_enabled IS 'User must explicitly enable live trading';



COMMENT ON COLUMN public.tenant_risk_policies.circuit_breaker_enabled IS 'Auto-pause trading after significant loss';



CREATE TABLE public.trade_costs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    trade_id text NOT NULL,
    symbol text NOT NULL,
    profile_id text,
    execution_price numeric NOT NULL,
    decision_mid_price numeric NOT NULL,
    slippage_bps numeric NOT NULL,
    fees numeric DEFAULT 0 NOT NULL,
    funding_cost numeric DEFAULT 0 NOT NULL,
    total_cost numeric NOT NULL,
    entry_fee_usd numeric,
    exit_fee_usd numeric,
    entry_fee_bps numeric,
    exit_fee_bps numeric,
    entry_slippage_bps numeric,
    exit_slippage_bps numeric,
    spread_cost_bps numeric,
    adverse_selection_bps numeric,
    total_cost_bps numeric,
    order_size numeric,
    side text,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT trade_costs_side_check CHECK ((side = ANY (ARRAY['long'::text, 'short'::text])))
);



COMMENT ON TABLE public.trade_costs IS 'Per-trade cost breakdown (slippage, fees, funding)';



CREATE TABLE public.trades (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    order_id uuid,
    user_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    side character varying(10) NOT NULL,
    quantity numeric(18,8) NOT NULL,
    price numeric(18,8) NOT NULL,
    fees numeric(18,8) DEFAULT 0 NOT NULL,
    pnl numeric(18,8) DEFAULT 0,
    pnl_percent numeric(5,2) DEFAULT 0,
    executed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    exchange character varying(20) DEFAULT 'binance'::character varying,
    exchange_trade_id character varying(100),
    exchange_account_id uuid,
    bot_id uuid,
    profile_id uuid,
    profile_version integer,
    trace_id uuid,
    CONSTRAINT trades_side_check CHECK (((side)::text = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::text[])))
);



CREATE TABLE public.trading_activity (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    type character varying(50) NOT NULL,
    token character varying(20),
    action character varying(20),
    confidence numeric(5,2),
    reasoning text,
    expected_outcome text,
    order_id uuid,
    position_id uuid,
    quantity numeric(18,8),
    price numeric(18,8),
    market_data jsonb,
    metadata jsonb,
    status character varying(50),
    result_message text
);



COMMENT ON TABLE public.trading_activity IS 'Stores all trading decisions, orders, and activity for audit trail and analysis';



CREATE TABLE public.trading_decisions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    token character varying(20) NOT NULL,
    decision jsonb NOT NULL,
    market_data jsonb NOT NULL,
    multi_timeframe jsonb,
    confidence numeric(5,4),
    action character varying(10) NOT NULL,
    executed boolean DEFAULT false,
    order_id uuid,
    reasoning text,
    factors jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    exchange_account_id uuid,
    bot_id uuid,
    trace_id uuid,
    CONSTRAINT trading_decisions_action_check CHECK (((action)::text = ANY ((ARRAY['buy'::character varying, 'sell'::character varying, 'hold'::character varying])::text[])))
);



CREATE TABLE public.user_chessboard_profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    name character varying(255) NOT NULL,
    description text,
    base_profile_id character varying(100),
    environment public.profile_environment DEFAULT 'dev'::public.profile_environment NOT NULL,
    strategy_composition jsonb DEFAULT '[]'::jsonb NOT NULL,
    risk_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    conditions jsonb DEFAULT '{}'::jsonb NOT NULL,
    lifecycle jsonb DEFAULT '{}'::jsonb NOT NULL,
    execution jsonb DEFAULT '{}'::jsonb NOT NULL,
    status public.profile_status DEFAULT 'draft'::public.profile_status NOT NULL,
    is_active boolean DEFAULT false,
    version integer DEFAULT 1 NOT NULL,
    promoted_from_id uuid,
    promoted_at timestamp with time zone,
    promotion_notes text,
    paper_start_at timestamp with time zone,
    paper_trades_count integer DEFAULT 0,
    paper_pnl_total numeric(20,8) DEFAULT 0,
    tags text[] DEFAULT ARRAY[]::text[],
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_system_template boolean DEFAULT false
);



COMMENT ON TABLE public.user_chessboard_profiles IS 'User-customizable trading profiles with strategy composition, risk controls, and market gates';



COMMENT ON COLUMN public.user_chessboard_profiles.user_id IS 'Owner of the profile. NULL for system templates (visible to all users)';



COMMENT ON COLUMN public.user_chessboard_profiles.environment IS 'Dev for testing, Paper for paper trading, Live for real trading';



COMMENT ON COLUMN public.user_chessboard_profiles.strategy_composition IS 'Array of strategy instances with weights and priorities';



COMMENT ON COLUMN public.user_chessboard_profiles.risk_config IS 'Risk management settings for this profile';



COMMENT ON COLUMN public.user_chessboard_profiles.conditions IS 'Market condition gates that must be met for profile to trade';



COMMENT ON COLUMN public.user_chessboard_profiles.lifecycle IS 'Trading lifecycle rules like cooldowns and loss limits';



COMMENT ON COLUMN public.user_chessboard_profiles.execution IS 'Order execution preferences';



COMMENT ON COLUMN public.user_chessboard_profiles.is_system_template IS 'System templates are read-only and available to all users as a starting point for creating custom profiles';



CREATE TABLE public.user_exchange_credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    exchange character varying(32) NOT NULL,
    label character varying(128),
    secret_id character varying(256) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying,
    last_verified_at timestamp with time zone,
    verification_error text,
    permissions jsonb DEFAULT '[]'::jsonb,
    is_demo boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    risk_config jsonb DEFAULT '{"maxLeverage": 1, "leverageMode": "isolated", "maxPositions": 4, "maxDailyLossPct": 0.05, "positionSizePct": 0.10, "maxTotalExposurePct": 0.80, "maxPositionsPerSymbol": 1, "maxDailyLossPerSymbolPct": 0.025}'::jsonb,
    execution_config jsonb DEFAULT '{"stopLossPct": 0.02, "takeProfitPct": 0.05, "trailingStopPct": 0.01, "defaultOrderType": "market", "maxHoldTimeHours": 24, "executionTimeoutSec": 5.0, "minTradeIntervalSec": 1.0, "trailingStopEnabled": false, "enableVolatilityFilter": true, "closePositionTimeoutSec": 15.0, "volatilityShockCooldownSec": 30.0}'::jsonb,
    ui_preferences jsonb DEFAULT '{"compactMode": false, "notifyOnTrade": true, "showPnlInHeader": true, "notifyOnStopLoss": true, "notifyOnTakeProfit": true, "defaultChartTimeframe": "1h"}'::jsonb,
    config_version integer DEFAULT 1,
    config_updated_at timestamp with time zone DEFAULT now(),
    exchange_balance numeric(20,8),
    balance_updated_at timestamp with time zone,
    account_connected boolean DEFAULT false,
    trading_capital numeric(20,8),
    balance_error text,
    balance_currency character varying(16) DEFAULT 'USDT'::character varying,
    connection_error text,
    CONSTRAINT valid_exchange CHECK (((exchange)::text = ANY ((ARRAY['okx'::character varying, 'binance'::character varying, 'bybit'::character varying])::text[])))
);



COMMENT ON TABLE public.user_exchange_credentials IS 'Per-user exchange API credential metadata (secrets stored externally)';



COMMENT ON COLUMN public.user_exchange_credentials.is_demo IS 'True if using exchange demo trading (Bybit api-demo, OKX simulated). Not available for Binance.';



COMMENT ON COLUMN public.user_exchange_credentials.risk_config IS 'Per-credential risk parameters: position sizing, leverage, loss limits';



COMMENT ON COLUMN public.user_exchange_credentials.execution_config IS 'Per-credential execution settings: SL/TP, timeouts, order types';



COMMENT ON COLUMN public.user_exchange_credentials.ui_preferences IS 'Per-credential UI preferences: notifications, display settings';



COMMENT ON COLUMN public.user_exchange_credentials.config_version IS 'Monotonically increasing version for config drift detection';



COMMENT ON COLUMN public.user_exchange_credentials.exchange_balance IS 'Actual balance fetched from the exchange account';



COMMENT ON COLUMN public.user_exchange_credentials.balance_updated_at IS 'Last successful balance fetch timestamp';



COMMENT ON COLUMN public.user_exchange_credentials.account_connected IS 'Whether we can successfully connect to the exchange';



COMMENT ON COLUMN public.user_exchange_credentials.trading_capital IS 'User-set capital for position sizing (must be <= exchange_balance)';



CREATE TABLE public.user_trade_profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    active_credential_id uuid,
    active_exchange character varying(32),
    trading_mode character varying(32) DEFAULT 'paper'::character varying,
    token_lists jsonb DEFAULT '{}'::jsonb,
    default_max_positions integer DEFAULT 4,
    default_position_size_pct numeric(10,4) DEFAULT 0.10,
    default_max_daily_loss_pct numeric(10,4) DEFAULT 0.05,
    assigned_bot_id character varying(128),
    bot_assigned_at timestamp with time zone,
    bot_status character varying(32),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    account_balance numeric(20,2) DEFAULT 10000.00,
    global_max_leverage integer DEFAULT 1,
    global_leverage_mode character varying(32) DEFAULT 'isolated'::character varying,
    active_config_snapshot jsonb,
    active_config_version integer,
    active_bot_exchange_config_id uuid
);



COMMENT ON TABLE public.user_trade_profiles IS 'User trading configuration including active exchange and token selection';



CREATE TABLE public.user_trading_settings (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    enabled_order_types text[] DEFAULT ARRAY['bracket'::text] NOT NULL,
    order_type_settings jsonb NOT NULL,
    risk_profile character varying(20) DEFAULT 'moderate'::character varying,
    max_concurrent_positions integer DEFAULT 4,
    max_position_size_percent numeric(10,4) DEFAULT 0.10,
    max_total_exposure_percent numeric(10,4) DEFAULT 0.40,
    ai_confidence_threshold numeric(3,1) DEFAULT 7.0,
    trading_interval integer DEFAULT 300000,
    enabled_tokens text[] DEFAULT ARRAY['SOLUSDT'::text],
    per_token_settings jsonb DEFAULT '{}'::jsonb,
    day_trading_enabled boolean DEFAULT false,
    scalping_mode boolean DEFAULT false,
    trailing_stops_enabled boolean DEFAULT true,
    partial_profits_enabled boolean DEFAULT true,
    time_based_exits_enabled boolean DEFAULT true,
    multi_timeframe_confirmation boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    day_trading_start_time time without time zone DEFAULT '09:30:00'::time without time zone,
    day_trading_end_time time without time zone DEFAULT '15:30:00'::time without time zone,
    day_trading_force_close_time time without time zone DEFAULT '15:45:00'::time without time zone,
    day_trading_days_only boolean DEFAULT false,
    leverage_enabled boolean DEFAULT false,
    max_leverage numeric(5,2) DEFAULT 1.0,
    leverage_mode character varying(20) DEFAULT 'isolated'::character varying,
    liquidation_buffer_percent numeric(10,4) DEFAULT 0.05,
    margin_call_threshold_percent numeric(10,4) DEFAULT 0.20,
    available_leverage_levels numeric(5,2)[] DEFAULT ARRAY[1.0, 2.0, 3.0, 5.0, 10.0],
    ai_filter_enabled boolean DEFAULT true,
    ai_filter_mode character varying(20) DEFAULT 'filter_only'::character varying,
    ai_swing_trading_enabled boolean DEFAULT false,
    strategy_selection character varying(50) DEFAULT 'amt_scalping'::character varying,
    day_trading_max_holding_hours numeric(10,2) DEFAULT 8.0,
    scalping_target_profit_percent numeric(10,4) DEFAULT 0.005,
    scalping_max_holding_minutes integer DEFAULT 15,
    scalping_min_volume_multiplier numeric(10,2) DEFAULT 2.0,
    trailing_stop_activation_percent numeric(10,4) DEFAULT 0.02,
    trailing_stop_callback_percent numeric(10,4) DEFAULT 0.01,
    trailing_stop_step_percent numeric(10,4) DEFAULT 0.005,
    partial_profit_levels jsonb DEFAULT '[{"target": 0.03, "percent": 25}, {"target": 0.05, "percent": 25}, {"target": 0.08, "percent": 25}, {"target": 0.12, "percent": 25}]'::jsonb,
    time_exit_max_holding_hours numeric(10,2) DEFAULT 24.0,
    time_exit_break_even_hours numeric(10,2) DEFAULT 4.0,
    time_exit_weekend_close boolean DEFAULT true,
    mtf_required_timeframes text[] DEFAULT ARRAY['15m'::text, '1h'::text, '4h'::text],
    mtf_min_confirmations integer DEFAULT 2,
    mtf_trend_alignment_required boolean DEFAULT true,
    CONSTRAINT user_trading_settings_leverage_mode_check CHECK (((leverage_mode)::text = ANY ((ARRAY['isolated'::character varying, 'cross'::character varying])::text[])))
);



COMMENT ON TABLE public.user_trading_settings IS 'User-configurable settings for AI trading behavior and order type preferences';



COMMENT ON COLUMN public.user_trading_settings.enabled_order_types IS 'Array of order types the AI is allowed to use';



COMMENT ON COLUMN public.user_trading_settings.order_type_settings IS 'Detailed settings for each order type';



COMMENT ON COLUMN public.user_trading_settings.risk_profile IS 'Overall risk profile: conservative, moderate, aggressive';



COMMENT ON COLUMN public.user_trading_settings.day_trading_start_time IS 'Time to start opening new positions (day trading mode)';



COMMENT ON COLUMN public.user_trading_settings.day_trading_end_time IS 'Time to stop opening new positions (day trading mode)';



COMMENT ON COLUMN public.user_trading_settings.day_trading_force_close_time IS 'Time to force close all positions (day trading mode)';



COMMENT ON COLUMN public.user_trading_settings.day_trading_days_only IS 'Only trade Monday-Friday (skip weekends)';



COMMENT ON COLUMN public.user_trading_settings.ai_filter_enabled IS 'Enable/disable AI regime analysis filter';



COMMENT ON COLUMN public.user_trading_settings.ai_filter_mode IS 'AI mode: filter_only (AI filters when to scalp) or full_control (AI makes all decisions)';



COMMENT ON COLUMN public.user_trading_settings.ai_swing_trading_enabled IS 'Enable AI-driven swing trading (future feature)';



COMMENT ON COLUMN public.user_trading_settings.strategy_selection IS 'Active strategy: amt_scalping, pure_technical, or ai_swing (future)';



COMMENT ON COLUMN public.user_trading_settings.day_trading_max_holding_hours IS 'Maximum hours to hold a position in day trading mode';



COMMENT ON COLUMN public.user_trading_settings.scalping_target_profit_percent IS 'Target profit percentage for scalping trades';



COMMENT ON COLUMN public.user_trading_settings.trailing_stop_activation_percent IS 'Profit % needed before trailing stop activates';



COMMENT ON COLUMN public.user_trading_settings.partial_profit_levels IS 'Array of profit taking levels with position % and target %';



COMMENT ON COLUMN public.user_trading_settings.time_exit_max_holding_hours IS 'Maximum hours to hold any position';



COMMENT ON COLUMN public.user_trading_settings.mtf_required_timeframes IS 'Timeframes required for multi-timeframe confirmation';



CREATE VIEW public.v_bot_paper_status AS
 SELECT bi.id AS bot_instance_id,
    bi.name AS bot_name,
    bi.trading_mode,
    bi.exchange_account_id,
    ea.venue AS exchange,
    ea.label AS exchange_label,
    pb.balance,
    pb.available_balance,
    pb.total_realized_pnl,
    pb.total_fees_paid,
    ( SELECT count(*) AS count
           FROM public.paper_positions pp
          WHERE ((pp.bot_instance_id = bi.id) AND ((pp.status)::text = 'open'::text))) AS open_positions,
    ( SELECT count(*) AS count
           FROM public.paper_orders po
          WHERE ((po.bot_instance_id = bi.id) AND ((po.status)::text = ANY ((ARRAY['pending'::character varying, 'open'::character varying])::text[])))) AS pending_orders,
    ( SELECT count(*) AS count
           FROM public.paper_trades pt
          WHERE (pt.bot_instance_id = bi.id)) AS total_trades
   FROM ((public.bot_instances bi
     LEFT JOIN public.exchange_accounts ea ON ((bi.exchange_account_id = ea.id)))
     LEFT JOIN public.paper_balances pb ON (((pb.bot_instance_id = bi.id) AND ((pb.currency)::text = 'USDT'::text))))
  WHERE (bi.deleted_at IS NULL);



COMMENT ON VIEW public.v_bot_paper_status IS 'View showing paper trading status for each bot instance';



CREATE TABLE public.var_calculations (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    calculation_type text NOT NULL,
    confidence_level numeric NOT NULL,
    time_horizon_days integer DEFAULT 1 NOT NULL,
    portfolio_id text,
    symbol text,
    profile_id text,
    var_value numeric NOT NULL,
    expected_shortfall numeric NOT NULL,
    var_pct numeric,
    es_pct numeric,
    sample_size integer,
    calculation_date date DEFAULT CURRENT_DATE NOT NULL,
    calculation_timestamp timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    method_params jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE public.wfo_runs (
    run_id uuid NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    profile_id text,
    symbol text,
    status text NOT NULL,
    config jsonb,
    results jsonb,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);



ALTER TABLE ONLY public.fast_scalper_positions ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_positions_id_seq'::regclass);



ALTER TABLE ONLY public.fast_scalper_trades ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_trades_id_seq'::regclass);



ALTER TABLE ONLY public.schema_migrations ALTER COLUMN id SET DEFAULT nextval('public.schema_migrations_id_seq'::regclass);



ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.audit_log_exports
    ADD CONSTRAINT audit_log_exports_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.backtest_decision_snapshots
    ADD CONSTRAINT backtest_decision_snapshots_pkey PRIMARY KEY (run_id, symbol, ts);



ALTER TABLE ONLY public.backtest_equity_curve
    ADD CONSTRAINT backtest_equity_curve_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.backtest_metrics
    ADD CONSTRAINT backtest_metrics_pkey PRIMARY KEY (run_id);



ALTER TABLE ONLY public.backtest_position_snapshots
    ADD CONSTRAINT backtest_position_snapshots_pkey PRIMARY KEY (run_id, ts);



ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_run_id_key UNIQUE (run_id);



ALTER TABLE ONLY public.backtest_symbol_equity_curve
    ADD CONSTRAINT backtest_symbol_equity_curve_pkey PRIMARY KEY (run_id, symbol, ts);



ALTER TABLE ONLY public.backtest_symbol_metrics
    ADD CONSTRAINT backtest_symbol_metrics_pkey PRIMARY KEY (run_id, symbol);



ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_bot_instance_id_exchange_account_id_key UNIQUE (bot_instance_id, exchange_account_id);



ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_config_actions
    ADD CONSTRAINT bot_config_actions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_bot_exchange_config_id_version_key UNIQUE (bot_exchange_config_id, version_number);



ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_logs
    ADD CONSTRAINT bot_logs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_pool_assignments
    ADD CONSTRAINT bot_pool_assignments_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_profile_versions
    ADD CONSTRAINT bot_profile_versions_bot_profile_id_version_number_key UNIQUE (bot_profile_id, version_number);



ALTER TABLE ONLY public.bot_profile_versions
    ADD CONSTRAINT bot_profile_versions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_profiles
    ADD CONSTRAINT bot_profiles_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_symbol_configs
    ADD CONSTRAINT bot_symbol_configs_bot_exchange_config_id_symbol_key UNIQUE (bot_exchange_config_id, symbol);



ALTER TABLE ONLY public.bot_symbol_configs
    ADD CONSTRAINT bot_symbol_configs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.bot_version_sections
    ADD CONSTRAINT bot_version_sections_bot_profile_version_id_section_key UNIQUE (bot_profile_version_id, section);



ALTER TABLE ONLY public.bot_version_sections
    ADD CONSTRAINT bot_version_sections_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.capacity_analysis
    ADD CONSTRAINT capacity_analysis_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.capacity_analysis
    ADD CONSTRAINT capacity_analysis_profile_id_notional_bucket_period_start_p_key UNIQUE (profile_id, notional_bucket, period_start, period_end);



ALTER TABLE ONLY public.component_var
    ADD CONSTRAINT component_var_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.config_audit_log
    ADD CONSTRAINT config_audit_log_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.config_diffs
    ADD CONSTRAINT config_diffs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.copilot_conversations
    ADD CONSTRAINT copilot_conversations_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.copilot_messages
    ADD CONSTRAINT copilot_messages_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.copilot_settings_snapshots
    ADD CONSTRAINT copilot_settings_snapshots_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.cost_aggregation
    ADD CONSTRAINT cost_aggregation_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.cost_aggregation
    ADD CONSTRAINT cost_aggregation_symbol_profile_id_period_type_period_start_key UNIQUE (symbol, profile_id, period_type, period_start);



ALTER TABLE ONLY public.credential_balance_history
    ADD CONSTRAINT credential_balance_history_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.credential_config_audit
    ADD CONSTRAINT credential_config_audit_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.data_quality_alerts
    ADD CONSTRAINT data_quality_alerts_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.data_quality_metrics
    ADD CONSTRAINT data_quality_metrics_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.data_quality_metrics
    ADD CONSTRAINT data_quality_metrics_symbol_timeframe_date_idx UNIQUE (symbol, timeframe, metric_date);



ALTER TABLE ONLY public.decision_traces
    ADD CONSTRAINT decision_traces_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_portfolio_id_timestamp_key UNIQUE (portfolio_id, "timestamp");



ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_tenant_id_venue_label_environment_key UNIQUE (tenant_id, venue, label, environment);



ALTER TABLE ONLY public.exchange_limits
    ADD CONSTRAINT exchange_limits_exchange_key UNIQUE (exchange);



ALTER TABLE ONLY public.exchange_limits
    ADD CONSTRAINT exchange_limits_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_exchange_account_id_key UNIQUE (exchange_account_id);



ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.exchange_token_catalog
    ADD CONSTRAINT exchange_token_catalog_exchange_symbol_key UNIQUE (exchange, symbol);



ALTER TABLE ONLY public.exchange_token_catalog
    ADD CONSTRAINT exchange_token_catalog_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.fast_scalper_positions
    ADD CONSTRAINT fast_scalper_positions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.fast_scalper_trades
    ADD CONSTRAINT fast_scalper_trades_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.feature_dictionary
    ADD CONSTRAINT feature_dictionary_pkey PRIMARY KEY (feature_name);



ALTER TABLE ONLY public.feed_gaps
    ADD CONSTRAINT feed_gaps_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.generated_reports
    ADD CONSTRAINT generated_reports_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.incident_affected_objects
    ADD CONSTRAINT incident_affected_objects_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.incident_events
    ADD CONSTRAINT incident_events_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_balances
    ADD CONSTRAINT paper_balances_bot_instance_currency_unique UNIQUE (bot_instance_id, currency);



ALTER TABLE ONLY public.paper_balances
    ADD CONSTRAINT paper_balances_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_orders
    ADD CONSTRAINT paper_orders_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_performance_snapshots
    ADD CONSTRAINT paper_performance_snapshots_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_position_alerts
    ADD CONSTRAINT paper_position_alerts_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_position_history
    ADD CONSTRAINT paper_position_history_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_position_tags
    ADD CONSTRAINT paper_position_tags_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_positions
    ADD CONSTRAINT paper_positions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.paper_trades
    ADD CONSTRAINT paper_trades_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.portfolio_summary
    ADD CONSTRAINT portfolio_summary_date_unique UNIQUE (calculation_date);



ALTER TABLE ONLY public.portfolio_summary
    ADD CONSTRAINT portfolio_summary_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.portfolios
    ADD CONSTRAINT portfolios_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.position_impacts
    ADD CONSTRAINT position_impacts_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.position_updates
    ADD CONSTRAINT position_updates_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_profile_id_version_key UNIQUE (profile_id, version);



ALTER TABLE ONLY public.promotion_history
    ADD CONSTRAINT promotion_history_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.replay_annotations
    ADD CONSTRAINT replay_annotations_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.replay_sessions
    ADD CONSTRAINT replay_sessions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.replay_snapshots
    ADD CONSTRAINT replay_snapshots_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.replay_snapshots
    ADD CONSTRAINT replay_snapshots_symbol_timestamp_idx UNIQUE (symbol, "timestamp");



ALTER TABLE ONLY public.report_templates
    ADD CONSTRAINT report_templates_name_unique UNIQUE (name);



ALTER TABLE ONLY public.report_templates
    ADD CONSTRAINT report_templates_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.retention_policies
    ADD CONSTRAINT retention_policies_log_type_action_category_key UNIQUE (log_type, action_category);



ALTER TABLE ONLY public.retention_policies
    ADD CONSTRAINT retention_policies_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.risk_metrics_aggregation
    ADD CONSTRAINT risk_metrics_aggregation_period_type_period_start_portfolio_key UNIQUE (period_type, period_start, portfolio_id, symbol, profile_id);



ALTER TABLE ONLY public.risk_metrics_aggregation
    ADD CONSTRAINT risk_metrics_aggregation_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.scenario_results
    ADD CONSTRAINT scenario_results_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_filename_key UNIQUE (filename);



ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.strategy_correlation
    ADD CONSTRAINT strategy_correlation_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.strategy_correlation
    ADD CONSTRAINT strategy_correlation_unique UNIQUE (strategy_a, strategy_b, calculation_date);



ALTER TABLE ONLY public.strategy_instances
    ADD CONSTRAINT strategy_instances_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.strategy_portfolio
    ADD CONSTRAINT strategy_portfolio_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.strategy_portfolio
    ADD CONSTRAINT strategy_portfolio_strategy_date_unique UNIQUE (strategy_name, calculation_date);



ALTER TABLE ONLY public.strategy_templates
    ADD CONSTRAINT strategy_templates_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.strategy_templates
    ADD CONSTRAINT strategy_templates_slug_key UNIQUE (slug);



ALTER TABLE ONLY public.symbol_data_health
    ADD CONSTRAINT symbol_data_health_pkey PRIMARY KEY (symbol);



ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_exchange_account_id_environment_symbol_key UNIQUE (exchange_account_id, environment, symbol);



ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.tenant_risk_policies
    ADD CONSTRAINT tenant_risk_policies_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.tenant_risk_policies
    ADD CONSTRAINT tenant_risk_policies_user_id_key UNIQUE (user_id);



ALTER TABLE ONLY public.trade_costs
    ADD CONSTRAINT trade_costs_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.user_exchange_credentials
    ADD CONSTRAINT user_exchange_credentials_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.user_exchange_credentials
    ADD CONSTRAINT user_exchange_credentials_user_id_exchange_label_key UNIQUE (user_id, exchange, label);



ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_user_id_key UNIQUE (user_id);



ALTER TABLE ONLY public.user_trading_settings
    ADD CONSTRAINT user_trading_settings_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.user_trading_settings
    ADD CONSTRAINT user_trading_settings_user_id_key UNIQUE (user_id);



ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);



ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.var_calculations
    ADD CONSTRAINT var_calculations_pkey PRIMARY KEY (id);



ALTER TABLE ONLY public.wfo_runs
    ADD CONSTRAINT wfo_runs_pkey PRIMARY KEY (run_id);



CREATE INDEX amt_metrics_time_idx ON public.amt_metrics USING btree ("time" DESC);



CREATE INDEX backtest_decision_snapshots_run_id_ts_idx ON public.backtest_decision_snapshots USING btree (run_id, ts DESC);



CREATE INDEX backtest_equity_curve_run_id_idx ON public.backtest_equity_curve USING btree (run_id);



CREATE INDEX backtest_equity_curve_ts_idx ON public.backtest_equity_curve USING btree (ts DESC);



CREATE INDEX backtest_metrics_run_id_idx ON public.backtest_metrics USING btree (run_id);



CREATE INDEX backtest_position_snapshots_run_id_ts_idx ON public.backtest_position_snapshots USING btree (run_id, ts DESC);



CREATE INDEX backtest_runs_symbol_idx ON public.backtest_runs USING btree (symbol);



CREATE INDEX backtest_runs_tenant_bot_idx ON public.backtest_runs USING btree (tenant_id, bot_id);



CREATE INDEX backtest_runs_tenant_status_idx ON public.backtest_runs USING btree (tenant_id, status);



CREATE INDEX backtest_symbol_equity_curve_run_id_symbol_idx ON public.backtest_symbol_equity_curve USING btree (run_id, symbol, ts DESC);



CREATE INDEX backtest_symbol_metrics_run_id_symbol_idx ON public.backtest_symbol_metrics USING btree (run_id, symbol);



CREATE INDEX backtest_trades_run_id_idx ON public.backtest_trades USING btree (run_id);



CREATE INDEX backtest_trades_ts_idx ON public.backtest_trades USING btree (ts DESC);



CREATE INDEX idx_alerts_user_unread ON public.alerts USING btree (user_id, is_read) WHERE (is_read = false);



CREATE INDEX idx_amt_symbol_timeframe_time ON public.amt_metrics USING btree (symbol, timeframe, "time" DESC);



CREATE INDEX idx_approvals_promotion ON public.approvals USING btree (promotion_id);



CREATE INDEX idx_approvals_requested_at ON public.approvals USING btree (requested_at DESC);



CREATE INDEX idx_approvals_requested_by ON public.approvals USING btree (requested_by);



CREATE INDEX idx_approvals_risk_level ON public.approvals USING btree (risk_level);



CREATE INDEX idx_approvals_status ON public.approvals USING btree (status);



CREATE INDEX idx_audit_log_action ON public.config_audit_log USING btree (action);



CREATE INDEX idx_audit_log_action_category ON public.audit_log USING btree (action_category);



CREATE INDEX idx_audit_log_action_type ON public.audit_log USING btree (action_type);



CREATE INDEX idx_audit_log_created_at ON public.audit_log USING btree (created_at DESC);



CREATE INDEX idx_audit_log_env ON public.config_audit_log USING btree (environment);



CREATE INDEX idx_audit_log_exports_created_at ON public.audit_log_exports USING btree (created_at DESC);



CREATE INDEX idx_audit_log_exports_status ON public.audit_log_exports USING btree (export_status);



CREATE INDEX idx_audit_log_exports_user_id ON public.audit_log_exports USING btree (user_id);



CREATE INDEX idx_audit_log_resource ON public.config_audit_log USING btree (resource_type, resource_id);



CREATE INDEX idx_audit_log_resource_id ON public.audit_log USING btree (resource_id);



CREATE INDEX idx_audit_log_resource_type ON public.audit_log USING btree (resource_type);



CREATE INDEX idx_audit_log_severity ON public.audit_log USING btree (severity);



CREATE INDEX idx_audit_log_time ON public.config_audit_log USING btree (created_at DESC);



CREATE INDEX idx_audit_log_user ON public.config_audit_log USING btree (user_id);



CREATE INDEX idx_audit_log_user_id ON public.audit_log USING btree (user_id);



CREATE INDEX idx_backtest_equity_curve_run_id ON public.backtest_equity_curve USING btree (backtest_run_id);



CREATE INDEX idx_backtest_equity_curve_timestamp ON public.backtest_equity_curve USING btree ("timestamp");



CREATE INDEX idx_backtest_runs_created_at ON public.backtest_runs USING btree (created_at DESC);
CREATE INDEX idx_backtest_runs_started_at ON public.backtest_runs USING btree (started_at DESC);



CREATE INDEX idx_backtest_runs_status ON public.backtest_runs USING btree (status);



CREATE INDEX idx_backtest_runs_strategy_id ON public.backtest_runs USING btree (strategy_id);



CREATE INDEX idx_backtest_runs_user_id ON public.backtest_runs USING btree (user_id);



CREATE INDEX idx_backtest_trades_entry_time ON public.backtest_trades USING btree (entry_time);



CREATE INDEX idx_backtest_trades_run_id ON public.backtest_trades USING btree (backtest_run_id);



CREATE INDEX idx_balance_history_credential ON public.credential_balance_history USING btree (credential_id, created_at DESC);



CREATE INDEX idx_balance_history_user ON public.credential_balance_history USING btree (user_id, created_at DESC);



CREATE INDEX idx_bot_assignments_bot_id ON public.bot_pool_assignments USING btree (bot_id);



CREATE INDEX idx_bot_assignments_status ON public.bot_pool_assignments USING btree (status);



CREATE INDEX idx_bot_assignments_user ON public.bot_pool_assignments USING btree (user_id);



CREATE INDEX idx_bot_budgets_account ON public.bot_budgets USING btree (exchange_account_id);



CREATE INDEX idx_bot_budgets_bot ON public.bot_budgets USING btree (bot_instance_id);



CREATE INDEX idx_bot_commands_bot_instance ON public.bot_commands USING btree (bot_instance_id);



CREATE INDEX idx_bot_commands_created ON public.bot_commands USING btree (created_at DESC);



CREATE INDEX idx_bot_commands_priority ON public.bot_commands USING btree (priority DESC, created_at) WHERE (status = 'pending'::public.bot_command_status);



CREATE INDEX idx_bot_commands_status ON public.bot_commands USING btree (status) WHERE (status = ANY (ARRAY['pending'::public.bot_command_status, 'processing'::public.bot_command_status]));



CREATE INDEX idx_bot_commands_user ON public.bot_commands USING btree (user_id);



CREATE INDEX idx_bot_config_actions_action ON public.bot_config_actions USING btree (action);



CREATE INDEX idx_bot_config_actions_profile ON public.bot_config_actions USING btree (bot_profile_id);



CREATE INDEX idx_bot_exchange_configs_active ON public.bot_exchange_configs USING btree (is_active) WHERE (is_active = true);



CREATE INDEX idx_bot_exchange_configs_bot ON public.bot_exchange_configs USING btree (bot_instance_id);



CREATE INDEX idx_bot_exchange_configs_credential ON public.bot_exchange_configs USING btree (credential_id);



CREATE INDEX idx_bot_exchange_configs_deleted ON public.bot_exchange_configs USING btree (deleted_at) WHERE (deleted_at IS NOT NULL);



CREATE INDEX idx_bot_exchange_configs_env ON public.bot_exchange_configs USING btree (environment);



CREATE INDEX idx_bot_exchange_configs_exchange_account ON public.bot_exchange_configs USING btree (exchange_account_id);



CREATE INDEX idx_bot_exchange_configs_mounted_profile ON public.bot_exchange_configs USING btree (mounted_profile_id) WHERE (mounted_profile_id IS NOT NULL);



CREATE INDEX idx_bot_exchange_configs_state ON public.bot_exchange_configs USING btree (state);



CREATE UNIQUE INDEX idx_bot_exchange_configs_unique_combo ON public.bot_exchange_configs USING btree (bot_instance_id, COALESCE(exchange_account_id, credential_id), environment);



CREATE INDEX idx_bot_instances_active ON public.bot_instances USING btree (user_id, is_active);



CREATE INDEX idx_bot_instances_deleted ON public.bot_instances USING btree (deleted_at) WHERE (deleted_at IS NOT NULL);



CREATE INDEX idx_bot_instances_exchange ON public.bot_instances USING btree (exchange_account_id);



CREATE INDEX idx_bot_instances_market_type ON public.bot_instances USING btree (market_type);



CREATE INDEX idx_bot_instances_role ON public.bot_instances USING btree (allocator_role);



CREATE INDEX idx_bot_instances_running ON public.bot_instances USING btree (exchange_account_id) WHERE ((runtime_state)::text = 'running'::text);



CREATE INDEX idx_bot_instances_state ON public.bot_instances USING btree (exchange_account_id, runtime_state);



CREATE INDEX idx_bot_instances_template ON public.bot_instances USING btree (strategy_template_id);



CREATE UNIQUE INDEX idx_bot_instances_unique_name ON public.bot_instances USING btree (user_id, name) WHERE (deleted_at IS NULL);



COMMENT ON INDEX public.idx_bot_instances_unique_name IS 'Ensures unique bot names per user, excluding soft-deleted bots';



CREATE INDEX idx_bot_instances_user ON public.bot_instances USING btree (user_id);



CREATE INDEX idx_bot_logs_bot_created ON public.bot_logs USING btree (bot_instance_id, created_at DESC);



CREATE INDEX idx_bot_logs_bot_instance ON public.bot_logs USING btree (bot_instance_id);



CREATE INDEX idx_bot_logs_category ON public.bot_logs USING btree (category);



CREATE INDEX idx_bot_logs_created_at ON public.bot_logs USING btree (created_at DESC);



CREATE INDEX idx_bot_logs_errors ON public.bot_logs USING btree (bot_instance_id, level) WHERE (level = ANY (ARRAY['error'::public.bot_log_level, 'fatal'::public.bot_log_level]));



CREATE INDEX idx_bot_logs_expires ON public.bot_logs USING btree (expires_at);



CREATE INDEX idx_bot_logs_level ON public.bot_logs USING btree (level);



CREATE INDEX idx_bot_logs_recent_errors ON public.bot_logs USING btree (bot_instance_id, created_at DESC) WHERE (level = ANY (ARRAY['error'::public.bot_log_level, 'fatal'::public.bot_log_level]));



CREATE INDEX idx_bot_logs_user ON public.bot_logs USING btree (user_id);



CREATE INDEX idx_bot_profile_versions_profile ON public.bot_profile_versions USING btree (bot_profile_id);



CREATE INDEX idx_bot_profile_versions_status ON public.bot_profile_versions USING btree (status);



CREATE INDEX idx_bot_profiles_environment ON public.bot_profiles USING btree (environment);



CREATE INDEX idx_bot_profiles_status ON public.bot_profiles USING btree (status);



CREATE INDEX idx_bot_symbol_configs_enabled ON public.bot_symbol_configs USING btree (bot_exchange_config_id, enabled) WHERE (enabled = true);



CREATE INDEX idx_bot_symbol_configs_parent ON public.bot_symbol_configs USING btree (bot_exchange_config_id);



CREATE INDEX idx_bot_symbol_configs_symbol ON public.bot_symbol_configs USING btree (symbol);



CREATE INDEX idx_candles_exchange ON public.market_candles USING btree (exchange);



CREATE INDEX idx_candles_symbol_timeframe_time ON public.market_candles USING btree (symbol, timeframe, "time" DESC);



CREATE INDEX idx_capacity_analysis_period ON public.capacity_analysis USING btree (period_start, period_end);



CREATE INDEX idx_capacity_analysis_profile ON public.capacity_analysis USING btree (profile_id);



CREATE INDEX idx_component_var_calc ON public.component_var USING btree (calculated_at DESC);



CREATE INDEX idx_component_var_symbol ON public.component_var USING btree (symbol);



CREATE INDEX idx_config_audit_created ON public.credential_config_audit USING btree (created_at DESC);



CREATE INDEX idx_config_audit_credential ON public.credential_config_audit USING btree (credential_id);



CREATE INDEX idx_config_audit_user ON public.credential_config_audit USING btree (user_id);



CREATE INDEX idx_config_diffs_promotion ON public.config_diffs USING btree (promotion_id);



CREATE INDEX idx_config_diffs_source ON public.config_diffs USING btree (source_config_id);



CREATE INDEX idx_config_diffs_target ON public.config_diffs USING btree (target_config_id);



CREATE INDEX idx_config_versions_created ON public.bot_exchange_config_versions USING btree (created_at DESC);



CREATE INDEX idx_config_versions_parent ON public.bot_exchange_config_versions USING btree (bot_exchange_config_id);



CREATE INDEX idx_copilot_conversations_user ON public.copilot_conversations USING btree (user_id, updated_at DESC);



CREATE INDEX idx_copilot_messages_conversation ON public.copilot_messages USING btree (conversation_id, "timestamp");



CREATE INDEX idx_copilot_messages_search ON public.copilot_messages USING gin (to_tsvector('english'::regconfig, content));



CREATE INDEX idx_copilot_settings_snapshots_user ON public.copilot_settings_snapshots USING btree (user_id, version DESC);



CREATE INDEX idx_cost_aggregation_period ON public.cost_aggregation USING btree (period_type, period_start);



CREATE INDEX idx_cost_aggregation_profile ON public.cost_aggregation USING btree (profile_id);



CREATE INDEX idx_cost_aggregation_symbol ON public.cost_aggregation USING btree (symbol);



CREATE INDEX idx_data_quality_alerts_detected ON public.data_quality_alerts USING btree (detected_at DESC);



CREATE INDEX idx_data_quality_alerts_severity ON public.data_quality_alerts USING btree (severity);



CREATE INDEX idx_data_quality_alerts_status ON public.data_quality_alerts USING btree (status);



CREATE INDEX idx_data_quality_alerts_symbol ON public.data_quality_alerts USING btree (symbol);



CREATE INDEX idx_data_quality_alerts_type ON public.data_quality_alerts USING btree (alert_type);



CREATE INDEX idx_data_quality_score ON public.data_quality_metrics USING btree (quality_score);



CREATE INDEX idx_data_quality_status ON public.data_quality_metrics USING btree (status);



CREATE INDEX idx_data_quality_symbol_date ON public.data_quality_metrics USING btree (symbol, metric_date DESC);



CREATE INDEX idx_decision_traces_bot ON public.decision_traces USING btree (bot_id, "timestamp");



CREATE INDEX idx_decision_traces_decision_type ON public.decision_traces USING btree (decision_type);



CREATE INDEX idx_decision_traces_outcome ON public.decision_traces USING btree (decision_outcome);



CREATE INDEX idx_decision_traces_symbol ON public.decision_traces USING btree (symbol);



CREATE INDEX idx_decision_traces_symbol_time ON public.decision_traces USING btree (symbol, "timestamp");



CREATE INDEX idx_decision_traces_timestamp ON public.decision_traces USING btree ("timestamp" DESC);



CREATE INDEX idx_decision_traces_trade_id ON public.decision_traces USING btree (trade_id);



CREATE INDEX idx_equity_curves_portfolio_id ON public.equity_curves USING btree (portfolio_id);



CREATE INDEX idx_equity_curves_portfolio_timestamp ON public.equity_curves USING btree (portfolio_id, "timestamp" DESC);



CREATE INDEX idx_equity_curves_timestamp ON public.equity_curves USING btree ("timestamp" DESC);



CREATE INDEX idx_equity_curves_user_id ON public.equity_curves USING btree (user_id);



CREATE INDEX idx_equity_curves_user_portfolio_timestamp ON public.equity_curves USING btree (user_id, portfolio_id, "timestamp" DESC);



CREATE INDEX idx_exchange_accounts_status ON public.exchange_accounts USING btree (tenant_id, status);



CREATE INDEX idx_exchange_accounts_tenant ON public.exchange_accounts USING btree (tenant_id);



CREATE INDEX idx_exchange_accounts_venue ON public.exchange_accounts USING btree (venue);



CREATE INDEX idx_exchange_creds_connected ON public.user_exchange_credentials USING btree (user_id, account_connected) WHERE (account_connected = true);



CREATE INDEX idx_exchange_creds_status ON public.user_exchange_credentials USING btree (status);



CREATE INDEX idx_exchange_creds_user ON public.user_exchange_credentials USING btree (user_id);



CREATE INDEX idx_exchange_policies_account ON public.exchange_policies USING btree (exchange_account_id);



CREATE INDEX idx_fast_scalper_positions_bot_id ON public.fast_scalper_positions USING btree (bot_id) WHERE (bot_id IS NOT NULL);



CREATE UNIQUE INDEX idx_fast_scalper_positions_unique_open ON public.fast_scalper_positions USING btree (user_id, symbol) WHERE (status = 'open'::text);



CREATE INDEX idx_fast_scalper_positions_user_symbol ON public.fast_scalper_positions USING btree (user_id, symbol, status);



CREATE INDEX idx_fast_scalper_trades_bot_id ON public.fast_scalper_trades USING btree (bot_id) WHERE (bot_id IS NOT NULL);



CREATE INDEX idx_fast_scalper_trades_symbol ON public.fast_scalper_trades USING btree (symbol, exit_time DESC);



CREATE INDEX idx_fast_scalper_trades_user_bot ON public.fast_scalper_trades USING btree (user_id, bot_id, exit_time DESC);



CREATE INDEX idx_fast_scalper_trades_user_time ON public.fast_scalper_trades USING btree (user_id, exit_time DESC);



CREATE INDEX idx_feed_gaps_resolved ON public.feed_gaps USING btree (resolved_at);



CREATE INDEX idx_feed_gaps_severity ON public.feed_gaps USING btree (severity);



CREATE INDEX idx_feed_gaps_symbol ON public.feed_gaps USING btree (symbol);



CREATE INDEX idx_feed_gaps_time_range ON public.feed_gaps USING btree (gap_start_time, gap_end_time);



CREATE INDEX idx_feed_gaps_timeframe ON public.feed_gaps USING btree (timeframe);



CREATE INDEX idx_generated_reports_generated ON public.generated_reports USING btree (generated_at DESC);



CREATE INDEX idx_generated_reports_period ON public.generated_reports USING btree (period_start, period_end);



CREATE INDEX idx_generated_reports_status ON public.generated_reports USING btree (status);



CREATE INDEX idx_generated_reports_template ON public.generated_reports USING btree (template_id);



CREATE INDEX idx_generated_reports_type ON public.generated_reports USING btree (report_type);



CREATE INDEX idx_incident_affected_incident_id ON public.incident_affected_objects USING btree (incident_id);



CREATE INDEX idx_incident_affected_object_type ON public.incident_affected_objects USING btree (object_type);



CREATE INDEX idx_incident_affected_symbol ON public.incident_affected_objects USING btree (symbol);



CREATE INDEX idx_incident_events_created_at ON public.incident_events USING btree (incident_id, created_at DESC);



CREATE INDEX idx_incident_events_incident_id ON public.incident_events USING btree (incident_id);



CREATE INDEX idx_incident_events_type ON public.incident_events USING btree (event_type);



CREATE INDEX idx_incidents_action_taken ON public.incidents USING btree (action_taken);



CREATE INDEX idx_incidents_bot_id ON public.incidents USING btree (bot_id);



CREATE INDEX idx_incidents_detected_at ON public.incidents USING btree (detected_at DESC);



CREATE INDEX idx_incidents_exchange_account ON public.incidents USING btree (exchange_account_id);



CREATE INDEX idx_incidents_owner ON public.incidents USING btree (owner_id);



CREATE INDEX idx_incidents_severity ON public.incidents USING btree (severity);



CREATE INDEX idx_incidents_status ON public.incidents USING btree (status);



CREATE INDEX idx_incidents_time_range ON public.incidents USING btree (start_time, end_time);



CREATE INDEX idx_incidents_trigger_rule ON public.incidents USING btree (trigger_rule);



CREATE INDEX idx_incidents_type ON public.incidents USING btree (incident_type);



CREATE INDEX idx_market_trades_exchange ON public.market_trades USING btree (exchange);



CREATE INDEX idx_market_trades_symbol_time ON public.market_trades USING btree (symbol, "time" DESC);



CREATE INDEX idx_market_trades_trade_id ON public.market_trades USING btree (trade_id);



CREATE INDEX idx_microstructure_symbol_time ON public.microstructure_features USING btree (symbol, "time" DESC);



CREATE INDEX idx_order_book_exchange ON public.order_book_snapshots USING btree (exchange);



CREATE INDEX idx_order_book_symbol_time ON public.order_book_snapshots USING btree (symbol, "time" DESC);



CREATE INDEX idx_orders_bot ON public.orders USING btree (bot_id);



CREATE INDEX idx_orders_created_at ON public.orders USING btree (created_at);



CREATE INDEX idx_orders_exchange_account ON public.orders USING btree (exchange_account_id);



CREATE INDEX idx_orders_portfolio_id ON public.orders USING btree (portfolio_id);



CREATE INDEX idx_orders_symbol_status ON public.orders USING btree (symbol, status);



CREATE INDEX idx_orders_trace ON public.orders USING btree (trace_id);



CREATE INDEX idx_orders_user_status ON public.orders USING btree (user_id, status);



CREATE INDEX idx_paper_balances_bot_instance_id ON public.paper_balances USING btree (bot_instance_id);



CREATE INDEX idx_paper_balances_exchange_account_id ON public.paper_balances USING btree (exchange_account_id);



CREATE INDEX idx_paper_orders_bot_instance_id ON public.paper_orders USING btree (bot_instance_id);



CREATE INDEX idx_paper_orders_bot_instance_status ON public.paper_orders USING btree (bot_instance_id, status);



CREATE INDEX idx_paper_orders_exchange_account_id ON public.paper_orders USING btree (exchange_account_id);



CREATE INDEX idx_paper_orders_simulated_at ON public.paper_orders USING btree (simulated_at DESC);



CREATE INDEX idx_paper_orders_status ON public.paper_orders USING btree (status);



CREATE INDEX idx_paper_orders_symbol ON public.paper_orders USING btree (symbol);



CREATE INDEX idx_paper_orders_user_id ON public.paper_orders USING btree (user_id);



CREATE INDEX idx_paper_performance_bot_instance ON public.paper_performance_snapshots USING btree (bot_instance_id, snapshot_date DESC);



CREATE INDEX idx_paper_performance_snapshots_date ON public.paper_performance_snapshots USING btree (exchange_account_id, snapshot_date DESC);



CREATE UNIQUE INDEX idx_paper_performance_unique ON public.paper_performance_snapshots USING btree (COALESCE(bot_instance_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(exchange_account_id, '00000000-0000-0000-0000-000000000000'::uuid), snapshot_date);



CREATE INDEX idx_paper_position_alerts_account ON public.paper_position_alerts USING btree (exchange_account_id);



CREATE INDEX idx_paper_position_alerts_active ON public.paper_position_alerts USING btree (position_id, is_triggered) WHERE (is_triggered = false);



CREATE INDEX idx_paper_position_alerts_bot ON public.paper_position_alerts USING btree (bot_instance_id);



CREATE INDEX idx_paper_position_history_bot ON public.paper_position_history USING btree (bot_instance_id, recorded_at DESC);



CREATE INDEX idx_paper_position_history_position_id ON public.paper_position_history USING btree (position_id, recorded_at DESC);



CREATE UNIQUE INDEX idx_paper_position_tags_unique ON public.paper_position_tags USING btree (COALESCE(bot_instance_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(exchange_account_id, '00000000-0000-0000-0000-000000000000'::uuid), tag_name);



CREATE INDEX idx_paper_positions_bot_instance_id ON public.paper_positions USING btree (bot_instance_id);



CREATE INDEX idx_paper_positions_bot_instance_status ON public.paper_positions USING btree (bot_instance_id, status) WHERE ((status)::text = 'open'::text);



CREATE INDEX idx_paper_positions_exchange_account_id ON public.paper_positions USING btree (exchange_account_id);



CREATE INDEX idx_paper_positions_open ON public.paper_positions USING btree (exchange_account_id, status) WHERE ((status)::text = 'open'::text);



CREATE INDEX idx_paper_positions_profile ON public.paper_positions USING btree (profile_id) WHERE (profile_id IS NOT NULL);



CREATE INDEX idx_paper_positions_status ON public.paper_positions USING btree (status);



CREATE INDEX idx_paper_positions_strategy ON public.paper_positions USING btree (strategy_id) WHERE (strategy_id IS NOT NULL);



CREATE INDEX idx_paper_positions_symbol ON public.paper_positions USING btree (symbol);



CREATE INDEX idx_paper_positions_updated_at ON public.paper_positions USING btree (updated_at DESC);



CREATE INDEX idx_paper_positions_user_id ON public.paper_positions USING btree (user_id);



CREATE INDEX idx_paper_trades_bot_instance ON public.paper_trades USING btree (bot_instance_id, executed_at DESC);



CREATE INDEX idx_paper_trades_bot_instance_id ON public.paper_trades USING btree (bot_instance_id);



CREATE INDEX idx_paper_trades_exchange_account_id ON public.paper_trades USING btree (exchange_account_id);



CREATE INDEX idx_paper_trades_executed_at ON public.paper_trades USING btree (executed_at DESC);



CREATE INDEX idx_paper_trades_mae_mfe ON public.paper_trades USING btree (exchange_account_id, executed_at DESC) WHERE ((mae IS NOT NULL) OR (mfe IS NOT NULL));



CREATE INDEX idx_paper_trades_symbol ON public.paper_trades USING btree (symbol);



CREATE INDEX idx_paper_trades_user_id ON public.paper_trades USING btree (user_id);



CREATE INDEX idx_portfolio_summary_date ON public.portfolio_summary USING btree (calculation_date DESC);



CREATE INDEX idx_portfolios_user_id ON public.portfolios USING btree (user_id);



CREATE INDEX idx_position_impacts_scenario ON public.position_impacts USING btree (scenario_id);



CREATE INDEX idx_position_impacts_symbol ON public.position_impacts USING btree (symbol);



CREATE INDEX idx_position_updates_position_id ON public.position_updates USING btree (position_id);



CREATE INDEX idx_position_updates_timestamp ON public.position_updates USING btree ("timestamp");



CREATE INDEX idx_positions_bot ON public.positions USING btree (bot_id);



CREATE INDEX idx_positions_exchange_account ON public.positions USING btree (exchange_account_id);



CREATE INDEX idx_positions_leverage ON public.positions USING btree (leverage);



CREATE INDEX idx_positions_liquidation_price ON public.positions USING btree (liquidation_price);



CREATE INDEX idx_positions_margin_ratio ON public.positions USING btree (margin_ratio);



CREATE INDEX idx_positions_opened_at ON public.positions USING btree (opened_at);



CREATE INDEX idx_positions_portfolio_status ON public.positions USING btree (portfolio_id, status);



CREATE INDEX idx_positions_symbol_status ON public.positions USING btree (symbol, status);



CREATE INDEX idx_positions_user_status ON public.positions USING btree (user_id, status);



CREATE INDEX idx_profile_versions_profile ON public.profile_versions USING btree (profile_id);



CREATE INDEX idx_profile_versions_profile_version ON public.profile_versions USING btree (profile_id, version);



CREATE INDEX idx_profiles_system_template ON public.user_chessboard_profiles USING btree (is_system_template) WHERE (is_system_template = true);



CREATE UNIQUE INDEX idx_profiles_system_template_unique ON public.user_chessboard_profiles USING btree (name, environment) WHERE ((is_system_template = true) AND (user_id IS NULL));



CREATE UNIQUE INDEX idx_profiles_user_name_env_unique ON public.user_chessboard_profiles USING btree (user_id, name, environment) WHERE (user_id IS NOT NULL);



CREATE INDEX idx_promotion_history_created_at ON public.promotion_history USING btree (created_at DESC);



CREATE INDEX idx_promotion_history_event_type ON public.promotion_history USING btree (event_type);



CREATE INDEX idx_promotion_history_promotion ON public.promotion_history USING btree (promotion_id);



CREATE INDEX idx_promotions_bot_profile ON public.promotions USING btree (bot_profile_id);



CREATE INDEX idx_promotions_requested_at ON public.promotions USING btree (requested_at DESC);



CREATE INDEX idx_promotions_requested_by ON public.promotions USING btree (requested_by);



CREATE INDEX idx_promotions_status ON public.promotions USING btree (status);



CREATE INDEX idx_promotions_type ON public.promotions USING btree (promotion_type);



CREATE INDEX idx_replay_annotations_session ON public.replay_annotations USING btree (session_id);



CREATE INDEX idx_replay_annotations_timestamp ON public.replay_annotations USING btree ("timestamp");



CREATE INDEX idx_replay_sessions_incident_id ON public.replay_sessions USING btree (incident_id);



CREATE INDEX idx_replay_sessions_symbol_time ON public.replay_sessions USING btree (symbol, start_time, end_time);



CREATE INDEX idx_replay_snapshots_incident_id ON public.replay_snapshots USING btree (incident_id);



CREATE INDEX idx_replay_snapshots_symbol_timestamp ON public.replay_snapshots USING btree (symbol, "timestamp" DESC);



CREATE INDEX idx_replay_snapshots_time ON public.replay_snapshots USING btree ("timestamp");



CREATE INDEX idx_replay_snapshots_type ON public.replay_snapshots USING btree (snapshot_type);



CREATE INDEX idx_report_templates_enabled ON public.report_templates USING btree (enabled);



CREATE INDEX idx_report_templates_type ON public.report_templates USING btree (report_type);



CREATE INDEX idx_retention_policies_active ON public.retention_policies USING btree (is_active);



CREATE INDEX idx_retention_policies_log_type ON public.retention_policies USING btree (log_type);



CREATE INDEX idx_risk_metrics_period ON public.risk_metrics_aggregation USING btree (period_type, period_start);



CREATE INDEX idx_risk_metrics_portfolio ON public.risk_metrics_aggregation USING btree (portfolio_id);



CREATE INDEX idx_risk_metrics_symbol_profile ON public.risk_metrics_aggregation USING btree (symbol, profile_id);



CREATE INDEX idx_scenario_results_name ON public.scenario_results USING btree (scenario_name);



CREATE INDEX idx_scenario_results_portfolio ON public.scenario_results USING btree (portfolio_id);



CREATE INDEX idx_scenario_results_symbol ON public.scenario_results USING btree (symbol);



CREATE INDEX idx_scenario_results_timestamp ON public.scenario_results USING btree (calculation_timestamp DESC);



CREATE INDEX idx_scenario_results_type ON public.scenario_results USING btree (scenario_type);



CREATE INDEX idx_signals_executed ON public.strategy_signals USING btree (executed);



CREATE INDEX idx_signals_strategy ON public.strategy_signals USING btree (strategy_id);



CREATE INDEX idx_signals_user_symbol_time ON public.strategy_signals USING btree (user_id, symbol, "time" DESC);



CREATE INDEX idx_strategy_correlation_a ON public.strategy_correlation USING btree (strategy_a);



CREATE INDEX idx_strategy_correlation_b ON public.strategy_correlation USING btree (strategy_b);



CREATE INDEX idx_strategy_correlation_date ON public.strategy_correlation USING btree (calculation_date DESC);



CREATE INDEX idx_strategy_instances_status ON public.strategy_instances USING btree (status);



CREATE INDEX idx_strategy_instances_system_template ON public.strategy_instances USING btree (is_system_template) WHERE (is_system_template = true);



CREATE UNIQUE INDEX idx_strategy_instances_system_template_unique ON public.strategy_instances USING btree (template_id) WHERE (is_system_template = true);



CREATE INDEX idx_strategy_instances_template ON public.strategy_instances USING btree (template_id);



CREATE INDEX idx_strategy_instances_user ON public.strategy_instances USING btree (user_id);



CREATE UNIQUE INDEX idx_strategy_instances_user_name_unique ON public.strategy_instances USING btree (user_id, name) WHERE (user_id IS NOT NULL);



CREATE INDEX idx_strategy_instances_user_status ON public.strategy_instances USING btree (user_id, status);



CREATE INDEX idx_strategy_portfolio_bot_profile ON public.strategy_portfolio USING btree (bot_profile_id);



CREATE INDEX idx_strategy_portfolio_date ON public.strategy_portfolio USING btree (calculation_date DESC);



CREATE INDEX idx_strategy_portfolio_family ON public.strategy_portfolio USING btree (strategy_family);



CREATE INDEX idx_strategy_portfolio_name ON public.strategy_portfolio USING btree (strategy_name);



CREATE INDEX idx_strategy_templates_active ON public.strategy_templates USING btree (is_active);



CREATE INDEX idx_strategy_templates_family ON public.strategy_templates USING btree (strategy_family);



CREATE INDEX idx_strategy_templates_slug ON public.strategy_templates USING btree (slug);



CREATE INDEX idx_symbol_data_health_score ON public.symbol_data_health USING btree (quality_score);



CREATE INDEX idx_symbol_data_health_status ON public.symbol_data_health USING btree (health_status);



CREATE INDEX idx_symbol_locks_account_env ON public.symbol_locks USING btree (exchange_account_id, environment);



CREATE INDEX idx_symbol_locks_heartbeat ON public.symbol_locks USING btree (lease_heartbeat_at);



CREATE INDEX idx_symbol_locks_owner ON public.symbol_locks USING btree (owner_bot_id);



CREATE INDEX idx_tenant_risk_policies_user ON public.tenant_risk_policies USING btree (user_id);



CREATE INDEX idx_token_catalog_active ON public.exchange_token_catalog USING btree (exchange, is_active);



CREATE INDEX idx_token_catalog_exchange ON public.exchange_token_catalog USING btree (exchange);



CREATE INDEX idx_trade_costs_profile_id ON public.trade_costs USING btree (profile_id);



CREATE INDEX idx_trade_costs_symbol ON public.trade_costs USING btree (symbol);



CREATE INDEX idx_trade_costs_timestamp ON public.trade_costs USING btree ("timestamp");



CREATE INDEX idx_trade_costs_trade_id ON public.trade_costs USING btree (trade_id);



CREATE INDEX idx_trade_profiles_active_config ON public.user_trade_profiles USING btree (active_bot_exchange_config_id);



CREATE INDEX idx_trade_profiles_bot ON public.user_trade_profiles USING btree (assigned_bot_id);



CREATE INDEX idx_trade_profiles_user ON public.user_trade_profiles USING btree (user_id);



CREATE INDEX idx_trades_bot ON public.trades USING btree (bot_id);



CREATE INDEX idx_trades_exchange_account ON public.trades USING btree (exchange_account_id);



CREATE INDEX idx_trades_executed_at ON public.trades USING btree (executed_at);



CREATE INDEX idx_trades_user_symbol ON public.trades USING btree (user_id, symbol);



CREATE INDEX idx_trading_activity_timestamp ON public.trading_activity USING btree ("timestamp" DESC);



CREATE INDEX idx_trading_activity_token ON public.trading_activity USING btree (token);



CREATE INDEX idx_trading_activity_type ON public.trading_activity USING btree (type);



CREATE INDEX idx_trading_activity_user_id ON public.trading_activity USING btree (user_id);



CREATE INDEX idx_trading_activity_user_timestamp ON public.trading_activity USING btree (user_id, "timestamp" DESC);



CREATE INDEX idx_trading_decisions_action ON public.trading_decisions USING btree (action);



CREATE INDEX idx_trading_decisions_bot ON public.trading_decisions USING btree (bot_id);



CREATE INDEX idx_trading_decisions_confidence ON public.trading_decisions USING btree (confidence) WHERE (confidence >= 0.5);



CREATE INDEX idx_trading_decisions_created_at ON public.trading_decisions USING btree (created_at DESC);



CREATE INDEX idx_trading_decisions_exchange_account ON public.trading_decisions USING btree (exchange_account_id);



CREATE INDEX idx_trading_decisions_executed ON public.trading_decisions USING btree (executed);



CREATE INDEX idx_trading_decisions_portfolio_id ON public.trading_decisions USING btree (portfolio_id);



CREATE INDEX idx_trading_decisions_user_token ON public.trading_decisions USING btree (user_id, token);



CREATE INDEX idx_user_profiles_active ON public.user_chessboard_profiles USING btree (is_active) WHERE (is_active = true);



CREATE INDEX idx_user_profiles_base ON public.user_chessboard_profiles USING btree (base_profile_id);



CREATE INDEX idx_user_profiles_env ON public.user_chessboard_profiles USING btree (environment);



CREATE INDEX idx_user_profiles_status ON public.user_chessboard_profiles USING btree (status);



CREATE INDEX idx_user_profiles_user ON public.user_chessboard_profiles USING btree (user_id);



CREATE INDEX idx_user_profiles_user_env ON public.user_chessboard_profiles USING btree (user_id, environment);



CREATE INDEX idx_user_trading_settings_risk_profile ON public.user_trading_settings USING btree (risk_profile);



CREATE INDEX idx_user_trading_settings_strategy ON public.user_trading_settings USING btree (strategy_selection);



CREATE INDEX idx_user_trading_settings_user_id ON public.user_trading_settings USING btree (user_id);



CREATE INDEX idx_users_email ON public.users USING btree (email);



CREATE INDEX idx_users_role ON public.users USING btree (role);



CREATE INDEX idx_var_calculations_date ON public.var_calculations USING btree (calculation_date DESC);



CREATE INDEX idx_var_calculations_portfolio ON public.var_calculations USING btree (portfolio_id);



CREATE INDEX idx_var_calculations_profile ON public.var_calculations USING btree (profile_id);



CREATE INDEX idx_var_calculations_symbol ON public.var_calculations USING btree (symbol);



CREATE INDEX idx_var_calculations_timestamp ON public.var_calculations USING btree (calculation_timestamp DESC);



CREATE INDEX idx_var_calculations_type ON public.var_calculations USING btree (calculation_type);



CREATE INDEX market_candles_time_idx ON public.market_candles USING btree ("time" DESC);



CREATE INDEX market_trades_time_idx ON public.market_trades USING btree ("time" DESC);



CREATE INDEX microstructure_features_time_idx ON public.microstructure_features USING btree ("time" DESC);



CREATE INDEX order_book_snapshots_time_idx ON public.order_book_snapshots USING btree ("time" DESC);



CREATE INDEX strategy_signals_time_idx ON public.strategy_signals USING btree ("time" DESC);



CREATE INDEX wfo_runs_tenant_idx ON public.wfo_runs USING btree (tenant_id);



CREATE INDEX wfo_runs_tenant_status_idx ON public.wfo_runs USING btree (tenant_id, status);



CREATE TRIGGER create_exchange_policy_on_account AFTER INSERT ON public.exchange_accounts FOR EACH ROW EXECUTE FUNCTION public.create_default_exchange_policy();



CREATE TRIGGER paper_position_high_low_trigger BEFORE UPDATE ON public.paper_positions FOR EACH ROW WHEN ((((old.status)::text = 'open'::text) AND (new.current_price IS DISTINCT FROM old.current_price))) EXECUTE FUNCTION public.update_paper_position_high_low();



CREATE TRIGGER paper_position_history_trigger AFTER UPDATE ON public.paper_positions FOR EACH ROW WHEN (((old.status)::text = 'open'::text)) EXECUTE FUNCTION public.record_paper_position_history();



CREATE TRIGGER trigger_assign_config_version BEFORE INSERT OR UPDATE ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.assign_config_version_before();



CREATE TRIGGER trigger_create_default_risk_policy AFTER INSERT ON public.users FOR EACH ROW EXECUTE FUNCTION public.create_default_risk_policy();



CREATE TRIGGER trigger_create_initial_profile_version AFTER INSERT ON public.user_chessboard_profiles FOR EACH ROW EXECUTE FUNCTION public.create_initial_profile_version();



CREATE TRIGGER trigger_create_paper_balance_for_bot AFTER INSERT ON public.bot_instances FOR EACH ROW EXECUTE FUNCTION public.create_paper_balance_for_bot_instance();



CREATE TRIGGER trigger_create_paper_balance_on_mode_change AFTER UPDATE OF trading_mode ON public.bot_instances FOR EACH ROW WHEN ((((new.trading_mode)::text = 'paper'::text) AND ((old.trading_mode IS NULL) OR ((old.trading_mode)::text <> 'paper'::text)))) EXECUTE FUNCTION public.create_paper_balance_for_bot_instance();



CREATE TRIGGER trigger_create_profile_version AFTER UPDATE ON public.user_chessboard_profiles FOR EACH ROW WHEN ((old.version IS DISTINCT FROM new.version)) EXECUTE FUNCTION public.create_profile_version_snapshot();



CREATE TRIGGER trigger_ensure_single_active_bot_config BEFORE INSERT OR UPDATE OF is_active ON public.bot_exchange_configs FOR EACH ROW WHEN ((new.is_active = true)) EXECUTE FUNCTION public.ensure_single_active_bot_config();



CREATE TRIGGER trigger_insert_config_version AFTER INSERT OR UPDATE ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.insert_config_version_after();



CREATE TRIGGER trigger_position_closed AFTER UPDATE ON public.positions FOR EACH ROW EXECUTE FUNCTION public.update_portfolio_on_position_close();



CREATE TRIGGER trigger_position_opened AFTER INSERT ON public.positions FOR EACH ROW WHEN (((new.status)::text = 'open'::text)) EXECUTE FUNCTION public.update_portfolio_on_position_open();



CREATE TRIGGER trigger_update_profile_timestamp BEFORE UPDATE ON public.user_chessboard_profiles FOR EACH ROW EXECUTE FUNCTION public.update_profile_timestamp();



CREATE TRIGGER trigger_update_strategy_instance_timestamp BEFORE UPDATE ON public.strategy_instances FOR EACH ROW EXECUTE FUNCTION public.update_strategy_instance_timestamp();



CREATE TRIGGER trigger_update_strategy_usage AFTER INSERT OR DELETE OR UPDATE OF strategy_composition ON public.user_chessboard_profiles FOR EACH ROW EXECUTE FUNCTION public.update_strategy_instance_usage();



CREATE TRIGGER trigger_validate_profile_environment BEFORE INSERT OR UPDATE OF mounted_profile_id ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.validate_profile_environment_match();



CREATE TRIGGER update_bot_assignments_updated_at BEFORE UPDATE ON public.bot_pool_assignments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_bot_budgets_updated_at BEFORE UPDATE ON public.bot_budgets FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_bot_exchange_configs_updated_at BEFORE UPDATE ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_bot_instances_updated_at BEFORE UPDATE ON public.bot_instances FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_bot_symbol_configs_updated_at BEFORE UPDATE ON public.bot_symbol_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_exchange_accounts_updated_at BEFORE UPDATE ON public.exchange_accounts FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_exchange_creds_updated_at BEFORE UPDATE ON public.user_exchange_credentials FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_exchange_policies_updated_at BEFORE UPDATE ON public.exchange_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_portfolios_updated_at BEFORE UPDATE ON public.portfolios FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_strategy_templates_updated_at BEFORE UPDATE ON public.strategy_templates FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_tenant_risk_policies_updated_at BEFORE UPDATE ON public.tenant_risk_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_trade_profiles_updated_at BEFORE UPDATE ON public.user_trade_profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();



ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_approver_id_fkey FOREIGN KEY (approver_id) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.audit_log_exports
    ADD CONSTRAINT audit_log_exports_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.backtest_decision_snapshots
    ADD CONSTRAINT backtest_decision_snapshots_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_equity_curve
    ADD CONSTRAINT backtest_equity_curve_backtest_run_id_fkey FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_runs(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_metrics
    ADD CONSTRAINT backtest_metrics_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_position_snapshots
    ADD CONSTRAINT backtest_position_snapshots_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_symbol_equity_curve
    ADD CONSTRAINT backtest_symbol_equity_curve_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_symbol_metrics
    ADD CONSTRAINT backtest_symbol_metrics_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;



ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_backtest_run_id_fkey FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_runs(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_exchange_config_id_fkey FOREIGN KEY (exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_parent_command_id_fkey FOREIGN KEY (parent_command_id) REFERENCES public.bot_commands(id);



ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);



ALTER TABLE ONLY public.bot_config_actions
    ADD CONSTRAINT bot_config_actions_bot_profile_id_fkey FOREIGN KEY (bot_profile_id) REFERENCES public.bot_profiles(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_config_actions
    ADD CONSTRAINT bot_config_actions_bot_profile_version_id_fkey FOREIGN KEY (bot_profile_version_id) REFERENCES public.bot_profile_versions(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_bot_exchange_config_id_fkey FOREIGN KEY (bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_mounted_profile_id_fkey FOREIGN KEY (mounted_profile_id) REFERENCES public.user_chessboard_profiles(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id);



ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_strategy_template_id_fkey FOREIGN KEY (strategy_template_id) REFERENCES public.strategy_templates(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_logs
    ADD CONSTRAINT bot_logs_bot_exchange_config_id_fkey FOREIGN KEY (bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_logs
    ADD CONSTRAINT bot_logs_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_logs
    ADD CONSTRAINT bot_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_pool_assignments
    ADD CONSTRAINT bot_pool_assignments_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_pool_assignments
    ADD CONSTRAINT bot_pool_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_profile_versions
    ADD CONSTRAINT bot_profile_versions_bot_profile_id_fkey FOREIGN KEY (bot_profile_id) REFERENCES public.bot_profiles(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_profiles
    ADD CONSTRAINT bot_profiles_active_version_fk FOREIGN KEY (active_version_id) REFERENCES public.bot_profile_versions(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.bot_symbol_configs
    ADD CONSTRAINT bot_symbol_configs_bot_exchange_config_id_fkey FOREIGN KEY (bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.bot_version_sections
    ADD CONSTRAINT bot_version_sections_bot_profile_version_id_fkey FOREIGN KEY (bot_profile_version_id) REFERENCES public.bot_profile_versions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.config_audit_log
    ADD CONSTRAINT config_audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.config_diffs
    ADD CONSTRAINT config_diffs_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.copilot_messages
    ADD CONSTRAINT copilot_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.copilot_conversations(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.copilot_settings_snapshots
    ADD CONSTRAINT copilot_settings_snapshots_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.copilot_conversations(id);



ALTER TABLE ONLY public.credential_balance_history
    ADD CONSTRAINT credential_balance_history_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.credential_balance_history
    ADD CONSTRAINT credential_balance_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.credential_config_audit
    ADD CONSTRAINT credential_config_audit_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.credential_config_audit
    ADD CONSTRAINT credential_config_audit_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_active_bot_fk FOREIGN KEY (active_bot_id) REFERENCES public.bot_instances(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_kill_switch_triggered_by_fkey FOREIGN KEY (kill_switch_triggered_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.fast_scalper_positions
    ADD CONSTRAINT fast_scalper_positions_bot_id_fkey FOREIGN KEY (bot_id) REFERENCES public.bot_instances(id);



ALTER TABLE ONLY public.fast_scalper_trades
    ADD CONSTRAINT fast_scalper_trades_bot_id_fkey FOREIGN KEY (bot_id) REFERENCES public.bot_instances(id);



ALTER TABLE ONLY public.generated_reports
    ADD CONSTRAINT generated_reports_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.report_templates(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.incident_affected_objects
    ADD CONSTRAINT incident_affected_objects_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.incidents(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.incident_events
    ADD CONSTRAINT incident_events_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.incidents(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_balances
    ADD CONSTRAINT paper_balances_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_balances
    ADD CONSTRAINT paper_balances_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_orders
    ADD CONSTRAINT paper_orders_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.paper_orders
    ADD CONSTRAINT paper_orders_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_orders
    ADD CONSTRAINT paper_orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_performance_snapshots
    ADD CONSTRAINT paper_performance_snapshots_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_performance_snapshots
    ADD CONSTRAINT paper_performance_snapshots_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_alerts
    ADD CONSTRAINT paper_position_alerts_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_alerts
    ADD CONSTRAINT paper_position_alerts_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_alerts
    ADD CONSTRAINT paper_position_alerts_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.paper_positions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_history
    ADD CONSTRAINT paper_position_history_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_history
    ADD CONSTRAINT paper_position_history_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.paper_positions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_tags
    ADD CONSTRAINT paper_position_tags_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_position_tags
    ADD CONSTRAINT paper_position_tags_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_positions
    ADD CONSTRAINT paper_positions_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.paper_positions
    ADD CONSTRAINT paper_positions_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_positions
    ADD CONSTRAINT paper_positions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_trades
    ADD CONSTRAINT paper_trades_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.paper_trades
    ADD CONSTRAINT paper_trades_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.paper_trades
    ADD CONSTRAINT paper_trades_paper_order_id_fkey FOREIGN KEY (paper_order_id) REFERENCES public.paper_orders(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.paper_trades
    ADD CONSTRAINT paper_trades_paper_position_id_fkey FOREIGN KEY (paper_position_id) REFERENCES public.paper_positions(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.paper_trades
    ADD CONSTRAINT paper_trades_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.portfolios
    ADD CONSTRAINT portfolios_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.position_updates
    ADD CONSTRAINT position_updates_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.positions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_entry_order_id_fkey FOREIGN KEY (entry_order_id) REFERENCES public.orders(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.users(id);



ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.user_chessboard_profiles(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.promotion_history
    ADD CONSTRAINT promotion_history_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.promotion_history
    ADD CONSTRAINT promotion_history_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_rejected_by_fkey FOREIGN KEY (rejected_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.replay_annotations
    ADD CONSTRAINT replay_annotations_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.replay_sessions(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.replay_sessions
    ADD CONSTRAINT replay_sessions_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.incidents(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.strategy_instances
    ADD CONSTRAINT strategy_instances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.strategy_templates
    ADD CONSTRAINT strategy_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_owner_bot_fk FOREIGN KEY (owner_bot_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.tenant_risk_policies
    ADD CONSTRAINT tenant_risk_policies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.positions(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);



ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_promoted_from_id_fkey FOREIGN KEY (promoted_from_id) REFERENCES public.user_chessboard_profiles(id);



ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.user_exchange_credentials
    ADD CONSTRAINT user_exchange_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_active_bot_exchange_config_id_fkey FOREIGN KEY (active_bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_active_credential_id_fkey FOREIGN KEY (active_credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE SET NULL;



ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;



ALTER TABLE ONLY public.user_trading_settings
    ADD CONSTRAINT user_trading_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

