/**
 * Promotion Workflow Service
 * 
 * Handles:
 * - Promotion workflow (Research → Paper → Live)
 * - Approval system
 * - Config diffing
 * - Risk assessment
 */

import pool from '../config/database.js';

/**
 * Create a promotion request
 */
async function createPromotion(params) {
  const {
    promotionType,
    sourceEnvironment,
    targetEnvironment,
    botProfileId,
    botVersionId,
    requestedBy,
    backtestSummary = null,
    paperTradingStats = null,
    requiresApproval = true,
  } = params;

  try {
    // Validate promotion type
    const validTypes = ['research_to_paper', 'paper_to_live', 'rollback'];
    if (!validTypes.includes(promotionType)) {
      throw new Error(`Invalid promotion type: ${promotionType}`);
    }

    // Validate environment transition
    const validTransitions = {
      'research_to_paper': { from: 'research', to: 'paper' },
      'paper_to_live': { from: 'paper', to: 'live' },
      'rollback': { from: 'live', to: 'paper' },
    };

    const transition = validTransitions[promotionType];
    if (sourceEnvironment !== transition.from || targetEnvironment !== transition.to) {
      throw new Error(`Invalid environment transition: ${sourceEnvironment} → ${targetEnvironment}`);
    }

    // Get config diff if promoting a version
    let configDiff = null;
    if (botVersionId) {
      configDiff = await generateConfigDiff(botProfileId, botVersionId);
    }

    // Create promotion record
    const result = await pool.query(
      `INSERT INTO promotions (
        promotion_type, source_environment, target_environment,
        bot_profile_id, bot_version_id, requested_by,
        backtest_summary, paper_trading_stats, config_diff,
        requires_approval, status
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
      RETURNING *`,
      [
        promotionType,
        sourceEnvironment,
        targetEnvironment,
        botProfileId,
        botVersionId,
        requestedBy,
        backtestSummary ? JSON.stringify(backtestSummary) : null,
        paperTradingStats ? JSON.stringify(paperTradingStats) : null,
        configDiff ? JSON.stringify(configDiff) : null,
        requiresApproval,
        requiresApproval ? 'pending' : 'approved',
      ]
    );

    const promotion = result.rows[0];

    // Create approval if required
    if (requiresApproval) {
      await createApproval({
        promotionId: promotion.id,
        actionType: 'promote',
        actionDescription: `Promote ${promotionType.replace('_', ' ')}`,
        riskLevel: targetEnvironment === 'live' ? 'high' : 'medium',
        requestedBy,
        requiresDifferentRole: targetEnvironment === 'live',
      });
    }

    // Log promotion history
    await logPromotionHistory({
      promotionId: promotion.id,
      eventType: 'created',
      eventDescription: `Promotion created: ${sourceEnvironment} → ${targetEnvironment}`,
      performedBy: requestedBy,
    });

    return promotion;
  } catch (error) {
    console.error('Error creating promotion:', error);
    throw error;
  }
}

/**
 * Generate config diff between versions
 */
async function generateConfigDiff(botProfileId, targetVersionId) {
  return null;
}

/**
 * Compare risk parameters
 */
function compareRiskParams(source, target) {
  const riskParams = ['maxDailyLoss', 'maxPositionSize', 'maxTotalExposure', 'maxPositions'];
  const changes = {};

  for (const param of riskParams) {
    if (source[param] !== target[param]) {
      changes[param] = {
        from: source[param],
        to: target[param],
      };
    }
  }

  return changes;
}

/**
 * Compare feature flags
 */
function compareFeatureFlags(source, target) {
  const flags = source.featureFlags || {};
  const targetFlags = target.featureFlags || {};
  const changes = {};

  for (const [flag, value] of Object.entries(targetFlags)) {
    if (flags[flag] !== value) {
      changes[flag] = {
        from: flags[flag],
        to: value,
      };
    }
  }

  return changes;
}

/**
 * Compare profiles
 */
