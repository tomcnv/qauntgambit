/**
 * Bot Instance Model
 * 
 * Bot instances are user-facing bots that reference strategy templates.
 * Each user can have multiple bot instances with different configurations.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Default risk configuration for bot instances
 */
export const DEFAULT_RISK_CONFIG = {
  positionSizePct: 0.10,
  maxPositions: 4,
  maxDailyLossPct: 0.05,
  maxTotalExposurePct: 0.80,
  maxLeverage: 1,
  leverageMode: 'isolated',
  maxPositionsPerSymbol: 1,
  maxDailyLossPerSymbolPct: 0.025,
  maxExposurePerSymbolPct: 0.25,  // Must be >= positionSizePct or trades will be rejected
  minPositionSizeUsd: 10,
  maxPositionSizeUsd: null,
  maxPositionsPerStrategy: 0,
  maxDrawdownPct: 0.10,
};

/**
 * Default execution configuration for bot instances
 */
export const DEFAULT_EXECUTION_CONFIG = {
  defaultOrderType: 'market',
  stopLossPct: 0.02,
  takeProfitPct: 0.05,
  trailingStopEnabled: false,
  trailingStopPct: 0.01,
  maxHoldTimeHours: 24,
  minTradeIntervalSec: 1,
  executionTimeoutSec: 5,
  enableVolatilityFilter: true,
  throttleMode: 'swing',  // Trading throttle mode: 'scalping', 'swing', or 'conservative'
  orderIntentMaxAgeSec: 0,
};

/**
 * Allocator roles for portfolio management
 */
export const ALLOCATOR_ROLES = ['core', 'satellite', 'hedge', 'experimental'];

/**
 * Get all bot instances for a user
 * By default, excludes deleted bots (deleted_at IS NULL)
 */
export async function getBotInstancesByUser(userId, includeInactive = false, includeDeleted = false) {
  let baseCondition = 'bi.user_id = $1';
  
  // Exclude deleted bots unless explicitly requested
  if (!includeDeleted) {
    baseCondition += ' AND bi.deleted_at IS NULL';
  }
  
  // Exclude inactive bots unless requested
  if (!includeInactive) {
    baseCondition += ' AND bi.is_active = true';
  }
  
  const query = `
    SELECT bi.*, st.name as template_name, st.slug as template_slug, st.strategy_family
    FROM bot_instances bi
    LEFT JOIN strategy_templates st ON bi.strategy_template_id = st.id
    WHERE ${baseCondition}
    ORDER BY bi.created_at DESC`;
  
  const result = await pool.query(query, [userId]);
  return result.rows;
}

/**
 * Get a bot instance by ID
 * Excludes deleted bots by default
 */
export async function getBotInstanceById(botId, userId = null, includeDeleted = false) {
  let query = `
    SELECT bi.*, st.name as template_name, st.slug as template_slug, 
           st.strategy_family, st.default_profile_bundle as template_profile_bundle
    FROM bot_instances bi
    LEFT JOIN strategy_templates st ON bi.strategy_template_id = st.id
    WHERE bi.id = $1`;
  const params = [botId];
  
  if (userId) {
    query += ` AND bi.user_id = $2`;
    params.push(userId);
  }
  
  // Exclude deleted bots unless explicitly requested
  if (!includeDeleted) {
    query += ` AND bi.deleted_at IS NULL`;
  }
  
  const result = await pool.query(query, params);
  return result.rows[0] || null;
}

/**
 * Create a new bot instance
 */
export async function createBotInstance(userId, {
  name,
  description,
  strategyTemplateId = null,
  allocatorRole = 'core',
  marketType = 'perp',
  defaultRiskConfig = DEFAULT_RISK_CONFIG,
  defaultExecutionConfig = DEFAULT_EXECUTION_CONFIG,
  profileOverrides = {},
  tags = [],
  metadata = {},
}) {
  const botId = randomUUID();
  
  const result = await pool.query(
    `INSERT INTO bot_instances (
      id, user_id, name, description, strategy_template_id, allocator_role, market_type,
      default_risk_config, default_execution_config, profile_overrides, tags, metadata
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    RETURNING *`,
    [
      botId, userId, name, description, strategyTemplateId, allocatorRole, marketType,
      JSON.stringify(defaultRiskConfig),
      JSON.stringify(defaultExecutionConfig),
      JSON.stringify(profileOverrides),
      tags,
      JSON.stringify(metadata),
    ]
  );
  
  return result.rows[0];
}

