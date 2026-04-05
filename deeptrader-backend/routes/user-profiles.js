/**
 * User Profile API Routes
 * 
 * Endpoints for managing user-customizable trading profiles.
 * Supports versioning, promotion workflow (Dev -> Paper -> Live), and activation.
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import * as UserProfile from '../models/UserProfile.js';
import auditService from '../services/auditService.js';
import profileInstallService from '../services/profileInstallService.js';

const router = express.Router();

// All routes require authentication
router.use(authenticateToken);

function resolveUserId(req) {
  return req?.user?.id || req?.user?.userId || null;
}

/**
 * GET /api/user-profiles
 * List all profiles for the authenticated user
 * Query params: environment, status, isActive
 */
router.get('/', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const { environment, status, isActive } = req.query;

    // Ensure system templates exist before listing profiles. This makes the
    // profiles page self-healing even if exchange-account bootstrap never ran.
    try {
      await profileInstallService.ensureSystemTemplates();
    } catch (templateErr) {
      console.error('[UserProfiles] Failed to ensure system templates:', templateErr);
    }
    
    const profiles = await UserProfile.getProfilesByUser(userId, {
      environment: environment || null,
      status: status || null,
      isActive: isActive === 'true' ? true : isActive === 'false' ? false : null,
    });
    
    res.json({
      success: true,
      profiles,
      count: profiles.length,
    });
  } catch (error) {
    console.error('Error fetching user profiles:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to fetch profiles',
      message: error.message,
    });
  }
});

/**
 * GET /api/user-profiles/:id
 * Get a specific profile with version history
 */
router.get('/:id', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    
    const profile = await UserProfile.getProfileWithVersions(profileId, userId);
    
    if (!profile) {
      return res.status(404).json({
        success: false,
        error: 'Profile not found',
      });
    }
    
    res.json({
      success: true,
      profile,
    });
  } catch (error) {
    console.error('Error fetching profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to fetch profile',
      message: error.message,
    });
  }
});

/**
 * GET /api/user-profiles/:id/diff/:versionA/:versionB
 * Compare two versions of a profile
 */
router.get('/:id/diff/:versionA/:versionB', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const { id: profileId, versionA, versionB } = req.params;
    
    // Verify ownership
    const profile = await UserProfile.getProfileByIdAndUser(profileId, userId);
    if (!profile) {
      return res.status(404).json({
        success: false,
        error: 'Profile not found',
      });
    }
    
    const diff = await UserProfile.compareVersions(
      profileId,
      parseInt(versionA),
      parseInt(versionB)
    );
    
    res.json({
      success: true,
      diff,
    });
  } catch (error) {
    console.error('Error comparing versions:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to compare versions',
      message: error.message,
    });
  }
});

/**
 * POST /api/user-profiles
 * Create a new profile
 */
router.post('/', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const {
      name,
      description,
      baseProfileId,
      environment,
      strategyComposition,
      riskConfig,
      conditions,
      lifecycle,
      execution,
      tags,
    } = req.body;
    
    // Validate required fields
    if (!name) {
      return res.status(400).json({
        success: false,
        error: 'name is required',
      });
    }
    
    // Validate environment
    if (environment && !UserProfile.ENVIRONMENTS.includes(environment)) {
      return res.status(400).json({
        success: false,
        error: `Invalid environment. Must be one of: ${UserProfile.ENVIRONMENTS.join(', ')}`,
      });
    }
    
    const profile = await UserProfile.createProfile({
      userId,
      name,
      description: description || null,
      baseProfileId: baseProfileId || null,
      environment: environment || 'dev',
      strategyComposition: strategyComposition || [],
      riskConfig: riskConfig || {},
      conditions: conditions || {},
      lifecycle: lifecycle || {},
      execution: execution || {},
      tags: tags || [],
    });
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: profile.id,
        actionType: 'create',
        actionCategory: 'profile',
        actionDescription: `Created profile "${name}" in ${environment || 'dev'} environment`,
        afterState: { name, environment: environment || 'dev' },
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.status(201).json({
      success: true,
      profile,
    });
  } catch (error) {
    console.error('Error creating profile:', error);
    
    // Handle unique constraint violation
    if (error.code === '23505') {
      return res.status(409).json({
        success: false,
        error: 'A profile with this name already exists in this environment',
      });
    }
    
    res.status(500).json({
      success: false,
      error: 'Failed to create profile',
      message: error.message,
    });
  }
});

/**
 * PUT /api/user-profiles/:id
 * Update a profile (creates new version automatically)
 */
