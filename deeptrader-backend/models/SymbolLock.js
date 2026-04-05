/**
 * Symbol Lock Model
 * 
 * Symbol ownership locks for TEAM/PROP modes - prevents bot conflicts.
 * Each symbol on an exchange account can only be traded by one bot at a time.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Default lease duration in minutes (for automatic expiry)
 */
export const DEFAULT_LEASE_MINUTES = 60;

/**
 * Acquire locks for multiple symbols atomically
 * Returns array of results: { symbol, acquired: boolean, owner_bot_id?, owner_bot_name? }
 */
export async function acquireMany(exchangeAccountId, environment, symbols, botId) {
  const results = [];
  
  // Use a transaction for atomicity
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    
    for (const symbol of symbols) {
      // Try to acquire or update if already owned by this bot
      const result = await client.query(
        `INSERT INTO symbol_locks (
          id, exchange_account_id, environment, symbol, owner_bot_id, 
          acquired_at, lease_heartbeat_at
        ) VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
        ON CONFLICT (exchange_account_id, environment, symbol) DO UPDATE
        SET owner_bot_id = EXCLUDED.owner_bot_id,
            acquired_at = NOW(),
            lease_heartbeat_at = NOW()
        WHERE symbol_locks.owner_bot_id = $5
           OR symbol_locks.lease_heartbeat_at < NOW() - INTERVAL '${DEFAULT_LEASE_MINUTES} minutes'
        RETURNING *`,
        [randomUUID(), exchangeAccountId, environment, symbol, botId]
      );
      
      if (result.rows.length > 0) {
        results.push({ symbol, acquired: true });
      } else {
        // Lock exists and is held by another bot - get owner info
        const existing = await client.query(
          `SELECT sl.*, bi.name as owner_bot_name
           FROM symbol_locks sl
           LEFT JOIN bot_instances bi ON bi.id = sl.owner_bot_id
           WHERE sl.exchange_account_id = $1 AND sl.environment = $2 AND sl.symbol = $3`,
          [exchangeAccountId, environment, symbol]
        );
        
        const owner = existing.rows[0];
        
        // Record conflict
        await client.query(
          `UPDATE symbol_locks
           SET last_conflict_bot_id = $1,
               last_conflict_at = NOW(),
               conflict_count = conflict_count + 1
           WHERE exchange_account_id = $2 AND environment = $3 AND symbol = $4`,
          [botId, exchangeAccountId, environment, symbol]
        );
        
        results.push({
          symbol,
          acquired: false,
          owner_bot_id: owner?.owner_bot_id,
          owner_bot_name: owner?.owner_bot_name,
        });
      }
    }
    
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
  
  return results;
}

/**
 * Acquire a single symbol lock
 */
export async function acquire(exchangeAccountId, environment, symbol, botId) {
  const results = await acquireMany(exchangeAccountId, environment, [symbol], botId);
  return results[0];
}

/**
 * Release all locks for a bot
 */
export async function releaseByBot(botId) {
  const result = await pool.query(
    `DELETE FROM symbol_locks WHERE owner_bot_id = $1 RETURNING *`,
    [botId]
  );
  return result.rows;
}

/**
 * Release specific symbols for a bot
 */
export async function releaseSymbols(botId, symbols) {
  const result = await pool.query(
    `DELETE FROM symbol_locks 
     WHERE owner_bot_id = $1 AND symbol = ANY($2)
     RETURNING *`,
    [botId, symbols]
  );
  return result.rows;
}

/**
 * Get lock for a specific symbol
 */
export async function getBySymbol(exchangeAccountId, environment, symbol) {
  const result = await pool.query(
    `SELECT sl.*, bi.name as owner_bot_name
     FROM symbol_locks sl
     LEFT JOIN bot_instances bi ON bi.id = sl.owner_bot_id
     WHERE sl.exchange_account_id = $1 AND sl.environment = $2 AND sl.symbol = $3`,
    [exchangeAccountId, environment, symbol]
  );
  return result.rows[0] || null;
}

