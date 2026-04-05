--
-- DeepTrader Database Schema
-- Auto-generated export of the complete database structure
-- 
-- To restore: psql -U deeptrader_user -d deeptrader < schema.sql
--
-- Generated: 
-- 2025-12-19 13:29:27
--

--
-- PostgreSQL database dump
--

-- Dumped from database version 15.13
-- Dumped by pg_dump version 15.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


--
-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: alert_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_type AS ENUM (
    'social',
    'news',
    'whale',
    'price'
);


--
-- Name: bot_command_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.bot_command_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'cancelled',
    'expired'
);


--
-- Name: bot_command_type; Type: TYPE; Schema: public; Owner: -
--

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


--
-- Name: bot_config_state; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.bot_config_state AS ENUM (
    'created',
    'ready',
    'running',
    'paused',
    'error',
    'decommissioned'
);


--
-- Name: bot_environment; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.bot_environment AS ENUM (
    'dev',
    'paper',
    'live'
);


--
-- Name: order_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.order_type AS ENUM (
    'market',
    'limit',
    'stop_loss',
    'take_profit'
);


--
-- Name: profile_environment; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.profile_environment AS ENUM (
    'dev',
    'paper',
    'live'
);


--
-- Name: profile_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.profile_status AS ENUM (
    'draft',
    'active',
    'disabled',
    'archived'
);


--
-- Name: trade_side; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.trade_side AS ENUM (
    'buy',
    'sell'
);


--
-- Name: trade_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.trade_status AS ENUM (
    'open',
    'closed',
    'cancelled'
);


--
-- Name: user_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.user_role AS ENUM (
    'user',
    'admin'
);


