/**
 * Secrets Provider - AWS Secrets Manager + Local Dev Fallback
 * 
 * Provides per-user, per-exchange credential management with:
 * - AWS Secrets Manager for production
 * - Encrypted local keystore for development
 * - In-memory caching with TTL
 * - Secret namespacing: deeptrader/<env>/<userId>/<exchange>
 */

import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

import { logStructuredEvent } from './logger.js';

// Cache configuration
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const secretsCache = new Map();

// Supported exchanges
export const SUPPORTED_EXCHANGES = ['okx', 'binance', 'bybit'];

// Python API configuration
const PYTHON_API_BASE_URL = process.env.PYTHON_API_URL || 'http://localhost:8888';

// Binance Futures Testnet (testnet.binancefuture.com) - for testnet API keys
const BINANCE_TESTNET_ENDPOINTS = {
  spot: {
    rest: 'https://testnet.binance.vision',
    wsTrade: 'wss://testnet.binance.vision',
    wsMarket: 'wss://testnet.binance.vision',
    sapi: 'https://testnet.binance.vision/sapi',
  },
  futures: {
    rest: 'https://testnet.binancefuture.com',
    wsMarket: 'wss://stream.binancefuture.com',
    sapi: 'https://testnet.binance.vision/sapi',
  },
};

// Keep demo endpoints as fallback (demo-fapi.binance.com) - different API keys
const BINANCE_DEMO_ENDPOINTS = {
  spot: {
    rest: 'https://demo-api.binance.com',
    wsTrade: 'wss://demo-ws-api.binance.com',
    wsMarket: 'wss://demo-stream.binance.com',
    sapi: 'https://demo-api.binance.com/sapi',
  },
  futures: {
    rest: 'https://demo-fapi.binance.com',
    wsMarket: 'wss://fstream.binancefuture.com',
    sapi: 'https://demo-api.binance.com/sapi',
  },
};

const BINANCE_FAPI_URL_KEYS = [
  'fapi',
  'fapiPublic',
  'fapiPrivate',
  'fapiPublicV2',
  'fapiPrivateV2',
  'fapiPublicV3',
  'fapiPrivateV3',
  'fapiData',
];

const BYBIT_DEMO_REST_BASE = 'https://api-demo.bybit.com';

// Environment detection
const isProduction = process.env.NODE_ENV === 'production';
const environment = process.env.DEEPTRADER_ENV || (isProduction ? 'prod' : 'dev');

// Local secrets directory (for development)
// Use __dirname to ensure consistent path regardless of process.cwd()
import { fileURLToPath } from 'url';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SECRETS_DIR = path.join(__dirname, '..', '.secrets', environment);

// Encryption key for local dev (derived from master password)
let localEncryptionKey = null;

// Helper to sanitize secret IDs for filesystem storage
function sanitizeSecretId(secretId) {
  return secretId.replace(/\//g, '__');
}

function normalizeCredentials(credentials = {}) {
  const normalized = { ...credentials };
  for (const field of ['apiKey', 'secretKey', 'passphrase']) {
    if (typeof normalized[field] === 'string') {
      normalized[field] = normalized[field].trim();
    }
  }
  return normalized;
}

async function fetchBybitApiKeyInfo(credentials, baseUrl = 'https://api.bybit.com') {
  const { response, data } = await fetchBybitSignedGet(credentials, {
    baseUrl,
    path: '/v5/user/query-api',
  });

  if (!response.ok || (data?.retCode !== 0 && data?.retCode !== '0')) {
    throw new Error(`bybit ${JSON.stringify(data)}`);
  }

  return data?.result || {};
}

async function fetchBybitSignedGet(credentials, { baseUrl = 'https://api.bybit.com', path, params = {} }) {
  const recvWindow = '5000';
  const timestamp = String(Date.now());
  const queryString = new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value !== undefined && value !== null && value !== '')
      .map(([key, value]) => [key, String(value)])
      .sort(([left], [right]) => left.localeCompare(right))
  ).toString();

  const toSign = `${timestamp}${credentials.apiKey}${recvWindow}${queryString}`;
  const signature = crypto
    .createHmac('sha256', credentials.secretKey)
    .update(toSign)
    .digest('hex');

  const url = queryString ? `${baseUrl}${path}?${queryString}` : `${baseUrl}${path}`;
  const response = await fetch(url, {
    headers: {
      'X-BAPI-SIGN-TYPE': '2',
      'X-BAPI-API-KEY': credentials.apiKey,
      'X-BAPI-TIMESTAMP': timestamp,
      'X-BAPI-RECV-WINDOW': recvWindow,
      'X-BAPI-SIGN': signature,
    },
  });
  const data = await response.json();
  return { response, data, queryString };
}

