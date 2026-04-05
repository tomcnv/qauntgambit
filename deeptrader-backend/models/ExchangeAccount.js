/**
 * Exchange Account Model
 * 
 * Exchange accounts represent the risk pool boundary - shared balance/margin
 * across all bots trading on a specific venue connection.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Valid venues
 */
export const VENUES = ['binance', 'okx', 'bybit', 'coinbase', 'kraken'];

/**
 * Venues that support demo trading
 * - Bybit: api-demo.bybit.com (simulated live trading)
 * - OKX: x-simulated-trading header (demo mode)
 * - Binance: NO DEMO - testnet deprecated, use paper trading instead
 */
export const DEMO_SUPPORTED_VENUES = ['bybit', 'okx'];

/**
 * Valid environments
 */
export const ENVIRONMENTS = ['dev', 'paper', 'live'];

/**
 * Valid statuses
 */
export const STATUSES = ['pending', 'verified', 'error', 'disabled'];

/**
 * Create a new exchange account
 */
export async function create(tenantId, {
  venue,
  label,
  environment = 'paper',
  secretId = null,
  isDemo = false,
  metadata = {},
}) {
  const id = randomUUID();
  
  // Validate: Demo mode only supported on Bybit and OKX
  if (isDemo && !DEMO_SUPPORTED_VENUES.includes(venue.toLowerCase())) {
    throw new Error(`Demo trading is not supported for ${venue}. Use paper trading instead.`);
  }
  
  const result = await pool.query(
    `INSERT INTO exchange_accounts (
      id, tenant_id, venue, label, environment, secret_id, is_demo, metadata
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    RETURNING *`,
    [id, tenantId, venue, label, environment, secretId, isDemo, JSON.stringify(metadata)]
  );
  
  return result.rows[0];
}

/**
 * Get exchange account by ID
 */
export async function getById(id) {
  const result = await pool.query(
    `SELECT ea.*, ep.kill_switch_enabled, ep.live_trading_enabled,
            bi.name as active_bot_name, bi.runtime_state as active_bot_state
     FROM exchange_accounts ea
     LEFT JOIN exchange_policies ep ON ep.exchange_account_id = ea.id
     LEFT JOIN bot_instances bi ON bi.id = ea.active_bot_id
     WHERE ea.id = $1`,
    [id]
  );
  return result.rows[0] || null;
}

/**
 * Get all exchange accounts for a tenant
 * Excludes soft-deleted bots from counts and active bot join
 */
