/**
 * Link strategies to canonical profiles
 * Maps Python profile strategy_ids to database strategy_instance IDs
 */

import pool from '../config/database.js';

// Mapping from Python canonical profiles to their strategy IDs
const PROFILE_STRATEGY_MAPPING = {
  'micro_range_mean_reversion': ['mean_reversion_fade', 'poc_magnet_scalp'],
  'early_trend_ignition': ['trend_pullback', 'breakout_scalp'],
  'late_trend_exhaustion': ['mean_reversion_fade'],
  'stop_run_fade': ['liquidity_hunt'],
  'breakout_continuation': ['breakout_scalp', 'high_vol_breakout'],
  'vwap_reversion': ['vwap_reversion', 'poc_magnet_scalp'],
  'spread_compression_scalp': ['spread_compression'],
  'vol_expansion_breakout': ['vol_expansion', 'high_vol_breakout'],
  'asia_range_scalp': ['asia_range_scalp', 'low_vol_grind'],
  'europe_open_vol': ['europe_open_vol', 'opening_range_breakout'],
  'us_open_momentum': ['us_open_momentum', 'trend_pullback'],
  'overnight_thin': ['overnight_thin', 'low_vol_grind'],
  'tight_range_compression': ['spread_compression', 'low_vol_grind'],
  'range_breakout_anticipation': ['vol_expansion', 'breakout_scalp'],
  'value_area_rejection': ['amt_value_area_rejection_scalp'],
  'poc_magnet': ['poc_magnet_scalp', 'vwap_reversion'],
  'trend_continuation_pullback': ['trend_pullback'],
  'momentum_breakout': ['breakout_scalp', 'high_vol_breakout'],
  'trend_acceleration': ['high_vol_breakout', 'us_open_momentum'],
  'opening_range_breakout': ['opening_range_breakout'],
};

async function linkStrategiesToProfiles() {
  console.log('🔗 Linking strategies to canonical profiles...\n');
  
  // Get all system template strategies by template_id
  const strategiesResult = await pool.query(
    `SELECT id, template_id FROM strategy_instances WHERE is_system_template = true`
  );
  
  // Create lookup map: template_id -> UUID
  const strategyIdMap = {};
  strategiesResult.rows.forEach(s => {
    strategyIdMap[s.template_id] = s.id;
  });
  
  console.log(`📊 Found ${Object.keys(strategyIdMap).length} system template strategies\n`);
  
  // Get all system template profiles
  const profilesResult = await pool.query(
    `SELECT id, name FROM user_chessboard_profiles WHERE is_system_template = true`
  );
  
  let updated = 0;
  let skipped = 0;
  
  for (const profile of profilesResult.rows) {
    // Convert profile name to ID format
    const profileKey = profile.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '');
    
    // Find matching entry in mapping
    let strategyIds = PROFILE_STRATEGY_MAPPING[profileKey];
    
    // Try alternative key formats
    if (!strategyIds) {
      const altKey = profile.name
        .toLowerCase()
        .replace(/ /g, '_')
        .replace(/-/g, '_');
      strategyIds = PROFILE_STRATEGY_MAPPING[altKey];
    }
    
    if (!strategyIds || strategyIds.length === 0) {
      console.log(`  ⚠️  No strategy mapping for: ${profile.name} (${profileKey})`);
      skipped++;
      continue;
    }
    
    // Build strategy_composition array
    const strategyComposition = strategyIds.map((templateId, index) => {
      const instanceId = strategyIdMap[templateId];
      if (!instanceId) {
        console.log(`    ⚠️  Strategy not found: ${templateId}`);
        return null;
      }
      return {
        strategy_instance_id: instanceId,
        weight: 1.0 / strategyIds.length, // Equal weight
        priority: index + 1,
      };
    }).filter(Boolean);
    
    if (strategyComposition.length === 0) {
      console.log(`  ⚠️  No valid strategies for: ${profile.name}`);
      skipped++;
      continue;
    }
    
    // Update profile
    await pool.query(
      `UPDATE user_chessboard_profiles 
       SET strategy_composition = $1, updated_at = NOW()
       WHERE id = $2`,
      [JSON.stringify(strategyComposition), profile.id]
    );
    
    console.log(`  ✅ ${profile.name} → ${strategyComposition.length} strategies`);
    updated++;
  }
  
  console.log(`\n📊 Summary: ${updated} profiles updated, ${skipped} skipped`);
  
  // Verify
  const verify = await pool.query(
    `SELECT name, jsonb_array_length(strategy_composition) as strategy_count 
     FROM user_chessboard_profiles 
     WHERE is_system_template = true
     ORDER BY name`
  );
  
  console.log('\n📋 Final profile strategy counts:');
  verify.rows.forEach(p => {
    console.log(`  - ${p.name}: ${p.strategy_count} strategies`);
  });
  
  await pool.end();
}

linkStrategiesToProfiles().catch(console.error);

