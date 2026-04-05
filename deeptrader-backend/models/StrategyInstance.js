/**
 * Strategy Instance Model
 * 
 * User-parameterized versions of strategy templates.
 * Users can customize parameters from the base strategy templates.
 */

import { randomUUID } from 'crypto';
import pool from '../config/database.js';

/**
 * Valid statuses
 */
export const STATUSES = ['active', 'deprecated', 'archived'];

/**
 * Get all strategy instances for a user, including system templates
 */
export async function getInstancesByUser(userId, { status = null, templateId = null, includeSystemTemplates = true } = {}) {
  let query = `
    SELECT * FROM strategy_instances
    WHERE (user_id = $1 ${includeSystemTemplates ? 'OR is_system_template = true' : ''})
  `;
  const params = [userId];
  let paramIndex = 2;
  
  if (status) {
    query += ` AND status = $${paramIndex}`;
    params.push(status);
    paramIndex++;
  }
  
  if (templateId) {
    query += ` AND template_id = $${paramIndex}`;
    params.push(templateId);
    paramIndex++;
  }
  
  query += ` ORDER BY is_system_template DESC, updated_at DESC`;
  
  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * Get all system template strategies
 */
export async function getSystemTemplates({ status = 'active' } = {}) {
  const result = await pool.query(
    `SELECT * FROM strategy_instances 
     WHERE is_system_template = true ${status ? 'AND status = $1' : ''}
     ORDER BY name ASC`,
    status ? [status] : []
  );
  return result.rows;
}

/**
 * Get a strategy instance by ID
 */
export async function getInstanceById(instanceId) {
  const result = await pool.query(
    `SELECT * FROM strategy_instances WHERE id = $1`,
    [instanceId]
  );
  return result.rows[0] || null;
}

/**
 * Get a strategy instance by ID, verifying user ownership
 */
export async function getInstanceByIdAndUser(instanceId, userId) {
  const result = await pool.query(
    `SELECT * FROM strategy_instances WHERE id = $1 AND user_id = $2`,
    [instanceId, userId]
  );
  return result.rows[0] || null;
}

/**
 * Create a new strategy instance from a template
 */
export async function createInstance({
  userId,
  templateId,
  name,
  description = null,
  params = {},
}) {
  const instanceId = randomUUID();
  
  const result = await pool.query(
    `INSERT INTO strategy_instances (
      id, user_id, template_id, name, description, params
    ) VALUES ($1, $2, $3, $4, $5, $6)
    RETURNING *`,
    [instanceId, userId, templateId, name, description, JSON.stringify(params)]
  );
  
  return result.rows[0];
}

/**
 * Update a strategy instance
 */
export async function updateInstance(instanceId, userId, updates) {
  const allowedFields = ['name', 'description', 'params', 'status'];
  
  const setClause = [];
  const values = [];
  let paramIndex = 1;
  
  for (const [key, value] of Object.entries(updates)) {
    if (allowedFields.includes(key)) {
      setClause.push(`${key} = $${paramIndex}`);
      values.push(key === 'params' ? JSON.stringify(value) : value);
      paramIndex++;
    }
  }
  
  if (setClause.length === 0) {
    throw new Error('No valid fields to update');
  }
  
  values.push(instanceId);
  values.push(userId);
  
  const result = await pool.query(
    `UPDATE strategy_instances
     SET ${setClause.join(', ')}
     WHERE id = $${paramIndex} AND user_id = $${paramIndex + 1}
     RETURNING *`,
    values
  );
  
  if (result.rows.length === 0) {
    throw new Error('Strategy instance not found or access denied');
  }
  
  return result.rows[0];
}

/**
 * Clone a strategy instance (works with user-owned and system templates)
 */
export async function cloneInstance(instanceId, userId, newName = null) {
  // Get the source instance - check both user-owned and system templates
  let source = await getInstanceByIdAndUser(instanceId, userId);
  
  // If not found, check if it's a system template
  if (!source) {
    const systemTemplate = await pool.query(
      `SELECT * FROM strategy_instances WHERE id = $1 AND is_system_template = true`,
      [instanceId]
    );
    source = systemTemplate.rows[0];
  }
  
  if (!source) {
    throw new Error('Strategy instance not found or access denied');
  }
  
  // Generate new name if not provided
  const cloneName = newName || `${source.name} (Copy)`;
  
  // Check for name collision
  const existing = await pool.query(
    `SELECT id FROM strategy_instances WHERE user_id = $1 AND name = $2`,
    [userId, cloneName]
  );
  
  if (existing.rows.length > 0) {
    throw new Error(`A strategy instance named "${cloneName}" already exists`);
  }
  
  // Create the clone
  return createInstance({
    userId,
    templateId: source.template_id,
    name: cloneName,
    description: source.description ? `Cloned from ${source.name}. ${source.description}` : `Cloned from ${source.name}`,
    params: source.params,
  });
}

/**
 * Archive a strategy instance (soft delete)
 */
export async function archiveInstance(instanceId, userId) {
  // Check if instance is used by any profiles
  const usageCheck = await pool.query(
    `SELECT id, name FROM user_chessboard_profiles 
     WHERE user_id = $1 
     AND strategy_composition @> $2::jsonb`,
    [userId, JSON.stringify([{ instance_id: instanceId }])]
  );
  
  if (usageCheck.rows.length > 0) {
    const profileNames = usageCheck.rows.map(p => p.name).join(', ');
    throw new Error(`Cannot archive: strategy instance is used by profiles: ${profileNames}`);
  }
  
  return updateInstance(instanceId, userId, { status: 'archived' });
}

/**
 * Deprecate a strategy instance (mark for replacement)
 */
export async function deprecateInstance(instanceId, userId) {
  return updateInstance(instanceId, userId, { status: 'deprecated' });
}

/**
 * Restore an archived/deprecated instance
 */
export async function restoreInstance(instanceId, userId) {
  return updateInstance(instanceId, userId, { status: 'active' });
}

/**
 * Delete a strategy instance permanently (only if archived)
 */
export async function deleteInstance(instanceId, userId) {
  const instance = await getInstanceByIdAndUser(instanceId, userId);
  if (!instance) {
    throw new Error('Strategy instance not found or access denied');
  }
  
  if (instance.status !== 'archived') {
    throw new Error('Only archived strategy instances can be permanently deleted');
  }
  
  await pool.query(
    `DELETE FROM strategy_instances WHERE id = $1 AND user_id = $2`,
    [instanceId, userId]
  );
  
  return { deleted: true, id: instanceId };
}

/**
 * Get usage statistics for a strategy instance
 */
export async function getInstanceUsage(instanceId, userId) {
  const instance = await getInstanceByIdAndUser(instanceId, userId);
  if (!instance) {
    throw new Error('Strategy instance not found or access denied');
  }
  
  // Get profiles using this instance
  const profiles = await pool.query(
    `SELECT id, name, environment, status, is_active
     FROM user_chessboard_profiles
     WHERE user_id = $1
     AND strategy_composition @> $2::jsonb`,
    [userId, JSON.stringify([{ instance_id: instanceId }])]
  );
  
  return {
    instance_id: instanceId,
    usage_count: instance.usage_count,
    profiles: profiles.rows,
    last_backtest: instance.last_backtest_at,
    backtest_summary: instance.last_backtest_summary,
  };
}

/**
 * Update backtest results for a strategy instance
 */
export async function updateBacktestResults(instanceId, userId, summary) {
  const result = await pool.query(
    `UPDATE strategy_instances
     SET last_backtest_at = NOW(), last_backtest_summary = $1
     WHERE id = $2 AND user_id = $3
     RETURNING *`,
    [JSON.stringify(summary), instanceId, userId]
  );
  
  if (result.rows.length === 0) {
    throw new Error('Strategy instance not found or access denied');
  }
  
  return result.rows[0];
}

export default {
  getInstancesByUser,
  getSystemTemplates,
  getInstanceById,
  getInstanceByIdAndUser,
  createInstance,
  updateInstance,
  cloneInstance,
  archiveInstance,
  deprecateInstance,
  restoreInstance,
  deleteInstance,
  getInstanceUsage,
  updateBacktestResults,
  STATUSES,
};


