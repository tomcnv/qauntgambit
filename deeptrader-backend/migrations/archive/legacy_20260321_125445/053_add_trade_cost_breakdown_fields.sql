-- Migration: Add granular trade cost breakdown fields
-- Date: 2026-02-14
-- Description: Adds per-leg fees/slippage and normalized total_cost_bps fields.

ALTER TABLE IF EXISTS trade_costs
    ADD COLUMN IF NOT EXISTS entry_fee_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS exit_fee_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS entry_fee_bps NUMERIC,
    ADD COLUMN IF NOT EXISTS exit_fee_bps NUMERIC,
    ADD COLUMN IF NOT EXISTS entry_slippage_bps NUMERIC,
    ADD COLUMN IF NOT EXISTS exit_slippage_bps NUMERIC,
    ADD COLUMN IF NOT EXISTS spread_cost_bps NUMERIC,
    ADD COLUMN IF NOT EXISTS adverse_selection_bps NUMERIC,
    ADD COLUMN IF NOT EXISTS total_cost_bps NUMERIC;

