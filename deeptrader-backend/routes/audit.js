/**
 * Audit Logging API Routes
 * 
 * Endpoints for:
 * - Getting audit logs
 * - Exporting audit logs
 * - Decision traces
 */

import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import auditService from '../services/auditService.js';
import { readFile } from 'fs/promises';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const router = express.Router();

/**
 * GET /api/audit
 * Get audit log with filters
 */
router.get('/', authenticateToken, async (req, res) => {
  try {
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
    } = req.query;

    const entries = await auditService.getAuditLog({
      userId,
      actionType,
      actionCategory,
      resourceType,
      resourceId,
      severity,
      startDate: startDate ? new Date(startDate) : null,
      endDate: endDate ? new Date(endDate) : null,
      limit: parseInt(limit),
      offset: parseInt(offset),
    });

    res.json({
      success: true,
      data: entries,
      count: entries.length,
      limit: parseInt(limit),
      offset: parseInt(offset),
    });
  } catch (error) {
    console.error('Error fetching audit log:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch audit log',
      error: error.message,
    });
  }
});

/**
 * GET /api/audit/export
 * Export audit log
 */
router.get('/export', authenticateToken, async (req, res) => {
  try {
    const {
      exportType = 'json',
      format = 'json',
      startDate,
      endDate,
      actionType,
      actionCategory,
      resourceType,
      severity,
    } = req.query;

    const exportResult = await auditService.exportAuditLog({
      userId: req.user.id,
      exportType,
      format,
      dateRangeStart: startDate ? new Date(startDate) : null,
      dateRangeEnd: endDate ? new Date(endDate) : null,
      filters: {
        actionType,
        actionCategory,
        resourceType,
        severity,
      },
    });

    res.json({
      success: true,
      message: 'Audit log exported',
      export: exportResult,
    });
  } catch (error) {
    console.error('Error exporting audit log:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to export audit log',
      error: error.message,
    });
  }
});

/**
 * GET /api/audit/export/:id/download
 * Download exported audit log file
 */
router.get('/export/:id/download', authenticateToken, async (req, res) => {
  try {
    const { id } = req.params;

    // Get export record
    const result = await pool.query(
      `SELECT * FROM audit_log_exports WHERE id = $1`,
      [id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({
        success: false,
        message: 'Export not found',
      });
    }

    const exportRecord = result.rows[0];

    if (exportRecord.export_status !== 'completed') {
      return res.status(400).json({
        success: false,
        message: `Export not ready: ${exportRecord.export_status}`,
      });
    }

    // Read and send file
    const fileContent = await readFile(exportRecord.file_path, 'utf8');
    const fileName = exportRecord.file_path.split('/').pop();

    res.setHeader('Content-Type', exportRecord.export_type === 'csv' ? 'text/csv' : 'application/json');
    res.setHeader('Content-Disposition', `attachment; filename="${fileName}"`);
    res.send(fileContent);
  } catch (error) {
    console.error('Error downloading export:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to download export',
      error: error.message,
    });
  }
});

/**
 * GET /api/traces/:tradeId
 * Get decision trace for a specific trade
 */
router.get('/traces/:tradeId', authenticateToken, async (req, res) => {
  try {
    const { tradeId } = req.params;

    const trace = await auditService.getDecisionTrace(tradeId);

    if (!trace) {
      return res.status(404).json({
        success: false,
        message: 'Decision trace not found',
      });
    }

    res.json({
      success: true,
      trace,
    });
  } catch (error) {
    console.error('Error fetching decision trace:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch decision trace',
      error: error.message,
    });
  }
});

/**
 * GET /api/traces
 * Get decision traces with filters
 */
router.get('/traces', authenticateToken, async (req, res) => {
  try {
    const {
      tradeId,
      symbol,
      decisionType,
      decisionOutcome,
      startDate,
      endDate,
      limit = 100,
      offset = 0,
    } = req.query;

    const traces = await auditService.getDecisionTraces({
      tradeId,
      symbol,
      decisionType,
      decisionOutcome,
      startDate: startDate ? new Date(startDate) : null,
      endDate: endDate ? new Date(endDate) : null,
      limit: parseInt(limit),
      offset: parseInt(offset),
    });

    res.json({
      success: true,
      data: traces,
      count: traces.length,
      limit: parseInt(limit),
      offset: parseInt(offset),
    });
  } catch (error) {
    console.error('Error fetching decision traces:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch decision traces',
      error: error.message,
    });
  }
});

export default router;





