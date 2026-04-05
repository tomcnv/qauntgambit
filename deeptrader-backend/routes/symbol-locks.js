/**
 * Symbol Locks Routes
 * 
 * For TEAM/PROP modes: manage symbol ownership locks.
 * Each symbol can only be traded by one bot at a time.
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import SymbolLock from '../models/SymbolLock.js';
import ExchangeAccount from '../models/ExchangeAccount.js';
import pool from '../config/database.js';

const router = express.Router();

// All routes require authentication
router.use(authenticateToken);

/**
 * GET /api/symbol-locks
 * Query symbol locks for an exchange account
 */
router.get('/', async (req, res) => {
  try {
    const { exchangeAccountId, environment, symbol, botId } = req.query;
    
    if (!exchangeAccountId) {
      return res.status(400).json({ error: 'exchangeAccountId is required' });
    }
    
    // Verify ownership
    const account = await ExchangeAccount.getById(exchangeAccountId);
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Check operating mode
    const tenant = await getTenant(req.user.id);
    if (tenant.operating_mode === 'solo') {
      return res.json({
        locks: [],
        message: 'Symbol locks are not used in SOLO mode',
      });
    }
    
    let locks;
    
    if (symbol) {
      // Get specific symbol lock
      const lock = await SymbolLock.getBySymbol(exchangeAccountId, environment, symbol);
      locks = lock ? [lock] : [];
    } else if (botId) {
      // Get locks for a specific bot
      locks = await SymbolLock.getByBot(botId);
    } else {
      // Get all locks for the account
      locks = await SymbolLock.getByExchangeAccount(exchangeAccountId, environment);
    }
    
    res.json({ locks });
  } catch (err) {
    console.error('Error fetching symbol locks:', err);
    res.status(500).json({ error: 'Failed to fetch symbol locks' });
  }
});

/**
 * GET /api/symbol-locks/conflicts
 * Check for conflicts before starting a bot
 */
router.get('/conflicts', async (req, res) => {
  try {
    const { exchangeAccountId, environment, symbols, botId } = req.query;
    
    if (!exchangeAccountId || !environment || !symbols || !botId) {
      return res.status(400).json({
        error: 'exchangeAccountId, environment, symbols, and botId are required',
      });
    }
    
    // Verify ownership
    const account = await ExchangeAccount.getById(exchangeAccountId);
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Check operating mode
    const tenant = await getTenant(req.user.id);
    if (tenant.operating_mode === 'solo') {
      return res.json({
        conflicts: [],
        message: 'Symbol locks are not used in SOLO mode',
      });
    }
    
    // Parse symbols (can be comma-separated or array)
    const symbolList = Array.isArray(symbols) ? symbols : symbols.split(',');
    
    const conflicts = await SymbolLock.getConflicts(
      exchangeAccountId,
      environment,
      symbolList,
      botId
    );
    
    res.json({
      conflicts,
      hasConflicts: conflicts.length > 0,
    });
  } catch (err) {
    console.error('Error checking conflicts:', err);
    res.status(500).json({ error: 'Failed to check conflicts' });
  }
});

/**
 * POST /api/symbol-locks/acquire
 * Manually acquire symbol locks for a bot
 */
router.post('/acquire', async (req, res) => {
  try {
    const { exchangeAccountId, environment, symbols, botId } = req.body;
    
    if (!exchangeAccountId || !environment || !symbols || !botId) {
      return res.status(400).json({
        error: 'exchangeAccountId, environment, symbols, and botId are required',
      });
    }
    
    // Verify ownership
    const account = await ExchangeAccount.getById(exchangeAccountId);
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    // Verify bot belongs to user
    const bot = await getBotInstance(botId, req.user.id);
    if (!bot) {
      return res.status(404).json({ error: 'Bot not found' });
    }
    
    // Check operating mode
    const tenant = await getTenant(req.user.id);
    if (tenant.operating_mode === 'solo') {
      return res.status(400).json({
        error: 'Symbol locks are not used in SOLO mode',
      });
    }
    
    // Acquire locks
    const results = await SymbolLock.acquireMany(exchangeAccountId, environment, symbols, botId);
    
    const acquired = results.filter(r => r.acquired);
    const failed = results.filter(r => !r.acquired);
    
    res.json({
      results,
      acquired: acquired.map(r => r.symbol),
      failed: failed.map(r => ({
        symbol: r.symbol,
        ownerBotId: r.owner_bot_id,
        ownerBotName: r.owner_bot_name,
      })),
      allAcquired: failed.length === 0,
    });
  } catch (err) {
    console.error('Error acquiring locks:', err);
    res.status(500).json({ error: 'Failed to acquire locks' });
  }
});

