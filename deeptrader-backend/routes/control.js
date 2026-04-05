import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import { enqueueCommand, fetchCommandResults, buildCommandStreams, getStartLockState, clearCommandStream, clearStartLock } from '../services/controlQueueService.js';
import BotInstance from '../models/BotInstance.js';
import * as BotExchangeConfig from '../models/BotExchangeConfig.js';
import * as ExchangeAccount from '../models/ExchangeAccount.js';
import guardianOrchestrator from '../services/guardianOrchestrator.js';

const router = express.Router();

router.use(authenticateToken);

const resolveRuntimeStreams = (exchange, marketType = 'perp') => {
  // Each exchange gets its own suffixed streams to prevent data mixing
  // MDS instances publish to exchange-specific streams (e.g., events:trades:binance)
  const normalizedExchange = (exchange || '').toLowerCase();
  const normalizedMarketType = (marketType || 'perp').toLowerCase();
  const suffix = normalizedExchange
    ? normalizedMarketType === 'spot'
      ? `:${normalizedExchange}:spot`
      : `:${normalizedExchange}`
    : '';
  return {
    orderbook: `events:orderbook_feed${suffix}`,
    trades: `events:trades${suffix}`,
    market: `events:market_data${suffix}`,
  };
};

const normalizeSymbolsForExchange = (exchange, symbols) => {
  if (!Array.isArray(symbols)) return symbols;
  return symbols.map((symbol) => {
    if (!symbol || typeof symbol !== 'string') return symbol;
    const cleaned = symbol.toUpperCase().split(':')[0].replace(/\//g, '-');
    if (exchange === 'okx') {
      if (cleaned.endsWith('-SWAP')) return cleaned;
      return cleaned.includes('-') ? `${cleaned}-SWAP` : cleaned;
    }
    return cleaned.replace(/-SWAP$/i, '').replace(/-(PERP|PERPETUAL|FUTURES)$/i, '').replace(/-/g, '');
  });
};

const normalizeTradingMode = (environment) => {
  if (!environment) return 'paper';
  return environment === 'live' ? 'live' : 'paper';
};

const buildRuntimeHints = async ({ tenantId, exchangeAccountId }) => {
  const exchangeAccount = exchangeAccountId ? await ExchangeAccount.getById(exchangeAccountId) : null;
  if (!exchangeAccount || exchangeAccount.tenant_id !== tenantId) {
    const err = new Error('exchange_account_not_found');
    err.status = 404;
    throw err;
  }
  const exchange = exchangeAccount.venue;
  const runtimeProcess = exchange === 'binance' ? 'quantgambit-runtime-binance' : 'quantgambit-runtime';
  return {
    runtime_process: runtimeProcess,
    runtime_stop_cmd: `pm2 stop ${runtimeProcess}`,
  };
};

const buildRuntimeEnvPrefix = (payload) => {
  const entries = {
    TENANT_ID: payload.tenant_id,
    BOT_ID: payload.bot_id,
    ACTIVE_EXCHANGE: payload.exchange,
    TRADING_MODE: payload.trading_mode,
    THROTTLE_MODE: payload.throttle_mode,
    MARKET_TYPE: payload.market_type,
    MARGIN_MODE: payload.margin_mode,
    ORDERBOOK_SYMBOLS: Array.isArray(payload.enabled_symbols) ? payload.enabled_symbols.join(',') : undefined,
    ORDERBOOK_EVENT_STREAM: payload.streams?.orderbook,
    TRADE_STREAM: payload.streams?.trades,
    MARKET_DATA_STREAM: payload.streams?.market,
    ORDERBOOK_TESTNET: payload.is_testnet ? 'true' : 'false',
    TRADE_TESTNET: payload.is_testnet ? 'true' : 'false',
  };
  return Object.entries(entries)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${value}`)
    .join(' ');
};

const buildStartPayload = async ({ tenantId, botId, exchangeAccountId }) => {
  const bot = await BotInstance.getBotInstanceById(botId, tenantId);
  if (!bot) {
    const err = new Error('bot_not_found');
    err.status = 404;
    throw err;
  }

  const exchangeAccount = exchangeAccountId ? await ExchangeAccount.getById(exchangeAccountId) : null;
  if (!exchangeAccount || exchangeAccount.tenant_id !== tenantId) {
    const err = new Error('exchange_account_not_found');
    err.status = 404;
    throw err;
  }

  const configs = await BotExchangeConfig.getConfigsByBotInstance(botId);
  const matched = configs.find((config) => config.exchange_account_id === exchangeAccountId);
  if (!matched) {
    const err = new Error('bot_exchange_config_missing');
    err.status = 400;
    throw err;
  }

  const exchange = exchangeAccount.venue || matched.exchange;
  const environment = matched.environment || exchangeAccount.environment || 'paper';
  const tradingMode = bot.trading_mode || normalizeTradingMode(environment);
  const isTestnet = exchangeAccount.is_testnet ?? matched.is_testnet ?? false;
  const isDemo = exchangeAccount.is_demo ?? false;
  const enabledSymbols = Array.isArray(matched.enabled_symbols) && matched.enabled_symbols.length
    ? matched.enabled_symbols
    : Array.isArray(bot.enabled_symbols) && bot.enabled_symbols.length
      ? bot.enabled_symbols
      : [];
  const normalizedSymbols = normalizeSymbolsForExchange(exchange, enabledSymbols);
  const metadata = matched.metadata || {};
  const marketType = (
    metadata.market_type ||
    metadata.marketType ||
    bot.market_type ||
    'perp'
  ).toLowerCase();
  const marginMode = metadata.margin_mode || metadata.marginMode || 'isolated';
  const streams = resolveRuntimeStreams(exchange, marketType);
  const runtimeProcess = exchange === 'binance' ? 'quantgambit-runtime-binance' : 'quantgambit-runtime';
  const executionProvider = tradingMode === 'live' ? 'ccxt' : 'none';
  const orderbookSource = 'external';
  const tradeSource = 'external';
  const marketDataProvider = 'ccxt';
  const profileOverrides = matched.profile_overrides || bot.profile_overrides || {};
  const envFile = marketType === 'spot'
    ? '.env.spot'
    : tradingMode === 'live'
      ? '.env.runtime-live'
      : '.env';
  const botType = String(profileOverrides?.bot_type || '').toLowerCase();
  const aiProvider = String(profileOverrides?.ai_provider || '').toLowerCase();
  const isAiSpotSwing = botType === 'ai_spot_swing' || ['deepseek_context', 'context_model', 'ai_spot_swing'].includes(aiProvider);
  const runtimeEnv = {
    ENV_FILE: envFile,
  };
  if (Object.keys(profileOverrides || {}).length > 0) {
    runtimeEnv.PROFILE_OVERRIDES = JSON.stringify(profileOverrides);
  }
  if (isAiSpotSwing) {
    runtimeEnv.PREDICTION_PROVIDER = aiProvider || 'deepseek_context';
    runtimeEnv.PREDICTION_MODEL_PATH = '';
    runtimeEnv.PREDICTION_MODEL_CONFIG = '';
    runtimeEnv.PREDICTION_MODEL_FEATURES = '';
    runtimeEnv.PREDICTION_MODEL_CLASSES = '';
    if (profileOverrides?.ai_confidence_floor !== undefined && profileOverrides?.ai_confidence_floor !== null) {
      runtimeEnv.AI_PROVIDER_MIN_CONFIDENCE = String(profileOverrides.ai_confidence_floor);
    }
    if (profileOverrides?.ai_require_baseline_alignment !== undefined) {
      runtimeEnv.AI_PROVIDER_REQUIRE_BASELINE_ALIGNMENT = profileOverrides.ai_require_baseline_alignment ? 'true' : 'false';
    }
    if (profileOverrides?.ai_sentiment_required !== undefined) {
      runtimeEnv.AI_SENTIMENT_REQUIRED = profileOverrides.ai_sentiment_required ? 'true' : 'false';
    }
    if (profileOverrides?.ai_shadow_mode !== undefined) {
      runtimeEnv.AI_SHADOW_ONLY = profileOverrides.ai_shadow_mode ? 'true' : 'false';
    }
    if (Array.isArray(profileOverrides?.ai_sessions) && profileOverrides.ai_sessions.length) {
      runtimeEnv.AI_ENABLED_SESSIONS = profileOverrides.ai_sessions.join(',');
    }
  }

  // Determine trading capital - priority: bot config > exchange account trading capital > exchange balance
  const tradingCapitalUsd = matched.trading_capital_usd 
    ? parseFloat(matched.trading_capital_usd)
    : exchangeAccount.trading_capital
      ? parseFloat(exchangeAccount.trading_capital)
      : exchangeAccount.exchange_balance 
        ? parseFloat(exchangeAccount.exchange_balance)
        : null;

  const payload = {
    tenant_id: tenantId,
    bot_id: botId,
    exchange_account_id: exchangeAccountId,
    exchange,
    environment,
    trading_mode: tradingMode,
    is_testnet: isTestnet,
    is_demo: isDemo,
    market_type: marketType,
    margin_mode: marginMode,
    execution_provider: executionProvider,
    orderbook_source: orderbookSource,
    trade_source: tradeSource,
    market_data_provider: marketDataProvider,
    enabled_symbols: normalizedSymbols,
    trading_capital_usd: tradingCapitalUsd,  // User's configured trading capital
    risk_config: matched.risk_config || bot.default_risk_config || {},
    execution_config: matched.execution_config || bot.default_execution_config || {},
    throttle_mode: (matched.execution_config?.throttleMode || bot.default_execution_config?.throttleMode || 'swing'),
    profile_overrides: profileOverrides,
    config_version: matched.config_version || null,
    runtime_env: runtimeEnv,
    exchange_account: {
      id: exchangeAccount.id,
      label: exchangeAccount.label,
      venue: exchangeAccount.venue,
      environment: exchangeAccount.environment,
      is_testnet: exchangeAccount.is_testnet,
      is_demo: exchangeAccount.is_demo,
      secret_id: exchangeAccount.secret_id, // For runtime to fetch credentials securely
      exchange_balance: exchangeAccount.exchange_balance ? parseFloat(exchangeAccount.exchange_balance) : null,
      available_balance: exchangeAccount.available_balance ? parseFloat(exchangeAccount.available_balance) : null,
      balance_currency: exchangeAccount.balance_currency || 'USDT',
      trading_capital: tradingCapitalUsd,  // Also include in exchange_account for redundancy
    },
    bot: {
      id: bot.id,
      name: bot.name,
      allocator_role: bot.allocator_role,
      trading_mode: bot.trading_mode || null,
      default_risk_config: bot.default_risk_config || {},
      default_execution_config: bot.default_execution_config || {},
    },
    streams,
    runtime_process: runtimeProcess,
    runtime_launch_cmd: `pm2 restart ${runtimeProcess} --update-env`,
    runtime_stop_cmd: `pm2 stop ${runtimeProcess}`,
  };
  
  // Log key fields for debugging
  console.log('[Control] buildStartPayload:', {
    exchange: payload.exchange,
    is_testnet: payload.is_testnet,
    is_demo: payload.is_demo,
    trading_mode: payload.trading_mode,
    exchange_account_is_demo: payload.exchange_account?.is_demo,
  });
  
  const envPrefix = buildRuntimeEnvPrefix(payload);
  if (envPrefix) {
    payload.runtime_launch_cmd = `${envPrefix} ${payload.runtime_launch_cmd}`;
  }
  return payload;
};

router.post('/command', async (req, res) => {
  try {
    const { type, tenantId, botId, reason, payload, requestedBy, exchangeAccountId, exchange_account_id } = req.body || {};
    if (!type) {
      return res.status(400).json({ error: 'type_required' });
    }
    if (!botId) {
      return res.status(400).json({ error: 'bot_id_required' });
    }
    const scopedTenantId = req.user?.id;
    if (!scopedTenantId) {
      return res.status(401).json({ error: 'tenant_id_required' });
    }
    if (tenantId && tenantId !== scopedTenantId) {
      return res.status(403).json({ error: 'tenant_mismatch' });
    }

    let fullPayload = payload || null;
    const accountId = exchangeAccountId || exchange_account_id || payload?.exchangeAccountId || payload?.exchange_account_id;
    if (type === 'start_bot') {
      if (!accountId) {
        return res.status(400).json({ error: 'exchange_account_id_required' });
      }
      fullPayload = await buildStartPayload({
        tenantId: scopedTenantId,
        botId,
        exchangeAccountId: accountId,
      });
    } else if (accountId) {
      fullPayload = await buildRuntimeHints({ tenantId: scopedTenantId, exchangeAccountId: accountId });
    }

    const { commandId, stream } = await enqueueCommand({
      type,
      tenantId: scopedTenantId,
      botId,
      reason,
      payload: fullPayload,
      requestedBy,
    });

    // Update active_bot_id on exchange account when starting/stopping
    if (type === 'start_bot' && accountId) {
      // Set this bot as the active bot for the exchange account
      ExchangeAccount.setActiveBot(accountId, botId).catch(err => {
        console.error('[Control] Failed to set active bot:', err.message);
      });
    } else if (type === 'stop_bot' && accountId) {
      // Clear the active bot when stopping
      ExchangeAccount.clearActiveBot(accountId).catch(err => {
        console.error('[Control] Failed to clear active bot:', err.message);
      });
    }

    // Orchestrate guardian for live trading bots
    if (type === 'start_bot' && fullPayload?.trading_mode === 'live') {
      // Fire and forget - don't block the response
      guardianOrchestrator.orchestrateGuardian(scopedTenantId, 'bot_start').catch(err => {
        console.error('[Control] Guardian orchestration error:', err.message);
      });
    } else if (type === 'stop_bot') {
      // Check if guardian still needed after this bot stops
      guardianOrchestrator.orchestrateGuardian(scopedTenantId, 'bot_stop').catch(err => {
        console.error('[Control] Guardian orchestration error:', err.message);
      });
    }

    const { resultStream } = buildCommandStreams({ tenantId: scopedTenantId, botId });
    return res.json({
      commandId,
      status: 'queued',
      commandStream: stream,
      resultStream,
    });
  } catch (error) {
    const message = error.message || 'enqueue_failed';
    const status = message.includes('start_in_progress') ? 409 : message.includes('bot_already_running') ? 409 : error.status || 500;
    return res.status(status).json({ error: message });
  }
});

router.get('/command-results', async (req, res) => {
  try {
    const { tenantId, botId, commandId, limit } = req.query || {};
    const scopedTenantId = req.user?.id;
    if (!botId) {
      return res.status(400).json({ error: 'bot_id_required' });
    }
    if (!scopedTenantId) {
      return res.status(401).json({ error: 'tenant_id_required' });
    }
    if (tenantId && tenantId !== scopedTenantId) {
      return res.status(403).json({ error: 'tenant_mismatch' });
    }
    const results = await fetchCommandResults({
      tenantId: scopedTenantId,
      botId,
      commandId,
      limit: limit ? Number(limit) : 20,
    });
    return res.json({ results });
  } catch (error) {
    return res.status(500).json({ error: error.message || 'fetch_failed' });
  }
});

router.get('/status', async (req, res) => {
  try {
    const { tenantId, botId } = req.query || {};
    if (!botId) return res.status(400).json({ error: 'bot_id_required' });
    const scopedTenantId = req.user?.id;
    if (!scopedTenantId) {
      return res.status(401).json({ error: 'tenant_id_required' });
    }
    if (tenantId && tenantId !== scopedTenantId) {
      return res.status(403).json({ error: 'tenant_mismatch' });
    }
    const lock = await getStartLockState(scopedTenantId, botId);
    return res.json({ startLock: lock });
  } catch (error) {
    return res.status(500).json({ error: error.message || 'status_failed' });
  }
});

// Admin endpoint to clear queued commands for a bot
router.post('/clear-queue', async (req, res) => {
  try {
    const { tenantId, botId } = req.body || {};
    if (!botId) return res.status(400).json({ error: 'bot_id_required' });
    await clearCommandStream(tenantId, botId);
    await clearStartLock(tenantId, botId);
    return res.json({ cleared: true });
  } catch (error) {
    return res.status(500).json({ error: error.message || 'clear_failed' });
  }
});

// ═══════════════════════════════════════════════════════════════
// Position Guardian Management
// ═══════════════════════════════════════════════════════════════

/**
 * GET /api/control/guardian/status
 * Get guardian status for the authenticated tenant
 */
router.get('/guardian/status', async (req, res) => {
  try {
    const tenantId = req.user?.id;
    if (!tenantId) {
      return res.status(401).json({ error: 'unauthorized' });
    }
    
    const status = await guardianOrchestrator.getGuardianStatus(tenantId);
    return res.json(status);
  } catch (error) {
    console.error('[Control] Guardian status error:', error);
    return res.status(500).json({ error: error.message || 'status_failed' });
  }
});

/**
 * POST /api/control/guardian/start
 * Manually start guardian for tenant (if they have live bots)
 */
router.post('/guardian/start', async (req, res) => {
  try {
    const tenantId = req.user?.id;
    if (!tenantId) {
      return res.status(401).json({ error: 'unauthorized' });
    }
    
    const result = await guardianOrchestrator.orchestrateGuardian(tenantId, 'manual_start');
    return res.json(result);
  } catch (error) {
    console.error('[Control] Guardian start error:', error);
    return res.status(500).json({ error: error.message || 'start_failed' });
  }
});

/**
 * POST /api/control/guardian/stop
 * Manually stop guardian for tenant
 */
router.post('/guardian/stop', async (req, res) => {
  try {
    const tenantId = req.user?.id;
    if (!tenantId) {
      return res.status(401).json({ error: 'unauthorized' });
    }
    
    await guardianOrchestrator.stopGuardian(tenantId);
    return res.json({ stopped: true });
  } catch (error) {
    console.error('[Control] Guardian stop error:', error);
    return res.status(500).json({ error: error.message || 'stop_failed' });
  }
});

export default router;
