/**
 * Exchange Policy Model
 * 
 * Hard risk caps per exchange account - enforced across all bots.
 * These are the "law" that cannot be exceeded by any bot budget.
 */

import pool from '../config/database.js';

/**
 * Default policy values
 */
export const DEFAULT_POLICY = {
  maxDailyLossPct: 0.10,
  maxDailyLossUsd: null,
  maxMarginUsedPct: 0.80,
  maxGrossExposurePct: 1.00,
  maxNetExposurePct: 0.50,
  maxLeverage: 10.0,
  maxOpenPositions: 10,
  killSwitchEnabled: false,
  circuitBreakerEnabled: true,
  circuitBreakerLossPct: 0.05,
  circuitBreakerCooldownMin: 60,
  liveTradingEnabled: false,
};

/**
 * Get policy by exchange account ID
 */
export async function getByAccount(exchangeAccountId) {
  const result = await pool.query(
    `SELECT * FROM exchange_policies WHERE exchange_account_id = $1`,
    [exchangeAccountId]
  );
  return result.rows[0] || null;
}

/**
 * Create policy (usually auto-created by trigger)
 */
export async function create(exchangeAccountId, policy = {}) {
  const result = await pool.query(
    `INSERT INTO exchange_policies (
      exchange_account_id,
      max_daily_loss_pct, max_daily_loss_usd,
      max_margin_used_pct, max_gross_exposure_pct, max_net_exposure_pct,
      max_leverage, max_open_positions,
      kill_switch_enabled, circuit_breaker_enabled,
      circuit_breaker_loss_pct, circuit_breaker_cooldown_min,
      live_trading_enabled
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    ON CONFLICT (exchange_account_id) DO NOTHING
    RETURNING *`,
    [
      exchangeAccountId,
      policy.maxDailyLossPct ?? DEFAULT_POLICY.maxDailyLossPct,
      policy.maxDailyLossUsd ?? DEFAULT_POLICY.maxDailyLossUsd,
      policy.maxMarginUsedPct ?? DEFAULT_POLICY.maxMarginUsedPct,
      policy.maxGrossExposurePct ?? DEFAULT_POLICY.maxGrossExposurePct,
      policy.maxNetExposurePct ?? DEFAULT_POLICY.maxNetExposurePct,
      policy.maxLeverage ?? DEFAULT_POLICY.maxLeverage,
      policy.maxOpenPositions ?? DEFAULT_POLICY.maxOpenPositions,
      policy.killSwitchEnabled ?? DEFAULT_POLICY.killSwitchEnabled,
      policy.circuitBreakerEnabled ?? DEFAULT_POLICY.circuitBreakerEnabled,
      policy.circuitBreakerLossPct ?? DEFAULT_POLICY.circuitBreakerLossPct,
      policy.circuitBreakerCooldownMin ?? DEFAULT_POLICY.circuitBreakerCooldownMin,
      policy.liveTradingEnabled ?? DEFAULT_POLICY.liveTradingEnabled,
    ]
  );
  
  // If conflict, fetch existing
  if (result.rows.length === 0) {
    return getByAccount(exchangeAccountId);
  }
  
  return result.rows[0];
}

/**
 * Update policy
 */
