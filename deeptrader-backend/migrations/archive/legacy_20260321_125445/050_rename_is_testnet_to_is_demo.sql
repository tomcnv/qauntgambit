-- Migration: Rename is_testnet to is_demo
-- Reason: is_testnet was ambiguous (could mean testnet or demo trading)
-- - Bybit has both testnet AND demo (different things)
-- - OKX only has demo trading (via header)
-- - Binance testnet is deprecated, no demo
-- This rename clarifies the intent: is_demo means exchange demo/simulated trading

-- Rename in exchange_accounts table
DO $$
BEGIN
  IF to_regclass('public.exchange_accounts') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='exchange_accounts' AND column_name='is_testnet'
     )
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='exchange_accounts' AND column_name='is_demo'
     )
  THEN
    ALTER TABLE public.exchange_accounts RENAME COLUMN is_testnet TO is_demo;
  END IF;
END $$;

-- Rename in user_exchange_credentials table
DO $$
BEGIN
  IF to_regclass('public.user_exchange_credentials') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='user_exchange_credentials' AND column_name='is_testnet'
     )
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='user_exchange_credentials' AND column_name='is_demo'
     )
  THEN
    ALTER TABLE public.user_exchange_credentials RENAME COLUMN is_testnet TO is_demo;
  END IF;
END $$;

-- Add comment for clarity
DO $$
BEGIN
  IF to_regclass('public.exchange_accounts') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='exchange_accounts' AND column_name='is_demo'
     )
  THEN
    COMMENT ON COLUMN public.exchange_accounts.is_demo IS 'True if using exchange demo trading (Bybit api-demo, OKX simulated). Not available for Binance.';
  END IF;

  IF to_regclass('public.user_exchange_credentials') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='user_exchange_credentials' AND column_name='is_demo'
     )
  THEN
    COMMENT ON COLUMN public.user_exchange_credentials.is_demo IS 'True if using exchange demo trading (Bybit api-demo, OKX simulated). Not available for Binance.';
  END IF;
END $$;
