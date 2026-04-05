/**
 * Script to verify all Redis keys expected by dashboard are being published by bot
 * Run this while bot is running to check data flow
 * 
 * Usage: node scripts/verify-redis-keys.js [userId]
 *   If userId is provided, checks user-scoped keys (bot:{userId}:*).
 *   If omitted, checks default namespace (bot:default:*).
 */

import redisState, { buildBotKey } from '../services/redisState.js';

// User-scoped key suffixes
const EXPECTED_KEY_SUFFIXES = {
  // Core bot state
  'heartbeat': 'string',
  'positions': 'array',
  'pending_orders': 'array',
  'metrics': 'object',
  'recent_trades': 'array',
  
  // Risk & execution
  'risk': 'object',
  'execution_stats': 'object',
  'exchange_status': 'object',
  'performance': 'object',
  
  // Advanced features
  'stage_rejections': 'object',
  'feature_health': 'object',
  'component_diagnostics': 'object',
  'decision_traces': 'array',
  'allocator': 'object',
  'blade_status': 'object',
  'blade_signals': 'object',
  'blade_metrics': 'object',
  'event_bus': 'object',
  'position_sizing': 'object',
  'protection_status': 'object',
  'resource_usage': 'object',
  
  // Layer-scoped data
  'layer2:signal_history': 'array',
  'layer3:execution_quality': 'object',
  'layer4:recent_trades': 'array',
  
  // Config keys
  'signal_config': 'object',
  'allocator_config': 'object',
};

async function verifyRedisKeys() {
  const userId = process.argv[2] || null;
  const namespace = userId || 'default';
  
  console.log(`🔍 Verifying Redis keys for user: ${namespace}\n`);
  console.log(`   Key prefix: bot:${namespace}:*\n`);
  
  const results = {
    found: [],
    missing: [],
    wrongType: [],
  };
  
  for (const [suffix, expectedType] of Object.entries(EXPECTED_KEY_SUFFIXES)) {
    const key = buildBotKey(userId, suffix);
    try {
      const exists = await redisState.keyExists(key);
      
      if (!exists) {
        results.missing.push(key);
        console.log(`❌ MISSING: ${key}`);
        continue;
      }
      
      const value = await redisState.getJson(key, null);
      
      if (value === null) {
        results.missing.push(key);
        console.log(`❌ NULL: ${key}`);
        continue;
      }
      
      // Check type
      const actualType = Array.isArray(value) ? 'array' : typeof value;
      if (actualType !== expectedType) {
        results.wrongType.push({ key, expected: expectedType, actual: actualType });
        console.log(`⚠️  WRONG TYPE: ${key} (expected ${expectedType}, got ${actualType})`);
        continue;
      }
      
      // Check if empty (might indicate issue)
      const isEmpty = Array.isArray(value) ? value.length === 0 : Object.keys(value).length === 0;
      if (isEmpty) {
        console.log(`⚠️  EMPTY: ${key} (exists but has no data)`);
      } else {
        console.log(`✅ FOUND: ${key} (${actualType}, has data)`);
      }
      
      results.found.push(key);
    } catch (error) {
      console.error(`❌ ERROR checking ${key}:`, error.message);
      results.missing.push(key);
    }
  }
  
  // Check for market context keys (dynamic, user-scoped)
  const contextPrefix = buildBotKey(userId, 'layer1:context:');
  console.log(`\n🔍 Checking market context keys (${contextPrefix}*):`);
  try {
    const client = await redisState.ensureClient();
    const keys = await client.keys(`${contextPrefix}*`);
    if (keys.length > 0) {
      console.log(`✅ Found ${keys.length} market context keys:`);
      for (const key of keys.slice(0, 5)) {
        const context = await redisState.getJson(key, null);
        if (context) {
          const age = context.timestamp ? Date.now() - (context.timestamp > 1e12 ? context.timestamp : context.timestamp * 1000) : null;
          console.log(`   ${key}: age=${age ? Math.round(age / 1000) + 's' : 'unknown'}`);
        }
      }
      if (keys.length > 5) {
        console.log(`   ... and ${keys.length - 5} more`);
      }
    } else {
      console.log('⚠️  No market context keys found for this user');
    }
  } catch (error) {
    console.error('❌ Error checking market context keys:', error.message);
  }
  
  // Summary
  console.log('\n📊 Summary:');
  console.log(`   ✅ Found: ${results.found.length}`);
  console.log(`   ❌ Missing: ${results.missing.length}`);
  console.log(`   ⚠️  Wrong Type: ${results.wrongType.length}`);
  
  if (results.missing.length > 0) {
    console.log('\n❌ Missing keys:');
    results.missing.forEach(key => console.log(`   - ${key}`));
  }
  
  if (results.wrongType.length > 0) {
    console.log('\n⚠️  Wrong type keys:');
    results.wrongType.forEach(({ key, expected, actual }) => {
      console.log(`   - ${key}: expected ${expected}, got ${actual}`);
    });
  }
  
  // Exit with error code if critical keys are missing
  const criticalSuffixes = ['heartbeat', 'metrics', 'positions'];
  const criticalMissing = criticalSuffixes.filter(s => results.missing.includes(buildBotKey(userId, s)));
  if (criticalMissing.length > 0) {
    console.log('\n❌ CRITICAL: Some critical keys are missing!');
    process.exit(1);
  }
  
  process.exit(0);
}

verifyRedisKeys().catch(error => {
  console.error('❌ Fatal error:', error);
  process.exit(1);
});




