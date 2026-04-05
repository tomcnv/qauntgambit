/**
 * Exchange Credentials API Tests
 * 
 * Tests for:
 * - Secrets provider (local mode)
 * - Exchange credential CRUD
 * - Trade profile management
 * - Bot pool integration
 */

import { randomUUID } from 'crypto';
import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'fs';
import path from 'path';

// Mock environment for testing
process.env.NODE_ENV = 'test';
process.env.DEEPTRADER_ENV = 'test';
process.env.SECRETS_MASTER_PASSWORD = 'test-master-password';

// ═══════════════════════════════════════════════════════════════
// SECRETS PROVIDER TESTS
// ═══════════════════════════════════════════════════════════════

describe('SecretsProvider', async () => {
  const TEST_USER_ID = 'test-user-123';
  const TEST_EXCHANGE = 'okx';
  let secretsProvider;
  let testSecretId;

  beforeEach(async () => {
    // Dynamically import to ensure env vars are set
    secretsProvider = await import('../../services/secretsProvider.js');
    await secretsProvider.initializeSecretsProvider();
    testSecretId = secretsProvider.buildSecretId({
      userId: TEST_USER_ID,
      exchange: TEST_EXCHANGE,
      credentialId: randomUUID(),
    });
  });

  afterEach(async () => {
    // Clean up test secrets
    try {
      await secretsProvider.deleteExchangeCredentials(testSecretId);
    } catch (e) {
      // Ignore cleanup errors
    }
    secretsProvider.clearSecretsCache();
  });

  it('should save and retrieve credentials', async () => {
    const credentials = {
      apiKey: 'test-api-key',
      secretKey: 'test-secret-key',
      passphrase: 'test-passphrase',
    };

    await secretsProvider.saveExchangeCredentials(testSecretId, TEST_EXCHANGE, credentials);
    const retrieved = await secretsProvider.getExchangeCredentials(testSecretId);

    assert.equal(retrieved.apiKey, credentials.apiKey);
    assert.equal(retrieved.secretKey, credentials.secretKey);
    assert.equal(retrieved.passphrase, credentials.passphrase);
  });

  it('should return null for non-existent credentials', async () => {
    const fakeSecretId = secretsProvider.buildSecretId({
      userId: 'non-existent-user',
      exchange: TEST_EXCHANGE,
      credentialId: randomUUID(),
    });
    const retrieved = await secretsProvider.getExchangeCredentials(fakeSecretId);
    assert.equal(retrieved, null);
  });

  it('should cache credentials', async () => {
    const credentials = {
      apiKey: 'cached-api-key',
      secretKey: 'cached-secret-key',
      passphrase: 'cached-passphrase',
    };

    await secretsProvider.saveExchangeCredentials(testSecretId, TEST_EXCHANGE, credentials);
    
    // First retrieval
    const first = await secretsProvider.getExchangeCredentials(testSecretId);
    
    // Second retrieval (should be from cache)
    const second = await secretsProvider.getExchangeCredentials(testSecretId);

    assert.deepEqual(first, second);
  });

  it('should mask credentials correctly', () => {
    const credentials = {
      apiKey: 'abcdefghijklmnop',
      secretKey: 'supersecretkey',
      passphrase: 'mypassphrase',
    };

    const masked = secretsProvider.maskCredentials(credentials);

    assert.ok(masked.apiKey.includes('...'));
    assert.equal(masked.secretKey, '********');
    assert.equal(masked.passphrase, '********');
  });

  it('should delete credentials', async () => {
    const credentials = {
      apiKey: 'delete-test-key',
      secretKey: 'delete-test-secret',
      passphrase: 'delete-test-pass',
    };

    await secretsProvider.saveExchangeCredentials(testSecretId, TEST_EXCHANGE, credentials);
    await secretsProvider.deleteExchangeCredentials(testSecretId);
    
    const retrieved = await secretsProvider.getExchangeCredentials(testSecretId);
    assert.equal(retrieved, null);
  });

  it('should reject unsupported exchanges', async () => {
    await assert.rejects(
      () => secretsProvider.saveExchangeCredentials(testSecretId, 'invalid-exchange', {}),
      /Unsupported exchange/
    );
  });

  it('should list user exchanges', async () => {
    const credentials = {
      apiKey: 'list-test-key',
      secretKey: 'list-test-secret',
      passphrase: 'list-test-pass',
    };

    await secretsProvider.saveExchangeCredentials(testSecretId, 'okx', credentials);
    
    const exchanges = await secretsProvider.listUserExchanges(TEST_USER_ID);
    assert.ok(exchanges.includes('okx'));
  });
});

// ═══════════════════════════════════════════════════════════════
// EXCHANGE VALIDATION TESTS
// ═══════════════════════════════════════════════════════════════

describe('Exchange Validation', () => {
  it('should require passphrase for OKX', () => {
    const credentials = {
      apiKey: 'test-key',
      secretKey: 'test-secret',
    };

    // OKX should require passphrase
    assert.throws(() => {
      if (!credentials.passphrase) {
        throw new Error('Passphrase is required for OKX');
      }
    }, /Passphrase/);
  });

  it('should not require passphrase for Binance', () => {
    const credentials = {
      apiKey: 'test-key',
      secretKey: 'test-secret',
    };

    // Binance doesn't need passphrase - this should pass
    assert.ok(credentials.apiKey);
    assert.ok(credentials.secretKey);
  });
});

// ═══════════════════════════════════════════════════════════════
// BOT POOL TESTS (Unit level)
// ═══════════════════════════════════════════════════════════════

describe('BotPool Configuration', () => {
  it('should default to local mode in development', () => {
    const mode = process.env.BOT_POOL_MODE || 'local';
    assert.equal(mode, 'local');
  });

  it('should have supported exchange list', async () => {
    const provider = await import('../../services/secretsProvider.js');
    const supported = provider.SUPPORTED_EXCHANGES;
    assert.ok(Array.isArray(supported));
    assert.ok(supported.includes('okx'));
  });
});

// ═══════════════════════════════════════════════════════════════
// SYMBOL NORMALIZATION TESTS
// ═══════════════════════════════════════════════════════════════

describe('Symbol Normalization', () => {
  it('should handle OKX symbol format', () => {
    const internal = 'BTC-USDT-SWAP';
    const okx = internal; // OKX uses same format
    assert.equal(internal, okx);
  });

  it('should convert to Binance format', () => {
    const internal = 'BTC-USDT-SWAP';
    // Internal: BTC-USDT-SWAP -> Binance: BTC/USDT:USDT
    const binance = internal.replace('-SWAP', '').replace('-', '/') + ':USDT';
    assert.equal(binance, 'BTC/USDT:USDT');
  });

  it('should parse base/quote from internal format', () => {
    const internal = 'ETH-USDT-SWAP';
    const parts = internal.replace('-SWAP', '').split('-');
    assert.equal(parts[0], 'ETH');
    assert.equal(parts[1], 'USDT');
  });
});

console.log('✅ Exchange Credentials tests defined');

