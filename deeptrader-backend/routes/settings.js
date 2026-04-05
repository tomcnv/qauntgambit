/**
 * Trading Settings API Routes
 * User-configurable AI trading preferences and order type settings
 */

import express from 'express';
import { authenticateToken, requireRole } from '../middleware/auth.js';
import UserTradingSettings from '../models/UserTradingSettings.js';
import {
  createUser,
  listViewerAccountsForParent,
  findViewerAccountById,
  updateViewerAccount,
} from '../models/User.js';
import redisState from '../services/redisState.js';
import crypto from 'crypto';
import speakeasy from 'speakeasy';
import qrcode from 'qrcode';

const router = express.Router();

// Simple helpers for user-scoped JSON settings stored in Redis
async function getUserSetting(userId, key, fallback) {
  return (await redisState.getUserJson(userId, key, fallback)) ?? fallback;
}

async function setUserSetting(userId, key, value) {
  await redisState.setUserJson(userId, key, value);
  return value;
}

const normalizePercent = (value) => {
  if (value === undefined || value === null) return value;
  const num = parseFloat(value);
  if (Number.isNaN(num)) return value;
  return num > 1 ? num / 100 : num;
};

const normalizePartialProfitLevels = (levels) => {
  if (!Array.isArray(levels)) return levels;
  return levels.map((level) => ({
    ...level,
    target: normalizePercent(level.target),
  }));
};

const normalizeTradingSettings = (settings) => {
  if (!settings || typeof settings !== 'object') return settings;
  const normalized = { ...settings };

  const percentFields = [
    'maxPositionSizePercent',
    'maxTotalExposurePercent',
    'scalpingTargetProfitPercent',
    'trailingStopActivationPercent',
    'trailingStopCallbackPercent',
    'trailingStopStepPercent',
    'liquidationBufferPercent',
    'marginCallThresholdPercent',
  ];

  for (const field of percentFields) {
    if (normalized[field] !== undefined) {
      normalized[field] = normalizePercent(normalized[field]);
    }
  }

  if (normalized.perTokenSettings && typeof normalized.perTokenSettings === 'object') {
    const next = { ...normalized.perTokenSettings };
    for (const [symbol, cfg] of Object.entries(next)) {
      if (!cfg || typeof cfg !== 'object') continue;
      next[symbol] = {
        ...cfg,
        positionSizePct: normalizePercent(cfg.positionSizePct),
      };
    }
    normalized.perTokenSettings = next;
  }

  if (normalized.orderTypeSettings && typeof normalized.orderTypeSettings === 'object') {
    const orderTypeSettings = { ...normalized.orderTypeSettings };
    if (orderTypeSettings.bracket) {
      orderTypeSettings.bracket = {
        ...orderTypeSettings.bracket,
        stop_loss_percent: normalizePercent(orderTypeSettings.bracket.stop_loss_percent),
        take_profit_percent: normalizePercent(orderTypeSettings.bracket.take_profit_percent),
      };
    }
    normalized.orderTypeSettings = orderTypeSettings;
  }

  if (normalized.partialProfitLevels) {
    normalized.partialProfitLevels = normalizePartialProfitLevels(normalized.partialProfitLevels);
  }

  return normalized;
};

/**
 * GET /api/settings/trading - Get user's trading settings
 */
router.get('/trading', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const settings = await UserTradingSettings.getSettings(userId);

    // Convert database format to API format (return ALL settings)
    const response = {
      enabledOrderTypes: settings.enabled_order_types || [],
      orderTypeSettings: settings.order_type_settings || {},
      riskProfile: settings.risk_profile || 'moderate',
      maxConcurrentPositions: settings.max_concurrent_positions || 4,
      maxPositionSizePercent: normalizePercent(settings.max_position_size_percent) || 0.10,
      maxTotalExposurePercent: normalizePercent(settings.max_total_exposure_percent) || 0.40,
      aiConfidenceThreshold: parseFloat(settings.ai_confidence_threshold) || 7.0,
      tradingInterval: settings.trading_interval || 300000,
      enabledTokens: settings.enabled_tokens || ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'TAOUSDT'],
      perTokenSettings: settings.per_token_settings || {},
      // Advanced features - main toggles
      dayTradingEnabled: settings.day_trading_enabled || false,
      scalpingMode: settings.scalping_mode || false,
      trailingStopsEnabled: settings.trailing_stops_enabled !== false,
      partialProfitsEnabled: settings.partial_profits_enabled !== false,
      timeBasedExitsEnabled: settings.time_based_exits_enabled !== false,
      multiTimeframeConfirmation: settings.multi_timeframe_confirmation || false,
      // Day Trading Mode settings
      dayTradingMaxHoldingHours: parseFloat(settings.day_trading_max_holding_hours) || 8.0,
      dayTradingStartTime: settings.day_trading_start_time || '09:30:00',
      dayTradingEndTime: settings.day_trading_end_time || '15:30:00',
      dayTradingForceCloseTime: settings.day_trading_force_close_time || '15:45:00',
      dayTradingDaysOnly: settings.day_trading_days_only || false,
      // Scalping Mode settings
      scalpingTargetProfitPercent: normalizePercent(settings.scalping_target_profit_percent) || 0.005,
      scalpingMaxHoldingMinutes: settings.scalping_max_holding_minutes || 15,
      scalpingMinVolumeMultiplier: parseFloat(settings.scalping_min_volume_multiplier) || 2.0,
      // Trailing Stops settings
      trailingStopActivationPercent: normalizePercent(settings.trailing_stop_activation_percent) || 0.02,
      trailingStopCallbackPercent: normalizePercent(settings.trailing_stop_callback_percent) || 0.01,
      trailingStopStepPercent: normalizePercent(settings.trailing_stop_step_percent) || 0.005,
      // Partial Profit Taking settings
      partialProfitLevels: normalizePartialProfitLevels(settings.partial_profit_levels) || [
        { percent: 25, target: 0.03 },
        { percent: 25, target: 0.05 },
        { percent: 25, target: 0.08 },
        { percent: 25, target: 0.12 }
      ],
      // Time-Based Exits settings
      timeExitMaxHoldingHours: parseFloat(settings.time_exit_max_holding_hours) || 24.0,
      timeExitBreakEvenHours: parseFloat(settings.time_exit_break_even_hours) || 4.0,
      timeExitWeekendClose: settings.time_exit_weekend_close !== false,
      // Multi-Timeframe Confirmation settings
      mtfRequiredTimeframes: settings.mtf_required_timeframes || ['15m', '1h', '4h'],
      mtfMinConfirmations: settings.mtf_min_confirmations || 2,
      mtfTrendAlignmentRequired: settings.mtf_trend_alignment_required !== false,
      // Leverage settings
      leverageEnabled: settings.leverage_enabled || false,
      maxLeverage: parseFloat(settings.max_leverage) || 1.0,
      leverageMode: settings.leverage_mode || 'isolated',
      liquidationBufferPercent: normalizePercent(settings.liquidation_buffer_percent) || 0.05,
      marginCallThresholdPercent: normalizePercent(settings.margin_call_threshold_percent) || 0.20,
      availableLeverageLevels: settings.available_leverage_levels || [1, 2, 3, 5, 10]
    };

    res.json(response);
  } catch (error) {
    console.error('Error fetching trading settings:', error);
    res.status(500).json({ message: 'Failed to fetch trading settings', error: error.message });
  }
});

