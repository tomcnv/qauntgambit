/**
 * Bot Budget Model
 * 
 * Per-bot budget allocations within an exchange account.
 * Optional in TEAM mode, required in PROP mode.
 * Budgets must sum to <= exchange policy limits.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Default budget values (no limits if null)
 */
export const DEFAULT_BUDGET = {
  maxDailyLossPct: null,
  maxDailyLossUsd: null,
  maxMarginUsedPct: null,
  maxExposurePct: null,
  maxOpenPositions: null,
  maxLeverage: null,
  maxOrderRatePerMin: null,
};

/**
 * Create a budget for a bot
 */
export async function create(botInstanceId, exchangeAccountId, budget = {}) {
  const id = randomUUID();
  
  const result = await pool.query(
    `INSERT INTO bot_budgets (
      id, bot_instance_id, exchange_account_id,
      max_daily_loss_pct, max_daily_loss_usd,
      max_margin_used_pct, max_exposure_pct,
      max_open_positions, max_leverage, max_order_rate_per_min
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ON CONFLICT (bot_instance_id, exchange_account_id) DO UPDATE SET
      max_daily_loss_pct = COALESCE(EXCLUDED.max_daily_loss_pct, bot_budgets.max_daily_loss_pct),
      max_daily_loss_usd = COALESCE(EXCLUDED.max_daily_loss_usd, bot_budgets.max_daily_loss_usd),
      max_margin_used_pct = COALESCE(EXCLUDED.max_margin_used_pct, bot_budgets.max_margin_used_pct),
      max_exposure_pct = COALESCE(EXCLUDED.max_exposure_pct, bot_budgets.max_exposure_pct),
      max_open_positions = COALESCE(EXCLUDED.max_open_positions, bot_budgets.max_open_positions),
      max_leverage = COALESCE(EXCLUDED.max_leverage, bot_budgets.max_leverage),
      max_order_rate_per_min = COALESCE(EXCLUDED.max_order_rate_per_min, bot_budgets.max_order_rate_per_min),
      budget_version = bot_budgets.budget_version + 1
    RETURNING *`,
    [
      id, botInstanceId, exchangeAccountId,
      budget.maxDailyLossPct ?? DEFAULT_BUDGET.maxDailyLossPct,
      budget.maxDailyLossUsd ?? DEFAULT_BUDGET.maxDailyLossUsd,
      budget.maxMarginUsedPct ?? DEFAULT_BUDGET.maxMarginUsedPct,
      budget.maxExposurePct ?? DEFAULT_BUDGET.maxExposurePct,
      budget.maxOpenPositions ?? DEFAULT_BUDGET.maxOpenPositions,
      budget.maxLeverage ?? DEFAULT_BUDGET.maxLeverage,
      budget.maxOrderRatePerMin ?? DEFAULT_BUDGET.maxOrderRatePerMin,
    ]
  );
  
  return result.rows[0];
}

/**
 * Get budget by bot and account
 */
export async function getByBot(botInstanceId, exchangeAccountId = null) {
  let query = `SELECT * FROM bot_budgets WHERE bot_instance_id = $1`;
  const params = [botInstanceId];
  
  if (exchangeAccountId) {
    query += ` AND exchange_account_id = $2`;
    params.push(exchangeAccountId);
  }
  
  const result = await pool.query(query, params);
  return exchangeAccountId ? result.rows[0] || null : result.rows;
}

/**
 * Get all budgets for an exchange account
 */
export async function getByExchangeAccount(exchangeAccountId) {
  const result = await pool.query(
    `SELECT bb.*, bi.name as bot_name
     FROM bot_budgets bb
     JOIN bot_instances bi ON bi.id = bb.bot_instance_id
     WHERE bb.exchange_account_id = $1
     ORDER BY bi.name`,
    [exchangeAccountId]
  );
  return result.rows;
}

/**
 * Update budget
 */
