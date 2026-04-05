/**
 * Deployment API Routes
 * 
 * Endpoints for mounting/unmounting profiles to exchange configs.
 * This connects a specific profile version to an exchange for trading.
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import * as BotExchangeConfig from '../models/BotExchangeConfig.js';
import * as UserProfile from '../models/UserProfile.js';
import auditService from '../services/auditService.js';
import pool from '../config/database.js';

const router = express.Router();

// All routes require authentication
router.use(authenticateToken);

/**
 * POST /api/deployment/mount
 * Mount a profile to an exchange config
 */
router.post('/mount', async (req, res) => {
  try {
    const userId = req.user.userId;
    const { exchangeConfigId, profileId } = req.body;
    
    if (!exchangeConfigId) {
      return res.status(400).json({
        success: false,
        error: 'exchangeConfigId is required',
      });
    }
    
    if (!profileId) {
      return res.status(400).json({
        success: false,
        error: 'profileId is required',
      });
    }
    
    // Verify the exchange config belongs to the user
    const config = await BotExchangeConfig.getConfigById(exchangeConfigId);
    if (!config) {
      return res.status(404).json({
        success: false,
        error: 'Exchange config not found',
      });
    }
    
    if (config.user_id !== userId) {
      return res.status(403).json({
        success: false,
        error: 'Access denied to this exchange config',
      });
    }
    
    // Verify the profile belongs to the user
    const profile = await UserProfile.getProfileByIdAndUser(profileId, userId);
    if (!profile) {
      return res.status(404).json({
        success: false,
        error: 'Profile not found',
      });
    }
    
    // Validate environment compatibility (done by database trigger, but good UX to check here)
    const configEnv = config.environment;
    const profileEnv = profile.environment;
    
    if (profileEnv === 'live' && configEnv !== 'live') {
      return res.status(400).json({
        success: false,
        error: 'Live profiles can only be mounted on live exchange configs',
      });
    }
    
    if (profileEnv === 'dev' && configEnv === 'live') {
      return res.status(400).json({
        success: false,
        error: 'Dev profiles cannot be mounted on live exchange configs',
      });
    }
    
    if (profileEnv === 'paper' && configEnv === 'live') {
      return res.status(400).json({
        success: false,
        error: 'Paper profiles cannot be mounted on live exchange configs. Promote to Live first.',
      });
    }
    
    // Mount the profile
    const result = await pool.query(
      `UPDATE bot_exchange_configs
       SET mounted_profile_id = $1, 
           mounted_profile_version = $2,
           mounted_at = NOW(),
           updated_at = NOW()
       WHERE id = $3
       RETURNING *`,
      [profileId, profile.version, exchangeConfigId]
    );
    
    const updatedConfig = result.rows[0];
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'bot_exchange_config',
        resourceId: exchangeConfigId,
        actionType: 'mount_profile',
        actionCategory: 'deployment',
        actionDescription: `Mounted profile "${profile.name}" (v${profile.version}) to exchange config`,
        afterState: {
          profileId,
          profileName: profile.name,
          profileVersion: profile.version,
          profileEnvironment: profile.environment,
        },
        actionDetails: {
          exchange: config.exchange,
          environment: config.environment,
        },
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      config: updatedConfig,
      message: `Profile "${profile.name}" mounted successfully`,
    });
  } catch (error) {
    console.error('Error mounting profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to mount profile',
      message: error.message,
    });
  }
});

/**
 * POST /api/deployment/unmount
 * Unmount a profile from an exchange config
 */
router.post('/unmount', async (req, res) => {
  try {
    const userId = req.user.userId;
    const { exchangeConfigId } = req.body;
    
    if (!exchangeConfigId) {
      return res.status(400).json({
        success: false,
        error: 'exchangeConfigId is required',
      });
    }
    
    // Verify the exchange config belongs to the user
    const config = await BotExchangeConfig.getConfigById(exchangeConfigId);
    if (!config) {
      return res.status(404).json({
        success: false,
        error: 'Exchange config not found',
      });
    }
    
    if (config.user_id !== userId) {
      return res.status(403).json({
        success: false,
        error: 'Access denied to this exchange config',
      });
    }
    
    // Get current mounted profile for audit
    const currentProfileId = config.mounted_profile_id;
    let currentProfile = null;
    if (currentProfileId) {
      currentProfile = await UserProfile.getProfileById(currentProfileId);
    }
    
    // Unmount the profile
    const result = await pool.query(
      `UPDATE bot_exchange_configs
       SET mounted_profile_id = NULL, 
           mounted_profile_version = NULL,
           mounted_at = NULL,
           updated_at = NOW()
       WHERE id = $1
       RETURNING *`,
      [exchangeConfigId]
    );
    
    const updatedConfig = result.rows[0];
    
    // Audit log
    if (currentProfile) {
      try {
        await auditService.logAuditEvent({
          userId,
          resourceType: 'bot_exchange_config',
          resourceId: exchangeConfigId,
          actionType: 'unmount_profile',
          actionCategory: 'deployment',
          actionDescription: `Unmounted profile "${currentProfile.name}" from exchange config`,
          beforeState: {
            profileId: currentProfileId,
            profileName: currentProfile.name,
          },
          actionDetails: {
            exchange: config.exchange,
            environment: config.environment,
          },
        });
      } catch (auditError) {
        console.warn('Failed to create audit log:', auditError.message);
      }
    }
    
    res.json({
      success: true,
      config: updatedConfig,
      message: 'Profile unmounted successfully',
    });
  } catch (error) {
    console.error('Error unmounting profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to unmount profile',
      message: error.message,
    });
  }
});

/**
 * GET /api/deployment/status/:exchangeConfigId
 * Get the deployment status of an exchange config
 */