/**
 * POST /api/symbol-locks/release
 * Release symbol locks for a bot
 */
router.post('/release', async (req, res) => {
  try {
    const { botId, symbols } = req.body;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    // Verify bot belongs to user
    const bot = await getBotInstance(botId, req.user.id);
    if (!bot) {
      return res.status(404).json({ error: 'Bot not found' });
    }
    
    let released;
    
    if (symbols && symbols.length > 0) {
      // Release specific symbols
      released = await SymbolLock.releaseSymbols(botId, symbols);
    } else {
      // Release all locks for this bot
      released = await SymbolLock.releaseByBot(botId);
    }
    
    res.json({
      success: true,
      released: released.map(l => l.symbol),
    });
  } catch (err) {
    console.error('Error releasing locks:', err);
    res.status(500).json({ error: 'Failed to release locks' });
  }
});

/**
 * POST /api/symbol-locks/heartbeat
 * Update heartbeat for a bot's locks
 */
router.post('/heartbeat', async (req, res) => {
  try {
    const { botId } = req.body;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    // Verify bot belongs to user
    const bot = await getBotInstance(botId, req.user.id);
    if (!bot) {
      return res.status(404).json({ error: 'Bot not found' });
    }
    
    const locks = await SymbolLock.heartbeat(botId);
    
    res.json({
      success: true,
      locksUpdated: locks.length,
    });
  } catch (err) {
    console.error('Error updating heartbeat:', err);
    res.status(500).json({ error: 'Failed to update heartbeat' });
  }
});

/**
 * GET /api/symbol-locks/summary
 * Get lock summary per bot for an account
 */
router.get('/summary', async (req, res) => {
  try {
    const { exchangeAccountId, environment } = req.query;
    
    if (!exchangeAccountId) {
      return res.status(400).json({ error: 'exchangeAccountId is required' });
    }
    
    // Verify ownership
    const account = await ExchangeAccount.getById(exchangeAccountId);
    if (!account || account.tenant_id !== req.user.id) {
      return res.status(404).json({ error: 'Exchange account not found' });
    }
    
    const summary = await SymbolLock.getLockSummary(exchangeAccountId, environment);
    
    res.json({ summary });
  } catch (err) {
    console.error('Error fetching lock summary:', err);
    res.status(500).json({ error: 'Failed to fetch lock summary' });
  }
});

/**
 * DELETE /api/symbol-locks/expired
 * Clean up expired locks (admin/maintenance)
 */
router.delete('/expired', async (req, res) => {
  try {
    const cleaned = await SymbolLock.cleanupExpired();
    
    res.json({
      success: true,
      cleaned: cleaned.length,
      symbols: cleaned.map(l => l.symbol),
    });
  } catch (err) {
    console.error('Error cleaning up expired locks:', err);
    res.status(500).json({ error: 'Failed to cleanup expired locks' });
  }
});

// === Helper Functions ===

async function getTenant(tenantId) {
  const result = await pool.query(
    `SELECT * FROM users WHERE id = $1`,
    [tenantId]
  );
  return result.rows[0] || null;
}

async function getBotInstance(botId, userId) {
  const result = await pool.query(
    `SELECT * FROM bot_instances WHERE id = $1 AND user_id = $2`,
    [botId, userId]
  );
  return result.rows[0] || null;
}

export default router;