function compareProfiles(source, target) {
  const sourceProfiles = source.enabledProfiles || [];
  const targetProfiles = target.enabledProfiles || [];

  return {
    added: targetProfiles.filter(p => !sourceProfiles.includes(p)),
    removed: sourceProfiles.filter(p => !targetProfiles.includes(p)),
    unchanged: sourceProfiles.filter(p => targetProfiles.includes(p)),
  };
}

/**
 * Compare symbols
 */
function compareSymbols(source, target) {
  const sourceSymbols = source.enabledSymbols || [];
  const targetSymbols = target.enabledSymbols || [];

  return {
    added: targetSymbols.filter(s => !sourceSymbols.includes(s)),
    removed: sourceSymbols.filter(s => !targetSymbols.includes(s)),
    unchanged: sourceSymbols.filter(s => targetSymbols.includes(s)),
  };
}

/**
 * Create approval request
 */
async function createApproval(params) {
  const {
    promotionId,
    actionType,
    actionDescription,
    riskLevel,
    requestedBy,
    requiresDifferentRole = false,
    metadata = null,
  } = params;

  try {
    const result = await pool.query(
      `INSERT INTO approvals (
        promotion_id, action_type, action_description,
        risk_level, requested_by, requires_different_role,
        approval_required, metadata, status
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
      RETURNING *`,
      [
        promotionId,
        actionType,
        actionDescription,
        riskLevel,
        requestedBy,
        requiresDifferentRole,
        true,
        metadata ? JSON.stringify(metadata) : null,
        'pending',
      ]
    );

    return result.rows[0];
  } catch (error) {
    console.error('Error creating approval:', error);
    throw error;
  }
}

/**
 * Approve promotion
 */
async function approvePromotion(promotionId, approverId, approvalNotes = null) {
  try {
    // Update promotion
    const promotionResult = await pool.query(
      `UPDATE promotions
       SET status = 'approved',
           approved_by = $1,
           approved_at = CURRENT_TIMESTAMP,
           approval_notes = $2,
           updated_at = CURRENT_TIMESTAMP
       WHERE id = $3
       RETURNING *`,
      [approverId, approvalNotes, promotionId]
    );

    if (promotionResult.rows.length === 0) {
      throw new Error(`Promotion not found: ${promotionId}`);
    }

    // Update approval
    await pool.query(
      `UPDATE approvals
       SET status = 'approved',
           approver_id = $1,
           approved_at = CURRENT_TIMESTAMP,
           updated_at = CURRENT_TIMESTAMP
       WHERE promotion_id = $2 AND status = 'pending'`,
      [approverId, promotionId]
    );

    // Log history
    await logPromotionHistory({
      promotionId,
      eventType: 'approved',
      eventDescription: `Promotion approved by user ${approverId}`,
      performedBy: approverId,
    });

    return promotionResult.rows[0];
  } catch (error) {
    console.error('Error approving promotion:', error);
    throw error;
  }
}

/**
 * Reject promotion
 */
async function rejectPromotion(promotionId, rejectedBy, rejectionReason) {
  try {
    // Update promotion
    const promotionResult = await pool.query(
      `UPDATE promotions
       SET status = 'rejected',
           rejected_by = $1,
           rejected_at = CURRENT_TIMESTAMP,
           rejection_reason = $2,
           updated_at = CURRENT_TIMESTAMP
       WHERE id = $3
       RETURNING *`,
      [rejectedBy, rejectionReason, promotionId]
    );

    if (promotionResult.rows.length === 0) {
      throw new Error(`Promotion not found: ${promotionId}`);
    }

    // Update approval
    await pool.query(
      `UPDATE approvals
       SET status = 'rejected',
           approver_id = $1,
           rejected_at = CURRENT_TIMESTAMP,
           rejection_reason = $2,
           updated_at = CURRENT_TIMESTAMP
       WHERE promotion_id = $3 AND status = 'pending'`,
      [rejectedBy, rejectionReason, promotionId]
    );

    // Log history
    await logPromotionHistory({
      promotionId,
      eventType: 'rejected',
      eventDescription: `Promotion rejected: ${rejectionReason}`,
      performedBy: rejectedBy,
    });

    return promotionResult.rows[0];
  } catch (error) {
    console.error('Error rejecting promotion:', error);
    throw error;
  }
}

