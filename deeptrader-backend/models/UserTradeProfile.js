/**
 * User Trade Profile Model
 * 
 * Manages user trading configuration including:
 * - Active exchange selection
 * - Trading mode (paper/live)
 * - Token lists per exchange
 * - Bot pool assignments
 */

import pool from '../config/database.js';

const QUOTE_ASSETS = ['USDT', 'USDC', 'USD'];

const normalizePercentValue = (value) => {
  if (value === undefined || value === null) return value;
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num > 1 ? num / 100 : num;
};

function normalizeSymbol(symbol) {
  if (!symbol) {
    return symbol;
  }

  let normalized = String(symbol).trim().toUpperCase();
  if (!normalized) {
    return normalized;
  }

  normalized = normalized.replace('/', '-');

  if (normalized.endsWith('-SWAP')) {
    return normalized;
  }

  if (normalized.includes('-')) {
    return normalized.endsWith('-SWAP') ? normalized : `${normalized}-SWAP`;
  }

  for (const quote of QUOTE_ASSETS) {
    if (normalized.endsWith(quote)) {
      const base = normalized.slice(0, -quote.length);
      if (base) {
        return `${base}-${quote}-SWAP`;
      }
    }
  }

  return normalized.endsWith('-SWAP') ? normalized : `${normalized}-SWAP`;
}

/**
 * Get or create a user's trade profile
 */
export async function getOrCreateProfile(userId) {
  // Try to get existing profile
  let result = await pool.query(
    `SELECT * FROM user_trade_profiles WHERE user_id = $1`,
    [userId]
  );
  
  if (result.rows[0]) {
    return result.rows[0];
  }
  
  // Create new profile with defaults
  result = await pool.query(
    `INSERT INTO user_trade_profiles (user_id)
     VALUES ($1)
     RETURNING *`,
    [userId]
  );
  
  return result.rows[0];
}

/**
 * Get user's trade profile
 */
export async function getProfile(userId) {
  const result = await pool.query(
    `SELECT tp.*, 
            ec.exchange as credential_exchange,
            ec.label as credential_label,
            ec.status as credential_status,
            ec.risk_config as credential_risk_config,
            ec.execution_config as credential_execution_config,
            ec.config_version as credential_config_version,
            ec.exchange_balance as credential_exchange_balance,
            ec.trading_capital as credential_trading_capital,
            ec.balance_updated_at as credential_balance_updated_at,
            ec.account_connected as credential_account_connected,
            ec.balance_currency as credential_balance_currency,
            ec.connection_error as credential_connection_error
     FROM user_trade_profiles tp
     LEFT JOIN user_exchange_credentials ec ON tp.active_credential_id = ec.id
     WHERE tp.user_id = $1`,
    [userId]
  );
  
  return result.rows[0] || null;
}

/**
 * Set active exchange credential
 */
export async function setActiveCredential(userId, credentialId) {
  // Get the credential to verify ownership and get exchange
  const credResult = await pool.query(
    `SELECT exchange FROM user_exchange_credentials 
     WHERE id = $1 AND user_id = $2 AND status = 'verified'`,
    [credentialId, userId]
  );
  
  if (!credResult.rows[0]) {
    throw new Error('Credential not found or not verified');
  }
  
  const exchange = credResult.rows[0].exchange;
  
  const result = await pool.query(
    `INSERT INTO user_trade_profiles (user_id, active_credential_id, active_exchange)
     VALUES ($1, $2, $3)
     ON CONFLICT (user_id) DO UPDATE SET
       active_credential_id = EXCLUDED.active_credential_id,
       active_exchange = EXCLUDED.active_exchange
     RETURNING *`,
    [userId, credentialId, exchange]
  );
  
  return result.rows[0];
}

/**
 * Set trading mode (paper/live)
 */
