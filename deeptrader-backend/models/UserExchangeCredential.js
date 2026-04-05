/**
 * User Exchange Credential Model
 * 
 * Manages per-user exchange API credential metadata
 * Actual secrets stored in secrets provider (AWS/local)
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';
import secretsProvider, { buildSecretId } from '../services/secretsProvider.js';

/**
 * Venues that support demo trading
 * - Bybit: api-demo.bybit.com (simulated live trading)
 * - OKX: x-simulated-trading header (demo mode)
 * - Binance: NO DEMO - testnet deprecated, use paper trading instead
 */
export const DEMO_SUPPORTED_VENUES = ['bybit', 'okx'];

/**
 * Create a new exchange credential record
 */
export async function createCredential(userId, { exchange, label, isDemo = false }) {
  // Validate: Demo mode only supported on Bybit and OKX
  if (isDemo && !DEMO_SUPPORTED_VENUES.includes(exchange.toLowerCase())) {
    throw new Error(`Demo trading is not supported for ${exchange}. Use paper trading instead.`);
  }
  
  const credentialId = randomUUID();
  const secretId = buildSecretId({
    userId,
    exchange,
    credentialId,
  });
  
  const result = await pool.query(
    `INSERT INTO user_exchange_credentials 
     (id, user_id, exchange, label, secret_id, is_demo, status)
     VALUES ($1, $2, $3, $4, $5, $6, 'pending')
     RETURNING *`,
    [credentialId, userId, exchange, label || `${exchange} Account`, secretId, isDemo]
  );
  
  return result.rows[0];
}

/**
 * Default risk configuration
 */
export const DEFAULT_RISK_CONFIG = {
  positionSizePct: 0.10,
  maxPositions: 4,
  maxDailyLossPct: 0.05,
  maxTotalExposurePct: 0.80, // safe default; capped by tenant policy
  maxExposurePerSymbolPct: 0.20,
  maxLeverage: 1,
  leverageMode: 'isolated',
  maxPositionsPerSymbol: 1,
  maxDailyLossPerSymbolPct: 0.025,
  minPositionSizeUsd: 10,
  maxPositionSizeUsd: null,
  maxPositionsPerStrategy: 0,
  maxDrawdownPct: 0.10,
};

/**
 * Default execution configuration
 */
export const DEFAULT_EXECUTION_CONFIG = {
  defaultOrderType: 'market',
  stopLossPct: 0.02,
  takeProfitPct: 0.05,
  trailingStopEnabled: false,
  trailingStopPct: 0.01,
  maxHoldTimeHours: 24,
  minTradeIntervalSec: 1.0,
  executionTimeoutSec: 5.0,
  closePositionTimeoutSec: 15.0,
  enableVolatilityFilter: true,
  volatilityShockCooldownSec: 30.0,
  throttleMode: 'swing',  // Trading throttle mode: 'scalping', 'swing', or 'conservative'
  orderIntentMaxAgeSec: 0,
};

/**
 * Default UI preferences
 */
export const DEFAULT_UI_PREFERENCES = {
  showPnlInHeader: true,
  notifyOnTrade: true,
  notifyOnStopLoss: true,
  notifyOnTakeProfit: true,
  defaultChartTimeframe: '1h',
  compactMode: false,
};

const normalizePercentValue = (value) => {
  if (value === null || value === undefined) return value;
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num > 1 ? num / 100 : num;
};

const formatPercent = (value, digits = 2) => {
  if (value === null || value === undefined) return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return "N/A";
  return `${(num * 100).toFixed(digits)}%`;
};

const normalizeRiskConfig = (config) => ({
  ...config,
  positionSizePct: normalizePercentValue(config.positionSizePct),
  maxDailyLossPct: normalizePercentValue(config.maxDailyLossPct),
  maxTotalExposurePct: normalizePercentValue(config.maxTotalExposurePct),
  maxExposurePerSymbolPct: normalizePercentValue(config.maxExposurePerSymbolPct),
  maxDailyLossPerSymbolPct: normalizePercentValue(config.maxDailyLossPerSymbolPct),
  maxDrawdownPct: normalizePercentValue(config.maxDrawdownPct),
});

const normalizeExecutionConfig = (config) => ({
  ...config,
  stopLossPct: normalizePercentValue(config.stopLossPct),
  takeProfitPct: normalizePercentValue(config.takeProfitPct),
  trailingStopPct: normalizePercentValue(config.trailingStopPct),
});

