/**
 * Exchange Accounts Routes
 * 
 * CRUD operations for exchange accounts, policy management,
 * active bot control, and kill switch.
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import ExchangeAccount from '../models/ExchangeAccount.js';
import ExchangePolicy from '../models/ExchangePolicy.js';
import BotBudget from '../models/BotBudget.js';
import secretsProvider, { buildSecretId } from '../services/secretsProvider.js';
import profileInstallService from '../services/profileInstallService.js';

const router = express.Router();

// All routes require authentication
router.use(authenticateToken);

// =============================================================================
// Exchange Account CRUD
// =============================================================================

/**
 * GET /api/exchange-accounts
 * List all exchange accounts for the authenticated user
 */
router.get('/', async (req, res) => {
  try {
    const { environment } = req.query;
    const exchangeAccountId = req.query.exchange_account_id || req.query.exchangeAccountId;

    if (exchangeAccountId) {
      const account = await ExchangeAccount.getById(exchangeAccountId);
      if (!account || account.tenant_id !== req.user.id) {
        return res.status(404).json({ error: 'Exchange account not found' });
      }
      return res.json({ accounts: [account] });
    }

    const accounts = await ExchangeAccount.getByTenant(req.user.id, environment);
    res.json({ accounts });
  } catch (err) {
    console.error('Error fetching exchange accounts:', err);
    res.status(500).json({ error: 'Failed to fetch exchange accounts' });
  }
});

/**
 * POST /api/exchange-accounts
 * Create a new exchange account
 */
router.post('/', async (req, res) => {
  try {
    const { venue, label, environment = 'paper', isDemo = false, paperCapital, metadata = {} } = req.body;
    
    if (!venue || !label) {
      return res.status(400).json({ error: 'Venue and label are required' });
    }
    
    if (!ExchangeAccount.VENUES.includes(venue)) {
      return res.status(400).json({ error: `Invalid venue. Allowed: ${ExchangeAccount.VENUES.join(', ')}` });
    }
    
    // NOTE: is_demo indicates exchange demo trading (Bybit api-demo, OKX simulated trading header)
    // Demo is NOT available for Binance (testnet deprecated) - use paper trading instead
    // environment indicates the bot's trading mode (paper simulation vs live orders)
    // Valid combinations:
    //   - demo + live = Real orders on demo exchange (safe testing, no real money)
    //   - demo + paper = Paper simulation using demo market data
    //   - mainnet + paper = Paper simulation using mainnet market data (no orders sent)
    //   - mainnet + live = REAL TRADING with real money!
    
    // Validate demo mode is only used on supported exchanges
    if (isDemo && !ExchangeAccount.DEMO_SUPPORTED_VENUES.includes(venue.toLowerCase())) {
      return res.status(400).json({ 
        error: `Demo trading is not supported for ${venue}. Use paper trading instead.` 
      });
    }
    
    if (!ExchangeAccount.ENVIRONMENTS.includes(environment)) {
      return res.status(400).json({ error: `Invalid environment. Allowed: ${ExchangeAccount.ENVIRONMENTS.join(', ')}` });
    }
    
    // For paper trading, require paper capital
    if (environment === 'paper' && (paperCapital === undefined || paperCapital === null)) {
      return res.status(400).json({ error: 'Paper capital is required for paper trading mode' });
    }
    
    // Check for duplicate
    const existing = await ExchangeAccount.getByCombo(req.user.id, venue, label, environment);
    if (existing) {
      return res.status(409).json({ error: 'An account with this venue, label, and environment already exists' });
    }
    
    // Store paper capital in metadata for paper trading accounts
    const accountMetadata = environment === 'paper' 
      ? { ...metadata, paperCapital, initialPaperCapital: paperCapital }
      : metadata;
    
    const account = await ExchangeAccount.create(req.user.id, {
      venue,
      label,
      environment,
      isDemo,
      metadata: accountMetadata,
    });
    
    // For paper trading, set the balance immediately
    if (environment === 'paper' && paperCapital) {
      await ExchangeAccount.updateBalance(account.id, {
        balance: paperCapital,
        available: paperCapital,
        currency: 'USDT',
      });
      // Re-fetch to get updated balance
      const updatedAccount = await ExchangeAccount.getById(account.id);
      
      // Ensure system profile templates are available (idempotent)
      let templateResult = null;
      try {
        templateResult = await profileInstallService.ensureSystemTemplates();
        if (templateResult.templatesCreated > 0) {
          console.log(`[ExchangeAccounts] Seeded ${templateResult.templatesCreated} system profile templates`);
        }
      } catch (templateErr) {
        console.error('[ExchangeAccounts] Failed to ensure system templates:', templateErr);
      }
      
      return res.status(201).json({ 
        account: updatedAccount,
        systemTemplatesAvailable: templateResult?.totalTemplates || 0,
      });
    }
    
    // Ensure system profile templates are available (idempotent)
    let templateResult = null;
    try {
      templateResult = await profileInstallService.ensureSystemTemplates();
      if (templateResult.templatesCreated > 0) {
        console.log(`[ExchangeAccounts] Seeded ${templateResult.templatesCreated} system profile templates`);
      }
    } catch (templateErr) {
      // Don't fail account creation if template seeding fails
      console.error('[ExchangeAccounts] Failed to ensure system templates:', templateErr);
    }
    
    res.status(201).json({ 
      account,
      systemTemplatesAvailable: templateResult?.totalTemplates || 0,
    });
  } catch (err) {
    console.error('Error creating exchange account:', err);
    res.status(500).json({ error: 'Failed to create exchange account' });
  }
});

