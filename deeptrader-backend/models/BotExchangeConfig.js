/**
 * Bot Exchange Config Model
 * 
 * Runtime binding of bot instance + exchange credential + environment.
 * This is the primary runtime unit that the trading engine reads.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Valid environments
 */
export const ENVIRONMENTS = ['dev', 'paper', 'live'];

/**
 * Valid lifecycle states
 */
export const STATES = ['created', 'ready', 'running', 'paused', 'error', 'decommissioned'];

/**
 * State transitions allowed
 */
export const STATE_TRANSITIONS = {
  created: ['ready', 'decommissioned'],
  ready: ['running', 'decommissioned'],
  running: ['paused', 'error', 'decommissioned'],
  paused: ['running', 'decommissioned'],
  error: ['ready', 'decommissioned'],
  decommissioned: [], // Terminal state
};

/**
 * Get all exchange configs for a bot instance
 * Supports both new (exchange_accounts) and legacy (user_exchange_credentials) systems
 * Excludes deleted configs by default
 */
export async function getConfigsByBotInstance(botInstanceId, includeDeleted = false) {
  const deletedFilter = includeDeleted ? '' : 'AND bec.deleted_at IS NULL';
  
  const result = await pool.query(
    `SELECT 
      bec.*,
      -- New system: exchange_accounts
      ea.venue as ea_exchange,
      ea.label as ea_label,
      ea.is_demo as ea_is_testnet,
      ea.status as ea_status,
      ea.available_balance as ea_balance,
      -- Legacy system: user_exchange_credentials
      uec.exchange as uec_exchange,
      uec.label as uec_label,
      uec.is_demo as uec_is_testnet,
      uec.status as uec_status,
      uec.exchange_balance as uec_balance,
      -- Coalesced values (prefer new system)
      COALESCE(ea.venue, uec.exchange, bec.exchange) as exchange,
      COALESCE(ea.label, uec.label) as credential_label,
      COALESCE(ea.is_demo, uec.is_demo, false) as is_testnet,
      COALESCE(ea.status, uec.status) as credential_status,
      COALESCE(ea.available_balance, uec.exchange_balance) as exchange_balance
     FROM bot_exchange_configs bec
     LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id
     LEFT JOIN user_exchange_credentials uec ON bec.credential_id = uec.id
     WHERE bec.bot_instance_id = $1 ${deletedFilter}
     ORDER BY bec.environment, bec.created_at DESC`,
    [botInstanceId]
  );
  return result.rows;
}

/**
 * Get a specific config by ID
 * Supports both new (exchange_accounts) and legacy (user_exchange_credentials) systems
 */
export async function getConfigById(configId) {
  const result = await pool.query(
    `SELECT 
      bec.*,
      bi.name as bot_name, 
      bi.user_id,
      -- Coalesced values (prefer new system)
      COALESCE(ea.venue, uec.exchange, bec.exchange) as exchange,
      COALESCE(ea.label, uec.label) as credential_label,
      COALESCE(ea.is_demo, uec.is_demo, false) as is_testnet,
      COALESCE(ea.status, uec.status) as credential_status,
      COALESCE(ea.available_balance, uec.exchange_balance) as exchange_balance
     FROM bot_exchange_configs bec
     LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id
     LEFT JOIN user_exchange_credentials uec ON bec.credential_id = uec.id
     JOIN bot_instances bi ON bec.bot_instance_id = bi.id
     WHERE bec.id = $1`,
    [configId]
  );
  return result.rows[0] || null;
}

/**
 * Get config by bot instance + account/credential + environment (unique combo)
 * The accountOrCredentialId can be either an exchange_account_id or a credential_id
 */
export async function getConfigByCombo(botInstanceId, accountOrCredentialId, environment) {
  const result = await pool.query(
    `SELECT 
      bec.*,
      COALESCE(ea.venue, uec.exchange, bec.exchange) as exchange,
      COALESCE(ea.label, uec.label) as credential_label,
      COALESCE(ea.is_demo, uec.is_demo, false) as is_testnet
     FROM bot_exchange_configs bec
     LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id
     LEFT JOIN user_exchange_credentials uec ON bec.credential_id = uec.id
     WHERE bec.bot_instance_id = $1 
       AND (bec.exchange_account_id = $2 OR bec.credential_id = $2) 
       AND bec.environment = $3`,
    [botInstanceId, accountOrCredentialId, environment]
  );
  return result.rows[0] || null;
}

/**
 * Get the active config for a user
 * Supports both new (exchange_accounts) and legacy (user_exchange_credentials) systems
 */
