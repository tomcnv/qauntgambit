import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import {
  getBotInstancesByUser,
  getBotInstanceById,
  getBotInstanceWithConfigs,
  createBotInstance,
  updateBotInstance,
  deleteBotInstance,
  DEFAULT_RISK_CONFIG,
  DEFAULT_EXECUTION_CONFIG,
} from '../models/BotInstance.js';
import { getConfigsByBotInstance } from '../models/BotExchangeConfig.js';
import pool from '../config/database.js';

const router = express.Router();
router.use(authenticateToken);

/**
 * GET /api/bot-instances
 * List all bot instances with their exchange configs
 */
router.get('/', async (req, res) => {
  try {
    const includeInactive = req.query.includeInactive === 'true';
    const bots = await getBotInstancesByUser(req.user.id, includeInactive);

    // Attach exchange configs to each bot
    const botsWithConfigs = await Promise.all(
      bots.map(async (bot) => {
        const configs = await getConfigsByBotInstance(bot.id);
        return { ...bot, exchangeConfigs: configs };
      })
    );

    res.json({ bots: botsWithConfigs });
  } catch (err) {
    console.error('Error fetching bot instances:', err);
    res.status(500).json({ error: 'Failed to fetch bot instances' });
  }
});

/**
 * GET /api/bot-instances/templates
 * List strategy templates
 */
router.get('/templates', async (req, res) => {
  try {
    const result = await pool.query(
      `SELECT * FROM strategy_templates WHERE is_active = true ORDER BY sort_order, name`
    );
    res.json({ templates: result.rows });
  } catch (err) {
    console.error('Error fetching templates:', err);
    res.status(500).json({ error: 'Failed to fetch templates' });
  }
});

/**
 * GET /api/bot-instances/templates/:templateId
 */
router.get('/templates/:templateId', async (req, res) => {
  try {
    const result = await pool.query(
      `SELECT * FROM strategy_templates WHERE id = $1`,
      [req.params.templateId]
    );
    if (!result.rows[0]) return res.status(404).json({ error: 'Template not found' });
    res.json({ template: result.rows[0] });
  } catch (err) {
    console.error('Error fetching template:', err);
    res.status(500).json({ error: 'Failed to fetch template' });
  }
});

/**
 * GET /api/bot-instances/:botId
 */
router.get('/:botId', async (req, res) => {
  try {
    const bot = await getBotInstanceWithConfigs(req.params.botId, req.user.id);
    if (!bot) return res.status(404).json({ error: 'Bot not found' });
    res.json({ bot });
  } catch (err) {
    console.error('Error fetching bot instance:', err);
    res.status(500).json({ error: 'Failed to fetch bot instance' });
  }
});

/**
 * POST /api/bot-instances
 */
router.post('/', async (req, res) => {
  try {
    const bot = await createBotInstance(req.user.id, {
      name: req.body.name,
      description: req.body.description,
      strategyTemplateId: req.body.strategyTemplateId,
      allocatorRole: req.body.allocatorRole || 'core',
      marketType: req.body.marketType || 'perp',
      defaultRiskConfig: req.body.defaultRiskConfig || DEFAULT_RISK_CONFIG,
      defaultExecutionConfig: req.body.defaultExecutionConfig || DEFAULT_EXECUTION_CONFIG,
      profileOverrides: req.body.profileOverrides || {},
      tags: req.body.tags || [],
      metadata: req.body.metadata || {},
    });
    res.status(201).json({ bot });
  } catch (err) {
    console.error('Error creating bot instance:', err);
    res.status(500).json({ error: 'Failed to create bot instance' });
  }
});

/**
 * PATCH /api/bot-instances/:botId
 */
router.patch('/:botId', async (req, res) => {
  try {
    const bot = await updateBotInstance(req.params.botId, req.user.id, req.body);
    if (!bot) return res.status(404).json({ error: 'Bot not found' });
    res.json({ bot });
  } catch (err) {
    console.error('Error updating bot instance:', err);
    res.status(500).json({ error: 'Failed to update bot instance' });
  }
});

/**
 * DELETE /api/bot-instances/:botId
 */
router.delete('/:botId', async (req, res) => {
  try {
    const bot = await deleteBotInstance(req.params.botId, req.user.id);
    if (!bot) return res.status(404).json({ error: 'Bot not found' });
    res.json({ success: true });
  } catch (err) {
    console.error('Error deleting bot instance:', err);
    res.status(500).json({ error: 'Failed to delete bot instance' });
  }
});

export default router;
