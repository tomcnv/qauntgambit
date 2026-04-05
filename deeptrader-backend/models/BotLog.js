/**
 * Bot Log Model
 * 
 * Event and error logging for bot instances.
 * Allows users to see what's happening with their bots.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Log levels
 */
export const LOG_LEVELS = ['debug', 'info', 'warn', 'error', 'fatal'];

/**
 * Log categories
 */
export const LOG_CATEGORIES = ['lifecycle', 'trade', 'signal', 'risk', 'connection', 'config', 'system'];

/**
 * Create a new log entry
 */
export async function createLog({
  botInstanceId,
  botExchangeConfigId = null,
  userId,
  level = 'info',
  category = 'system',
  message,
  details = {},
  errorCode = null,
  errorType = null,
  stackTrace = null,
  symbol = null,
  orderId = null,
  positionId = null,
  source = null,
}) {
  const logId = randomUUID();
  
  const result = await pool.query(
    `INSERT INTO bot_logs (
      id, bot_instance_id, bot_exchange_config_id, user_id,
      level, category, message, details,
      error_code, error_type, stack_trace,
      symbol, order_id, position_id, source
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
    RETURNING *`,
    [
      logId, botInstanceId, botExchangeConfigId, userId,
      level, category, message, JSON.stringify(details),
      errorCode, errorType, stackTrace,
      symbol, orderId, positionId, source,
    ]
  );
  
  // If this is an error/fatal log, update the bot_exchange_config
  if ((level === 'error' || level === 'fatal') && botExchangeConfigId) {
    await pool.query(
      `UPDATE bot_exchange_configs 
       SET last_error = $1, 
           last_error_at = NOW(), 
           error_count = COALESCE(error_count, 0) + 1,
           state = CASE WHEN state != 'decommissioned' THEN 'error'::bot_config_state ELSE state END
       WHERE id = $2`,
      [message, botExchangeConfigId]
    );
  }
  
  return result.rows[0];
}

/**
 * Get logs for a bot instance with pagination
 */
export async function getLogsByBotInstance(botInstanceId, {
  level = null,
  category = null,
  limit = 50,
  offset = 0,
  since = null,
  until = null,
} = {}) {
  let query = `
    SELECT bl.*, bec.environment
    FROM bot_logs bl
    LEFT JOIN bot_exchange_configs bec ON bl.bot_exchange_config_id = bec.id
    WHERE bl.bot_instance_id = $1
  `;
  const params = [botInstanceId];
  let paramIndex = 2;
  
  if (level) {
    if (Array.isArray(level)) {
      query += ` AND bl.level = ANY($${paramIndex})`;
      params.push(level);
    } else {
      query += ` AND bl.level = $${paramIndex}`;
      params.push(level);
    }
    paramIndex++;
  }
  
  if (category) {
    query += ` AND bl.category = $${paramIndex}`;
    params.push(category);
    paramIndex++;
  }
  
  if (since) {
    query += ` AND bl.created_at >= $${paramIndex}`;
    params.push(since);
    paramIndex++;
  }
  
  if (until) {
    query += ` AND bl.created_at <= $${paramIndex}`;
    params.push(until);
    paramIndex++;
  }
  
  query += ` ORDER BY bl.created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
  params.push(limit, offset);
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Get recent errors for a bot instance
 */
export async function getRecentErrors(botInstanceId, limit = 10) {
  const result = await pool.query(
    `SELECT * FROM bot_logs 
     WHERE bot_instance_id = $1 AND level IN ('error', 'fatal')
     ORDER BY created_at DESC
     LIMIT $2`,
    [botInstanceId, limit]
  );
  return result.rows;
}

/**
 * Get error count for a bot in the last N hours
 */
export async function getErrorCount(botInstanceId, hours = 24) {
  const result = await pool.query(
    `SELECT COUNT(*) FROM bot_logs 
     WHERE bot_instance_id = $1 
       AND level IN ('error', 'fatal')
       AND created_at >= NOW() - ($2 || ' hours')::interval`,
    [botInstanceId, hours]
  );
  return parseInt(result.rows[0].count);
}

/**
 * Get logs for a user with pagination (across all bots)
 */
export async function getLogsByUser(userId, {
  level = null,
  category = null,
  limit = 50,
  offset = 0,
} = {}) {
  let query = `
    SELECT bl.*, bi.name as bot_name, bec.environment
    FROM bot_logs bl
    JOIN bot_instances bi ON bl.bot_instance_id = bi.id
    LEFT JOIN bot_exchange_configs bec ON bl.bot_exchange_config_id = bec.id
    WHERE bl.user_id = $1
  `;
  const params = [userId];
  let paramIndex = 2;
  
  if (level) {
    if (Array.isArray(level)) {
      query += ` AND bl.level = ANY($${paramIndex})`;
      params.push(level);
    } else {
      query += ` AND bl.level = $${paramIndex}`;
      params.push(level);
    }
    paramIndex++;
  }
  
  if (category) {
    query += ` AND bl.category = $${paramIndex}`;
    params.push(category);
    paramIndex++;
  }
  
  query += ` ORDER BY bl.created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
  params.push(limit, offset);
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Get log statistics for a bot
 */
export async function getLogStats(botInstanceId, hours = 24) {
  const result = await pool.query(
    `SELECT 
       level,
       COUNT(*) as count
     FROM bot_logs 
     WHERE bot_instance_id = $1 
       AND created_at >= NOW() - ($2 || ' hours')::interval
     GROUP BY level`,
    [botInstanceId, hours]
  );
  
  const stats = {
    debug: 0,
    info: 0,
    warn: 0,
    error: 0,
    fatal: 0,
    total: 0,
  };
  
  for (const row of result.rows) {
    stats[row.level] = parseInt(row.count);
    stats.total += parseInt(row.count);
  }
  
  return stats;
}

/**
 * Clear old logs (for maintenance)
 */
export async function clearExpiredLogs() {
  const result = await pool.query(
    `DELETE FROM bot_logs WHERE expires_at < NOW() RETURNING id`
  );
  return result.rowCount;
}

/**
 * Clear error state for a bot (when manually resolved)
 */
export async function clearErrorState(botExchangeConfigId) {
  await pool.query(
    `UPDATE bot_exchange_configs 
     SET error_count = 0, 
         last_error = NULL, 
         last_error_at = NULL,
         state = CASE 
           WHEN state = 'error' THEN 'ready'::bot_config_state 
           ELSE state 
         END
     WHERE id = $1`,
    [botExchangeConfigId]
  );
}

/**
 * Helper to log different levels
 */
export const log = {
  debug: (params) => createLog({ ...params, level: 'debug' }),
  info: (params) => createLog({ ...params, level: 'info' }),
  warn: (params) => createLog({ ...params, level: 'warn' }),
  error: (params) => createLog({ ...params, level: 'error' }),
  fatal: (params) => createLog({ ...params, level: 'fatal' }),
};

export default {
  createLog,
  getLogsByBotInstance,
  getRecentErrors,
  getErrorCount,
  getLogsByUser,
  getLogStats,
  clearExpiredLogs,
  clearErrorState,
  log,
  LOG_LEVELS,
  LOG_CATEGORIES,
};