export async function getByTenant(tenantId, environment = null) {
  let query = `
    SELECT ea.*, ep.kill_switch_enabled, ep.live_trading_enabled,
           bi.name as active_bot_name, bi.runtime_state as active_bot_state,
           (SELECT COUNT(*) FROM bot_instances WHERE exchange_account_id = ea.id AND deleted_at IS NULL) as bot_count,
           (SELECT COUNT(*) FROM bot_instances WHERE exchange_account_id = ea.id AND runtime_state = 'running' AND deleted_at IS NULL) as running_bot_count
    FROM exchange_accounts ea
    LEFT JOIN exchange_policies ep ON ep.exchange_account_id = ea.id
    LEFT JOIN bot_instances bi ON bi.id = ea.active_bot_id AND bi.deleted_at IS NULL
    WHERE ea.tenant_id = $1`;
  
  const params = [tenantId];
  
  if (environment) {
    query += ` AND ea.environment = $2`;
    params.push(environment);
  }
  
  query += ` ORDER BY ea.venue, ea.label, ea.environment`;
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Get exchange account by tenant, venue, label, environment
 */
export async function getByCombo(tenantId, venue, label, environment) {
  const result = await pool.query(
    `SELECT * FROM exchange_accounts 
     WHERE tenant_id = $1 AND venue = $2 AND label = $3 AND environment = $4`,
    [tenantId, venue, label, environment]
  );
  return result.rows[0] || null;
}

/**
 * Update exchange account
 */
export async function update(id, updates) {
  const allowedFields = [
    'label', 'secret_id', 'is_demo', 'status', 'verification_error',
    'permissions', 'metadata',
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
  
  values.push(id);
  
  const query = `UPDATE exchange_accounts
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex}
     RETURNING *`;
  
  console.log('[ExchangeAccount.update] Query:', query);
  console.log('[ExchangeAccount.update] Values:', values);
  
  const result = await pool.query(query, values);
  
  return result.rows[0];
}

/**
 * Delete exchange account
 */
export async function remove(id) {
  const result = await pool.query(
    `DELETE FROM exchange_accounts WHERE id = $1 RETURNING *`,
    [id]
  );
  return result.rows[0];
}

/**
 * Update verification status
 */
export async function updateVerificationStatus(id, status, error = null, permissions = null) {
  const query = `UPDATE exchange_accounts
     SET status = $1::text,
         verification_error = $2,
         permissions = $3::jsonb,
         last_verified_at = CASE WHEN $1::text = 'verified' THEN NOW() ELSE last_verified_at END
     WHERE id = $4
     RETURNING *`;
  const values = [status, error, permissions ? JSON.stringify(permissions) : null, id];

  console.log('[ExchangeAccount.updateVerificationStatus] Query:', query);
  console.log('[ExchangeAccount.updateVerificationStatus] Values:', values);

  const result = await pool.query(query, values);
  return result.rows[0];
}

/**
 * Update balance
 */
export async function updateBalance(id, {
  balance,
  available = null,
  marginUsed = null,
  unrealizedPnl = null,
  currency = 'USDT',
}) {
  const result = await pool.query(
    `UPDATE exchange_accounts
     SET exchange_balance = $1,
         available_balance = COALESCE($2, available_balance),
         margin_used = COALESCE($3, margin_used),
         unrealized_pnl = COALESCE($4, unrealized_pnl),
         balance_currency = $5,
         balance_updated_at = NOW()
     WHERE id = $6
     RETURNING *`,
    [balance, available, marginUsed, unrealizedPnl, currency, id]
  );
  return result.rows[0];
}

/**
 * Get active bot for account (SOLO mode)
 */
export async function getActiveBot(accountId) {
  const result = await pool.query(
    `SELECT bi.* FROM bot_instances bi
     JOIN exchange_accounts ea ON ea.active_bot_id = bi.id
     WHERE ea.id = $1`,
    [accountId]
  );
  return result.rows[0] || null;
}

/**
 * Set active bot (SOLO mode)
 */
export async function setActiveBot(accountId, botId) {
  const result = await pool.query(
    `UPDATE exchange_accounts
     SET active_bot_id = $1
     WHERE id = $2
     RETURNING *`,
    [botId, accountId]
  );
  return result.rows[0];
}

/**
 * Clear active bot
 */
export async function clearActiveBot(accountId) {
  const result = await pool.query(
    `UPDATE exchange_accounts
     SET active_bot_id = NULL
     WHERE id = $1
     RETURNING *`,
    [accountId]
  );
  return result.rows[0];
}

/**
 * Get all running bots for an account (excludes soft-deleted)
 */
export async function getRunningBots(accountId) {
  const result = await pool.query(
    `SELECT * FROM bot_instances
     WHERE exchange_account_id = $1 
       AND runtime_state = 'running'
       AND deleted_at IS NULL
     ORDER BY started_at DESC`,
    [accountId]
  );
  return result.rows;
}

/**
 * Get all bots for an account (excludes soft-deleted)
 */
export async function getBots(accountId, includeInactive = false) {
  let query = `
    SELECT bi.*, bb.max_daily_loss_pct as budget_daily_loss, 
           bb.max_margin_used_pct as budget_margin
    FROM bot_instances bi
    LEFT JOIN bot_budgets bb ON bb.bot_instance_id = bi.id AND bb.exchange_account_id = bi.exchange_account_id
    WHERE bi.exchange_account_id = $1
      AND bi.deleted_at IS NULL`;
  
  if (!includeInactive) {
    query += ` AND bi.is_active = true`;
  }
  
  query += ` ORDER BY bi.created_at DESC`;
  
  const result = await pool.query(query, [accountId]);
  return result.rows;
}

/**
 * Check if account has any running bots (excludes soft-deleted)
 */
export async function hasRunningBots(accountId) {
  const result = await pool.query(
    `SELECT EXISTS(
      SELECT 1 FROM bot_instances 
      WHERE exchange_account_id = $1 
        AND runtime_state = 'running'
        AND deleted_at IS NULL
    ) as has_running`,
    [accountId]
  );
  return result.rows[0].has_running;
}

/**
 * Get all bots linked to this exchange account (for deletion checks)
 * Excludes soft-deleted bots (deleted_at IS NOT NULL)
 */
export async function getLinkedBots(accountId) {
  const result = await pool.query(
    `SELECT id, name, runtime_state, is_active 
     FROM bot_instances 
     WHERE exchange_account_id = $1
       AND deleted_at IS NULL
     ORDER BY is_active DESC, name ASC`,
    [accountId]
  );
  return result.rows;
}

export default {
  create,
  getById,
  getByTenant,
  getByCombo,
  update,
  remove,
  updateVerificationStatus,
  updateBalance,
  getActiveBot,
  setActiveBot,
  clearActiveBot,
  getRunningBots,
  getBots,
  hasRunningBots,
  getLinkedBots,
  VENUES,
  DEMO_SUPPORTED_VENUES,
  ENVIRONMENTS,
  STATUSES,
};