function unsanitizeSecretId(filename) {
  return filename.replace(/__/g, '/');
}

function buildLocalPathFromSecretId(secretId) {
  const safeName = sanitizeSecretId(secretId);
  return path.join(SECRETS_DIR, `${safeName}.enc`);
}

/**
 * Initialize the secrets provider
 * In dev mode, derives encryption key from master password
 */
export async function initializeSecretsProvider() {
  if (!isProduction) {
    const masterPassword = process.env.SECRETS_MASTER_PASSWORD || 'dev-master-key-change-in-prod';
    localEncryptionKey = crypto.scryptSync(masterPassword, 'deeptrader-salt', 32);
    
    // Ensure secrets directory exists
    if (!fs.existsSync(SECRETS_DIR)) {
      fs.mkdirSync(SECRETS_DIR, { recursive: true });
      console.log(`📁 Created secrets directory: ${SECRETS_DIR}`);
    }
    console.log('🔐 Secrets provider initialized (local mode)');
  } else {
    // Lazy-load AWS SDK only in production
    try {
      const { SecretsManagerClient } = await import('@aws-sdk/client-secrets-manager');
      globalThis._awsSecretsClient = new SecretsManagerClient({
        region: process.env.AWS_REGION || 'us-east-1',
      });
      console.log('🔐 Secrets provider initialized (AWS mode)');
    } catch (err) {
      console.error('❌ Failed to initialize AWS Secrets Manager:', err.message);
      throw err;
    }
  }
}

/**
 * Build the secret ID/path for a credential
 */
export function buildSecretId({ userId, exchange, credentialId }) {
  if (!userId || !exchange || !credentialId) {
    throw new Error('userId, exchange, and credentialId are required to build secretId');
  }
  return `deeptrader/${environment}/${userId}/${exchange}/${credentialId}`;
}

/**
 * Encrypt data for local storage
 */
function encryptLocal(data) {
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv('aes-256-gcm', localEncryptionKey, iv);
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(data), 'utf8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return JSON.stringify({
    iv: iv.toString('base64'),
    data: encrypted.toString('base64'),
    tag: authTag.toString('base64'),
  });
}

/**
 * Decrypt data from local storage
 */
function decryptLocal(encryptedStr) {
  const { iv, data, tag } = JSON.parse(encryptedStr);
  const decipher = crypto.createDecipheriv(
    'aes-256-gcm',
    localEncryptionKey,
    Buffer.from(iv, 'base64')
  );
  decipher.setAuthTag(Buffer.from(tag, 'base64'));
  const decrypted = Buffer.concat([
    decipher.update(Buffer.from(data, 'base64')),
    decipher.final(),
  ]);
  return JSON.parse(decrypted.toString('utf8'));
}

/**
 * Get exchange credentials by secret ID
 * 
 * @param {string} secretId - Secret identifier (deeptrader/... path)
 * @returns {Promise<Object|null>} Credentials object or null if not found
 */
export async function getExchangeCredentials(secretId) {
  if (!secretId) {
    throw new Error('secretId is required to fetch credentials');
  }
  
  // Check cache first
  const cached = secretsCache.get(secretId);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
    return cached.data;
  }

  let credentials = null;

  if (isProduction) {
    credentials = await getFromAWS(secretId);
  } else {
    credentials = getFromLocal(secretId);
  }

  // Cache the result
  if (credentials) {
    credentials = normalizeCredentials(credentials);
    secretsCache.set(secretId, { data: credentials, timestamp: Date.now() });
  }

  return credentials;
}

/**
 * Save exchange credentials for a user
 * 
 * @param {string} secretId - Secret identifier
 * @param {string} exchange - Exchange name (for validation)
 * @param {Object} credentials - Credentials object
 * @returns {Promise<boolean>} Success status
 */
export async function saveExchangeCredentials(secretId, exchange, credentials) {
  const normalizedCredentials = normalizeCredentials(credentials);
  if (!SUPPORTED_EXCHANGES.includes(exchange)) {
    throw new Error(`Unsupported exchange: ${exchange}`);
  }

  // Validate required fields per exchange
  validateCredentials(exchange, normalizedCredentials);
  if (!secretId) {
    throw new Error('secretId is required to save credentials');
  }

  if (isProduction) {
    await saveToAWS(secretId, normalizedCredentials);
  } else {
    saveToLocal(secretId, normalizedCredentials);
  }

  // Update cache
  secretsCache.set(secretId, { data: normalizedCredentials, timestamp: Date.now() });

  return true;
}