/**
 * GET /api/settings/account - Get tenant/account preferences
 */
router.get('/account', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const defaults = {
      orgName: 'veloxio Ops',
      timezone: 'UTC',
      baseCurrency: 'USD',
      language: 'en',
    };
    const account = await getUserSetting(userId, 'settings_account', defaults);
    res.json(account);
  } catch (error) {
    console.error('Error fetching account settings:', error);
    res.status(500).json({ message: 'Failed to fetch account settings', error: error.message });
  }
});

/**
 * PUT /api/settings/account - Update tenant/account preferences
 */
router.put('/account', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { orgName, timezone, baseCurrency, language } = req.body || {};

    if (orgName !== undefined && (typeof orgName !== 'string' || !orgName.trim())) {
      return res.status(400).json({ message: 'orgName must be a non-empty string' });
    }
    if (timezone !== undefined && typeof timezone !== 'string') {
      return res.status(400).json({ message: 'timezone must be a string' });
    }
    if (baseCurrency !== undefined && typeof baseCurrency !== 'string') {
      return res.status(400).json({ message: 'baseCurrency must be a string' });
    }
    if (language !== undefined && typeof language !== 'string') {
      return res.status(400).json({ message: 'language must be a string' });
    }

    const existing = await getUserSetting(userId, 'settings_account', {});
    const updated = {
      ...existing,
      ...(orgName !== undefined ? { orgName } : {}),
      ...(timezone !== undefined ? { timezone } : {}),
      ...(baseCurrency !== undefined ? { baseCurrency } : {}),
      ...(language !== undefined ? { language } : {}),
    };

    await setUserSetting(userId, 'settings_account', updated);
    res.json(updated);
  } catch (error) {
    console.error('Error updating account settings:', error);
    res.status(500).json({ message: 'Failed to update account settings', error: error.message });
  }
});

function buildViewerScope(payload = {}) {
  const botId = payload.botId ? String(payload.botId).trim() : '';
  const exchangeAccountId = payload.exchangeAccountId ? String(payload.exchangeAccountId).trim() : '';
  if (!botId || !exchangeAccountId) {
    throw new Error('botId and exchangeAccountId are required');
  }
  return {
    botId,
    botName: payload.botName ? String(payload.botName).trim() : null,
    exchangeAccountId,
    exchangeAccountName: payload.exchangeAccountName ? String(payload.exchangeAccountName).trim() : null,
    allowedBotIds: [botId],
  };
}

function serializeViewer(user) {
  return {
    id: user.id,
    tenantId: user.tenantId,
    parentUserId: user.parentUserId,
    email: user.email,
    username: user.username,
    firstName: user.firstName,
    lastName: user.lastName,
    role: user.role,
    isActive: user.isActive,
    viewerScope: user.viewerScope,
    createdAt: user.createdAt,
    lastLogin: user.lastLogin,
  };
}

router.get('/account/viewers', authenticateToken, requireRole('admin'), async (req, res) => {
  try {
    const viewers = await listViewerAccountsForParent(req.user.id);
    res.json({ viewers: viewers.map(serializeViewer) });
  } catch (error) {
    console.error('Error listing viewer accounts:', error);
    res.status(500).json({ message: 'Failed to list viewer accounts', error: error.message });
  }
});

router.post('/account/viewers', authenticateToken, requireRole('admin'), async (req, res) => {
  try {
    const {
      email,
      password,
      firstName,
      lastName,
      botId,
      botName,
      exchangeAccountId,
      exchangeAccountName,
    } = req.body || {};

    if (!email || !password) {
      return res.status(400).json({ message: 'email and password are required' });
    }
    if (String(password).length < 8) {
      return res.status(400).json({ message: 'password must be at least 8 characters long' });
    }

    const viewerScope = buildViewerScope({
      botId,
      botName,
      exchangeAccountId,
      exchangeAccountName,
    });

    const viewer = await createUser({
      email: String(email).toLowerCase().trim(),
      password: String(password),
      firstName: firstName?.trim(),
      lastName: lastName?.trim(),
      role: 'viewer',
      metadata: {
        parentUserId: req.user.id,
        viewerScope,
      },
    });

    res.status(201).json({ viewer: serializeViewer(viewer) });
  } catch (error) {
    console.error('Error creating viewer account:', error);
    const status = String(error.message || '').includes('already exists') ? 409 : 500;
    res.status(status).json({ message: 'Failed to create viewer account', error: error.message });
  }
});

