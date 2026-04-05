-- Migration: Add fast scalper tables required by 043 bot-level trade/position tracking
-- These tables are used by runtime and dashboard views but were accidentally missing from
-- migration replay due legacy dump ordering issues.

CREATE SEQUENCE IF NOT EXISTS public.fast_scalper_positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.fast_scalper_trades_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS public.fast_scalper_positions (
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
    CONSTRAINT fast_scalper_positions_side_check CHECK (side IN ('long', 'short', 'net'))
);

CREATE TABLE IF NOT EXISTS public.fast_scalper_trades (
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
    CONSTRAINT fast_scalper_trades_side_check CHECK (side = ANY (ARRAY['long'::text, 'short'::text, 'buy'::text, 'sell'::text, 'net'::text]))
);

ALTER TABLE public.fast_scalper_positions
    ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_positions_id_seq'::regclass);

ALTER TABLE public.fast_scalper_trades
    ALTER COLUMN id SET DEFAULT nextval('public.fast_scalper_trades_id_seq'::regclass);

ALTER SEQUENCE public.fast_scalper_positions_id_seq OWNED BY public.fast_scalper_positions.id;
ALTER SEQUENCE public.fast_scalper_trades_id_seq OWNED BY public.fast_scalper_trades.id;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        INNER JOIN pg_class t ON t.oid = c.conrelid
        INNER JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE c.conname = 'fast_scalper_positions_pkey'
          AND t.relname = 'fast_scalper_positions'
          AND n.nspname = 'public'
    ) THEN
        ALTER TABLE public.fast_scalper_positions
            ADD CONSTRAINT fast_scalper_positions_pkey PRIMARY KEY (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        INNER JOIN pg_class t ON t.oid = c.conrelid
        INNER JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE c.conname = 'fast_scalper_trades_pkey'
          AND t.relname = 'fast_scalper_trades'
          AND n.nspname = 'public'
    ) THEN
        ALTER TABLE public.fast_scalper_trades
            ADD CONSTRAINT fast_scalper_trades_pkey PRIMARY KEY (id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_fast_scalper_positions_unique_open
    ON public.fast_scalper_positions USING btree (user_id, symbol)
    WHERE (status = 'open'::text);

CREATE INDEX IF NOT EXISTS idx_fast_scalper_positions_user_symbol
    ON public.fast_scalper_positions USING btree (user_id, symbol, status);

CREATE INDEX IF NOT EXISTS idx_fast_scalper_trades_symbol
    ON public.fast_scalper_trades USING btree (symbol, exit_time DESC);

CREATE INDEX IF NOT EXISTS idx_fast_scalper_trades_user_time
    ON public.fast_scalper_trades USING btree (user_id, exit_time DESC);
