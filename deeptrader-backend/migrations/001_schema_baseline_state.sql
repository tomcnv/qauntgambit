CREATE TABLE IF NOT EXISTS public.schema_baseline_state (
    schema_name text NOT NULL,
    schema_path text NOT NULL,
    schema_checksum text NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'schema_baseline_state_pkey'
          AND conrelid = 'public.schema_baseline_state'::regclass
    ) THEN
        ALTER TABLE ONLY public.schema_baseline_state
            ADD CONSTRAINT schema_baseline_state_pkey PRIMARY KEY (schema_name);
    END IF;
END;
$$;
