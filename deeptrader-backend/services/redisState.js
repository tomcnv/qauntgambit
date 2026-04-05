import Redis from 'ioredis';

const DEFAULT_NAMESPACE = 'default';

/**
 * Normalize an ID (bot_id or user_id) for use in Redis keys.
 */
function normalizeNamespace(id) {
  if (!id) return DEFAULT_NAMESPACE;
  const cleaned = String(id).trim();
  if (!cleaned) return DEFAULT_NAMESPACE;
  // Preserve colons to align with Python publisher; only strip spaces
  return cleaned.replace(/\s+/g, '_');
}

// Alias for backwards compatibility
const normalizeUserNamespace = normalizeNamespace;

/**
 * Build a Redis key with the given namespace and suffix.
 * 
 * Key format: bot:<namespace>:<suffix>
 * 
 * @param {string} namespace - Bot instance ID or user ID
 * @param {string} suffix - Key suffix (e.g., 'positions', 'metrics')
 * @returns {string} Full Redis key
 */
export function buildBotKey(namespace, suffix) {
  const normalized = normalizeNamespace(namespace);
  const safeSuffix = String(suffix || '').trim();
  return `bot:${normalized}:${safeSuffix}`;
}

class RedisState {
  constructor() {
    this.client = null;
    this.connected = false;
    this.connecting = null;
    this.defaultOptions = {
      host: process.env.REDIS_HOST || 'localhost',
      port: process.env.REDIS_PORT || 6379,
      password: process.env.REDIS_PASSWORD || undefined,
      lazyConnect: true,
      maxRetriesPerRequest: 3,
    };
  }

  buildUserKey(userId, suffix) {
    return buildBotKey(userId, suffix);
  }

  async connect() {
    if (this.connected && this.client) {
      return this.client;
    }

    if (this.connecting) {
      return this.connecting;
    }

    this.client = new Redis(this.defaultOptions);

    this.client.on('error', (err) => {
      console.error('❌ RedisState error:', err.message);
      this.connected = false;
    });

    this.connecting = this.client
      .connect()
      .then(() => {
        this.connected = true;
        console.log('✅ RedisState connected to', `${this.defaultOptions.host}:${this.defaultOptions.port}`);
        return this.client;
      })
      .catch((err) => {
        this.connected = false;
        this.client = null;
        throw err;
      })
      .finally(() => {
        this.connecting = null;
      });

    return this.connecting;
  }

  async ensureClient() {
    if (this.connected && this.client) {
      return this.client;
    }
    return this.connect();
  }

  async getJson(key, fallback = null) {
    try {
      const client = await this.ensureClient();
      const raw = await client.get(key);
      if (!raw) return fallback;
      return JSON.parse(raw);
    } catch (error) {
      console.error(`❌ Failed to read Redis key ${key}:`, error.message);
      return fallback;
    }
  }

  async getString(key, fallback = null) {
    try {
      const client = await this.ensureClient();
      const raw = await client.get(key);
      return raw ?? fallback;
    } catch (error) {
      console.error(`❌ Failed to read Redis key ${key}:`, error.message);
      return fallback;
    }
  }

  async keyExists(key) {
    try {
      const client = await this.ensureClient();
      const exists = await client.exists(key);
      return exists === 1;
    } catch (error) {
      console.error(`❌ Failed to check Redis key ${key}:`, error.message);
      return false;
    }
  }