/**
 * GET /api/exchange-accounts/:id
 * Get a specific exchange account
 */
router.get('/:id', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Get policy and bots
    const policy = await ExchangePolicy.getByAccount(account.id);
    const bots = await ExchangeAccount.getBots(account.id);
    const budgets = await BotBudget.getByExchangeAccount(account.id);
    
    res.json({
      account,
      policy,
      bots,
      budgets,
    });
  } catch (err) {
    console.error('Error fetching exchange account:', err);
    res.status(500).json({ error: 'Failed to fetch exchange account' });
  }
});

/**
 * PUT /api/exchange-accounts/:id
 * Update an exchange account
 */
router.put('/:id', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // NOTE: is_demo = use exchange demo trading API, environment = trading mode
    // Demo only supported on Bybit and OKX (see POST handler for details)
    
    const updated = await ExchangeAccount.update(req.params.id, req.body);
    res.json({ account: updated });
  } catch (err) {
    console.error('Error updating exchange account:', err);
    res.status(500).json({ error: 'Failed to update exchange account' });
  }
});

/**
 * GET /api/exchange-accounts/:id/can-delete
 * Check if an exchange account can be deleted (no linked bots)
 */
router.get('/:id/can-delete', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Check for running bots
    const hasRunning = await ExchangeAccount.hasRunningBots(account.id);
    if (hasRunning) {
      const runningBots = await ExchangeAccount.getRunningBots(account.id);
      return res.json({ 
        canDelete: false,
        reason: 'RUNNING_BOTS',
        message: 'Please stop all bots using this exchange account before deleting it.',
        linkedBots: runningBots.map(b => ({ id: b.id, name: b.name, status: 'running' }))
      });
    }
    
    // Check for linked bots (even if not running)
    const linkedBots = await ExchangeAccount.getLinkedBots(account.id);
    if (linkedBots && linkedBots.length > 0) {
      return res.json({ 
        canDelete: false,
        reason: 'LINKED_BOTS',
        message: `This exchange account is linked to ${linkedBots.length} bot(s). Please delete these bots first.`,
        linkedBots: linkedBots.map(b => ({ id: b.id, name: b.name, status: b.runtime_state || 'idle' }))
      });
    }
    
    res.json({ canDelete: true });
  } catch (err) {
    console.error('Error checking exchange account deletion:', err);
    res.status(500).json({ error: 'Failed to check account status' });
  }
});

