/**
 * Position Model
 * PostgreSQL model for tracking open and closed positions
 */

import pool from '../config/database.js';
import { v4 as uuidv4 } from 'uuid';

export class Position {
  /**
   * Create a new position
   */
  static async create(positionData) {
    const {
      userId,
      portfolioId,
      entryOrderId = null,
      symbol,
      side,
      quantity,
      entryPrice,
      currentPrice = null,
      stopLoss = null,
      takeProfit = null,
      feesPaid = 0,
      metadata = null,
      leverage = 1.0,
      initialMargin = null,
      maintenanceMargin = null,
      liquidationPrice = null,
      marginMode = 'isolated'
    } = positionData;

    const id = uuidv4();
    // Calculate margin values if leverage > 1
    const positionValue = quantity * entryPrice;
    const calculatedInitialMargin = initialMargin || (leverage > 1 ? positionValue / leverage : positionValue);
    const calculatedMaintenanceMargin = maintenanceMargin || (leverage > 1 ? calculatedInitialMargin * 0.5 : calculatedInitialMargin);

    const query = `
      INSERT INTO positions (
        id, user_id, portfolio_id, entry_order_id, symbol, side, quantity,
        entry_price, current_price, stop_loss, take_profit, fees_paid,
        unrealized_pnl, unrealized_pnl_percent, metadata,
        leverage, initial_margin, maintenance_margin, liquidation_price,
        margin_ratio, margin_mode
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 0, 0, $13,
              $14, $15, $16, $17, 100.0, $18)
      RETURNING *
    `;

    const values = [
      id, userId, portfolioId, entryOrderId, symbol, side, quantity,
      entryPrice, currentPrice || entryPrice, stopLoss, takeProfit, feesPaid,
      metadata ? JSON.stringify(metadata) : null,
      leverage, calculatedInitialMargin, calculatedMaintenanceMargin,
      liquidationPrice, marginMode
    ];

    try {
      const { rows } = await pool.query(query, values);
      console.log(`📊 Position created: ${side.toUpperCase()} ${quantity} ${symbol} @ ${entryPrice}`);
      return rows[0];
    } catch (error) {
      console.error('Error creating position:', error);
      throw error;
    }
  }

  /**
   * Find position by ID
   */
  static async findById(positionId) {
    const query = 'SELECT * FROM positions WHERE id = $1';
    try {
      const { rows } = await pool.query(query, [positionId]);
      return rows[0] || null;
    } catch (error) {
      console.error('Error finding position:', error);
      throw error;
    }
  }

  /**
   * Find all open positions for a user
   */
  static async findOpenByUserId(userId) {
    const query = `
      SELECT * FROM positions
      WHERE user_id = $1 AND status = 'open'
      ORDER BY opened_at DESC
    `;
    try {
      const { rows } = await pool.query(query, [userId]);
      return rows;
    } catch (error) {
      console.error('Error finding open positions:', error);
      throw error;
    }
  }

  /**
   * Find all open positions for a portfolio
   */
  static async findOpenByPortfolioId(portfolioId) {
    const query = `
      SELECT * FROM positions
      WHERE portfolio_id = $1 AND status = 'open'
      ORDER BY opened_at DESC
    `;
    try {
      const { rows } = await pool.query(query, [portfolioId]);
      return rows;
    } catch (error) {
      console.error('Error finding open positions:', error);
      throw error;
    }
  }

  /**
   * Find all positions (open and closed) for a portfolio
   */
  static async findAllByPortfolioId(portfolioId, limit = 100, offset = 0) {
    const query = `
      SELECT * FROM positions
      WHERE portfolio_id = $1
      ORDER BY opened_at DESC
      LIMIT $2 OFFSET $3
    `;
    try {
      const { rows } = await pool.query(query, [portfolioId, limit, offset]);
      return rows;
    } catch (error) {
      console.error('Error finding positions:', error);
      throw error;
    }
  }

