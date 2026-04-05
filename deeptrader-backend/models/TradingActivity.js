/**
 * TradingActivity Model
 * Stores all trading decisions, orders, and activity for audit trail
 */

import pool from '../config/database.js';
import { v4 as uuidv4 } from 'uuid';

class TradingActivity {
  constructor(data) {
    this.id = data.id;
    this.userId = data.user_id;
    this.timestamp = data.timestamp;
    this.type = data.type;
    this.token = data.token;
    this.action = data.action;
    this.confidence = data.confidence;
    this.reasoning = data.reasoning;
    this.expectedOutcome = data.expected_outcome;
    this.orderId = data.order_id;
    this.positionId = data.position_id;
    this.quantity = data.quantity;
    this.price = data.price;
    this.marketData = data.market_data;
    this.metadata = data.metadata;
    this.status = data.status;
    this.resultMessage = data.result_message;
  }

  /**
   * Log a trading decision
   */
  static async logDecision(userId, decision, token, marketData, metadata = {}) {
    const query = `
      INSERT INTO trading_activity (
        user_id, type, token, action, confidence, reasoning, expected_outcome,
        market_data, metadata, status, timestamp
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
      RETURNING *
    `;

    // Include raw AI response and metadata in the metadata field
    const enrichedMetadata = {
      ...metadata,
      rawAIResponse: decision.rawAIResponse,
      aiMetadata: decision.aiMetadata,
      factorAnalysis: decision.factorAnalysis
    };

    const values = [
      userId,
      'decision',
      token,
      decision.action,
      decision.confidence,
      decision.reasoning,
      decision.expectedOutcome,
      JSON.stringify(marketData),
      JSON.stringify(enrichedMetadata),
      'pending',
      new Date()
    ];

    try {
      const { rows } = await pool.query(query, values);
      return new TradingActivity(rows[0]);
    } catch (error) {
      console.error('Error logging decision:', error);
      throw error;
    }
  }

  /**
   * Log an order creation
   */
  static async logOrderCreated(userId, order, decision = null) {
    const query = `
      INSERT INTO trading_activity (
        user_id, type, token, action, order_id, quantity, price,
        confidence, reasoning, metadata, status, timestamp
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
      RETURNING *
    `;

    const values = [
      userId,
      'order_created',
      order.symbol,
      order.side,
      order.id,
      order.quantity,
      order.price || null,
      decision?.confidence || null,
      decision?.reasoning || null,
      JSON.stringify({ orderType: order.orderType, ...order.metadata }),
      'executed',
      new Date()
    ];

    try {
      const { rows } = await pool.query(query, values);
      return new TradingActivity(rows[0]);
    } catch (error) {
      console.error('Error logging order creation:', error);
      throw error;
    }
  }

  /**
   * Log a position opening
   */
  static async logPositionOpened(userId, position, order = null) {
    const query = `
      INSERT INTO trading_activity (
        user_id, type, token, action, position_id, order_id, quantity, price,
        metadata, status, timestamp
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
      RETURNING *
    `;

    const values = [
      userId,
      'position_opened',
      position.symbol,
      position.side,
      position.id,
      order?.id || null,
      position.quantity,
      position.entry_price || position.entryPrice,
      JSON.stringify({
        stopLoss: position.stop_loss || position.stopLoss,
        takeProfit: position.take_profit || position.takeProfit,
        leverage: position.leverage
      }),
      'completed',
      new Date()
    ];

    try {
      const { rows } = await pool.query(query, values);
      return new TradingActivity(rows[0]);
    } catch (error) {
      console.error('Error logging position opened:', error);
      throw error;
    }
  }

  /**
   * Log a trade being blocked
   */
  static async logTradeBlocked(userId, token, decision, reason, metadata = {}) {
    const query = `
      INSERT INTO trading_activity (
        user_id, type, token, action, confidence, reasoning,
        metadata, status, result_message, timestamp
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
      RETURNING *
    `;

    const values = [
      userId,
      'trade_blocked',
      token,
      decision.action,
      decision.confidence,
      decision.reasoning,
      JSON.stringify(metadata),
      'blocked',
      reason,
      new Date()
    ];

    try {
      const { rows } = await pool.query(query, values);
      return new TradingActivity(rows[0]);
    } catch (error) {
      console.error('Error logging trade blocked:', error);
      throw error;
    }
  }

