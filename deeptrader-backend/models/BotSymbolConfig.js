/**
 * Bot Symbol Config Model
 * 
 * Per-symbol overrides within a bot-exchange configuration.
 * Allows granular control for each symbol (position sizing, leverage, risk).
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Get all symbol configs for a bot exchange config
 */
export async function getSymbolConfigsByParent(botExchangeConfigId) {
  const result = await pool.query(
    `SELECT * FROM bot_symbol_configs
     WHERE bot_exchange_config_id = $1
     ORDER BY symbol ASC`,
    [botExchangeConfigId]
  );
  return result.rows;
}

/**
 * Get enabled symbol configs only
 */
export async function getEnabledSymbolConfigs(botExchangeConfigId) {
  const result = await pool.query(
    `SELECT * FROM bot_symbol_configs
     WHERE bot_exchange_config_id = $1 AND enabled = true
     ORDER BY symbol ASC`,
    [botExchangeConfigId]
  );
  return result.rows;
}

/**
 * Get a specific symbol config
 */
export async function getSymbolConfig(botExchangeConfigId, symbol) {
  const result = await pool.query(
    `SELECT * FROM bot_symbol_configs
     WHERE bot_exchange_config_id = $1 AND symbol = $2`,
    [botExchangeConfigId, symbol]
  );
  return result.rows[0] || null;
}

/**
 * Create or update a symbol config (upsert)
 */
export async function upsertSymbolConfig(botExchangeConfigId, symbol, config) {
  const {
    enabled = true,
    maxExposurePct = null,
    maxPositionSizeUsd = null,
    maxPositions = 1,
    maxLeverage = null,
    symbolRiskConfig = {},
    symbolProfileOverrides = {},
    preferredOrderType = null,
    maxSlippageBps = null,
    notes = null,
    metadata = {},
  } = config;
  
  const result = await pool.query(
    `INSERT INTO bot_symbol_configs (
      id, bot_exchange_config_id, symbol, enabled, max_exposure_pct,
      max_position_size_usd, max_positions, max_leverage, symbol_risk_config,
      symbol_profile_overrides, preferred_order_type, max_slippage_bps, notes, metadata
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
    ON CONFLICT (bot_exchange_config_id, symbol)
    DO UPDATE SET
      enabled = EXCLUDED.enabled,
      max_exposure_pct = EXCLUDED.max_exposure_pct,
      max_position_size_usd = EXCLUDED.max_position_size_usd,
      max_positions = EXCLUDED.max_positions,
      max_leverage = EXCLUDED.max_leverage,
      symbol_risk_config = EXCLUDED.symbol_risk_config,
      symbol_profile_overrides = EXCLUDED.symbol_profile_overrides,
      preferred_order_type = EXCLUDED.preferred_order_type,
      max_slippage_bps = EXCLUDED.max_slippage_bps,
      notes = EXCLUDED.notes,
      metadata = EXCLUDED.metadata,
      updated_at = NOW()
    RETURNING *`,
    [
      randomUUID(), botExchangeConfigId, symbol, enabled, maxExposurePct,
      maxPositionSizeUsd, maxPositions, maxLeverage,
      JSON.stringify(symbolRiskConfig),
      JSON.stringify(symbolProfileOverrides),
      preferredOrderType, maxSlippageBps, notes,
      JSON.stringify(metadata),
    ]
  );
  
  return result.rows[0];
}

/**
 * Bulk upsert symbol configs
 */
export async function bulkUpsertSymbolConfigs(botExchangeConfigId, symbolConfigs) {
  const results = [];
  for (const [symbol, config] of Object.entries(symbolConfigs)) {
    const result = await upsertSymbolConfig(botExchangeConfigId, symbol, config);
    results.push(result);
  }
  return results;
}

/**
 * Enable a symbol
 */
export async function enableSymbol(botExchangeConfigId, symbol) {
  const result = await pool.query(
    `UPDATE bot_symbol_configs
     SET enabled = true
     WHERE bot_exchange_config_id = $1 AND symbol = $2
     RETURNING *`,
    [botExchangeConfigId, symbol]
  );
  
  if (result.rows.length === 0) {
    // Create a new config if it doesn't exist
    return upsertSymbolConfig(botExchangeConfigId, symbol, { enabled: true });
  }
  
  return result.rows[0];
}

/**
 * Disable a symbol
 */
export async function disableSymbol(botExchangeConfigId, symbol) {
  const result = await pool.query(
    `UPDATE bot_symbol_configs
     SET enabled = false
     WHERE bot_exchange_config_id = $1 AND symbol = $2
     RETURNING *`,
    [botExchangeConfigId, symbol]
  );
  
  if (result.rows.length === 0) {
    // Create a new config if it doesn't exist
    return upsertSymbolConfig(botExchangeConfigId, symbol, { enabled: false });
  }
  
  return result.rows[0];
}

/**
 * Delete a symbol config
 */
export async function deleteSymbolConfig(botExchangeConfigId, symbol) {
  const result = await pool.query(
    `DELETE FROM bot_symbol_configs
     WHERE bot_exchange_config_id = $1 AND symbol = $2
     RETURNING *`,
    [botExchangeConfigId, symbol]
  );
  return result.rows[0];
}

/**
 * Get symbols with their effective configuration (merged with defaults)
 */
export async function getEffectiveSymbolConfigs(botExchangeConfigId, defaultRiskConfig = {}) {
  const symbolConfigs = await getSymbolConfigsByParent(botExchangeConfigId);
  
  return symbolConfigs.map(sc => ({
    symbol: sc.symbol,
    enabled: sc.enabled,
    maxExposurePct: sc.max_exposure_pct ?? defaultRiskConfig.positionSizePct ?? 0.10,
    maxPositionSizeUsd: sc.max_position_size_usd,
    maxPositions: sc.max_positions ?? 1,
    maxLeverage: sc.max_leverage ?? defaultRiskConfig.maxLeverage ?? 1,
    riskConfig: {
      ...defaultRiskConfig,
      ...(sc.symbol_risk_config || {}),
    },
    profileOverrides: sc.symbol_profile_overrides || {},
    preferredOrderType: sc.preferred_order_type,
    maxSlippageBps: sc.max_slippage_bps,
  }));
}

export default {
  getSymbolConfigsByParent,
  getEnabledSymbolConfigs,
  getSymbolConfig,
  upsertSymbolConfig,
  bulkUpsertSymbolConfigs,
  enableSymbol,
  disableSymbol,
  deleteSymbolConfig,
  getEffectiveSymbolConfigs,
};