/**
 * Update a bot instance
 */
export async function updateBotInstance(botId, userId, updates) {
  const allowedFields = [
    'name', 'description', 'strategy_template_id', 'allocator_role', 'market_type',
    'default_risk_config', 'default_execution_config', 'profile_overrides',
    'tags', 'is_active', 'metadata',
  ];
  
  const setClause = [];
  const values = [];
  let paramIndex = 1;
  
  for (const [key, value] of Object.entries(updates)) {
    const dbKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
    if (allowedFields.includes(dbKey)) {
      setClause.push(`${dbKey} = $${paramIndex}`);
      values.push(typeof value === 'object' && !Array.isArray(value) ? JSON.stringify(value) : value);
      paramIndex++;
    }
  }
  
  if (setClause.length === 0) {
    throw new Error('No valid fields to update');
  }
  
  values.push(botId, userId);
  
  const result = await pool.query(
    `UPDATE bot_instances
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex} AND user_id = $${paramIndex + 1}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Delete a bot instance (soft delete)
 */
/**
 * Soft delete a bot instance (sets deleted_at timestamp)
 * - The bot will no longer appear in normal queries
 * - Trade history and audit logs are preserved
 * - Symbol locks are released
 */
export async function deleteBotInstance(botId, userId) {
  // First, release any symbol locks owned by this bot
  await pool.query(
    `DELETE FROM symbol_locks WHERE owner_bot_id = $1`,
    [botId]
  );
  
  // Soft delete the bot (set deleted_at, is_active = false)
  const result = await pool.query(
    `UPDATE bot_instances 
     SET is_active = false, 
         deleted_at = NOW(),
         deleted_by = $2
     WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL
     RETURNING *`,
    [botId, userId]
  );
  
  // Also soft-delete all exchange configs for this bot
  if (result.rows[0]) {
    await pool.query(
      `UPDATE bot_exchange_configs 
       SET deleted_at = NOW(), state = 'decommissioned'
       WHERE bot_instance_id = $1`,
      [botId]
    );
  }
  
  return result.rows[0];
}

/**
 * Hard delete a bot instance (use with caution - for testing/cleanup only)
 * This permanently removes the bot and all related data
 */
export async function hardDeleteBotInstance(botId, userId) {
  // Cascade will handle related records
  const result = await pool.query(
    `DELETE FROM bot_instances WHERE id = $1 AND user_id = $2 RETURNING *`,
    [botId, userId]
  );
  return result.rows[0];
}

/**
 * Get bot instance with all exchange configs
 */
export async function getBotInstanceWithConfigs(botId, userId) {
  const bot = await getBotInstanceById(botId, userId);
  if (!bot) return null;
  
  const configs = await pool.query(
    `SELECT bec.*, uec.exchange, uec.label as credential_label, uec.is_testnet,
            uec.status as credential_status
     FROM bot_exchange_configs bec
     JOIN user_exchange_credentials uec ON bec.credential_id = uec.id
     WHERE bec.bot_instance_id = $1
     ORDER BY bec.environment, bec.created_at DESC`,
    [botId]
  );
  
  return {
    ...bot,
    exchangeConfigs: configs.rows,
  };
}

/**
 * Get bots by allocator role
 */
export async function getBotsByAllocatorRole(userId, allocatorRole) {
  const result = await pool.query(
    `SELECT * FROM bot_instances 
     WHERE user_id = $1 AND allocator_role = $2 AND is_active = true
     ORDER BY created_at DESC`,
    [userId, allocatorRole]
  );
  return result.rows;
}

export default {
  getBotInstancesByUser,
  getBotInstanceById,
  createBotInstance,
  updateBotInstance,
  deleteBotInstance,
  hardDeleteBotInstance,
  getBotInstanceWithConfigs,
  getBotsByAllocatorRole,
  DEFAULT_RISK_CONFIG,
  DEFAULT_EXECUTION_CONFIG,
  ALLOCATOR_ROLES,
};