/**
 * Get all credentials for a user
 */
export async function getCredentialsByUser(userId) {
  const result = await pool.query(
    `SELECT id, user_id, exchange, label, secret_id, status, 
            last_verified_at, verification_error, permissions,
            is_demo, created_at, updated_at,
            risk_config, execution_config, ui_preferences, config_version,
            exchange_balance, balance_updated_at, account_connected,
            trading_capital, balance_currency, connection_error, balance_error
     FROM user_exchange_credentials
     WHERE user_id = $1
     ORDER BY created_at DESC`,
    [userId]
  );
  
  return result.rows;
}

/**
 * Get a specific credential by ID
 */
export async function getCredentialById(credentialId, userId = null) {
  let query = `SELECT * FROM user_exchange_credentials WHERE id = $1`;
  const params = [credentialId];
  
  if (userId) {
    query += ` AND user_id = $2`;
    params.push(userId);
  }
  
  const result = await pool.query(query, params);
  return result.rows[0] || null;
}

/**
 * Get credential by user and exchange
 */
export async function getCredentialByExchange(userId, exchange) {
  const result = await pool.query(
    `SELECT * FROM user_exchange_credentials 
     WHERE user_id = $1 AND exchange = $2 AND status != 'disabled'
     ORDER BY created_at DESC
     LIMIT 1`,
    [userId, exchange]
  );
  
  return result.rows[0] || null;
}

/**
 * Update credential metadata
 */
export async function updateCredential(credentialId, userId, updates) {
  const allowedFields = ['label', 'is_demo', 'status'];
  const setClause = [];
  const values = [];
  let paramIndex = 1;
  
  for (const [key, value] of Object.entries(updates)) {
    const dbKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
    if (allowedFields.includes(dbKey)) {
      setClause.push(`${dbKey} = $${paramIndex}`);
      values.push(value);
      paramIndex++;
    }
  }
  
  if (setClause.length === 0) {
    throw new Error('No valid fields to update');
  }
  
  values.push(credentialId, userId);
  
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex} AND user_id = $${paramIndex + 1}
     RETURNING *`,
    values
  );
  
  return result.rows[0] || null;
}

/**
 * Update verification status (optionally with balance)
 */
export async function updateVerificationStatus(credentialId, status, error = null, permissions = null, balanceData = null) {
  let query;
  let params;
  
  if (balanceData && balanceData.balance !== undefined) {
    // Include balance update
    query = `UPDATE user_exchange_credentials 
     SET status = $1::varchar, 
         verification_error = $2, 
         permissions = COALESCE($3, permissions),
         last_verified_at = CASE WHEN $1::varchar = 'verified'::varchar THEN NOW() ELSE last_verified_at END,
        exchange_balance = $5,
        balance_currency = $6,
        balance_updated_at = NOW(),
        account_connected = $7,
        connection_error = CASE WHEN $7 = false THEN $2 ELSE NULL END,
        balance_error = NULL
     WHERE id = $4
     RETURNING *`;
    params = [
      status, 
      error, 
      permissions ? JSON.stringify(permissions) : null, 
      credentialId,
      balanceData.balance,
      balanceData.currency || 'USDT',
      balanceData.accountConnected !== false,
    ];
  } else {
    // Standard update without balance
    query = `UPDATE user_exchange_credentials 
     SET status = $1::varchar, 
         verification_error = $2, 
         permissions = COALESCE($3, permissions),
         last_verified_at = CASE WHEN $1::varchar = 'verified'::varchar THEN NOW() ELSE last_verified_at END,
         account_connected = CASE WHEN $1::varchar = 'verified'::varchar THEN true ELSE false END
     WHERE id = $4
     RETURNING *`;
    params = [status, error, permissions ? JSON.stringify(permissions) : null, credentialId];
  }
  
  const result = await pool.query(query, params);
  const updated = result.rows[0] || null;
  
  if (updated && balanceData && balanceData.balance !== undefined) {
    await recordBalanceHistory(updated, {
      fetchSource: balanceData.fetchSource || 'verification',
      currency: balanceData.currency || updated.balance_currency || 'USDT',
      exchangeBalance: balanceData.balance,
    });
  }
  
  return updated;
}

/**
 * Update exchange balance for a credential
 */
export async function updateExchangeBalance(credentialId, userId, balance, currency = 'USDT', options = {}) {
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET exchange_balance = $1,
         balance_currency = $2,
         balance_updated_at = NOW(),
         account_connected = true,
         connection_error = NULL,
         balance_error = NULL
     WHERE id = $3 AND user_id = $4
     RETURNING *`,
    [balance, currency, credentialId, userId]
  );
  
  const updated = result.rows[0] || null;
  
  if (updated) {
    await recordBalanceHistory(updated, {
      fetchSource: options.fetchSource || 'manual_refresh',
      availableBalance: options.availableBalance ?? null,
      marginUsed: options.marginUsed ?? null,
      unrealizedPnl: options.unrealizedPnl ?? null,
      currency: currency,
      exchangeBalance: balance,
    });
  }
  
  return updated;
}