  /**
   * Update position price and P&L
   */
  static async updatePrice(positionId, currentPrice) {
    const query = `
      SELECT * FROM positions WHERE id = $1 AND status = 'open'
    `;
    
    try {
      const { rows } = await pool.query(query, [positionId]);
      if (rows.length === 0) return null;

      const position = rows[0];
      
      // Calculate unrealized P&L
      const priceDiff = position.side === 'long'
        ? currentPrice - position.entry_price
        : position.entry_price - currentPrice;
      
      const unrealizedPnl = (priceDiff * position.quantity) - position.fees_paid;
      const unrealizedPnlPercent = (priceDiff / position.entry_price) * 100;

      // Update position
      const updateQuery = `
        UPDATE positions
        SET current_price = $1,
            unrealized_pnl = $2,
            unrealized_pnl_percent = $3,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $4
        RETURNING *
      `;

      const { rows: updatedRows } = await pool.query(updateQuery, [
        currentPrice,
        unrealizedPnl,
        unrealizedPnlPercent,
        positionId
      ]);

      // Record price update in history
      await pool.query(`
        INSERT INTO position_updates (position_id, price, unrealized_pnl, unrealized_pnl_percent)
        VALUES ($1, $2, $3, $4)
      `, [positionId, currentPrice, unrealizedPnl, unrealizedPnlPercent]);

      return updatedRows[0];
    } catch (error) {
      console.error('Error updating position price:', error);
      throw error;
    }
  }

  /**
   * Close a position
   */
  static async close(positionId, closePrice, closeReason = 'manual') {
    const query = `
      SELECT * FROM positions WHERE id = $1 AND status = 'open'
    `;
    
    try {
      const { rows } = await pool.query(query, [positionId]);
      if (rows.length === 0) {
        throw new Error('Position not found or already closed');
      }

      const position = rows[0];
      
      // Calculate realized P&L
      const priceDiff = position.side === 'long'
        ? closePrice - position.entry_price
        : position.entry_price - closePrice;
      
      const realizedPnl = (priceDiff * position.quantity) - position.fees_paid;
      const realizedPnlPercent = (priceDiff / position.entry_price) * 100;

      // Close position
      const updateQuery = `
        UPDATE positions
        SET status = 'closed',
            current_price = $1,
            unrealized_pnl = $2,
            unrealized_pnl_percent = $3,
            closed_at = CURRENT_TIMESTAMP,
            close_reason = $4,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $5
        RETURNING *
      `;

      const { rows: closedRows } = await pool.query(updateQuery, [
        closePrice,
        realizedPnl,
        realizedPnlPercent,
        closeReason,
        positionId
      ]);

      // Update portfolio P&L
      await pool.query(`
        UPDATE portfolios
        SET total_pnl = total_pnl + $1,
            total_pnl_percentage = ((total_value + total_pnl + $1 - starting_capital) / starting_capital) * 100,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $2
      `, [realizedPnl, position.portfolio_id]);

      console.log(`✅ Position closed: ${position.symbol} ${position.side.toUpperCase()} - P&L: $${realizedPnl.toFixed(2)} (${realizedPnlPercent.toFixed(2)}%)`);

      return closedRows[0];
    } catch (error) {
      console.error('Error closing position:', error);
      throw error;
    }
  }

  /**
   * Partially close a position (for partial profit taking)
   */
  static async partialClose(positionId, quantityToClose, closePrice, closeReason = 'partial_profit') {
    const query = `
      SELECT * FROM positions WHERE id = $1 AND status = 'open'
    `;
    
    try {
      const { rows } = await pool.query(query, [positionId]);
      if (rows.length === 0) {
        throw new Error('Position not found or already closed');
      }

      const position = rows[0];
      
      if (quantityToClose >= position.quantity) {
        // Close entire position if quantity to close is >= total quantity
        return await this.close(positionId, closePrice, closeReason);
      }

      // Calculate P&L for the closed portion
      const priceDiff = position.side === 'long'
        ? closePrice - position.entry_price
        : position.entry_price - closePrice;
      
      const partialPnl = priceDiff * quantityToClose;
      const remainingQuantity = position.quantity - quantityToClose;

      // Update position quantity
      const updateQuery = `
        UPDATE positions
        SET quantity = $1,
            current_price = $2,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $3
        RETURNING *
      `;

      const { rows: updatedRows } = await pool.query(updateQuery, [
        remainingQuantity,
        closePrice,
        positionId
      ]);

      // Update portfolio P&L
      await pool.query(`
        UPDATE portfolios
        SET total_pnl = total_pnl + $1,
            total_pnl_percentage = ((total_value + total_pnl + $1 - starting_capital) / starting_capital) * 100,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $2
      `, [partialPnl, position.portfolio_id]);

      console.log(`📊 Partial close: ${position.symbol} ${position.side.toUpperCase()} - Closed ${quantityToClose}/${position.quantity} - P&L: $${partialPnl.toFixed(2)}`);

      return updatedRows[0];
    } catch (error) {
      console.error('Error partially closing position:', error);
      throw error;
    }
  }

