/**
 * Profile Install Service
 * 
 * Manages system profile templates that are available to all users.
 * System templates can be cloned by users to create their own customized profiles.
 * 
 * System templates have:
 * - user_id = NULL (not owned by any user)
 * - is_system_template = true
 * - Available to all users via getProfilesByUser() which includes system templates
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

// The 20 canonical chessboard profiles from the DeepTrader whitepaper
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
      risk_per_trade_pct: 0.005,
      max_leverage: 2,
      stop_loss_pct: 0.003,
      take_profit_pct: 0.001,
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
      risk_per_trade_pct: 0.015,
      max_leverage: 3,
      stop_loss_pct: 0.005,
      take_profit_pct: 0.015,
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
      risk_per_trade_pct: 0.01,
      max_leverage: 2,
      stop_loss_pct: 0.008,
      take_profit_pct: 0.01,
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
    conditions: { required_volatility: "high" },
    riskConfig: {
      risk_per_trade_pct: 0.01,
      stop_loss_pct: 0.006,
      take_profit_pct: 0.012,
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
    conditions: { required_volatility: "high" },
    riskConfig: {
      risk_per_trade_pct: 0.02,
      max_leverage: 3,
      stop_loss_pct: 0.007,
      take_profit_pct: 0.02,
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
    conditions: { required_volatility: "medium" },
    riskConfig: {
      risk_per_trade_pct: 0.01,
      stop_loss_pct: 0.005,
      take_profit_pct: 0.008,
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
      risk_per_trade_pct: 0.005,
      stop_loss_pct: 0.002,
      take_profit_pct: 0.001,
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
    conditions: { required_volatility: "high" },
    riskConfig: {
      risk_per_trade_pct: 0.015,
      max_leverage: 2,
      stop_loss_pct: 0.01,
      take_profit_pct: 0.02,
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
      risk_per_trade_pct: 0.008,
      stop_loss_pct: 0.005,
      take_profit_pct: 0.008,
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
      risk_per_trade_pct: 0.015,
      stop_loss_pct: 0.008,
      take_profit_pct: 0.015,
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
      risk_per_trade_pct: 0.02,
      max_leverage: 3,
      stop_loss_pct: 0.01,
      take_profit_pct: 0.02,
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
      risk_per_trade_pct: 0.005,
      max_leverage: 1.5,
      stop_loss_pct: 0.004,
      take_profit_pct: 0.006,
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
      risk_per_trade_pct: 0.003,
      max_leverage: 1.5,
      stop_loss_pct: 0.002,
      take_profit_pct: 0.0008,
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
      risk_per_trade_pct: 0.008,
      max_leverage: 3,
      stop_loss_pct: 0.006,
      take_profit_pct: 0.012,
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
    conditions: { required_volatility: "medium" },
    riskConfig: {
      risk_per_trade_pct: 0.006,
      max_leverage: 2.5,
      stop_loss_pct: 0.005,
      take_profit_pct: 0.008,
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
    conditions: { required_volatility: "medium" },
    riskConfig: {
      risk_per_trade_pct: 0.005,
      max_leverage: 2,
      stop_loss_pct: 0.004,
      take_profit_pct: 0.006,
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
    conditions: { required_volatility: "medium" },
    riskConfig: {
      risk_per_trade_pct: 0.007,
      max_leverage: 2.5,
      stop_loss_pct: 0.006,
      take_profit_pct: 0.01,
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
    conditions: { required_volatility: "high" },
    riskConfig: {
      risk_per_trade_pct: 0.008,
      max_leverage: 3,
      stop_loss_pct: 0.008,
      take_profit_pct: 0.015,
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
    conditions: { required_volatility: "high" },
    riskConfig: {
      risk_per_trade_pct: 0.006,
      max_leverage: 2.5,
      stop_loss_pct: 0.007,
      take_profit_pct: 0.012,
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
    conditions: { required_volatility: "medium" },
    riskConfig: {
      risk_per_trade_pct: 0.007,
      max_leverage: 2.5,
      stop_loss_pct: 0.006,
      take_profit_pct: 0.012,
    },
    lifecycle: { max_hold_seconds: 1800, disable_after_consecutive_losses: 3 },
    execution: { order_type: "market", slippage_tolerance_bps: 10 },
    tags: ["orb", "session_open", "breakout"],
  },
];

let _profileUserIdNullable = null;

async function isProfileUserIdNullable() {
  if (_profileUserIdNullable !== null) return _profileUserIdNullable;
  const result = await pool.query(
    `SELECT is_nullable
       FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'user_chessboard_profiles'
        AND column_name = 'user_id'`
  );
  _profileUserIdNullable = result.rows[0]?.is_nullable === 'YES';
  return _profileUserIdNullable;
}

async function resolveTemplateOwnerUserId() {
  const preferred = process.env.SYSTEM_TEMPLATE_OWNER_ID || process.env.TEMPLATE_OWNER_USER_ID;
  if (preferred) return preferred;
  const fallback = await pool.query(
    `SELECT id FROM users WHERE is_active = true ORDER BY created_at ASC LIMIT 1`
  );
  return fallback.rows[0]?.id || null;
}

/**
 * Check if system templates are already seeded
 */
