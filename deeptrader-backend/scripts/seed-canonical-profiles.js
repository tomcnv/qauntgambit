#!/usr/bin/env node
/**
 * Seed the 20 canonical chessboard profiles into the database
 * These are the market structure patterns from the DeepTrader whitepaper
 */

import pool from '../config/database.js';
import { randomUUID } from 'crypto';

// The 20 canonical profiles from quantgambit-python.
const CANONICAL_PROFILES = [
  {
    id: "micro_range_mean_reversion",
    name: "Micro-Range Mean Reversion",
    description: "Profit from small oscillations in a tight range",
    baseProfileId: "micro_range_mean_reversion",
    conditions: {
      required_volatility: "low",
      max_spread_bps: 5,
      required_trend: "flat",
    },
    riskConfig: {
      risk_per_trade_pct: 0.5,
      max_leverage: 2,
      stop_loss_pct: 0.3,
      take_profit_pct: 0.1,
    },
    lifecycle: {
      warmup_candles: 2,
      disable_after_consecutive_losses: 5,
      max_hold_seconds: 300,
    },
    execution: { order_type: "limit", slippage_tolerance_bps: 3 },
    tags: ["mean_reversion", "low_vol", "scalp"],
  },
  {
    id: "early_trend_ignition",
    name: "Early Trend Ignition",
    description: "Catch momentum at trend start",
    baseProfileId: "early_trend_ignition",
    conditions: {
      required_volatility: "medium",
      required_trend: "any",
    },
    riskConfig: {
      risk_per_trade_pct: 1.5,
      max_leverage: 3,
      stop_loss_pct: 0.5,
      take_profit_pct: 1.5,
    },
    lifecycle: {
      warmup_candles: 2,
      disable_after_consecutive_losses: 3,
      max_hold_seconds: 1800,
    },
    execution: { order_type: "market", slippage_tolerance_bps: 10 },
    tags: ["momentum", "trend", "aggressive"],
  },
  {
    id: "late_trend_exhaustion",
    name: "Late Trend Exhaustion",
    description: "Fade overextended trends",
    baseProfileId: "late_trend_exhaustion",
    conditions: {
      required_volatility: "high",
      required_trend: "any",
    },
    riskConfig: {
      risk_per_trade_pct: 1.0,
      max_leverage: 2,
      stop_loss_pct: 0.8,
      take_profit_pct: 1.0,
    },
    lifecycle: {
      warmup_candles: 2,
      disable_after_consecutive_losses: 4,
      max_hold_seconds: 600,
    },
    execution: { order_type: "limit", slippage_tolerance_bps: 5 },
    tags: ["reversal", "fade", "contrarian"],
  },
  {
    id: "stop_run_fade",
    name: "Stop-Run Fade",
    description: "Fade liquidity hunts and stop runs",
    baseProfileId: "stop_run_fade",
    conditions: {
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 1.0,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.2,
    },
    lifecycle: { disable_after_consecutive_losses: 4 },
    execution: { order_type: "limit", slippage_tolerance_bps: 5 },
    tags: ["reversal", "microstructure"],
  },
  {
    id: "breakout_continuation",
    name: "Breakout Continuation",
    description: "Follow confirmed breakouts",
    baseProfileId: "breakout_continuation",
    conditions: {
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 2.0,
      max_leverage: 3,
      stop_loss_pct: 0.7,
      take_profit_pct: 2.0,
    },
    lifecycle: { disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 15 },
    tags: ["breakout", "momentum"],
  },
  {
    id: "vwap_reversion",
    name: "VWAP Reversion",
    description: "Mean reversion to VWAP",
    baseProfileId: "vwap_reversion",
    conditions: {
      required_volatility: "medium",
    },
    riskConfig: {
      risk_per_trade_pct: 1.0,
      stop_loss_pct: 0.5,
      take_profit_pct: 0.8,
    },
    lifecycle: { disable_after_consecutive_losses: 5 },
    execution: { order_type: "limit", slippage_tolerance_bps: 3 },
    tags: ["mean_reversion", "vwap"],
  },
  {
    id: "spread_compression_scalp",
    name: "Spread Compression Scalp",
    description: "Scalp during tight spreads",
    baseProfileId: "spread_compression_scalp",
    conditions: {
      max_spread_bps: 3,
      required_volatility: "low",
    },
    riskConfig: {
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.2,
      take_profit_pct: 0.1,
    },
    lifecycle: { max_hold_seconds: 60, disable_after_consecutive_losses: 6 },
    execution: { order_type: "limit", slippage_tolerance_bps: 2 },
    tags: ["scalp", "microstructure"],
  },
  {
    id: "vol_expansion_breakout",
    name: "Volatility Expansion Breakout",
    description: "Trade volatility breakouts",
    baseProfileId: "vol_expansion_breakout",
    conditions: {
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 1.5,
      max_leverage: 2,
      stop_loss_pct: 1.0,
      take_profit_pct: 2.0,
    },
    lifecycle: { disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 15 },
    tags: ["volatility", "breakout"],
  },
  {
    id: "asia_range_scalp",
    name: "Asia Range Scalp",
    description: "Range-bound scalping during Asia session",
    baseProfileId: "asia_range_scalp",
    conditions: {
      required_session: "asia",
      required_volatility: "low",
    },
    riskConfig: {
      risk_per_trade_pct: 0.8,
      stop_loss_pct: 0.5,
      take_profit_pct: 0.8,
    },
    lifecycle: { disable_after_consecutive_losses: 4 },
    execution: { order_type: "limit", slippage_tolerance_bps: 3 },
    tags: ["session", "range", "asia"],
  },
  {
    id: "europe_open_vol",
    name: "Europe Open Volatility",
    description: "Trade Europe session volatility",
    baseProfileId: "europe_open_vol",
    conditions: {
      required_session: "europe",
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 1.5,
      stop_loss_pct: 0.8,
      take_profit_pct: 1.5,
    },
    lifecycle: { disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 10 },
    tags: ["session", "volatility", "europe"],
  },
  {
    id: "us_open_momentum",
    name: "US Open Momentum",
    description: "Trade US market open momentum",
    baseProfileId: "us_open_momentum",
    conditions: {
      required_session: "us",
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 2.0,
      max_leverage: 3,
      stop_loss_pct: 1.0,
      take_profit_pct: 2.0,
    },
    lifecycle: { disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 15 },
    tags: ["session", "momentum", "us"],
  },
  {
    id: "overnight_thin",
    name: "Overnight Thin Liquidity",
    description: "Conservative trading during thin overnight hours",
    baseProfileId: "overnight_thin",
    conditions: {
      required_session: "overnight",
      max_spread_bps: 10,
    },
    riskConfig: {
      risk_per_trade_pct: 0.5,
      max_leverage: 1.5,
      stop_loss_pct: 0.4,
      take_profit_pct: 0.6,
    },
    lifecycle: { disable_after_consecutive_losses: 5 },
    execution: { order_type: "limit", slippage_tolerance_bps: 3 },
    tags: ["session", "conservative", "overnight"],
  },
  {
    id: "tight_range_compression",
    name: "Tight Range Compression",
    description: "Scalp ultra-tight spreads in compressed ranges",
    baseProfileId: "tight_range_compression",
    conditions: {
      required_volatility: "low",
      max_spread_bps: 3,
      required_trend: "flat",
    },
    riskConfig: {
      risk_per_trade_pct: 0.3,
      max_leverage: 1.5,
      stop_loss_pct: 0.2,
      take_profit_pct: 0.08,
    },
    lifecycle: { max_hold_seconds: 120, disable_after_consecutive_losses: 4 },
    execution: { order_type: "limit", slippage_tolerance_bps: 2 },
    tags: ["compression", "ultra_low_vol", "hft"],
  },
  {
    id: "range_breakout_anticipation",
    name: "Range Breakout Anticipation",
    description: "Position for breakout from consolidation",
    baseProfileId: "range_breakout_anticipation",
    conditions: {
      required_trend: "flat",
      required_volatility: "medium",
    },
    riskConfig: {
      risk_per_trade_pct: 0.8,
      max_leverage: 3,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.2,
    },
    lifecycle: { max_hold_seconds: 900, disable_after_consecutive_losses: 3 },
    execution: { order_type: "limit", slippage_tolerance_bps: 5 },
    tags: ["breakout", "anticipation", "vol_expansion"],
  },
  {
    id: "value_area_rejection",
    name: "Value Area Rejection Fade",
    description: "Fade price rejections at VAH/VAL boundaries",
    baseProfileId: "value_area_rejection",
    conditions: {
      required_volatility: "medium",
    },
    riskConfig: {
      risk_per_trade_pct: 0.6,
      max_leverage: 2.5,
      stop_loss_pct: 0.5,
      take_profit_pct: 0.8,
    },
    lifecycle: { max_hold_seconds: 600, disable_after_consecutive_losses: 4 },
    execution: { order_type: "limit", slippage_tolerance_bps: 3 },
    tags: ["value_area", "rejection", "mean_reversion"],
  },
  {
    id: "poc_magnet",
    name: "POC Magnet",
    description: "Trade toward Point of Control (magnet effect)",
    baseProfileId: "poc_magnet",
    conditions: {
      required_volatility: "medium",
    },
    riskConfig: {
      risk_per_trade_pct: 0.5,
      max_leverage: 2,
      stop_loss_pct: 0.4,
      take_profit_pct: 0.6,
    },
    lifecycle: { max_hold_seconds: 480, disable_after_consecutive_losses: 5 },
    execution: { order_type: "limit", slippage_tolerance_bps: 3 },
    tags: ["poc", "magnet", "mean_reversion"],
  },
  {
    id: "trend_continuation_pullback",
    name: "Trend Continuation Pullback",
    description: "Buy dips in uptrend / sell rallies in downtrend",
    baseProfileId: "trend_continuation_pullback",
    conditions: {
      required_volatility: "medium",
    },
    riskConfig: {
      risk_per_trade_pct: 0.7,
      max_leverage: 2.5,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.0,
    },
    lifecycle: { max_hold_seconds: 720, disable_after_consecutive_losses: 4 },
    execution: { order_type: "limit", slippage_tolerance_bps: 5 },
    tags: ["trend", "pullback", "continuation"],
  },
  {
    id: "momentum_breakout",
    name: "Momentum Breakout",
    description: "Ride strong momentum breaking value boundaries",
    baseProfileId: "momentum_breakout",
    conditions: {
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 0.8,
      max_leverage: 3,
      stop_loss_pct: 0.8,
      take_profit_pct: 1.5,
    },
    lifecycle: { max_hold_seconds: 600, disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 15 },
    tags: ["momentum", "breakout", "high_vol"],
  },
  {
    id: "trend_acceleration",
    name: "Trend Acceleration",
    description: "Scalp in trend direction during vol spikes",
    baseProfileId: "trend_acceleration",
    conditions: {
      required_volatility: "high",
    },
    riskConfig: {
      risk_per_trade_pct: 0.6,
      max_leverage: 2.5,
      stop_loss_pct: 0.7,
      take_profit_pct: 1.2,
    },
    lifecycle: { max_hold_seconds: 480, disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 10 },
    tags: ["trend", "acceleration", "high_vol"],
  },
  {
    id: "opening_range_breakout",
    name: "Opening Range Breakout",
    description: "Trade breakouts of first 30min range",
    baseProfileId: "opening_range_breakout",
    conditions: {
      required_volatility: "medium",
    },
    riskConfig: {
      risk_per_trade_pct: 0.7,
      max_leverage: 2.5,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.2,
    },
    lifecycle: { max_hold_seconds: 1800, disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 10 },
    tags: ["orb", "session_open", "breakout"],
  },
];