  async getList(key, { start = -50, stop = -1 } = {}) {
    try {
      const client = await this.ensureClient();
      const values = await client.lrange(key, start, stop);
      if (!values || values.length === 0) {
        // Fallback: key might be stored as a JSON string array instead of a Redis list
        const raw = await client.get(key);
        if (raw) {
          try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
          } catch {
            return [];
          }
        }
        return [];
      }
      return values.map((entry) => {
        try {
          return JSON.parse(entry);
        } catch {
          return entry;
        }
      });
    } catch (error) {
      if (error.message?.includes('WRONGTYPE')) {
        // Key exists but is not a list – try to parse as JSON string
        try {
          const client = await this.ensureClient();
          const raw = await client.get(key);
          if (raw) {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
          }
        } catch (innerErr) {
          console.error(`❌ Failed to fallback-read Redis key ${key}:`, innerErr.message);
        }
        return [];
      }
      console.error(`❌ Failed to read Redis list ${key}:`, error.message);
      return [];
    }
  }

  async setJson(key, value, { expireSeconds } = {}) {
    try {
      const client = await this.ensureClient();
      const payload = JSON.stringify(value);
      if (expireSeconds) {
        await client.set(key, payload, 'EX', expireSeconds);
      } else {
        await client.set(key, payload);
      }
      return true;
    } catch (error) {
      console.error(`❌ Failed to write Redis key ${key}:`, error.message);
      return false;
    }
  }

  async getUserJson(userId, suffix, fallback = null) {
    const key = this.buildUserKey(userId, suffix);
    // decision_traces is stored as a Redis list, not JSON string
    if (suffix === 'decision_traces') {
      return this.getList(key, { start: 0, stop: 99 });
    }
    return this.getJson(key, fallback);
  }

  async getUserList(userId, suffix, options = { start: -50, stop: -1 }) {
    const key = this.buildUserKey(userId, suffix);
    return this.getList(key, options);
  }

  async setUserJson(userId, suffix, value, options = {}) {
    const key = this.buildUserKey(userId, suffix);
    return this.setJson(key, value, options);
  }

  // ═══════════════════════════════════════════════════════════════
  // BOT-SCOPED METHODS (preferred for bot-level isolation)
  // ═══════════════════════════════════════════════════════════════

  /**
   * Build a Redis key for a specific bot instance.
   * @param {string} botId - Bot instance UUID
   * @param {string} suffix - Key suffix
   */
  buildBotKey(botId, suffix) {
    return buildBotKey(botId, suffix);
  }

  /**
   * Get JSON data for a specific bot instance.
   * @param {string} botId - Bot instance UUID
   * @param {string} suffix - Key suffix (e.g., 'positions', 'metrics')
   * @param {any} fallback - Default value if key doesn't exist
   */
  async getBotJson(botId, suffix, fallback = null) {
    const key = this.buildBotKey(botId, suffix);
    // decision_traces is stored as a Redis list, not JSON string
    if (suffix === 'decision_traces') {
      return this.getList(key, { start: 0, stop: 99 });
    }
    return this.getJson(key, fallback);
  }

  /**
   * Get list data for a specific bot instance.
   * @param {string} botId - Bot instance UUID
   * @param {string} suffix - Key suffix
   * @param {object} options - Range options { start, stop }
   */
  async getBotList(botId, suffix, options = { start: -50, stop: -1 }) {
    const key = this.buildBotKey(botId, suffix);
    return this.getList(key, options);
  }

  /**
   * Set JSON data for a specific bot instance.
   * @param {string} botId - Bot instance UUID
   * @param {string} suffix - Key suffix
   * @param {any} value - Value to store
   * @param {object} options - Options like { expireSeconds }
   */
  async setBotJson(botId, suffix, value, options = {}) {
    const key = this.buildBotKey(botId, suffix);
    return this.setJson(key, value, options);
  }

  /**
   * Check if a key exists for a specific bot instance.
   * @param {string} botId - Bot instance UUID
   * @param {string} suffix - Key suffix
   */
  async botKeyExists(botId, suffix) {
    const key = this.buildBotKey(botId, suffix);
    return this.keyExists(key);
  }

  /**
   * Fallback helper: return the first available service_health payload (any namespace).
   * Useful when the caller's userId doesn't match the publisher's namespace.
   */
  async getAnyServiceHealth() {
    try {
      const client = await this.ensureClient();
      const keys = await client.keys('bot:*:service_health');
      if (!keys || keys.length === 0) return null;
      const raw = await client.get(keys[0]);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      console.error('❌ Failed to fetch fallback service_health:', error.message);
      return null;
    }
  }

  async keyExistsForUser(userId, suffix) {
    const key = this.buildUserKey(userId, suffix);
    return this.keyExists(key);
  }

  async getStateSnapshot(userId = null) {
    const suffixes = {
      positions: 'positions',
      pendingOrders: 'pending_orders',
      metrics: 'metrics',
      risk: 'risk',
      exchangeStatus: 'exchange_status',
      performance: 'performance',
      protection: 'protection_status',
      execution: 'execution_stats',
      sizing: 'position_sizing',
      serviceHealth: 'service_health',
      resourceUsage: 'resource_usage',
      componentDiagnostics: 'component_diagnostics',
      stateSnapshot: 'state_snapshot',
    };

    const entries = await Promise.all(
      Object.entries(suffixes).map(async ([field, suffix]) => {
        const value = await this.getUserJson(userId, suffix);
        return [field, value];
      })
    );

    const snapshot = Object.fromEntries(entries);

    // If serviceHealth is missing for this user, fall back to any available publisher
    if (!snapshot.serviceHealth) {
      snapshot.serviceHealth = await this.getAnyServiceHealth();
    }

    snapshot.updatedAt = Date.now();
    return snapshot;
  }
}

export default new RedisState();