export async function hasSystemTemplatesSeeded() {
  const result = await pool.query(
    `SELECT COUNT(*) FROM user_chessboard_profiles WHERE is_system_template = true`
  );
  return parseInt(result.rows[0].count) > 0;
}

/**
 * Seed all canonical chessboard profiles as SYSTEM TEMPLATES
 * These are available to all users and can be cloned to create custom profiles.
 * 
 * System templates have:
 * - user_id = NULL
 * - is_system_template = true
 */
export async function seedSystemTemplates() {
  const results = { created: 0, skipped: 0, templates: [] };
  const userIdNullable = await isProfileUserIdNullable();
  const templateOwnerUserId = userIdNullable ? null : await resolveTemplateOwnerUserId();

  if (!userIdNullable && !templateOwnerUserId) {
    throw new Error('Cannot seed system templates: no active user found for non-null user_id schema');
  }

  for (const profile of CANONICAL_PROFILES) {
    const profileId = randomUUID();

    try {
      const result = await pool.query(
        `INSERT INTO user_chessboard_profiles 
         (id, user_id, name, description, base_profile_id, environment, 
          strategy_composition, risk_config, conditions, lifecycle, execution, 
          is_active, status, tags, is_system_template) 
         VALUES ($1, $2, $3, $4, $5, 'dev', $6, $7, $8, $9, $10, false, 'active', $11, true)
         ON CONFLICT DO NOTHING
         RETURNING id, name`,
        [
          profileId,
          templateOwnerUserId,
          profile.name,
          profile.description,
          profile.baseProfileId,
          JSON.stringify([]), // Empty strategy composition - users will customize after cloning
          JSON.stringify(profile.riskConfig || {}),
          JSON.stringify(profile.conditions || {}),
          JSON.stringify(profile.lifecycle || {}),
          JSON.stringify(profile.execution || {}),
          profile.tags || [],
        ]
      );

      if (result.rows.length > 0) {
        results.created++;
        results.templates.push(result.rows[0]);
      } else {
        results.skipped++;
      }
    } catch (error) {
      if (error.code === '23505') {
        // Unique violation - template already exists
        results.skipped++;
      } else {
        throw error;
      }
    }
  }

  return results;
}

/**
 * Ensure system templates are available
 * This is idempotent - will only seed if templates don't exist
 */
export async function ensureSystemTemplates() {
  const alreadySeeded = await hasSystemTemplatesSeeded();
  
  if (alreadySeeded) {
    const count = await pool.query(
      `SELECT COUNT(*) FROM user_chessboard_profiles WHERE is_system_template = true`
    );
    console.log(`[ProfileInstall] System templates already exist (${count.rows[0].count} templates)`);
    return {
      success: true,
      alreadySeeded: true,
      templatesCreated: 0,
      totalTemplates: parseInt(count.rows[0].count),
    };
  }

  console.log(`[ProfileInstall] Seeding system profile templates...`);
  const results = await seedSystemTemplates();
  console.log(`[ProfileInstall] Created ${results.created} system templates`);

  return {
    success: true,
    alreadySeeded: false,
    templatesCreated: results.created,
    templatesSkipped: results.skipped,
    totalTemplates: results.created,
    templates: results.templates,
  };
}

/**
 * Get all available system templates
 */
export async function getSystemTemplates() {
  const result = await pool.query(
    `SELECT * FROM user_chessboard_profiles 
     WHERE is_system_template = true 
     ORDER BY name`
  );
  return result.rows;
}

/**
 * Get installation status - how many templates and user profiles exist
 */
export async function getInstallationStatus(userId) {
  const userProfileCount = await pool.query(
    `SELECT COUNT(*) FROM user_chessboard_profiles WHERE user_id = $1`,
    [userId]
  );

  const systemTemplateCount = await pool.query(
    `SELECT COUNT(*) FROM user_chessboard_profiles WHERE is_system_template = true`
  );

  const strategyTemplateCount = await pool.query(
    `SELECT COUNT(*) FROM strategy_templates WHERE is_active = true`
  );

  return {
    userProfilesCount: parseInt(userProfileCount.rows[0].count),
    systemTemplatesCount: parseInt(systemTemplateCount.rows[0].count),
    strategyTemplatesCount: parseInt(strategyTemplateCount.rows[0].count),
    hasUserProfiles: parseInt(userProfileCount.rows[0].count) > 0,
    hasSystemTemplates: parseInt(systemTemplateCount.rows[0].count) > 0,
  };
}

// Legacy function for backward compatibility - now just ensures system templates exist
export async function installDefaultsForUser(userId) {
  // Ensure system templates are seeded (idempotent)
  const templateResult = await ensureSystemTemplates();
  
  return {
    success: true,
    templatesAvailable: templateResult.totalTemplates,
    templatesCreated: templateResult.templatesCreated,
    alreadySeeded: templateResult.alreadySeeded,
  };
}

export default {
  ensureSystemTemplates,
  seedSystemTemplates,
  hasSystemTemplatesSeeded,
  getSystemTemplates,
  getInstallationStatus,
  installDefaultsForUser, // Legacy - now just ensures system templates exist
  CANONICAL_PROFILES,
};