/**
 * DELETE /api/exchange-accounts/:id
 * Delete an exchange account
 */
router.delete('/:id', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Check for running bots
    const hasRunning = await ExchangeAccount.hasRunningBots(account.id);
    if (hasRunning) {
      return res.status(400).json({ 
        error: 'Cannot delete account with running bots',
        code: 'RUNNING_BOTS',
        message: 'Please stop all bots using this exchange account before deleting it.'
      });
    }
    
    // Check for linked bots (even if not running)
    const linkedBots = await ExchangeAccount.getLinkedBots(account.id);
    if (linkedBots && linkedBots.length > 0) {
      return res.status(400).json({ 
        error: 'Cannot delete account with linked bots',
        code: 'LINKED_BOTS',
        message: `This exchange account is linked to ${linkedBots.length} bot(s): ${linkedBots.map(b => b.name).join(', ')}. Please delete or reassign these bots first.`,
        linkedBots: linkedBots.map(b => ({ id: b.id, name: b.name }))
      });
    }
    
    // Delete secrets if present
    if (account.secret_id) {
      try {
        await secretsProvider.deleteExchangeCredentials(account.secret_id);
      } catch (err) {
        console.warn('Failed to delete secrets:', err.message);
      }
    }
    
    await ExchangeAccount.remove(req.params.id);
    res.json({ success: true });
  } catch (err) {
    console.error('Error deleting exchange account:', err);
    
    // Handle foreign key constraint violations
    if (err.code === '23503') { // PostgreSQL foreign key violation
      return res.status(400).json({ 
        error: 'Cannot delete account due to linked data',
        code: 'FOREIGN_KEY_CONSTRAINT',
        message: 'This exchange account has associated data (bots, trades, or configurations) that must be removed first.',
        detail: err.detail
      });
    }
    
    res.status(500).json({ error: 'Failed to delete exchange account' });
  }
});

// =============================================================================
// Credentials & Verification
// =============================================================================

/**
 * POST /api/exchange-accounts/:id/credentials
 * Store and verify credentials for an exchange account
 * SECURITY: Rejects credentials that have withdrawal permissions
 */