export async function update(exchangeAccountId, updates) {
  const allowedFields = [
    'max_daily_loss_pct', 'max_daily_loss_usd',
    'max_margin_used_pct', 'max_gross_exposure_pct', 'max_net_exposure_pct',
    'max_leverage', 'max_open_positions',
    'circuit_breaker_enabled', 'circuit_breaker_loss_pct', 'circuit_breaker_cooldown_min',
    'live_trading_enabled',
  ];
  
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
  
  // Increment version
  setClause.push(`policy_version = policy_version + 1`);
  
  values.push(exchangeAccountId);
  
  const result = await pool.query(
    `UPDATE exchange_policies
     SET ${setClause.join(', ')}
     WHERE exchange_account_id = $${paramIndex}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Activate kill switch
 */
export async function activateKillSwitch(exchangeAccountId, userId, reason = null) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET kill_switch_enabled = true,
         kill_switch_triggered_at = NOW(),
         kill_switch_triggered_by = $1,
         kill_switch_reason = $2,
         policy_version = policy_version + 1
     WHERE exchange_account_id = $3
     RETURNING *`,
    [userId, reason, exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Deactivate kill switch
 */
export async function deactivateKillSwitch(exchangeAccountId) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET kill_switch_enabled = false,
         policy_version = policy_version + 1
     WHERE exchange_account_id = $1
     RETURNING *`,
    [exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Trigger circuit breaker
 */
export async function triggerCircuitBreaker(exchangeAccountId) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET circuit_breaker_triggered_at = NOW(),
         kill_switch_enabled = true,
         kill_switch_reason = 'Circuit breaker auto-triggered',
         policy_version = policy_version + 1
     WHERE exchange_account_id = $1
     RETURNING *`,
    [exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Check if circuit breaker is in cooldown
 */
export async function isCircuitBreakerActive(exchangeAccountId) {
  const result = await pool.query(
    `SELECT 
      circuit_breaker_enabled,
      circuit_breaker_triggered_at,
      circuit_breaker_cooldown_min,
      CASE 
        WHEN circuit_breaker_triggered_at IS NOT NULL 
          AND circuit_breaker_triggered_at + (circuit_breaker_cooldown_min || ' minutes')::interval > NOW()
        THEN true
        ELSE false
      END as is_in_cooldown
     FROM exchange_policies 
     WHERE exchange_account_id = $1`,
    [exchangeAccountId]
  );
  
  if (!result.rows[0]) return false;
  return result.rows[0].is_in_cooldown;
}

/**
 * Update daily loss used
 */
export async function updateDailyLoss(exchangeAccountId, lossUsd) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET daily_loss_used_usd = COALESCE(daily_loss_used_usd, 0) + $1
     WHERE exchange_account_id = $2
     RETURNING *`,
    [lossUsd, exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Check if daily loss limit is breached
 */
export async function isDailyLossBreached(exchangeAccountId) {
  const result = await pool.query(
    `SELECT 
      daily_loss_used_usd,
      max_daily_loss_usd,
      max_daily_loss_pct,
      CASE 
        WHEN max_daily_loss_usd IS NOT NULL AND daily_loss_used_usd >= max_daily_loss_usd THEN true
        ELSE false
      END as is_breached
     FROM exchange_policies 
     WHERE exchange_account_id = $1`,
    [exchangeAccountId]
  );
  
  if (!result.rows[0]) return false;
  return result.rows[0].is_breached;
}

/**
 * Reset daily loss tracking
 */
export async function resetDailyLoss(exchangeAccountId) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET daily_loss_used_usd = 0,
         daily_loss_reset_at = NOW()
     WHERE exchange_account_id = $1
     RETURNING *`,
    [exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Enable live trading
 */
export async function enableLiveTrading(exchangeAccountId) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET live_trading_enabled = true,
         policy_version = policy_version + 1
     WHERE exchange_account_id = $1
     RETURNING *`,
    [exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Disable live trading
 */
export async function disableLiveTrading(exchangeAccountId) {
  const result = await pool.query(
    `UPDATE exchange_policies
     SET live_trading_enabled = false,
         policy_version = policy_version + 1
     WHERE exchange_account_id = $1
     RETURNING *`,
    [exchangeAccountId]
  );
  return result.rows[0];
}

export default {
  getByAccount,
  create,
  update,
  activateKillSwitch,
  deactivateKillSwitch,
  triggerCircuitBreaker,
  isCircuitBreakerActive,
  updateDailyLoss,
  isDailyLossBreached,
  resetDailyLoss,
  enableLiveTrading,
  disableLiveTrading,
  DEFAULT_POLICY,
};






