/**
 * Strategy Template Model
 * 
 * Strategy templates define trading logic, profile bundles, and default parameters.
 * They are the "what the bot does" layer, separate from runtime configuration.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Default risk configuration for templates
 */
export const DEFAULT_RISK_CONFIG = {
  positionSizePct: 0.10,
  maxPositions: 4,
  maxDailyLossPct: 0.05,
  maxTotalExposurePct: 0.80,
  maxLeverage: 1,
  leverageMode: 'isolated',
  maxExposurePerSymbolPct: 0.25,
  maxPositionsPerSymbol: 1,
  maxDailyLossPerSymbolPct: 0.025,
  minPositionSizeUsd: 10,
  maxPositionSizeUsd: null,
  maxPositionsPerStrategy: 0,
  maxDrawdownPct: 0.10,
};

/**
 * Default execution configuration for templates
 */
export const DEFAULT_EXECUTION_CONFIG = {
  defaultOrderType: 'market',
  stopLossPct: 0.02,
  takeProfitPct: 0.05,
  trailingStopEnabled: false,
  trailingStopPct: 0.01,
  maxHoldTimeHours: 24,
  throttleMode: 'swing',  // Trading throttle mode: 'scalping', 'swing', or 'conservative'
  orderIntentMaxAgeSec: 0,
};

/**
 * Get all strategy templates
 */
export async function getAllTemplates(includeInactive = false) {
  const query = includeInactive
    ? `SELECT * FROM strategy_templates ORDER BY is_system DESC, name ASC`
    : `SELECT * FROM strategy_templates WHERE is_active = true ORDER BY is_system DESC, name ASC`;
  
  const result = await pool.query(query);
  return result.rows;
}

/**
 * Get a strategy template by ID
 */
export async function getTemplateById(templateId) {
  const result = await pool.query(
    `SELECT * FROM strategy_templates WHERE id = $1`,
    [templateId]
  );
  return result.rows[0] || null;
}

/**
 * Get a strategy template by slug
 */
export async function getTemplateBySlug(slug) {
  const result = await pool.query(
    `SELECT * FROM strategy_templates WHERE slug = $1`,
    [slug]
  );
  return result.rows[0] || null;
}

/**
 * Create a new strategy template
 */
export async function createTemplate({
  name,
  slug,
  description,
  strategyFamily = 'scalper',
  timeframe = '1m',
  defaultProfileBundle = {},
  defaultRiskConfig = DEFAULT_RISK_CONFIG,
  defaultExecutionConfig = DEFAULT_EXECUTION_CONFIG,
  supportedExchanges = ['binance', 'okx', 'bybit'],
  recommendedSymbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP'],
  isSystem = false,
  createdBy = null,
  metadata = {},
}) {
  const templateId = randomUUID();
  
  const result = await pool.query(
    `INSERT INTO strategy_templates (
      id, name, slug, description, strategy_family, timeframe,
      default_profile_bundle, default_risk_config, default_execution_config,
      supported_exchanges, recommended_symbols, is_system, created_by, metadata
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
    RETURNING *`,
    [
      templateId, name, slug, description, strategyFamily, timeframe,
      JSON.stringify(defaultProfileBundle),
      JSON.stringify(defaultRiskConfig),
      JSON.stringify(defaultExecutionConfig),
      supportedExchanges, recommendedSymbols, isSystem, createdBy,
      JSON.stringify(metadata),
    ]
  );
  
  return result.rows[0];
}

/**
 * Update a strategy template
 */
export async function updateTemplate(templateId, updates) {
  const allowedFields = [
    'name', 'description', 'strategy_family', 'timeframe',
    'default_profile_bundle', 'default_risk_config', 'default_execution_config',
    'supported_exchanges', 'recommended_symbols', 'is_active', 'metadata',
  ];
  
  const setClause = [];
  const values = [];
  let paramIndex = 1;
  
  for (const [key, value] of Object.entries(updates)) {
    const dbKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
    if (allowedFields.includes(dbKey)) {
      setClause.push(`${dbKey} = $${paramIndex}`);
      values.push(typeof value === 'object' ? JSON.stringify(value) : value);
      paramIndex++;
    }
  }
  
  if (setClause.length === 0) {
    throw new Error('No valid fields to update');
  }
  
  // Increment version
  setClause.push(`version = version + 1`);
  
  values.push(templateId);
  
  const result = await pool.query(
    `UPDATE strategy_templates
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Delete a strategy template (soft delete by setting is_active = false)
 */
export async function deleteTemplate(templateId) {
  const result = await pool.query(
    `UPDATE strategy_templates SET is_active = false WHERE id = $1 AND is_system = false RETURNING *`,
    [templateId]
  );
  return result.rows[0];
}

/**
 * Get templates by strategy family
 */
export async function getTemplatesByFamily(strategyFamily) {
  const result = await pool.query(
    `SELECT * FROM strategy_templates 
     WHERE strategy_family = $1 AND is_active = true
     ORDER BY is_system DESC, name ASC`,
    [strategyFamily]
  );
  return result.rows;
}

export default {
  getAllTemplates,
  getTemplateById,
  getTemplateBySlug,
  createTemplate,
  updateTemplate,
  deleteTemplate,
  getTemplatesByFamily,
  DEFAULT_RISK_CONFIG,
  DEFAULT_EXECUTION_CONFIG,
};

