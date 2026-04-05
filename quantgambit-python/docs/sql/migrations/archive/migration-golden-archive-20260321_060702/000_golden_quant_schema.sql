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
-- Name: update_backtest_quality_metrics_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_backtest_quality_metrics_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_table_access_method = heap;

--
-- Name: _compressed_hypertable_2; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._compressed_hypertable_2 (
);


--
-- Name: _compressed_hypertable_4; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._compressed_hypertable_4 (
);


--
-- Name: orderbook_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orderbook_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: _hyper_15_1_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_15_1_chunk (
    CONSTRAINT constraint_1 CHECK (((ts >= '2026-03-19 00:00:00+00'::timestamp with time zone) AND (ts < '2026-03-26 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.orderbook_events);


--
-- Name: orderbook_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orderbook_snapshots (
    ts timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    seq bigint NOT NULL,
    bids jsonb NOT NULL,
    asks jsonb NOT NULL,
    spread_bps double precision NOT NULL,
    bid_depth_usd double precision NOT NULL,
    ask_depth_usd double precision NOT NULL,
    orderbook_imbalance double precision NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    bot_id text DEFAULT 'default'::text NOT NULL
);


--
-- Name: TABLE orderbook_snapshots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.orderbook_snapshots IS 'TimescaleDB hypertable storing point-in-time orderbook snapshots with 20 levels of bids/asks and derived metrics (spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance)';


--
-- Name: COLUMN orderbook_snapshots.ts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.ts IS 'Timestamp of the orderbook snapshot';


--
-- Name: COLUMN orderbook_snapshots.symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.symbol IS 'Trading pair symbol (e.g., BTC-USD)';


--
-- Name: COLUMN orderbook_snapshots.exchange; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.exchange IS 'Exchange name (e.g., binance, coinbase)';


--
-- Name: COLUMN orderbook_snapshots.seq; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.seq IS 'Sequence number from the exchange for gap detection';


--
-- Name: COLUMN orderbook_snapshots.bids; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.bids IS 'JSONB array of bid levels [[price, size], ...] up to 20 levels';


--
-- Name: COLUMN orderbook_snapshots.asks; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.asks IS 'JSONB array of ask levels [[price, size], ...] up to 20 levels';


--
-- Name: COLUMN orderbook_snapshots.spread_bps; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.spread_bps IS 'Bid-ask spread in basis points: ((best_ask - best_bid) / mid_price) * 10000';


--
-- Name: COLUMN orderbook_snapshots.bid_depth_usd; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.bid_depth_usd IS 'Total USD value of all bid orders: sum(price * size)';


--
-- Name: COLUMN orderbook_snapshots.ask_depth_usd; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.ask_depth_usd IS 'Total USD value of all ask orders: sum(price * size)';


--
-- Name: COLUMN orderbook_snapshots.orderbook_imbalance; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.orderbook_imbalance IS 'Ratio of bid depth to total depth: bid_depth_usd / (bid_depth_usd + ask_depth_usd)';


--
-- Name: COLUMN orderbook_snapshots.tenant_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.tenant_id IS 'Multi-tenant identifier';


--
-- Name: COLUMN orderbook_snapshots.bot_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.orderbook_snapshots.bot_id IS 'Bot identifier for filtering';


--
-- Name: _hyper_1_3_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_1_3_chunk (
    CONSTRAINT constraint_3 CHECK (((ts >= '2026-03-19 00:00:00+00'::timestamp with time zone) AND (ts < '2026-03-26 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.orderbook_snapshots);


--
-- Name: trade_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_records (
    ts timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    price double precision NOT NULL,
    size double precision NOT NULL,
    side text NOT NULL,
    trade_id text NOT NULL,
    tenant_id text DEFAULT 'default'::text NOT NULL,
    bot_id text DEFAULT 'default'::text NOT NULL
);


--
-- Name: TABLE trade_records; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.trade_records IS 'TimescaleDB hypertable storing individual trade records for VWAP calculation, volume profiles, and backtest replay';


--
-- Name: COLUMN trade_records.ts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.ts IS 'Timestamp of the trade (original exchange timestamp for accurate replay)';


--
-- Name: COLUMN trade_records.symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.symbol IS 'Trading pair symbol (e.g., BTC-USD)';


--
-- Name: COLUMN trade_records.exchange; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.exchange IS 'Exchange name (e.g., binance, coinbase)';


--
-- Name: COLUMN trade_records.price; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.price IS 'Trade execution price';


--
-- Name: COLUMN trade_records.size; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.size IS 'Trade size/quantity';


--
-- Name: COLUMN trade_records.side; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.side IS 'Trade side: buy or sell';


--
-- Name: COLUMN trade_records.trade_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.trade_id IS 'Unique trade identifier from the exchange';


--
-- Name: COLUMN trade_records.tenant_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.tenant_id IS 'Multi-tenant identifier';


--
-- Name: COLUMN trade_records.bot_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.trade_records.bot_id IS 'Bot identifier for filtering';


--
-- Name: _hyper_3_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: -
--

CREATE TABLE _timescaledb_internal._hyper_3_2_chunk (
    CONSTRAINT constraint_2 CHECK (((ts >= '2026-03-19 00:00:00+00'::timestamp with time zone) AND (ts < '2026-03-26 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.trade_records);


--
-- Name: backtest_equity_curve; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_equity_curve (
    run_id uuid NOT NULL,
    ts timestamp with time zone NOT NULL,
    equity double precision NOT NULL,
    realized_pnl double precision NOT NULL,
    open_positions integer NOT NULL
);


--
-- Name: backtest_metrics; Type: TABLE; Schema: public; Owner: -
--

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
    avg_trade_pnl double precision NOT NULL
);


--
-- Name: backtest_quality_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_quality_metrics (
    run_id uuid NOT NULL,
    data_quality_grade character varying(1) DEFAULT 'A'::character varying NOT NULL,
    data_completeness_pct double precision DEFAULT 100.0 NOT NULL,
    total_gaps integer DEFAULT 0 NOT NULL,
    critical_gaps integer DEFAULT 0 NOT NULL,
    missing_price_count integer DEFAULT 0 NOT NULL,
    missing_depth_count integer DEFAULT 0 NOT NULL,
    quality_warnings jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE backtest_quality_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_quality_metrics IS 'Stores data quality metrics for backtest runs including pre-flight validation and runtime tracking';


--
-- Name: COLUMN backtest_quality_metrics.data_quality_grade; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.data_quality_grade IS 'Quality grade: A (>=95%), B (>=85%), C (>=70%), D (>=50%), F (<50%)';


--
-- Name: COLUMN backtest_quality_metrics.data_completeness_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.data_completeness_pct IS 'Overall data completeness percentage from pre-flight validation';


--
-- Name: COLUMN backtest_quality_metrics.total_gaps; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.total_gaps IS 'Total number of data gaps detected during validation';


--
-- Name: COLUMN backtest_quality_metrics.critical_gaps; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.critical_gaps IS 'Number of critical gaps (during trading hours, >15 minutes)';


--
-- Name: COLUMN backtest_quality_metrics.missing_price_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.missing_price_count IS 'Count of snapshots missing price data during runtime';


--
-- Name: COLUMN backtest_quality_metrics.missing_depth_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.missing_depth_count IS 'Count of snapshots missing depth data during runtime';


--
-- Name: COLUMN backtest_quality_metrics.quality_warnings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_quality_metrics.quality_warnings IS 'JSON array of warning messages from validation';


--
-- Name: backtest_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_runs (
    run_id uuid NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    name text,
    symbol text,
    start_date timestamp with time zone,
    end_date timestamp with time zone,
    status text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    config jsonb NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    execution_diagnostics jsonb
);


--
-- Name: COLUMN backtest_runs.execution_diagnostics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.execution_diagnostics IS 'JSONB containing execution diagnostics: total_snapshots, snapshots_processed, snapshots_skipped, global_gate_rejections, rejection_breakdown, profiles_selected, signals_generated, cooldown_rejections, summary, primary_issue, suggestions';


--
-- Name: backtest_trades; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_trades (
    run_id uuid NOT NULL,
    ts timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    side text NOT NULL,
    size double precision NOT NULL,
    entry_price double precision NOT NULL,
    exit_price double precision NOT NULL,
    pnl double precision NOT NULL,
    entry_fee double precision NOT NULL,
    exit_fee double precision NOT NULL,
    total_fees double precision NOT NULL,
    entry_slippage_bps double precision NOT NULL,
    exit_slippage_bps double precision NOT NULL,
    strategy_id text,
    profile_id text,
    reason text
);


--
-- Name: config_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_versions (
    version_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text NOT NULL,
    config_hash text NOT NULL,
    parameters jsonb NOT NULL,
    is_active boolean DEFAULT false,
    CONSTRAINT config_versions_created_by_check CHECK ((created_by = ANY (ARRAY['live'::text, 'backtest'::text, 'optimizer'::text])))
);


--
-- Name: TABLE config_versions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.config_versions IS 'Stores versioned configuration snapshots for trading pipeline integration. 
Each version represents a point-in-time snapshot of trading configuration parameters.';


--
-- Name: COLUMN config_versions.version_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.config_versions.version_id IS 'Unique identifier for this configuration version';


--
-- Name: COLUMN config_versions.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.config_versions.created_at IS 'Timestamp when this version was created';


--
-- Name: COLUMN config_versions.created_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.config_versions.created_by IS 'Source of the configuration: live (from live trading), backtest (from backtest run), or optimizer (from parameter optimization)';


--
-- Name: COLUMN config_versions.config_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.config_versions.config_hash IS '16-character SHA256 hash of parameters for quick comparison';


--
-- Name: COLUMN config_versions.parameters; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.config_versions.parameters IS 'Full configuration parameters as JSON object';


--
-- Name: COLUMN config_versions.is_active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.config_versions.is_active IS 'Whether this is the currently active configuration for live trading';


--
-- Name: copilot_conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.copilot_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id text NOT NULL,
    title text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE copilot_conversations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.copilot_conversations IS 'Stores copilot conversation metadata. Each conversation belongs to a user and persists permanently.';


--
-- Name: copilot_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.copilot_messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id uuid NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    tool_calls jsonb,
    tool_call_id text,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE copilot_messages; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.copilot_messages IS 'Stores individual messages within copilot conversations. Supports user, assistant, and tool roles with optional tool call data.';


--
-- Name: copilot_settings_snapshots; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: TABLE copilot_settings_snapshots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.copilot_settings_snapshots IS 'Stores versioned point-in-time snapshots of user settings for rollback capability. Created when the copilot or user mutates settings.';


--
-- Name: decision_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.decision_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: execution_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.execution_ledger (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    exchange text NOT NULL,
    exec_id text NOT NULL,
    order_id text,
    client_order_id text,
    symbol text NOT NULL,
    side text,
    exec_price double precision,
    exec_qty double precision,
    exec_value double precision,
    exec_fee_usd double precision,
    exec_time_ms bigint,
    source text DEFAULT 'execution_sync'::text NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    exec_pnl double precision
);


--
-- Name: fee_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fee_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: guardrail_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.guardrail_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: latency_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.latency_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: market_candles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_candles (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    timeframe_sec integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    open double precision NOT NULL,
    high double precision NOT NULL,
    low double precision NOT NULL,
    close double precision NOT NULL,
    volume double precision NOT NULL
);


--
-- Name: market_data_provider_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_data_provider_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: order_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL,
    semantic_key text
);


--
-- Name: order_execution_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_execution_summary (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    exchange text NOT NULL,
    order_id text NOT NULL,
    client_order_id text,
    symbol text NOT NULL,
    side text,
    exec_count integer DEFAULT 0 NOT NULL,
    total_qty double precision,
    avg_price double precision,
    total_fee_usd double precision,
    exec_pnl double precision,
    first_exec_time_ms bigint,
    last_exec_time_ms bigint,
    source text DEFAULT 'execution_reconcile'::text NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: order_update_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_update_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: position_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: prediction_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prediction_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: recorded_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recorded_decisions (
    decision_id text NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    config_version text NOT NULL,
    market_snapshot jsonb NOT NULL,
    features jsonb NOT NULL,
    positions jsonb,
    account_state jsonb,
    stage_results jsonb,
    rejection_stage text,
    rejection_reason text,
    decision text NOT NULL,
    signal jsonb,
    profile_id text,
    CONSTRAINT recorded_decisions_decision_check CHECK ((decision = ANY (ARRAY['accepted'::text, 'rejected'::text, 'shadow'::text])))
);


--
-- Name: TABLE recorded_decisions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.recorded_decisions IS 'Stores complete decision records for replay and analysis. Each record captures 
the full context of a trading decision including market state, features, pipeline 
execution, and final outcome. Uses TimescaleDB hypertable for efficient time-range queries.';


--
-- Name: COLUMN recorded_decisions.decision_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.decision_id IS 'Unique identifier for this decision record (format: dec_XXXXXXXXXXXX)';


--
-- Name: COLUMN recorded_decisions."timestamp"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions."timestamp" IS 'Timestamp when the decision was made (UTC)';


--
-- Name: COLUMN recorded_decisions.symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.symbol IS 'Trading symbol (e.g., BTCUSDT)';


--
-- Name: COLUMN recorded_decisions.config_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.config_version IS 'Version ID of the configuration used for this decision (references config_versions)';


--
-- Name: COLUMN recorded_decisions.market_snapshot; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.market_snapshot IS 'Complete market state at decision time including prices, orderbook depth, spread, etc.';


--
-- Name: COLUMN recorded_decisions.features; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.features IS 'Computed features used for decision making (AMT, volatility, trend, etc.)';


--
-- Name: COLUMN recorded_decisions.positions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.positions IS 'Current open positions at decision time with entry prices, sizes, and timestamps';


--
-- Name: COLUMN recorded_decisions.account_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.account_state IS 'Account state at decision time including equity, margin, available balance';


--
-- Name: COLUMN recorded_decisions.stage_results; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.stage_results IS 'Output from each pipeline stage as array of {stage, passed, reason, metrics}';


--
-- Name: COLUMN recorded_decisions.rejection_stage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.rejection_stage IS 'Name of the pipeline stage that rejected the decision (NULL if accepted)';


--
-- Name: COLUMN recorded_decisions.rejection_reason; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.rejection_reason IS 'Human-readable reason for rejection (NULL if accepted)';


--
-- Name: COLUMN recorded_decisions.decision; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.decision IS 'Final decision outcome: accepted (signal generated), rejected (filtered out), shadow (shadow mode comparison)';


--
-- Name: COLUMN recorded_decisions.signal; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.signal IS 'Generated signal details if accepted (side, size, entry, targets, etc.)';


--
-- Name: COLUMN recorded_decisions.profile_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.recorded_decisions.profile_id IS 'Trading profile ID used for this decision (from profile router)';


--
-- Name: replay_validations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.replay_validations (
    id integer NOT NULL,
    run_id text NOT NULL,
    run_at timestamp with time zone DEFAULT now() NOT NULL,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    total_replayed integer NOT NULL,
    matches integer NOT NULL,
    changes integer NOT NULL,
    match_rate double precision NOT NULL,
    changes_by_category jsonb,
    changes_by_stage jsonb,
    CONSTRAINT replay_validations_changes_check CHECK ((changes >= 0)),
    CONSTRAINT replay_validations_match_rate_check CHECK (((match_rate >= (0.0)::double precision) AND (match_rate <= (1.0)::double precision))),
    CONSTRAINT replay_validations_matches_check CHECK ((matches >= 0)),
    CONSTRAINT replay_validations_total_replayed_check CHECK ((total_replayed >= 0)),
    CONSTRAINT replay_validations_totals_check CHECK (((matches + changes) = total_replayed))
);


--
-- Name: TABLE replay_validations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.replay_validations IS 'Stores replay validation results for comparing historical decisions against current pipeline';


--
-- Name: COLUMN replay_validations.run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.run_id IS 'Unique identifier for this replay run';


--
-- Name: COLUMN replay_validations.run_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.run_at IS 'Timestamp when the replay was executed';


--
-- Name: COLUMN replay_validations.start_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.start_time IS 'Start of the time range that was replayed';


--
-- Name: COLUMN replay_validations.end_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.end_time IS 'End of the time range that was replayed';


--
-- Name: COLUMN replay_validations.total_replayed; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.total_replayed IS 'Total number of decisions replayed';


--
-- Name: COLUMN replay_validations.matches; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.matches IS 'Number of decisions that matched original outcome';


--
-- Name: COLUMN replay_validations.changes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.changes IS 'Number of decisions that changed from original outcome';


--
-- Name: COLUMN replay_validations.match_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.match_rate IS 'Ratio of matches to total (0.0 to 1.0)';


--
-- Name: COLUMN replay_validations.changes_by_category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.changes_by_category IS 'JSON object with counts by category (expected, unexpected, improved, degraded)';


--
-- Name: COLUMN replay_validations.changes_by_stage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.replay_validations.changes_by_stage IS 'JSON object with counts by stage difference (e.g., "ev_gate->amt_gate": 5)';


--
-- Name: replay_validations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.replay_validations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: replay_validations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.replay_validations_id_seq OWNED BY public.replay_validations.id;


--
-- Name: risk_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    exchange text,
    ts timestamp with time zone NOT NULL,
    payload jsonb NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    id integer NOT NULL,
    name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    checksum text
);


--
-- Name: schema_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.schema_migrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: schema_migrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.schema_migrations_id_seq OWNED BY public.schema_migrations.id;


--
-- Name: shadow_comparisons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shadow_comparisons (
    id integer NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    symbol text NOT NULL,
    live_decision text NOT NULL,
    shadow_decision text NOT NULL,
    agrees boolean NOT NULL,
    divergence_reason text,
    live_config_version text,
    shadow_config_version text
);


--
-- Name: TABLE shadow_comparisons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.shadow_comparisons IS 'Stores comparison results between live and shadow pipeline decisions for shadow mode validation';


--
-- Name: COLUMN shadow_comparisons."timestamp"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons."timestamp" IS 'When the comparison was made';


--
-- Name: COLUMN shadow_comparisons.symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.symbol IS 'Trading symbol (e.g., BTCUSDT)';


--
-- Name: COLUMN shadow_comparisons.live_decision; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.live_decision IS 'Decision from live pipeline (accepted or rejected)';


--
-- Name: COLUMN shadow_comparisons.shadow_decision; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.shadow_decision IS 'Decision from shadow pipeline (accepted or rejected)';


--
-- Name: COLUMN shadow_comparisons.agrees; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.agrees IS 'True if live_decision equals shadow_decision';


--
-- Name: COLUMN shadow_comparisons.divergence_reason; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.divergence_reason IS 'Reason for divergence if decisions differ (e.g., stage_diff:ev_gate vs data_readiness)';


--
-- Name: COLUMN shadow_comparisons.live_config_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.live_config_version IS 'Configuration version used by live pipeline';


--
-- Name: COLUMN shadow_comparisons.shadow_config_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.shadow_comparisons.shadow_config_version IS 'Configuration version used by shadow pipeline';


--
-- Name: shadow_comparisons_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.shadow_comparisons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: shadow_comparisons_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.shadow_comparisons_id_seq OWNED BY public.shadow_comparisons.id;


--
-- Name: trade_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_costs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
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
    CONSTRAINT trade_costs_side_check CHECK ((side = ANY (ARRAY['long'::text, 'short'::text, 'buy'::text, 'sell'::text])))
);


--
-- Name: wfo_runs; Type: TABLE; Schema: public; Owner: -
--

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


--
-- Name: _hyper_1_3_chunk tenant_id; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk ALTER COLUMN tenant_id SET DEFAULT 'default'::text;


--
-- Name: _hyper_1_3_chunk bot_id; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_3_chunk ALTER COLUMN bot_id SET DEFAULT 'default'::text;


--
-- Name: _hyper_3_2_chunk tenant_id; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_3_2_chunk ALTER COLUMN tenant_id SET DEFAULT 'default'::text;


--
-- Name: _hyper_3_2_chunk bot_id; Type: DEFAULT; Schema: _timescaledb_internal; Owner: -
--

ALTER TABLE ONLY _timescaledb_internal._hyper_3_2_chunk ALTER COLUMN bot_id SET DEFAULT 'default'::text;


--
-- Name: replay_validations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_validations ALTER COLUMN id SET DEFAULT nextval('public.replay_validations_id_seq'::regclass);


--
-- Name: schema_migrations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations ALTER COLUMN id SET DEFAULT nextval('public.schema_migrations_id_seq'::regclass);


--
-- Name: shadow_comparisons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shadow_comparisons ALTER COLUMN id SET DEFAULT nextval('public.shadow_comparisons_id_seq'::regclass);


--
-- Name: backtest_metrics backtest_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_metrics
    ADD CONSTRAINT backtest_metrics_pkey PRIMARY KEY (run_id);


--
-- Name: backtest_quality_metrics backtest_quality_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_quality_metrics
    ADD CONSTRAINT backtest_quality_metrics_pkey PRIMARY KEY (run_id);


--
-- Name: backtest_runs backtest_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_pkey PRIMARY KEY (run_id);


--
-- Name: config_versions config_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_versions
    ADD CONSTRAINT config_versions_pkey PRIMARY KEY (version_id);


--
-- Name: copilot_conversations copilot_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.copilot_conversations
    ADD CONSTRAINT copilot_conversations_pkey PRIMARY KEY (id);


--
-- Name: copilot_messages copilot_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.copilot_messages
    ADD CONSTRAINT copilot_messages_pkey PRIMARY KEY (id);


--
-- Name: copilot_settings_snapshots copilot_settings_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.copilot_settings_snapshots
    ADD CONSTRAINT copilot_settings_snapshots_pkey PRIMARY KEY (id);


--
-- Name: execution_ledger execution_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_ledger
    ADD CONSTRAINT execution_ledger_pkey PRIMARY KEY (tenant_id, bot_id, exchange, exec_id);


--
-- Name: order_execution_summary order_execution_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_execution_summary
    ADD CONSTRAINT order_execution_summary_pkey PRIMARY KEY (tenant_id, bot_id, exchange, order_id);


--
-- Name: recorded_decisions recorded_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recorded_decisions
    ADD CONSTRAINT recorded_decisions_pkey PRIMARY KEY (decision_id, "timestamp");


--
-- Name: replay_validations replay_validations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_validations
    ADD CONSTRAINT replay_validations_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_name_key UNIQUE (name);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (id);


--
-- Name: trade_costs trade_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_costs
    ADD CONSTRAINT trade_costs_pkey PRIMARY KEY (id);


--
-- Name: wfo_runs wfo_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wfo_runs
    ADD CONSTRAINT wfo_runs_pkey PRIMARY KEY (run_id);


--
-- Name: _hyper_15_1_chunk_orderbook_events_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_15_1_chunk_orderbook_events_idx ON _timescaledb_internal._hyper_15_1_chunk USING btree (tenant_id, bot_id, symbol, ts DESC);


--
-- Name: _hyper_15_1_chunk_orderbook_events_ts_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_15_1_chunk_orderbook_events_ts_idx ON _timescaledb_internal._hyper_15_1_chunk USING btree (ts DESC);


--
-- Name: _hyper_1_3_chunk_idx_orderbook_snapshots_exchange_symbol_ts; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_orderbook_snapshots_exchange_symbol_ts ON _timescaledb_internal._hyper_1_3_chunk USING btree (exchange, symbol, ts DESC);


--
-- Name: _hyper_1_3_chunk_idx_orderbook_snapshots_symbol_ts; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_orderbook_snapshots_symbol_ts ON _timescaledb_internal._hyper_1_3_chunk USING btree (symbol, ts DESC);


--
-- Name: _hyper_1_3_chunk_idx_orderbook_snapshots_tenant_ts; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_idx_orderbook_snapshots_tenant_ts ON _timescaledb_internal._hyper_1_3_chunk USING btree (tenant_id, ts DESC);


--
-- Name: _hyper_1_3_chunk_orderbook_snapshots_ts_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_1_3_chunk_orderbook_snapshots_ts_idx ON _timescaledb_internal._hyper_1_3_chunk USING btree (ts DESC);


--
-- Name: _hyper_3_2_chunk_idx_trade_records_exchange_symbol_ts; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_idx_trade_records_exchange_symbol_ts ON _timescaledb_internal._hyper_3_2_chunk USING btree (exchange, symbol, ts DESC);


--
-- Name: _hyper_3_2_chunk_idx_trade_records_symbol_ts; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_idx_trade_records_symbol_ts ON _timescaledb_internal._hyper_3_2_chunk USING btree (symbol, ts DESC);


--
-- Name: _hyper_3_2_chunk_idx_trade_records_tenant_ts; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_idx_trade_records_tenant_ts ON _timescaledb_internal._hyper_3_2_chunk USING btree (tenant_id, ts DESC);


--
-- Name: _hyper_3_2_chunk_idx_trade_records_trade_id; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_idx_trade_records_trade_id ON _timescaledb_internal._hyper_3_2_chunk USING btree (trade_id);


--
-- Name: _hyper_3_2_chunk_trade_records_ts_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: -
--

CREATE INDEX _hyper_3_2_chunk_trade_records_ts_idx ON _timescaledb_internal._hyper_3_2_chunk USING btree (ts DESC);


--
-- Name: backtest_equity_curve_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_equity_curve_idx ON public.backtest_equity_curve USING btree (run_id, ts DESC);


--
-- Name: backtest_metrics_run_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_metrics_run_id_idx ON public.backtest_metrics USING btree (run_id);


--
-- Name: backtest_runs_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_runs_created_at_idx ON public.backtest_runs USING btree (created_at DESC);


--
-- Name: backtest_runs_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_runs_status_idx ON public.backtest_runs USING btree (status);


--
-- Name: backtest_runs_symbol_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_runs_symbol_idx ON public.backtest_runs USING btree (symbol);


--
-- Name: backtest_runs_tenant_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_runs_tenant_idx ON public.backtest_runs USING btree (tenant_id);


--
-- Name: backtest_runs_tenant_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_runs_tenant_status_idx ON public.backtest_runs USING btree (tenant_id, status);


--
-- Name: backtest_trades_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_trades_idx ON public.backtest_trades USING btree (run_id, ts DESC);


--
-- Name: backtest_trades_symbol_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backtest_trades_symbol_idx ON public.backtest_trades USING btree (symbol);


--
-- Name: decision_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX decision_events_idx ON public.decision_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: decision_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX decision_events_ts_idx ON public.decision_events USING btree (ts DESC);


--
-- Name: execution_ledger_order_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX execution_ledger_order_idx ON public.execution_ledger USING btree (tenant_id, bot_id, exchange, order_id);


--
-- Name: execution_ledger_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX execution_ledger_time_idx ON public.execution_ledger USING btree (tenant_id, bot_id, exchange, exec_time_ms DESC);


--
-- Name: fee_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fee_events_idx ON public.fee_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: fee_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fee_events_ts_idx ON public.fee_events USING btree (ts DESC);


--
-- Name: guardrail_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX guardrail_events_idx ON public.guardrail_events USING btree (tenant_id, bot_id, symbol, ts DESC);


--
-- Name: guardrail_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX guardrail_events_ts_idx ON public.guardrail_events USING btree (ts DESC);


--
-- Name: idx_backtest_quality_metrics_completeness; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_quality_metrics_completeness ON public.backtest_quality_metrics USING btree (data_completeness_pct);


--
-- Name: idx_backtest_quality_metrics_grade; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_quality_metrics_grade ON public.backtest_quality_metrics USING btree (data_quality_grade);


--
-- Name: idx_config_versions_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_active ON public.config_versions USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_config_versions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_created ON public.config_versions USING btree (created_at DESC);


--
-- Name: idx_config_versions_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_created_by ON public.config_versions USING btree (created_by, created_at DESC);


--
-- Name: idx_config_versions_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_config_versions_hash ON public.config_versions USING btree (config_hash);


--
-- Name: idx_copilot_conversations_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_copilot_conversations_user ON public.copilot_conversations USING btree (user_id, updated_at DESC);


--
-- Name: idx_copilot_messages_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_copilot_messages_conversation ON public.copilot_messages USING btree (conversation_id, "timestamp");


--
-- Name: idx_copilot_messages_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_copilot_messages_search ON public.copilot_messages USING gin (to_tsvector('english'::regconfig, content));


--
-- Name: idx_copilot_settings_snapshots_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_copilot_settings_snapshots_user ON public.copilot_settings_snapshots USING btree (user_id, version DESC);


--
-- Name: idx_orderbook_snapshots_exchange_symbol_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orderbook_snapshots_exchange_symbol_ts ON public.orderbook_snapshots USING btree (exchange, symbol, ts DESC);


--
-- Name: idx_orderbook_snapshots_symbol_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orderbook_snapshots_symbol_ts ON public.orderbook_snapshots USING btree (symbol, ts DESC);


--
-- Name: idx_orderbook_snapshots_tenant_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orderbook_snapshots_tenant_ts ON public.orderbook_snapshots USING btree (tenant_id, ts DESC);


--
-- Name: idx_recorded_decisions_config_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recorded_decisions_config_version ON public.recorded_decisions USING btree (config_version, "timestamp" DESC);


--
-- Name: idx_recorded_decisions_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recorded_decisions_decision ON public.recorded_decisions USING btree (decision, "timestamp" DESC);


--
-- Name: idx_recorded_decisions_profile; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recorded_decisions_profile ON public.recorded_decisions USING btree (profile_id, "timestamp" DESC) WHERE (profile_id IS NOT NULL);


--
-- Name: idx_recorded_decisions_rejection_stage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recorded_decisions_rejection_stage ON public.recorded_decisions USING btree (rejection_stage, "timestamp" DESC) WHERE (rejection_stage IS NOT NULL);


--
-- Name: idx_recorded_decisions_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recorded_decisions_symbol ON public.recorded_decisions USING btree (symbol, "timestamp" DESC);


--
-- Name: idx_recorded_decisions_symbol_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recorded_decisions_symbol_decision ON public.recorded_decisions USING btree (symbol, decision, "timestamp" DESC);


--
-- Name: idx_replay_validations_run_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_validations_run_at ON public.replay_validations USING btree (run_at DESC);


--
-- Name: idx_replay_validations_run_at_match_rate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_validations_run_at_match_rate ON public.replay_validations USING btree (run_at DESC, match_rate);


--
-- Name: idx_replay_validations_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_validations_run_id ON public.replay_validations USING btree (run_id);


--
-- Name: idx_replay_validations_time_range; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_replay_validations_time_range ON public.replay_validations USING btree (start_time, end_time);


--
-- Name: idx_shadow_comparisons_agrees; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_comparisons_agrees ON public.shadow_comparisons USING btree (agrees, "timestamp" DESC);


--
-- Name: idx_shadow_comparisons_config_versions; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_comparisons_config_versions ON public.shadow_comparisons USING btree (live_config_version, shadow_config_version, "timestamp" DESC);


--
-- Name: idx_shadow_comparisons_divergence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_comparisons_divergence ON public.shadow_comparisons USING btree (divergence_reason, "timestamp" DESC) WHERE (divergence_reason IS NOT NULL);


--
-- Name: idx_shadow_comparisons_symbol_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shadow_comparisons_symbol_time ON public.shadow_comparisons USING btree (symbol, "timestamp" DESC);


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

CREATE INDEX idx_trade_costs_timestamp ON public.trade_costs USING btree ("timestamp" DESC);


--
-- Name: idx_trade_costs_trade_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_costs_trade_id ON public.trade_costs USING btree (trade_id);


--
-- Name: idx_trade_records_exchange_symbol_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_records_exchange_symbol_ts ON public.trade_records USING btree (exchange, symbol, ts DESC);


--
-- Name: idx_trade_records_symbol_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_records_symbol_ts ON public.trade_records USING btree (symbol, ts DESC);


--
-- Name: idx_trade_records_tenant_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_records_tenant_ts ON public.trade_records USING btree (tenant_id, ts DESC);


--
-- Name: idx_trade_records_trade_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_records_trade_id ON public.trade_records USING btree (trade_id);


--
-- Name: latency_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX latency_events_idx ON public.latency_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: latency_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX latency_events_ts_idx ON public.latency_events USING btree (ts DESC);


--
-- Name: market_candles_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_candles_idx ON public.market_candles USING btree (tenant_id, bot_id, symbol, timeframe_sec, ts DESC);


--
-- Name: market_candles_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_candles_ts_idx ON public.market_candles USING btree (ts DESC);


--
-- Name: market_data_provider_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_data_provider_events_idx ON public.market_data_provider_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: market_data_provider_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_data_provider_events_ts_idx ON public.market_data_provider_events USING btree (ts DESC);


--
-- Name: order_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_events_idx ON public.order_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: order_events_semantic_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_events_semantic_key_idx ON public.order_events USING btree (tenant_id, bot_id, semantic_key);


--
-- Name: order_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_events_ts_idx ON public.order_events USING btree (ts DESC);


--
-- Name: order_execution_summary_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_execution_summary_time_idx ON public.order_execution_summary USING btree (tenant_id, bot_id, exchange, last_exec_time_ms DESC);


--
-- Name: order_update_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_update_events_idx ON public.order_update_events USING btree (tenant_id, bot_id, symbol, ts DESC);


--
-- Name: order_update_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_update_events_ts_idx ON public.order_update_events USING btree (ts DESC);


--
-- Name: orderbook_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX orderbook_events_idx ON public.orderbook_events USING btree (tenant_id, bot_id, symbol, ts DESC);


--
-- Name: orderbook_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX orderbook_events_ts_idx ON public.orderbook_events USING btree (ts DESC);


--
-- Name: orderbook_snapshots_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX orderbook_snapshots_ts_idx ON public.orderbook_snapshots USING btree (ts DESC);


--
-- Name: position_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX position_events_idx ON public.position_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: position_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX position_events_ts_idx ON public.position_events USING btree (ts DESC);


--
-- Name: prediction_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX prediction_events_idx ON public.prediction_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: prediction_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX prediction_events_ts_idx ON public.prediction_events USING btree (ts DESC);


--
-- Name: recorded_decisions_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX recorded_decisions_timestamp_idx ON public.recorded_decisions USING btree ("timestamp" DESC);


--
-- Name: risk_events_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX risk_events_idx ON public.risk_events USING btree (tenant_id, bot_id, ts DESC);


--
-- Name: risk_events_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX risk_events_ts_idx ON public.risk_events USING btree (ts DESC);


--
-- Name: schema_migrations_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX schema_migrations_name_idx ON public.schema_migrations USING btree (name);


--
-- Name: shadow_comparisons_timestamp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX shadow_comparisons_timestamp_idx ON public.shadow_comparisons USING btree ("timestamp" DESC);


--
-- Name: trade_records_ts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trade_records_ts_idx ON public.trade_records USING btree (ts DESC);


--
-- Name: wfo_runs_profile_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wfo_runs_profile_idx ON public.wfo_runs USING btree (profile_id);


--
-- Name: wfo_runs_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wfo_runs_status_idx ON public.wfo_runs USING btree (status);


--
-- Name: wfo_runs_symbol_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wfo_runs_symbol_idx ON public.wfo_runs USING btree (symbol);


--
-- Name: wfo_runs_tenant_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wfo_runs_tenant_idx ON public.wfo_runs USING btree (tenant_id);


--
-- Name: wfo_runs_tenant_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wfo_runs_tenant_status_idx ON public.wfo_runs USING btree (tenant_id, status);


--
-- Name: backtest_quality_metrics trigger_update_backtest_quality_metrics_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_backtest_quality_metrics_updated_at BEFORE UPDATE ON public.backtest_quality_metrics FOR EACH ROW EXECUTE FUNCTION public.update_backtest_quality_metrics_updated_at();


--
-- Name: backtest_equity_curve backtest_equity_curve_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity_curve
    ADD CONSTRAINT backtest_equity_curve_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;


--
-- Name: backtest_metrics backtest_metrics_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_metrics
    ADD CONSTRAINT backtest_metrics_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;


--
-- Name: backtest_quality_metrics backtest_quality_metrics_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_quality_metrics
    ADD CONSTRAINT backtest_quality_metrics_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;


--
-- Name: backtest_trades backtest_trades_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE;


--
-- Name: copilot_messages copilot_messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.copilot_messages
    ADD CONSTRAINT copilot_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.copilot_conversations(id) ON DELETE CASCADE;


--
-- Name: copilot_settings_snapshots copilot_settings_snapshots_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.copilot_settings_snapshots
    ADD CONSTRAINT copilot_settings_snapshots_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.copilot_conversations(id);


--
-- Name: recorded_decisions recorded_decisions_config_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recorded_decisions
    ADD CONSTRAINT recorded_decisions_config_version_fkey FOREIGN KEY (config_version) REFERENCES public.config_versions(version_id);


--
-- PostgreSQL database dump complete
--

