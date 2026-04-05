CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS public.bot_configs (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    version integer NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.idempotency_audit (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    client_order_id text NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone,
    reason text
);

CREATE TABLE IF NOT EXISTS public.market_context (
    id bigint NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    spread_bps numeric,
    depth_usd numeric,
    funding_rate numeric,
    iv numeric,
    vol numeric,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.market_context_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.market_context_id_seq OWNED BY public.market_context.id;
ALTER TABLE ONLY public.market_context ALTER COLUMN id SET DEFAULT nextval('public.market_context_id_seq'::regclass);

CREATE TABLE IF NOT EXISTS public.order_errors (
    error_id uuid NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    exchange text,
    symbol text,
    order_id text,
    client_order_id text,
    stage text NOT NULL,
    error_code text,
    error_message text,
    payload jsonb,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE IF NOT EXISTS public.order_intents (
    intent_id uuid NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    decision_id text,
    client_order_id text NOT NULL,
    symbol text NOT NULL,
    side text NOT NULL,
    size double precision NOT NULL,
    entry_price double precision,
    stop_loss double precision,
    take_profit double precision,
    strategy_id text,
    profile_id text,
    status text NOT NULL,
    order_id text,
    last_error text,
    created_at timestamp with time zone NOT NULL,
    submitted_at timestamp with time zone,
    snapshot_metrics jsonb
);

CREATE TABLE IF NOT EXISTS public.order_lifecycle_events (
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    exchange text,
    symbol text NOT NULL,
    side text NOT NULL,
    size double precision NOT NULL,
    status text NOT NULL,
    event_type text,
    order_id text,
    client_order_id text,
    reason text,
    fill_price double precision,
    fee_usd double precision,
    filled_size double precision,
    remaining_size double precision,
    state_source text,
    raw_exchange_status text,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE IF NOT EXISTS public.order_states (
    id bigint NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    exchange text,
    symbol text NOT NULL,
    side text NOT NULL,
    size double precision NOT NULL,
    status text NOT NULL,
    order_id text,
    client_order_id text,
    reason text,
    fill_price double precision,
    fee_usd double precision,
    filled_size double precision,
    remaining_size double precision,
    state_source text,
    raw_exchange_status text,
    submitted_at timestamp with time zone,
    accepted_at timestamp with time zone,
    open_at timestamp with time zone,
    filled_at timestamp with time zone,
    updated_at timestamp with time zone NOT NULL,
    slippage_bps double precision
);

CREATE SEQUENCE IF NOT EXISTS public.order_states_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.order_states_id_seq OWNED BY public.order_states.id;
ALTER TABLE ONLY public.order_states ALTER COLUMN id SET DEFAULT nextval('public.order_states_id_seq'::regclass);

CREATE TABLE IF NOT EXISTS public.risk_incidents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    type text,
    symbol text,
    limit_hit text,
    detail jsonb,
    pnl numeric,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.schema_baseline_state (
    schema_name text NOT NULL,
    schema_path text NOT NULL,
    schema_checksum text NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.signals (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    decision text,
    reason text,
    score numeric,
    timeframe text,
    pnl numeric,
    payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.sltp_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    symbol text,
    side text,
    event_type text,
    pnl numeric,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.timeline_events (
    id bigint NOT NULL,
    tenant_id text NOT NULL,
    bot_id text NOT NULL,
    event_type text,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.timeline_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.timeline_events_id_seq OWNED BY public.timeline_events.id;
ALTER TABLE ONLY public.timeline_events ALTER COLUMN id SET DEFAULT nextval('public.timeline_events_id_seq'::regclass);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'bot_configs_pkey'
          AND conrelid = 'public.bot_configs'::regclass
    ) THEN
        ALTER TABLE ONLY public.bot_configs
            ADD CONSTRAINT bot_configs_pkey PRIMARY KEY (tenant_id, bot_id, version);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'market_context_pkey'
          AND conrelid = 'public.market_context'::regclass
    ) THEN
        ALTER TABLE ONLY public.market_context
            ADD CONSTRAINT market_context_pkey PRIMARY KEY (id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'order_errors_pkey'
          AND conrelid = 'public.order_errors'::regclass
    ) THEN
        ALTER TABLE ONLY public.order_errors
            ADD CONSTRAINT order_errors_pkey PRIMARY KEY (error_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'order_intents_pkey'
          AND conrelid = 'public.order_intents'::regclass
    ) THEN
        ALTER TABLE ONLY public.order_intents
            ADD CONSTRAINT order_intents_pkey PRIMARY KEY (intent_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'order_states_pkey'
          AND conrelid = 'public.order_states'::regclass
    ) THEN
        ALTER TABLE ONLY public.order_states
            ADD CONSTRAINT order_states_pkey PRIMARY KEY (id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'risk_incidents_pkey'
          AND conrelid = 'public.risk_incidents'::regclass
    ) THEN
        ALTER TABLE ONLY public.risk_incidents
            ADD CONSTRAINT risk_incidents_pkey PRIMARY KEY (id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'schema_baseline_state_pkey'
          AND conrelid = 'public.schema_baseline_state'::regclass
    ) THEN
        ALTER TABLE ONLY public.schema_baseline_state
            ADD CONSTRAINT schema_baseline_state_pkey PRIMARY KEY (schema_name);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'signals_pkey'
          AND conrelid = 'public.signals'::regclass
    ) THEN
        ALTER TABLE ONLY public.signals
            ADD CONSTRAINT signals_pkey PRIMARY KEY (id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'sltp_events_pkey'
          AND conrelid = 'public.sltp_events'::regclass
    ) THEN
        ALTER TABLE ONLY public.sltp_events
            ADD CONSTRAINT sltp_events_pkey PRIMARY KEY (id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'timeline_events_pkey'
          AND conrelid = 'public.timeline_events'::regclass
    ) THEN
        ALTER TABLE ONLY public.timeline_events
            ADD CONSTRAINT timeline_events_pkey PRIMARY KEY (id);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS bot_configs_latest_idx
    ON public.bot_configs USING btree (tenant_id, bot_id, version DESC);

CREATE INDEX IF NOT EXISTS idempotency_audit_idx
    ON public.idempotency_audit USING btree (tenant_id, bot_id, created_at DESC);

CREATE INDEX IF NOT EXISTS market_context_symbol_idx
    ON public.market_context USING btree (symbol);

CREATE INDEX IF NOT EXISTS market_context_tenant_bot_created_idx
    ON public.market_context USING btree (tenant_id, bot_id, created_at DESC);

CREATE INDEX IF NOT EXISTS order_errors_tenant_bot_idx
    ON public.order_errors USING btree (tenant_id, bot_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS order_intents_client_order_id_idx
    ON public.order_intents USING btree (tenant_id, bot_id, client_order_id);

CREATE INDEX IF NOT EXISTS order_intents_status_idx
    ON public.order_intents USING btree (tenant_id, bot_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS order_lifecycle_events_tenant_bot_idx
    ON public.order_lifecycle_events USING btree (tenant_id, bot_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS order_states_client_order_id_idx
    ON public.order_states USING btree (tenant_id, bot_id, client_order_id)
    WHERE (client_order_id IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS order_states_order_id_idx
    ON public.order_states USING btree (tenant_id, bot_id, order_id)
    WHERE (order_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS risk_incidents_tenant_bot_created_idx
    ON public.risk_incidents USING btree (tenant_id, bot_id, created_at DESC);

CREATE INDEX IF NOT EXISTS signals_symbol_idx
    ON public.signals USING btree (symbol);

CREATE INDEX IF NOT EXISTS signals_tenant_bot_created_idx
    ON public.signals USING btree (tenant_id, bot_id, created_at DESC);

CREATE INDEX IF NOT EXISTS sltp_events_tenant_bot_created_idx
    ON public.sltp_events USING btree (tenant_id, bot_id, created_at DESC);

CREATE INDEX IF NOT EXISTS timeline_events_tenant_bot_created_idx
    ON public.timeline_events USING btree (tenant_id, bot_id, created_at DESC);
