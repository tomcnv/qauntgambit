-- Migration: 052_normalize_percent_configs.sql
-- Normalize percent values to decimal form across configs and policies

BEGIN;

-- Normalize percent scalars (values > 1 treated as whole percentages)
CREATE OR REPLACE FUNCTION normalize_percent_value(value numeric)
RETURNS numeric AS $$
BEGIN
  IF value IS NULL THEN
    RETURN NULL;
  END IF;
  IF value > 1 THEN
    RETURN value / 100;
  END IF;
  RETURN value;
END;
$$ LANGUAGE plpgsql;

-- Normalize a JSONB key holding a numeric percent
CREATE OR REPLACE FUNCTION normalize_percent_jsonb(payload jsonb, key text)
RETURNS jsonb AS $$
DECLARE
  raw text;
  num numeric;
BEGIN
  IF payload IS NULL OR NOT (payload ? key) THEN
    RETURN payload;
  END IF;
  raw := payload->>key;
  IF raw IS NULL OR raw = '' THEN
    RETURN payload;
  END IF;
  BEGIN
    num := raw::numeric;
  EXCEPTION WHEN others THEN
    RETURN payload;
  END;
  IF num > 1 THEN
    RETURN jsonb_set(payload, ARRAY[key], to_jsonb(num / 100), true);
  END IF;
  RETURN payload;
END;
$$ LANGUAGE plpgsql;

-- Update user_exchange_credentials configs
UPDATE user_exchange_credentials
SET risk_config = normalize_percent_jsonb(
    normalize_percent_jsonb(
      normalize_percent_jsonb(
        normalize_percent_jsonb(
          normalize_percent_jsonb(risk_config, 'positionSizePct'),
        'maxDailyLossPct'),
      'maxTotalExposurePct'),
    'maxExposurePerSymbolPct'),
  'maxDailyLossPerSymbolPct')
WHERE risk_config IS NOT NULL;

UPDATE user_exchange_credentials
SET execution_config = normalize_percent_jsonb(
    normalize_percent_jsonb(
      normalize_percent_jsonb(execution_config, 'stopLossPct'),
    'takeProfitPct'),
  'trailingStopPct')
WHERE execution_config IS NOT NULL;

-- Update bot_exchange_configs configs
UPDATE bot_exchange_configs
SET risk_config = normalize_percent_jsonb(
    normalize_percent_jsonb(
      normalize_percent_jsonb(
        normalize_percent_jsonb(
          normalize_percent_jsonb(risk_config, 'positionSizePct'),
        'maxDailyLossPct'),
      'maxTotalExposurePct'),
    'maxExposurePerSymbolPct'),
  'maxDailyLossPerSymbolPct')
WHERE risk_config IS NOT NULL;

UPDATE bot_exchange_configs
SET execution_config = normalize_percent_jsonb(
    normalize_percent_jsonb(
      normalize_percent_jsonb(execution_config, 'stopLossPct'),
    'takeProfitPct'),
  'trailingStopPct')
WHERE execution_config IS NOT NULL;

-- Update bot_exchange_config_versions configs when present
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'bot_exchange_config_versions'
  ) THEN
    UPDATE bot_exchange_config_versions
    SET risk_config = normalize_percent_jsonb(
        normalize_percent_jsonb(
          normalize_percent_jsonb(
            normalize_percent_jsonb(
              normalize_percent_jsonb(risk_config, 'positionSizePct'),
            'maxDailyLossPct'),
          'maxTotalExposurePct'),
        'maxExposurePerSymbolPct'),
      'maxDailyLossPerSymbolPct')
    WHERE risk_config IS NOT NULL;

    UPDATE bot_exchange_config_versions
    SET execution_config = normalize_percent_jsonb(
        normalize_percent_jsonb(
          normalize_percent_jsonb(execution_config, 'stopLossPct'),
        'takeProfitPct'),
      'trailingStopPct')
    WHERE execution_config IS NOT NULL;
  END IF;
END $$;

-- Normalize user_trade_profiles defaults
ALTER TABLE user_trade_profiles
  ALTER COLUMN default_position_size_pct TYPE numeric(10,4) USING default_position_size_pct::numeric,
  ALTER COLUMN default_max_daily_loss_pct TYPE numeric(10,4) USING default_max_daily_loss_pct::numeric;

UPDATE user_trade_profiles
SET default_position_size_pct = normalize_percent_value(default_position_size_pct),
    default_max_daily_loss_pct = normalize_percent_value(default_max_daily_loss_pct)
WHERE default_position_size_pct IS NOT NULL
   OR default_max_daily_loss_pct IS NOT NULL;