router.put('/account/viewers/:viewerId', authenticateToken, requireRole('admin'), async (req, res) => {
  try {
    const { viewerId } = req.params;
    const payload = req.body || {};
    const updates = {};

    if (payload.email !== undefined) updates.email = payload.email;
    if (payload.firstName !== undefined) updates.firstName = payload.firstName;
    if (payload.lastName !== undefined) updates.lastName = payload.lastName;
    if (payload.password) {
      if (String(payload.password).length < 8) {
        return res.status(400).json({ message: 'password must be at least 8 characters long' });
      }
      updates.password = payload.password;
    }
    if (
      payload.botId !== undefined ||
      payload.botName !== undefined ||
      payload.exchangeAccountId !== undefined ||
      payload.exchangeAccountName !== undefined
    ) {
      updates.metadata = {
        viewerScope: buildViewerScope(payload),
      };
    }
    if (payload.isActive !== undefined) {
      updates.isActive = Boolean(payload.isActive);
    }

    const updated = await updateViewerAccount(viewerId, req.user.id, updates);
    if (!updated) {
      return res.status(404).json({ message: 'Viewer not found' });
    }
    res.json({ viewer: serializeViewer(updated) });
  } catch (error) {
    console.error('Error updating viewer account:', error);
    const status = error.message === 'Viewer not found' ? 404 : 500;
    res.status(status).json({ message: 'Failed to update viewer account', error: error.message });
  }
});

router.delete('/account/viewers/:viewerId', authenticateToken, requireRole('admin'), async (req, res) => {
  try {
    const { viewerId } = req.params;
    const viewer = await findViewerAccountById(viewerId, req.user.id);
    if (!viewer) {
      return res.status(404).json({ message: 'Viewer not found' });
    }
    await viewer.deactivate();
    res.status(204).end();
  } catch (error) {
    console.error('Error deleting viewer account:', error);
    res.status(500).json({ message: 'Failed to delete viewer account', error: error.message });
  }
});

/**
 * Notifications: channels + routing
 */

const CHANNEL_KEY = 'settings_notifications_channels';
const ROUTING_KEY = 'settings_notifications_routing';

router.get('/notifications/channels', authenticateToken, async (req, res) => {
  try {
    const channels = await getUserSetting(req.user.id, CHANNEL_KEY, []);
    res.json({ channels });
  } catch (error) {
    console.error('Error fetching notification channels:', error);
    res.status(500).json({ message: 'Failed to fetch channels', error: error.message });
  }
});

router.post('/notifications/channels', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const channels = await getUserSetting(userId, CHANNEL_KEY, []);
    const payload = req.body || {};
    if (!payload.type || typeof payload.type !== 'string') {
      return res.status(400).json({ message: 'type is required' });
    }
    const id = payload.id || crypto.randomUUID();
    const channel = {
      id,
      type: payload.type,
      label: payload.label || payload.type,
      enabled: payload.enabled !== false,
      config: payload.config || {},
      createdAt: new Date().toISOString(),
    };
    const next = [...channels.filter((c) => c.id !== id), channel];
    await setUserSetting(userId, CHANNEL_KEY, next);
    res.status(201).json({ channel });
  } catch (error) {
    console.error('Error creating notification channel:', error);
    res.status(500).json({ message: 'Failed to create channel', error: error.message });
  }
});

router.put('/notifications/channels/:id', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { id } = req.params;
    const channels = await getUserSetting(userId, CHANNEL_KEY, []);
    const idx = channels.findIndex((c) => c.id === id);
    if (idx === -1) return res.status(404).json({ message: 'Channel not found' });
    const existing = channels[idx];
    const payload = req.body || {};
    const updated = {
      ...existing,
      ...payload,
      id: existing.id,
    };
    channels[idx] = updated;
    await setUserSetting(userId, CHANNEL_KEY, channels);
    res.json({ channel: updated });
  } catch (error) {
    console.error('Error updating notification channel:', error);
    res.status(500).json({ message: 'Failed to update channel', error: error.message });
  }
});

router.delete('/notifications/channels/:id', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { id } = req.params;
    const channels = await getUserSetting(userId, CHANNEL_KEY, []);
    const next = channels.filter((c) => c.id !== id);
    await setUserSetting(userId, CHANNEL_KEY, next);
    res.status(204).end();
  } catch (error) {
    console.error('Error deleting notification channel:', error);
    res.status(500).json({ message: 'Failed to delete channel', error: error.message });
  }
});

router.get('/notifications/routing', authenticateToken, async (req, res) => {
  try {
    const routing = await getUserSetting(req.user.id, ROUTING_KEY, { rules: [] });
    res.json(routing);
  } catch (error) {
    console.error('Error fetching notification routing:', error);
    res.status(500).json({ message: 'Failed to fetch routing', error: error.message });
  }
});

router.put('/notifications/routing', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const routing = req.body || {};
    if (!routing.rules || !Array.isArray(routing.rules)) {
      return res.status(400).json({ message: 'rules must be an array' });
    }
    await setUserSetting(userId, ROUTING_KEY, routing);
    res.json(routing);
  } catch (error) {
    console.error('Error updating notification routing:', error);
    res.status(500).json({ message: 'Failed to update routing', error: error.message });
  }
});

router.post('/notifications/test', authenticateToken, async (req, res) => {
  try {
    // In a real implementation, dispatch a test notification through the selected channel
    res.json({ message: 'Test notification queued' });
  } catch (error) {
    console.error('Error sending test notification:', error);
    res.status(500).json({ message: 'Failed to send test notification', error: error.message });
  }
});

/**
 * Security settings: session + 2FA requirement
 */
const SECURITY_KEY = 'settings_security';
const hashCode = (code) => crypto.createHash('sha256').update(code).digest('hex');
router.get('/security', authenticateToken, async (req, res) => {
  try {
    const defaults = {
      twoFactorEnabled: false,
      sessionTimeout: 60,
      requireTwoFactorForLive: true,
    };
    const security = await getUserSetting(req.user.id, SECURITY_KEY, defaults);
    res.json(security);
  } catch (error) {
    console.error('Error fetching security settings:', error);
    res.status(500).json({ message: 'Failed to fetch security settings', error: error.message });
  }
});