router.get('/status/:exchangeConfigId', async (req, res) => {
  try {
    const userId = req.user.userId;
    const { exchangeConfigId } = req.params;
    
    // Verify the exchange config belongs to the user
    const config = await BotExchangeConfig.getConfigById(exchangeConfigId);
    if (!config) {
      return res.status(404).json({
        success: false,
        error: 'Exchange config not found',
      });
    }
    
    if (config.user_id !== userId) {
      return res.status(403).json({
        success: false,
        error: 'Access denied to this exchange config',
      });
    }
    
    // Get mounted profile details if any
    let mountedProfile = null;
    if (config.mounted_profile_id) {
      mountedProfile = await UserProfile.getProfileById(config.mounted_profile_id);
    }
    
    res.json({
      success: true,
      deployment: {
        exchangeConfigId,
        exchange: config.exchange,
        environment: config.environment,
        state: config.state,
        isActive: config.is_active,
        mountedProfile: mountedProfile ? {
          id: mountedProfile.id,
          name: mountedProfile.name,
          environment: mountedProfile.environment,
          version: config.mounted_profile_version,
          currentVersion: mountedProfile.version,
          isOutdated: config.mounted_profile_version !== mountedProfile.version,
          status: mountedProfile.status,
          isActive: mountedProfile.is_active,
        } : null,
        mountedAt: config.mounted_at,
        lastHeartbeat: config.last_heartbeat_at,
        decisionsCount: config.decisions_count,
        tradesCount: config.trades_count,
      },
    });
  } catch (error) {
    console.error('Error getting deployment status:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to get deployment status',
      message: error.message,
    });
  }
});

/**
 * POST /api/deployment/refresh
 * Refresh the mounted profile to the latest version
 */
router.post('/refresh', async (req, res) => {
  try {
    const userId = req.user.userId;
    const { exchangeConfigId } = req.body;
    
    if (!exchangeConfigId) {
      return res.status(400).json({
        success: false,
        error: 'exchangeConfigId is required',
      });
    }
    
    // Verify the exchange config belongs to the user
    const config = await BotExchangeConfig.getConfigById(exchangeConfigId);
    if (!config) {
      return res.status(404).json({
        success: false,
        error: 'Exchange config not found',
      });
    }
    
    if (config.user_id !== userId) {
      return res.status(403).json({
        success: false,
        error: 'Access denied to this exchange config',
      });
    }
    
    if (!config.mounted_profile_id) {
      return res.status(400).json({
        success: false,
        error: 'No profile is mounted on this exchange config',
      });
    }
    
    // Get the current profile version
    const profile = await UserProfile.getProfileById(config.mounted_profile_id);
    if (!profile) {
      return res.status(404).json({
        success: false,
        error: 'Mounted profile not found',
      });
    }
    
    // Check if already at latest version
    if (config.mounted_profile_version === profile.version) {
      return res.json({
        success: true,
        message: 'Already at the latest version',
        config,
      });
    }
    
    // Update to latest version
    const result = await pool.query(
      `UPDATE bot_exchange_configs
       SET mounted_profile_version = $1, updated_at = NOW()
       WHERE id = $2
       RETURNING *`,
      [profile.version, exchangeConfigId]
    );
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'bot_exchange_config',
        resourceId: exchangeConfigId,
        actionType: 'refresh_profile',
        actionCategory: 'deployment',
        actionDescription: `Refreshed profile "${profile.name}" from v${config.mounted_profile_version} to v${profile.version}`,
        beforeState: { version: config.mounted_profile_version },
        afterState: { version: profile.version },
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      config: result.rows[0],
      message: `Profile refreshed from v${config.mounted_profile_version} to v${profile.version}`,
    });
  } catch (error) {
    console.error('Error refreshing profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to refresh profile',
      message: error.message,
    });
  }
});

/**
 * GET /api/deployment/list
 * List all exchange configs with their deployment status for the user
 */
router.get('/list', async (req, res) => {
  try {
    const userId = req.user.userId;
    const { environment } = req.query;
    
    let query = `
      SELECT 
        bec.*,
        ucp.name as profile_name,
        ucp.environment as profile_environment,
        ucp.version as profile_current_version,
        ucp.status as profile_status,
        ucp.is_active as profile_is_active,
        bi.name as bot_name
      FROM bot_exchange_configs bec
      JOIN bot_instances bi ON bec.bot_instance_id = bi.id
      LEFT JOIN user_chessboard_profiles ucp ON bec.mounted_profile_id = ucp.id
      WHERE bi.user_id = $1
    `;
    const params = [userId];
    
    if (environment) {
      query += ` AND bec.environment = $2`;
      params.push(environment);
    }
    
    query += ` ORDER BY bec.is_active DESC, bec.environment, bec.updated_at DESC`;
    
    const result = await pool.query(query, params);
    
    const deployments = result.rows.map(row => ({
      exchangeConfigId: row.id,
      botName: row.bot_name,
      exchange: row.exchange,
      environment: row.environment,
      state: row.state,
      isActive: row.is_active,
      mountedProfile: row.mounted_profile_id ? {
        id: row.mounted_profile_id,
        name: row.profile_name,
        environment: row.profile_environment,
        mountedVersion: row.mounted_profile_version,
        currentVersion: row.profile_current_version,
        isOutdated: row.mounted_profile_version !== row.profile_current_version,
        status: row.profile_status,
        isActive: row.profile_is_active,
      } : null,
      mountedAt: row.mounted_at,
      lastHeartbeat: row.last_heartbeat_at,
      decisionsCount: row.decisions_count,
      tradesCount: row.trades_count,
    }));
    
    res.json({
      success: true,
      deployments,
      count: deployments.length,
    });
  } catch (error) {
    console.error('Error listing deployments:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to list deployments',
      message: error.message,
    });
  }
});

export default router;


