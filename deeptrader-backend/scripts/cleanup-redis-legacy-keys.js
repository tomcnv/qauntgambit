/**
 * Cleanup script to remove legacy Redis keys that used underscores instead of colons
 * for layer-scoped data (e.g., layer1_context vs layer1:context).
 *
 * Usage:
 *   node scripts/cleanup-redis-legacy-keys.js        # dry-run (default)
 *   node scripts/cleanup-redis-legacy-keys.js --apply # actually delete keys
 */

import redisState from '../services/redisState.js';

const APPLY = process.argv.includes('--apply');

// Legacy patterns that used underscores instead of colons
const LEGACY_PATTERNS = [
  'bot:*:layer1_context*',
  'bot:*:layer2_signal*',
  'bot:*:layer2_signal_history*',
  'bot:*:layer3_execution*',
  'bot:*:layer4_performance*',
  'bot:*:layer4_recent_trades*',
  'bot:*:layer_stats',
];

async function main() {
  const client = await redisState.ensureClient();
  const toDelete = [];

  for (const pattern of LEGACY_PATTERNS) {
    const keys = await client.keys(pattern);
    if (keys.length) {
      console.log(`Found ${keys.length} keys for pattern "${pattern}"`);
      toDelete.push(...keys);
    }
  }

  const uniqueKeys = Array.from(new Set(toDelete));

  if (!uniqueKeys.length) {
    console.log('No legacy keys found. ✅');
    process.exit(0);
  }

  console.log(`\nTotal unique legacy keys: ${uniqueKeys.length}`);
  uniqueKeys.slice(0, 20).forEach((k) => console.log(` - ${k}`));
  if (uniqueKeys.length > 20) {
    console.log(` ... and ${uniqueKeys.length - 20} more`);
  }

  if (!APPLY) {
    console.log('\nDry run complete. Re-run with --apply to delete these keys.');
    process.exit(0);
  }

  // Apply deletions
  const deleted = await client.del(uniqueKeys);
  console.log(`\nDeleted ${deleted} keys. ✅`);
  process.exit(0);
}

main().catch((err) => {
  console.error('❌ Cleanup failed:', err);
  process.exit(1);
});