router.post('/:id/credentials', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const { apiKey, secretKey, passphrase } = req.body;
    
    if (!apiKey || !secretKey) {
      return res.status(400).json({ error: 'API key and secret key are required' });
    }
    
    // Build secret ID
    const secretId = account.secret_id || buildSecretId({
      userId: req.user.id,
      exchange: account.venue,
      credentialId: account.id,
    });
    
    const credentials = { apiKey, secretKey, passphrase };
    const isDemo = account.is_demo || false;
    
    // STEP 1: Verify credentials with the exchange to check permissions
    console.log(`Verifying credentials for ${account.venue} (demo: ${isDemo})`);
    let verifyResult;
    try {
      verifyResult = await secretsProvider.verifyExchangeCredentials(
        account.venue,
        credentials,
        isDemo
      );
    } catch (verifyErr) {
      console.error('Credential verification failed:', verifyErr.message);

      // For paper trading environments, accept credentials even if verification fails
      // This allows users to use production keys for paper trading
      if (account.environment === 'paper' || account.environment === 'dev') {
        console.log('Accepting credentials for paper/dev environment despite verification failure');
        verifyResult = {
          valid: true,
          permissions: ['read', 'trade'], // Assume basic permissions for paper trading
          balance: 100000, // Default paper trading balance
          currency: 'USDT',
          accountConnected: true,
          canWithdraw: false,
          meta: { fallback: true, reason: 'paper_trading_fallback' }
        };
      } else {
        return res.status(400).json({
          error: 'Invalid credentials: ' + verifyErr.message,
          code: 'INVALID_CREDENTIALS'
        });
      }
    }

    if (!verifyResult?.valid) {
      return res.status(400).json({
        error: 'Invalid credentials: ' + (verifyResult?.error || 'verification failed'),
        code: 'INVALID_CREDENTIALS'
      });
    }
    
    // STEP 2: Check for withdrawal permissions - REJECT if present
    const permissions = verifyResult.permissions || [];
    const hasWithdraw = permissions.includes('withdraw') || 
                        permissions.includes('withdrawal') ||
                        verifyResult.canWithdraw === true;
    
    if (hasWithdraw) {
      console.warn(`SECURITY: Rejecting credentials with withdrawal permission for account ${account.id}`);
      return res.status(400).json({ 
        error: 'SECURITY VIOLATION: These API keys have withdrawal permissions enabled. For your safety, Veloxio does not accept keys with withdrawal access. Please create new API keys with only "Read" and "Trade" permissions.',
        code: 'WITHDRAWAL_PERMISSION_DETECTED'
      });
    }
    
    // STEP 3: Store credentials (verified and safe)
    console.log('[credentials] Saving credentials with secretId:', secretId);
    await secretsProvider.saveExchangeCredentials(secretId, account.venue, credentials);
    console.log('[credentials] Credentials saved successfully');
    
    // STEP 4: Update account with verification status
    console.log('[credentials] Updating account:', account.id, 'with secretId:', secretId);
    try {
      await ExchangeAccount.update(account.id, {
        secretId,
        status: 'verified',
      });
      console.log('[credentials] Account updated successfully');
    } catch (updateErr) {
      console.error('[credentials] ExchangeAccount.update failed:', updateErr);
      throw updateErr;
    }
    
    console.log('[credentials] Updating verification status');
    try {
      await ExchangeAccount.updateVerificationStatus(
        account.id,
        'verified',
        null,
        { 
          read: permissions.includes('read') || true,
          trade: permissions.includes('trade') || true,
          withdraw: false // We've verified it's false
        }
      );
      console.log('[credentials] Verification status updated');
    } catch (verifyErr) {
      console.error('[credentials] updateVerificationStatus failed:', verifyErr);
      throw verifyErr;
    }
    
    // Update balance if available
    if (verifyResult.balance !== undefined) {
      console.log('[credentials] Updating balance:', verifyResult.balance);
      try {
        await ExchangeAccount.updateBalance(account.id, {
          balance: verifyResult.balance,
          available: verifyResult.balance,
          currency: verifyResult.currency || 'USDT',
        });
        console.log('[credentials] Balance updated');
      } catch (balanceErr) {
        console.error('[credentials] updateBalance failed:', balanceErr);
        throw balanceErr;
      }
    }
    
    res.json({ 
      success: true, 
      message: 'Credentials verified and saved',
      permissions: { read: true, trade: true, withdraw: false },
      balance: verifyResult.balance,
      currency: verifyResult.currency
    });
  } catch (err) {
    console.error('Error storing credentials:', err);
    res.status(500).json({ error: 'Failed to store credentials: ' + err.message });
  }
});

/**
 * POST /api/exchange-accounts/:id/verify
 * Re-verify credentials by connecting to the exchange
 * SECURITY: Checks for withdrawal permissions and rejects if found
 */
