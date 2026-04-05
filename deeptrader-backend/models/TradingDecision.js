/**
 * Trading Decision Model
 * PostgreSQL model for storing AI trading decisions
 */

import pool from '../config/database.js';
import { v4 as uuidv4 } from 'uuid';

class TradingDecision {
  /**
   * Create a new trading decision
   */
  static async create(decisionData) {
    const {
      userId,
      portfolioId,
      token,
      decision,
      marketData,
      multiTimeframe,
      confidence,
      action,
      executed = false,
      orderId = null,
      reasoning = null,
      factors = null
    } = decisionData;

    const id = uuidv4();
    const query = `
      INSERT INTO trading_decisions (
        id, user_id, portfolio_id, token, decision, market_data,
        multi_timeframe, confidence, action, executed, order_id, reasoning, factors
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
      RETURNING *
    `;

    const values = [
      id, userId, portfolioId, token,
      JSON.stringify(decision),
      JSON.stringify(marketData),
      multiTimeframe ? JSON.stringify(multiTimeframe) : null,
      confidence,
      action,
      executed,
      orderId,
      reasoning,
      factors ? JSON.stringify(factors) : null
    ];

    try {
      const { rows } = await pool.query(query, values);
      return rows[0];
    } catch (error) {
      console.error('Error creating trading decision:', error);
      throw error;
    }
  }

  /**
   * Mark a decision as executed and link to order
   */
  static async markExecuted(decisionId, orderId) {
    const query = `
      UPDATE trading_decisions
      SET executed = true, order_id = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
      RETURNING *
    `;
    const { rows } = await pool.query(query, [decisionId, orderId]);
    return rows[0];
  }

  /**
   * Find decisions by user ID with filtering
   */
  static async findByUserId(userId, filters = {}) {
    const { token, action, executed, limit = 50, offset = 0, startDate, endDate } = filters;

    let query = `
      SELECT * FROM trading_decisions
      WHERE user_id = $1
    `;
    const values = [userId];
    let paramIndex = 2;

    if (token) {
      query += ` AND token = $${paramIndex}`;
      values.push(token);
      paramIndex++;
    }

    if (action) {
      query += ` AND action = $${paramIndex}`;
      values.push(action);
      paramIndex++;
    }

    if (executed !== undefined) {
      query += ` AND executed = $${paramIndex}`;
      values.push(executed);
      paramIndex++;
    }

    if (startDate) {
      query += ` AND created_at >= $${paramIndex}`;
      values.push(startDate);
      paramIndex++;
    }

    if (endDate) {
      query += ` AND created_at <= $${paramIndex}`;
      values.push(endDate);
      paramIndex++;
    }

    query += ` ORDER BY created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
    values.push(limit, offset);

    const { rows } = await pool.query(query, values);
    return rows;
  }

  /**
   * Get recent decisions for dashboard
   */
  static async getRecentDecisions(userId, limit = 20) {
    const query = `
      SELECT
        id,
        token,
        action,
        confidence,
        executed,
        reasoning,
        created_at,
        decision,
        market_data
      FROM trading_decisions
      WHERE user_id = $1
      ORDER BY created_at DESC
      LIMIT $2
    `;
    const { rows } = await pool.query(query, [userId, limit]);
    return rows;
  }

  /**
   * Get decision statistics
   */
  static async getDecisionStats(userId, days = 30) {
    const query = `
      SELECT
        COUNT(*) as total_decisions,
        COUNT(CASE WHEN executed = true THEN 1 END) as executed_decisions,
        COUNT(CASE WHEN action = 'buy' THEN 1 END) as buy_signals,
        COUNT(CASE WHEN action = 'sell' THEN 1 END) as sell_signals,
        COUNT(CASE WHEN action = 'hold' THEN 1 END) as hold_signals,
        AVG(confidence) as avg_confidence,
        MAX(confidence) as max_confidence,
        MIN(confidence) as min_confidence,
        COUNT(CASE WHEN confidence >= 0.8 THEN 1 END) as high_confidence_decisions
      FROM trading_decisions
      WHERE user_id = $1 AND created_at >= CURRENT_TIMESTAMP - INTERVAL '${days} days'
    `;
    const { rows } = await pool.query(query, [userId]);
    return rows[0];
  }

  /**
   * Get decisions by token with performance metrics
   */
  static async getTokenPerformance(userId, token, days = 30) {
    const query = `
      SELECT
        token,
        COUNT(*) as total_decisions,
        COUNT(CASE WHEN executed = true THEN 1 END) as executed_decisions,
        COUNT(CASE WHEN action = 'buy' THEN 1 END) as buy_signals,
        COUNT(CASE WHEN action = 'sell' THEN 1 END) as sell_signals,
        AVG(confidence) as avg_confidence,
        MAX(created_at) as last_decision
      FROM trading_decisions
      WHERE user_id = $1 AND token = $2 AND created_at >= CURRENT_TIMESTAMP - INTERVAL '${days} days'
      GROUP BY token
    `;
    const { rows } = await pool.query(query, [userId, token]);
    return rows[0] || null;
  }

  /**
   * Clean up old decisions (keep last 1000 per user)
   */
  static async cleanupOldDecisions(userId, keepCount = 1000) {
    const query = `
      DELETE FROM trading_decisions
      WHERE user_id = $1
        AND id NOT IN (
          SELECT id FROM trading_decisions
          WHERE user_id = $1
          ORDER BY created_at DESC
          LIMIT $2
        )
    `;
    const { rowCount } = await pool.query(query, [userId, keepCount]);
    return rowCount;
  }

  /**
   * Get decision by ID
   */
  static async findById(decisionId) {
    const query = `SELECT * FROM trading_decisions WHERE id = $1`;
    const { rows } = await pool.query(query, [decisionId]);
    return rows[0];
  }

  /**
   * Update decision with additional factors/analysis
   */
  static async updateFactors(decisionId, factors, reasoning) {
    const query = `
      UPDATE trading_decisions
      SET factors = $2, reasoning = $3, updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
      RETURNING *
    `;
    const { rows } = await pool.query(query, [decisionId, JSON.stringify(factors), reasoning]);
    return rows[0];
  }
}

export default TradingDecision;