/**
 * Complete promotion (execute the promotion)
 */
async function completePromotion(promotionId, completedBy) {
  try {
    // Update promotion
    const promotionResult = await pool.query(
      `UPDATE promotions
       SET status = 'completed',
           completed_at = CURRENT_TIMESTAMP,
           updated_at = CURRENT_TIMESTAMP
       WHERE id = $1 AND status = 'approved'
       RETURNING *`,
      [promotionId]
    );

    if (promotionResult.rows.length === 0) {
      throw new Error(`Promotion not found or not approved: ${promotionId}`);
    }

    const promotion = promotionResult.rows[0];

    // Promotion execution is handled by QuantGambit runtime/config APIs.

    // Log history
    await logPromotionHistory({
      promotionId,
      eventType: 'completed',
      eventDescription: `Promotion completed: ${promotion.source_environment} → ${promotion.target_environment}`,
      performedBy: completedBy,
    });

    return promotion;
  } catch (error) {
    console.error('Error completing promotion:', error);
    throw error;
  }
}

/**
 * Get promotions with filters
 */
async function getPromotions(filters = {}) {
  const {
    status,
    promotionType,
    sourceEnvironment,
    targetEnvironment,
    botProfileId,
    requestedBy,
    limit = 100,
  } = filters;

  let query = `SELECT * FROM promotions WHERE 1=1`;
  const queryParams = [];
  let paramIndex = 1;

  if (status) {
    query += ` AND status = $${paramIndex}`;
    queryParams.push(status);
    paramIndex++;
  }

  if (promotionType) {
    query += ` AND promotion_type = $${paramIndex}`;
    queryParams.push(promotionType);
    paramIndex++;
  }

  if (sourceEnvironment) {
    query += ` AND source_environment = $${paramIndex}`;
    queryParams.push(sourceEnvironment);
    paramIndex++;
  }

  if (targetEnvironment) {
    query += ` AND target_environment = $${paramIndex}`;
    queryParams.push(targetEnvironment);
    paramIndex++;
  }

  if (botProfileId) {
    query += ` AND bot_profile_id = $${paramIndex}`;
    queryParams.push(botProfileId);
    paramIndex++;
  }

  if (requestedBy) {
    query += ` AND requested_by = $${paramIndex}`;
    queryParams.push(requestedBy);
    paramIndex++;
  }

  query += ` ORDER BY requested_at DESC LIMIT $${paramIndex}`;
  queryParams.push(limit);

  const result = await pool.query(query, queryParams);
  return result.rows;
}

/**
 * Get config diff
 */
async function getConfigDiff(sourceConfigId, targetConfigId) {
  try {
    const result = await pool.query(
      `SELECT * FROM config_diffs
       WHERE (source_config_id = $1 AND target_config_id = $2)
          OR (source_config_id = $2 AND target_config_id = $1)
       ORDER BY created_at DESC
       LIMIT 1`,
      [sourceConfigId, targetConfigId]
    );

    if (result.rows.length === 0) {
      // Generate diff on the fly
      return await generateConfigDiff(sourceConfigId, targetConfigId);
    }

    return result.rows[0];
  } catch (error) {
    console.error('Error getting config diff:', error);
    return null;
  }
}

/**
 * Log promotion history
 */
async function logPromotionHistory(params) {
  const {
    promotionId,
    eventType,
    eventDescription,
    performedBy,
    eventData = null,
  } = params;

  try {
    await pool.query(
      `INSERT INTO promotion_history (
        promotion_id, event_type, event_description,
        performed_by, event_data
      ) VALUES ($1, $2, $3, $4, $5)`,
      [
        promotionId,
        eventType,
        eventDescription,
        performedBy,
        eventData ? JSON.stringify(eventData) : null,
      ]
    );
  } catch (error) {
    console.error('Error logging promotion history:', error);
    // Don't throw - history logging shouldn't break the workflow
  }
}

export default {
  createPromotion,
  approvePromotion,
  rejectPromotion,
  completePromotion,
  getPromotions,
  getConfigDiff,
  generateConfigDiff,
  createApproval,
};