--
-- Name: assign_config_version_before(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: calculate_portfolio_pnl(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.calculate_portfolio_pnl(portfolio_uuid uuid) RETURNS TABLE(total_pnl numeric, total_pnl_percentage numeric, total_trades bigint, winning_trades bigint, losing_trades bigint, win_rate numeric)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(SUM(t.pnl), 0) as total_pnl,
        CASE
            WHEN p.starting_capital > 0 THEN
                ROUND((COALESCE(SUM(t.pnl), 0) / p.starting_capital) * 100, 4)
            ELSE 0
        END as total_pnl_percentage,
        COUNT(*) as total_trades,
        COUNT(CASE WHEN t.pnl > 0 THEN 1 END) as winning_trades,
        COUNT(CASE WHEN t.pnl < 0 THEN 1 END) as losing_trades,
        CASE
            WHEN COUNT(*) > 0 THEN
                ROUND((COUNT(CASE WHEN t.pnl > 0 THEN 1 END)::DECIMAL / COUNT(*)::DECIMAL) * 100, 2)
            ELSE 0
        END as win_rate
    FROM portfolios p
    LEFT JOIN trades t ON p.id = t.portfolio_id AND t.status = 'closed'
    WHERE p.id = portfolio_uuid
    GROUP BY p.id, p.starting_capital;
END;
$$;


--
-- Name: complete_bot_command(uuid, boolean, jsonb, jsonb, text); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: create_audit_log_entry(uuid, character varying, uuid, character varying, character varying, jsonb, jsonb, text); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: FUNCTION create_audit_log_entry(p_user_id uuid, p_resource_type character varying, p_resource_id uuid, p_action character varying, p_environment character varying, p_before_state jsonb, p_after_state jsonb, p_notes text); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.create_audit_log_entry(p_user_id uuid, p_resource_type character varying, p_resource_id uuid, p_action character varying, p_environment character varying, p_before_state jsonb, p_after_state jsonb, p_notes text) IS 'Helper to create audit log entries from application code';


--
-- Name: create_default_exchange_policy(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: create_default_risk_policy(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: create_initial_profile_version(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: create_profile_version_snapshot(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: ensure_single_active_bot_config(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: get_latest_portfolio_value(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_latest_portfolio_value(portfolio_uuid uuid) RETURNS numeric
    LANGUAGE plpgsql
    AS $$
DECLARE
    latest_value DECIMAL(20,8);
BEGIN
    SELECT value INTO latest_value
    FROM portfolio_equity
    WHERE portfolio_id = portfolio_uuid
    ORDER BY timestamp DESC
    LIMIT 1;

    IF latest_value IS NULL THEN
        SELECT starting_capital INTO latest_value
        FROM portfolios
        WHERE id = portfolio_uuid;
    END IF;

    RETURN COALESCE(latest_value, 0);
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: bot_commands; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE bot_commands; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_commands IS 'Queue-based bot control commands with audit trail';


--
-- Name: COLUMN bot_commands.priority; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_commands.priority IS 'Higher values = higher priority. Emergency commands should use high priority.';


--
-- Name: COLUMN bot_commands.expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_commands.expires_at IS 'Optional TTL - command will be marked expired if not processed by this time';


--
-- Name: COLUMN bot_commands.correlation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_commands.correlation_id IS 'For tracking related commands (e.g., restart = stop + start)';


--
-- Name: get_next_bot_command(uuid); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: insert_config_version_after(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: reset_daily_loss_tracking(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: FUNCTION reset_daily_loss_tracking(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.reset_daily_loss_tracking() IS 'Call daily to reset loss tracking counters';


--
-- Name: update_portfolio_on_position_close(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: update_portfolio_on_position_open(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: update_profile_timestamp(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: update_strategy_instance_timestamp(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: update_strategy_instance_usage(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: validate_profile_environment_match(); Type: FUNCTION; Schema: public; Owner: -
--

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


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    "timestamp" timestamp with time zone NOT NULL,
    event_type text NOT NULL,
    symbol text,
    sequence bigint,
    data jsonb NOT NULL
);


--
-- Name: _hyper_11_12_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_11_12_chunk (
    CONSTRAINT constraint_12 CHECK ((("timestamp" >= '2025-12-12 00:00:00+00'::timestamp with time zone) AND ("timestamp" < '2025-12-13 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.events);


--
-- Name: _hyper_11_9_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_11_9_chunk (
    CONSTRAINT constraint_9 CHECK ((("timestamp" >= '2025-12-08 00:00:00+00'::timestamp with time zone) AND ("timestamp" < '2025-12-09 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.events);


--
-- Name: market_trades; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE market_trades; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.market_trades IS 'Time-series table for individual market trades from exchanges';


--
-- Name: _hyper_1_11_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_11_chunk (
    CONSTRAINT constraint_11 CHECK ((("time" >= '2025-12-11 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-18 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_trades);


--
-- Name: _hyper_1_14_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_14_chunk (
    CONSTRAINT constraint_14 CHECK ((("time" >= '2025-12-18 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-25 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_trades);


--
-- Name: _hyper_1_1_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_1_chunk (
    CONSTRAINT constraint_1 CHECK ((("time" >= '2025-11-13 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-11-20 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_trades);


--
-- Name: _hyper_1_3_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_3_chunk (
    CONSTRAINT constraint_3 CHECK ((("time" >= '2025-11-20 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-11-27 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_trades);


--
-- Name: _hyper_1_6_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_6_chunk (
    CONSTRAINT constraint_6 CHECK ((("time" >= '2025-11-27 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-04 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_trades);


--
-- Name: _hyper_1_7_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_7_chunk (
    CONSTRAINT constraint_7 CHECK ((("time" >= '2025-12-04 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-11 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_trades);


--
-- Name: order_book_snapshots; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE order_book_snapshots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.order_book_snapshots IS 'Time-series snapshots of order book state';


--
-- Name: _hyper_2_13_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_2_13_chunk (
    CONSTRAINT constraint_13 CHECK ((("time" >= '2025-12-11 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-18 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.order_book_snapshots);


--
-- Name: market_candles; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE market_candles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.market_candles IS 'OHLCV candle data at various timeframes';


--
-- Name: _hyper_3_10_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_10_chunk (
    CONSTRAINT constraint_10 CHECK ((("time" >= '2025-12-11 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-18 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_candles);


--
-- Name: _hyper_3_15_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_15_chunk (
    CONSTRAINT constraint_15 CHECK ((("time" >= '2025-12-18 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-25 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_candles);


--
-- Name: _hyper_3_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_2_chunk (
    CONSTRAINT constraint_2 CHECK ((("time" >= '2025-11-13 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-11-20 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_candles);


--
-- Name: _hyper_3_4_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_4_chunk (
    CONSTRAINT constraint_4 CHECK ((("time" >= '2025-11-20 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-11-27 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_candles);


--
-- Name: _hyper_3_5_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_5_chunk (
    CONSTRAINT constraint_5 CHECK ((("time" >= '2025-11-27 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-04 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_candles);


--
-- Name: _hyper_3_8_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_8_chunk (
    CONSTRAINT constraint_8 CHECK ((("time" >= '2025-12-04 00:00:00+00'::timestamp with time zone) AND ("time" < '2025-12-11 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.market_candles);


--
-- Name: alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alerts (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    type public.alert_type NOT NULL,
    token character varying(20),
    title character varying(500) NOT NULL,
    message text,
    severity character varying(20) DEFAULT 'info'::character varying,
    is_read boolean DEFAULT false,
    data jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: TABLE alerts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.alerts IS 'User notifications and alerts';


--
-- Name: amt_metrics; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE amt_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.amt_metrics IS 'Auction Market Theory metrics and value areas';


--
-- Name: approvals; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: audit_log_exports; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: backtest_equity_curve; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_equity_curve (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    backtest_run_id uuid NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    equity numeric(15,2) NOT NULL,
    drawdown numeric(10,4),
    drawdown_percent numeric(10,4)
);


--
-- Name: TABLE backtest_equity_curve; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_equity_curve IS 'Equity curve data points for backtest runs';


--
-- Name: backtest_runs; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT backtest_runs_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: TABLE backtest_runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_runs IS 'Backtest run metadata and results';


--
-- Name: backtest_trades; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT backtest_trades_side_check CHECK ((side = ANY (ARRAY['buy'::text, 'sell'::text])))
);


--
-- Name: TABLE backtest_trades; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_trades IS 'Individual trades from backtest runs';


--
-- Name: bot_budgets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bot_budgets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_instance_id uuid NOT NULL,
    exchange_account_id uuid NOT NULL,
    max_daily_loss_pct numeric(5,2),
    max_daily_loss_usd numeric(20,2),
    max_margin_used_pct numeric(5,2),
    max_exposure_pct numeric(5,2),
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


--
-- Name: TABLE bot_budgets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_budgets IS 'Per-bot budget allocations within an exchange account (required in PROP mode)';


--
-- Name: bot_exchange_configs; Type: TABLE; Schema: public; Owner: -
--

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
    mounted_at timestamp with time zone
);


--
-- Name: TABLE bot_exchange_configs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_exchange_configs IS 'Runtime binding of bot instance + exchange credential + environment';


--
-- Name: COLUMN bot_exchange_configs.credential_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.credential_id IS 'Legacy: kept for backward compatibility, will be phased out';


--
-- Name: COLUMN bot_exchange_configs.environment; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.environment IS 'Trading environment: dev (local testing), paper (simulated), live (real money)';


--
-- Name: COLUMN bot_exchange_configs.state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.state IS 'Lifecycle state: created -> ready -> running/paused/error -> decommissioned';


--
-- Name: COLUMN bot_exchange_configs.is_active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.is_active IS 'Only one config can be active per user at a time';


--
-- Name: COLUMN bot_exchange_configs.exchange_account_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.exchange_account_id IS 'New: references exchange_accounts for the operating modes system';


--
-- Name: COLUMN bot_exchange_configs.exchange; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.exchange IS 'Denormalized exchange name (e.g., binance, okx) for quick access';


--
-- Name: COLUMN bot_exchange_configs.deleted_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.deleted_at IS 'Soft delete timestamp';


--
-- Name: COLUMN bot_exchange_configs.mounted_profile_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.mounted_profile_id IS 'The user profile currently mounted for trading on this exchange';


--
-- Name: COLUMN bot_exchange_configs.mounted_profile_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.mounted_profile_version IS 'The specific version of the profile that was mounted';


--
-- Name: COLUMN bot_exchange_configs.mounted_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_exchange_configs.mounted_at IS 'Timestamp when the profile was mounted';


--
-- Name: bot_instances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bot_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(128) NOT NULL,
    description text,
    strategy_template_id uuid,
    allocator_role character varying(32) DEFAULT 'core'::character varying,
    default_risk_config jsonb DEFAULT '{"maxLeverage": 1, "leverageMode": "isolated", "maxPositions": 4, "maxDailyLossPct": 5, "positionSizePct": 10, "maxTotalExposurePct": 40, "maxPositionsPerSymbol": 1, "maxDailyLossPerSymbolPct": 2.5}'::jsonb,
    default_execution_config jsonb DEFAULT '{"stopLossPct": 2, "takeProfitPct": 5, "trailingStopPct": 1, "defaultOrderType": "market", "maxHoldTimeHours": 24, "executionTimeoutSec": 5, "minTradeIntervalSec": 1, "trailingStopEnabled": false, "enableVolatilityFilter": true}'::jsonb,
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
    CONSTRAINT bot_instances_runtime_state_check CHECK (((runtime_state)::text = ANY ((ARRAY['idle'::character varying, 'starting'::character varying, 'running'::character varying, 'paused'::character varying, 'stopping'::character varying, 'error'::character varying])::text[])))
);


--
-- Name: TABLE bot_instances; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_instances IS 'User-facing bot configurations that reference strategy templates';


--
-- Name: COLUMN bot_instances.allocator_role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.allocator_role IS 'Role in portfolio allocation: core, satellite, hedge, experimental';


--
-- Name: COLUMN bot_instances.default_risk_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.default_risk_config IS 'Default risk settings, can be overridden per exchange attachment';


--
-- Name: COLUMN bot_instances.profile_overrides; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.profile_overrides IS 'Overrides to merge with strategy template profile bundle';


--
-- Name: COLUMN bot_instances.exchange_account_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.exchange_account_id IS 'The exchange account (risk pool) this bot trades on';


--
-- Name: COLUMN bot_instances.runtime_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.runtime_state IS 'Current execution state: idle, starting, running, paused, stopping, error';


--
-- Name: COLUMN bot_instances.enabled_symbols; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.enabled_symbols IS 'Symbols this bot is configured to trade';


--
-- Name: COLUMN bot_instances.deleted_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.deleted_at IS 'Soft delete timestamp - when set, bot is considered deleted';


--
-- Name: COLUMN bot_instances.deleted_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_instances.deleted_by IS 'User who deleted the bot';


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    email character varying(255) NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    role public.user_role DEFAULT 'user'::public.user_role,
    email_verified boolean DEFAULT false,
    email_verification_token character varying(255),
    password_reset_token character varying(255),
    password_reset_expires timestamp without time zone,
    is_active boolean DEFAULT true,
    last_login timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    operating_mode character varying(16) DEFAULT 'solo'::character varying,
    CONSTRAINT users_operating_mode_check CHECK (((operating_mode)::text = ANY ((ARRAY['solo'::character varying, 'team'::character varying, 'prop'::character varying])::text[])))
);


--
-- Name: TABLE users; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.users IS 'User accounts with authentication information';


--
-- Name: COLUMN users.operating_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.users.operating_mode IS 'Operating mode: solo (1 bot per exchange), team (concurrent + locks), prop (concurrent + locks + budgets required)';


--
-- Name: bot_command_history; Type: VIEW; Schema: public; Owner: -
--

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


--
-- Name: bot_config_actions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE bot_config_actions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_config_actions IS 'Audit trail for bot configuration + control plane actions';


--
-- Name: bot_configurations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bot_configurations (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    portfolio_id uuid,
    name character varying(100) NOT NULL,
    is_active boolean DEFAULT false,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: bot_exchange_config_versions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE bot_exchange_config_versions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_exchange_config_versions IS 'Immutable version history of bot-exchange configurations';


--
-- Name: bot_pool_assignments; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE bot_pool_assignments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_pool_assignments IS 'Tracks which bot instance is running for each user in the pool';


--
-- Name: bot_profile_versions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE bot_profile_versions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_profile_versions IS 'Immutable configuration payloads for each bot profile';


--
-- Name: bot_profiles; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE bot_profiles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_profiles IS 'Logical trading bots grouped by environment';


--
-- Name: COLUMN bot_profiles.active_version_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_profiles.active_version_id IS 'Currently active configuration version';


--
-- Name: bot_symbol_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bot_symbol_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_exchange_config_id uuid NOT NULL,
    symbol character varying(64) NOT NULL,
    enabled boolean DEFAULT true,
    max_exposure_pct numeric(5,2),
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


--
-- Name: TABLE bot_symbol_configs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_symbol_configs IS 'Per-symbol overrides within a bot-exchange configuration';


--
-- Name: COLUMN bot_symbol_configs.max_exposure_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_symbol_configs.max_exposure_pct IS 'Maximum exposure for this symbol as percentage of trading capital';


--
-- Name: COLUMN bot_symbol_configs.symbol_risk_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_symbol_configs.symbol_risk_config IS 'Risk parameter overrides specific to this symbol';


--
-- Name: COLUMN bot_symbol_configs.symbol_profile_overrides; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bot_symbol_configs.symbol_profile_overrides IS 'Strategy/profile overrides for this symbol';


--
-- Name: bot_version_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bot_version_sections (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    bot_profile_version_id uuid NOT NULL,
    section text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE bot_version_sections; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bot_version_sections IS 'Optional per-section payloads extracted from config blobs';


--
-- Name: capacity_analysis; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE capacity_analysis; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.capacity_analysis IS 'Capacity curves showing performance vs notional size';


--
-- Name: component_var; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: config_audit_log; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE config_audit_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.config_audit_log IS 'Comprehensive audit trail for all configuration changes';


--
-- Name: config_blocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_blocks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    config_version_id uuid NOT NULL,
    block_type text NOT NULL,
    block_key text NOT NULL,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: config_change_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_change_log (
    id bigint NOT NULL,
    config_version_id uuid NOT NULL,
    action text NOT NULL,
    actor_id uuid,
    details jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT config_change_log_action_check CHECK ((action = ANY (ARRAY['create'::text, 'update'::text, 'publish'::text, 'rollback'::text, 'deprecate'::text])))
);


--
-- Name: config_change_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.config_change_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: config_change_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.config_change_log_id_seq OWNED BY public.config_change_log.id;


--
-- Name: config_diffs; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: config_environments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_environments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: config_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    config_version_id uuid NOT NULL,
    key text NOT NULL,
    value_json jsonb NOT NULL,
    data_type text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: config_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_sets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    domain text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: config_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    config_set_id uuid NOT NULL,
    environment_id uuid,
    version_semver text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    promoted_at timestamp with time zone,
    promoted_by uuid,
    notes text,
    CONSTRAINT config_versions_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'active'::text, 'deprecated'::text])))
);


--
-- Name: cost_aggregation; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE cost_aggregation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cost_aggregation IS 'Pre-aggregated cost metrics for fast queries';


--
-- Name: credential_balance_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credential_balance_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    credential_id uuid NOT NULL,
    user_id uuid NOT NULL,
    exchange_balance numeric(20,8) NOT NULL,
    trading_capital numeric(20,8),
    balance_currency character varying(16) DEFAULT 'USDT'::character varying,
    source character varying(32) DEFAULT 'api_fetch'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE credential_balance_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.credential_balance_history IS 'Historical balance snapshots for trend analysis';


--
-- Name: credential_config_audit; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE credential_config_audit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.credential_config_audit IS 'Audit trail of all configuration changes per credential';


--
-- Name: data_quality_alerts; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE data_quality_alerts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.data_quality_alerts IS 'Alerts when data quality thresholds are breached';


--
-- Name: data_quality_metrics; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE data_quality_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.data_quality_metrics IS 'Daily quality metrics per symbol/timeframe';


--
-- Name: decision_traces; Type: TABLE; Schema: public; Owner: -
--

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
    profile_id text
);


--
-- Name: equity_curves; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: exchange_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exchange_accounts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    venue character varying(32) NOT NULL,
    label character varying(128) NOT NULL,
    environment character varying(16) NOT NULL,
    secret_id character varying(256),
    is_testnet boolean DEFAULT false,
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


--
-- Name: TABLE exchange_accounts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.exchange_accounts IS 'Exchange accounts represent the risk pool boundary - shared balance/margin across all bots';


--
-- Name: COLUMN exchange_accounts.active_bot_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.exchange_accounts.active_bot_id IS 'SOLO mode: the single bot allowed to run on this account+env';


--
-- Name: exchange_limits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exchange_limits (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange character varying(32) NOT NULL,
    max_leverage integer DEFAULT 125,
    default_leverage integer DEFAULT 1,
    min_position_usd numeric(20,2) DEFAULT 5.00,
    max_position_usd numeric(20,2) DEFAULT 1000000.00,
    min_stop_loss_pct numeric(5,2) DEFAULT 0.1,
    max_daily_trades integer DEFAULT 1000,
    supports_isolated_margin boolean DEFAULT true,
    supports_cross_margin boolean DEFAULT true,
    supports_trailing_stop boolean DEFAULT true,
    supports_bracket_orders boolean DEFAULT true,
    last_updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE exchange_limits; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.exchange_limits IS 'Exchange-imposed limits used for validation';


--
-- Name: exchange_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exchange_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    exchange_account_id uuid NOT NULL,
    max_daily_loss_pct numeric(5,2) DEFAULT 10.0,
    max_daily_loss_usd numeric(20,2),
    daily_loss_used_usd numeric(20,2) DEFAULT 0,
    daily_loss_reset_at timestamp with time zone DEFAULT now(),
    max_margin_used_pct numeric(5,2) DEFAULT 80.0,
    max_gross_exposure_pct numeric(5,2) DEFAULT 100.0,
    max_net_exposure_pct numeric(5,2) DEFAULT 50.0,
    max_leverage numeric(5,2) DEFAULT 10.0,
    max_open_positions integer DEFAULT 10,
    kill_switch_enabled boolean DEFAULT false,
    kill_switch_triggered_at timestamp with time zone,
    kill_switch_triggered_by uuid,
    kill_switch_reason text,
    circuit_breaker_enabled boolean DEFAULT true,
    circuit_breaker_loss_pct numeric(5,2) DEFAULT 5.0,
    circuit_breaker_cooldown_min integer DEFAULT 60,
    circuit_breaker_triggered_at timestamp with time zone,
    live_trading_enabled boolean DEFAULT false,
    policy_version integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE exchange_policies; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.exchange_policies IS 'Hard risk caps per exchange account - enforced across all bots';


--
-- Name: COLUMN exchange_policies.kill_switch_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.exchange_policies.kill_switch_enabled IS 'When true, ALL trading is blocked on this account';


--
-- Name: COLUMN exchange_policies.circuit_breaker_loss_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.exchange_policies.circuit_breaker_loss_pct IS 'Auto-trigger kill switch at this daily loss %';


--
-- Name: exchange_token_catalog; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE exchange_token_catalog; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.exchange_token_catalog IS 'Cached catalog of available trading pairs per exchange';


--
-- Name: fast_scalper_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fast_scalper_metrics (
    id integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    user_id text NOT NULL,
    positions_open integer DEFAULT 0,
    daily_pnl numeric DEFAULT 0,
    total_exposure numeric DEFAULT 0,
    account_balance numeric DEFAULT 0,
    completed_trades integer DEFAULT 0,
    decisions_per_sec numeric DEFAULT 0,
    symbols_tracked integer DEFAULT 0,
    uptime_seconds integer DEFAULT 0,
    ws_public_connected boolean DEFAULT false,
    ws_private_connected boolean DEFAULT false
);


--
-- Name: fast_scalper_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fast_scalper_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fast_scalper_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fast_scalper_metrics_id_seq OWNED BY public.fast_scalper_metrics.id;


--
-- Name: fast_scalper_positions; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT fast_scalper_positions_side_check CHECK ((side = ANY (ARRAY['long'::text, 'short'::text, 'net'::text])))
);


--
-- Name: fast_scalper_positions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fast_scalper_positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fast_scalper_positions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fast_scalper_positions_id_seq OWNED BY public.fast_scalper_positions.id;


--
-- Name: fast_scalper_trades; Type: TABLE; Schema: public; Owner: -
--

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
    CONSTRAINT fast_scalper_trades_side_check CHECK ((side = ANY (ARRAY['long'::text, 'short'::text, 'buy'::text, 'sell'::text, 'net'::text])))
);


--
-- Name: fast_scalper_trades_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fast_scalper_trades_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fast_scalper_trades_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fast_scalper_trades_id_seq OWNED BY public.fast_scalper_trades.id;


--
-- Name: feed_gaps; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE feed_gaps; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.feed_gaps IS 'Tracks gaps in data feeds';


--
-- Name: generated_reports; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE generated_reports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.generated_reports IS 'Generated report instances';


--
-- Name: incidents; Type: TABLE; Schema: public; Owner: -
--

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
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE incidents; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.incidents IS 'Tracks significant events requiring investigation';


--
-- Name: market_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_data (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    token character varying(20) NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    price numeric(20,8) NOT NULL,
    volume numeric(20,8),
    high_24h numeric(20,8),
    low_24h numeric(20,8),
    change_24h numeric(10,4),
    market_cap numeric(25,2),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: TABLE market_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.market_data IS 'Cached market data for analysis';


--
-- Name: microstructure_features; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE microstructure_features; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.microstructure_features IS 'Market microstructure and order flow features';


--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: platform_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.platform_users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid,
    external_ref text,
    email text,
    role text DEFAULT 'member'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: portfolio_equity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_equity (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    portfolio_id uuid,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    value numeric(20,8) NOT NULL,
    capital numeric(20,8) NOT NULL,
    pnl numeric(20,8) DEFAULT 0.00,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: portfolio_summary; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE portfolio_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.portfolio_summary IS 'Aggregate portfolio-level metrics';


--
-- Name: portfolios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolios (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    name character varying(100) DEFAULT 'Main Portfolio'::character varying,
    description text,
    starting_capital numeric(20,8) DEFAULT 10000.00,
    current_capital numeric(20,8) DEFAULT 10000.00,
    total_value numeric(20,8) DEFAULT 10000.00,
    total_pnl numeric(20,8) DEFAULT 0.00,
    total_pnl_percentage numeric(10,4) DEFAULT 0.0000,
    is_paper_trading boolean DEFAULT true,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    open_positions_count integer DEFAULT 0,
    total_unrealized_pnl numeric(18,8) DEFAULT 0
);


--
-- Name: TABLE portfolios; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.portfolios IS 'User trading portfolios with capital tracking';


--
-- Name: position_impacts; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: position_updates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_updates (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    position_id uuid NOT NULL,
    price numeric(18,8) NOT NULL,
    unrealized_pnl numeric(18,8) NOT NULL,
    unrealized_pnl_percent numeric(5,2) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: positions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: profile_versions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE profile_versions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.profile_versions IS 'Audit trail of all profile configuration changes';


--
-- Name: promotion_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.promotion_history (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    promotion_id uuid,
    event_type text NOT NULL,
    event_description text,
    performed_by uuid,
    event_data jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: promotions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: replay_sessions; Type: TABLE; Schema: public; Owner: -
--

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
    last_accessed_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE replay_sessions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.replay_sessions IS 'Tracks investigation sessions for incident analysis';


--
-- Name: replay_snapshots; Type: TABLE; Schema: public; Owner: -
--

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
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE replay_snapshots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.replay_snapshots IS 'Stores complete market and decision state at decision points for replay';


--
-- Name: report_templates; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE report_templates; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.report_templates IS 'Templates for automated report generation';


--
-- Name: retention_policies; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: risk_metrics_aggregation; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: scenario_results; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: strategy_correlation; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE strategy_correlation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.strategy_correlation IS 'Correlation metrics between strategies';


--
-- Name: strategy_instances; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE strategy_instances; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.strategy_instances IS 'User-customized instances of strategy templates with parameterized settings';


--
-- Name: COLUMN strategy_instances.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_instances.user_id IS 'Owner of the strategy instance. NULL for system templates (visible to all users)';


--
-- Name: COLUMN strategy_instances.template_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_instances.template_id IS 'References the base strategy in the Python strategy registry';


--
-- Name: COLUMN strategy_instances.params; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_instances.params IS 'User-customized parameters merged with template defaults at runtime';


--
-- Name: COLUMN strategy_instances.usage_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_instances.usage_count IS 'Number of profiles currently using this strategy instance';


--
-- Name: COLUMN strategy_instances.is_system_template; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_instances.is_system_template IS 'When true, this strategy is a system template visible to all users for use in profiles';


--
-- Name: strategy_portfolio; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE strategy_portfolio; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.strategy_portfolio IS 'Per-strategy performance and risk metrics';


--
-- Name: strategy_signals; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE strategy_signals; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.strategy_signals IS 'Trading strategy signals and execution results';


--
-- Name: strategy_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(128) NOT NULL,
    slug character varying(64) NOT NULL,
    description text,
    strategy_family character varying(64) DEFAULT 'scalper'::character varying NOT NULL,
    timeframe character varying(16) DEFAULT '1m'::character varying,
    default_profile_bundle jsonb DEFAULT '{}'::jsonb NOT NULL,
    default_risk_config jsonb DEFAULT '{"maxLeverage": 1, "leverageMode": "isolated", "maxPositions": 4, "maxDailyLossPct": 5, "positionSizePct": 10, "maxTotalExposurePct": 40}'::jsonb,
    default_execution_config jsonb DEFAULT '{"stopLossPct": 2, "takeProfitPct": 5, "trailingStopPct": 1, "defaultOrderType": "market", "maxHoldTimeHours": 24, "trailingStopEnabled": false}'::jsonb,
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


--
-- Name: TABLE strategy_templates; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.strategy_templates IS 'Strategy templates define trading logic and default parameters';


--
-- Name: COLUMN strategy_templates.default_profile_bundle; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_templates.default_profile_bundle IS 'Chessboard profiles and indicator configurations';


--
-- Name: COLUMN strategy_templates.is_system; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_templates.is_system IS 'System templates are read-only for regular users';


--
-- Name: symbol_data_health; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE symbol_data_health; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.symbol_data_health IS 'Current health status per symbol';


--
-- Name: symbol_locks; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE symbol_locks; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.symbol_locks IS 'Symbol ownership locks for TEAM/PROP modes - prevents bot conflicts';


--
-- Name: COLUMN symbol_locks.lease_heartbeat_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.symbol_locks.lease_heartbeat_at IS 'Updated by running bot; expired leases can be reclaimed';


--
-- Name: tenant_risk_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_risk_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    max_daily_loss_pct numeric(5,2) DEFAULT 10.00,
    max_daily_loss_usd numeric(20,2),
    max_total_exposure_pct numeric(5,2) DEFAULT 100.00,
    max_single_position_pct numeric(5,2) DEFAULT 25.00,
    max_per_symbol_exposure_pct numeric(5,2) DEFAULT 50.00,
    max_leverage numeric(5,2) DEFAULT 10.00,
    allowed_leverage_levels integer[] DEFAULT ARRAY[1, 2, 3, 5, 10],
    max_concurrent_positions integer DEFAULT 10,
    max_concurrent_bots integer DEFAULT 1,
    max_symbols integer DEFAULT 20,
    total_capital_limit_usd numeric(20,2),
    min_reserve_pct numeric(5,2) DEFAULT 10.00,
    live_trading_enabled boolean DEFAULT false,
    allowed_environments text[] DEFAULT ARRAY['dev'::text, 'paper'::text],
    allowed_exchanges text[] DEFAULT ARRAY['binance'::text, 'okx'::text, 'bybit'::text],
    trading_hours_enabled boolean DEFAULT false,
    trading_start_time time without time zone,
    trading_end_time time without time zone,
    trading_days text[] DEFAULT ARRAY['mon'::text, 'tue'::text, 'wed'::text, 'thu'::text, 'fri'::text],
    timezone character varying(64) DEFAULT 'UTC'::character varying,
    circuit_breaker_enabled boolean DEFAULT true,
    circuit_breaker_loss_pct numeric(5,2) DEFAULT 5.00,
    circuit_breaker_cooldown_minutes integer DEFAULT 60,
    policy_version integer DEFAULT 1,
    notes text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_reviewed_at timestamp with time zone
);


--
-- Name: TABLE tenant_risk_policies; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tenant_risk_policies IS 'Account-level risk limits that cap all bot configurations';


--
-- Name: COLUMN tenant_risk_policies.max_daily_loss_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant_risk_policies.max_daily_loss_pct IS 'Global daily drawdown limit - bots cannot exceed this';


--
-- Name: COLUMN tenant_risk_policies.max_leverage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant_risk_policies.max_leverage IS 'Global leverage cap - per-bot leverage cannot exceed this';


--
-- Name: COLUMN tenant_risk_policies.live_trading_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant_risk_policies.live_trading_enabled IS 'User must explicitly enable live trading';


--
-- Name: COLUMN tenant_risk_policies.circuit_breaker_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant_risk_policies.circuit_breaker_enabled IS 'Auto-pause trading after significant loss';


--
-- Name: trade_costs; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE trade_costs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trade_costs IS 'Per-trade cost breakdown (slippage, fees, funding)';


--
-- Name: trades; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trades (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    portfolio_id uuid,
    external_id character varying(100),
    token character varying(20) NOT NULL,
    side public.trade_side NOT NULL,
    order_type public.order_type DEFAULT 'market'::public.order_type,
    quantity numeric(20,8) NOT NULL,
    price numeric(20,8) NOT NULL,
    total_value numeric(20,8) NOT NULL,
    fees numeric(20,8) DEFAULT 0.00,
    stop_loss numeric(20,8),
    take_profit numeric(20,8),
    status public.trade_status DEFAULT 'open'::public.trade_status,
    entry_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    exit_time timestamp without time zone,
    exit_price numeric(20,8),
    exit_reason character varying(100),
    pnl numeric(20,8),
    pnl_percentage numeric(10,4),
    ai_reasoning text,
    strategy character varying(100),
    exchange_name character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    exchange_account_id uuid,
    bot_id uuid,
    profile_id uuid,
    profile_version integer,
    trace_id uuid
);


--
-- Name: TABLE trades; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trades IS 'Individual trades executed in portfolios';


--
-- Name: trading_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trading_accounts (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    exchange_name character varying(50) NOT NULL,
    account_name character varying(100),
    api_key_encrypted text,
    api_secret_encrypted text,
    is_active boolean DEFAULT false,
    last_used timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: trading_activity; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE trading_activity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trading_activity IS 'Stores all trading decisions, orders, and activity for audit trail and analysis';


--
-- Name: trading_decisions; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: user_chessboard_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_chessboard_profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
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


--
-- Name: TABLE user_chessboard_profiles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_chessboard_profiles IS 'User-customizable trading profiles with strategy composition, risk controls, and market gates';


--
-- Name: COLUMN user_chessboard_profiles.environment; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.environment IS 'Dev for testing, Paper for paper trading, Live for real trading';


--
-- Name: COLUMN user_chessboard_profiles.strategy_composition; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.strategy_composition IS 'Array of strategy instances with weights and priorities';


--
-- Name: COLUMN user_chessboard_profiles.risk_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.risk_config IS 'Risk management settings for this profile';


--
-- Name: COLUMN user_chessboard_profiles.conditions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.conditions IS 'Market condition gates that must be met for profile to trade';


--
-- Name: COLUMN user_chessboard_profiles.lifecycle; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.lifecycle IS 'Trading lifecycle rules like cooldowns and loss limits';


--
-- Name: COLUMN user_chessboard_profiles.execution; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.execution IS 'Order execution preferences';


--
-- Name: COLUMN user_chessboard_profiles.is_system_template; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_chessboard_profiles.is_system_template IS 'When true, this profile is a system template visible to all users for cloning';


--
-- Name: user_exchange_credentials; Type: TABLE; Schema: public; Owner: -
--

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
    is_testnet boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    risk_config jsonb DEFAULT '{"maxLeverage": 1, "leverageMode": "isolated", "maxPositions": 4, "maxDailyLossPct": 5.0, "positionSizePct": 10.0, "maxTotalExposurePct": 40.0, "maxPositionsPerSymbol": 1, "maxDailyLossPerSymbolPct": 2.5}'::jsonb,
    execution_config jsonb DEFAULT '{"stopLossPct": 2.0, "takeProfitPct": 5.0, "trailingStopPct": 1.0, "defaultOrderType": "market", "maxHoldTimeHours": 24, "executionTimeoutSec": 5.0, "minTradeIntervalSec": 1.0, "trailingStopEnabled": false, "enableVolatilityFilter": true, "closePositionTimeoutSec": 15.0, "volatilityShockCooldownSec": 30.0}'::jsonb,
    ui_preferences jsonb DEFAULT '{"compactMode": false, "notifyOnTrade": true, "showPnlInHeader": true, "notifyOnStopLoss": true, "notifyOnTakeProfit": true, "defaultChartTimeframe": "1h"}'::jsonb,
    config_version integer DEFAULT 1,
    config_updated_at timestamp with time zone DEFAULT now(),
    exchange_balance numeric(20,8),
    balance_updated_at timestamp with time zone,
    account_connected boolean DEFAULT false,
    trading_capital numeric(20,8),
    balance_currency character varying(16) DEFAULT 'USDT'::character varying,
    connection_error text,
    balance_error text,
    CONSTRAINT valid_exchange CHECK (((exchange)::text = ANY ((ARRAY['okx'::character varying, 'binance'::character varying, 'bybit'::character varying])::text[])))
);


--
-- Name: TABLE user_exchange_credentials; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_exchange_credentials IS 'Per-user exchange API credential metadata (secrets stored externally)';


--
-- Name: COLUMN user_exchange_credentials.risk_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.risk_config IS 'Per-credential risk parameters: position sizing, leverage, loss limits';


--
-- Name: COLUMN user_exchange_credentials.execution_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.execution_config IS 'Per-credential execution settings: SL/TP, timeouts, order types';


--
-- Name: COLUMN user_exchange_credentials.ui_preferences; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.ui_preferences IS 'Per-credential UI preferences: notifications, display settings';


--
-- Name: COLUMN user_exchange_credentials.config_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.config_version IS 'Monotonically increasing version for config drift detection';


--
-- Name: COLUMN user_exchange_credentials.exchange_balance; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.exchange_balance IS 'Last fetched balance from exchange API';


--
-- Name: COLUMN user_exchange_credentials.balance_updated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.balance_updated_at IS 'Timestamp of last successful balance fetch';


--
-- Name: COLUMN user_exchange_credentials.account_connected; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.account_connected IS 'Whether we can reach the exchange account';


--
-- Name: COLUMN user_exchange_credentials.trading_capital; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_exchange_credentials.trading_capital IS 'User-set trading capital (must be <= exchange_balance)';


--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preferences (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    preferences jsonb DEFAULT '{}'::jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: user_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_sessions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid,
    token_hash character varying(255) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    user_agent text,
    ip_address inet
);


--
-- Name: TABLE user_sessions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_sessions IS 'Active user sessions for JWT invalidation';


--
-- Name: user_trade_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_trade_profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    active_credential_id uuid,
    active_exchange character varying(32),
    trading_mode character varying(32) DEFAULT 'paper'::character varying,
    token_lists jsonb DEFAULT '{}'::jsonb,
    default_max_positions integer DEFAULT 4,
    default_position_size_pct numeric(5,2) DEFAULT 10.00,
    default_max_daily_loss_pct numeric(5,2) DEFAULT 5.00,
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


--
-- Name: TABLE user_trade_profiles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_trade_profiles IS 'User trading configuration including active exchange and token selection';


--
-- Name: user_trading_settings; Type: TABLE; Schema: public; Owner: -
--

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
    enabled_tokens text[] DEFAULT ARRAY['BTCUSDT'::text, 'ETHUSDT'::text, 'SOLUSDT'::text, 'TAOUSDT'::text],
    day_trading_enabled boolean DEFAULT false,
    scalping_mode boolean DEFAULT false,
    trailing_stops_enabled boolean DEFAULT true,
    partial_profits_enabled boolean DEFAULT true,
    time_based_exits_enabled boolean DEFAULT true,
    multi_timeframe_confirmation boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    day_trading_max_holding_hours numeric(10,2) DEFAULT 8.0,
    day_trading_force_close_time time without time zone DEFAULT '15:45:00'::time without time zone,
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
    day_trading_start_time time without time zone DEFAULT '09:30:00'::time without time zone,
    day_trading_end_time time without time zone DEFAULT '15:30:00'::time without time zone,
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
    per_token_settings jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT user_trading_settings_leverage_mode_check CHECK (((leverage_mode)::text = ANY ((ARRAY['isolated'::character varying, 'cross'::character varying])::text[])))
);


--
-- Name: COLUMN user_trading_settings.day_trading_max_holding_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.day_trading_max_holding_hours IS 'Maximum hours to hold a position in day trading mode';


--
-- Name: COLUMN user_trading_settings.day_trading_force_close_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.day_trading_force_close_time IS 'Time to force close all positions (day trading mode)';


--
-- Name: COLUMN user_trading_settings.scalping_target_profit_percent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.scalping_target_profit_percent IS 'Target profit percentage for scalping trades';


--
-- Name: COLUMN user_trading_settings.trailing_stop_activation_percent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.trailing_stop_activation_percent IS 'Profit % needed before trailing stop activates';


--
-- Name: COLUMN user_trading_settings.partial_profit_levels; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.partial_profit_levels IS 'Array of profit taking levels with position % and target %';


--
-- Name: COLUMN user_trading_settings.time_exit_max_holding_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.time_exit_max_holding_hours IS 'Maximum hours to hold any position';


--
-- Name: COLUMN user_trading_settings.mtf_required_timeframes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.mtf_required_timeframes IS 'Timeframes required for multi-timeframe confirmation';


--
-- Name: COLUMN user_trading_settings.day_trading_start_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.day_trading_start_time IS 'Time to start opening new positions (day trading mode)';


--
-- Name: COLUMN user_trading_settings.day_trading_end_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.day_trading_end_time IS 'Time to stop opening new positions (day trading mode)';


--
-- Name: COLUMN user_trading_settings.day_trading_days_only; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.day_trading_days_only IS 'Only trade Monday-Friday (skip weekends)';


--
-- Name: COLUMN user_trading_settings.ai_filter_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.ai_filter_enabled IS 'Enable/disable AI regime analysis filter';


--
-- Name: COLUMN user_trading_settings.ai_filter_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.ai_filter_mode IS 'AI mode: filter_only (AI filters when to scalp) or full_control (AI makes all decisions)';


--
-- Name: COLUMN user_trading_settings.ai_swing_trading_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.ai_swing_trading_enabled IS 'Enable AI-driven swing trading (future feature)';


--
-- Name: COLUMN user_trading_settings.strategy_selection; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_trading_settings.strategy_selection IS 'Active strategy: amt_scalping, pure_technical, or ai_swing (future)';


--
-- Name: var_calculations; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: config_change_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_change_log ALTER COLUMN id SET DEFAULT nextval('public.config_change_log_id_seq'::regclass);


--
-- Name: fast_scalper_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fast_scalper_metrics ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_metrics_id_seq'::regclass);


--
-- Name: fast_scalper_positions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fast_scalper_positions ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_positions_id_seq'::regclass);


--
-- Name: fast_scalper_trades id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fast_scalper_trades ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_trades_id_seq'::regclass);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: approvals approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_pkey PRIMARY KEY (id);


--
-- Name: audit_log_exports audit_log_exports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log_exports
    ADD CONSTRAINT audit_log_exports_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: backtest_equity_curve backtest_equity_curve_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity_curve
    ADD CONSTRAINT backtest_equity_curve_pkey PRIMARY KEY (id);


--
-- Name: backtest_runs backtest_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_pkey PRIMARY KEY (id);


--
-- Name: backtest_trades backtest_trades_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_pkey PRIMARY KEY (id);


--
-- Name: bot_budgets bot_budgets_bot_instance_id_exchange_account_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_bot_instance_id_exchange_account_id_key UNIQUE (bot_instance_id, exchange_account_id);


--
-- Name: bot_budgets bot_budgets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_pkey PRIMARY KEY (id);


--
-- Name: bot_commands bot_commands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_pkey PRIMARY KEY (id);


--
-- Name: bot_config_actions bot_config_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_config_actions
    ADD CONSTRAINT bot_config_actions_pkey PRIMARY KEY (id);


--
-- Name: bot_configurations bot_configurations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_configurations
    ADD CONSTRAINT bot_configurations_pkey PRIMARY KEY (id);


--
-- Name: bot_exchange_config_versions bot_exchange_config_versions_bot_exchange_config_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_bot_exchange_config_id_version_key UNIQUE (bot_exchange_config_id, version_number);


--
-- Name: bot_exchange_config_versions bot_exchange_config_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_pkey PRIMARY KEY (id);


--
-- Name: bot_exchange_configs bot_exchange_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_pkey PRIMARY KEY (id);


--
-- Name: bot_instances bot_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_pkey PRIMARY KEY (id);


--
-- Name: bot_pool_assignments bot_pool_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_pool_assignments
    ADD CONSTRAINT bot_pool_assignments_pkey PRIMARY KEY (id);


--
-- Name: bot_profile_versions bot_profile_versions_bot_profile_id_version_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_profile_versions
    ADD CONSTRAINT bot_profile_versions_bot_profile_id_version_number_key UNIQUE (bot_profile_id, version_number);


--
-- Name: bot_profile_versions bot_profile_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_profile_versions
    ADD CONSTRAINT bot_profile_versions_pkey PRIMARY KEY (id);


--
-- Name: bot_profiles bot_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_profiles
    ADD CONSTRAINT bot_profiles_pkey PRIMARY KEY (id);


--
-- Name: bot_symbol_configs bot_symbol_configs_bot_exchange_config_id_symbol_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_symbol_configs
    ADD CONSTRAINT bot_symbol_configs_bot_exchange_config_id_symbol_key UNIQUE (bot_exchange_config_id, symbol);


--
-- Name: bot_symbol_configs bot_symbol_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_symbol_configs
    ADD CONSTRAINT bot_symbol_configs_pkey PRIMARY KEY (id);


--
-- Name: bot_version_sections bot_version_sections_bot_profile_version_id_section_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_version_sections
    ADD CONSTRAINT bot_version_sections_bot_profile_version_id_section_key UNIQUE (bot_profile_version_id, section);


--
-- Name: bot_version_sections bot_version_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_version_sections
    ADD CONSTRAINT bot_version_sections_pkey PRIMARY KEY (id);


--
-- Name: capacity_analysis capacity_analysis_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capacity_analysis
    ADD CONSTRAINT capacity_analysis_pkey PRIMARY KEY (id);


--
-- Name: capacity_analysis capacity_analysis_profile_id_notional_bucket_period_start_p_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.capacity_analysis
    ADD CONSTRAINT capacity_analysis_profile_id_notional_bucket_period_start_p_key UNIQUE (profile_id, notional_bucket, period_start, period_end);


--
-- Name: component_var component_var_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.component_var
    ADD CONSTRAINT component_var_pkey PRIMARY KEY (id);


--
-- Name: config_audit_log config_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_audit_log
    ADD CONSTRAINT config_audit_log_pkey PRIMARY KEY (id);


--
-- Name: config_blocks config_blocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_blocks
    ADD CONSTRAINT config_blocks_pkey PRIMARY KEY (id);


--
-- Name: config_change_log config_change_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_change_log
    ADD CONSTRAINT config_change_log_pkey PRIMARY KEY (id);


--
-- Name: config_diffs config_diffs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_diffs
    ADD CONSTRAINT config_diffs_pkey PRIMARY KEY (id);


--
-- Name: config_environments config_environments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_environments
    ADD CONSTRAINT config_environments_pkey PRIMARY KEY (id);


--
-- Name: config_items config_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_items
    ADD CONSTRAINT config_items_pkey PRIMARY KEY (id);


--
-- Name: config_sets config_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_sets
    ADD CONSTRAINT config_sets_pkey PRIMARY KEY (id);


--
-- Name: config_versions config_versions_config_set_id_version_semver_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_config_set_id_version_semver_key UNIQUE (config_set_id, version_semver);


--
-- Name: config_versions config_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_pkey PRIMARY KEY (id);


--
-- Name: cost_aggregation cost_aggregation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_aggregation
    ADD CONSTRAINT cost_aggregation_pkey PRIMARY KEY (id);


--
-- Name: cost_aggregation cost_aggregation_symbol_profile_id_period_type_period_start_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_aggregation
    ADD CONSTRAINT cost_aggregation_symbol_profile_id_period_type_period_start_key UNIQUE (symbol, profile_id, period_type, period_start);


--
-- Name: credential_balance_history credential_balance_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_balance_history
    ADD CONSTRAINT credential_balance_history_pkey PRIMARY KEY (id);


--
-- Name: credential_config_audit credential_config_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_config_audit
    ADD CONSTRAINT credential_config_audit_pkey PRIMARY KEY (id);


--
-- Name: data_quality_alerts data_quality_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_alerts
    ADD CONSTRAINT data_quality_alerts_pkey PRIMARY KEY (id);


--
-- Name: data_quality_metrics data_quality_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_metrics
    ADD CONSTRAINT data_quality_metrics_pkey PRIMARY KEY (id);


--
-- Name: data_quality_metrics data_quality_metrics_symbol_timeframe_date_idx; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_quality_metrics
    ADD CONSTRAINT data_quality_metrics_symbol_timeframe_date_idx UNIQUE (symbol, timeframe, metric_date);


--
-- Name: decision_traces decision_traces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.decision_traces
    ADD CONSTRAINT decision_traces_pkey PRIMARY KEY (id);


--
-- Name: equity_curves equity_curves_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_pkey PRIMARY KEY (id);


--
-- Name: equity_curves equity_curves_portfolio_id_timestamp_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_portfolio_id_timestamp_key UNIQUE (portfolio_id, "timestamp");


--
-- Name: exchange_accounts exchange_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_pkey PRIMARY KEY (id);


--
-- Name: exchange_accounts exchange_accounts_tenant_id_venue_label_environment_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_tenant_id_venue_label_environment_key UNIQUE (tenant_id, venue, label, environment);


--
-- Name: exchange_limits exchange_limits_exchange_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_limits
    ADD CONSTRAINT exchange_limits_exchange_key UNIQUE (exchange);


--
-- Name: exchange_limits exchange_limits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_limits
    ADD CONSTRAINT exchange_limits_pkey PRIMARY KEY (id);


--
-- Name: exchange_policies exchange_policies_exchange_account_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_exchange_account_id_key UNIQUE (exchange_account_id);


--
-- Name: exchange_policies exchange_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_pkey PRIMARY KEY (id);


--
-- Name: exchange_token_catalog exchange_token_catalog_exchange_symbol_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_token_catalog
    ADD CONSTRAINT exchange_token_catalog_exchange_symbol_key UNIQUE (exchange, symbol);


--
-- Name: exchange_token_catalog exchange_token_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_token_catalog
    ADD CONSTRAINT exchange_token_catalog_pkey PRIMARY KEY (id);


--
-- Name: fast_scalper_metrics fast_scalper_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fast_scalper_metrics
    ADD CONSTRAINT fast_scalper_metrics_pkey PRIMARY KEY (id, "timestamp");


--
-- Name: fast_scalper_positions fast_scalper_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fast_scalper_positions
    ADD CONSTRAINT fast_scalper_positions_pkey PRIMARY KEY (id);


--
-- Name: fast_scalper_trades fast_scalper_trades_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fast_scalper_trades
    ADD CONSTRAINT fast_scalper_trades_pkey PRIMARY KEY (id);


--
-- Name: feed_gaps feed_gaps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feed_gaps
    ADD CONSTRAINT feed_gaps_pkey PRIMARY KEY (id);


--
-- Name: generated_reports generated_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.generated_reports
    ADD CONSTRAINT generated_reports_pkey PRIMARY KEY (id);


--
-- Name: incidents incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (id);


--
-- Name: market_data market_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_data
    ADD CONSTRAINT market_data_pkey PRIMARY KEY (id);


--
-- Name: market_data market_data_token_timestamp_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_data
    ADD CONSTRAINT market_data_token_timestamp_key UNIQUE (token, "timestamp");


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);


--
-- Name: platform_users platform_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_users
    ADD CONSTRAINT platform_users_pkey PRIMARY KEY (id);


--
-- Name: portfolio_equity portfolio_equity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_equity
    ADD CONSTRAINT portfolio_equity_pkey PRIMARY KEY (id);


--
-- Name: portfolio_summary portfolio_summary_date_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_summary
    ADD CONSTRAINT portfolio_summary_date_unique UNIQUE (calculation_date);


--
-- Name: portfolio_summary portfolio_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_summary
    ADD CONSTRAINT portfolio_summary_pkey PRIMARY KEY (id);


--
-- Name: portfolios portfolios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolios
    ADD CONSTRAINT portfolios_pkey PRIMARY KEY (id);


--
-- Name: portfolios portfolios_user_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolios
    ADD CONSTRAINT portfolios_user_id_name_key UNIQUE (user_id, name);


--
-- Name: position_impacts position_impacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_impacts
    ADD CONSTRAINT position_impacts_pkey PRIMARY KEY (id);


--
-- Name: position_updates position_updates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_updates
    ADD CONSTRAINT position_updates_pkey PRIMARY KEY (id);


--
-- Name: positions positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (id);


--
-- Name: profile_versions profile_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_pkey PRIMARY KEY (id);


--
-- Name: profile_versions profile_versions_profile_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_profile_id_version_key UNIQUE (profile_id, version);


--
-- Name: promotion_history promotion_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotion_history
    ADD CONSTRAINT promotion_history_pkey PRIMARY KEY (id);


--
-- Name: promotions promotions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_pkey PRIMARY KEY (id);


--
-- Name: replay_sessions replay_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_sessions
    ADD CONSTRAINT replay_sessions_pkey PRIMARY KEY (id);


--
-- Name: replay_snapshots replay_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_snapshots
    ADD CONSTRAINT replay_snapshots_pkey PRIMARY KEY (id);


--
-- Name: replay_snapshots replay_snapshots_symbol_timestamp_idx; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_snapshots
    ADD CONSTRAINT replay_snapshots_symbol_timestamp_idx UNIQUE (symbol, "timestamp");


--
-- Name: report_templates report_templates_name_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_templates
    ADD CONSTRAINT report_templates_name_unique UNIQUE (name);


--
-- Name: report_templates report_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.report_templates
    ADD CONSTRAINT report_templates_pkey PRIMARY KEY (id);


--
-- Name: retention_policies retention_policies_log_type_action_category_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retention_policies
    ADD CONSTRAINT retention_policies_log_type_action_category_key UNIQUE (log_type, action_category);


--
-- Name: retention_policies retention_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.retention_policies
    ADD CONSTRAINT retention_policies_pkey PRIMARY KEY (id);


--
-- Name: risk_metrics_aggregation risk_metrics_aggregation_period_type_period_start_portfolio_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_metrics_aggregation
    ADD CONSTRAINT risk_metrics_aggregation_period_type_period_start_portfolio_key UNIQUE (period_type, period_start, portfolio_id, symbol, profile_id);


--
-- Name: risk_metrics_aggregation risk_metrics_aggregation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_metrics_aggregation
    ADD CONSTRAINT risk_metrics_aggregation_pkey PRIMARY KEY (id);


--
-- Name: scenario_results scenario_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_results
    ADD CONSTRAINT scenario_results_pkey PRIMARY KEY (id);


--
-- Name: strategy_correlation strategy_correlation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_correlation
    ADD CONSTRAINT strategy_correlation_pkey PRIMARY KEY (id);


--
-- Name: strategy_correlation strategy_correlation_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_correlation
    ADD CONSTRAINT strategy_correlation_unique UNIQUE (strategy_a, strategy_b, calculation_date);


--
-- Name: strategy_instances strategy_instances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_instances
    ADD CONSTRAINT strategy_instances_pkey PRIMARY KEY (id);


--
-- Name: strategy_portfolio strategy_portfolio_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_portfolio
    ADD CONSTRAINT strategy_portfolio_pkey PRIMARY KEY (id);


--
-- Name: strategy_portfolio strategy_portfolio_strategy_date_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_portfolio
    ADD CONSTRAINT strategy_portfolio_strategy_date_unique UNIQUE (strategy_name, calculation_date);


--
-- Name: strategy_templates strategy_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_templates
    ADD CONSTRAINT strategy_templates_pkey PRIMARY KEY (id);


--
-- Name: strategy_templates strategy_templates_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_templates
    ADD CONSTRAINT strategy_templates_slug_key UNIQUE (slug);


--
-- Name: symbol_data_health symbol_data_health_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_data_health
    ADD CONSTRAINT symbol_data_health_pkey PRIMARY KEY (symbol);


--
-- Name: symbol_locks symbol_locks_exchange_account_id_environment_symbol_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_exchange_account_id_environment_symbol_key UNIQUE (exchange_account_id, environment, symbol);


--
-- Name: symbol_locks symbol_locks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_pkey PRIMARY KEY (id);


--
-- Name: tenant_risk_policies tenant_risk_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_risk_policies
    ADD CONSTRAINT tenant_risk_policies_pkey PRIMARY KEY (id);


--
-- Name: tenant_risk_policies tenant_risk_policies_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_risk_policies
    ADD CONSTRAINT tenant_risk_policies_user_id_key UNIQUE (user_id);


--
-- Name: trade_costs trade_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_costs
    ADD CONSTRAINT trade_costs_pkey PRIMARY KEY (id);


--
-- Name: trades trades_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_pkey PRIMARY KEY (id);


--
-- Name: trading_accounts trading_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_accounts
    ADD CONSTRAINT trading_accounts_pkey PRIMARY KEY (id);


--
-- Name: trading_activity trading_activity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_pkey PRIMARY KEY (id);


--
-- Name: trading_decisions trading_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_pkey PRIMARY KEY (id);


--
-- Name: user_chessboard_profiles user_chessboard_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_pkey PRIMARY KEY (id);


--
-- Name: user_chessboard_profiles user_chessboard_profiles_user_id_name_environment_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_user_id_name_environment_key UNIQUE (user_id, name, environment);


--
-- Name: user_exchange_credentials user_exchange_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_exchange_credentials
    ADD CONSTRAINT user_exchange_credentials_pkey PRIMARY KEY (id);


--
-- Name: user_exchange_credentials user_exchange_credentials_user_id_exchange_label_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_exchange_credentials
    ADD CONSTRAINT user_exchange_credentials_user_id_exchange_label_key UNIQUE (user_id, exchange, label);


--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (id);


--
-- Name: user_sessions user_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_pkey PRIMARY KEY (id);


--
-- Name: user_trade_profiles user_trade_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_pkey PRIMARY KEY (id);


--
-- Name: user_trade_profiles user_trade_profiles_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_user_id_key UNIQUE (user_id);


--
-- Name: user_trading_settings user_trading_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trading_settings
    ADD CONSTRAINT user_trading_settings_pkey PRIMARY KEY (id);


--
-- Name: user_trading_settings user_trading_settings_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trading_settings
    ADD CONSTRAINT user_trading_settings_user_id_key UNIQUE (user_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: var_calculations var_calculations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.var_calculations
    ADD CONSTRAINT var_calculations_pkey PRIMARY KEY (id);


--
-- Name: _hyper_11_12_chunk_events_timestamp_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_11_12_chunk_events_timestamp_idx ON _timescaledb_internal._hyper_11_12_chunk USING btree ("timestamp" DESC);


--
-- Name: _hyper_11_12_chunk_idx_events_sequence; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_11_12_chunk_idx_events_sequence ON _timescaledb_internal._hyper_11_12_chunk USING btree (sequence);


--
-- Name: _hyper_11_12_chunk_idx_events_type_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_11_12_chunk_idx_events_type_symbol_time ON _timescaledb_internal._hyper_11_12_chunk USING btree (event_type, symbol, "timestamp" DESC);


--
-- Name: _hyper_11_9_chunk_events_timestamp_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_11_9_chunk_events_timestamp_idx ON _timescaledb_internal._hyper_11_9_chunk USING btree ("timestamp" DESC);


--
-- Name: _hyper_11_9_chunk_idx_events_sequence; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_11_9_chunk_idx_events_sequence ON _timescaledb_internal._hyper_11_9_chunk USING btree (sequence);


--
-- Name: _hyper_11_9_chunk_idx_events_type_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_11_9_chunk_idx_events_type_symbol_time ON _timescaledb_internal._hyper_11_9_chunk USING btree (event_type, symbol, "timestamp" DESC);


--
-- Name: _hyper_1_11_chunk_idx_market_trades_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_11_chunk_idx_market_trades_exchange ON _timescaledb_internal._hyper_1_11_chunk USING btree (exchange);


--
-- Name: _hyper_1_11_chunk_idx_market_trades_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_11_chunk_idx_market_trades_symbol_time ON _timescaledb_internal._hyper_1_11_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_1_11_chunk_idx_market_trades_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_11_chunk_idx_market_trades_trade_id ON _timescaledb_internal._hyper_1_11_chunk USING btree (trade_id);


--
-- Name: _hyper_1_11_chunk_market_trades_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_11_chunk_market_trades_time_idx ON _timescaledb_internal._hyper_1_11_chunk USING btree ("time" DESC);


--
-- Name: _hyper_1_14_chunk_idx_market_trades_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_14_chunk_idx_market_trades_exchange ON _timescaledb_internal._hyper_1_14_chunk USING btree (exchange);


--
-- Name: _hyper_1_14_chunk_idx_market_trades_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_14_chunk_idx_market_trades_symbol_time ON _timescaledb_internal._hyper_1_14_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_1_14_chunk_idx_market_trades_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_14_chunk_idx_market_trades_trade_id ON _timescaledb_internal._hyper_1_14_chunk USING btree (trade_id);


--
-- Name: _hyper_1_14_chunk_market_trades_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_14_chunk_market_trades_time_idx ON _timescaledb_internal._hyper_1_14_chunk USING btree ("time" DESC);


--
-- Name: _hyper_1_1_chunk_idx_market_trades_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_market_trades_exchange ON _timescaledb_internal._hyper_1_1_chunk USING btree (exchange);


--
-- Name: _hyper_1_1_chunk_idx_market_trades_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_market_trades_symbol_time ON _timescaledb_internal._hyper_1_1_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_1_1_chunk_idx_market_trades_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_idx_market_trades_trade_id ON _timescaledb_internal._hyper_1_1_chunk USING btree (trade_id);


--
-- Name: _hyper_1_1_chunk_market_trades_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_1_chunk_market_trades_time_idx ON _timescaledb_internal._hyper_1_1_chunk USING btree ("time" DESC);


--
-- Name: _hyper_1_3_chunk_idx_market_trades_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_market_trades_exchange ON _timescaledb_internal._hyper_1_3_chunk USING btree (exchange);


--
-- Name: _hyper_1_3_chunk_idx_market_trades_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_market_trades_symbol_time ON _timescaledb_internal._hyper_1_3_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_1_3_chunk_idx_market_trades_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_market_trades_trade_id ON _timescaledb_internal._hyper_1_3_chunk USING btree (trade_id);


--
-- Name: _hyper_1_3_chunk_market_trades_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_market_trades_time_idx ON _timescaledb_internal._hyper_1_3_chunk USING btree ("time" DESC);


--
-- Name: _hyper_1_6_chunk_idx_market_trades_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_market_trades_exchange ON _timescaledb_internal._hyper_1_6_chunk USING btree (exchange);


--
-- Name: _hyper_1_6_chunk_idx_market_trades_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_market_trades_symbol_time ON _timescaledb_internal._hyper_1_6_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_1_6_chunk_idx_market_trades_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_idx_market_trades_trade_id ON _timescaledb_internal._hyper_1_6_chunk USING btree (trade_id);


--
-- Name: _hyper_1_6_chunk_market_trades_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_6_chunk_market_trades_time_idx ON _timescaledb_internal._hyper_1_6_chunk USING btree ("time" DESC);


--
-- Name: _hyper_1_7_chunk_idx_market_trades_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_market_trades_exchange ON _timescaledb_internal._hyper_1_7_chunk USING btree (exchange);


--
-- Name: _hyper_1_7_chunk_idx_market_trades_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_market_trades_symbol_time ON _timescaledb_internal._hyper_1_7_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_1_7_chunk_idx_market_trades_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_idx_market_trades_trade_id ON _timescaledb_internal._hyper_1_7_chunk USING btree (trade_id);


--
-- Name: _hyper_1_7_chunk_market_trades_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_7_chunk_market_trades_time_idx ON _timescaledb_internal._hyper_1_7_chunk USING btree ("time" DESC);


--
-- Name: _hyper_2_13_chunk_idx_order_book_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_2_13_chunk_idx_order_book_exchange ON _timescaledb_internal._hyper_2_13_chunk USING btree (exchange);


--
-- Name: _hyper_2_13_chunk_idx_order_book_symbol_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_2_13_chunk_idx_order_book_symbol_time ON _timescaledb_internal._hyper_2_13_chunk USING btree (symbol, "time" DESC);


--
-- Name: _hyper_2_13_chunk_order_book_snapshots_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_2_13_chunk_order_book_snapshots_time_idx ON _timescaledb_internal._hyper_2_13_chunk USING btree ("time" DESC);


--
-- Name: _hyper_3_10_chunk_idx_candles_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_10_chunk_idx_candles_exchange ON _timescaledb_internal._hyper_3_10_chunk USING btree (exchange);


--
-- Name: _hyper_3_10_chunk_idx_candles_symbol_timeframe_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_10_chunk_idx_candles_symbol_timeframe_time ON _timescaledb_internal._hyper_3_10_chunk USING btree (symbol, timeframe, "time" DESC);


--
-- Name: _hyper_3_10_chunk_market_candles_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_10_chunk_market_candles_time_idx ON _timescaledb_internal._hyper_3_10_chunk USING btree ("time" DESC);


--
-- Name: _hyper_3_15_chunk_idx_candles_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_15_chunk_idx_candles_exchange ON _timescaledb_internal._hyper_3_15_chunk USING btree (exchange);


--
-- Name: _hyper_3_15_chunk_idx_candles_symbol_timeframe_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_15_chunk_idx_candles_symbol_timeframe_time ON _timescaledb_internal._hyper_3_15_chunk USING btree (symbol, timeframe, "time" DESC);


--
-- Name: _hyper_3_15_chunk_market_candles_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_15_chunk_market_candles_time_idx ON _timescaledb_internal._hyper_3_15_chunk USING btree ("time" DESC);


--
-- Name: _hyper_3_2_chunk_idx_candles_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_idx_candles_exchange ON _timescaledb_internal._hyper_3_2_chunk USING btree (exchange);


--
-- Name: _hyper_3_2_chunk_idx_candles_symbol_timeframe_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_idx_candles_symbol_timeframe_time ON _timescaledb_internal._hyper_3_2_chunk USING btree (symbol, timeframe, "time" DESC);


--
-- Name: _hyper_3_2_chunk_market_candles_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_market_candles_time_idx ON _timescaledb_internal._hyper_3_2_chunk USING btree ("time" DESC);


--
-- Name: _hyper_3_4_chunk_idx_candles_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_4_chunk_idx_candles_exchange ON _timescaledb_internal._hyper_3_4_chunk USING btree (exchange);


--
-- Name: _hyper_3_4_chunk_idx_candles_symbol_timeframe_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_4_chunk_idx_candles_symbol_timeframe_time ON _timescaledb_internal._hyper_3_4_chunk USING btree (symbol, timeframe, "time" DESC);


--
-- Name: _hyper_3_4_chunk_market_candles_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_4_chunk_market_candles_time_idx ON _timescaledb_internal._hyper_3_4_chunk USING btree ("time" DESC);


--
-- Name: _hyper_3_5_chunk_idx_candles_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_5_chunk_idx_candles_exchange ON _timescaledb_internal._hyper_3_5_chunk USING btree (exchange);


--
-- Name: _hyper_3_5_chunk_idx_candles_symbol_timeframe_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_5_chunk_idx_candles_symbol_timeframe_time ON _timescaledb_internal._hyper_3_5_chunk USING btree (symbol, timeframe, "time" DESC);


--
-- Name: _hyper_3_5_chunk_market_candles_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_5_chunk_market_candles_time_idx ON _timescaledb_internal._hyper_3_5_chunk USING btree ("time" DESC);


--
-- Name: _hyper_3_8_chunk_idx_candles_exchange; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_8_chunk_idx_candles_exchange ON _timescaledb_internal._hyper_3_8_chunk USING btree (exchange);


--
-- Name: _hyper_3_8_chunk_idx_candles_symbol_timeframe_time; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_8_chunk_idx_candles_symbol_timeframe_time ON _timescaledb_internal._hyper_3_8_chunk USING btree (symbol, timeframe, "time" DESC);


--
-- Name: _hyper_3_8_chunk_market_candles_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_8_chunk_market_candles_time_idx ON _timescaledb_internal._hyper_3_8_chunk USING btree ("time" DESC);


--
-- Name: amt_metrics_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX amt_metrics_time_idx ON public.amt_metrics USING btree ("time" DESC);


--
-- Name: events_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX events_timestamp_idx ON public.events USING btree ("timestamp" DESC);


--
-- Name: fast_scalper_metrics_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fast_scalper_metrics_timestamp_idx ON public.fast_scalper_metrics USING btree ("timestamp" DESC);


--
-- Name: idx_alerts_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_created_at ON public.alerts USING btree (created_at DESC);


--
-- Name: idx_alerts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_user_id ON public.alerts USING btree (user_id);


--
-- Name: idx_alerts_user_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_alerts_user_unread ON public.alerts USING btree (user_id, is_read) WHERE (is_read = false);


--
-- Name: idx_amt_symbol_timeframe_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_amt_symbol_timeframe_time ON public.amt_metrics USING btree (symbol, timeframe, "time" DESC);


--
-- Name: idx_approvals_promotion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_promotion ON public.approvals USING btree (promotion_id);


--
-- Name: idx_approvals_requested_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_requested_at ON public.approvals USING btree (requested_at DESC);


--
-- Name: idx_approvals_requested_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_requested_by ON public.approvals USING btree (requested_by);


--
-- Name: idx_approvals_risk_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_risk_level ON public.approvals USING btree (risk_level);


--
-- Name: idx_approvals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approvals_status ON public.approvals USING btree (status);


--
-- Name: idx_audit_log_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_action ON public.config_audit_log USING btree (action);


--
-- Name: idx_audit_log_action_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_action_category ON public.audit_log USING btree (action_category);


--
-- Name: idx_audit_log_action_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_action_type ON public.audit_log USING btree (action_type);


--
-- Name: idx_audit_log_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_created_at ON public.audit_log USING btree (created_at DESC);


--
-- Name: idx_audit_log_env; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_env ON public.config_audit_log USING btree (environment);


--
-- Name: idx_audit_log_exports_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_exports_created_at ON public.audit_log_exports USING btree (created_at DESC);


--
-- Name: idx_audit_log_exports_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_exports_status ON public.audit_log_exports USING btree (export_status);


--
-- Name: idx_audit_log_exports_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_exports_user_id ON public.audit_log_exports USING btree (user_id);


--
-- Name: idx_audit_log_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_resource ON public.config_audit_log USING btree (resource_type, resource_id);


--
-- Name: idx_audit_log_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_resource_id ON public.audit_log USING btree (resource_id);


--
-- Name: idx_audit_log_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_resource_type ON public.audit_log USING btree (resource_type);


--
-- Name: idx_audit_log_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_severity ON public.audit_log USING btree (severity);


--
-- Name: idx_audit_log_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_time ON public.config_audit_log USING btree (created_at DESC);


--
-- Name: idx_audit_log_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_user ON public.config_audit_log USING btree (user_id);


--
-- Name: idx_audit_log_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_user_id ON public.audit_log USING btree (user_id);


--
-- Name: idx_backtest_equity_curve_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_equity_curve_run_id ON public.backtest_equity_curve USING btree (backtest_run_id);


--
-- Name: idx_backtest_equity_curve_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_equity_curve_timestamp ON public.backtest_equity_curve USING btree ("timestamp");


--
-- Name: idx_backtest_runs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_created_at ON public.backtest_runs USING btree (created_at DESC);


--
-- Name: idx_backtest_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_status ON public.backtest_runs USING btree (status);


--
-- Name: idx_backtest_runs_strategy_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_strategy_id ON public.backtest_runs USING btree (strategy_id);


--
-- Name: idx_backtest_runs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_user_id ON public.backtest_runs USING btree (user_id);


--
-- Name: idx_backtest_trades_entry_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_trades_entry_time ON public.backtest_trades USING btree (entry_time);


--
-- Name: idx_backtest_trades_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_trades_run_id ON public.backtest_trades USING btree (backtest_run_id);


--
-- Name: idx_balance_history_credential; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_balance_history_credential ON public.credential_balance_history USING btree (credential_id, created_at DESC);


--
-- Name: idx_balance_history_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_balance_history_user ON public.credential_balance_history USING btree (user_id, created_at DESC);


--
-- Name: idx_bot_assignments_bot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_assignments_bot_id ON public.bot_pool_assignments USING btree (bot_id);


--
-- Name: idx_bot_assignments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_assignments_status ON public.bot_pool_assignments USING btree (status);


--
-- Name: idx_bot_assignments_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_assignments_user ON public.bot_pool_assignments USING btree (user_id);


--
-- Name: idx_bot_budgets_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_budgets_account ON public.bot_budgets USING btree (exchange_account_id);


--
-- Name: idx_bot_budgets_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_budgets_bot ON public.bot_budgets USING btree (bot_instance_id);


--
-- Name: idx_bot_commands_bot_instance; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_commands_bot_instance ON public.bot_commands USING btree (bot_instance_id);


--
-- Name: idx_bot_commands_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_commands_created ON public.bot_commands USING btree (created_at DESC);


--
-- Name: idx_bot_commands_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_commands_priority ON public.bot_commands USING btree (priority DESC, created_at) WHERE (status = 'pending'::public.bot_command_status);


--
-- Name: idx_bot_commands_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_commands_status ON public.bot_commands USING btree (status) WHERE (status = ANY (ARRAY['pending'::public.bot_command_status, 'processing'::public.bot_command_status]));


--
-- Name: idx_bot_commands_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_commands_user ON public.bot_commands USING btree (user_id);


--
-- Name: idx_bot_config_actions_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_config_actions_action ON public.bot_config_actions USING btree (action);


--
-- Name: idx_bot_config_actions_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_config_actions_profile ON public.bot_config_actions USING btree (bot_profile_id);


--
-- Name: idx_bot_exchange_configs_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_active ON public.bot_exchange_configs USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_bot_exchange_configs_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_bot ON public.bot_exchange_configs USING btree (bot_instance_id);


--
-- Name: idx_bot_exchange_configs_credential; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_credential ON public.bot_exchange_configs USING btree (credential_id);


--
-- Name: idx_bot_exchange_configs_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_deleted ON public.bot_exchange_configs USING btree (deleted_at) WHERE (deleted_at IS NOT NULL);


--
-- Name: idx_bot_exchange_configs_env; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_env ON public.bot_exchange_configs USING btree (environment);


--
-- Name: idx_bot_exchange_configs_exchange_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_exchange_account ON public.bot_exchange_configs USING btree (exchange_account_id);


--
-- Name: idx_bot_exchange_configs_mounted_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_mounted_profile ON public.bot_exchange_configs USING btree (mounted_profile_id) WHERE (mounted_profile_id IS NOT NULL);


--
-- Name: idx_bot_exchange_configs_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_exchange_configs_state ON public.bot_exchange_configs USING btree (state);


--
-- Name: idx_bot_exchange_configs_unique_combo; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_bot_exchange_configs_unique_combo ON public.bot_exchange_configs USING btree (bot_instance_id, COALESCE(exchange_account_id, credential_id), environment);


--
-- Name: idx_bot_instances_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_active ON public.bot_instances USING btree (user_id, is_active);


--
-- Name: idx_bot_instances_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_deleted ON public.bot_instances USING btree (deleted_at) WHERE (deleted_at IS NOT NULL);


--
-- Name: idx_bot_instances_exchange; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_exchange ON public.bot_instances USING btree (exchange_account_id);


--
-- Name: idx_bot_instances_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_role ON public.bot_instances USING btree (allocator_role);


--
-- Name: idx_bot_instances_running; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_running ON public.bot_instances USING btree (exchange_account_id) WHERE ((runtime_state)::text = 'running'::text);


--
-- Name: idx_bot_instances_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_state ON public.bot_instances USING btree (exchange_account_id, runtime_state);


--
-- Name: idx_bot_instances_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_template ON public.bot_instances USING btree (strategy_template_id);


--
-- Name: idx_bot_instances_unique_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_bot_instances_unique_name ON public.bot_instances USING btree (user_id, name) WHERE (deleted_at IS NULL);


--
-- Name: INDEX idx_bot_instances_unique_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON INDEX public.idx_bot_instances_unique_name IS 'Ensures unique bot names per user, excluding soft-deleted bots';


--
-- Name: idx_bot_instances_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_instances_user ON public.bot_instances USING btree (user_id);


--
-- Name: idx_bot_profile_versions_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_profile_versions_profile ON public.bot_profile_versions USING btree (bot_profile_id);


--
-- Name: idx_bot_profile_versions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_profile_versions_status ON public.bot_profile_versions USING btree (status);


--
-- Name: idx_bot_profiles_environment; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_profiles_environment ON public.bot_profiles USING btree (environment);


--
-- Name: idx_bot_profiles_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_profiles_status ON public.bot_profiles USING btree (status);


--
-- Name: idx_bot_symbol_configs_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_symbol_configs_enabled ON public.bot_symbol_configs USING btree (bot_exchange_config_id, enabled) WHERE (enabled = true);


--
-- Name: idx_bot_symbol_configs_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_symbol_configs_parent ON public.bot_symbol_configs USING btree (bot_exchange_config_id);


--
-- Name: idx_bot_symbol_configs_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bot_symbol_configs_symbol ON public.bot_symbol_configs USING btree (symbol);


--
-- Name: idx_candles_exchange; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candles_exchange ON public.market_candles USING btree (exchange);


--
-- Name: idx_candles_symbol_timeframe_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_candles_symbol_timeframe_time ON public.market_candles USING btree (symbol, timeframe, "time" DESC);


--
-- Name: idx_capacity_analysis_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_capacity_analysis_period ON public.capacity_analysis USING btree (period_start, period_end);


--
-- Name: idx_capacity_analysis_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_capacity_analysis_profile ON public.capacity_analysis USING btree (profile_id);


--
-- Name: idx_component_var_calc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_component_var_calc ON public.component_var USING btree (calculated_at DESC);


--
-- Name: idx_component_var_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_component_var_symbol ON public.component_var USING btree (symbol);


--
-- Name: idx_config_audit_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_audit_created ON public.credential_config_audit USING btree (created_at DESC);


--
-- Name: idx_config_audit_credential; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_audit_credential ON public.credential_config_audit USING btree (credential_id);


--
-- Name: idx_config_audit_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_audit_user ON public.credential_config_audit USING btree (user_id);


--
-- Name: idx_config_blocks_data_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_blocks_data_gin ON public.config_blocks USING gin (data);


--
-- Name: idx_config_blocks_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_config_blocks_lookup ON public.config_blocks USING btree (config_version_id, lower(block_type), lower(block_key));


--
-- Name: idx_config_change_log_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_change_log_version ON public.config_change_log USING btree (config_version_id, created_at DESC);


--
-- Name: idx_config_diffs_promotion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_diffs_promotion ON public.config_diffs USING btree (promotion_id);


--
-- Name: idx_config_diffs_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_diffs_source ON public.config_diffs USING btree (source_config_id);


--
-- Name: idx_config_diffs_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_diffs_target ON public.config_diffs USING btree (target_config_id);


--
-- Name: idx_config_environments_user_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_config_environments_user_name ON public.config_environments USING btree (user_id, lower(name));


--
-- Name: idx_config_items_version_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_config_items_version_key ON public.config_items USING btree (config_version_id, lower(key));


--
-- Name: idx_config_sets_user_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_config_sets_user_domain ON public.config_sets USING btree (user_id, lower(domain));


--
-- Name: idx_config_versions_active_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_config_versions_active_scope ON public.config_versions USING btree (config_set_id, COALESCE(environment_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE (status = 'active'::text);


--
-- Name: idx_config_versions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_created ON public.bot_exchange_config_versions USING btree (created_at DESC);


--
-- Name: idx_config_versions_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_parent ON public.bot_exchange_config_versions USING btree (bot_exchange_config_id);


--
-- Name: idx_config_versions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_status ON public.config_versions USING btree (config_set_id, status, created_at DESC);


--
-- Name: idx_cost_aggregation_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cost_aggregation_period ON public.cost_aggregation USING btree (period_type, period_start);


--
-- Name: idx_cost_aggregation_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cost_aggregation_profile ON public.cost_aggregation USING btree (profile_id);


--
-- Name: idx_cost_aggregation_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cost_aggregation_symbol ON public.cost_aggregation USING btree (symbol);


--
-- Name: idx_data_quality_alerts_detected; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_alerts_detected ON public.data_quality_alerts USING btree (detected_at DESC);


--
-- Name: idx_data_quality_alerts_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_alerts_severity ON public.data_quality_alerts USING btree (severity);


--
-- Name: idx_data_quality_alerts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_alerts_status ON public.data_quality_alerts USING btree (status);


--
-- Name: idx_data_quality_alerts_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_alerts_symbol ON public.data_quality_alerts USING btree (symbol);


--
-- Name: idx_data_quality_alerts_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_alerts_type ON public.data_quality_alerts USING btree (alert_type);


--
-- Name: idx_data_quality_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_score ON public.data_quality_metrics USING btree (quality_score);


--
-- Name: idx_data_quality_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_status ON public.data_quality_metrics USING btree (status);


--
-- Name: idx_data_quality_symbol_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_quality_symbol_date ON public.data_quality_metrics USING btree (symbol, metric_date DESC);


--
-- Name: idx_decision_traces_decision_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decision_traces_decision_type ON public.decision_traces USING btree (decision_type);


--
-- Name: idx_decision_traces_outcome; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decision_traces_outcome ON public.decision_traces USING btree (decision_outcome);


--
-- Name: idx_decision_traces_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decision_traces_symbol ON public.decision_traces USING btree (symbol);


--
-- Name: idx_decision_traces_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decision_traces_timestamp ON public.decision_traces USING btree ("timestamp" DESC);


--
-- Name: idx_decision_traces_trade_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_decision_traces_trade_id ON public.decision_traces USING btree (trade_id);


--
-- Name: idx_equity_curves_portfolio_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_equity_curves_portfolio_timestamp ON public.equity_curves USING btree (portfolio_id, "timestamp" DESC);


--
-- Name: idx_events_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_sequence ON public.events USING btree (sequence);


--
-- Name: idx_events_type_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_type_symbol_time ON public.events USING btree (event_type, symbol, "timestamp" DESC);


--
-- Name: idx_exchange_accounts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_accounts_status ON public.exchange_accounts USING btree (tenant_id, status);


--
-- Name: idx_exchange_accounts_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_accounts_tenant ON public.exchange_accounts USING btree (tenant_id);


--
-- Name: idx_exchange_accounts_venue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_accounts_venue ON public.exchange_accounts USING btree (venue);


--
-- Name: idx_exchange_creds_connected; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_creds_connected ON public.user_exchange_credentials USING btree (user_id, account_connected) WHERE (account_connected = true);


--
-- Name: idx_exchange_creds_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_creds_status ON public.user_exchange_credentials USING btree (status);


--
-- Name: idx_exchange_creds_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_creds_user ON public.user_exchange_credentials USING btree (user_id);


--
-- Name: idx_exchange_policies_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exchange_policies_account ON public.exchange_policies USING btree (exchange_account_id);


--
-- Name: idx_fast_scalper_metrics_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fast_scalper_metrics_user_time ON public.fast_scalper_metrics USING btree (user_id, "timestamp" DESC);


--
-- Name: idx_fast_scalper_positions_unique_open; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_fast_scalper_positions_unique_open ON public.fast_scalper_positions USING btree (user_id, symbol) WHERE (status = 'open'::text);


--
-- Name: idx_fast_scalper_positions_user_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fast_scalper_positions_user_symbol ON public.fast_scalper_positions USING btree (user_id, symbol, status);


--
-- Name: idx_fast_scalper_trades_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fast_scalper_trades_symbol ON public.fast_scalper_trades USING btree (symbol, exit_time DESC);


--
-- Name: idx_fast_scalper_trades_user_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fast_scalper_trades_user_time ON public.fast_scalper_trades USING btree (user_id, exit_time DESC);


--
-- Name: idx_feed_gaps_resolved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_gaps_resolved ON public.feed_gaps USING btree (resolved_at);


--
-- Name: idx_feed_gaps_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_gaps_severity ON public.feed_gaps USING btree (severity);


--
-- Name: idx_feed_gaps_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_gaps_symbol ON public.feed_gaps USING btree (symbol);


--
-- Name: idx_feed_gaps_time_range; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_gaps_time_range ON public.feed_gaps USING btree (gap_start_time, gap_end_time);


--
-- Name: idx_feed_gaps_timeframe; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feed_gaps_timeframe ON public.feed_gaps USING btree (timeframe);


--
-- Name: idx_generated_reports_generated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_generated_reports_generated ON public.generated_reports USING btree (generated_at DESC);


--
-- Name: idx_generated_reports_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_generated_reports_period ON public.generated_reports USING btree (period_start, period_end);


--
-- Name: idx_generated_reports_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_generated_reports_status ON public.generated_reports USING btree (status);


--
-- Name: idx_generated_reports_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_generated_reports_template ON public.generated_reports USING btree (template_id);


--
-- Name: idx_generated_reports_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_generated_reports_type ON public.generated_reports USING btree (report_type);


--
-- Name: idx_incidents_detected_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidents_detected_at ON public.incidents USING btree (detected_at DESC);


--
-- Name: idx_incidents_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidents_severity ON public.incidents USING btree (severity);


--
-- Name: idx_incidents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidents_status ON public.incidents USING btree (status);


--
-- Name: idx_incidents_time_range; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidents_time_range ON public.incidents USING btree (start_time, end_time);


--
-- Name: idx_incidents_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_incidents_type ON public.incidents USING btree (incident_type);


--
-- Name: idx_market_data_token_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_data_token_timestamp ON public.market_data USING btree (token, "timestamp" DESC);


--
-- Name: idx_market_trades_exchange; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_trades_exchange ON public.market_trades USING btree (exchange);


--
-- Name: idx_market_trades_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_trades_symbol_time ON public.market_trades USING btree (symbol, "time" DESC);


--
-- Name: idx_market_trades_trade_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_trades_trade_id ON public.market_trades USING btree (trade_id);


--
-- Name: idx_microstructure_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_microstructure_symbol_time ON public.microstructure_features USING btree (symbol, "time" DESC);


--
-- Name: idx_order_book_exchange; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_book_exchange ON public.order_book_snapshots USING btree (exchange);


--
-- Name: idx_order_book_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_book_symbol_time ON public.order_book_snapshots USING btree (symbol, "time" DESC);


--
-- Name: idx_orders_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_bot ON public.orders USING btree (bot_id);


--
-- Name: idx_orders_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_created_at ON public.orders USING btree (created_at);


--
-- Name: idx_orders_exchange_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_exchange_account ON public.orders USING btree (exchange_account_id);


--
-- Name: idx_orders_portfolio_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_portfolio_id ON public.orders USING btree (portfolio_id);


--
-- Name: idx_orders_symbol_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_symbol_status ON public.orders USING btree (symbol, status);


--
-- Name: idx_orders_trace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_trace ON public.orders USING btree (trace_id);


--
-- Name: idx_orders_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_user_status ON public.orders USING btree (user_id, status);


--
-- Name: idx_platform_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_platform_users_email ON public.platform_users USING btree (lower(email));


--
-- Name: idx_portfolio_equity_portfolio_id_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_equity_portfolio_id_timestamp ON public.portfolio_equity USING btree (portfolio_id, "timestamp" DESC);


--
-- Name: idx_portfolio_summary_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_summary_date ON public.portfolio_summary USING btree (calculation_date DESC);


--
-- Name: idx_portfolios_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolios_user_id ON public.portfolios USING btree (user_id);


--
-- Name: idx_position_impacts_scenario; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_impacts_scenario ON public.position_impacts USING btree (scenario_id);


--
-- Name: idx_position_impacts_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_impacts_symbol ON public.position_impacts USING btree (symbol);


--
-- Name: idx_position_updates_position_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_updates_position_id ON public.position_updates USING btree (position_id);


--
-- Name: idx_position_updates_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_updates_timestamp ON public.position_updates USING btree ("timestamp");


--
-- Name: idx_positions_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_bot ON public.positions USING btree (bot_id);


--
-- Name: idx_positions_exchange_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_exchange_account ON public.positions USING btree (exchange_account_id);


--
-- Name: idx_positions_leverage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_leverage ON public.positions USING btree (leverage);


--
-- Name: idx_positions_liquidation_price; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_liquidation_price ON public.positions USING btree (liquidation_price);


--
-- Name: idx_positions_margin_ratio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_margin_ratio ON public.positions USING btree (margin_ratio);


--
-- Name: idx_positions_opened_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_opened_at ON public.positions USING btree (opened_at);


--
-- Name: idx_positions_portfolio_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_portfolio_status ON public.positions USING btree (portfolio_id, status);


--
-- Name: idx_positions_symbol_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_symbol_status ON public.positions USING btree (symbol, status);


--
-- Name: idx_positions_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_positions_user_status ON public.positions USING btree (user_id, status);


--
-- Name: idx_profile_versions_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_versions_profile ON public.profile_versions USING btree (profile_id);


--
-- Name: idx_profile_versions_profile_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profile_versions_profile_version ON public.profile_versions USING btree (profile_id, version);


--
-- Name: idx_profiles_system_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_system_template ON public.user_chessboard_profiles USING btree (is_system_template) WHERE (is_system_template = true);


--
-- Name: idx_promotion_history_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotion_history_created_at ON public.promotion_history USING btree (created_at DESC);


--
-- Name: idx_promotion_history_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotion_history_event_type ON public.promotion_history USING btree (event_type);


--
-- Name: idx_promotion_history_promotion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotion_history_promotion ON public.promotion_history USING btree (promotion_id);


--
-- Name: idx_promotions_bot_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotions_bot_profile ON public.promotions USING btree (bot_profile_id);


--
-- Name: idx_promotions_requested_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotions_requested_at ON public.promotions USING btree (requested_at DESC);


--
-- Name: idx_promotions_requested_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotions_requested_by ON public.promotions USING btree (requested_by);


--
-- Name: idx_promotions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotions_status ON public.promotions USING btree (status);


--
-- Name: idx_promotions_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_promotions_type ON public.promotions USING btree (promotion_type);


--
-- Name: idx_replay_sessions_incident_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_sessions_incident_id ON public.replay_sessions USING btree (incident_id);


--
-- Name: idx_replay_sessions_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_sessions_symbol_time ON public.replay_sessions USING btree (symbol, start_time, end_time);


--
-- Name: idx_replay_snapshots_incident_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_snapshots_incident_id ON public.replay_snapshots USING btree (incident_id);


--
-- Name: idx_replay_snapshots_symbol_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_snapshots_symbol_timestamp ON public.replay_snapshots USING btree (symbol, "timestamp" DESC);


--
-- Name: idx_replay_snapshots_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_snapshots_type ON public.replay_snapshots USING btree (snapshot_type);


--
-- Name: idx_report_templates_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_templates_enabled ON public.report_templates USING btree (enabled);


--
-- Name: idx_report_templates_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_report_templates_type ON public.report_templates USING btree (report_type);


--
-- Name: idx_retention_policies_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_retention_policies_active ON public.retention_policies USING btree (is_active);


--
-- Name: idx_retention_policies_log_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_retention_policies_log_type ON public.retention_policies USING btree (log_type);


--
-- Name: idx_risk_metrics_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_metrics_period ON public.risk_metrics_aggregation USING btree (period_type, period_start);


--
-- Name: idx_risk_metrics_portfolio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_metrics_portfolio ON public.risk_metrics_aggregation USING btree (portfolio_id);


--
-- Name: idx_risk_metrics_symbol_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_metrics_symbol_profile ON public.risk_metrics_aggregation USING btree (symbol, profile_id);


--
-- Name: idx_scenario_results_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scenario_results_name ON public.scenario_results USING btree (scenario_name);


--
-- Name: idx_scenario_results_portfolio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scenario_results_portfolio ON public.scenario_results USING btree (portfolio_id);


--
-- Name: idx_scenario_results_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scenario_results_symbol ON public.scenario_results USING btree (symbol);


--
-- Name: idx_scenario_results_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scenario_results_timestamp ON public.scenario_results USING btree (calculation_timestamp DESC);


--
-- Name: idx_scenario_results_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scenario_results_type ON public.scenario_results USING btree (scenario_type);


--
-- Name: idx_signals_executed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_signals_executed ON public.strategy_signals USING btree (executed);


--
-- Name: idx_signals_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_signals_strategy ON public.strategy_signals USING btree (strategy_id);


--
-- Name: idx_signals_user_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_signals_user_symbol_time ON public.strategy_signals USING btree (user_id, symbol, "time" DESC);


--
-- Name: idx_strategy_correlation_a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_correlation_a ON public.strategy_correlation USING btree (strategy_a);


--
-- Name: idx_strategy_correlation_b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_correlation_b ON public.strategy_correlation USING btree (strategy_b);


--
-- Name: idx_strategy_correlation_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_correlation_date ON public.strategy_correlation USING btree (calculation_date DESC);


--
-- Name: idx_strategy_instances_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_instances_status ON public.strategy_instances USING btree (status);


--
-- Name: idx_strategy_instances_system_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_instances_system_template ON public.strategy_instances USING btree (is_system_template) WHERE (is_system_template = true);


--
-- Name: idx_strategy_instances_system_template_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_strategy_instances_system_template_unique ON public.strategy_instances USING btree (template_id) WHERE (is_system_template = true);


--
-- Name: idx_strategy_instances_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_instances_template ON public.strategy_instances USING btree (template_id);


--
-- Name: idx_strategy_instances_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_instances_user ON public.strategy_instances USING btree (user_id);


--
-- Name: idx_strategy_instances_user_name_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_strategy_instances_user_name_unique ON public.strategy_instances USING btree (user_id, name) WHERE (user_id IS NOT NULL);


--
-- Name: idx_strategy_instances_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_instances_user_status ON public.strategy_instances USING btree (user_id, status);


--
-- Name: idx_strategy_portfolio_bot_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_portfolio_bot_profile ON public.strategy_portfolio USING btree (bot_profile_id);


--
-- Name: idx_strategy_portfolio_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_portfolio_date ON public.strategy_portfolio USING btree (calculation_date DESC);


--
-- Name: idx_strategy_portfolio_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_portfolio_family ON public.strategy_portfolio USING btree (strategy_family);


--
-- Name: idx_strategy_portfolio_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_portfolio_name ON public.strategy_portfolio USING btree (strategy_name);


--
-- Name: idx_strategy_templates_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_templates_active ON public.strategy_templates USING btree (is_active);


--
-- Name: idx_strategy_templates_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_templates_family ON public.strategy_templates USING btree (strategy_family);


--
-- Name: idx_strategy_templates_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_templates_slug ON public.strategy_templates USING btree (slug);


--
-- Name: idx_symbol_data_health_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_data_health_score ON public.symbol_data_health USING btree (quality_score);


--
-- Name: idx_symbol_data_health_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_data_health_status ON public.symbol_data_health USING btree (health_status);


--
-- Name: idx_symbol_locks_account_env; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_locks_account_env ON public.symbol_locks USING btree (exchange_account_id, environment);


--
-- Name: idx_symbol_locks_heartbeat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_locks_heartbeat ON public.symbol_locks USING btree (lease_heartbeat_at);


--
-- Name: idx_symbol_locks_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_locks_owner ON public.symbol_locks USING btree (owner_bot_id);


--
-- Name: idx_tenant_risk_policies_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_risk_policies_user ON public.tenant_risk_policies USING btree (user_id);


--
-- Name: idx_token_catalog_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_token_catalog_active ON public.exchange_token_catalog USING btree (exchange, is_active);


--
-- Name: idx_token_catalog_exchange; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_token_catalog_exchange ON public.exchange_token_catalog USING btree (exchange);


--
-- Name: idx_trade_costs_profile_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_costs_profile_id ON public.trade_costs USING btree (profile_id);


--
-- Name: idx_trade_costs_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_costs_symbol ON public.trade_costs USING btree (symbol);


--
-- Name: idx_trade_costs_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_costs_timestamp ON public.trade_costs USING btree ("timestamp");


--
-- Name: idx_trade_costs_trade_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_costs_trade_id ON public.trade_costs USING btree (trade_id);


--
-- Name: idx_trade_profiles_active_config; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_profiles_active_config ON public.user_trade_profiles USING btree (active_bot_exchange_config_id);


--
-- Name: idx_trade_profiles_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_profiles_bot ON public.user_trade_profiles USING btree (assigned_bot_id);


--
-- Name: idx_trade_profiles_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_profiles_user ON public.user_trade_profiles USING btree (user_id);


--
-- Name: idx_trades_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trades_bot ON public.trades USING btree (bot_id);


--
-- Name: idx_trades_entry_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trades_entry_time ON public.trades USING btree (entry_time);


--
-- Name: idx_trades_exchange_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trades_exchange_account ON public.trades USING btree (exchange_account_id);


--
-- Name: idx_trades_portfolio_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trades_portfolio_id ON public.trades USING btree (portfolio_id);


--
-- Name: idx_trades_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trades_status ON public.trades USING btree (status);


--
-- Name: idx_trades_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trades_token ON public.trades USING btree (token);


--
-- Name: idx_trading_activity_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_activity_timestamp ON public.trading_activity USING btree ("timestamp" DESC);


--
-- Name: idx_trading_activity_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_activity_token ON public.trading_activity USING btree (token);


--
-- Name: idx_trading_activity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_activity_type ON public.trading_activity USING btree (type);


--
-- Name: idx_trading_activity_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_activity_user_id ON public.trading_activity USING btree (user_id);


--
-- Name: idx_trading_activity_user_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_activity_user_timestamp ON public.trading_activity USING btree (user_id, "timestamp" DESC);


--
-- Name: idx_trading_decisions_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_action ON public.trading_decisions USING btree (action);


--
-- Name: idx_trading_decisions_bot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_bot ON public.trading_decisions USING btree (bot_id);


--
-- Name: idx_trading_decisions_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_confidence ON public.trading_decisions USING btree (confidence) WHERE (confidence >= 0.5);


--
-- Name: idx_trading_decisions_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_created_at ON public.trading_decisions USING btree (created_at DESC);


--
-- Name: idx_trading_decisions_exchange_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_exchange_account ON public.trading_decisions USING btree (exchange_account_id);


--
-- Name: idx_trading_decisions_executed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_executed ON public.trading_decisions USING btree (executed);


--
-- Name: idx_trading_decisions_portfolio_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_portfolio_id ON public.trading_decisions USING btree (portfolio_id);


--
-- Name: idx_trading_decisions_user_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trading_decisions_user_token ON public.trading_decisions USING btree (user_id, token);


--
-- Name: idx_user_profiles_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_active ON public.user_chessboard_profiles USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_user_profiles_base; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_base ON public.user_chessboard_profiles USING btree (base_profile_id);


--
-- Name: idx_user_profiles_env; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_env ON public.user_chessboard_profiles USING btree (environment);


--
-- Name: idx_user_profiles_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_status ON public.user_chessboard_profiles USING btree (status);


--
-- Name: idx_user_profiles_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_user ON public.user_chessboard_profiles USING btree (user_id);


--
-- Name: idx_user_profiles_user_env; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_user_env ON public.user_chessboard_profiles USING btree (user_id, environment);


--
-- Name: idx_user_trading_settings_risk_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_trading_settings_risk_profile ON public.user_trading_settings USING btree (risk_profile);


--
-- Name: idx_user_trading_settings_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_trading_settings_strategy ON public.user_trading_settings USING btree (strategy_selection);


--
-- Name: idx_user_trading_settings_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_trading_settings_user_id ON public.user_trading_settings USING btree (user_id);


--
-- Name: idx_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_email ON public.users USING btree (email);


--
-- Name: idx_users_username; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_username ON public.users USING btree (username);


--
-- Name: idx_var_calculations_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_var_calculations_date ON public.var_calculations USING btree (calculation_date DESC);


--
-- Name: idx_var_calculations_portfolio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_var_calculations_portfolio ON public.var_calculations USING btree (portfolio_id);


--
-- Name: idx_var_calculations_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_var_calculations_profile ON public.var_calculations USING btree (profile_id);


--
-- Name: idx_var_calculations_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_var_calculations_symbol ON public.var_calculations USING btree (symbol);


--
-- Name: idx_var_calculations_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_var_calculations_timestamp ON public.var_calculations USING btree (calculation_timestamp DESC);


--
-- Name: idx_var_calculations_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_var_calculations_type ON public.var_calculations USING btree (calculation_type);


--
-- Name: market_candles_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_candles_time_idx ON public.market_candles USING btree ("time" DESC);


--
-- Name: market_trades_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_trades_time_idx ON public.market_trades USING btree ("time" DESC);


--
-- Name: microstructure_features_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX microstructure_features_time_idx ON public.microstructure_features USING btree ("time" DESC);


--
-- Name: order_book_snapshots_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_book_snapshots_time_idx ON public.order_book_snapshots USING btree ("time" DESC);


--
-- Name: strategy_signals_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX strategy_signals_time_idx ON public.strategy_signals USING btree ("time" DESC);


--
-- Name: exchange_accounts create_exchange_policy_on_account; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER create_exchange_policy_on_account AFTER INSERT ON public.exchange_accounts FOR EACH ROW EXECUTE FUNCTION public.create_default_exchange_policy();


--
-- Name: bot_exchange_configs trigger_assign_config_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_assign_config_version BEFORE INSERT OR UPDATE ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.assign_config_version_before();


--
-- Name: users trigger_create_default_risk_policy; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_create_default_risk_policy AFTER INSERT ON public.users FOR EACH ROW EXECUTE FUNCTION public.create_default_risk_policy();


--
-- Name: user_chessboard_profiles trigger_create_initial_profile_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_create_initial_profile_version AFTER INSERT ON public.user_chessboard_profiles FOR EACH ROW EXECUTE FUNCTION public.create_initial_profile_version();


--
-- Name: user_chessboard_profiles trigger_create_profile_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_create_profile_version AFTER UPDATE ON public.user_chessboard_profiles FOR EACH ROW WHEN ((old.version IS DISTINCT FROM new.version)) EXECUTE FUNCTION public.create_profile_version_snapshot();


--
-- Name: bot_exchange_configs trigger_ensure_single_active_bot_config; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_ensure_single_active_bot_config BEFORE INSERT OR UPDATE OF is_active ON public.bot_exchange_configs FOR EACH ROW WHEN ((new.is_active = true)) EXECUTE FUNCTION public.ensure_single_active_bot_config();


--
-- Name: bot_exchange_configs trigger_insert_config_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_insert_config_version AFTER INSERT OR UPDATE ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.insert_config_version_after();


--
-- Name: positions trigger_position_closed; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_position_closed AFTER UPDATE ON public.positions FOR EACH ROW EXECUTE FUNCTION public.update_portfolio_on_position_close();


--
-- Name: positions trigger_position_opened; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_position_opened AFTER INSERT ON public.positions FOR EACH ROW WHEN (((new.status)::text = 'open'::text)) EXECUTE FUNCTION public.update_portfolio_on_position_open();


--
-- Name: user_chessboard_profiles trigger_update_profile_timestamp; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_profile_timestamp BEFORE UPDATE ON public.user_chessboard_profiles FOR EACH ROW EXECUTE FUNCTION public.update_profile_timestamp();


--
-- Name: strategy_instances trigger_update_strategy_instance_timestamp; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_strategy_instance_timestamp BEFORE UPDATE ON public.strategy_instances FOR EACH ROW EXECUTE FUNCTION public.update_strategy_instance_timestamp();


--
-- Name: user_chessboard_profiles trigger_update_strategy_usage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_strategy_usage AFTER INSERT OR DELETE OR UPDATE OF strategy_composition ON public.user_chessboard_profiles FOR EACH ROW EXECUTE FUNCTION public.update_strategy_instance_usage();


--
-- Name: bot_exchange_configs trigger_validate_profile_environment; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_validate_profile_environment BEFORE INSERT OR UPDATE OF mounted_profile_id ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.validate_profile_environment_match();


--
-- Name: bot_pool_assignments update_bot_assignments_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_bot_assignments_updated_at BEFORE UPDATE ON public.bot_pool_assignments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: bot_budgets update_bot_budgets_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_bot_budgets_updated_at BEFORE UPDATE ON public.bot_budgets FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: bot_configurations update_bot_configurations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_bot_configurations_updated_at BEFORE UPDATE ON public.bot_configurations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: bot_exchange_configs update_bot_exchange_configs_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_bot_exchange_configs_updated_at BEFORE UPDATE ON public.bot_exchange_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: bot_instances update_bot_instances_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_bot_instances_updated_at BEFORE UPDATE ON public.bot_instances FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: bot_symbol_configs update_bot_symbol_configs_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_bot_symbol_configs_updated_at BEFORE UPDATE ON public.bot_symbol_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: exchange_accounts update_exchange_accounts_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_exchange_accounts_updated_at BEFORE UPDATE ON public.exchange_accounts FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: user_exchange_credentials update_exchange_creds_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_exchange_creds_updated_at BEFORE UPDATE ON public.user_exchange_credentials FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: exchange_policies update_exchange_policies_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_exchange_policies_updated_at BEFORE UPDATE ON public.exchange_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: portfolios update_portfolios_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_portfolios_updated_at BEFORE UPDATE ON public.portfolios FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: strategy_templates update_strategy_templates_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_strategy_templates_updated_at BEFORE UPDATE ON public.strategy_templates FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: tenant_risk_policies update_tenant_risk_policies_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_tenant_risk_policies_updated_at BEFORE UPDATE ON public.tenant_risk_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: user_trade_profiles update_trade_profiles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_trade_profiles_updated_at BEFORE UPDATE ON public.user_trade_profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: trades update_trades_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_trades_updated_at BEFORE UPDATE ON public.trades FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: user_preferences update_user_preferences_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_user_preferences_updated_at BEFORE UPDATE ON public.user_preferences FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: users update_users_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: alerts alerts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: approvals approvals_approver_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_approver_id_fkey FOREIGN KEY (approver_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approvals approvals_promotion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;


--
-- Name: approvals approvals_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: audit_log_exports audit_log_exports_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log_exports
    ADD CONSTRAINT audit_log_exports_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: audit_log audit_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: backtest_equity_curve backtest_equity_curve_backtest_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity_curve
    ADD CONSTRAINT backtest_equity_curve_backtest_run_id_fkey FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_runs(id) ON DELETE CASCADE;


--
-- Name: backtest_runs backtest_runs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: backtest_trades backtest_trades_backtest_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_backtest_run_id_fkey FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_runs(id) ON DELETE CASCADE;


--
-- Name: bot_budgets bot_budgets_bot_instance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;


--
-- Name: bot_budgets bot_budgets_exchange_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_budgets
    ADD CONSTRAINT bot_budgets_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;


--
-- Name: bot_commands bot_commands_bot_instance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;


--
-- Name: bot_commands bot_commands_exchange_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_exchange_config_id_fkey FOREIGN KEY (exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE CASCADE;


--
-- Name: bot_commands bot_commands_parent_command_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_parent_command_id_fkey FOREIGN KEY (parent_command_id) REFERENCES public.bot_commands(id);


--
-- Name: bot_commands bot_commands_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_commands
    ADD CONSTRAINT bot_commands_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: bot_config_actions bot_config_actions_bot_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_config_actions
    ADD CONSTRAINT bot_config_actions_bot_profile_id_fkey FOREIGN KEY (bot_profile_id) REFERENCES public.bot_profiles(id) ON DELETE CASCADE;


--
-- Name: bot_config_actions bot_config_actions_bot_profile_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_config_actions
    ADD CONSTRAINT bot_config_actions_bot_profile_version_id_fkey FOREIGN KEY (bot_profile_version_id) REFERENCES public.bot_profile_versions(id) ON DELETE SET NULL;


--
-- Name: bot_configurations bot_configurations_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_configurations
    ADD CONSTRAINT bot_configurations_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: bot_configurations bot_configurations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_configurations
    ADD CONSTRAINT bot_configurations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: bot_exchange_config_versions bot_exchange_config_versions_bot_exchange_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_bot_exchange_config_id_fkey FOREIGN KEY (bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE CASCADE;


--
-- Name: bot_exchange_config_versions bot_exchange_config_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_config_versions
    ADD CONSTRAINT bot_exchange_config_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: bot_exchange_configs bot_exchange_configs_bot_instance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_bot_instance_id_fkey FOREIGN KEY (bot_instance_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;


--
-- Name: bot_exchange_configs bot_exchange_configs_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE CASCADE;


--
-- Name: bot_exchange_configs bot_exchange_configs_exchange_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE SET NULL;


--
-- Name: bot_exchange_configs bot_exchange_configs_mounted_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_exchange_configs
    ADD CONSTRAINT bot_exchange_configs_mounted_profile_id_fkey FOREIGN KEY (mounted_profile_id) REFERENCES public.user_chessboard_profiles(id) ON DELETE SET NULL;


--
-- Name: bot_instances bot_instances_deleted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES public.users(id);


--
-- Name: bot_instances bot_instances_exchange_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id);


--
-- Name: bot_instances bot_instances_strategy_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_strategy_template_id_fkey FOREIGN KEY (strategy_template_id) REFERENCES public.strategy_templates(id) ON DELETE SET NULL;


--
-- Name: bot_instances bot_instances_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_instances
    ADD CONSTRAINT bot_instances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: bot_pool_assignments bot_pool_assignments_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_pool_assignments
    ADD CONSTRAINT bot_pool_assignments_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE SET NULL;


--
-- Name: bot_pool_assignments bot_pool_assignments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_pool_assignments
    ADD CONSTRAINT bot_pool_assignments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: bot_profile_versions bot_profile_versions_bot_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_profile_versions
    ADD CONSTRAINT bot_profile_versions_bot_profile_id_fkey FOREIGN KEY (bot_profile_id) REFERENCES public.bot_profiles(id) ON DELETE CASCADE;


--
-- Name: bot_profiles bot_profiles_active_version_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_profiles
    ADD CONSTRAINT bot_profiles_active_version_fk FOREIGN KEY (active_version_id) REFERENCES public.bot_profile_versions(id) ON DELETE SET NULL;


--
-- Name: bot_symbol_configs bot_symbol_configs_bot_exchange_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_symbol_configs
    ADD CONSTRAINT bot_symbol_configs_bot_exchange_config_id_fkey FOREIGN KEY (bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE CASCADE;


--
-- Name: bot_version_sections bot_version_sections_bot_profile_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_version_sections
    ADD CONSTRAINT bot_version_sections_bot_profile_version_id_fkey FOREIGN KEY (bot_profile_version_id) REFERENCES public.bot_profile_versions(id) ON DELETE CASCADE;


--
-- Name: config_audit_log config_audit_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_audit_log
    ADD CONSTRAINT config_audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: config_blocks config_blocks_config_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_blocks
    ADD CONSTRAINT config_blocks_config_version_id_fkey FOREIGN KEY (config_version_id) REFERENCES public.config_versions(id) ON DELETE CASCADE;


--
-- Name: config_change_log config_change_log_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_change_log
    ADD CONSTRAINT config_change_log_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.platform_users(id);


--
-- Name: config_change_log config_change_log_config_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_change_log
    ADD CONSTRAINT config_change_log_config_version_id_fkey FOREIGN KEY (config_version_id) REFERENCES public.config_versions(id) ON DELETE CASCADE;


--
-- Name: config_diffs config_diffs_promotion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_diffs
    ADD CONSTRAINT config_diffs_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;


--
-- Name: config_environments config_environments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_environments
    ADD CONSTRAINT config_environments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.platform_users(id) ON DELETE CASCADE;


--
-- Name: config_items config_items_config_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_items
    ADD CONSTRAINT config_items_config_version_id_fkey FOREIGN KEY (config_version_id) REFERENCES public.config_versions(id) ON DELETE CASCADE;


--
-- Name: config_sets config_sets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_sets
    ADD CONSTRAINT config_sets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.platform_users(id) ON DELETE CASCADE;


--
-- Name: config_versions config_versions_config_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_config_set_id_fkey FOREIGN KEY (config_set_id) REFERENCES public.config_sets(id) ON DELETE CASCADE;


--
-- Name: config_versions config_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.platform_users(id);


--
-- Name: config_versions config_versions_environment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_environment_id_fkey FOREIGN KEY (environment_id) REFERENCES public.config_environments(id) ON DELETE CASCADE;


--
-- Name: config_versions config_versions_promoted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_promoted_by_fkey FOREIGN KEY (promoted_by) REFERENCES public.platform_users(id);


--
-- Name: credential_balance_history credential_balance_history_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_balance_history
    ADD CONSTRAINT credential_balance_history_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE CASCADE;


--
-- Name: credential_balance_history credential_balance_history_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_balance_history
    ADD CONSTRAINT credential_balance_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: credential_config_audit credential_config_audit_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_config_audit
    ADD CONSTRAINT credential_config_audit_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE CASCADE;


--
-- Name: credential_config_audit credential_config_audit_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_config_audit
    ADD CONSTRAINT credential_config_audit_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: equity_curves equity_curves_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: equity_curves equity_curves_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.equity_curves
    ADD CONSTRAINT equity_curves_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: exchange_accounts exchange_accounts_active_bot_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_active_bot_fk FOREIGN KEY (active_bot_id) REFERENCES public.bot_instances(id) ON DELETE SET NULL;


--
-- Name: exchange_accounts exchange_accounts_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_accounts
    ADD CONSTRAINT exchange_accounts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: exchange_policies exchange_policies_exchange_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;


--
-- Name: exchange_policies exchange_policies_kill_switch_triggered_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_policies
    ADD CONSTRAINT exchange_policies_kill_switch_triggered_by_fkey FOREIGN KEY (kill_switch_triggered_by) REFERENCES public.users(id);


--
-- Name: generated_reports generated_reports_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.generated_reports
    ADD CONSTRAINT generated_reports_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.report_templates(id) ON DELETE SET NULL;


--
-- Name: orders orders_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: orders orders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: portfolio_equity portfolio_equity_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_equity
    ADD CONSTRAINT portfolio_equity_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: portfolios portfolios_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolios
    ADD CONSTRAINT portfolios_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: position_updates position_updates_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_updates
    ADD CONSTRAINT position_updates_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.positions(id) ON DELETE CASCADE;


--
-- Name: positions positions_entry_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_entry_order_id_fkey FOREIGN KEY (entry_order_id) REFERENCES public.orders(id) ON DELETE SET NULL;


--
-- Name: positions positions_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: positions positions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: profile_versions profile_versions_changed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.users(id);


--
-- Name: profile_versions profile_versions_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.user_chessboard_profiles(id) ON DELETE CASCADE;


--
-- Name: promotion_history promotion_history_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotion_history
    ADD CONSTRAINT promotion_history_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: promotion_history promotion_history_promotion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotion_history
    ADD CONSTRAINT promotion_history_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;


--
-- Name: promotions promotions_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: promotions promotions_rejected_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_rejected_by_fkey FOREIGN KEY (rejected_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: promotions promotions_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: replay_sessions replay_sessions_incident_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_sessions
    ADD CONSTRAINT replay_sessions_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.incidents(id) ON DELETE SET NULL;


--
-- Name: strategy_instances strategy_instances_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_instances
    ADD CONSTRAINT strategy_instances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: strategy_templates strategy_templates_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_templates
    ADD CONSTRAINT strategy_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: symbol_locks symbol_locks_exchange_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_exchange_account_id_fkey FOREIGN KEY (exchange_account_id) REFERENCES public.exchange_accounts(id) ON DELETE CASCADE;


--
-- Name: symbol_locks symbol_locks_owner_bot_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_locks
    ADD CONSTRAINT symbol_locks_owner_bot_fk FOREIGN KEY (owner_bot_id) REFERENCES public.bot_instances(id) ON DELETE CASCADE;


--
-- Name: tenant_risk_policies tenant_risk_policies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_risk_policies
    ADD CONSTRAINT tenant_risk_policies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: trades trades_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trades
    ADD CONSTRAINT trades_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: trading_accounts trading_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_accounts
    ADD CONSTRAINT trading_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: trading_activity trading_activity_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id) ON DELETE SET NULL;


--
-- Name: trading_activity trading_activity_position_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_position_id_fkey FOREIGN KEY (position_id) REFERENCES public.positions(id) ON DELETE SET NULL;


--
-- Name: trading_activity trading_activity_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_activity
    ADD CONSTRAINT trading_activity_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: trading_decisions trading_decisions_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.orders(id);


--
-- Name: trading_decisions trading_decisions_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolios(id) ON DELETE CASCADE;


--
-- Name: trading_decisions trading_decisions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trading_decisions
    ADD CONSTRAINT trading_decisions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_chessboard_profiles user_chessboard_profiles_promoted_from_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_promoted_from_id_fkey FOREIGN KEY (promoted_from_id) REFERENCES public.user_chessboard_profiles(id);


--
-- Name: user_chessboard_profiles user_chessboard_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_chessboard_profiles
    ADD CONSTRAINT user_chessboard_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_exchange_credentials user_exchange_credentials_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_exchange_credentials
    ADD CONSTRAINT user_exchange_credentials_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_preferences user_preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_sessions user_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_trade_profiles user_trade_profiles_active_bot_exchange_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_active_bot_exchange_config_id_fkey FOREIGN KEY (active_bot_exchange_config_id) REFERENCES public.bot_exchange_configs(id) ON DELETE SET NULL;


--
-- Name: user_trade_profiles user_trade_profiles_active_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_active_credential_id_fkey FOREIGN KEY (active_credential_id) REFERENCES public.user_exchange_credentials(id) ON DELETE SET NULL;


--
-- Name: user_trade_profiles user_trade_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trade_profiles
    ADD CONSTRAINT user_trade_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_trading_settings user_trading_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_trading_settings
    ADD CONSTRAINT user_trading_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--