router.put('/security', authenticateToken, async (req, res) => {
  try {
    const { twoFactorEnabled, sessionTimeout, requireTwoFactorForLive } = req.body || {};
    if (sessionTimeout !== undefined && (typeof sessionTimeout !== 'number' || sessionTimeout <= 0)) {
      return res.status(400).json({ message: 'sessionTimeout must be a positive number (minutes)' });
    }
    const current = await getUserSetting(req.user.id, SECURITY_KEY, {});
    const updated = {
      ...current,
      twoFactorEnabled: twoFactorEnabled ?? current.twoFactorEnabled ?? false,
      sessionTimeout: sessionTimeout ?? current.sessionTimeout ?? 60,
      requireTwoFactorForLive: requireTwoFactorForLive ?? current.requireTwoFactorForLive ?? true,
    };
    await setUserSetting(req.user.id, SECURITY_KEY, updated);
    res.json(updated);
  } catch (error) {
    console.error('Error updating security settings:', error);
    res.status(500).json({ message: 'Failed to update security settings', error: error.message });
  }
});

/**
 * API Keys (dashboard)
 * NOTE: Keys are stored hashed; the raw key is returned only at creation time.
 */
const API_KEYS_KEY = 'settings_api_keys';

router.get('/api-keys', authenticateToken, async (req, res) => {
  try {
    const keys = await getUserSetting(req.user.id, API_KEYS_KEY, []);
    const redacted = keys.map((k) => ({
      id: k.id,
      label: k.label,
      createdAt: k.createdAt,
      lastUsedAt: k.lastUsedAt,
      prefix: k.prefix,
    }));
    res.json({ keys: redacted });
  } catch (error) {
    console.error('Error fetching API keys:', error);
    res.status(500).json({ message: 'Failed to fetch API keys', error: error.message });
  }
});

router.post('/api-keys', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { label } = req.body || {};
    const keys = await getUserSetting(userId, API_KEYS_KEY, []);
    const raw = `dtk_${crypto.randomBytes(24).toString('hex')}`;
    const id = crypto.randomUUID();
    const hash = crypto.createHash('sha256').update(raw).digest('hex');
    const prefix = raw.slice(0, 8);
    const keyObj = {
      id,
      label: label || 'API Key',
      createdAt: new Date().toISOString(),
      lastUsedAt: null,
      prefix,
      hash,
    };
    const next = [...keys, keyObj];
    await setUserSetting(userId, API_KEYS_KEY, next);
    res.status(201).json({ key: { ...keyObj, apiKey: raw } });
  } catch (error) {
    console.error('Error creating API key:', error);
    res.status(500).json({ message: 'Failed to create API key', error: error.message });
  }
});

router.delete('/api-keys/:id', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { id } = req.params;
    const keys = await getUserSetting(userId, API_KEYS_KEY, []);
    const next = keys.filter((k) => k.id !== id);
    await setUserSetting(userId, API_KEYS_KEY, next);
    res.status(204).end();
  } catch (error) {
    console.error('Error deleting API key:', error);
    res.status(500).json({ message: 'Failed to delete API key', error: error.message });
  }
});

/**
 * Validate an API key and update lastUsedAt
 */
router.post('/api-keys/validate', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { apiKey } = req.body || {};
    if (!apiKey || typeof apiKey !== 'string') {
      return res.status(400).json({ message: 'apiKey is required' });
    }
    const keys = await getUserSetting(userId, API_KEYS_KEY, []);
    const hash = crypto.createHash('sha256').update(apiKey).digest('hex');
    const idx = keys.findIndex((k) => k.hash === hash);
    if (idx === -1) {
      return res.status(401).json({ message: 'Invalid API key' });
    }
    const now = new Date().toISOString();
    keys[idx].lastUsedAt = now;
    await setUserSetting(userId, API_KEYS_KEY, keys);
    const { hash: _, ...meta } = keys[idx];
    res.json({ valid: true, key: meta });
  } catch (error) {
    console.error('Error validating API key:', error);
    res.status(500).json({ message: 'Failed to validate API key', error: error.message });
  }
});

/**
 * 2FA validation stub (records lastValidatedAt)
 */
router.post('/security/validate-2fa', authenticateToken, async (req, res) => {
  try {
    const { code } = req.body || {};
    if (!code) return res.status(400).json({ message: 'code is required' });
    const current = await getUserSetting(req.user.id, SECURITY_KEY, {
      twoFactorEnabled: false,
      sessionTimeout: 60,
      requireTwoFactorForLive: true,
    });
    if (!current.twoFactorEnabled || !current.totpSecret) {
      return res.status(400).json({ message: '2FA not enabled' });
    }
    let verified = speakeasy.totp.verify({
      secret: current.totpSecret,
      encoding: 'base32',
      token: code,
      window: 1,
    });

    // Check backup codes if TOTP failed
    if (!verified && Array.isArray(current.backupCodes)) {
      const h = hashCode(code.trim());
      const idx = current.backupCodes.findIndex((c) => c.hash === h && !c.used);
      if (idx !== -1) {
        current.backupCodes[idx].used = true;
        verified = true;
      }
    }

    if (!verified) {
      return res.status(401).json({ message: 'Invalid 2FA code' });
    }
    const updated = { ...current, lastValidatedAt: new Date().toISOString() };
    await setUserSetting(req.user.id, SECURITY_KEY, updated);
    res.json({ valid: true, lastValidatedAt: updated.lastValidatedAt });
  } catch (error) {
    console.error('Error validating 2FA code:', error);
    res.status(500).json({ message: 'Failed to validate 2FA', error: error.message });
  }
});

/**
 * 2FA enrollment: provision secret and QR
 */
router.post('/security/2fa/enroll', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const secret = speakeasy.generateSecret({
      name: `veloxio (${userId})`,
      length: 20,
    });
    const otpauth = secret.otpauth_url;
    const qr = await qrcode.toDataURL(otpauth);
    const current = await getUserSetting(userId, SECURITY_KEY, {
      twoFactorEnabled: false,
      sessionTimeout: 60,
      requireTwoFactorForLive: true,
    });
    const updated = {
      ...current,
      pendingTotpSecret: secret.base32,
    };
    await setUserSetting(userId, SECURITY_KEY, updated);
    res.json({ otpauthUrl: otpauth, qr, secret: secret.base32 });
  } catch (error) {
    console.error('Error enrolling 2FA:', error);
    res.status(500).json({ message: 'Failed to enroll 2FA', error: error.message });
  }
});

/**
 * 2FA confirm: verify code against pending secret, then enable 2FA
 */