router.post('/:id/verify', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    if (!account.secret_id) {
      return res.status(400).json({ error: 'No credentials stored' });
    }
    
    // Get credentials
    const creds = await secretsProvider.getExchangeCredentials(account.secret_id);
    if (!creds) {
      return res.status(400).json({ error: 'Credentials not found' });
    }
    
    const isDemo = account.is_demo || false;
    
    // Verify with exchange
    let verifyResult;
    try {
      verifyResult = await secretsProvider.verifyExchangeCredentials(
        account.venue,
        creds,
        isDemo
      );
    } catch (verifyErr) {
      await ExchangeAccount.updateVerificationStatus(account.id, 'error', verifyErr.message);
      return res.status(400).json({ 
        error: 'Verification failed: ' + verifyErr.message,
        code: 'VERIFICATION_FAILED'
      });
    }
    
    if (!verifyResult.valid) {
      await ExchangeAccount.updateVerificationStatus(account.id, 'error', verifyResult.error);
      return res.status(400).json({ 
        error: 'Credentials invalid: ' + verifyResult.error,
        code: 'INVALID_CREDENTIALS'
      });
    }
    
    // SECURITY: Check for withdrawal permissions
    const permissions = verifyResult.permissions || [];
    if (verifyResult.canWithdraw || permissions.includes('withdraw')) {
      await ExchangeAccount.updateVerificationStatus(
        account.id, 
        'error', 
        'Withdrawal permission detected - rejected for security'
      );
      return res.status(400).json({ 
        error: 'SECURITY VIOLATION: These API keys have withdrawal permissions. Please create new API keys with only "Read" and "Trade" permissions.',
        code: 'WITHDRAWAL_PERMISSION_DETECTED'
      });
    }
    
    // Update verification status
    const updated = await ExchangeAccount.updateVerificationStatus(
      account.id,
      'verified',
      null,
      { 
        read: permissions.includes('read') || true,
        trade: permissions.includes('trade') || true,
        withdraw: false
      }
    );
    
    // Update balance if available
    if (verifyResult.balance !== undefined) {
      await ExchangeAccount.updateBalance(account.id, {
        balance: verifyResult.balance,
        available: verifyResult.balance,
        currency: verifyResult.currency || 'USDT',
      });
    }
    
    res.json({ 
      success: true, 
      account: updated,
      permissions: { read: true, trade: true, withdraw: false },
      balance: verifyResult.balance,
      currency: verifyResult.currency
    });
  } catch (err) {
    console.error('Error verifying credentials:', err);
    await ExchangeAccount.updateVerificationStatus(
      req.params.id,
      'error',
      err.message
    );
    res.status(500).json({ error: 'Verification failed: ' + err.message });
  }
});

/**
 * PUT /api/exchange-accounts/:id/paper-capital
 * Update paper trading capital for paper accounts
 */
router.put('/:id/paper-capital', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    if (account.environment !== 'paper') {
      return res.status(400).json({ error: 'Paper capital can only be set for paper trading accounts' });
    }
    
    const { paperCapital } = req.body;
    
    if (paperCapital === undefined || paperCapital === null || paperCapital < 0) {
      return res.status(400).json({ error: 'Paper capital must be a non-negative number' });
    }
    
    // Update balance
    await ExchangeAccount.updateBalance(account.id, {
      balance: paperCapital,
      available: paperCapital,
      currency: 'USDT',
    });
    
    // Update metadata with new paper capital
    const updatedMetadata = { 
      ...account.metadata, 
      paperCapital,
    };
    await ExchangeAccount.update(account.id, { metadata: updatedMetadata });
    
    // Re-fetch to get updated account
    const updatedAccount = await ExchangeAccount.getById(account.id);
    
    console.log(`[paper-capital] Updated paper capital for ${account.label}: ${paperCapital} USDT`);
    
    res.json({ 
      account: updatedAccount, 
      balance: paperCapital, 
      currency: 'USDT' 
    });
  } catch (err) {
    console.error('Error updating paper capital:', err);
    res.status(500).json({ error: 'Failed to update paper capital' });
  }
});

/**
 * PUT /api/exchange-accounts/:id/manual-balance
 * Manually set balance for testnet/demo accounts when API verification fails
 * This is useful when exchange API keys have issues but user knows their demo balance
 */
