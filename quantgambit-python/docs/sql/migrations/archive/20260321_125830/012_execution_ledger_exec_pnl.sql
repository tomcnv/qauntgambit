-- Ensure execution_ledger captures exchange-reported realized PnL per execution.
-- This is required for exchange-authoritative trade/PnL reconciliation (Bybit v5 execPnl).

ALTER TABLE execution_ledger
  ADD COLUMN IF NOT EXISTS exec_pnl double precision;