  /**
   * Update position metadata (for tracking trailing stops, etc.)
   */
  static async updateMetadata(positionId, metadata) {
    const query = `
      UPDATE positions
      SET metadata = $1,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $2
      RETURNING *
    `;

    try {
      const { rows } = await pool.query(query, [JSON.stringify(metadata), positionId]);
      return rows[0];
    } catch (error) {
      console.error('Error updating position metadata:', error);
      throw error;
    }
  }

  /**
   * Get position history (price updates)
   */
  static async getHistory(positionId, limit = 100) {
    const query = `
      SELECT * FROM position_updates
      WHERE position_id = $1
      ORDER BY timestamp DESC
      LIMIT $2
    `;

    try {
      const { rows } = await pool.query(query, [positionId, limit]);
      return rows.reverse(); // Return chronological order
    } catch (error) {
      console.error('Error getting position history:', error);
      throw error;
    }
  }

  /**
   * Calculate liquidation price for a leveraged position
   * @param {number} entryPrice - Entry price of position
   * @param {number} leverage - Leverage multiplier (1.0 = no leverage)
   * @param {string} side - 'long' or 'short'
   * @param {number} bufferPercent - Buffer percentage before liquidation
   * @returns {number} Liquidation price
   */
  static calculateLiquidationPrice(entryPrice, leverage, side, bufferPercent = 0) {
    if (leverage <= 1) return 0; // No leverage = no liquidation

    const bufferFactor = bufferPercent / 100;

    if (side === 'long') {
      // Long: price drops to liquidation when losses exceed initial margin
      // Formula: liquidationPrice = entryPrice * (1 - (1 / leverage) + bufferFactor)
      return entryPrice * (1 - (1 / leverage) + bufferFactor);
    } else if (side === 'short') {
      // Short: price rises to liquidation when losses exceed initial margin
      // Formula: liquidationPrice = entryPrice * (1 + (1 / leverage) - bufferFactor)
      return entryPrice * (1 + (1 / leverage) - bufferFactor);
    }

    return 0;
  }

  /**
   * Update margin ratio for a position
   * @param {string} positionId - Position ID
   * @param {number} currentPrice - Current market price
   * @returns {Object} Updated position data
   */
  static async updateMarginRatio(positionId, currentPrice) {
    const position = await this.findById(positionId);
    if (!position) {
      throw new Error(`Position ${positionId} not found`);
    }

    if (position.leverage <= 1) {
      // No leverage - margin ratio is always 100%
      return position;
    }

    const positionValue = position.quantity * currentPrice;
    const equity = position.initial_margin + position.unrealized_pnl;
    const marginRatio = (equity / position.maintenance_margin) * 100;

    const query = `
      UPDATE positions
      SET margin_ratio = $1,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $2
      RETURNING *
    `;

    try {
      const { rows } = await pool.query(query, [marginRatio, positionId]);
      return rows[0];
    } catch (error) {
      console.error('Error updating margin ratio:', error);
      throw error;
    }
  }

  /**
   * Check if position should be liquidated
   * @param {Object} position - Position data
   * @param {number} bufferPercent - Buffer percentage
   * @returns {boolean} True if should be liquidated
   */
  static shouldLiquidate(position, bufferPercent = 0) {
    if (position.leverage <= 1 || !position.liquidation_price) {
      return false;
    }

    const currentPrice = position.current_price;
    const liquidationPrice = position.liquidation_price;

    if (position.side === 'long') {
      // Long position liquidated when price drops below liquidation price
      return currentPrice <= liquidationPrice;
    } else if (position.side === 'short') {
      // Short position liquidated when price rises above liquidation price
      return currentPrice >= liquidationPrice;
    }

    return false;
  }

  /**
   * Get positions at risk of liquidation
   * @param {string} userId - User ID
   * @param {number} marginThreshold - Margin ratio threshold (e.g., 20 for 20%)
   * @returns {Array} Positions with low margin ratios
   */
  static async getPositionsAtRisk(userId, marginThreshold = 20) {
    const query = `
      SELECT * FROM positions
      WHERE user_id = $1
        AND status = 'open'
        AND leverage > 1
        AND margin_ratio <= $2
      ORDER BY margin_ratio ASC
    `;

    try {
      const { rows } = await pool.query(query, [userId, marginThreshold]);
      return rows;
    } catch (error) {
      console.error('Error getting positions at risk:', error);
      throw error;
    }
  }
}

export default Position;