export async function update(botInstanceId, exchangeAccountId, updates) {
  const allowedFields = [
    'max_daily_loss_pct', 'max_daily_loss_usd',
    'max_margin_used_pct', 'max_exposure_pct',
    'max_open_positions', 'max_leverage', 'max_order_rate_per_min',
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
  setClause.push(`budget_version = budget_version + 1`);
  
  values.push(botInstanceId, exchangeAccountId);
  
  const result = await pool.query(
    `UPDATE bot_budgets
     SET ${setClause.join(', ')}
     WHERE bot_instance_id = $${paramIndex} AND exchange_account_id = $${paramIndex + 1}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Delete budget
 */
export async function remove(botInstanceId, exchangeAccountId) {
  const result = await pool.query(
    `DELETE FROM bot_budgets 
     WHERE bot_instance_id = $1 AND exchange_account_id = $2
     RETURNING *`,
    [botInstanceId, exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Update runtime tracking (daily loss, margin, positions)
 */
export async function updateRuntime(botInstanceId, exchangeAccountId, {
  dailyLossUsedUsd = null,
  marginUsedUsd = null,
  currentPositions = null,
}) {
  const setClauses = [];
  const values = [];
  let paramIndex = 1;
  
  if (dailyLossUsedUsd !== null) {
    setClauses.push(`daily_loss_used_usd = $${paramIndex}`);
    values.push(dailyLossUsedUsd);
    paramIndex++;
  }
  
  if (marginUsedUsd !== null) {
    setClauses.push(`margin_used_usd = $${paramIndex}`);
    values.push(marginUsedUsd);
    paramIndex++;
  }
  
  if (currentPositions !== null) {
    setClauses.push(`current_positions = $${paramIndex}`);
    values.push(currentPositions);
    paramIndex++;
  }
  
  if (setClauses.length === 0) {
    return getByBot(botInstanceId, exchangeAccountId);
  }
  
  values.push(botInstanceId, exchangeAccountId);
  
  const result = await pool.query(
    `UPDATE bot_budgets
     SET ${setClauses.join(', ')}
     WHERE bot_instance_id = $${paramIndex} AND exchange_account_id = $${paramIndex + 1}
     RETURNING *`,
    values
  );
  
  return result.rows[0];
}

/**
 * Add to daily loss
 */
export async function addDailyLoss(botInstanceId, exchangeAccountId, lossUsd) {
  const result = await pool.query(
    `UPDATE bot_budgets
     SET daily_loss_used_usd = COALESCE(daily_loss_used_usd, 0) + $1
     WHERE bot_instance_id = $2 AND exchange_account_id = $3
     RETURNING *`,
    [lossUsd, botInstanceId, exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Reset daily tracking
 */
export async function resetDaily(botInstanceId, exchangeAccountId) {
  const result = await pool.query(
    `UPDATE bot_budgets
     SET daily_loss_used_usd = 0,
         daily_reset_at = NOW()
     WHERE bot_instance_id = $1 AND exchange_account_id = $2
     RETURNING *`,
    [botInstanceId, exchangeAccountId]
  );
  return result.rows[0];
}

/**
 * Check if budget allows an order
 */
export async function checkBudget(botInstanceId, exchangeAccountId, {
  orderSizeUsd = 0,
  leverage = 1,
  wouldAddPosition = false,
}) {
  const budget = await getByBot(botInstanceId, exchangeAccountId);
  
  if (!budget) {
    // No budget = no limits (allowed in SOLO/TEAM modes)
    return { allowed: true, reason: null };
  }
  
  const errors = [];
  
  // Check daily loss
  if (budget.max_daily_loss_usd !== null) {
    if (budget.daily_loss_used_usd >= budget.max_daily_loss_usd) {
      errors.push({
        code: 'BOT_BUDGET_DAILY_LOSS',
        message: `Daily loss limit reached: $${budget.daily_loss_used_usd} / $${budget.max_daily_loss_usd}`,
      });
    }
  }
  
  // Check margin (rough estimate)
  if (budget.max_margin_used_pct !== null && budget.margin_used_usd !== null) {
    // Would need account balance to calculate percentage properly
    // This is a simplified check
  }
  
  // Check positions
  if (budget.max_open_positions !== null && wouldAddPosition) {
    if (budget.current_positions >= budget.max_open_positions) {
      errors.push({
        code: 'BOT_BUDGET_POSITIONS',
        message: `Position limit reached: ${budget.current_positions} / ${budget.max_open_positions}`,
      });
    }
  }
  
  // Check leverage
  if (budget.max_leverage !== null && leverage > budget.max_leverage) {
    errors.push({
      code: 'BOT_BUDGET_LEVERAGE',
      message: `Leverage ${leverage}x exceeds budget max ${budget.max_leverage}x`,
    });
  }
  
  return {
    allowed: errors.length === 0,
    errors,
    budget,
  };
}

/**
 * Get budget utilization summary for an account
 */
export async function getUtilizationSummary(exchangeAccountId) {
  const result = await pool.query(
    `SELECT 
      bb.bot_instance_id,
      bi.name as bot_name,
      bb.max_daily_loss_usd,
      bb.daily_loss_used_usd,
      CASE 
        WHEN bb.max_daily_loss_usd > 0 
        THEN ROUND((bb.daily_loss_used_usd / bb.max_daily_loss_usd) * 100, 1)
        ELSE 0
      END as daily_loss_pct_used,
      bb.max_open_positions,
      bb.current_positions,
      bb.max_margin_used_pct,
      bb.margin_used_usd
     FROM bot_budgets bb
     JOIN bot_instances bi ON bi.id = bb.bot_instance_id
     WHERE bb.exchange_account_id = $1
     ORDER BY bi.name`,
    [exchangeAccountId]
  );
  return result.rows;
}

export default {
  create,
  getByBot,
  getByExchangeAccount,
  update,
  remove,
  updateRuntime,
  addDailyLoss,
  resetDaily,
  checkBudget,
  getUtilizationSummary,
  DEFAULT_BUDGET,
};