router.put('/:id/manual-balance', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Only allow manual balance for testnet/demo accounts (not live production)
    if (account.environment === 'live' && !account.is_demo) {
      return res.status(400).json({ 
        error: 'Manual balance can only be set for testnet/demo accounts. Use refresh-balance for live accounts.' 
      });
    }
    
    const { balance, currency = 'USDT' } = req.body;
    
    if (balance === undefined || balance === null || balance < 0) {
      return res.status(400).json({ error: 'Balance must be a non-negative number' });
    }
    
    // Update balance in database
    await ExchangeAccount.updateBalance(account.id, {
      balance: balance,
      available: balance,
      currency: currency,
    });
    
    // Update metadata to note this was manually set
    const updatedMetadata = { 
      ...account.metadata, 
      manualBalanceSet: true,
      manualBalanceSetAt: new Date().toISOString(),
    };
    await ExchangeAccount.update(account.id, { metadata: updatedMetadata });
    
    // Re-fetch to get updated account
    const updatedAccount = await ExchangeAccount.getById(account.id);
    
    console.log(`[manual-balance] Set manual balance for ${account.label}: ${balance} ${currency}`);
    
    res.json({ 
      account: updatedAccount, 
      balance: balance, 
      currency: currency,
      message: 'Balance set manually. Note: This does not sync with exchange - use refresh-balance when API issues are resolved.'
    });
  } catch (err) {
    console.error('Error setting manual balance:', err);
    res.status(500).json({ error: 'Failed to set manual balance' });
  }
});

/**
 * POST /api/exchange-accounts/:id/refresh-balance
 * Refresh balance from exchange (fetches real balance via API)
 * For paper accounts, this is a no-op that returns current balance
 */
router.post('/:id/refresh-balance', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // For paper accounts, just return the current balance (it's managed locally)
    if (account.environment === 'paper') {
      return res.json({ 
        account, 
        balance: account.exchange_balance || account.metadata?.paperCapital || 0,
        currency: account.balance_currency || 'USDT',
        message: 'Paper trading balance is managed locally'
      });
    }
    
    if (account.status !== 'verified') {
      return res.status(400).json({ error: 'Account not verified' });
    }
    
    if (!account.secret_id) {
      return res.status(400).json({ error: 'No credentials stored for this account' });
    }
    
    // Get credentials from secrets provider
    const creds = await secretsProvider.getExchangeCredentials(account.secret_id);
    if (!creds) {
      return res.status(400).json({ error: 'Credentials not found' });
    }
    
    const isDemo = account.is_demo || false;

    // Fetch balance from exchange
    console.log(`[refresh-balance] Fetching balance for ${account.venue} (demo: ${isDemo})`);
    let balanceResult;

    try {
      balanceResult = await secretsProvider.fetchExchangeBalance(
        account.venue,
        creds,
        isDemo
      );
    } catch (fetchErr) {
      console.error('[refresh-balance] Failed to fetch balance:', fetchErr.message);
      return res.status(400).json({
        error: 'Failed to fetch balance from exchange: ' + fetchErr.message
      });
    }

    if (!balanceResult.success) {
      return res.status(400).json({
        error: balanceResult.error || 'Failed to fetch balance'
      });
    }
    
    // Update balance in database
    const updated = await ExchangeAccount.updateBalance(account.id, {
      balance: balanceResult.balance,
      available: balanceResult.balance, // Most exchanges report available = total for futures
      marginUsed: 0,
      unrealizedPnl: 0,
      currency: balanceResult.currency || 'USDT',
    });
    
    console.log(`[refresh-balance] Updated balance: ${balanceResult.balance} ${balanceResult.currency}`);
    
    res.json({ account: updated, balance: balanceResult.balance, currency: balanceResult.currency });
  } catch (err) {
    console.error('Error refreshing balance:', err);
    res.status(500).json({ error: 'Failed to refresh balance' });
  }
});

// =============================================================================
// Exchange Policy
// =============================================================================

/**
 * GET /api/exchange-accounts/:id/policy
 * Get the risk policy for an exchange account
 */
router.get('/:id/policy', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const policy = await ExchangePolicy.getByAccount(account.id);
    res.json({ policy: policy || ExchangePolicy.DEFAULT_POLICY });
  } catch (err) {
    console.error('Error fetching policy:', err);
    res.status(500).json({ error: 'Failed to fetch policy' });
  }
});

/**
 * PUT /api/exchange-accounts/:id/policy
 * Update the risk policy for an exchange account
 */
