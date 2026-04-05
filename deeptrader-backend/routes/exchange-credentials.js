/**
 * Exchange Credentials Routes
 * 
 * REST API for managing per-user exchange API credentials
 * and trading profiles.
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import * as UserExchangeCredential from '../models/UserExchangeCredential.js';
import * as UserTradeProfile from '../models/UserTradeProfile.js';
import ExchangeAccount from '../models/ExchangeAccount.js';
import secretsProvider from '../services/secretsProvider.js';
import pool from '../config/database.js';
import { logStructuredEvent } from '../services/logger.js';

const router = express.Router();

// All routes require authentication
router.use(authenticateToken);

const BALANCE_REFRESH_MIN_INTERVAL_MS = Math.max(
  5000,
  parseInt(process.env.BALANCE_REFRESH_MIN_INTERVAL_MS || '30000', 10)
);
const DEFAULT_RETRY_AFTER_SECONDS = Math.ceil(BALANCE_REFRESH_MIN_INTERVAL_MS / 1000);

const logBalanceEvent = (level, message, context = {}) =>
  logStructuredEvent(level, 'exchange_balance', message, context);

// ═══════════════════════════════════════════════════════════════
// EXCHANGE CREDENTIALS
// ═══════════════════════════════════════════════════════════════

/**
 * GET /api/exchange-credentials
 * List all exchange credentials for the current user
 */
router.get('/', async (req, res) => {
  try {
    const credentials = await UserExchangeCredential.getCredentialsByUser(req.user.id);

    // Mask sensitive data
    const masked = credentials.map(cred => ({
      ...cred,
      secret_id: undefined, // Don't expose secret paths
    }));

    res.json({ credentials: masked });
  } catch (error) {
    console.error('Failed to list credentials:', error);
    res.status(500).json({ error: 'Failed to list credentials' });
  }
});

/**
 * POST /api/exchange-credentials
 * Add new exchange credentials
 */
router.post('/', async (req, res) => {
  try {
    const { exchange, apiKey, secretKey, passphrase, label, isDemo } = req.body;

    // Validate exchange
    if (!secretsProvider.SUPPORTED_EXCHANGES.includes(exchange)) {
      return res.status(400).json({
        error: `Unsupported exchange. Must be one of: ${secretsProvider.SUPPORTED_EXCHANGES.join(', ')}`
      });
    }

    // Validate required fields
    if (!apiKey || !secretKey) {
      return res.status(400).json({ error: 'API key and secret key are required' });
    }

    if (exchange === 'okx' && !passphrase) {
      return res.status(400).json({ error: 'Passphrase is required for OKX' });
    }

    // Check if user already has this exchange
    const existing = await UserExchangeCredential.getCredentialByExchange(req.user.id, exchange);
    if (existing && !label) {
      return res.status(400).json({
        error: 'You already have credentials for this exchange. Use a unique label or update existing.'
      });
    }

    // Create credential record in DB
    const credential = await UserExchangeCredential.createCredential(req.user.id, {
      exchange,
      label,
      isDemo: isDemo || false,
    });

    // Save actual secrets
    const secrets = { apiKey, secretKey };
    if (passphrase) secrets.passphrase = passphrase;

    await secretsProvider.saveExchangeCredentials(credential.secret_id, exchange, secrets);

    // Verify credentials in background (includes balance fetch)
    verifyCredentialsAsync(credential.id, exchange, secrets, isDemo);

    res.status(201).json({
      message: 'Credentials added successfully. Verification in progress.',
      credential: {
        id: credential.id,
        exchange: credential.exchange,
        label: credential.label,
        status: credential.status,
        isDemo: credential.is_demo,
        createdAt: credential.created_at,
      },
    });
  } catch (error) {
    console.error('Failed to add credentials:', error);
    res.status(500).json({ error: 'Failed to add credentials' });
  }
});

/**
 * PUT /api/exchange-credentials/:id
 * Update credential metadata (not secrets)
 */
