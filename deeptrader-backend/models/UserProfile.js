/**
 * User Profile Model
 * 
 * User-customizable trading profiles with strategy composition,
 * risk controls, market condition gates, and lifecycle rules.
 * Supports Dev -> Paper -> Live promotion workflow.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Valid environments
 */
export const ENVIRONMENTS = ['dev', 'paper', 'live'];

/**
 * Valid statuses
 */
export const STATUSES = ['draft', 'active', 'disabled', 'archived'];

/**
 * Minimum paper burn-in requirements before Live promotion
 */
export const PAPER_BURNIN_REQUIREMENTS = {
  minTrades: 10,
  minDays: 1,
  minPnlPositive: false, // Don't require positive PnL, just experience
};

/**
 * Get all profiles for a user (including system templates)
 */
export async function getProfilesByUser(userId, { environment = null, status = null, isActive = null, includeSystemTemplates = true } = {}) {
  let query = `
    SELECT * FROM user_chessboard_profiles
    WHERE (user_id = $1 ${includeSystemTemplates ? 'OR is_system_template = true' : ''})
  `;
  const params = [userId];
  let paramIndex = 2;
  
  if (environment) {
    query += ` AND environment = $${paramIndex}`;
    params.push(environment);
    paramIndex++;
  }
  
  if (status) {
    query += ` AND status = $${paramIndex}`;
    params.push(status);
    paramIndex++;
  }
  
  if (isActive !== null) {
    query += ` AND is_active = $${paramIndex}`;
    params.push(isActive);
    paramIndex++;
  }
  
  query += ` ORDER BY is_system_template DESC, environment, updated_at DESC`;
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Get system templates only
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
 * Clone a profile (system template or own profile) to create a new user profile
 */
export async function cloneProfile(sourceProfileId, userId, { name = null, environment = 'dev' } = {}) {
  // Get source profile (can be system template or user's own)
  const source = await pool.query(
    `SELECT * FROM user_chessboard_profiles 
     WHERE id = $1 AND (user_id = $2 OR is_system_template = true)`,
    [sourceProfileId, userId]
  );
  
  if (source.rows.length === 0) {
    throw new Error('Source profile not found or access denied');
  }
  
  const srcProfile = source.rows[0];
  const newName = name || `${srcProfile.name} (Copy)`;
  
  const newId = randomUUID();
  const result = await pool.query(
    `INSERT INTO user_chessboard_profiles (
      id, user_id, name, description, base_profile_id, environment,
      strategy_composition, risk_config, conditions, lifecycle, execution,
      status, tags, is_system_template
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'draft', $12, false)
    RETURNING *`,
    [
      newId,
      userId,
      newName,
      srcProfile.description,
      srcProfile.base_profile_id || srcProfile.id, // Track which template it came from
      environment,
      JSON.stringify(srcProfile.strategy_composition || []),
      JSON.stringify(srcProfile.risk_config || {}),
      JSON.stringify(srcProfile.conditions || {}),
      JSON.stringify(srcProfile.lifecycle || {}),
      JSON.stringify(srcProfile.execution || {}),
      srcProfile.tags || [],
    ]
  );
  
  return result.rows[0];
}

/**
 * Get a profile by ID
 */
export async function getProfileById(profileId) {
  const result = await pool.query(
    `SELECT * FROM user_chessboard_profiles WHERE id = $1`,
    [profileId]
  );
  return result.rows[0] || null;
}

/**
 * Get a profile by ID, verifying user ownership
 */
export async function getProfileByIdAndUser(profileId, userId) {
  const result = await pool.query(
    `SELECT * FROM user_chessboard_profiles WHERE id = $1 AND user_id = $2`,
    [profileId, userId]
  );
  return result.rows[0] || null;
}

/**
 * Get profile with version history
 */
export async function getProfileWithVersions(profileId, userId) {
  const profile = await getProfileByIdAndUser(profileId, userId);
  if (!profile) return null;
  
  const versions = await pool.query(
    `SELECT * FROM profile_versions 
     WHERE profile_id = $1 
     ORDER BY version DESC`,
    [profileId]
  );
  
  return {
    ...profile,
    versions: versions.rows,
  };
}

/**
 * Create a new profile
 */
export async function createProfile({
  userId,
  name,
  description = null,
  baseProfileId = null,
  environment = 'dev',
  strategyComposition = [],
  riskConfig = {},
  conditions = {},
  lifecycle = {},
  execution = {},
  tags = [],
}) {
  const profileId = randomUUID();
  
  // Set default risk config
  const defaultRiskConfig = {
    risk_per_trade_pct: 0.01,
    max_leverage: 1.0,
    max_positions: 4,
    stop_loss_pct: 0.005,
    take_profit_pct: 0.015,
    max_drawdown_pct: 0.05,
    max_daily_loss_pct: 0.03,
    ...riskConfig,
  };
  
  // Set default conditions
  const defaultConditions = {
    required_session: 'any',
    required_volatility: 'any',
    required_trend: 'any',
    max_spread_bps: 20,
    min_depth_usd: 5000,
    ...conditions,
  };
  
  // Set default lifecycle
  const defaultLifecycle = {
    cooldown_seconds: 60,
    disable_after_consecutive_losses: 5,
    protection_mode_threshold_pct: 50,
    warmup_seconds: 300,
    max_trades_per_hour: 20,
    ...lifecycle,
  };
  
  // Set default execution
  const defaultExecution = {
    order_type_preference: 'bracket',
    maker_taker_bias: 0.5,
    max_slippage_bps: 5,
    time_in_force: 'GTC',
    reduce_only_exits: true,
    ...execution,
  };
  
  const result = await pool.query(
    `INSERT INTO user_chessboard_profiles (
      id, user_id, name, description, base_profile_id, environment,
      strategy_composition, risk_config, conditions, lifecycle, execution, tags
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    RETURNING *`,
    [
      profileId,
      userId,
      name,
      description,
      baseProfileId,
      environment,
      JSON.stringify(strategyComposition),
      JSON.stringify(defaultRiskConfig),
      JSON.stringify(defaultConditions),
      JSON.stringify(defaultLifecycle),
      JSON.stringify(defaultExecution),
      tags,
    ]
  );
  
  return result.rows[0];
}

/**
 * Update a profile (creates new version automatically via trigger)
 */
export async function updateProfile(profileId, userId, updates, changeReason = null) {
  const allowedFields = [
    'name', 'description', 'strategy_composition', 'risk_config',
    'conditions', 'lifecycle', 'execution', 'status', 'is_active', 'tags',
  ];
  
  const setClause = [];
  const values = [];
  let paramIndex = 1;
  
  for (const [key, value] of Object.entries(updates)) {
    const dbKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
    if (allowedFields.includes(dbKey)) {
      setClause.push(`${dbKey} = $${paramIndex}`);
      values.push(
        typeof value === 'object' && !Array.isArray(value)
          ? JSON.stringify(value)
          : Array.isArray(value) && dbKey !== 'tags'
          ? JSON.stringify(value)
          : value
      );
      paramIndex++;
    }
  }
  
  if (setClause.length === 0) {
    throw new Error('No valid fields to update');
  }
  
  values.push(profileId);
  values.push(userId);
  
  const result = await pool.query(
    `UPDATE user_chessboard_profiles
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex} AND user_id = $${paramIndex + 1}
     RETURNING *`,
    values
  );
  
  if (result.rows.length === 0) {
    throw new Error('Profile not found or access denied');
  }
  
  // Update the change reason in the version history
  if (changeReason) {
    await pool.query(
      `UPDATE profile_versions 
       SET change_reason = $1 
       WHERE profile_id = $2 AND version = $3`,
      [changeReason, profileId, result.rows[0].version]
    );
  }
  
  return result.rows[0];
}

/**
 * Promote a profile to the next environment
 * Dev -> Paper -> Live
 */
export async function promoteProfile(profileId, userId, notes = null) {
  const profile = await getProfileByIdAndUser(profileId, userId);
  if (!profile) {
    throw new Error('Profile not found or access denied');
  }
  
  const currentEnv = profile.environment;
  let nextEnv;
  
  switch (currentEnv) {
    case 'dev':
      nextEnv = 'paper';
      break;
    case 'paper':
      nextEnv = 'live';
      // Check burn-in requirements
      if (profile.paper_trades_count < PAPER_BURNIN_REQUIREMENTS.minTrades) {
        throw new Error(
          `Cannot promote to Live: need at least ${PAPER_BURNIN_REQUIREMENTS.minTrades} paper trades ` +
          `(current: ${profile.paper_trades_count})`
        );
      }
      if (profile.paper_start_at) {
        const paperDays = (Date.now() - new Date(profile.paper_start_at).getTime()) / (1000 * 60 * 60 * 24);
        if (paperDays < PAPER_BURNIN_REQUIREMENTS.minDays) {
          throw new Error(
            `Cannot promote to Live: need at least ${PAPER_BURNIN_REQUIREMENTS.minDays} day(s) of paper trading ` +
            `(current: ${paperDays.toFixed(1)} days)`
          );
        }
      }
      break;
    case 'live':
      throw new Error('Profile is already at Live environment');
    default:
      throw new Error(`Unknown environment: ${currentEnv}`);
  }
  
  // Check if promoted version already exists
  const existing = await pool.query(
    `SELECT id FROM user_chessboard_profiles 
     WHERE user_id = $1 AND name = $2 AND environment = $3`,
    [userId, profile.name, nextEnv]
  );
  
  if (existing.rows.length > 0) {
    // Update existing promoted profile
    const result = await pool.query(
      `UPDATE user_chessboard_profiles
       SET strategy_composition = $1,
           risk_config = $2,
           conditions = $3,
           lifecycle = $4,
           execution = $5,
           promoted_from_id = $6,
           promoted_at = NOW(),
           promotion_notes = $7,
           version = version + 1,
           updated_at = NOW()
       WHERE id = $8
       RETURNING *`,
      [
        JSON.stringify(profile.strategy_composition),
        JSON.stringify(profile.risk_config),
        JSON.stringify(profile.conditions),
        JSON.stringify(profile.lifecycle),
        JSON.stringify(profile.execution),
        profileId,
        notes,
        existing.rows[0].id,
      ]
    );
    return result.rows[0];
  }
  
  // Create new promoted profile
  const newProfileId = randomUUID();
  const result = await pool.query(
    `INSERT INTO user_chessboard_profiles (
      id, user_id, name, description, base_profile_id, environment,
      strategy_composition, risk_config, conditions, lifecycle, execution,
      status, promoted_from_id, promoted_at, promotion_notes, tags,
      paper_start_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), $14, $15, $16)
    RETURNING *`,
    [
      newProfileId,
      userId,
      profile.name,
      profile.description,
      profile.base_profile_id,
      nextEnv,
      JSON.stringify(profile.strategy_composition),
      JSON.stringify(profile.risk_config),
      JSON.stringify(profile.conditions),
      JSON.stringify(profile.lifecycle),
      JSON.stringify(profile.execution),
      'draft',
      profileId,
      notes,
      profile.tags,
      nextEnv === 'paper' ? new Date() : null,
    ]
  );
  
  return result.rows[0];
}

/**
 * Activate a profile for trading
 * 
 * NOTE: Multiple profiles CAN be active simultaneously!
 * The Profile Router dynamically selects the best profile based on
 * current market conditions (the "chessboard" concept).
 * 
 * Activating a profile adds it to the pool of profiles the router considers.
 */
export async function activateProfile(profileId, userId) {
  const profile = await getProfileByIdAndUser(profileId, userId);
  if (!profile) {
    throw new Error('Profile not found or access denied');
  }
  
  if (profile.status === 'archived') {
    throw new Error('Cannot activate an archived profile');
  }
  
  // Simply activate this profile - do NOT deactivate others!
  // The Profile Router will score all active profiles and select
  // the best match for current market conditions.
  const result = await pool.query(
    `UPDATE user_chessboard_profiles
     SET is_active = true, status = 'active'
     WHERE id = $1
     RETURNING *`,
    [profileId]
  );
  
  return result.rows[0];
}

/**
 * Deactivate a profile
 */
export async function deactivateProfile(profileId, userId) {
  const result = await pool.query(
    `UPDATE user_chessboard_profiles
     SET is_active = false
     WHERE id = $1 AND user_id = $2
     RETURNING *`,
    [profileId, userId]
  );
  
  if (result.rows.length === 0) {
    throw new Error('Profile not found or access denied');
  }
  
  return result.rows[0];
}

/**
 * Archive a profile
 */
export async function archiveProfile(profileId, userId) {
  // Check if profile is mounted anywhere
  const mounted = await pool.query(
    `SELECT bec.id, bi.name as bot_name
     FROM bot_exchange_configs bec
     JOIN bot_instances bi ON bec.bot_instance_id = bi.id
     WHERE bec.mounted_profile_id = $1`,
    [profileId]
  );
  
  if (mounted.rows.length > 0) {
    throw new Error('Cannot archive: profile is mounted on exchange configs. Unmount first.');
  }
  
  const result = await pool.query(
    `UPDATE user_chessboard_profiles
     SET status = 'archived', is_active = false
     WHERE id = $1 AND user_id = $2
     RETURNING *`,
    [profileId, userId]
  );
  
  if (result.rows.length === 0) {
    throw new Error('Profile not found or access denied');
  }
  
  return result.rows[0];
}

/**
 * Compare two versions of a profile
 */
export async function compareVersions(profileId, versionA, versionB) {
  const versions = await pool.query(
    `SELECT * FROM profile_versions 
     WHERE profile_id = $1 AND version IN ($2, $3)
     ORDER BY version`,
    [profileId, versionA, versionB]
  );
  
  if (versions.rows.length !== 2) {
    throw new Error('One or both versions not found');
  }
  
  const [older, newer] = versions.rows;
  const diff = {
    versionA: older.version,
    versionB: newer.version,
    changes: [],
  };
  
  // Compare each config section
  const sections = ['strategy_composition', 'risk_config', 'conditions', 'lifecycle', 'execution'];
  
  for (const section of sections) {
    const oldVal = JSON.stringify(older.config_snapshot[section] || {});
    const newVal = JSON.stringify(newer.config_snapshot[section] || {});
    
    if (oldVal !== newVal) {
      diff.changes.push({
        field: section,
        from: older.config_snapshot[section],
        to: newer.config_snapshot[section],
      });
    }
  }
  
  return diff;
}

/**
 * Update paper trading stats
 */
export async function updatePaperStats(profileId, tradesCount, pnlDelta) {
  await pool.query(
    `UPDATE user_chessboard_profiles
     SET paper_trades_count = paper_trades_count + $1,
         paper_pnl_total = paper_pnl_total + $2,
         paper_start_at = COALESCE(paper_start_at, NOW())
     WHERE id = $3`,
    [tradesCount, pnlDelta, profileId]
  );
}

/**
 * Delete a profile permanently (only if archived)
 */
export async function deleteProfile(profileId, userId) {
  const profile = await getProfileByIdAndUser(profileId, userId);
  if (!profile) {
    throw new Error('Profile not found or access denied');
  }
  
  if (profile.status !== 'archived') {
    throw new Error('Only archived profiles can be permanently deleted');
  }
  
  // Delete versions first (cascade should handle this, but being explicit)
  await pool.query('DELETE FROM profile_versions WHERE profile_id = $1', [profileId]);
  
  await pool.query(
    'DELETE FROM user_chessboard_profiles WHERE id = $1 AND user_id = $2',
    [profileId, userId]
  );
  
  return { deleted: true, id: profileId };
}

export default {
  getProfilesByUser,
  getSystemTemplates,
  cloneProfile,
  getProfileById,
  getProfileByIdAndUser,
  getProfileWithVersions,
  createProfile,
  updateProfile,
  promoteProfile,
  activateProfile,
  deactivateProfile,
  archiveProfile,
  compareVersions,
  updatePaperStats,
  deleteProfile,
  ENVIRONMENTS,
  STATUSES,
  PAPER_BURNIN_REQUIREMENTS,
};

