/**
 * Tenant Risk Policy Model
 * 
 * Global risk envelope for an account. These limits cap all bot configurations.
 * Effective risk = min(global_policy, per_bot_config)
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Default tenant risk policy
 */
export const DEFAULT_POLICY = {
  maxDailyLossPct: 0.10,
  maxDailyLossUsd: null,
  maxTotalExposurePct: 1.0,
  maxSinglePositionPct: 0.25,
  maxPerSymbolExposurePct: 0.50,
  maxLeverage: 10.0,
  allowedLeverageLevels: [1, 2, 3, 5, 10],
  maxConcurrentPositions: 10,
  maxConcurrentBots: 1,
  maxSymbols: 20,
  totalCapitalLimitUsd: null,
  minReservePct: 0.10,
  liveTradingEnabled: false,
  allowedEnvironments: ['dev', 'paper'],
  allowedExchanges: ['binance', 'okx', 'bybit'],
  tradingHoursEnabled: false,
  circuitBreakerEnabled: true,
  circuitBreakerLossPct: 0.05,
  circuitBreakerCooldownMinutes: 60,
};

const formatPercent = (value, digits = 2) => {
  if (value === null || value === undefined) return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return "N/A";
  return `${(num * 100).toFixed(digits)}%`;
};

/**
 * Get risk policy for a user
 */
export async function getPolicyByUser(userId) {
  const result = await pool.query(
    `SELECT * FROM tenant_risk_policies WHERE user_id = $1`,
    [userId]
  );
  
  if (result.rows.length === 0) {
    // Create default policy if none exists
    return createDefaultPolicy(userId);
  }
  
  return result.rows[0];
}

/**
 * Create default policy for a user
 */
export async function createDefaultPolicy(userId) {
  const policyId = randomUUID();
  
  const result = await pool.query(
    `INSERT INTO tenant_risk_policies (
      id, user_id, max_daily_loss_pct, max_total_exposure_pct, max_single_position_pct,
      max_per_symbol_exposure_pct, max_leverage, allowed_leverage_levels,
      max_concurrent_positions, max_concurrent_bots, max_symbols, min_reserve_pct,
      live_trading_enabled, allowed_environments, allowed_exchanges,
      circuit_breaker_enabled, circuit_breaker_loss_pct, circuit_breaker_cooldown_minutes
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
    ON CONFLICT (user_id) DO NOTHING
    RETURNING *`,
    [
      policyId, userId,
      DEFAULT_POLICY.maxDailyLossPct,
      DEFAULT_POLICY.maxTotalExposurePct,
      DEFAULT_POLICY.maxSinglePositionPct,
      DEFAULT_POLICY.maxPerSymbolExposurePct,
      DEFAULT_POLICY.maxLeverage,
      DEFAULT_POLICY.allowedLeverageLevels,
      DEFAULT_POLICY.maxConcurrentPositions,
      DEFAULT_POLICY.maxConcurrentBots,
      DEFAULT_POLICY.maxSymbols,
      DEFAULT_POLICY.minReservePct,
      DEFAULT_POLICY.liveTradingEnabled,
      DEFAULT_POLICY.allowedEnvironments,
      DEFAULT_POLICY.allowedExchanges,
      DEFAULT_POLICY.circuitBreakerEnabled,
      DEFAULT_POLICY.circuitBreakerLossPct,
      DEFAULT_POLICY.circuitBreakerCooldownMinutes,
    ]
  );
  
  // If conflict, fetch the existing policy
  if (result.rows.length === 0) {
    return getPolicyByUser(userId);
  }
  
  return result.rows[0];
}

/**
 * Update risk policy
 */