router.post('/security/2fa/confirm', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { code } = req.body || {};
    if (!code) return res.status(400).json({ message: 'code is required' });
    const current = await getUserSetting(userId, SECURITY_KEY, {
      twoFactorEnabled: false,
      sessionTimeout: 60,
      requireTwoFactorForLive: true,
    });
    const pendingSecret = current.pendingTotpSecret;
    if (!pendingSecret) {
      return res.status(400).json({ message: 'No pending 2FA enrollment' });
    }
    const verified = speakeasy.totp.verify({
      secret: pendingSecret,
      encoding: 'base32',
      token: code,
      window: 1,
    });
    if (!verified) {
      return res.status(401).json({ message: 'Invalid 2FA code' });
    }
    // Generate backup codes on enable if none
    const backupCodes = (current.backupCodes && current.backupCodes.length > 0)
      ? current.backupCodes
      : Array.from({ length: 10 }, () => {
          const codeVal = Math.random().toString().slice(2, 10);
          return { hash: hashCode(codeVal), used: false, plain: codeVal };
        });
    const returnedCodes = backupCodes.filter((c) => c.plain).map((c) => c.plain);
    const storedCodes = backupCodes.map((c) => ({ hash: c.hash, used: c.used }));
    const updated = {
      ...current,
      twoFactorEnabled: true,
      totpSecret: pendingSecret,
      pendingTotpSecret: null,
      lastValidatedAt: new Date().toISOString(),
      backupCodes: storedCodes,
    };
    await setUserSetting(userId, SECURITY_KEY, updated);
    res.json({ enabled: true, backupCodes: returnedCodes });
  } catch (error) {
    console.error('Error confirming 2FA:', error);
    res.status(500).json({ message: 'Failed to confirm 2FA', error: error.message });
  }
});

/**
 * Generate new backup codes (replaces existing)
 */
router.post('/security/2fa/backup-codes', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const current = await getUserSetting(userId, SECURITY_KEY, {
      twoFactorEnabled: false,
      sessionTimeout: 60,
      requireTwoFactorForLive: true,
      backupCodes: [],
    });
    if (!current.twoFactorEnabled || !current.totpSecret) {
      return res.status(400).json({ message: 'Enable 2FA first' });
    }
    const codes = Array.from({ length: 10 }, () => {
      const codeVal = Math.random().toString().slice(2, 10);
      return { hash: hashCode(codeVal), used: false, plain: codeVal };
    });
    const stored = codes.map((c) => ({ hash: c.hash, used: c.used }));
    await setUserSetting(userId, SECURITY_KEY, { ...current, backupCodes: stored });
    res.json({ backupCodes: codes.map((c) => c.plain) });
  } catch (error) {
    console.error('Error generating backup codes:', error);
    res.status(500).json({ message: 'Failed to generate backup codes', error: error.message });
  }
});

/**
 * 2FA disable
 */
router.post('/security/2fa/disable', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const current = await getUserSetting(userId, SECURITY_KEY, {
      twoFactorEnabled: false,
      sessionTimeout: 60,
      requireTwoFactorForLive: true,
    });
    const updated = {
      ...current,
      twoFactorEnabled: false,
      totpSecret: null,
      pendingTotpSecret: null,
      lastValidatedAt: null,
      backupCodes: [],
    };
    await setUserSetting(userId, SECURITY_KEY, updated);
    res.json({ disabled: true });
  } catch (error) {
    console.error('Error disabling 2FA:', error);
    res.status(500).json({ message: 'Failed to disable 2FA', error: error.message });
  }
});

/**
 * PUT /api/settings/trading - Update user's trading settings
 */