router.put('/:id', async (req, res) => {
  try {
    const { label, isDemo } = req.body;

    const credential = await UserExchangeCredential.updateCredential(
      req.params.id,
      req.user.id,
      { label, is_demo: isDemo }
    );

    if (!credential) {
      return res.status(404).json({ error: 'Credential not found' });
    }

    res.json({ credential });
  } catch (error) {
    console.error('Failed to update credential:', error);
    res.status(500).json({ error: 'Failed to update credential' });
  }
});

/**
 * PUT /api/exchange-credentials/:id/secrets
 * Update the actual API secrets
 */
router.put('/:id/secrets', async (req, res) => {
  try {
    const { apiKey, secretKey, passphrase } = req.body;

    // Get existing credential
    const credential = await UserExchangeCredential.getCredentialById(req.params.id, req.user.id);
    if (!credential) {
      return res.status(404).json({ error: 'Credential not found' });
    }

    // Validate required fields
    if (!apiKey || !secretKey) {
      return res.status(400).json({ error: 'API key and secret key are required' });
    }

    if (credential.exchange === 'okx' && !passphrase) {
      return res.status(400).json({ error: 'Passphrase is required for OKX' });
    }

    // Update secrets
    const secrets = { apiKey, secretKey };
    if (passphrase) secrets.passphrase = passphrase;

    await secretsProvider.saveExchangeCredentials(credential.secret_id, credential.exchange, secrets);

    // Reset verification status
    await UserExchangeCredential.updateVerificationStatus(credential.id, 'pending');

    // Re-verify in background (includes balance fetch)
    verifyCredentialsAsync(credential.id, credential.exchange, secrets, credential.is_demo);

    res.json({ message: 'Secrets updated. Verification in progress.' });
  } catch (error) {
    console.error('Failed to update secrets:', error);
    res.status(500).json({ error: 'Failed to update secrets' });
  }
});

/**
 * POST /api/exchange-credentials/:id/verify
 * Manually trigger credential verification
 */
router.post('/:id/verify', async (req, res) => {
  try {
    const credential = await UserExchangeCredential.getCredentialById(req.params.id, req.user.id);
    if (!credential) {
      return res.status(404).json({ error: 'Credential not found' });
    }
    logStructuredEvent('info', 'exchange.verify.start', 'Manual verification triggered', {
      credentialId: credential.id,
      exchange: credential.exchange,
      isDemo: credential.is_demo,
    });

    // Get secrets
    const secrets = await secretsProvider.getExchangeCredentials(credential.secret_id);
    if (!secrets) {
      return res.status(400).json({ error: 'No secrets found for this credential' });
    }

    // Verify synchronously (now includes balance)
    const result = await secretsProvider.verifyExchangeCredentials(
      credential.exchange,
      secrets,
      credential.is_demo
    );

    // Update verification status with balance data
    await UserExchangeCredential.updateVerificationStatus(
      credential.id,
      result.valid ? 'verified' : 'failed',
      result.error,
      result.permissions,
      {
        balance: result.balance,
        currency: result.currency,
        accountConnected: result.accountConnected,
      }
    );

    logStructuredEvent(
      result.valid ? 'info' : 'warn',
      'exchange.verify.finish',
      'Verification completed',
      {
        credentialId: credential.id,
        exchange: credential.exchange,
        isDemo: credential.is_demo,
        baseUrl: result.meta?.baseUrl,
        warning: result.warning,
        error: result.error,
      }
    );

    res.json({
      valid: result.valid,
      error: result.error,
      warning: result.warning,
      permissions: result.permissions,
      balance: result.balance,
      currency: result.currency,
      accountConnected: result.accountConnected,
    });
  } catch (error) {
    console.error('Failed to verify credential:', error);
    logStructuredEvent('error', 'exchange.verify.error', 'Verification threw exception', {
      credentialId: req.params.id,
      userId: req.user.id,
      error: error.message,
    });
    res.status(500).json({ error: 'Failed to verify credential' });
  }
});