/**
 * Delete exchange credentials for a user
 * 
 * @param {string} secretId - Secret identifier
 * @returns {Promise<boolean>} Success status
 */
export async function deleteExchangeCredentials(secretId) {
  if (!secretId) {
    throw new Error('secretId is required to delete credentials');
  }

  if (isProduction) {
    await deleteFromAWS(secretId);
  } else {
    deleteFromLocal(secretId);
  }

  // Clear cache
  secretsCache.delete(secretId);

  return true;
}

/**
 * List all exchanges a user has credentials for
 * 
 * @param {string} userId - User ID
 * @returns {Promise<string[]>} Array of exchange names
 */
export async function listUserExchanges(userId) {
  if (isProduction) {
    return listFromAWS(userId);
  } else {
    return listFromLocal(userId);
  }
}

/**
 * Validate credentials object for an exchange
 */
function validateCredentials(exchange, credentials) {
  const requiredFields = {
    okx: ['apiKey', 'secretKey', 'passphrase'],
    binance: ['apiKey', 'secretKey'],
    bybit: ['apiKey', 'secretKey'],
  };

  const required = requiredFields[exchange];
  for (const field of required) {
    if (!credentials[field]) {
      throw new Error(`Missing required field for ${exchange}: ${field}`);
    }
  }
}

/**
 * Mask credentials for safe display
 * 
 * @param {Object} credentials - Full credentials
 * @returns {Object} Credentials with masked sensitive values
 */
export function maskCredentials(credentials) {
  if (!credentials) return null;
  
  const masked = { ...credentials };
  
  if (masked.apiKey) {
    masked.apiKey = masked.apiKey.slice(0, 8) + '...' + masked.apiKey.slice(-4);
  }
  if (masked.secretKey) {
    masked.secretKey = '********';
  }
  if (masked.passphrase) {
    masked.passphrase = '********';
  }
  
  return masked;
}

// ═══════════════════════════════════════════════════════════════
// AWS SECRETS MANAGER OPERATIONS
// ═══════════════════════════════════════════════════════════════

async function getFromAWS(secretId) {
  try {
    const { GetSecretValueCommand } = await import('@aws-sdk/client-secrets-manager');
    const command = new GetSecretValueCommand({ SecretId: secretId });
    const response = await globalThis._awsSecretsClient.send(command);
    return JSON.parse(response.SecretString);
  } catch (err) {
    if (err.name === 'ResourceNotFoundException') {
      return null;
    }
    console.error(`❌ AWS Secrets Manager error for ${secretId}:`, err.message);
    throw err;
  }
}

async function saveToAWS(secretId, credentials) {
  try {
    const { CreateSecretCommand, UpdateSecretCommand, ResourceNotFoundException } = await import('@aws-sdk/client-secrets-manager');
    
    // Try to update first, create if not exists
    try {
      const updateCommand = new UpdateSecretCommand({
        SecretId: secretId,
        SecretString: JSON.stringify(credentials),
      });
      await globalThis._awsSecretsClient.send(updateCommand);
    } catch (err) {
      if (err.name === 'ResourceNotFoundException') {
        const createCommand = new CreateSecretCommand({
          Name: secretId,
          SecretString: JSON.stringify(credentials),
          Description: `DeepTrader exchange credentials`,
        });
        await globalThis._awsSecretsClient.send(createCommand);
      } else {
        throw err;
      }
    }
  } catch (err) {
    console.error(`❌ Failed to save secret ${secretId}:`, err.message);
    throw err;
  }
}

async function deleteFromAWS(secretId) {
  try {
    const { DeleteSecretCommand } = await import('@aws-sdk/client-secrets-manager');
    const command = new DeleteSecretCommand({
      SecretId: secretId,
      ForceDeleteWithoutRecovery: true,
    });
    await globalThis._awsSecretsClient.send(command);
  } catch (err) {
    if (err.name !== 'ResourceNotFoundException') {
      console.error(`❌ Failed to delete secret ${secretId}:`, err.message);
      throw err;
    }
  }
}

async function listFromAWS(userId) {
  try {
    const { ListSecretsCommand } = await import('@aws-sdk/client-secrets-manager');
    const prefix = `deeptrader/${environment}/${userId}/`;
    const command = new ListSecretsCommand({
      Filters: [{ Key: 'name', Values: [prefix] }],
    });
    const response = await globalThis._awsSecretsClient.send(command);
    
    const exchanges = new Set();
    (response.SecretList || []).forEach(secret => {
      const parts = secret.Name.split('/');
      if (parts.length >= 5) {
        exchanges.add(parts[parts.length - 2]);
      } else if (parts.length >= 4) {
        exchanges.add(parts[parts.length - 1]);
      }
    });
    return Array.from(exchanges);
  } catch (err) {
    console.error(`❌ Failed to list secrets for user ${userId}:`, err.message);
    return [];
  }
}