export async function getActiveConfigForUser(userId) {
  const result = await pool.query(
    `SELECT 
      bec.*,
      bi.name as bot_name, 
      bi.default_risk_config as bot_default_risk,
      bi.default_execution_config as bot_default_execution,
      -- Coalesced values (prefer new system)
      COALESCE(ea.venue, uec.exchange, bec.exchange) as exchange,
      COALESCE(ea.label, uec.label) as credential_label,
      COALESCE(ea.is_demo, uec.is_demo, false) as is_testnet,
      COALESCE(ea.status, uec.status) as credential_status,
      COALESCE(ea.available_balance, uec.exchange_balance) as exchange_balance
     FROM bot_exchange_configs bec
     LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id
     LEFT JOIN user_exchange_credentials uec ON bec.credential_id = uec.id
     JOIN bot_instances bi ON bec.bot_instance_id = bi.id
     WHERE bi.user_id = $1 AND bec.is_active = true
     LIMIT 1`,
    [userId]
  );
  return result.rows[0] || null;
}

/**
 * Get all configs for a user (across all bots)
 */
export async function getConfigsByUser(userId, environment = null) {
  let query = `
    SELECT bec.*, uec.exchange, uec.label as credential_label, uec.is_testnet,
           uec.status as credential_status, bi.name as bot_name
    FROM bot_exchange_configs bec
    JOIN user_exchange_credentials uec ON bec.credential_id = uec.id
    JOIN bot_instances bi ON bec.bot_instance_id = bi.id
    WHERE bi.user_id = $1`;
  
  const params = [userId];
  
  if (environment) {
    query += ` AND bec.environment = $2`;
    params.push(environment);
  }
  
  query += ` ORDER BY bec.is_active DESC, bec.environment, bec.updated_at DESC`;
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Create a new bot exchange config
 * 
 * Supports both new (exchangeAccountId) and legacy (credentialId) systems:
 * - exchangeAccountId: References the new exchange_accounts table
 * - credentialId: Legacy reference to user_exchange_credentials (deprecated)
 * - exchange: Denormalized exchange name for quick access
 */
export async function createConfig({
  botInstanceId,
  credentialId = null,       // Legacy - will be phased out
  exchangeAccountId = null,  // New - preferred
  exchange = null,           // Denormalized exchange name (e.g., 'binance')
  environment = 'paper',
  tradingCapitalUsd = null,
  enabledSymbols = [],
  riskConfig = {},
  executionConfig = {},
  profileOverrides = {},
  notes = null,
  metadata = {},
}) {
  const configId = randomUUID();
  
  // Require exactly one linkage path while legacy credential IDs still exist.
  if (!exchangeAccountId && !credentialId) {
    throw new Error('Either exchangeAccountId or credentialId is required');
  }
  if (exchangeAccountId && credentialId) {
    throw new Error('Provide exchangeAccountId or credentialId, not both');
  }
  
  const result = await pool.query(
    `INSERT INTO bot_exchange_configs (
      id, bot_instance_id, credential_id, exchange_account_id, exchange, environment, 
      trading_capital_usd, enabled_symbols, risk_config, execution_config, 
      profile_overrides, notes, metadata, state
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'created')
    RETURNING *`,
    [
      configId, 
      botInstanceId, 
      credentialId,           // May be null for new system
      exchangeAccountId,      // May be null for legacy system
      exchange,               // Denormalized
      environment, 
      tradingCapitalUsd,
      JSON.stringify(enabledSymbols),
      JSON.stringify(riskConfig),
      JSON.stringify(executionConfig),
      JSON.stringify(profileOverrides),
      notes,
      JSON.stringify(metadata),
    ]
  );
  
  return result.rows[0];
}

/**
 * Update a bot exchange config
 */
export async function updateConfig(configId, updates) {
  const allowedFields = [
    'trading_capital_usd', 'enabled_symbols', 'risk_config', 'execution_config',
    'profile_overrides', 'notes', 'metadata',
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
  
  values.push(configId);
  
  const result = await pool.query(
    `UPDATE bot_exchange_configs
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Transition config state
 */
export async function transitionState(configId, newState, errorMessage = null) {
  // Get current state
  const current = await getConfigById(configId);
  if (!current) {
    throw new Error('Config not found');
  }
  
  const currentState = current.state;
  const allowedTransitions = STATE_TRANSITIONS[currentState] || [];
  
  if (!allowedTransitions.includes(newState)) {
    throw new Error(`Invalid state transition: ${currentState} -> ${newState}`);
  }
  
  const result = await pool.query(
    `UPDATE bot_exchange_configs
     SET state = $1, last_state_change = NOW(), last_error = $2
     WHERE id = $3
     RETURNING *`,
    [newState, errorMessage, configId]
  );
  
  return result.rows[0];
}

/**
 * Activate a config (deactivates all others for the user)
 */
export async function activateConfig(configId, userId) {
  // Verify the config belongs to the user and is in a valid state
  const config = await getConfigById(configId);
  if (!config) {
    throw new Error('Config not found');
  }
  if (config.user_id !== userId) {
    throw new Error('Config does not belong to user');
  }
  if (config.state === 'decommissioned') {
    throw new Error('Cannot activate a decommissioned config');
  }
  
  // The trigger will handle deactivating other configs
  const result = await pool.query(
    `UPDATE bot_exchange_configs
     SET is_active = true, activated_at = NOW()
     WHERE id = $1
     RETURNING *`,
    [configId]
  );
  
  // Update user_trade_profiles to keep existing dashboard endpoints bot-scoped (phase 1):
  // - active_bot_exchange_config_id: pinned bot runtime config
  // - active_credential_id / active_exchange: drives /dashboard/* data sources
  // - trading_mode: align paper/live with the pinned config
  const nextTradingMode = ['paper', 'live'].includes(config.environment) ? config.environment : 'paper';
  await pool.query(
    `INSERT INTO user_trade_profiles (
        user_id,
        active_bot_exchange_config_id,
        active_credential_id,
        active_exchange,
        trading_mode
     )
     VALUES ($1, $2, $3, $4, $5)
     ON CONFLICT (user_id) DO UPDATE SET
       active_bot_exchange_config_id = EXCLUDED.active_bot_exchange_config_id,
       active_credential_id = EXCLUDED.active_credential_id,
       active_exchange = EXCLUDED.active_exchange,
       trading_mode = EXCLUDED.trading_mode`,
    [userId, configId, config.credential_id, config.exchange, nextTradingMode]
  );
  
  return result.rows[0];
}

/**
 * Deactivate a config
 */
export async function deactivateConfig(configId, userId) {
  const result = await pool.query(
    `UPDATE bot_exchange_configs bec
     SET is_active = false
     FROM bot_instances bi
     WHERE bec.id = $1 AND bec.bot_instance_id = bi.id AND bi.user_id = $2
     RETURNING bec.*`,
    [configId, userId]
  );
  
  // Clear from user_trade_profiles if this was the active config
  await pool.query(
    `UPDATE user_trade_profiles
     SET active_bot_exchange_config_id = NULL
     WHERE user_id = $1 AND active_bot_exchange_config_id = $2`,
    [userId, configId]
  );
  
  return result.rows[0];
}

/**
 * Delete a config (soft delete by decommissioning)
 */
export async function deleteConfig(configId, userId) {
  return transitionState(configId, 'decommissioned');
}

/**
 * Update runtime metrics (heartbeat, decisions, trades)
 */
export async function updateMetrics(configId, metrics) {
  const { decisionsCount, tradesCount } = metrics;
  
  const result = await pool.query(
    `UPDATE bot_exchange_configs
     SET last_heartbeat_at = NOW(),
         decisions_count = COALESCE($2, decisions_count),
         trades_count = COALESCE($3, trades_count)
     WHERE id = $1
     RETURNING *`,
    [configId, decisionsCount, tradesCount]
  );
  
  return result.rows[0];
}

/**
 * Get config versions (history)
 */
export async function getConfigVersions(configId, limit = 20) {
  const result = await pool.query(
    `SELECT * FROM bot_exchange_config_versions
     WHERE bot_exchange_config_id = $1
     ORDER BY version_number DESC
     LIMIT $2`,
    [configId, limit]
  );
  return result.rows;
}

/**
 * Get a specific version
 */
export async function getConfigVersion(configId, versionNumber) {
  const result = await pool.query(
    `SELECT * FROM bot_exchange_config_versions
     WHERE bot_exchange_config_id = $1 AND version_number = $2`,
    [configId, versionNumber]
  );
  return result.rows[0] || null;
}

/**
 * Rollback config to a previous version
 * Creates a NEW version with the old config values (versions are immutable)
 * Returns the newly created config state
 */
export async function rollbackToVersion(configId, targetVersionNumber, userId = null) {
  // Get the target version snapshot
  const targetVersion = await getConfigVersion(configId, targetVersionNumber);
  if (!targetVersion) {
    throw new Error(`Version ${targetVersionNumber} not found for config ${configId}`);
  }

  // Get current config to verify it exists
  const currentConfig = await getConfigById(configId);
  if (!currentConfig) {
    throw new Error(`Config ${configId} not found`);
  }

  // Update the current config with values from the target version
  // This will trigger the version creation via database trigger
  const result = await pool.query(
    `UPDATE bot_exchange_configs
     SET 
       trading_capital_usd = $1,
       enabled_symbols = $2,
       risk_config = $3,
       execution_config = $4,
       profile_overrides = $5,
       notes = CONCAT(notes, E'\n[Rollback to v', $6::text, ' by user ', COALESCE($7::text, 'system'), ' at ', NOW()::text, ']'),
       updated_at = NOW()
     WHERE id = $8
     RETURNING *`,
    [
      targetVersion.trading_capital_usd,
      targetVersion.enabled_symbols,
      targetVersion.risk_config,
      targetVersion.execution_config,
      targetVersion.profile_overrides,
      targetVersionNumber,
      userId,
      configId,
    ]
  );

  // Create audit log entry
  try {
    await pool.query(
      `SELECT create_audit_log_entry($1, 'bot_exchange_config', $2, 'rollback', $3, $4, $5, $6)`,
      [
        userId,
        configId,
        currentConfig.environment,
        JSON.stringify({ version: currentConfig.config_version }),
        JSON.stringify({ version: result.rows[0].config_version, rollback_to: targetVersionNumber }),
        `Rolled back from v${currentConfig.config_version} to v${targetVersionNumber}`,
      ]
    );
  } catch (auditErr) {
    console.warn('Failed to create audit log for rollback:', auditErr.message);
  }

  return result.rows[0];
}

/**
 * Compare two versions (for diff display)
 */
export async function compareVersions(configId, versionA, versionB) {
  const [a, b] = await Promise.all([
    getConfigVersion(configId, versionA),
    getConfigVersion(configId, versionB),
  ]);

  if (!a || !b) {
    throw new Error('One or both versions not found');
  }

  const diff = {
    versionA: a.version_number,
    versionB: b.version_number,
    changes: [],
  };

  // Compare trading capital
  if (a.trading_capital_usd !== b.trading_capital_usd) {
    diff.changes.push({
      field: 'trading_capital_usd',
      label: 'Trading Capital',
      from: a.trading_capital_usd,
      to: b.trading_capital_usd,
    });
  }

  // Compare enabled symbols
  const symbolsA = JSON.stringify(a.enabled_symbols || []);
  const symbolsB = JSON.stringify(b.enabled_symbols || []);
  if (symbolsA !== symbolsB) {
    diff.changes.push({
      field: 'enabled_symbols',
      label: 'Enabled Symbols',
      from: a.enabled_symbols,
      to: b.enabled_symbols,
    });
  }

  // Compare risk config
  const riskA = JSON.stringify(a.risk_config || {});
  const riskB = JSON.stringify(b.risk_config || {});
  if (riskA !== riskB) {
    diff.changes.push({
      field: 'risk_config',
      label: 'Risk Configuration',
      from: a.risk_config,
      to: b.risk_config,
    });
  }

  // Compare execution config
  const execA = JSON.stringify(a.execution_config || {});
  const execB = JSON.stringify(b.execution_config || {});
  if (execA !== execB) {
    diff.changes.push({
      field: 'execution_config',
      label: 'Execution Configuration',
      from: a.execution_config,
      to: b.execution_config,
    });
  }

  return diff;
}

/**
 * Get performance metrics by version
 * Aggregates trades/orders for each version of a config
 */
export async function getVersionPerformance(configId, limit = 10) {
  // Get versions
  const versions = await getConfigVersions(configId, limit);

  // Get performance for each version from orders/trades
  const performanceData = await pool.query(
    `WITH version_trades AS (
      SELECT 
        o.profile_version as version_number,
        COUNT(*) as trade_count,
        COUNT(CASE WHEN o.status = 'filled' THEN 1 END) as filled_count,
        COUNT(CASE WHEN o.status = 'cancelled' THEN 1 END) as cancelled_count,
        SUM(CASE WHEN o.status = 'filled' THEN o.filled_quantity * o.avg_fill_price ELSE 0 END) as total_volume,
        MIN(o.created_at) as first_trade,
        MAX(o.filled_at) as last_trade
      FROM orders o
      WHERE o.profile_id = (
        SELECT bot_instance_id::text FROM bot_exchange_configs WHERE id = $1
      )
      AND o.profile_version IS NOT NULL
      GROUP BY o.profile_version
    )
    SELECT * FROM version_trades
    ORDER BY version_number DESC`,
    [configId]
  );

  // Merge version info with performance data
  const performanceMap = new Map();
  for (const row of performanceData.rows) {
    performanceMap.set(row.version_number, row);
  }

  return versions.map((v) => ({
    ...v,
    performance: performanceMap.get(v.version_number) || {
      trade_count: 0,
      filled_count: 0,
      cancelled_count: 0,
      total_volume: 0,
      first_trade: null,
      last_trade: null,
    },
  }));
}

export default {
  getConfigsByBotInstance,
  getConfigById,
  getConfigByCombo,
  getActiveConfigForUser,
  getConfigsByUser,
  createConfig,
  updateConfig,
  transitionState,
  activateConfig,
  deactivateConfig,
  deleteConfig,
  updateMetrics,
  getConfigVersions,
  getConfigVersion,
  rollbackToVersion,
  compareVersions,
  getVersionPerformance,
  ENVIRONMENTS,
  STATES,
  STATE_TRANSITIONS,
};