export async function setTradingMode(userId, mode) {
  if (!['paper', 'live'].includes(mode)) {
    throw new Error('Invalid trading mode. Must be "paper" or "live"');
  }
  
  const result = await pool.query(
    `INSERT INTO user_trade_profiles (user_id, trading_mode)
     VALUES ($1, $2)
     ON CONFLICT (user_id) DO UPDATE SET trading_mode = EXCLUDED.trading_mode
     RETURNING *`,
    [userId, mode]
  );
  
  return result.rows[0];
}

/**
 * Update token list for an exchange
 */
export async function updateTokenList(userId, exchange, tokens) {
  if (!Array.isArray(tokens)) {
    throw new Error('Tokens must be an array');
  }

  const normalizedTokens = Array.from(
    new Set(tokens.map((symbol) => normalizeSymbol(symbol)))
  );
  
  // Update the JSONB token_lists field
  const result = await pool.query(
    `INSERT INTO user_trade_profiles (user_id, token_lists)
     VALUES ($1, jsonb_build_object($2::text, $3::jsonb))
     ON CONFLICT (user_id) DO UPDATE SET
       token_lists = user_trade_profiles.token_lists || jsonb_build_object($2::text, $3::jsonb)
     RETURNING *`,
    [userId, exchange, JSON.stringify(normalizedTokens)]
  );
  
  if (result.rows[0]) {
    result.rows[0].token_lists = result.rows[0].token_lists || {};
    result.rows[0].token_lists[exchange] = normalizedTokens;
  }

  return result.rows[0];
}

/**
 * Get token list for an exchange
 */
export async function getTokenList(userId, exchange) {
  const result = await pool.query(
    `SELECT token_lists -> ($2::text) as tokens
     FROM user_trade_profiles
     WHERE user_id = $1`,
    [userId, exchange]
  );
  
  const storedTokens = result.rows[0]?.tokens;
  if (Array.isArray(storedTokens) && storedTokens.length > 0) {
    return storedTokens.map((symbol) => normalizeSymbol(symbol));
  }
  
  if (!storedTokens) {
    // Return defaults based on exchange
    const defaults = {
      okx: ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP'],
      binance: ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP'],
      bybit: ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP'],
    };
    return defaults[exchange] || [];
  }

  return [];
}

/**
 * Update risk settings
 */
export async function updateRiskSettings(userId, settings) {
  const { maxPositions, positionSizePct, maxDailyLossPct } = settings;
  const normalizedPositionSizePct = normalizePercentValue(positionSizePct);
  const normalizedMaxDailyLossPct = normalizePercentValue(maxDailyLossPct);
  
  const result = await pool.query(
    `INSERT INTO user_trade_profiles 
     (user_id, default_max_positions, default_position_size_pct, default_max_daily_loss_pct)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (user_id) DO UPDATE SET
       default_max_positions = COALESCE(EXCLUDED.default_max_positions, user_trade_profiles.default_max_positions),
       default_position_size_pct = COALESCE(EXCLUDED.default_position_size_pct, user_trade_profiles.default_position_size_pct),
       default_max_daily_loss_pct = COALESCE(EXCLUDED.default_max_daily_loss_pct, user_trade_profiles.default_max_daily_loss_pct)
     RETURNING *`,
    [userId, maxPositions, normalizedPositionSizePct, normalizedMaxDailyLossPct]
  );
  
  return result.rows[0];
}

/**
 * Update bot assignment
 */
export async function updateBotAssignment(userId, botId, status) {
  const result = await pool.query(
    `UPDATE user_trade_profiles 
     SET assigned_bot_id = $2::text,
         bot_status = $3::text,
         bot_assigned_at = CASE WHEN $2::text IS NOT NULL THEN NOW() ELSE NULL END
     WHERE user_id = $1
     RETURNING *`,
    [userId, botId, status]
  );
  
  return result.rows[0];
}

/**
 * Get users with active bots
 */
export async function getUsersWithActiveBots() {
  const result = await pool.query(
    `SELECT tp.*, u.email, u.username
     FROM user_trade_profiles tp
     JOIN users u ON tp.user_id = u.id
     WHERE tp.bot_status = 'running' AND tp.assigned_bot_id IS NOT NULL`
  );
  
  return result.rows;
}