// ═══════════════════════════════════════════════════════════════
// LOCAL STORAGE OPERATIONS (Development)
// ═══════════════════════════════════════════════════════════════

function getFromLocal(secretId) {
  const filePath = buildLocalPathFromSecretId(secretId);
  
  if (!fs.existsSync(filePath)) {
    return null;
  }
  
  try {
    const encrypted = fs.readFileSync(filePath, 'utf8');
    return decryptLocal(encrypted);
  } catch (err) {
    console.error(`❌ Failed to read local secret ${filePath}:`, err.message);
    return null;
  }
}

function saveToLocal(secretId, credentials) {
  const filePath = buildLocalPathFromSecretId(secretId);
  
  try {
    const encrypted = encryptLocal(credentials);
    fs.writeFileSync(filePath, encrypted, 'utf8');
    console.log(`✅ Saved credentials for ${secretId} to local keystore`);
  } catch (err) {
    console.error(`❌ Failed to save local secret ${filePath}:`, err.message);
    throw err;
  }
}

function deleteFromLocal(secretId) {
  const filePath = buildLocalPathFromSecretId(secretId);
  
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
    console.log(`🗑️  Deleted credentials for ${secretId} from local keystore`);
  }
}

function listFromLocal(userId) {
  if (!fs.existsSync(SECRETS_DIR)) {
    return [];
  }
  
  const files = fs.readdirSync(SECRETS_DIR);
  const exchanges = new Set();
  
  for (const file of files) {
    if (!file.endsWith('.enc')) continue;
    const secretId = unsanitizeSecretId(file.replace('.enc', ''));
    const parts = secretId.split('/');
    if (parts.length >= 5) {
      const [, , secretUserId, exchange] = parts;
      if (secretUserId === userId) {
        exchanges.add(exchange);
      }
    } else if (parts.length >= 4) {
      const [, , secretUserId, exchange] = parts;
      if (secretUserId === userId) {
        exchanges.add(exchange);
      }
    }
  }
  
  return Array.from(exchanges);
}

// ═══════════════════════════════════════════════════════════════
// CREDENTIAL VERIFICATION & BALANCE FETCHING
// ═══════════════════════════════════════════════════════════════

/**
 * Create a CCXT client for an exchange
 * @param {string} exchange - Exchange name
 * @param {Object} credentials - API credentials
 * @param {boolean} isDemo - Whether to use demo trading endpoints
 *   - Bybit: api-demo.bybit.com (simulated live trading)
 *   - OKX: x-simulated-trading header (demo mode)
 *   - Binance: NOT SUPPORTED (testnet deprecated)
 */
async function createExchangeClient(exchange, credentials, isDemo = false) {
  const ccxt = await import('ccxt');
  
  // Validate: Demo mode only supported on Bybit and OKX
  if (isDemo && exchange === 'binance') {
    throw new Error('Demo trading is not supported for Binance (testnet deprecated). Use paper trading instead.');
  }
  
  const exchangeConfig = {
    okx: {
      class: ccxt.default.okx,
      config: {
        apiKey: credentials.apiKey,
        secret: credentials.secretKey,
        password: credentials.passphrase,
        options: { defaultType: 'swap' },
        // OKX demo trading uses x-simulated-trading header, not sandbox mode
        headers: isDemo ? { 'x-simulated-trading': '1' } : {},
      },
    },
    binance: {
      class: ccxt.default.binance,
      config: {
        apiKey: credentials.apiKey,
        secret: credentials.secretKey,
        options: { 
          defaultType: 'future',
        },
      },
    },
    bybit: {
      class: ccxt.default.bybit,
      config: {
        apiKey: credentials.apiKey,
        secret: credentials.secretKey,
        options: { 
          defaultType: 'swap',
          // CRITICAL: /v5/asset/coin/query-info is NOT supported on demo
          fetchCurrencies: false,
        },
      },
      // Bybit demo trading uses api-demo.bybit.com (mainnet keys with demo feature)
      useDemoEndpoint: isDemo,
    },
  };
  
  const config = exchangeConfig[exchange];
  if (!config) {
    throw new Error(`Unsupported exchange: ${exchange}`);
  }
  
  const client = new config.class(config.config);
  
  // For sandbox mode - skip exchanges that use special demo handling:
  // - Bybit: uses separate demo API endpoint (api-demo.bybit.com)
  // - OKX: uses 'x-simulated-trading' header for demo trading
  // - Binance: Demo not supported (testnet deprecated)
  const sandboxToggleSupported = !['binance', 'bybit', 'okx'].includes(exchange);
  
  if (isDemo && sandboxToggleSupported && typeof client.setSandboxMode === 'function') {
    client.setSandboxMode(true);
  }
  
  // Bybit demo trading uses api-demo.bybit.com
  // Must also preload markets from mainnet and skip unsupported endpoints
  if (exchange === 'bybit' && config.useDemoEndpoint) {
    const demoUrls = {
      public: BYBIT_DEMO_REST_BASE,
      private: BYBIT_DEMO_REST_BASE,
      v2: BYBIT_DEMO_REST_BASE,
      spot: BYBIT_DEMO_REST_BASE,
      futures: BYBIT_DEMO_REST_BASE,
    };
    console.log(`[createExchangeClient] Setting Bybit demo endpoint: ${JSON.stringify(demoUrls)}`);
    if (!client.urls) client.urls = {};
    client.urls.api = demoUrls;
  }
  
  // Note: Binance demo/testnet is NOT supported - the code path should not reach here
  // due to the validation above, but kept for safety
  if (isDemo && client.urls?.test && exchange !== 'bybit') {
    client.urls.api = client.urls.test;
  }
  
  client.__dtBaseUrl = determineClientBaseUrl(client, exchange);
  return client;
}