router.put('/trading', authenticateToken, async (req, res) => {
  const userId = req.user.id;
    const settings = normalizeTradingSettings(req.body);
  
  try {
    // Validate settings
    if (!settings || typeof settings !== 'object') {
      return res.status(400).json({ message: 'Invalid settings format' });
    }

    // Validate enabled order types
    const validOrderTypes = ['market', 'limit', 'stop_loss', 'stop_limit', 'trailing_stop', 'take_profit', 'bracket', 'oco'];
    if (settings.enabledOrderTypes && !Array.isArray(settings.enabledOrderTypes)) {
      return res.status(400).json({ message: 'enabledOrderTypes must be an array' });
    }

    if (settings.enabledOrderTypes) {
      const invalidTypes = settings.enabledOrderTypes.filter(type => !validOrderTypes.includes(type));
      if (invalidTypes.length > 0) {
        return res.status(400).json({ message: `Invalid order types: ${invalidTypes.join(', ')}` });
      }
    }

    // Validate numeric fields
    const numericFields = ['maxConcurrentPositions', 'maxPositionSizePercent', 'maxTotalExposurePercent', 'aiConfidenceThreshold', 'tradingInterval'];
    for (const field of numericFields) {
      if (settings[field] !== undefined && (typeof settings[field] !== 'number' || settings[field] < 0)) {
        return res.status(400).json({ message: `${field} must be a positive number` });
    // Validate per-token settings shape
    if (settings.perTokenSettings) {
      if (typeof settings.perTokenSettings !== 'object' || Array.isArray(settings.perTokenSettings)) {
        return res.status(400).json({ message: 'perTokenSettings must be an object keyed by symbol' });
      }
      for (const [symbol, cfg] of Object.entries(settings.perTokenSettings)) {
        if (!cfg || typeof cfg !== 'object') {
          return res.status(400).json({ message: `Invalid per-token config for ${symbol}` });
        }
        if (cfg.positionSizePct !== undefined && (typeof cfg.positionSizePct !== 'number' || cfg.positionSizePct <= 0)) {
          return res.status(400).json({ message: `positionSizePct for ${symbol} must be a positive number` });
        }
        if (cfg.leverage !== undefined && (typeof cfg.leverage !== 'number' || cfg.leverage < 1)) {
          return res.status(400).json({ message: `leverage for ${symbol} must be >= 1` });
        }
        if (cfg.enabled !== undefined && typeof cfg.enabled !== 'boolean') {
          return res.status(400).json({ message: `enabled for ${symbol} must be boolean` });
        }
      }
    }

      }
    }

    // Validate risk profile
    const validRiskProfiles = ['conservative', 'moderate', 'aggressive'];
    if (settings.riskProfile && !validRiskProfiles.includes(settings.riskProfile)) {
      return res.status(400).json({ message: `Invalid risk profile. Must be one of: ${validRiskProfiles.join(', ')}` });
    }

    // Update settings
    const updatedSettings = await UserTradingSettings.updateSettings(userId, settings);
    
    // Check if update was successful
    if (!updatedSettings) {
      throw new Error('updateSettings returned undefined - check UserTradingSettings.updateSettings implementation');
    }

    // Convert to API format (return ALL settings)
    const response = {
      enabledOrderTypes: updatedSettings.enabled_order_types || [],
      orderTypeSettings: updatedSettings.order_type_settings || {},
      riskProfile: updatedSettings.risk_profile || 'moderate',
      maxConcurrentPositions: updatedSettings.max_concurrent_positions || 4,
      maxPositionSizePercent: normalizePercent(updatedSettings.max_position_size_percent) || 0.10,
      maxTotalExposurePercent: normalizePercent(updatedSettings.max_total_exposure_percent) || 0.40,
      aiConfidenceThreshold: parseFloat(updatedSettings.ai_confidence_threshold) || 7.0,
      tradingInterval: updatedSettings.trading_interval || 300000,
      enabledTokens: updatedSettings.enabled_tokens || ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'TAOUSDT'],
      perTokenSettings: updatedSettings.per_token_settings || {},
      // Advanced features - main toggles
      dayTradingEnabled: updatedSettings.day_trading_enabled || false,
      scalpingMode: updatedSettings.scalping_mode || false,
      trailingStopsEnabled: updatedSettings.trailing_stops_enabled !== false,
      partialProfitsEnabled: updatedSettings.partial_profits_enabled !== false,
      timeBasedExitsEnabled: updatedSettings.time_based_exits_enabled !== false,
      multiTimeframeConfirmation: updatedSettings.multi_timeframe_confirmation || false,
      // Day Trading Mode settings
      dayTradingMaxHoldingHours: parseFloat(updatedSettings.day_trading_max_holding_hours) || 8.0,
      dayTradingStartTime: updatedSettings.day_trading_start_time || '09:30:00',
      dayTradingEndTime: updatedSettings.day_trading_end_time || '15:30:00',
      dayTradingForceCloseTime: updatedSettings.day_trading_force_close_time || '15:45:00',
      dayTradingDaysOnly: updatedSettings.day_trading_days_only || false,
      // Scalping Mode settings
      scalpingTargetProfitPercent: normalizePercent(updatedSettings.scalping_target_profit_percent) || 0.005,
      scalpingMaxHoldingMinutes: updatedSettings.scalping_max_holding_minutes || 15,
      scalpingMinVolumeMultiplier: parseFloat(updatedSettings.scalping_min_volume_multiplier) || 2.0,
      // Trailing Stops settings
      trailingStopActivationPercent: normalizePercent(updatedSettings.trailing_stop_activation_percent) || 0.02,
      trailingStopCallbackPercent: normalizePercent(updatedSettings.trailing_stop_callback_percent) || 0.01,
      trailingStopStepPercent: normalizePercent(updatedSettings.trailing_stop_step_percent) || 0.005,
      // Partial Profit Taking settings
      partialProfitLevels: normalizePartialProfitLevels(updatedSettings.partial_profit_levels) || [
        { percent: 25, target: 0.03 },
        { percent: 25, target: 0.05 },
        { percent: 25, target: 0.08 },
        { percent: 25, target: 0.12 }
      ],
      // Time-Based Exits settings
      timeExitMaxHoldingHours: parseFloat(updatedSettings.time_exit_max_holding_hours) || 24.0,
      timeExitBreakEvenHours: parseFloat(updatedSettings.time_exit_break_even_hours) || 4.0,
      timeExitWeekendClose: updatedSettings.time_exit_weekend_close !== false,
      // Multi-Timeframe Confirmation settings
      mtfRequiredTimeframes: updatedSettings.mtf_required_timeframes || ['15m', '1h', '4h'],
      mtfMinConfirmations: updatedSettings.mtf_min_confirmations || 2,
      mtfTrendAlignmentRequired: updatedSettings.mtf_trend_alignment_required !== false,
      // Leverage settings
      leverageEnabled: updatedSettings.leverage_enabled || false,
      maxLeverage: parseFloat(updatedSettings.max_leverage) || 1.0,
      leverageMode: updatedSettings.leverage_mode || 'isolated',
      liquidationBufferPercent: normalizePercent(updatedSettings.liquidation_buffer_percent) || 0.05,
      marginCallThresholdPercent: normalizePercent(updatedSettings.margin_call_threshold_percent) || 0.20,
      availableLeverageLevels: updatedSettings.available_leverage_levels || [1, 2, 3, 5, 10]
    };

    res.json({
      message: 'Trading settings updated successfully',
      settings: response
    });
  } catch (error) {
    console.error('Error updating trading settings:', error);
    console.error('Error stack:', error.stack);
    console.error('Settings received:', JSON.stringify(settings, null, 2));
    console.error('User ID:', userId);
    res.status(500).json({ message: 'Failed to update trading settings', error: error.message, details: error.stack });
  }
});

/**
 * POST /api/settings/trading/reset - Reset trading settings to defaults
 */