/**
 * POST /api/exchange-credentials/:id/refresh-balance
 * Refresh the exchange balance for a credential
 */
router.post('/:id/refresh-balance', async (req, res) => {
  try {
    const credential = await UserExchangeCredential.getCredentialById(req.params.id, req.user.id);
    if (!credential) {
      return res.status(404).json({ error: 'Credential not found' });
    }

    if (credential.status !== 'verified') {
      return res.status(400).json({ error: 'Credential must be verified before refreshing balance' });
    }

    // Get secrets
    const secrets = await secretsProvider.getExchangeCredentials(credential.secret_id);
    if (!secrets) {
      return res.status(400).json({ error: 'No secrets found for this credential' });
    }

    // Rate limit refresh attempts to avoid hammering exchanges
    if (credential.balance_updated_at) {
      const lastRefreshMs = new Date(credential.balance_updated_at).getTime();
      const elapsed = Date.now() - lastRefreshMs;
      if (elapsed < BALANCE_REFRESH_MIN_INTERVAL_MS) {
        const retryAfter = Math.ceil((BALANCE_REFRESH_MIN_INTERVAL_MS - elapsed) / 1000);
        return res.status(429).json({
          error: 'Balance was refreshed recently',
          errorCode: 'BALANCE_REFRESH_COOLDOWN',
          retryAfter,
        });
      }
    }

    // Fetch balance
    const result = await secretsProvider.fetchExchangeBalance(
      credential.exchange,
      secrets,
      credential.is_demo
    );

    if (result.success) {
      // Update the credential with new balance
      await UserExchangeCredential.updateExchangeBalance(
        credential.id,
        req.user.id,
        result.balance,
        result.currency,
        { fetchSource: 'manual_refresh' }
      );

      logBalanceEvent('info', 'Balance refresh success', {
        credentialId: credential.id,
        userId: req.user.id,
        exchange: credential.exchange,
        balance: result.balance,
      });

      res.json({
        success: true,
        balance: result.balance,
        currency: result.currency,
        timestamp: result.timestamp,
        accountConnected: true,
        retryAfter: DEFAULT_RETRY_AFTER_SECONDS,
      });
    } else {
      // Mark as disconnected
      await UserExchangeCredential.markDisconnected(credential.id, result.error);
      logBalanceEvent('warn', 'Balance refresh failed', {
        credentialId: credential.id,
        userId: req.user.id,
        exchange: credential.exchange,
        error: result.error,
      });

      res.status(502).json({
        success: false,
        error: result.error,
        errorCode: 'BALANCE_REFRESH_FAILED',
        accountConnected: false,
        retryAfter: DEFAULT_RETRY_AFTER_SECONDS,
      });
    }
  } catch (error) {
    logBalanceEvent('error', 'Balance refresh exception', {
      credentialId: req.params.id,
      userId: req.user.id,
      error: error.message,
    });
    res.status(500).json({
      error: 'Failed to refresh balance',
      errorCode: 'BALANCE_REFRESH_ERROR',
      retryAfter: DEFAULT_RETRY_AFTER_SECONDS,
    });
  }
});

/**
 * PUT /api/exchange-credentials/:id/trading-capital
 * Set the trading capital for a credential
 */
router.put('/:id/trading-capital', async (req, res) => {
  try {
    const { tradingCapital } = req.body;

    if (typeof tradingCapital !== 'number' || tradingCapital < 0) {
      return res.status(400).json({ error: 'Trading capital must be a positive number' });
    }

    const credential = await UserExchangeCredential.updateTradingCapital(
      req.params.id,
      req.user.id,
      tradingCapital
    );

    if (!credential) {
      return res.status(404).json({ error: 'Credential not found' });
    }

    res.json({ credential, message: 'Trading capital updated' });
  } catch (error) {
    console.error('Failed to update trading capital:', error);
    res.status(500).json({ error: error.message || 'Failed to update trading capital' });
  }
});