async function seedCanonicalProfiles() {
  try {
    // Get the first user
    const users = await pool.query('SELECT id FROM users LIMIT 1');
    if (users.rows.length === 0) {
      console.error('❌ No users found. Create a user first.');
      process.exit(1);
    }
    const userId = users.rows[0].id;
    console.log('👤 Seeding canonical profiles for user:', userId);
    
    console.log('\n🌱 Seeding 20 canonical chessboard profiles...\n');
    
    let created = 0;
    let skipped = 0;
    
    for (const profile of CANONICAL_PROFILES) {
      const profileId = randomUUID();
      
      try {
        await pool.query(
          `INSERT INTO user_chessboard_profiles 
           (id, user_id, name, description, base_profile_id, environment, 
            strategy_composition, risk_config, conditions, lifecycle, execution, 
            is_active, status, tags) 
           VALUES ($1, $2, $3, $4, $5, 'dev', $6, $7, $8, $9, $10, false, 'active', $11)`,
          [
            profileId,
            userId,
            profile.name,
            profile.description,
            profile.baseProfileId,
            JSON.stringify([]), // strategy_composition - empty for canonical, users will add
            JSON.stringify(profile.riskConfig || {}),
            JSON.stringify(profile.conditions || {}),
            JSON.stringify(profile.lifecycle || {}),
            JSON.stringify(profile.execution || {}),
            profile.tags || [],
          ]
        );
        console.log(`  ✅ ${profile.name}`);
        created++;
      } catch (error) {
        if (error.code === '23505') { // Unique violation
          console.log(`  ⏭️  ${profile.name} (already exists)`);
          skipped++;
        } else {
          throw error;
        }
      }
    }
    
    // Verify
    const count = await pool.query('SELECT COUNT(*) FROM user_chessboard_profiles');
    console.log(`\n📊 Total profiles in database: ${count.rows[0].count}`);
    console.log(`   Created: ${created}, Skipped: ${skipped}`);
    
    console.log('\n✅ Canonical profiles seeded!');
    console.log('   These profiles are ready to be customized with strategy instances.');
  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

seedCanonicalProfiles();
