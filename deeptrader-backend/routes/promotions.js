/**
 * Promotion Workflow API Routes
 * 
 * Endpoints for:
 * - Creating promotions
 * - Approving/rejecting promotions
 * - Getting promotion history
 * - Config diffing
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import promotionService from '../services/promotionService.js';

const router = express.Router();

/**
 * GET /api/promotions
 * Get promotions with filters
 */
router.get('/', authenticateToken, async (req, res) => {
  try {
    const {
      status,
      promotionType,
      sourceEnvironment,
      targetEnvironment,
      botProfileId,
      requestedBy,
      limit = 100,
    } = req.query;

    const promotions = await promotionService.getPromotions({
      status,
      promotionType,
      sourceEnvironment,
      targetEnvironment,
      botProfileId,
      requestedBy,
      limit: parseInt(limit),
    });

    res.json({
      success: true,
      data: promotions,
      count: promotions.length,
    });
  } catch (error) {
    console.error('Error fetching promotions:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch promotions',
      error: error.message,
    });
  }
});

/**
 * POST /api/promotions
 * Create a new promotion request
 */
router.post('/', authenticateToken, async (req, res) => {
  try {
    const {
      promotionType,
      sourceEnvironment,
      targetEnvironment,
      botProfileId,
      botVersionId,
      backtestSummary,
      paperTradingStats,
      requiresApproval = true,
    } = req.body;

    if (!promotionType || !sourceEnvironment || !targetEnvironment) {
      return res.status(400).json({
        success: false,
        message: 'Missing required fields: promotionType, sourceEnvironment, targetEnvironment',
      });
    }

    const promotion = await promotionService.createPromotion({
      promotionType,
      sourceEnvironment,
      targetEnvironment,
      botProfileId,
      botVersionId,
      requestedBy: req.user.id, // From auth middleware
      backtestSummary,
      paperTradingStats,
      requiresApproval,
    });

    res.status(201).json({
      success: true,
      message: 'Promotion created',
      promotion,
    });
  } catch (error) {
    console.error('Error creating promotion:', error);
    res.status(400).json({
      success: false,
      message: 'Failed to create promotion',
      error: error.message,
    });
  }
});

/**
 * PUT /api/promotions/:id/approve
 * Approve a promotion
 */
router.put('/:id/approve', authenticateToken, async (req, res) => {
  try {
    const { id } = req.params;
    const { approvalNotes } = req.body;

    const promotion = await promotionService.approvePromotion(
      id,
      req.user.id,
      approvalNotes
    );

    res.json({
      success: true,
      message: 'Promotion approved',
      promotion,
    });
  } catch (error) {
    console.error('Error approving promotion:', error);
    res.status(400).json({
      success: false,
      message: 'Failed to approve promotion',
      error: error.message,
    });
  }
});

/**
 * PUT /api/promotions/:id/reject
 * Reject a promotion
 */
router.put('/:id/reject', authenticateToken, async (req, res) => {
  try {
    const { id } = req.params;
    const { rejectionReason } = req.body;

    if (!rejectionReason) {
      return res.status(400).json({
        success: false,
        message: 'Rejection reason is required',
      });
    }

    const promotion = await promotionService.rejectPromotion(
      id,
      req.user.id,
      rejectionReason
    );

    res.json({
      success: true,
      message: 'Promotion rejected',
      promotion,
    });
  } catch (error) {
    console.error('Error rejecting promotion:', error);
    res.status(400).json({
      success: false,
      message: 'Failed to reject promotion',
      error: error.message,
    });
  }
});

/**
 * PUT /api/promotions/:id/complete
 * Complete a promotion (execute it)
 */
router.put('/:id/complete', authenticateToken, async (req, res) => {
  try {
    const { id } = req.params;

    const promotion = await promotionService.completePromotion(
      id,
      req.user.id
    );

    res.json({
      success: true,
      message: 'Promotion completed',
      promotion,
    });
  } catch (error) {
    console.error('Error completing promotion:', error);
    res.status(400).json({
      success: false,
      message: 'Failed to complete promotion',
      error: error.message,
    });
  }
});

/**
 * GET /api/promotions/:id
 * Get specific promotion with history
 */
router.get('/:id', authenticateToken, async (req, res) => {
  try {
    const { id } = req.params;

    const promotions = await promotionService.getPromotions({
      limit: 1,
    });

    const promotion = promotions.find(p => p.id === id);

    if (!promotion) {
      return res.status(404).json({
        success: false,
        message: 'Promotion not found',
      });
    }

    res.json({
      success: true,
      promotion,
    });
  } catch (error) {
    console.error('Error fetching promotion:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch promotion',
      error: error.message,
    });
  }
});

/**
 * GET /api/config/diff
 * Compare two configs/versions
 */
router.get('/config/diff', authenticateToken, async (req, res) => {
  try {
    const { sourceConfigId, targetConfigId } = req.query;

    if (!sourceConfigId || !targetConfigId) {
      return res.status(400).json({
        success: false,
        message: 'Missing required fields: sourceConfigId, targetConfigId',
      });
    }

    const diff = await promotionService.getConfigDiff(
      sourceConfigId,
      targetConfigId
    );

    if (!diff) {
      return res.status(404).json({
        success: false,
        message: 'Config diff not found',
      });
    }

    res.json({
      success: true,
      diff,
    });
  } catch (error) {
    console.error('Error getting config diff:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to get config diff',
      error: error.message,
    });
  }
});

export default router;





