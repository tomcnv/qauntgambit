/**
 * Audit Logging Service
 * 
 * Handles:
 * - Comprehensive audit logging
 * - Decision trace storage
 * - Audit log export
 * - Retention policy management
 */

import pool from '../config/database.js';
import { writeFile, mkdir } from 'fs/promises';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Log an audit event
 */
async function logAuditEvent(params) {
  const {
    userId,
    actionType,
    actionCategory,
    resourceType,
    resourceId,
    actionDescription,
    actionDetails = null,
    beforeState = null,
    afterState = null,
    ipAddress = null,
    userAgent = null,
    severity = 'info',
    requiresRetention = true,
    retentionDays = null,
  } = params;

  try {
    // Get retention policy if not specified
    let finalRetentionDays = retentionDays;
    if (!finalRetentionDays && requiresRetention) {
      const policy = await getRetentionPolicy('audit_log', actionCategory);
      finalRetentionDays = policy?.retention_days || null;
    }

    const result = await pool.query(
      `INSERT INTO audit_log (
        user_id, action_type, action_category,
        resource_type, resource_id, action_description,
        action_details, before_state, after_state,
        ip_address, user_agent, severity,
        requires_retention, retention_days
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
      RETURNING *`,
      [
        userId,
        actionType,
        actionCategory,
        resourceType,
        resourceId,
        actionDescription,
        actionDetails ? JSON.stringify(actionDetails) : null,
        beforeState ? JSON.stringify(beforeState) : null,
        afterState ? JSON.stringify(afterState) : null,
        ipAddress,
        userAgent,
        severity,
        requiresRetention,
        finalRetentionDays,
      ]
    );

    return result.rows[0];
  } catch (error) {
    console.error('Error logging audit event:', error);
    // Don't throw - audit logging shouldn't break the main flow
    return null;
  }
}

/**
 * Store decision trace
 */
async function storeDecisionTrace(params) {
  const {
    tradeId,
    symbol,
    timestamp,
    decisionType,
    decisionOutcome,
    signalData = null,
    marketContext = null,
    stageResults,
    rejectionReasons = null,
    finalDecision = null,
    executionResult = null,
    traceMetadata = null,
  } = params;

  try {
    const result = await pool.query(
      `INSERT INTO decision_traces (
        trade_id, symbol, timestamp,
        decision_type, decision_outcome,
        signal_data, market_context, stage_results,
        rejection_reasons, final_decision, execution_result, trace_metadata
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
      RETURNING *`,
      [
        tradeId,
        symbol,
        timestamp,
        decisionType,
        decisionOutcome,
        signalData ? JSON.stringify(signalData) : null,
        marketContext ? JSON.stringify(marketContext) : null,
        JSON.stringify(stageResults),
        rejectionReasons ? JSON.stringify(rejectionReasons) : null,
        finalDecision ? JSON.stringify(finalDecision) : null,
        executionResult ? JSON.stringify(executionResult) : null,
        traceMetadata ? JSON.stringify(traceMetadata) : null,
      ]
    );

    return result.rows[0];
  } catch (error) {
    console.error('Error storing decision trace:', error);
    throw error;
  }
}

/**
 * Get audit log with filters
 */
