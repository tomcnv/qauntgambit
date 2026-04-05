-- Migration: Add leverage columns to positions table
-- Date: $(date)
-- Description: Add leverage-related columns for margin trading position tracking

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS leverage DECIMAL(5,2) DEFAULT 1.0;

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS initial_margin NUMERIC(18,8) DEFAULT 0;

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS maintenance_margin NUMERIC(18,8) DEFAULT 0;

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS liquidation_price NUMERIC(18,8) NULL;

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS margin_ratio NUMERIC(8,2) DEFAULT 0;

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS margin_mode VARCHAR(20) DEFAULT 'isolated'
  CHECK (margin_mode IN ('isolated', 'cross'));

-- Update existing records to have default values
UPDATE positions
SET
  leverage = COALESCE(leverage, 1.0),
  initial_margin = COALESCE(initial_margin, entry_price * quantity),
  maintenance_margin = COALESCE(maintenance_margin, entry_price * quantity),
  margin_ratio = COALESCE(margin_ratio, 100.0),
  margin_mode = COALESCE(margin_mode, 'isolated')
WHERE leverage IS NULL
   OR initial_margin IS NULL
   OR maintenance_margin IS NULL
   OR margin_ratio IS NULL
   OR margin_mode IS NULL;

-- Add index for efficient leverage queries
CREATE INDEX IF NOT EXISTS idx_positions_leverage ON positions(leverage);
CREATE INDEX IF NOT EXISTS idx_positions_margin_ratio ON positions(margin_ratio);
CREATE INDEX IF NOT EXISTS idx_positions_liquidation_price ON positions(liquidation_price);