/**
 * Update trading capital for a credential
 */
export async function updateTradingCapital(credentialId, userId, tradingCapital) {
  // First verify trading capital doesn't exceed exchange balance
  const credential = await getCredentialById(credentialId, userId);
  if (!credential) {
    throw new Error('Credential not found');
  }
  
  if (credential.exchange_balance !== null && tradingCapital > parseFloat(credential.exchange_balance)) {
    throw new Error(`Trading capital ($${tradingCapital}) cannot exceed exchange balance ($${credential.exchange_balance})`);
  }
  
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET trading_capital = $1
     WHERE id = $2 AND user_id = $3
     RETURNING *`,
    [tradingCapital, credentialId, userId]
  );
  
  return result.rows[0] || null;
}

/**
 * Mark credential as disconnected (failed to connect)
 */
export async function markDisconnected(credentialId, errorMessage) {
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET account_connected = false,
        connection_error = $1,
        balance_error = $1
     WHERE id = $2
     RETURNING *`,
    [errorMessage, credentialId]
  );
  
  return result.rows[0] || null;
}

/**
 * Delete a credential
 */
export async function deleteCredential(credentialId, userId) {
  // First get the credential to find the exchange
  const credential = await getCredentialById(credentialId, userId);
  if (!credential) {
    return false;
  }
  
  // Delete from secrets provider
  try {
    await secretsProvider.deleteExchangeCredentials(credential.secret_id);
  } catch (err) {
    console.warn(`⚠️ Failed to delete secret: ${err.message}`);
  }
  
  // Delete from database
  const result = await pool.query(
    `DELETE FROM user_exchange_credentials WHERE id = $1 AND user_id = $2`,
    [credentialId, userId]
  );
  
  return result.rowCount > 0;
}

/**
 * Get the count of credentials per exchange for a user
 */
export async function getCredentialCounts(userId) {
  const result = await pool.query(
    `SELECT exchange, COUNT(*) as count, 
            SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) as verified_count
     FROM user_exchange_credentials
     WHERE user_id = $1 AND status != 'disabled'
     GROUP BY exchange`,
    [userId]
  );
  
  return result.rows;
}

/**
 * Update risk configuration for a credential
 */
export async function updateRiskConfig(credentialId, userId, riskConfig, changeReason = null) {
  // Get current config for audit
  const current = await getCredentialById(credentialId, userId);
  if (!current) {
    throw new Error('Credential not found');
  }
  
  const oldConfig = current.risk_config || DEFAULT_RISK_CONFIG;
  const newConfig = normalizeRiskConfig({ ...DEFAULT_RISK_CONFIG, ...oldConfig, ...riskConfig });
  
  // Validate leverage against exchange limits
  const limits = await getExchangeLimits(current.exchange);
  if (newConfig.maxLeverage > limits.max_leverage) {
    throw new Error(`Max leverage for ${current.exchange} is ${limits.max_leverage}x`);
  }
  
  // Validate risk percentages
  if (newConfig.positionSizePct < 0.001 || newConfig.positionSizePct > 1.0) {
    throw new Error('Position size must be between 0.1% and 100%');
  }
  if (newConfig.maxDailyLossPct < 0.001 || newConfig.maxDailyLossPct > 1.0) {
    throw new Error('Max daily loss must be between 0.1% and 100%');
  }
  if (newConfig.maxTotalExposurePct < 0.01 || newConfig.maxTotalExposurePct > 1.0) {
    throw new Error('Max total exposure must be between 1% and 100%');
  }
  
  // Update credential
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET risk_config = $1, 
         config_version = config_version + 1,
         config_updated_at = NOW()
     WHERE id = $2 AND user_id = $3
     RETURNING *`,
    [JSON.stringify(newConfig), credentialId, userId]
  );
  
  // Audit the change
  await auditConfigChange(credentialId, userId, 'risk_config', oldConfig, newConfig, changeReason);
  
  return result.rows[0];
}

/**
 * Update execution configuration for a credential
 */
export async function updateExecutionConfig(credentialId, userId, executionConfig, changeReason = null) {
  const current = await getCredentialById(credentialId, userId);
  if (!current) {
    throw new Error('Credential not found');
  }
  
  const oldConfig = current.execution_config || DEFAULT_EXECUTION_CONFIG;
  const newConfig = normalizeExecutionConfig({ ...DEFAULT_EXECUTION_CONFIG, ...oldConfig, ...executionConfig });
  
  // Validate stop loss / take profit
  if (newConfig.stopLossPct < 0.001 || newConfig.stopLossPct > 0.50) {
    throw new Error('Stop loss must be between 0.1% and 50%');
  }
  if (newConfig.takeProfitPct < 0.001 || newConfig.takeProfitPct > 1.0) {
    throw new Error('Take profit must be between 0.1% and 100%');
  }
  
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET execution_config = $1, 
         config_version = config_version + 1,
         config_updated_at = NOW()
     WHERE id = $2 AND user_id = $3
     RETURNING *`,
    [JSON.stringify(newConfig), credentialId, userId]
  );
  
  await auditConfigChange(credentialId, userId, 'execution_config', oldConfig, newConfig, changeReason);
  
  return result.rows[0];
}