  /**
   * Log a position closing
   */
  static async logPositionClosed(data) {
    const {
      userId,
      positionId,
      token,
      side,
      quantity,
      entryPrice,
      exitPrice,
      realizedPnl,
      realizedPnlPercent,
      closeReason,
      metadata = {}
    } = data;

    const query = `
      INSERT INTO trading_activity (
        user_id, type, token, action, position_id, quantity, price,
        metadata, status, result_message, timestamp
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
      RETURNING *
    `;

    const values = [
      userId,
      'position_closed',
      token,
      side,
      positionId,
      quantity,
      exitPrice,
      JSON.stringify({
        entryPrice,
        exitPrice,
        realizedPnl,
        realizedPnlPercent,
        closeReason,
        ...metadata
      }),
      'completed',
      `Position closed: ${realizedPnl >= 0 ? 'Profit' : 'Loss'} ${realizedPnlPercent.toFixed(2)}%`,
      new Date()
    ];

    try {
      const { rows } = await pool.query(query, values);
      return new TradingActivity(rows[0]);
    } catch (error) {
      console.error('Error logging position closed:', error);
      throw error;
    }
  }

  /**
   * Get recent activity for a user with optional filters
   */
  static async getRecentActivity(userId, limit = 50, filters = {}) {
    let query = `
      SELECT * FROM trading_activity
      WHERE user_id = $1
    `;
    
    const params = [userId];
    let paramIndex = 2;

    // Apply filters
    if (filters.type) {
      query += ` AND type = $${paramIndex}`;
      params.push(filters.type);
      paramIndex++;
    }

    if (filters.token) {
      query += ` AND token = $${paramIndex}`;
      params.push(filters.token);
      paramIndex++;
    }

    if (filters.action) {
      query += ` AND action = $${paramIndex}`;
      params.push(filters.action);
      paramIndex++;
    }

    if (filters.status) {
      query += ` AND status = $${paramIndex}`;
      params.push(filters.status);
      paramIndex++;
    }

    if (filters.minConfidence !== undefined) {
      query += ` AND confidence >= $${paramIndex}`;
      params.push(filters.minConfidence);
      paramIndex++;
    }

    if (filters.startDate) {
      query += ` AND timestamp >= $${paramIndex}`;
      params.push(filters.startDate);
      paramIndex++;
    }

    if (filters.endDate) {
      query += ` AND timestamp <= $${paramIndex}`;
      params.push(filters.endDate);
      paramIndex++;
    }

    query += ` ORDER BY timestamp DESC LIMIT $${paramIndex}`;
    params.push(limit);

    console.log('🔍 TradingActivity.getRecentActivity - SQL Query:', query);
    console.log('🔍 TradingActivity.getRecentActivity - Params:', params);

    try {
      const { rows } = await pool.query(query, params);
      console.log('📊 TradingActivity.getRecentActivity - Found', rows.length, 'rows');
      return rows.map(row => new TradingActivity(row));
    } catch (error) {
      console.error('Error getting recent activity:', error);
      throw error;
    }
  }

  /**
   * Get activity by type
   */
  static async getActivityByType(userId, type, limit = 50) {
    const query = `
      SELECT * FROM trading_activity
      WHERE user_id = $1 AND type = $2
      ORDER BY timestamp DESC
      LIMIT $3
    `;

    try {
      const { rows } = await pool.query(query, [userId, type, limit]);
      return rows.map(row => new TradingActivity(row));
    } catch (error) {
      console.error('Error getting activity by type:', error);
      throw error;
    }
  }

  /**
   * Get activity for a specific token
   */
  static async getActivityForToken(userId, token, limit = 50) {
    const query = `
      SELECT * FROM trading_activity
      WHERE user_id = $1 AND token = $2
      ORDER BY timestamp DESC
      LIMIT $3
    `;

    try {
      const { rows } = await pool.query(query, [userId, token, limit]);
      return rows.map(row => new TradingActivity(row));
    } catch (error) {
      console.error('Error getting activity for token:', error);
      throw error;
    }
  }

  /**
   * Convert to JSON (format for frontend compatibility)
   */
  toJSON() {
    const base = {
      id: this.id,
      userId: this.userId,
      timestamp: this.timestamp,
      type: this.type,
      token: this.token,
      orderId: this.orderId,
      positionId: this.positionId,
      quantity: this.quantity ? parseFloat(this.quantity) : null,
      price: this.price ? parseFloat(this.price) : null,
      marketData: this.marketData,
      metadata: this.metadata,
      status: this.status,
      resultMessage: this.resultMessage
    };

    // For decision and trade_blocked types, nest action/confidence/reasoning in a 'decision' object
    // to match frontend expectations
    if (this.type === 'decision' || this.type === 'trade_blocked') {
      base.decision = {
        action: this.action,
        confidence: this.confidence ? parseFloat(this.confidence) : null,
        reasoning: this.reasoning,
        expectedOutcome: this.expectedOutcome
      };
    } else {
      // For other types, keep them at top level
      base.action = this.action;
      base.confidence = this.confidence ? parseFloat(this.confidence) : null;
      base.reasoning = this.reasoning;
      base.expectedOutcome = this.expectedOutcome;
    }

    return base;
  }
}

export default TradingActivity;

