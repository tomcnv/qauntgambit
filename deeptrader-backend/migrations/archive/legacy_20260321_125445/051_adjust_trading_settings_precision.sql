-- Migration: Increase precision for decimal percent fields in user_trading_settings
-- Created: 2025-11-18

ALTER TABLE user_trading_settings
ALTER COLUMN max_position_size_percent TYPE numeric(10,4) USING max_position_size_percent::numeric,
ALTER COLUMN max_total_exposure_percent TYPE numeric(10,4) USING max_total_exposure_percent::numeric,
ALTER COLUMN scalping_target_profit_percent TYPE numeric(10,4) USING scalping_target_profit_percent::numeric,
ALTER COLUMN trailing_stop_activation_percent TYPE numeric(10,4) USING trailing_stop_activation_percent::numeric,
ALTER COLUMN trailing_stop_callback_percent TYPE numeric(10,4) USING trailing_stop_callback_percent::numeric,
ALTER COLUMN trailing_stop_step_percent TYPE numeric(10,4) USING trailing_stop_step_percent::numeric,
ALTER COLUMN liquidation_buffer_percent TYPE numeric(10,4) USING liquidation_buffer_percent::numeric,
ALTER COLUMN margin_call_threshold_percent TYPE numeric(10,4) USING margin_call_threshold_percent::numeric;

ALTER TABLE user_trading_settings
ALTER COLUMN max_position_size_percent SET DEFAULT 0.10,
ALTER COLUMN max_total_exposure_percent SET DEFAULT 0.40,
ALTER COLUMN scalping_target_profit_percent SET DEFAULT 0.005,
ALTER COLUMN trailing_stop_activation_percent SET DEFAULT 0.02,
ALTER COLUMN trailing_stop_callback_percent SET DEFAULT 0.01,
ALTER COLUMN trailing_stop_step_percent SET DEFAULT 0.005,
ALTER COLUMN liquidation_buffer_percent SET DEFAULT 0.05,
ALTER COLUMN margin_call_threshold_percent SET DEFAULT 0.20;

UPDATE user_trading_settings
SET
  max_position_size_percent = CASE
    WHEN max_position_size_percent > 1 THEN max_position_size_percent / 100
    ELSE max_position_size_percent
  END,
  max_total_exposure_percent = CASE
    WHEN max_total_exposure_percent > 1 THEN max_total_exposure_percent / 100
    ELSE max_total_exposure_percent
  END,
  scalping_target_profit_percent = CASE
    WHEN scalping_target_profit_percent > 1 THEN scalping_target_profit_percent / 100
    ELSE scalping_target_profit_percent
  END,
  trailing_stop_activation_percent = CASE
    WHEN trailing_stop_activation_percent > 1 THEN trailing_stop_activation_percent / 100
    ELSE trailing_stop_activation_percent
  END,
  trailing_stop_callback_percent = CASE
    WHEN trailing_stop_callback_percent > 1 THEN trailing_stop_callback_percent / 100
    ELSE trailing_stop_callback_percent
  END,
  trailing_stop_step_percent = CASE
    WHEN trailing_stop_step_percent > 1 THEN trailing_stop_step_percent / 100
    ELSE trailing_stop_step_percent
  END,
  liquidation_buffer_percent = CASE
    WHEN liquidation_buffer_percent > 1 THEN liquidation_buffer_percent / 100
    ELSE liquidation_buffer_percent
  END,
  margin_call_threshold_percent = CASE
    WHEN margin_call_threshold_percent > 1 THEN margin_call_threshold_percent / 100
    ELSE margin_call_threshold_percent
  END,
  partial_profit_levels = (
    SELECT jsonb_agg(
      CASE
        WHEN (elem->>'target')::numeric > 1
          THEN jsonb_set(elem, '{target}', to_jsonb(((elem->>'target')::numeric) / 100))
        ELSE elem
      END
    )
    FROM jsonb_array_elements(partial_profit_levels) elem
  )
WHERE partial_profit_levels IS NOT NULL;