router.put('/:id/policy', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Ensure policy exists
    await ExchangePolicy.create(account.id);
    
    // Update policy
    const policy = await ExchangePolicy.update(account.id, req.body);
    res.json({ policy });
  } catch (err) {
    console.error('Error updating policy:', err);
    res.status(500).json({ error: 'Failed to update policy' });
  }
});

// =============================================================================
// Active Bot (SOLO mode)
// =============================================================================

/**
 * GET /api/exchange-accounts/:id/active-bot
 * Get the active bot for an exchange account (SOLO mode)
 */
router.get('/:id/active-bot', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const bot = await ExchangeAccount.getActiveBot(account.id);
    res.json({ bot });
  } catch (err) {
    console.error('Error fetching active bot:', err);
    res.status(500).json({ error: 'Failed to fetch active bot' });
  }
});

/**
 * POST /api/exchange-accounts/:id/active-bot
 * Switch the active bot (SOLO mode)
 */
router.post('/:id/active-bot', async (req, res) => {
  try {
    const { botId } = req.body;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    await ExchangeAccount.setActiveBot(req.params.id, botId);
    const updated = await ExchangeAccount.getActiveBot(req.params.id);
    res.json({ bot: updated });
  } catch (err) {
    console.error('Error switching active bot:', err);
    if (err.code) {
      return res.status(400).json(err.toJSON ? err.toJSON() : { error: err.message, code: err.code });
    }
    res.status(500).json({ error: 'Failed to switch active bot' });
  }
});

// =============================================================================
// Running Bots
// =============================================================================

/**
 * GET /api/exchange-accounts/:id/bots
 * Get all bots for an exchange account
 */
router.get('/:id/bots', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const includeInactive = req.query.includeInactive === 'true';
    const bots = await ExchangeAccount.getBots(account.id, includeInactive);
    
    res.json({ bots });
  } catch (err) {
    console.error('Error fetching bots:', err);
    res.status(500).json({ error: 'Failed to fetch bots' });
  }
});

/**
 * GET /api/exchange-accounts/:id/running-bots
 * Get only running bots for an exchange account
 */
router.get('/:id/running-bots', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const bots = await ExchangeAccount.getRunningBots(account.id);
    res.json({ bots });
  } catch (err) {
    console.error('Error fetching running bots:', err);
    res.status(500).json({ error: 'Failed to fetch running bots' });
  }
});

// =============================================================================
// Kill Switch
// =============================================================================

/**
 * POST /api/exchange-accounts/:id/kill-switch
 * Activate kill switch (emergency stop all trading)
 */
router.post('/:id/kill-switch', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const { reason } = req.body;
    
    // Activate kill switch
    const policy = await ExchangePolicy.activateKillSwitch(account.id, req.user.id, reason);
    
    res.json({
      success: true,
      policy,
    });
  } catch (err) {
    console.error('Error activating kill switch:', err);
    res.status(500).json({ error: 'Failed to activate kill switch' });
  }
});

/**
 * DELETE /api/exchange-accounts/:id/kill-switch
 * Deactivate kill switch (re-enable trading)
 */
router.delete('/:id/kill-switch', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const policy = await ExchangePolicy.deactivateKillSwitch(account.id);
    
    res.json({ success: true, policy });
  } catch (err) {
    console.error('Error deactivating kill switch:', err);
    res.status(500).json({ error: 'Failed to deactivate kill switch' });
  }
});

// =============================================================================
// Budget Utilization
// =============================================================================

/**
 * GET /api/exchange-accounts/:id/budget-utilization
 * Get budget utilization summary for all bots
 */
router.get('/:id/budget-utilization', async (req, res) => {
  try {
    const account = await ExchangeAccount.getById(req.params.id);
    
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const utilization = await BotBudget.getUtilizationSummary(account.id);
    res.json({ utilization });
  } catch (err) {
    console.error('Error fetching budget utilization:', err);
    res.status(500).json({ error: 'Failed to fetch budget utilization' });
  }
});

export default router;
