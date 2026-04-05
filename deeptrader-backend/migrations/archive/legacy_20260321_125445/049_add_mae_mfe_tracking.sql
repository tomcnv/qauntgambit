-- Migration: Add MAE/MFE Price Tracking to Paper Positions
-- This enables tracking high/low prices during position hold time
-- to calculate MAE (Max Adverse Excursion) and MFE (Max Favorable Excursion)
-- when positions are closed.

-- =========================================================================
-- 1. Add high_price and low_price columns to paper_positions
-- =========================================================================
ALTER TABLE paper_positions 
ADD COLUMN IF NOT EXISTS high_price NUMERIC(18, 8) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS low_price NUMERIC(18, 8) DEFAULT NULL;

-- Comment on columns
COMMENT ON COLUMN paper_positions.high_price IS 'Highest price reached since position opened (for MFE calculation)';
COMMENT ON COLUMN paper_positions.low_price IS 'Lowest price reached since position opened (for MAE calculation)';

-- =========================================================================
-- 2. Initialize high_price and low_price for existing open positions
-- =========================================================================
UPDATE paper_positions 
SET 
    high_price = COALESCE(current_price, entry_price),
    low_price = COALESCE(current_price, entry_price)
WHERE status = 'open' 
  AND high_price IS NULL;

-- =========================================================================
-- 3. Add mae_bps and mfe_bps columns for basis point representation
-- =========================================================================
ALTER TABLE paper_trades 
ADD COLUMN IF NOT EXISTS mae_bps NUMERIC(10, 2) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS mfe_bps NUMERIC(10, 2) DEFAULT NULL;

COMMENT ON COLUMN paper_trades.mae_bps IS 'Max Adverse Excursion in basis points';
COMMENT ON COLUMN paper_trades.mfe_bps IS 'Max Favorable Excursion in basis points';

-- =========================================================================
-- 4. Create function to update high/low prices on position price updates
-- =========================================================================
CREATE OR REPLACE FUNCTION update_paper_position_high_low()
RETURNS TRIGGER AS $$
BEGIN
    -- Update high_price if current price is higher
    IF NEW.current_price IS NOT NULL THEN
        NEW.high_price := GREATEST(COALESCE(NEW.high_price, NEW.current_price), NEW.current_price);
        NEW.low_price := LEAST(COALESCE(NEW.low_price, NEW.current_price), NEW.current_price);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger (drop if exists first)
DROP TRIGGER IF EXISTS paper_position_high_low_trigger ON paper_positions;
CREATE TRIGGER paper_position_high_low_trigger
BEFORE UPDATE ON paper_positions
FOR EACH ROW
WHEN (OLD.status = 'open' AND NEW.current_price IS DISTINCT FROM OLD.current_price)
EXECUTE FUNCTION update_paper_position_high_low();

-- =========================================================================
-- 5. Create function to calculate MAE/MFE when closing a position
-- =========================================================================
CREATE OR REPLACE FUNCTION calculate_mae_mfe(
    p_entry_price NUMERIC,
    p_high_price NUMERIC,
    p_low_price NUMERIC,
    p_side VARCHAR(10)
)
RETURNS TABLE (mae NUMERIC, mfe NUMERIC, mae_bps NUMERIC, mfe_bps NUMERIC) AS $$
DECLARE
    v_mae NUMERIC;
    v_mfe NUMERIC;
    v_mae_bps NUMERIC;
    v_mfe_bps NUMERIC;
BEGIN
    IF p_side IN ('long', 'buy', 'LONG', 'BUY') THEN
        -- For long positions:
        -- MAE = how far price dropped below entry (adverse)
        -- MFE = how far price rose above entry (favorable)
        v_mae := p_entry_price - COALESCE(p_low_price, p_entry_price);
        v_mfe := COALESCE(p_high_price, p_entry_price) - p_entry_price;
    ELSE
        -- For short positions:
        -- MAE = how far price rose above entry (adverse)
        -- MFE = how far price dropped below entry (favorable)
        v_mae := COALESCE(p_high_price, p_entry_price) - p_entry_price;
        v_mfe := p_entry_price - COALESCE(p_low_price, p_entry_price);
    END IF;
    
    -- Convert to basis points (relative to entry price)
    IF p_entry_price > 0 THEN
        v_mae_bps := (v_mae / p_entry_price) * 10000;
        v_mfe_bps := (v_mfe / p_entry_price) * 10000;
    ELSE
        v_mae_bps := 0;
        v_mfe_bps := 0;
    END IF;
    
    -- Ensure non-negative values
    v_mae := GREATEST(v_mae, 0);
    v_mfe := GREATEST(v_mfe, 0);
    v_mae_bps := GREATEST(v_mae_bps, 0);
    v_mfe_bps := GREATEST(v_mfe_bps, 0);
    
    mae := v_mae;
    mfe := v_mfe;
    mae_bps := v_mae_bps;
    mfe_bps := v_mfe_bps;
    
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- =========================================================================
-- 6. Add index for querying trades with MAE/MFE data
-- =========================================================================
CREATE INDEX IF NOT EXISTS idx_paper_trades_mae_mfe 
ON paper_trades(exchange_account_id, executed_at DESC) 
WHERE mae IS NOT NULL OR mfe IS NOT NULL;

-- =========================================================================
-- Done!
-- =========================================================================