router.post('/trading/reset', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;

    const defaultSettings = await UserTradingSettings.resetToDefaults(userId);

    // Convert to API format
    const response = {
      enabledOrderTypes: defaultSettings.enabled_order_types || [],
      orderTypeSettings: defaultSettings.order_type_settings || {},
      riskProfile: defaultSettings.risk_profile || 'moderate',
      maxConcurrentPositions: defaultSettings.max_concurrent_positions || 4,
      maxPositionSizePercent: normalizePercent(defaultSettings.max_position_size_percent) || 0.10,
      maxTotalExposurePercent: normalizePercent(defaultSettings.max_total_exposure_percent) || 0.40,
      aiConfidenceThreshold: parseFloat(defaultSettings.ai_confidence_threshold) || 7.0,
      tradingInterval: defaultSettings.trading_interval || 300000,
      enabledTokens: defaultSettings.enabled_tokens || ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'TAOUSDT'],
      dayTradingEnabled: defaultSettings.day_trading_enabled || false,
      scalpingMode: defaultSettings.scalping_mode || false,
      trailingStopsEnabled: defaultSettings.trailing_stops_enabled || true,
      partialProfitsEnabled: defaultSettings.partial_profits_enabled || true,
      timeBasedExitsEnabled: defaultSettings.time_based_exits_enabled || true,
      multiTimeframeConfirmation: defaultSettings.multi_timeframe_confirmation || false,
      // Leverage settings
      leverageEnabled: defaultSettings.leverage_enabled || false,
      maxLeverage: parseFloat(defaultSettings.max_leverage) || 1.0,
      leverageMode: defaultSettings.leverage_mode || 'isolated',
      liquidationBufferPercent: normalizePercent(defaultSettings.liquidation_buffer_percent) || 0.05,
      marginCallThresholdPercent: normalizePercent(defaultSettings.margin_call_threshold_percent) || 0.20,
      availableLeverageLevels: defaultSettings.available_leverage_levels || [1, 2, 3, 5, 10]
    };

    res.json({
      message: 'Trading settings reset to defaults',
      settings: response
    });
  } catch (error) {
    console.error('Error resetting trading settings:', error);
    res.status(500).json({ message: 'Failed to reset trading settings', error: error.message });
  }
});

/**
 * GET /api/settings/order-types - Get available order types and their configurations
 */
router.get('/order-types', authenticateToken, async (req, res) => {
  try {
    const orderTypes = {
      market: {
        name: 'Market Order',
        description: 'Execute immediately at current market price',
        settings: {
          slippageLimit: {
            type: 'number',
            label: 'Max Slippage %',
            default: 0.5,
            min: 0,
            max: 5,
            step: 0.1
          },
          postOnly: {
            type: 'boolean',
            label: 'Post Only',
            default: false,
            description: 'Only place order if it would be a maker order'
          }
        }
      },
      limit: {
        name: 'Limit Order',
        description: 'Execute only at specified price or better',
        settings: {
          timeInForce: {
            type: 'select',
            label: 'Time in Force',
            default: 'GTC',
            options: [
              { value: 'GTC', label: 'Good Till Cancelled' },
              { value: 'IOC', label: 'Immediate or Cancel' },
              { value: 'FOK', label: 'Fill or Kill' },
              { value: 'GTD', label: 'Good Till Date' }
            ]
          },
          postOnly: {
            type: 'boolean',
            label: 'Post Only',
            default: true
          }
        }
      },
      stop_loss: {
        name: 'Stop Loss Order',
        description: 'Automatically sell when price drops to stop level',
        settings: {
          timeInForce: {
            type: 'select',
            label: 'Time in Force',
            default: 'GTC',
            options: [
              { value: 'GTC', label: 'Good Till Cancelled' },
              { value: 'IOC', label: 'Immediate or Cancel' }
            ]
          },
          reduceOnly: {
            type: 'boolean',
            label: 'Reduce Only',
            default: true,
            description: 'Only reduce position size, never increase'
          }
        }
      },
      stop_limit: {
        name: 'Stop Limit Order',
        description: 'Place limit order when stop price is reached',
        settings: {
          timeInForce: {
            type: 'select',
            label: 'Time in Force',
            default: 'GTC',
            options: [
              { value: 'GTC', label: 'Good Till Cancelled' },
              { value: 'IOC', label: 'Immediate or Cancel' }
            ]
          },
          reduceOnly: {
            type: 'boolean',
            label: 'Reduce Only',
            default: true
          }
        }
      },
      trailing_stop: {
        name: 'Trailing Stop Order',
        description: 'Dynamically adjust stop price as price moves favorably',
        settings: {
          callbackRate: {
            type: 'number',
            label: 'Callback Rate %',
            default: 1.0,
            min: 0.1,
            max: 10,
            step: 0.1,
            description: 'Percentage distance for trailing stop'
          },
          reduceOnly: {
            type: 'boolean',
            label: 'Reduce Only',
            default: true
          }
        }
      },
      take_profit: {
        name: 'Take Profit Order',
        description: 'Automatically sell when price reaches profit target',
        settings: {
          timeInForce: {
            type: 'select',
            label: 'Time in Force',
            default: 'GTC',
            options: [
              { value: 'GTC', label: 'Good Till Cancelled' },
              { value: 'IOC', label: 'Immediate or Cancel' }
            ]
          },
          reduceOnly: {
            type: 'boolean',
            label: 'Reduce Only',
            default: true
          }
        }
      },
      bracket: {
        name: 'Bracket Order',
        description: 'Entry order with attached stop-loss and take-profit',
        settings: {
          stopLossPercent: {
            type: 'number',
            label: 'Stop Loss %',
            default: 2.0,
            min: 0.1,
            max: 20,
            step: 0.1,
            description: 'Percentage below entry for stop loss'
          },
          takeProfitPercent: {
            type: 'number',
            label: 'Take Profit %',
            default: 5.0,
            min: 0.1,
            max: 50,
            step: 0.1,
            description: 'Percentage above entry for take profit'
          },
          timeInForce: {
            type: 'select',
            label: 'Time in Force',
            default: 'GTC',
            options: [
              { value: 'GTC', label: 'Good Till Cancelled' },
              { value: 'IOC', label: 'Immediate or Cancel' }
            ]
          }
        }
      },
      oco: {
        name: 'One Cancels Other (OCO)',
        description: 'Place two orders where filling one cancels the other',
        settings: {
          timeInForce: {
            type: 'select',
            label: 'Time in Force',
            default: 'GTC',
            options: [
              { value: 'GTC', label: 'Good Till Cancelled' },
              { value: 'IOC', label: 'Immediate or Cancel' }
            ]
          }
        }
      }
    };

    res.json({
      orderTypes,
      riskProfiles: {
        conservative: {
          name: 'Conservative',
          description: 'Lower risk, smaller positions, higher confidence required',
          settings: {
            maxPositionSizePercent: 5,
            maxTotalExposurePercent: 20,
            aiConfidenceThreshold: 8.0
          }
        },
        moderate: {
          name: 'Moderate',
          description: 'Balanced risk and reward approach',
          settings: {
            maxPositionSizePercent: 10,
            maxTotalExposurePercent: 40,
            aiConfidenceThreshold: 7.0
          }
        },
        aggressive: {
          name: 'Aggressive',
          description: 'Higher risk, larger positions, lower confidence threshold',
          settings: {
            maxPositionSizePercent: 15,
            maxTotalExposurePercent: 60,
            aiConfidenceThreshold: 6.0
          }
        }
      }
    });
  } catch (error) {
    console.error('Error fetching order types:', error);
    res.status(500).json({ message: 'Failed to fetch order types', error: error.message });
  }
});