function ensureApiUrls(client, demoBase) {
  if (!client.urls.api) {
    client.urls.api = {};
  }
  client.urls.api = {
    ...client.urls.api,
    public: demoBase,
    private: demoBase,
  };
}

function determineClientBaseUrl(client, exchange) {
  if (exchange === 'binance') {
    const privateUrl =
      client.urls?.fapiPrivate ||
      client.urls?.api?.private ||
      client.urls?.api?.public ||
      client.urls?.api ||
      client.urls?.rest;
    return privateUrl || 'unknown';
  }
  const apiUrl = client.urls?.api;
  if (typeof apiUrl === 'string') return apiUrl;
  if (apiUrl?.private) return apiUrl.private;
  if (apiUrl?.public) return apiUrl.public;
  return client.urls?.rest || 'unknown';
}

/**
 * Extract USDT balance from ccxt balance response
 */
function extractUsdtBalance(balanceData) {
  // Try to find USDT balance in various formats
  if (balanceData.USDT?.total !== undefined) {
    return { balance: parseFloat(balanceData.USDT.total), currency: 'USDT' };
  }
  if (balanceData.total?.USDT !== undefined) {
    return { balance: parseFloat(balanceData.total.USDT), currency: 'USDT' };
  }
  // For futures, check info field
  if (balanceData.info) {
    // Binance futures format
    if (Array.isArray(balanceData.info)) {
      const usdtAsset = balanceData.info.find(a => a.asset === 'USDT');
      if (usdtAsset) {
        return { balance: parseFloat(usdtAsset.walletBalance || usdtAsset.balance || 0), currency: 'USDT' };
      }
    }
    // OKX format
    if (balanceData.info.data?.[0]?.details) {
      const usdtDetail = balanceData.info.data[0].details.find(d => d.ccy === 'USDT');
      if (usdtDetail) {
        return { balance: parseFloat(usdtDetail.cashBal || usdtDetail.availBal || 0), currency: 'USDT' };
      }
    }
    // Bybit format
    if (balanceData.info.result?.list?.[0]?.coin) {
      const usdtCoin = balanceData.info.result.list[0].coin.find(c => c.coin === 'USDT');
      if (usdtCoin) {
        return { balance: parseFloat(usdtCoin.walletBalance || 0), currency: 'USDT' };
      }
    }
  }
  // Fallback - check for any positive balance
  for (const [currency, data] of Object.entries(balanceData)) {
    if (typeof data === 'object' && data.total > 0) {
      return { balance: parseFloat(data.total), currency };
    }
  }
  return { balance: 0, currency: 'USDT' };
}

/**
 * Verify exchange credentials by making a test API call
 * 
 * @param {string} exchange - Exchange name
 * @param {Object} credentials - Credentials to verify
 * @param {boolean} isDemo - Whether to use demo trading (Bybit/OKX only)
 * @returns {Promise<{valid: boolean, error?: string, permissions?: string[], balance?: number, currency?: string}>}
 */