async function getAuditLog(filters = {}) {
  const {
    userId,
    actionType,
    actionCategory,
    resourceType,
    resourceId,
    severity,
    startDate,
    endDate,
    limit = 100,
    offset = 0,
  } = filters;

  let query = `SELECT * FROM audit_log WHERE 1=1`;
  const queryParams = [];
  let paramIndex = 1;

  if (userId) {
    query += ` AND user_id = $${paramIndex}`;
    queryParams.push(userId);
    paramIndex++;
  }

  if (actionType) {
    query += ` AND action_type = $${paramIndex}`;
    queryParams.push(actionType);
    paramIndex++;
  }

  if (actionCategory) {
    query += ` AND action_category = $${paramIndex}`;
    queryParams.push(actionCategory);
    paramIndex++;
  }

  if (resourceType) {
    query += ` AND resource_type = $${paramIndex}`;
    queryParams.push(resourceType);
    paramIndex++;
  }

  if (resourceId) {
    query += ` AND resource_id = $${paramIndex}`;
    queryParams.push(resourceId);
    paramIndex++;
  }

  if (severity) {
    query += ` AND severity = $${paramIndex}`;
    queryParams.push(severity);
    paramIndex++;
  }

  if (startDate) {
    query += ` AND created_at >= $${paramIndex}`;
    queryParams.push(startDate);
    paramIndex++;
  }

  if (endDate) {
    query += ` AND created_at <= $${paramIndex}`;
    queryParams.push(endDate);
    paramIndex++;
  }

  query += ` ORDER BY created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
  queryParams.push(limit, offset);

  const result = await pool.query(query, queryParams);
  
  // Parse JSONB fields from database
  return result.rows.map(row => {
    const parsed = { ...row };
    // Parse JSONB fields if they're strings
    if (parsed.action_details && typeof parsed.action_details === 'string') {
      try {
        parsed.action_details = JSON.parse(parsed.action_details);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.before_state && typeof parsed.before_state === 'string') {
      try {
        parsed.before_state = JSON.parse(parsed.before_state);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.after_state && typeof parsed.after_state === 'string') {
      try {
        parsed.after_state = JSON.parse(parsed.after_state);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    return parsed;
  });
}

/**
 * Get decision trace by trade ID
 */
async function getDecisionTrace(tradeId) {
  try {
    const result = await pool.query(
      `SELECT * FROM decision_traces WHERE trade_id = $1 ORDER BY timestamp DESC LIMIT 1`,
      [tradeId]
    );

    if (result.rows.length === 0) {
      return null;
    }

    const row = result.rows[0];
    
    // Parse JSONB fields from database
    const parsed = { ...row };
    if (parsed.signal_data && typeof parsed.signal_data === 'string') {
      try {
        parsed.signal_data = JSON.parse(parsed.signal_data);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.market_context && typeof parsed.market_context === 'string') {
      try {
        parsed.market_context = JSON.parse(parsed.market_context);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.stage_results && typeof parsed.stage_results === 'string') {
      try {
        parsed.stage_results = JSON.parse(parsed.stage_results);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.rejection_reasons && typeof parsed.rejection_reasons === 'string') {
      try {
        parsed.rejection_reasons = JSON.parse(parsed.rejection_reasons);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.final_decision && typeof parsed.final_decision === 'string') {
      try {
        parsed.final_decision = JSON.parse(parsed.final_decision);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.execution_result && typeof parsed.execution_result === 'string') {
      try {
        parsed.execution_result = JSON.parse(parsed.execution_result);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    
    return parsed;
  } catch (error) {
    console.error('Error getting decision trace:', error);
    throw error;
  }
}

/**
 * Get decision traces with filters
 */
async function getDecisionTraces(filters = {}) {
  const {
    tradeId,
    symbol,
    decisionType,
    decisionOutcome,
    startDate,
    endDate,
    limit = 100,
    offset = 0,
  } = filters;

  let query = `SELECT * FROM decision_traces WHERE 1=1`;
  const queryParams = [];
  let paramIndex = 1;

  if (tradeId) {
    query += ` AND trade_id = $${paramIndex}`;
    queryParams.push(tradeId);
    paramIndex++;
  }

  if (symbol) {
    query += ` AND symbol = $${paramIndex}`;
    queryParams.push(symbol);
    paramIndex++;
  }

  if (decisionType) {
    query += ` AND decision_type = $${paramIndex}`;
    queryParams.push(decisionType);
    paramIndex++;
  }

  if (decisionOutcome) {
    query += ` AND decision_outcome = $${paramIndex}`;
    queryParams.push(decisionOutcome);
    paramIndex++;
  }

  if (startDate) {
    query += ` AND timestamp >= $${paramIndex}`;
    queryParams.push(startDate);
    paramIndex++;
  }

  if (endDate) {
    query += ` AND timestamp <= $${paramIndex}`;
    queryParams.push(endDate);
    paramIndex++;
  }

  query += ` ORDER BY timestamp DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
  queryParams.push(limit, offset);

  const result = await pool.query(query, queryParams);
  
  // Parse JSONB fields from database
  return result.rows.map(row => {
    const parsed = { ...row };
    // Parse JSONB fields if they're strings
    if (parsed.signal_data && typeof parsed.signal_data === 'string') {
      try {
        parsed.signal_data = JSON.parse(parsed.signal_data);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.market_context && typeof parsed.market_context === 'string') {
      try {
        parsed.market_context = JSON.parse(parsed.market_context);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.stage_results && typeof parsed.stage_results === 'string') {
      try {
        parsed.stage_results = JSON.parse(parsed.stage_results);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.rejection_reasons && typeof parsed.rejection_reasons === 'string') {
      try {
        parsed.rejection_reasons = JSON.parse(parsed.rejection_reasons);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.final_decision && typeof parsed.final_decision === 'string') {
      try {
        parsed.final_decision = JSON.parse(parsed.final_decision);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    if (parsed.execution_result && typeof parsed.execution_result === 'string') {
      try {
        parsed.execution_result = JSON.parse(parsed.execution_result);
      } catch (e) {
        // Keep as string if parse fails
      }
    }
    return parsed;
  });
}

/**
 * Export audit log
 */
async function exportAuditLog(params) {
  const {
    userId,
    exportType = 'json',
    dateRangeStart,
    dateRangeEnd,
    filters = {},
    format = 'json', // 'json', 'csv'
  } = params;

  try {
    // Get audit log entries
    const entries = await getAuditLog({
      ...filters,
      startDate: dateRangeStart,
      endDate: dateRangeEnd,
      limit: 10000, // Large limit for export
    });

    // Create export record
    const exportRecord = await pool.query(
      `INSERT INTO audit_log_exports (
        user_id, export_type, date_range_start, date_range_end,
        filters, export_status
      ) VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING *`,
      [
        userId,
        exportType,
        dateRangeStart,
        dateRangeEnd,
        JSON.stringify(filters),
        'pending',
      ]
    );

    const exportId = exportRecord.rows[0].id;

    // Generate export file
    let fileContent;
    let fileExtension;

    if (format === 'csv') {
      fileContent = generateCSVExport(entries);
      fileExtension = 'csv';
    } else {
      fileContent = JSON.stringify(entries, null, 2);
      fileExtension = 'json';
    }

    // Save file
    const exportsDir = join(__dirname, '../../exports');
    await mkdir(exportsDir, { recursive: true });
    const fileName = `audit_export_${exportId}_${Date.now()}.${fileExtension}`;
    const filePath = join(exportsDir, fileName);

    await writeFile(filePath, fileContent, 'utf8');

    // Update export record
    const stats = await import('fs').then(fs => fs.promises.stat(filePath));

    await pool.query(
      `UPDATE audit_log_exports
       SET export_status = 'completed',
           file_path = $1,
           file_size_bytes = $2,
           record_count = $3,
           completed_at = CURRENT_TIMESTAMP
       WHERE id = $4`,
      [filePath, stats.size, entries.length, exportId]
    );

    return {
      exportId,
      filePath,
      fileName,
      recordCount: entries.length,
      fileSize: stats.size,
    };
  } catch (error) {
    console.error('Error exporting audit log:', error);
    
    // Update export record with error
    if (exportId) {
      await pool.query(
        `UPDATE audit_log_exports
         SET export_status = 'failed',
             error_message = $1
         WHERE id = $2`,
        [error.message, exportId]
      );
    }

    throw error;
  }
}

/**
 * Generate CSV export
 */
function generateCSVExport(entries) {
  if (entries.length === 0) {
    return 'No entries found';
  }

  const headers = [
    'id',
    'timestamp',
    'user_id',
    'action_type',
    'action_category',
    'resource_type',
    'resource_id',
    'action_description',
    'severity',
  ];

  const rows = entries.map(entry => [
    entry.id,
    entry.created_at,
    entry.user_id || '',
    entry.action_type,
    entry.action_category,
    entry.resource_type || '',
    entry.resource_id || '',
    entry.action_description,
    entry.severity,
  ]);

  const csvRows = [
    headers.join(','),
    ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')),
  ];

  return csvRows.join('\n');
}

/**
 * Get retention policy
 */
async function getRetentionPolicy(logType, actionCategory = null) {
  try {
    let query = `SELECT * FROM retention_policies WHERE log_type = $1 AND is_active = true`;
    const queryParams = [logType];

    if (actionCategory) {
      query += ` AND (action_category = $2 OR action_category IS NULL)`;
      queryParams.push(actionCategory);
    }

    query += ` ORDER BY action_category NULLS LAST LIMIT 1`;

    const result = await pool.query(query, queryParams);
    return result.rows[0] || null;
  } catch (error) {
    console.error('Error getting retention policy:', error);
    return null;
  }
}

/**
 * Apply retention policies (cleanup old logs)
 */
async function applyRetentionPolicies() {
  try {
    const policies = await pool.query(
      `SELECT * FROM retention_policies WHERE is_active = true`
    );

    let totalDeleted = 0;

    for (const policy of policies.rows) {
      const cutoffDate = new Date();
      cutoffDate.setDate(cutoffDate.getDate() - policy.retention_days);

      let query;
      const queryParams = [cutoffDate];

      if (policy.log_type === 'audit_log') {
        if (policy.action_category) {
          query = `DELETE FROM audit_log 
                   WHERE created_at < $1 
                   AND action_category = $2 
                   AND requires_retention = false`;
          queryParams.push(policy.action_category);
        } else {
          query = `DELETE FROM audit_log 
                   WHERE created_at < $1 
                   AND requires_retention = false`;
        }
      } else if (policy.log_type === 'decision_traces') {
        query = `DELETE FROM decision_traces WHERE timestamp < $1`;
      }

      if (query) {
        const result = await pool.query(query, queryParams);
        totalDeleted += result.rowCount || 0;
      }
    }

    return {
      policiesApplied: policies.rows.length,
      recordsDeleted: totalDeleted,
    };
  } catch (error) {
    console.error('Error applying retention policies:', error);
    throw error;
  }
}

export default {
  logAuditEvent,
  storeDecisionTrace,
  getAuditLog,
  getDecisionTrace,
  getDecisionTraces,
  exportAuditLog,
  getRetentionPolicy,
  applyRetentionPolicies,
};