/**
 * Get all locks for an exchange account
 */
export async function getByExchangeAccount(exchangeAccountId, environment = null) {
  let query = `
    SELECT sl.*, bi.name as owner_bot_name
    FROM symbol_locks sl
    LEFT JOIN bot_instances bi ON bi.id = sl.owner_bot_id
    WHERE sl.exchange_account_id = $1`;
  
  const params = [exchangeAccountId];
  
  if (environment) {
    query += ` AND sl.environment = $2`;
    params.push(environment);
  }
  
  query += ` ORDER BY sl.symbol`;
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Get all locks owned by a bot
 */
export async function getByBot(botId) {
  const result = await pool.query(
    `SELECT * FROM symbol_locks WHERE owner_bot_id = $1 ORDER BY symbol`,
    [botId]
  );
  return result.rows;
}

/**
 * Check for conflicts before starting a bot
 * Returns list of symbols that would conflict
 */
export async function getConflicts(exchangeAccountId, environment, symbols, requestingBotId) {
  const result = await pool.query(
    `SELECT sl.symbol, sl.owner_bot_id, bi.name as owner_bot_name
     FROM symbol_locks sl
     LEFT JOIN bot_instances bi ON bi.id = sl.owner_bot_id
     WHERE sl.exchange_account_id = $1 
       AND sl.environment = $2 
       AND sl.symbol = ANY($3)
       AND sl.owner_bot_id != $4
       AND sl.lease_heartbeat_at > NOW() - INTERVAL '${DEFAULT_LEASE_MINUTES} minutes'`,
    [exchangeAccountId, environment, symbols, requestingBotId]
  );
  return result.rows;
}

/**
 * Update heartbeat for a bot's locks (keeps them alive)
 */
export async function heartbeat(botId) {
  const result = await pool.query(
    `UPDATE symbol_locks
     SET lease_heartbeat_at = NOW()
     WHERE owner_bot_id = $1
     RETURNING *`,
    [botId]
  );
  return result.rows;
}

/**
 * Clean up expired locks
 */
export async function cleanupExpired() {
  const result = await pool.query(
    `DELETE FROM symbol_locks
     WHERE (expires_at IS NOT NULL AND expires_at < NOW())
        OR lease_heartbeat_at < NOW() - INTERVAL '${DEFAULT_LEASE_MINUTES * 2} minutes'
     RETURNING *`
  );
  return result.rows;
}

/**
 * Check if a bot owns a specific symbol
 */
export async function botOwnsSymbol(botId, symbol) {
  const result = await pool.query(
    `SELECT EXISTS(
      SELECT 1 FROM symbol_locks 
      WHERE owner_bot_id = $1 AND symbol = $2
    ) as owns`,
    [botId, symbol]
  );
  return result.rows[0].owns;
}

/**
 * Get summary of locks per bot for an account
 */
export async function getLockSummary(exchangeAccountId, environment = null) {
  let query = `
    SELECT sl.owner_bot_id, bi.name as bot_name, 
           COUNT(*) as symbol_count,
           array_agg(sl.symbol ORDER BY sl.symbol) as symbols
    FROM symbol_locks sl
    LEFT JOIN bot_instances bi ON bi.id = sl.owner_bot_id
    WHERE sl.exchange_account_id = $1`;
  
  const params = [exchangeAccountId];
  
  if (environment) {
    query += ` AND sl.environment = $2`;
    params.push(environment);
  }
  
  query += ` GROUP BY sl.owner_bot_id, bi.name ORDER BY bi.name`;
  
  const result = await pool.query(query, params);
  return result.rows;
}

export default {
  acquireMany,
  acquire,
  releaseByBot,
  releaseSymbols,
  getBySymbol,
  getByExchangeAccount,
  getByBot,
  getConflicts,
  heartbeat,
  cleanupExpired,
  botOwnsSymbol,
  getLockSummary,
  DEFAULT_LEASE_MINUTES,
};