export async function verifyExchangeCredentials(exchange, credentials, isDemo = false) {
  try {
    credentials = normalizeCredentials(credentials);
    // Binance demo is not supported - block early
    if (exchange === 'binance' && isDemo) {
      return {
        valid: false,
        error: 'Demo trading is not supported for Binance (testnet deprecated). Use paper trading instead.',
        permissions: [],
        balance: null,
        currency: 'USDT',
        accountConnected: false,
      };
    }
    
    if (exchange === 'binance') {
      // Binance production - use REST verification
      const result = await verifyBinanceTestnetCredentials(credentials);
      logStructuredEvent('info', 'exchange.verify', 'Binance demo verification via REST', {
        exchange,
        isDemo,
        baseUrl: result.meta?.baseUrl,
      });
      return result;
    }

    const client = await createExchangeClient(exchange, credentials, isDemo);
    const meta = {
      exchange,
      isDemo,
      baseUrl: client.__dtBaseUrl || determineClientBaseUrl(client, exchange),
    };
    logStructuredEvent('info', 'exchange.verify', 'Attempting credential verification', meta);

    let balance = null;
    let currency = 'USDT';
    let permissions = ['read'];
    let canWithdraw = false;

    // Bybit demo rejects the generic balance path with 10032. Use query-api for
    // auth + permission validation and leave balance refresh to the dedicated path.
    if (exchange === 'bybit' && isDemo) {
      const keyInfo = await fetchBybitApiKeyInfo(credentials, BYBIT_DEMO_REST_BASE);
      const walletPermissions = Array.isArray(keyInfo?.permissions?.Wallet)
        ? keyInfo.permissions.Wallet.map((value) => String(value))
        : [];
      const contractPermissions = Array.isArray(keyInfo?.permissions?.ContractTrade)
        ? keyInfo.permissions.ContractTrade.map((value) => String(value))
        : [];
      const spotPermissions = Array.isArray(keyInfo?.permissions?.Spot)
        ? keyInfo.permissions.Spot.map((value) => String(value))
        : [];

      if (
        contractPermissions.some((value) => value === 'Order' || value === 'Position') ||
        spotPermissions.includes('SpotTrade')
      ) {
        permissions.push('trade');
      }

      canWithdraw = walletPermissions.includes('Withdraw');
    } else {
      // Try to fetch balance as verification
      const balanceData = await client.fetchBalance();
      ({ balance, currency } = extractUsdtBalance(balanceData));

      // Check trade permission
      try {
        // Most exchanges allow this if trade permission exists
        await client.fetchOpenOrders();
        permissions.push('trade');
      } catch (e) {
        // Trade permission not available
      }
    
      // Check for withdrawal permission (SECURITY: we reject keys with this)
      // For testnet/dev we explicitly skip the withdraw probe to avoid false positives.
      if (!isDemo) {
        try {
          // OKX: Try to get withdrawal history - requires withdraw permission
          if (exchange === 'okx') {
            await client.fetchWithdrawals();
            canWithdraw = true;
            permissions.push('withdraw');
          }
          // Binance: Try to get withdraw history
          else if (exchange === 'binance' || exchange === 'binanceusdm') {
            await client.fetchWithdrawals();
            canWithdraw = true;
            permissions.push('withdraw');
          }
          // Bybit: query the API key permission object directly. Using
          // `fetchWithdrawals()` here can produce false positives.
          else if (exchange === 'bybit') {
            const keyInfo = await fetchBybitApiKeyInfo(credentials, meta.baseUrl);
            const walletPermissions = Array.isArray(keyInfo?.permissions?.Wallet)
              ? keyInfo.permissions.Wallet.map((value) => String(value))
              : [];
            const contractPermissions = Array.isArray(keyInfo?.permissions?.ContractTrade)
              ? keyInfo.permissions.ContractTrade.map((value) => String(value))
              : [];
            const spotPermissions = Array.isArray(keyInfo?.permissions?.Spot)
              ? keyInfo.permissions.Spot.map((value) => String(value))
              : [];

            if (
              contractPermissions.some((value) => value === 'Order' || value === 'Position') ||
              spotPermissions.includes('SpotTrade')
            ) {
              if (!permissions.includes('trade')) {
                permissions.push('trade');
              }
            }

            canWithdraw = walletPermissions.includes('Withdraw');
            if (canWithdraw) {
              permissions.push('withdraw');
            }
          }
        } catch (e) {
          // Withdrawal permission not available - this is GOOD for security
          canWithdraw = false;
        }
      }
    }
    
    const result = { 
      valid: true, 
      permissions,
      canWithdraw,
      balance,
      currency,
      accountConnected: true,
      warning: undefined,
      meta,
    };
    logStructuredEvent('info', 'exchange.verify.success', 'Credential verification successful', {
      ...meta,
      balance,
      permissions,
    });
    return result;
  } catch (err) {
    const message = err.message || 'Verification failed';
    const meta = {
      exchange,
      isDemo,
    };
    if (exchange === 'binance' && isDemo && /does not have a testnet/i.test(message)) {
      logStructuredEvent('warn', 'exchange.verify.warning', 'Binance demo lacks balance endpoint', {
        ...meta,
      });
      return {
        valid: true,
        warning: 'Binance USDM testnet no longer exposes SAPI endpoints via ccxt sandbox. Keys saved, but balances must be managed via the Binance demo account.',
        permissions: ['read'],
        balance: null,
        currency: 'USDT',
        accountConnected: true,
        meta,
      };
    }
    logStructuredEvent('warn', 'exchange.verify.failed', 'Credential verification failed', {
      ...meta,
      error: message,
    });
    return { valid: false, error: message, accountConnected: false, meta };
  }
}

