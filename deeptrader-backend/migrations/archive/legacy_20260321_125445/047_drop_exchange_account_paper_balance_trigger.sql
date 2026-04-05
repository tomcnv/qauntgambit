-- Migration: Remove exchange-account paper balance trigger (obsolete)
-- Created: 2026-02-18
-- Description:
--   Migration 044 created a trigger on exchange_accounts to auto-create a paper_balances row:
--     create_paper_balance_on_account_insert()
--   Migration 046 moved paper trading to bot-level balances and dropped the unique constraint
--   on (exchange_account_id, currency). If the old trigger still exists, inserts into
--   exchange_accounts can fail with:
--     "there is no unique or exclusion constraint matching the ON CONFLICT specification"
--
--   This migration removes the obsolete trigger/function. It is idempotent.

DROP TRIGGER IF EXISTS trigger_create_paper_balance ON exchange_accounts;
DROP FUNCTION IF EXISTS create_paper_balance_on_account_insert();

