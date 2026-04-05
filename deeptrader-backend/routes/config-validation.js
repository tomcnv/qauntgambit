/**
 * Bot Configuration Validation API Routes
 * 
 * Provides endpoints to validate bot configuration before starting.
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import configValidationService from '../services/configValidationService.js';
import pool from '../config/database.js';

const router = express.Router();

/**
 * POST /api/config-validation/validate
 * Validate a configuration object (doesn't need to be saved yet)
 */
router.post('/validate', authenticateToken, async (req, res) => {
  try {
    const config = req.body;
    
    if (!config) {
      return res.status(400).json({
        error: 'No configuration provided',
        valid: false
      });
    }
    
    const result = configValidationService.validateConfig(config);
    
    res.json(result);
  } catch (error) {
    console.error('Config validation error:', error);
    res.status(500).json({
      error: 'Validation failed',
      message: error.message
    });
  }
});

/**
 * GET /api/config-validation/bot/:botId
 * Validate a saved bot's configuration
 */
router.get('/bot/:botId', authenticateToken, async (req, res) => {
  try {
    const { botId } = req.params;
    const userId = req.user.id;
    
    // Fetch bot configuration from database
    const botQuery = await pool.query(`
      SELECT 
        bi.id,
        bi.name,
        bi.exchange_account_id,
        bi.trading_mode,
        bc.risk_config,
        bc.execution_config,
        bc.enabled_symbols,
        bc.trading_capital_usd,
        bc.version as config_version,
        ea.venue,
        ea.is_demo
      FROM bot_instances bi
      LEFT JOIN bot_configs bc ON bi.config_id = bc.id
      LEFT JOIN exchange_accounts ea ON bi.exchange_account_id = ea.id
      WHERE bi.id = $1 AND bi.user_id = $2
    `, [botId, userId]);
    
    if (botQuery.rows.length === 0) {
      return res.status(404).json({
        error: 'Bot not found',
        valid: false
      });
    }
    
    const bot = botQuery.rows[0];
    
    // Transform to validation format
    const config = {
      botId: bot.id,
      botName: bot.name,
      tradingMode: bot.trading_mode,
      venue: bot.venue,
      isTestnet: bot.is_demo,
      tradingCapitalUsd: bot.trading_capital_usd,
      enabledSymbols: bot.enabled_symbols || [],
      riskConfig: bot.risk_config || {},
      executionConfig: bot.execution_config || {}
    };
    
    const result = configValidationService.validateConfig(config);
    
    // Add bot info to result
    result.botId = botId;
    result.botName = bot.name;
    
    res.json(result);
  } catch (error) {
    console.error('Bot validation error:', error);
    res.status(500).json({
      error: 'Validation failed',
      message: error.message
    });
  }
});

/**
 * POST /api/config-validation/can-start/:botId
 * Pre-flight check before starting a bot
 * Returns simple pass/fail with detailed reason
 */
router.post('/can-start/:botId', authenticateToken, async (req, res) => {
  try {
    const { botId } = req.params;
    const userId = req.user.id;
    
    // Fetch bot configuration
    const botQuery = await pool.query(`
      SELECT 
        bi.id,
        bi.name,
        bi.exchange_account_id,
        bi.trading_mode,
        bi.status,
        bc.risk_config,
        bc.execution_config,
        bc.enabled_symbols,
        bc.trading_capital_usd,
        ea.venue,
        ea.is_demo,
        ea.api_key_set
      FROM bot_instances bi
      LEFT JOIN bot_configs bc ON bi.config_id = bc.id
      LEFT JOIN exchange_accounts ea ON bi.exchange_account_id = ea.id
      WHERE bi.id = $1 AND bi.user_id = $2
    `, [botId, userId]);
    
    if (botQuery.rows.length === 0) {
      return res.status(404).json({
        canStart: false,
        reason: 'Bot not found',
        errors: [{ message: 'Bot not found or you do not have permission' }]
      });
    }
    
    const bot = botQuery.rows[0];
    
    // Check if already running
    if (bot.status === 'running') {
      return res.json({
        canStart: false,
        reason: 'Bot is already running',
        errors: [{ 
          id: 'already_running',
          message: 'Bot is already running',
          suggestion: 'Stop the bot first before restarting'
        }]
      });
    }
    
    // Check exchange credentials for live trading
    if (bot.trading_mode === 'live' && !bot.api_key_set) {
      return res.json({
        canStart: false,
        reason: 'Exchange API credentials not configured',
        errors: [{
          id: 'no_credentials',
          message: 'Exchange API credentials not configured',
          detail: 'Live trading requires API keys from your exchange.',
          suggestion: 'Add your exchange API credentials in the Exchange Accounts section'
        }]
      });
    }
    
    // Transform to validation format
    const config = {
      botId: bot.id,
      botName: bot.name,
      tradingMode: bot.trading_mode,
      environment: bot.trading_mode,
      venue: bot.venue,
      isTestnet: bot.is_testnet,
      tradingCapitalUsd: bot.trading_capital_usd,
      enabledSymbols: bot.enabled_symbols || [],
      riskConfig: bot.risk_config || {},
      executionConfig: bot.execution_config || {}
    };
    
    // Run validation
    const validation = configValidationService.validateConfig(config);
    
    // Get suggested fixes if there are errors
    let suggestedFixes = null;
    if (!validation.valid) {
      suggestedFixes = configValidationService.getSuggestedFixes(config);
      
      // Set state to "blocked" and record the error reason
      try {
        await pool.query(`
          UPDATE bot_exchange_configs 
          SET state = 'blocked', 
              last_error = $1, 
              updated_at = NOW()
          WHERE bot_instance_id = $2
        `, [validation.summary || validation.errors[0]?.message, botId]);
        
        console.log(`🚫 Bot ${bot.name} (${botId}) blocked: ${validation.summary}`);
      } catch (dbError) {
        console.warn('Failed to update bot state to blocked:', dbError.message);
      }
    }
    
    res.json({
      canStart: validation.valid,
      reason: validation.valid ? 'Configuration valid' : validation.errors[0]?.message,
      botId,
      botName: bot.name,
      tradingMode: bot.trading_mode,
      errors: validation.errors,
      warnings: validation.warnings,
      info: validation.info,
      summary: validation.summary,
      suggestedFixes
    });
  } catch (error) {
    console.error('Pre-flight check error:', error);
    res.status(500).json({
      canStart: false,
      reason: 'Pre-flight check failed',
      errors: [{ message: error.message }]
    });
  }
});

/**
 * GET /api/config-validation/rules
 * Get list of all validation rules (for documentation)
 */
router.get('/rules', authenticateToken, (req, res) => {
  const rules = configValidationService.validationRules.map(rule => ({
    id: rule.id,
    name: rule.name
  }));
  
  res.json({
    rules,
    severityLevels: configValidationService.SEVERITY
  });
});

export default router;