/**
 * Fetch current balance from exchange
 * 
 * @param {string} exchange - Exchange name
 * @param {Object} credentials - API credentials
 * @param {boolean} isDemo - Whether to use testnet endpoints
 * @returns {Promise<{success: boolean, balance?: number, currency?: string, error?: string}>}
 */
export async function fetchExchangeBalance(exchange, credentials, isDemo = false) {
  try {
    credentials = normalizeCredentials(credentials);
    // For Binance testnet, use direct REST calls (CCXT doesn't properly support testnet)
    if (exchange === 'binance' && isDemo) {
      console.log('[fetchExchangeBalance] Using direct REST call for Binance testnet');
      const result = await fetchBinanceTestnetBalance(credentials);
      return {
        success: true,
        balance: result.balance,
        currency: result.currency,
        timestamp: Date.now(),
      };
    }

    // For Bybit demo, prefer CCXT first because it already handles Bybit's
    // authenticated request shape. Fall back to the direct wallet-balance
    // endpoint only when the generic balance call is explicitly unsupported.
    if (exchange === 'bybit' && isDemo) {
      try {
        console.log('[fetchExchangeBalance] Using CCXT fetchBalance for Bybit demo');
        const client = await createExchangeClient(exchange, credentials, isDemo);
        const balanceData = await client.fetchBalance();
        const { balance, currency } = extractUsdtBalance(balanceData);
        return {
          success: true,
          balance,
          currency,
          timestamp: Date.now(),
        };
      } catch (err) {
        const message = String(err?.message || err);
        if (!/10032|unsupported|not supported/i.test(message)) {
          throw err;
        }
        console.log('[fetchExchangeBalance] Falling back to wallet-balance endpoint for Bybit demo');
        const result = await fetchBybitDemoBalance(credentials);
        return {
          success: true,
          balance: result.balance,
          currency: result.currency,
          timestamp: Date.now(),
        };
      }
    }

    // For Binance production, try Python API first
    if (exchange === 'binance') {
      const balanceResult = await fetchBalanceFromPythonAPI(exchange, credentials, isDemo);
      if (balanceResult.success) {
        return balanceResult;
      }
      // Fall back to CCXT if Python API fails
      console.log('[fetchExchangeBalance] Python API failed, falling back to CCXT');
    }

    const client = await createExchangeClient(exchange, credentials, isDemo);
    const balanceData = await client.fetchBalance();
    const { balance, currency } = extractUsdtBalance(balanceData);

    return {
      success: true,
      balance,
      currency,
      timestamp: Date.now(),
    };
  } catch (err) {
    return {
      success: false,
      error: err.message,
    };
  }
}

/**
 * Fetch balance from Binance testnet using direct REST API
 * (CCXT doesn't support Binance demo/testnet balance endpoint)
 */
async function fetchBinanceTestnetBalance(credentials) {
  const baseUrl = BINANCE_TESTNET_ENDPOINTS.futures.rest;
  const accountPath = '/fapi/v2/account';
  const recvWindow = 5000;
  const timestamp = Date.now();
  const query = `timestamp=${timestamp}&recvWindow=${recvWindow}`;
  const signature = crypto.createHmac('sha256', credentials.secretKey).update(query).digest('hex');
  const accountUrl = `${baseUrl}${accountPath}?${query}&signature=${signature}`;
  const headers = {
    'X-MBX-APIKEY': credentials.apiKey,
  };

  const accountRes = await fetch(accountUrl, { headers });
  const accountText = await accountRes.text();
  
  if (!accountRes.ok) {
    throw new Error(`Binance API error: ${accountText}`);
  }
  
  const account = JSON.parse(accountText);
  const balance = parseFloat(account.totalWalletBalance ?? account.totalMarginBalance ?? 0) || 0;

  return {
    balance,
    currency: 'USDT',
  };
}