/**
 * DELETE /api/exchange-credentials/:id
 * Delete a credential
 */
router.delete('/:id', async (req, res) => {
  try {
    const deleted = await UserExchangeCredential.deleteCredential(req.params.id, req.user.id);

    if (!deleted) {
      return res.status(404).json({ error: 'Credential not found' });
    }

    res.json({ message: 'Credential deleted successfully' });
  } catch (error) {
    console.error('Failed to delete credential:', error);
    res.status(500).json({ error: 'Failed to delete credential' });
  }
});

// ═══════════════════════════════════════════════════════════════
// TRADE PROFILE
// ═══════════════════════════════════════════════════════════════

/**
 * GET /api/exchange-credentials/profile
 * Get user's trade profile with active credential info
 */
router.get('/profile', async (req, res) => {
  try {
    const exchangeAccountId = req.query.exchange_account_id || req.query.exchangeAccountId;

    // First ensure profile exists
    await UserTradeProfile.getOrCreateProfile(req.user.id);
    let profile = await UserTradeProfile.getProfile(req.user.id);

    if (exchangeAccountId) {
      const account = await ExchangeAccount.getById(exchangeAccountId);
      if (!account || account.tenant_id !== req.user.id) {
        return res.status(404).json({ error: 'Exchange account not found' });
      }

      const credentialResult = account.secret_id
        ? await pool.query(
            `SELECT *
               FROM user_exchange_credentials
              WHERE user_id = $1
                AND secret_id = $2
              ORDER BY created_at DESC
              LIMIT 1`,
            [req.user.id, account.secret_id]
          )
        : { rows: [] };
      const credential = credentialResult.rows[0] || null;

      profile = {
        ...profile,
        scoped_exchange_account_id: account.id,
        active_credential_id: credential?.id || account.id,
        active_exchange: credential?.exchange || account.venue,
        credential_exchange: credential?.exchange || account.venue,
        credential_label: credential?.label || account.label,
        credential_status: credential?.status || account.status,
        credential_risk_config: credential?.risk_config ?? profile?.credential_risk_config ?? null,
        credential_execution_config: credential?.execution_config ?? profile?.credential_execution_config ?? null,
        credential_config_version: credential?.config_version ?? profile?.credential_config_version ?? null,
        credential_exchange_balance:
          credential?.exchange_balance ?? account.exchange_balance ?? null,
        credential_trading_capital:
          credential?.trading_capital ?? profile?.credential_trading_capital ?? null,
        credential_balance_updated_at:
          credential?.balance_updated_at ?? account.balance_updated_at ?? null,
        credential_account_connected:
          credential?.account_connected ??
          (account.status === 'verified' ? true : null),
        credential_balance_currency:
          credential?.balance_currency ?? account.balance_currency ?? null,
        credential_connection_error:
          credential?.connection_error ?? account.verification_error ?? null,
      };
    }

    res.json({ profile });
  } catch (error) {
    console.error('Failed to get trade profile:', error);
    res.status(500).json({ error: 'Failed to get trade profile' });
  }
});

/**
 * PUT /api/exchange-credentials/profile/active
 * Set active exchange credential
 */
router.put('/profile/active', async (req, res) => {
  try {
    const { credentialId } = req.body;

    if (!credentialId) {
      return res.status(400).json({ error: 'Credential ID is required' });
    }

    const profile = await UserTradeProfile.setActiveCredential(req.user.id, credentialId);
    res.json({ profile });
  } catch (error) {
    console.error('Failed to set active credential:', error);
    res.status(500).json({ error: error.message || 'Failed to set active credential' });
  }
});

/**
 * PUT /api/exchange-credentials/profile/mode
 * Set trading mode (paper/live)
 */