/**
 * Update UI preferences for a credential
 */
export async function updateUiPreferences(credentialId, userId, uiPreferences) {
  const current = await getCredentialById(credentialId, userId);
  if (!current) {
    throw new Error('Credential not found');
  }
  
  const oldConfig = current.ui_preferences || DEFAULT_UI_PREFERENCES;
  const newConfig = { ...DEFAULT_UI_PREFERENCES, ...oldConfig, ...uiPreferences };
  
  const result = await pool.query(
    `UPDATE user_exchange_credentials 
     SET ui_preferences = $1, 
         config_version = config_version + 1,
         config_updated_at = NOW()
     WHERE id = $2 AND user_id = $3
     RETURNING *`,
    [JSON.stringify(newConfig), credentialId, userId]
  );
  
  // UI preferences don't need audit
  return result.rows[0];
}

/**
 * Get full bot profile for a credential (all configs merged)
 */
export async function getBotProfile(credentialId, userId) {
  const result = await pool.query(
    `SELECT 
       ec.id as credential_id,
       ec.exchange,
       ec.is_demo,
       ec.status,
       ec.risk_config,
       ec.execution_config,
       ec.ui_preferences,
       ec.config_version,
       ec.exchange_balance,
       ec.trading_capital,
       ec.balance_currency,
       ec.account_connected,
       ec.balance_updated_at,
       tp.token_lists,
       tp.trading_mode,
       tp.account_balance as profile_account_balance,
       tp.global_max_leverage,
       tp.global_leverage_mode
     FROM user_exchange_credentials ec
     LEFT JOIN user_trade_profiles tp ON tp.user_id = ec.user_id
     WHERE ec.id = $1 AND ec.user_id = $2`,
    [credentialId, userId]
  );
  
  if (!result.rows[0]) {
    return null;
  }
  
  const row = result.rows[0];
  const riskConfig = row.risk_config || DEFAULT_RISK_CONFIG;
  const executionConfig = row.execution_config || DEFAULT_EXECUTION_CONFIG;
  
  // Determine the trading capital to use:
  // Single source of truth: credential's trading_capital (user-set, per-credential)
  // No legacy fallback to profile account_balance
  const tradingCapital = row.trading_capital
    ? parseFloat(row.trading_capital)
    : 10000.0;
  
  // Merge profile with credential configs
  return {
    credentialId: row.credential_id,
    exchange: row.exchange,
    isDemo: row.is_demo,
    status: row.status,
    configVersion: row.config_version,
    tradingMode: row.trading_mode || 'paper',
    // Balance info
    exchangeBalance: row.exchange_balance ? parseFloat(row.exchange_balance) : null,
    tradingCapital,
    balanceCurrency: row.balance_currency || 'USDT',
    accountConnected: row.account_connected || false,
    balanceUpdatedAt: row.balance_updated_at,
    // Legacy field for backward compatibility
    accountBalance: tradingCapital,
    tokens: (row.token_lists || {})[row.exchange] || [],
    risk: {
      ...DEFAULT_RISK_CONFIG,
      ...riskConfig,
      // Use global leverage if credential doesn't specify
      maxLeverage: riskConfig.maxLeverage || row.global_max_leverage || 1,
      leverageMode: riskConfig.leverageMode || row.global_leverage_mode || 'isolated',
    },
    execution: {
      ...DEFAULT_EXECUTION_CONFIG,
      ...executionConfig,
    },
    ui: {
      ...DEFAULT_UI_PREFERENCES,
      ...row.ui_preferences,
    },
  };
}