/**
 * Fetch balance from Bybit demo trading using the supported wallet-balance endpoint.
 * 
 * Bybit demo only supports limited v5 endpoints. The standard fetchBalance() 
 * calls /v5/asset/coin/query-info which returns "Demo trading are not supported" (10032).
 * Instead, we call /v5/account/wallet-balance directly.
 */
async function fetchBybitDemoBalance(credentials) {
  const { data } = await fetchBybitSignedGet(credentials, {
    baseUrl: BYBIT_DEMO_REST_BASE,
    path: '/v5/account/wallet-balance',
    params: {
      accountType: 'UNIFIED',
    },
  });
  
  if (data.retCode !== 0 && data.retCode !== '0') {
    throw new Error(`Bybit API error: ${JSON.stringify(data)}`);
  }
  
  const list = data.result?.list || [];
  if (list.length > 0) {
    const account = list[0];
    // Look for USDT wallet balance specifically, not totalEquity
    const coins = account.coin || [];
    let usdtBalance = 0;
    for (const coin of coins) {
      if (coin.coin === 'USDT') {
        usdtBalance = parseFloat(coin.walletBalance || '0');
        break;
      }
    }
    const totalEquity = parseFloat(account.totalEquity || '0');
    console.log(`[fetchBybitDemoBalance] USDT wallet: ${usdtBalance}, Total equity: ${totalEquity}`);
    return {
      balance: usdtBalance || totalEquity, // Prefer USDT wallet balance, fall back to total equity
      currency: 'USDT',
    };
  }
  
  return {
    balance: 0,
    currency: 'USDT',
  };
}

/**
 * Fetch balance using Python API with custom BinanceRestClient
 */
async function fetchBalanceFromPythonAPI(exchange, credentials, isDemo) {
  try {
    const response = await fetch(`${PYTHON_API_BASE_URL}/balance`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        exchange,
        api_key: credentials.apiKey,
        secret_key: credentials.secretKey,
        passphrase: credentials.passphrase || '',
        is_testnet: isDemo,
      }),
    });

    if (!response.ok) {
      throw new Error(`Python API returned ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    if (data.success) {
      return {
        success: true,
        balance: data.balance,
        currency: data.currency,
        timestamp: Date.now(),
      };
    } else {
      throw new Error(data.error || 'Unknown error from Python API');
    }
  } catch (err) {
    console.error('[fetchBalanceFromPythonAPI] Error:', err.message);
    return {
      success: false,
      error: err.message,
    };
  }
}

/**
 * Clear the secrets cache (for testing or forced refresh)
 */
export function clearSecretsCache() {
  secretsCache.clear();
}

export default {
  initializeSecretsProvider,
  getExchangeCredentials,
  saveExchangeCredentials,
  deleteExchangeCredentials,
  listUserExchanges,
  verifyExchangeCredentials,
  fetchExchangeBalance,
  maskCredentials,
  clearSecretsCache,
  SUPPORTED_EXCHANGES,
  buildSecretId,
};

async function verifyBinanceTestnetCredentials(credentials) {
  const baseUrl = BINANCE_TESTNET_ENDPOINTS.futures.rest;
  const accountPath = '/fapi/v2/account';
  const openOrdersPath = '/fapi/v1/openOrders';
  const recvWindow = 5000;
  const timestamp = Date.now();
  const query = `timestamp=${timestamp}&recvWindow=${recvWindow}`;
  const signature = crypto.createHmac('sha256', credentials.secretKey).update(query).digest('hex');
  const accountUrl = `${baseUrl}${accountPath}?${query}&signature=${signature}`;
  const headers = {
    'X-MBX-APIKEY': credentials.apiKey,
  };

  const accountRes = await fetch(accountUrl, { headers });
  const accountText = await accountRes.text();
  if (!accountRes.ok) {
    throw new Error(`binanceusdm ${accountText}`);
  }
  const account = JSON.parse(accountText);

  // Optional open orders call to ensure trade permissions
  const ordersUrl = `${baseUrl}${openOrdersPath}?${query}&signature=${signature}`;
  const ordersRes = await fetch(ordersUrl, { headers });
  const ordersText = await ordersRes.text();
  if (!ordersRes.ok) {
    throw new Error(`binanceusdm ${ordersText}`);
  }

  const balance =
    parseFloat(account.totalWalletBalance ?? account.totalMarginBalance ?? 0) || 0;

  return {
    valid: true,
    permissions: ['read', 'trade'],
    balance,
    currency: 'USDT',
    accountConnected: true,
    meta: { baseUrl },
  };
}