router.put('/profile/mode', async (req, res) => {
  try {
    const { mode } = req.body;

    if (mode === 'live') {
      const profile = await UserTradeProfile.getProfile(req.user.id);
      if (!profile || !profile.active_credential_id) {
        return res.status(400).json({ error: 'Set a verified active credential before enabling live trading' });
      }
      const credential = await UserExchangeCredential.getCredentialById(profile.active_credential_id, req.user.id);
      if (!credential || credential.status !== 'verified') {
        return res.status(400).json({ error: 'Active credential must be verified before enabling live trading' });
      }
    }

    const profile = await UserTradeProfile.setTradingMode(req.user.id, mode);
    res.json({ profile });
  } catch (error) {
    console.error('Failed to set trading mode:', error);
    res.status(500).json({ error: error.message || 'Failed to set trading mode' });
  }
});

/**
 * GET /api/exchange-credentials/profile/tokens/:exchange
 * Get token list for an exchange
 */
router.get('/profile/tokens/:exchange', async (req, res) => {
  try {
    const tokens = await UserTradeProfile.getTokenList(req.user.id, req.params.exchange);
    res.json({ tokens });
  } catch (error) {
    console.error('Failed to get tokens:', error);
    res.status(500).json({ error: 'Failed to get tokens' });
  }
});

/**
 * PUT /api/exchange-credentials/profile/tokens/:exchange
 * Update token list for an exchange
 */
router.put('/profile/tokens/:exchange', async (req, res) => {
  try {
    const { tokens } = req.body;

    if (!Array.isArray(tokens)) {
      return res.status(400).json({ error: 'Tokens must be an array' });
    }

    const profile = await UserTradeProfile.updateTokenList(req.user.id, req.params.exchange, tokens);
    res.json({ profile });
  } catch (error) {
    console.error('Failed to update tokens:', error);
    res.status(500).json({ error: 'Failed to update tokens' });
  }
});

/**
 * PUT /api/exchange-credentials/profile/risk
 * Update global risk settings (profile level)
 */
router.put('/profile/risk', async (req, res) => {
  try {
    const { maxPositions, positionSizePct, maxDailyLossPct } = req.body;

    const profile = await UserTradeProfile.updateRiskSettings(req.user.id, {
      maxPositions,
      positionSizePct,
      maxDailyLossPct,
    });

    res.json({ profile });
  } catch (error) {
    console.error('Failed to update risk settings:', error);
    res.status(500).json({ error: 'Failed to update risk settings' });
  }
});

/**
 * PUT /api/exchange-credentials/profile/balance
 * Update account balance for position sizing
 */
router.put('/profile/balance', async (req, res) => {
  try {
    const { accountBalance } = req.body;

    if (typeof accountBalance !== 'number' || accountBalance < 0) {
      return res.status(400).json({ error: 'Account balance must be a positive number' });
    }

    const profile = await UserTradeProfile.updateAccountBalance(req.user.id, accountBalance);
    res.json({ profile });
  } catch (error) {
    console.error('Failed to update account balance:', error);
    res.status(500).json({ error: error.message || 'Failed to update account balance' });
  }
});

/**
 * PUT /api/exchange-credentials/profile/leverage
 * Update global leverage settings
 */
router.put('/profile/leverage', async (req, res) => {
  try {
    const { maxLeverage, leverageMode } = req.body;

    const profile = await UserTradeProfile.updateGlobalLeverage(
      req.user.id,
      maxLeverage || 1,
      leverageMode || 'isolated'
    );
    res.json({ profile });
  } catch (error) {
    console.error('Failed to update leverage:', error);
    res.status(500).json({ error: error.message || 'Failed to update leverage settings' });
  }
});

/**
 * GET /api/exchange-credentials/profile/context
 * Get full trading context (profile + active credential config)
 */
router.get('/profile/context', async (req, res) => {
  try {
    const context = await UserTradeProfile.getFullTradingContext(req.user.id);
    res.json({ context });
  } catch (error) {
    console.error('Failed to get trading context:', error);
    res.status(500).json({ error: 'Failed to get trading context' });
  }
});

// ═══════════════════════════════════════════════════════════════
// PER-CREDENTIAL CONFIGURATION
// ═══════════════════════════════════════════════════════════════

