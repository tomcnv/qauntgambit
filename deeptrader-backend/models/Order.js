/**
 * Order Model
 * PostgreSQL model for order management
 */

import pool from '../config/database.js';
import { v4 as uuidv4 } from 'uuid';

class Order {
  /**
   * Create a new order
   */
  static async create(orderData) {
    const {
      userId,
      portfolioId,
      symbol,
      orderType,
      side,
      quantity,
      price = null,
      stopPrice = null,
      trailingPercent = null,
      timeInForce = 'GTC',
      postOnly = false,
      reduceOnly = false,
      linkedOrders = null,
      expiresAt = null,
      exchange = 'binance',
      metadata = null,
      // Versioning & Attribution fields
      profileId = null,
      profileVersion = null,
      botInstanceId = null,
      exchangeAccountId = null,
    } = orderData;

    const id = uuidv4();
    const query = `
      INSERT INTO orders (
        id, user_id, portfolio_id, symbol, order_type, side, quantity, price,
        stop_price, trailing_percent, time_in_force, post_only, reduce_only,
        linked_orders, expires_at, exchange, metadata,
        profile_id, profile_version, bot_instance_id, exchange_account_id
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
      RETURNING *
    `;

    const values = [
      id, userId, portfolioId, symbol, orderType, side, quantity, price,
      stopPrice, trailingPercent, timeInForce, postOnly, reduceOnly,
      linkedOrders ? JSON.stringify(linkedOrders) : null,
      expiresAt, exchange, metadata ? JSON.stringify(metadata) : null,
      profileId, profileVersion, botInstanceId, exchangeAccountId
    ];

    try {
      const { rows } = await pool.query(query, values);
      return rows[0];
    } catch (error) {
      console.error('Error creating order:', error);
      throw error;
    }
  }

  /**
   * Find order by ID
   */
  static async findById(orderId) {
    const query = `
      SELECT * FROM orders WHERE id = $1
    `;
    const { rows } = await pool.query(query, [orderId]);
    return rows[0];
  }

  /**
   * Find orders by user ID with optional filters
   */
  static async findByUserId(userId, filters = {}) {
    const { status, symbol, orderType, limit = 50, offset = 0 } = filters;

    let query = `
      SELECT * FROM orders
      WHERE user_id = $1
    `;
    const values = [userId];
    let paramIndex = 2;

    if (status) {
      query += ` AND status = $${paramIndex}`;
      values.push(status);
      paramIndex++;
    }

    if (symbol) {
      query += ` AND symbol = $${paramIndex}`;
      values.push(symbol);
      paramIndex++;
    }

    if (orderType) {
      query += ` AND order_type = $${paramIndex}`;
      values.push(orderType);
      paramIndex++;
    }

    query += ` ORDER BY created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
    values.push(limit, offset);

    const { rows } = await pool.query(query, values);
    return rows;
  }

  /**
   * Find active orders for a user
   */
  static async findActiveByUserId(userId) {
    const query = `
      SELECT * FROM orders
      WHERE user_id = $1 AND status IN ('pending', 'active')
      ORDER BY created_at ASC
    `;
    const { rows } = await pool.query(query, [userId]);
    return rows;
  }

  /**
   * Update order status
   */
  static async updateStatus(orderId, status, additionalData = {}) {
    const { filledQuantity, avgFillPrice, filledAt, errorMessage, exchangeOrderId } = additionalData;

    const query = `
      UPDATE orders
      SET
        status = $1,
        filled_quantity = COALESCE($2, filled_quantity),
        avg_fill_price = COALESCE($3, avg_fill_price),
        filled_at = COALESCE($4, filled_at),
        exchange_order_id = COALESCE($5, exchange_order_id),
        error_message = COALESCE($6, error_message),
        updated_at = CURRENT_TIMESTAMP
      WHERE id = $7
      RETURNING *
    `;

    const values = [status, filledQuantity, avgFillPrice, filledAt, exchangeOrderId, errorMessage, orderId];

    try {
      const { rows } = await pool.query(query, values);
      return rows[0];
    } catch (error) {
      console.error('Error updating order status:', error);
      throw error;
    }
  }

  /**
   * Cancel order
   */
  static async cancel(orderId) {
    const query = `
      UPDATE orders
      SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
      WHERE id = $1 AND status IN ('pending', 'active')
      RETURNING *
    `;
    const { rows } = await pool.query(query, [orderId]);
    return rows[0];
  }

  /**
   * Cancel all active orders for a user
   */
  static async cancelAllActive(userId) {
    const query = `
      UPDATE orders
      SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
      WHERE user_id = $1 AND status IN ('pending', 'active')
      RETURNING *
    `;
    const { rows } = await pool.query(query, [userId]);
    return rows;
  }

  /**
   * Get order statistics for a user
   */
  static async getStats(userId) {
    const query = `
      SELECT
        COUNT(*) as total_orders,
        COUNT(CASE WHEN status = 'filled' THEN 1 END) as filled_orders,
        COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled_orders,
        COUNT(CASE WHEN status = 'active' THEN 1 END) as active_orders,
        SUM(CASE WHEN status = 'filled' THEN filled_quantity ELSE 0 END) as total_filled_quantity,
        AVG(CASE WHEN status = 'filled' THEN avg_fill_price END) as avg_fill_price
      FROM orders
      WHERE user_id = $1 AND created_at >= CURRENT_DATE - INTERVAL '30 days'
    `;
    const { rows } = await pool.query(query, [userId]);
    return rows[0];
  }

  /**
   * Clean up expired orders
   */
  static async cleanupExpired() {
    const query = `
      UPDATE orders
      SET status = 'expired', updated_at = CURRENT_TIMESTAMP
      WHERE status IN ('pending', 'active')
        AND expires_at IS NOT NULL
        AND expires_at < CURRENT_TIMESTAMP
      RETURNING *
    `;
    const { rows } = await pool.query(query);
    return rows;
  }
}

export default Order;




