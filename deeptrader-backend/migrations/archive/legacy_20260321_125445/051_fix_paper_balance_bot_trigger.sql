-- Migration: Fix bot-level paper balance trigger for nullable exchange_account_id
-- Created: 2026-02-18
-- Description:
--   Migration 046 introduced a bot_instances trigger that creates a paper_balances row
--   on bot insert/update when trading_mode='paper'. It attempted to write NEW.exchange_account_id
--   into paper_balances.exchange_account_id, but bot instances may be created before any
--   exchange config is attached, leaving exchange_account_id NULL and causing:
--     null value in column "exchange_account_id" of relation "paper_balances" violates not-null constraint
--
--   Fix:
--   - Allow paper_balances.exchange_account_id to be NULL (bot-level balances).
--   - Update/create the trigger function to insert without exchange_account_id.
--
--   This migration is idempotent and safe to run multiple times.

DO $$
BEGIN
  IF to_regclass('public.paper_balances') IS NOT NULL
     AND EXISTS (
       SELECT 1
       FROM information_schema.columns
       WHERE table_schema='public' AND table_name='paper_balances' AND column_name='exchange_account_id'
         AND is_nullable='NO'
     )
  THEN
    ALTER TABLE public.paper_balances
      ALTER COLUMN exchange_account_id DROP NOT NULL;
  END IF;
END $$;

-- Create/update function in a way that does not reference NEW.exchange_account_id.
CREATE OR REPLACE FUNCTION public.create_paper_balance_for_bot_instance()
RETURNS TRIGGER AS $$
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
$$ LANGUAGE plpgsql;

-- Ensure triggers exist and point at the updated function.
DROP TRIGGER IF EXISTS trigger_create_paper_balance_for_bot ON public.bot_instances;
CREATE TRIGGER trigger_create_paper_balance_for_bot
  AFTER INSERT ON public.bot_instances
  FOR EACH ROW
  EXECUTE FUNCTION public.create_paper_balance_for_bot_instance();

DROP TRIGGER IF EXISTS trigger_create_paper_balance_on_mode_change ON public.bot_instances;
CREATE TRIGGER trigger_create_paper_balance_on_mode_change
  AFTER UPDATE OF trading_mode ON public.bot_instances
  FOR EACH ROW
  WHEN (NEW.trading_mode = 'paper' AND (OLD.trading_mode IS NULL OR OLD.trading_mode != 'paper'))
  EXECUTE FUNCTION public.create_paper_balance_for_bot_instance();