export async function updatePolicy(userId, updates) {
  const allowedFields = [
    'max_daily_loss_pct', 'max_daily_loss_usd', 'max_total_exposure_pct',
    'max_single_position_pct', 'max_per_symbol_exposure_pct', 'max_leverage',
    'allowed_leverage_levels', 'max_concurrent_positions', 'max_concurrent_bots',
    'max_symbols', 'total_capital_limit_usd', 'min_reserve_pct',
    'live_trading_enabled', 'allowed_environments', 'allowed_exchanges',
    'trading_hours_enabled', 'trading_start_time', 'trading_end_time',
    'trading_days', 'timezone', 'circuit_breaker_enabled', 'circuit_breaker_loss_pct',
    'circuit_breaker_cooldown_minutes', 'notes', 'metadata',
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
  
  // Increment policy version
  setClause.push(`policy_version = policy_version + 1`);
  
  values.push(userId);
  
  const result = await pool.query(
    `UPDATE tenant_risk_policies
     SET ${setClause.join(', ')}
     WHERE user_id = $${paramIndex}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Enable live trading for a user
 */
export async function enableLiveTrading(userId) {
  const result = await pool.query(
    `UPDATE tenant_risk_policies
     SET live_trading_enabled = true, 
         allowed_environments = array_append(
           CASE WHEN 'live' = ANY(allowed_environments) THEN allowed_environments
           ELSE allowed_environments END,
           'live'
         )
     WHERE user_id = $1
     RETURNING *`,
    [userId]
  );
  return result.rows[0];
}

/**
 * Disable live trading for a user
 */
export async function disableLiveTrading(userId) {
  const result = await pool.query(
    `UPDATE tenant_risk_policies
     SET live_trading_enabled = false,
         allowed_environments = array_remove(allowed_environments, 'live')
     WHERE user_id = $1
     RETURNING *`,
    [userId]
  );
  return result.rows[0];
}

/**
 * Check if an action is allowed by the policy
 */
export async function validateAgainstPolicy(userId, action) {
  const policy = await getPolicyByUser(userId);
  const errors = [];
  
  // Validate environment
  if (action.environment && !policy.allowed_environments.includes(action.environment)) {
    errors.push(`Environment '${action.environment}' is not allowed. Allowed: ${policy.allowed_environments.join(', ')}`);
  }
  
  // Validate live trading
  if (action.environment === 'live' && !policy.live_trading_enabled) {
    errors.push('Live trading is not enabled for this account');
  }
  
  // Validate exchange
  if (action.exchange && !policy.allowed_exchanges.includes(action.exchange)) {
    errors.push(`Exchange '${action.exchange}' is not allowed. Allowed: ${policy.allowed_exchanges.join(', ')}`);
  }
  
  // Validate leverage
  if (action.leverage && action.leverage > policy.max_leverage) {
    errors.push(`Leverage ${action.leverage}x exceeds maximum ${policy.max_leverage}x`);
  }
  
  // Validate position size
  if (action.positionSizePct && action.positionSizePct > policy.max_single_position_pct) {
    errors.push(`Position size ${formatPercent(action.positionSizePct)} exceeds maximum ${formatPercent(policy.max_single_position_pct)}`);
  }
  
  return {
    valid: errors.length === 0,
    errors,
    policy,
  };
}

/**
 * Get effective risk limits (policy caps applied to requested values)
 */
export function getEffectiveLimits(policy, requested) {
  return {
    maxDailyLossPct: Math.min(requested.maxDailyLossPct ?? 1.0, policy.max_daily_loss_pct),
    maxTotalExposurePct: Math.min(requested.maxTotalExposurePct ?? 1.0, policy.max_total_exposure_pct),
    maxLeverage: Math.min(requested.maxLeverage ?? 100, policy.max_leverage),
    maxPositionSizePct: Math.min(requested.positionSizePct ?? 1.0, policy.max_single_position_pct),
    maxConcurrentPositions: Math.min(requested.maxPositions ?? 100, policy.max_concurrent_positions),
    // Add capped flag if any limits were reduced
    cappedByPolicy: (
      (requested.maxDailyLossPct && requested.maxDailyLossPct > policy.max_daily_loss_pct) ||
      (requested.maxLeverage && requested.maxLeverage > policy.max_leverage) ||
      (requested.positionSizePct && requested.positionSizePct > policy.max_single_position_pct)
    ),
  };
}

export default {
  getPolicyByUser,
  createDefaultPolicy,
  updatePolicy,
  enableLiveTrading,
  disableLiveTrading,
  validateAgainstPolicy,
  getEffectiveLimits,
  DEFAULT_POLICY,
};