-- Normalize percentage-based capital fields when present
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'bot_exchange_configs' AND column_name = 'trading_capital_pct'
  ) THEN
    ALTER TABLE bot_exchange_configs
      ALTER COLUMN trading_capital_pct TYPE numeric(10,4) USING trading_capital_pct::numeric,
      ALTER COLUMN position_size_pct TYPE numeric(10,4) USING position_size_pct::numeric;

    ALTER TABLE bot_exchange_configs
      DROP CONSTRAINT IF EXISTS check_trading_capital_pct_range,
      DROP CONSTRAINT IF EXISTS check_position_size_pct_range;

    ALTER TABLE bot_exchange_configs
      ADD CONSTRAINT check_trading_capital_pct_range
      CHECK (trading_capital_pct >= 0.01 AND trading_capital_pct <= 1.00);

    ALTER TABLE bot_exchange_configs
      ADD CONSTRAINT check_position_size_pct_range
      CHECK (position_size_pct >= 0.001 AND position_size_pct <= 1.00);

    UPDATE bot_exchange_configs
    SET trading_capital_pct = normalize_percent_value(trading_capital_pct),
        position_size_pct = normalize_percent_value(position_size_pct);
  END IF;
END $$;

-- Normalize bot_symbol_configs max_exposure_pct
ALTER TABLE bot_symbol_configs
  ALTER COLUMN max_exposure_pct TYPE numeric(10,4) USING max_exposure_pct::numeric;

UPDATE bot_symbol_configs
SET max_exposure_pct = normalize_percent_value(max_exposure_pct)
WHERE max_exposure_pct IS NOT NULL;

-- Normalize exchange limits
ALTER TABLE exchange_limits
  ALTER COLUMN min_stop_loss_pct TYPE numeric(10,4) USING min_stop_loss_pct::numeric;

UPDATE exchange_limits
SET min_stop_loss_pct = normalize_percent_value(min_stop_loss_pct)
WHERE min_stop_loss_pct IS NOT NULL;

-- Normalize tenant risk policies when present
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'tenant_risk_policies' AND column_name = 'max_daily_loss_pct'
  ) THEN
    ALTER TABLE tenant_risk_policies
      ALTER COLUMN max_daily_loss_pct TYPE numeric(10,4) USING max_daily_loss_pct::numeric,
      ALTER COLUMN max_total_exposure_pct TYPE numeric(10,4) USING max_total_exposure_pct::numeric,
      ALTER COLUMN max_single_position_pct TYPE numeric(10,4) USING max_single_position_pct::numeric,
      ALTER COLUMN max_per_symbol_exposure_pct TYPE numeric(10,4) USING max_per_symbol_exposure_pct::numeric,
      ALTER COLUMN min_reserve_pct TYPE numeric(10,4) USING min_reserve_pct::numeric,
      ALTER COLUMN circuit_breaker_loss_pct TYPE numeric(10,4) USING circuit_breaker_loss_pct::numeric;

    UPDATE tenant_risk_policies
    SET max_daily_loss_pct = normalize_percent_value(max_daily_loss_pct),
        max_total_exposure_pct = normalize_percent_value(max_total_exposure_pct),
        max_single_position_pct = normalize_percent_value(max_single_position_pct),
        max_per_symbol_exposure_pct = normalize_percent_value(max_per_symbol_exposure_pct),
        min_reserve_pct = normalize_percent_value(min_reserve_pct),
        circuit_breaker_loss_pct = normalize_percent_value(circuit_breaker_loss_pct);
  END IF;
END $$;

-- Normalize exchange policies when present
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'exchange_policies' AND column_name = 'max_daily_loss_pct'
  ) THEN
    ALTER TABLE exchange_policies
      ALTER COLUMN max_daily_loss_pct TYPE numeric(10,4) USING max_daily_loss_pct::numeric,
      ALTER COLUMN max_margin_used_pct TYPE numeric(10,4) USING max_margin_used_pct::numeric,
      ALTER COLUMN max_gross_exposure_pct TYPE numeric(10,4) USING max_gross_exposure_pct::numeric,
      ALTER COLUMN max_net_exposure_pct TYPE numeric(10,4) USING max_net_exposure_pct::numeric,
      ALTER COLUMN circuit_breaker_loss_pct TYPE numeric(10,4) USING circuit_breaker_loss_pct::numeric;

    UPDATE exchange_policies
    SET max_daily_loss_pct = normalize_percent_value(max_daily_loss_pct),
        max_margin_used_pct = normalize_percent_value(max_margin_used_pct),
        max_gross_exposure_pct = normalize_percent_value(max_gross_exposure_pct),
        max_net_exposure_pct = normalize_percent_value(max_net_exposure_pct),
        circuit_breaker_loss_pct = normalize_percent_value(circuit_breaker_loss_pct);
  END IF;
END $$;

COMMIT;
