-- Migration: Create portfolios table (missing dependency)
-- Date: 2026-02-17
-- Notes:
-- - Several early migrations reference portfolios(id) but the table was never created in migrations.
-- - Local dev DB already has this table; this migration aligns AWS/local.

CREATE TABLE IF NOT EXISTS public.portfolios (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    name character varying(100) DEFAULT 'Main Portfolio'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'portfolios_pkey'
          AND conrelid = 'public.portfolios'::regclass
    ) THEN
        ALTER TABLE ONLY public.portfolios
            ADD CONSTRAINT portfolios_pkey PRIMARY KEY (id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'portfolios_user_id_fkey'
          AND conrelid = 'public.portfolios'::regclass
    ) THEN
        ALTER TABLE ONLY public.portfolios
            ADD CONSTRAINT portfolios_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON public.portfolios(user_id);

-- Keep updated_at consistent with users updated_at trigger if present.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        DROP TRIGGER IF EXISTS update_portfolios_updated_at ON public.portfolios;
        CREATE TRIGGER update_portfolios_updated_at
            BEFORE UPDATE ON public.portfolios
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