/**
 * GET /api/settings/signal-config - Get signal generation configuration
 */
router.get('/signal-config', authenticateToken, async (req, res) => {
  try {
    // Get user-scoped signal config from Redis or return defaults
    const signalConfig = await redisState.getUserJson(req.user.id, 'signal_config', {
      // Signal Generation
      minConfirmations: 2,
      minRiskReward: 1.5,
      
      // Cooldown Settings
      standardCooldownSec: 5.0,
      lossCooldownSec: 30.0,
      chopCooldownSec: 60.0,
      
      // User Filters
      minConfidenceThreshold: 7.0,
      minDataCompleteness: 0.15,
      requireDataQuality: true,
      
      // Stage Configuration
      stages: {
        profileRouting: { enabled: true },
        signalGeneration: { enabled: true, minConfirmations: 2, minRiskReward: 1.5 },
        orderbookPrediction: { enabled: true, minConfidence: 0.6 },
        riskValidation: { enabled: true },
        positionSizing: { enabled: true },
      },
      
      // Rejection Thresholds
      maxRejectionsPerSymbol: 10,
      maxRejectionsPerStage: 50,
    });
    
    res.json({ config: signalConfig });
  } catch (error) {
    console.error('Error fetching signal config:', error);
    res.status(500).json({ message: 'Failed to load signal configuration', error: error.message });
  }
});

/**
 * PUT /api/settings/signal-config - Update signal generation configuration
 */
router.put('/signal-config', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const updates = req.body;
    
    if (!updates || typeof updates !== 'object') {
      return res.status(400).json({ message: 'Invalid configuration format' });
    }
    
    // Validate numeric fields
    const numericFields = ['minConfirmations', 'minRiskReward', 'standardCooldownSec', 'lossCooldownSec', 'chopCooldownSec', 'minConfidenceThreshold', 'minDataCompleteness'];
    for (const field of numericFields) {
      if (updates[field] !== undefined && (typeof updates[field] !== 'number' || updates[field] < 0)) {
        return res.status(400).json({ message: `${field} must be a positive number` });
      }
    }
    
    // Get current user-scoped config
    const currentConfig = await redisState.getUserJson(req.user.id, 'signal_config', {});
    const mergedConfig = { ...currentConfig, ...updates };
    
    // Save to Redis (user-scoped)
    await redisState.setUserJson(req.user.id, 'signal_config', mergedConfig);
    
    res.json({ message: 'Signal configuration updated', config: mergedConfig });
  } catch (error) {
    console.error('Error updating signal config:', error);
    res.status(500).json({ message: 'Failed to update signal configuration', error: error.message });
  }
});

/**
 * GET /api/settings/allocator - Get portfolio allocator configuration
 */
router.get('/allocator', authenticateToken, async (req, res) => {
  try {
    // Get user-scoped allocator config from Redis or return defaults
    const allocatorConfig = await redisState.getUserJson(req.user.id, 'allocator_config', {
      // Preemption thresholds
      scoreUpgradeFactor: 1.25,
      minScoreToPreempt: 0.6,
      
      // Guardrails
      minHoldTimeSec: 30.0,
      maxPreemptionsPerSymbolPerMin: 2,
      maxPreemptionsPerMin: 5,
      staleSlotAgeSec: 180.0,
      staleSlotMomentumThreshold: 0.35,
      staleSlotMinScoreDelta: 0.05,
      staleSlotUpgradeFactor: 1.05,
      staleSlotAllowNegativePnl: true,
      
      // Transaction cost awareness
      requirePositiveExpectedGain: true,
      minExpectedGainUsd: 5.0,
      expectedGainMultiplier: 0.15,
      
      // Feature flag
      enabled: false,
    });
    
    res.json({ config: allocatorConfig });
  } catch (error) {
    console.error('Error fetching allocator config:', error);
    res.status(500).json({ message: 'Failed to load allocator configuration', error: error.message });
  }
});

/**
 * PUT /api/settings/allocator - Update portfolio allocator configuration
 */
router.put('/allocator', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const updates = req.body;
    
    if (!updates || typeof updates !== 'object') {
      return res.status(400).json({ message: 'Invalid configuration format' });
    }
    
    // Validate numeric fields
    const numericFields = [
      'scoreUpgradeFactor', 'minScoreToPreempt', 'minHoldTimeSec',
      'maxPreemptionsPerSymbolPerMin', 'maxPreemptionsPerMin',
      'staleSlotAgeSec', 'staleSlotMomentumThreshold', 'staleSlotMinScoreDelta',
      'staleSlotUpgradeFactor', 'minExpectedGainUsd', 'expectedGainMultiplier'
    ];
    for (const field of numericFields) {
      if (updates[field] !== undefined && (typeof updates[field] !== 'number' || updates[field] < 0)) {
        return res.status(400).json({ message: `${field} must be a positive number` });
      }
    }
    
    // Get current user-scoped config
    const currentConfig = await redisState.getUserJson(req.user.id, 'allocator_config', {});
    const mergedConfig = { ...currentConfig, ...updates };
    
    // Save to Redis (user-scoped)
    await redisState.setUserJson(req.user.id, 'allocator_config', mergedConfig);
    
    res.json({ message: 'Allocator configuration updated', config: mergedConfig });
  } catch (error) {
    console.error('Error updating allocator config:', error);
    res.status(500).json({ message: 'Failed to update allocator configuration', error: error.message });
  }
});

export default router;