/**
 * GET /api/exchange-credentials/:id/config
 * Get full bot profile for a credential
 */
router.get('/:id/config', async (req, res) => {
  try {
    const profile = await UserExchangeCredential.getBotProfile(req.params.id, req.user.id);

    if (!profile) {
      return res.status(404).json({ error: 'Credential not found' });
    }

    res.json({ profile });
  } catch (error) {
    console.error('Failed to get credential config:', error);
    res.status(500).json({ error: 'Failed to get credential config' });
  }
});

/**
 * PUT /api/exchange-credentials/:id/config/risk
 * Update risk configuration for a credential
 */
router.put('/:id/config/risk', async (req, res) => {
  try {
    const { riskConfig, changeReason } = req.body;

    if (!riskConfig || typeof riskConfig !== 'object') {
      return res.status(400).json({ error: 'Risk config object is required' });
    }

    const credential = await UserExchangeCredential.updateRiskConfig(
      req.params.id,
      req.user.id,
      riskConfig,
      changeReason
    );

    res.json({ credential, message: 'Risk configuration updated successfully' });
  } catch (error) {
    console.error('Failed to update risk config:', error);
    res.status(500).json({ error: error.message || 'Failed to update risk config' });
  }
});

/**
 * PUT /api/exchange-credentials/:id/config/execution
 * Update execution configuration for a credential
 */
router.put('/:id/config/execution', async (req, res) => {
  try {
    const { executionConfig, changeReason } = req.body;

    if (!executionConfig || typeof executionConfig !== 'object') {
      return res.status(400).json({ error: 'Execution config object is required' });
    }

    const credential = await UserExchangeCredential.updateExecutionConfig(
      req.params.id,
      req.user.id,
      executionConfig,
      changeReason
    );

    res.json({ credential, message: 'Execution configuration updated successfully' });
  } catch (error) {
    console.error('Failed to update execution config:', error);
    res.status(500).json({ error: error.message || 'Failed to update execution config' });
  }
});

/**
 * PUT /api/exchange-credentials/:id/config/ui
 * Update UI preferences for a credential
 */
router.put('/:id/config/ui', async (req, res) => {
  try {
    const { uiPreferences } = req.body;

    if (!uiPreferences || typeof uiPreferences !== 'object') {
      return res.status(400).json({ error: 'UI preferences object is required' });
    }

    const credential = await UserExchangeCredential.updateUiPreferences(
      req.params.id,
      req.user.id,
      uiPreferences
    );

    res.json({ credential });
  } catch (error) {
    console.error('Failed to update UI preferences:', error);
    res.status(500).json({ error: error.message || 'Failed to update UI preferences' });
  }
});

/**
 * GET /api/exchange-credentials/:id/config/audit
 * Get config change audit history for a credential
 */
router.get('/:id/config/audit', async (req, res) => {
  try {
    const history = await UserExchangeCredential.getConfigAuditHistory(
      req.params.id,
      req.user.id,
      parseInt(req.query.limit) || 50
    );

    res.json({ history });
  } catch (error) {
    console.error('Failed to get audit history:', error);
    res.status(500).json({ error: 'Failed to get audit history' });
  }
});

/**
 * GET /api/exchange-credentials/limits/:exchange
 * Get exchange-imposed limits for validation
 */
router.get('/limits/:exchange', async (req, res) => {
  try {
    const limits = await UserExchangeCredential.getExchangeLimits(req.params.exchange);
    res.json({ limits });
  } catch (error) {
    console.error('Failed to get exchange limits:', error);
    res.status(500).json({ error: 'Failed to get exchange limits' });
  }
});

// ═══════════════════════════════════════════════════════════════
// EXCHANGE TOKEN CATALOG
// ═══════════════════════════════════════════════════════════════

/**
 * GET /api/exchange-credentials/exchanges
 * Get list of supported exchanges
 */