/**
 * Clear bot assignment (when bot stops)
 */
export async function clearBotAssignment(userId) {
  const result = await pool.query(
    `UPDATE user_trade_profiles 
     SET assigned_bot_id = NULL, bot_status = 'stopped'
     WHERE user_id = $1
     RETURNING *`,
    [userId]
  );
  
  return result.rows[0];
}

/**
 * Update account balance for position sizing
 */
export async function updateAccountBalance(userId, accountBalance) {
  if (accountBalance < 0) {
    throw new Error('Account balance cannot be negative');
  }
  
  const result = await pool.query(
    `INSERT INTO user_trade_profiles (user_id, account_balance)
     VALUES ($1, $2)
     ON CONFLICT (user_id) DO UPDATE SET account_balance = EXCLUDED.account_balance
     RETURNING *`,
    [userId, accountBalance]
  );
  
  return result.rows[0];
}

/**
 * Update global leverage settings
 */
export async function updateGlobalLeverage(userId, maxLeverage, leverageMode = 'isolated') {
  if (maxLeverage < 1 || maxLeverage > 125) {
    throw new Error('Leverage must be between 1 and 125');
  }
  if (!['isolated', 'cross'].includes(leverageMode)) {
    throw new Error('Leverage mode must be "isolated" or "cross"');
  }
  
  const result = await pool.query(
    `INSERT INTO user_trade_profiles (user_id, global_max_leverage, global_leverage_mode)
     VALUES ($1, $2, $3)
     ON CONFLICT (user_id) DO UPDATE SET 
       global_max_leverage = EXCLUDED.global_max_leverage,
       global_leverage_mode = EXCLUDED.global_leverage_mode
     RETURNING *`,
    [userId, maxLeverage, leverageMode]
  );
  
  return result.rows[0];
}

/**
 * Set the active config snapshot when bot starts
 */
export async function setActiveConfigSnapshot(userId, configSnapshot, configVersion) {
  const result = await pool.query(
    `UPDATE user_trade_profiles 
     SET active_config_snapshot = $2,
         active_config_version = $3
     WHERE user_id = $1
     RETURNING *`,
    [userId, JSON.stringify(configSnapshot), configVersion]
  );
  
  return result.rows[0];
}

/**
 * Clear active config snapshot when bot stops
 */
export async function clearActiveConfigSnapshot(userId) {
  const result = await pool.query(
    `UPDATE user_trade_profiles 
     SET active_config_snapshot = NULL,
         active_config_version = NULL
     WHERE user_id = $1
     RETURNING *`,
    [userId]
  );
  
  return result.rows[0];
}

/**
 * Get full trading context for a user (profile + credential config)
 */
export async function getFullTradingContext(userId) {
  const result = await pool.query(
    `SELECT 
       tp.*,
       ec.id as credential_id,
       ec.exchange,
       ec.is_testnet,
       ec.status as credential_status,
       ec.risk_config,
       ec.execution_config,
       ec.ui_preferences,
       ec.config_version,
       el.max_leverage as exchange_max_leverage,
       el.min_position_usd as exchange_min_position_usd,
       el.supports_isolated_margin,
       el.supports_cross_margin,
       el.supports_trailing_stop
     FROM user_trade_profiles tp
     LEFT JOIN user_exchange_credentials ec ON tp.active_credential_id = ec.id
     LEFT JOIN exchange_limits el ON ec.exchange = el.exchange
     WHERE tp.user_id = $1`,
    [userId]
  );
  
  return result.rows[0] || null;
}

export default {
  getOrCreateProfile,
  getProfile,
  setActiveCredential,
  setTradingMode,
  updateTokenList,
  getTokenList,
  updateRiskSettings,
  updateBotAssignment,
  getUsersWithActiveBots,
  clearBotAssignment,
  updateAccountBalance,
  updateGlobalLeverage,
  setActiveConfigSnapshot,
  clearActiveConfigSnapshot,
  getFullTradingContext,
};