/**
 * Get exchange limits for validation
 */
export async function getExchangeLimits(exchange) {
  const result = await pool.query(
    `SELECT * FROM exchange_limits WHERE exchange = $1`,
    [exchange]
  );
  
  if (result.rows[0]) {
    return result.rows[0];
  }
  
  // Return defaults if not in database
  return {
    exchange,
    max_leverage: 125,
    default_leverage: 1,
    min_position_usd: 5.0,
    max_position_usd: 1000000.0,
    min_stop_loss_pct: 0.001,
    max_daily_trades: 1000,
    supports_isolated_margin: true,
    supports_cross_margin: true,
    supports_trailing_stop: true,
    supports_bracket_orders: true,
  };
}

/**
 * Audit a config change
 */
async function auditConfigChange(credentialId, userId, configType, oldValue, newValue, changeReason = null) {
  // Find which fields changed
  const changedFields = [];
  for (const key of Object.keys(newValue)) {
    if (JSON.stringify(oldValue[key]) !== JSON.stringify(newValue[key])) {
      changedFields.push(key);
    }
  }
  
  if (changedFields.length === 0) {
    return; // No actual changes
  }
  
  await pool.query(
    `INSERT INTO credential_config_audit 
     (credential_id, user_id, config_type, old_value, new_value, changed_fields, change_reason, changed_by)
     VALUES ($1, $2, $3, $4, $5, $6, $7, 'user')`,
    [credentialId, userId, configType, JSON.stringify(oldValue), JSON.stringify(newValue), changedFields, changeReason]
  );
}

/**
 * Get config audit history for a credential
 */
export async function getConfigAuditHistory(credentialId, userId, limit = 50) {
  const result = await pool.query(
    `SELECT * FROM credential_config_audit 
     WHERE credential_id = $1 AND user_id = $2
     ORDER BY created_at DESC
     LIMIT $3`,
    [credentialId, userId, limit]
  );
  
  return result.rows;
}

async function recordBalanceHistory(credential, overrides = {}) {
  try {
    if (!credential) {
      return;
    }
    
    const exchangeBalance = overrides.exchangeBalance ?? credential.exchange_balance;
    if (exchangeBalance === undefined || exchangeBalance === null) {
      return;
    }
    
    const tradingCapital = overrides.tradingCapital ?? credential.trading_capital;
    const availableBalance = overrides.availableBalance ?? null;
    const marginUsed = overrides.marginUsed ?? null;
    const unrealizedPnl = overrides.unrealizedPnl ?? null;
    const currency = overrides.currency || credential.balance_currency || 'USDT';
    const fetchSource = overrides.fetchSource || 'manual_refresh';
    
    await pool.query(
      `INSERT INTO credential_balance_history 
       (credential_id, user_id, exchange_balance, trading_capital, available_balance, margin_used, unrealized_pnl, currency, fetch_source)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
      [
        credential.id,
        credential.user_id,
        exchangeBalance,
        tradingCapital,
        availableBalance,
        marginUsed,
        unrealizedPnl,
        currency,
        fetchSource,
      ]
    );
  } catch (err) {
    console.warn(`⚠️ Failed to record balance history for credential ${credential?.id}: ${err.message}`);
  }
}

export default {
  createCredential,
  getCredentialsByUser,
  getCredentialById,
  getCredentialByExchange,
  updateCredential,
  updateVerificationStatus,
  deleteCredential,
  getCredentialCounts,
  updateRiskConfig,
  updateExecutionConfig,
  updateUiPreferences,
  getBotProfile,
  getExchangeLimits,
  getConfigAuditHistory,
  updateExchangeBalance,
  updateTradingCapital,
  markDisconnected,
  DEFAULT_RISK_CONFIG,
  DEFAULT_EXECUTION_CONFIG,
  DEFAULT_UI_PREFERENCES,
};