router.get('/exchanges', async (req, res) => {
  res.json({
    exchanges: secretsProvider.SUPPORTED_EXCHANGES.map(ex => ({
      id: ex,
      name: ex.charAt(0).toUpperCase() + ex.slice(1),
      requiresPassphrase: ex === 'okx',
    })),
  });
});

/**
 * GET /api/exchange-credentials/exchanges/:exchange/tokens
 * Get available tokens for an exchange
 */
router.get('/exchanges/:exchange/tokens', async (req, res) => {
  try {
    const { exchange } = req.params;

    if (!secretsProvider.SUPPORTED_EXCHANGES.includes(exchange)) {
      return res.status(400).json({ error: 'Unsupported exchange' });
    }

    // Try to get from catalog first
    const result = await pool.query(
      `SELECT symbol, base_currency, quote_currency, contract_type, min_size, is_active
       FROM exchange_token_catalog
       WHERE exchange = $1 AND is_active = true
       ORDER BY base_currency`,
      [exchange]
    );

    if (result.rows.length > 0) {
      return res.json({ tokens: result.rows });
    }

    // Return defaults if catalog is empty
    const defaults = {
      okx: [
        { symbol: 'BTC-USDT-SWAP', base_currency: 'BTC', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'ETH-USDT-SWAP', base_currency: 'ETH', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'SOL-USDT-SWAP', base_currency: 'SOL', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'DOGE-USDT-SWAP', base_currency: 'DOGE', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'XRP-USDT-SWAP', base_currency: 'XRP', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'LINK-USDT-SWAP', base_currency: 'LINK', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'AVAX-USDT-SWAP', base_currency: 'AVAX', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'MATIC-USDT-SWAP', base_currency: 'MATIC', quote_currency: 'USDT', contract_type: 'perpetual' },
      ],
      binance: [
        { symbol: 'BTCUSDT', base_currency: 'BTC', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'ETHUSDT', base_currency: 'ETH', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'SOLUSDT', base_currency: 'SOL', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'DOGEUSDT', base_currency: 'DOGE', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'XRPUSDT', base_currency: 'XRP', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'LINKUSDT', base_currency: 'LINK', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'AVAXUSDT', base_currency: 'AVAX', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'MATICUSDT', base_currency: 'MATIC', quote_currency: 'USDT', contract_type: 'perpetual' },
      ],
      bybit: [
        { symbol: 'BTCUSDT', base_currency: 'BTC', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'ETHUSDT', base_currency: 'ETH', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'SOLUSDT', base_currency: 'SOL', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'DOGEUSDT', base_currency: 'DOGE', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'XRPUSDT', base_currency: 'XRP', quote_currency: 'USDT', contract_type: 'perpetual' },
        { symbol: 'LINKUSDT', base_currency: 'LINK', quote_currency: 'USDT', contract_type: 'perpetual' },
      ],
    };

    res.json({ tokens: defaults[exchange] || [] });
  } catch (error) {
    console.error('Failed to get exchange tokens:', error);
    res.status(500).json({ error: 'Failed to get exchange tokens' });
  }
});

// ═══════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════

/**
 * Verify credentials asynchronously (fire and forget)
 */
async function verifyCredentialsAsync(credentialId, exchange, secrets, isDemo = false) {
  try {
    const result = await secretsProvider.verifyExchangeCredentials(exchange, secrets, isDemo);

    await UserExchangeCredential.updateVerificationStatus(
      credentialId,
      result.valid ? 'verified' : 'failed',
      result.error,
      result.permissions,
      {
        balance: result.balance,
        currency: result.currency,
        accountConnected: result.accountConnected,
      }
    );

    console.log(`✅ Credential ${credentialId} verification: ${result.valid ? 'success' : 'failed'}${result.balance ? ` (balance: ${result.balance} ${result.currency})` : ''}`);
  } catch (err) {
    console.error(`❌ Credential ${credentialId} verification error:`, err.message);
    await UserExchangeCredential.updateVerificationStatus(credentialId, 'failed', err.message);
  }
}

export default router;