router.put('/:id', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    const { changeReason, ...updates } = req.body;
    
    // Get current profile for audit
    const currentProfile = await UserProfile.getProfileByIdAndUser(profileId, userId);
    if (!currentProfile) {
      return res.status(404).json({
        success: false,
        error: 'Profile not found',
      });
    }
    
    // Require change reason for Live profiles
    if (currentProfile.environment === 'live' && !changeReason) {
      return res.status(400).json({
        success: false,
        error: 'changeReason is required for Live profile updates',
      });
    }
    
    const profile = await UserProfile.updateProfile(profileId, userId, updates, changeReason);
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: profileId,
        actionType: 'update',
        actionCategory: 'profile',
        actionDescription: `Updated profile "${profile.name}" (v${profile.version})`,
        beforeState: { version: currentProfile.version },
        afterState: { version: profile.version, changeReason },
        actionDetails: { environment: profile.environment },
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      profile,
    });
  } catch (error) {
    console.error('Error updating profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to update profile',
      message: error.message,
    });
  }
});

/**
 * POST /api/user-profiles/:id/clone
 * Clone a profile (system template or own profile) to create a new user profile
 */
router.post('/:id/clone', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const sourceId = req.params.id;
    const { name, environment } = req.body;
    
    const profile = await UserProfile.cloneProfile(sourceId, userId, { name, environment });
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: profile.id,
        actionType: 'clone',
        actionCategory: 'profile',
        actionDescription: `Cloned profile from "${sourceId}" as "${profile.name}"`,
        afterState: { name: profile.name, clonedFrom: sourceId },
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.status(201).json({
      success: true,
      profile,
      message: `Profile cloned as "${profile.name}"`,
    });
  } catch (error) {
    console.error('Error cloning profile:', error);
    res.status(400).json({
      success: false,
      error: 'Failed to clone profile',
      message: error.message,
    });
  }
});

/**
 * POST /api/user-profiles/:id/promote
 * Promote a profile to the next environment (Dev -> Paper -> Live)
 */
router.post('/:id/promote', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    const { notes } = req.body;
    
    const currentProfile = await UserProfile.getProfileByIdAndUser(profileId, userId);
    if (!currentProfile) {
      return res.status(404).json({
        success: false,
        error: 'Profile not found',
      });
    }
    
    const promotedProfile = await UserProfile.promoteProfile(profileId, userId, notes);
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: promotedProfile.id,
        actionType: 'promote',
        actionCategory: 'profile',
        actionDescription: `Promoted profile "${promotedProfile.name}" from ${currentProfile.environment} to ${promotedProfile.environment}`,
        beforeState: { environment: currentProfile.environment },
        afterState: { environment: promotedProfile.environment, notes },
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      profile: promotedProfile,
      message: `Profile promoted to ${promotedProfile.environment}`,
    });
  } catch (error) {
    console.error('Error promoting profile:', error);
    res.status(400).json({
      success: false,
      error: 'Failed to promote profile',
      message: error.message,
    });
  }
});

/**
 * POST /api/user-profiles/:id/activate
 * Activate a profile for trading
 */
router.post('/:id/activate', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    
    const profile = await UserProfile.activateProfile(profileId, userId);
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: profileId,
        actionType: 'activate',
        actionCategory: 'profile',
        actionDescription: `Activated profile "${profile.name}" in ${profile.environment}`,
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      profile,
    });
  } catch (error) {
    console.error('Error activating profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to activate profile',
      message: error.message,
    });
  }
});

/**
 * POST /api/user-profiles/:id/deactivate
 * Deactivate a profile
 */
router.post('/:id/deactivate', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    
    const profile = await UserProfile.deactivateProfile(profileId, userId);
    
    res.json({
      success: true,
      profile,
    });
  } catch (error) {
    console.error('Error deactivating profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to deactivate profile',
      message: error.message,
    });
  }
});

/**
 * POST /api/user-profiles/:id/archive
 * Archive a profile
 */
router.post('/:id/archive', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    
    const profile = await UserProfile.archiveProfile(profileId, userId);
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: profileId,
        actionType: 'archive',
        actionCategory: 'profile',
        actionDescription: `Archived profile "${profile.name}"`,
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      profile,
    });
  } catch (error) {
    console.error('Error archiving profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to archive profile',
      message: error.message,
    });
  }
});

/**
 * DELETE /api/user-profiles/:id
 * Permanently delete a profile (must be archived first)
 */
router.delete('/:id', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) {
      return res.status(401).json({ success: false, error: 'Authentication required' });
    }
    const profileId = req.params.id;
    
    // Get profile name for audit before deletion
    const profile = await UserProfile.getProfileByIdAndUser(profileId, userId);
    
    const result = await UserProfile.deleteProfile(profileId, userId);
    
    // Audit log
    try {
      await auditService.logAuditEvent({
        userId,
        resourceType: 'user_profile',
        resourceId: profileId,
        actionType: 'delete',
        actionCategory: 'profile',
        actionDescription: `Permanently deleted profile "${profile?.name || profileId}"`,
      });
    } catch (auditError) {
      console.warn('Failed to create audit log:', auditError.message);
    }
    
    res.json({
      success: true,
      ...result,
    });
  } catch (error) {
    console.error('Error deleting profile:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to delete profile',
      message: error.message,
    });
  }
});

export default router;
