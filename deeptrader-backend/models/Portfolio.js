/**
 * Portfolio Model
 * Handles user portfolios and trading data in PostgreSQL
 */

import pool from '../config/database.js';
import { v4 as uuidv4 } from 'uuid';

let _portfolioColumnsPromise = null;
async function getPortfolioColumns() {
  if (_portfolioColumnsPromise) return _portfolioColumnsPromise;
  _portfolioColumnsPromise = (async () => {
    const res = await pool.query(
      `select column_name
       from information_schema.columns
       where table_schema='public' and table_name='portfolios'`
    );
    return new Set(res.rows.map((r) => r.column_name));
  })();
  return _portfolioColumnsPromise;
}

export class Portfolio {
  constructor(data) {
    this.id = data.id;
    this.userId = data.user_id;
    this.name = data.name;
    this.description = data.description ?? null;
    this.startingCapital = parseFloat(data.starting_capital ?? 0);
    this.currentCapital = parseFloat(data.current_capital ?? data.starting_capital ?? 0);
    this.totalValue = parseFloat(data.total_value ?? data.current_capital ?? data.starting_capital ?? 0);
    this.totalPnL = parseFloat(data.total_pnl ?? 0);
    this.totalPnLPercentage = parseFloat(data.total_pnl_percentage ?? 0);
    this.isPaperTrading = data.is_paper_trading ?? true;
    this.isActive = data.is_active ?? true;
    this.createdAt = data.created_at;
    this.updatedAt = data.updated_at;
  }

  /**
   * Create a new portfolio
   */
  static async create(userId, portfolioData = {}) {
    const {
      name = 'Main Portfolio',
      description,
      startingCapital = 10000.00,
      isPaperTrading = true
    } = portfolioData;

    const cols = await getPortfolioColumns();

    // Support both schemas:
    // - full schema: description/starting_capital/current_capital/total_value/is_paper_trading/etc.
    // - minimal schema (AWS dev/local drift): only (user_id, name, timestamps, plus a couple metrics)
    const insertCols = ['user_id', 'name'];
    const insertVals = [userId, name];

    if (cols.has('description')) {
      insertCols.push('description');
      insertVals.push(description);
    }
    if (cols.has('starting_capital')) {
      insertCols.push('starting_capital');
      insertVals.push(startingCapital);
    }
    if (cols.has('current_capital')) {
      insertCols.push('current_capital');
      insertVals.push(startingCapital);
    }
    if (cols.has('total_value')) {
      insertCols.push('total_value');
      insertVals.push(startingCapital);
    }
    if (cols.has('is_paper_trading')) {
      insertCols.push('is_paper_trading');
      insertVals.push(isPaperTrading);
    }
    if (cols.has('open_positions_count')) {
      insertCols.push('open_positions_count');
      insertVals.push(0);
    }
    if (cols.has('total_unrealized_pnl')) {
      insertCols.push('total_unrealized_pnl');
      insertVals.push(0);
    }

    const placeholders = insertVals.map((_, idx) => `$${idx + 1}`).join(', ');
    const query = `INSERT INTO portfolios (${insertCols.join(', ')}) VALUES (${placeholders}) RETURNING *`;

    const result = await pool.query(query, insertVals);

    return new Portfolio(result.rows[0]);
  }

  /**
   * Find portfolio by ID
   */
  static async findById(id) {
    const query = 'SELECT * FROM portfolios WHERE id = $1 AND is_active = true';
    const result = await pool.query(query, [id]);
    return result.rows[0] ? new Portfolio(result.rows[0]) : null;
  }

  /**
   * Find portfolios by user ID
   */
  static async findByUserId(userId) {
    const query = 'SELECT * FROM portfolios WHERE user_id = $1 AND is_active = true ORDER BY created_at DESC';
    const result = await pool.query(query, [userId]);
    return result.rows.map(row => new Portfolio(row));
  }

  /**
   * Get default portfolio for user (first one created)
   */
  static async getDefaultPortfolio(userId) {
    const query = 'SELECT * FROM portfolios WHERE user_id = $1 AND is_active = true ORDER BY created_at ASC LIMIT 1';
    const result = await pool.query(query, [userId]);
    return result.rows[0] ? new Portfolio(result.rows[0]) : null;
  }

  /**
   * Update portfolio values
   */
  async update(values) {
    const { currentCapital, totalValue, totalPnL, totalPnLPercentage } = values;

    const query = `
      UPDATE portfolios
      SET current_capital = $1, total_value = $2, total_pnl = $3, total_pnl_percentage = $4, updated_at = CURRENT_TIMESTAMP
      WHERE id = $5
      RETURNING *
    `;

    const result = await pool.query(query, [
      currentCapital,
      totalValue,
      totalPnL,
      totalPnLPercentage,
      this.id
    ]);

    Object.assign(this, result.rows[0]);
    return this;
  }

  /**
   * Add equity point to history
   */
  async addEquityPoint(value, capital, pnl = 0) {
    const query = `
      INSERT INTO portfolio_equity (portfolio_id, value, capital, pnl)
      VALUES ($1, $2, $3, $4)
    `;

    await pool.query(query, [this.id, value, capital, pnl]);
  }

  /**
   * Get equity curve
   */
  async getEquityCurve(limit = 1000) {
    const query = `
      SELECT timestamp, value, capital, pnl
      FROM portfolio_equity
      WHERE portfolio_id = $1
      ORDER BY timestamp DESC
      LIMIT $2
    `;

    const result = await pool.query(query, [this.id, limit]);
    return result.rows.reverse(); // Return chronological order
  }

  /**
   * Get trades
   */
  async getTrades(status = null, limit = 100, offset = 0) {
    let query = 'SELECT * FROM trades WHERE portfolio_id = $1';
    const params = [this.id];
    let paramCount = 1;

    if (status) {
      query += ` AND status = $${++paramCount}`;
      params.push(status);
    }

    query += ` ORDER BY entry_time DESC LIMIT $${++paramCount} OFFSET $${++paramCount}`;
    params.push(limit, offset);

    const result = await pool.query(query, params);
    return result.rows;
  }

  /**
   * Get trade statistics
   */
  async getTradeStats() {
    const query = `
      SELECT
        COUNT(*) as total_trades,
        COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed_trades,
        COUNT(CASE WHEN status = 'open' THEN 1 END) as open_trades,
        COUNT(CASE WHEN status = 'closed' AND pnl > 0 THEN 1 END) as winning_trades,
        COUNT(CASE WHEN status = 'closed' AND pnl < 0 THEN 1 END) as losing_trades,
        COALESCE(SUM(CASE WHEN status = 'closed' THEN pnl ELSE 0 END), 0) as total_pnl,
        COALESCE(AVG(CASE WHEN status = 'closed' AND pnl > 0 THEN pnl END), 0) as avg_win,
        COALESCE(AVG(CASE WHEN status = 'closed' AND pnl < 0 THEN pnl END), 0) as avg_loss,
        COALESCE(MAX(CASE WHEN status = 'closed' THEN pnl END), 0) as best_trade,
        COALESCE(MIN(CASE WHEN status = 'closed' THEN pnl END), 0) as worst_trade
      FROM trades
      WHERE portfolio_id = $1
    `;

    const result = await pool.query(query, [this.id]);
    const stats = result.rows[0];

    // Calculate additional metrics
    const winRate = stats.total_trades > 0 ? (stats.winning_trades / stats.closed_trades) * 100 : 0;
    const profitFactor = Math.abs(stats.avg_loss) > 0 ? (stats.avg_win * stats.winning_trades) / (Math.abs(stats.avg_loss) * stats.losing_trades) : 0;

    return {
      ...stats,
      winRate,
      profitFactor,
      expectancy: stats.avg_win * (stats.winning_trades / stats.closed_trades) + stats.avg_loss * (stats.losing_trades / stats.closed_trades)
    };
  }

  /**
   * Add a trade
   */
  async addTrade(tradeData) {
    const {
      externalId,
      token,
      side,
      orderType = 'market',
      quantity,
      price,
      totalValue,
      fees = 0,
      stopLoss,
      takeProfit,
      aiReasoning,
      strategy
    } = tradeData;

    const query = `
      INSERT INTO trades (
        portfolio_id, external_id, token, side, order_type, quantity, price,
        total_value, fees, stop_loss, take_profit, ai_reasoning, strategy
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
      RETURNING *
    `;

    const result = await pool.query(query, [
      this.id, externalId, token, side, orderType, quantity, price,
      totalValue, fees, stopLoss, takeProfit, aiReasoning, strategy
    ]);

    return result.rows[0];
  }

  /**
   * Close a trade
   */
  async closeTrade(tradeId, exitPrice, exitReason = 'manual') {
    const exitTime = new Date();

    // First get the trade to calculate P&L
    const tradeQuery = 'SELECT * FROM trades WHERE id = $1 AND portfolio_id = $2';
    const tradeResult = await pool.query(tradeQuery, [tradeId, this.id]);

    if (tradeResult.rows.length === 0) {
      throw new Error('Trade not found');
    }

    const trade = tradeResult.rows[0];
    const pnl = trade.side === 'buy'
      ? (exitPrice - trade.price) * trade.quantity - trade.fees
      : (trade.price - exitPrice) * trade.quantity - trade.fees;

    const pnlPercentage = trade.price > 0 ? (pnl / (trade.price * trade.quantity)) * 100 : 0;

    // Update the trade
    const updateQuery = `
      UPDATE trades
      SET status = 'closed', exit_price = $1, exit_time = $2, exit_reason = $3, pnl = $4, pnl_percentage = $5, updated_at = CURRENT_TIMESTAMP
      WHERE id = $6 AND portfolio_id = $7
      RETURNING *
    `;

    const result = await pool.query(updateQuery, [
      exitPrice, exitTime, exitReason, pnl, pnlPercentage, tradeId, this.id
    ]);

    // Update portfolio P&L
    await this.recalculatePnL();

    return result.rows[0];
  }

  /**
   * Recalculate portfolio P&L from all closed trades
   */
  async recalculatePnL() {
    const query = `
      SELECT
        COALESCE(SUM(pnl), 0) as total_pnl,
        CASE WHEN $1 > 0 THEN ROUND((COALESCE(SUM(pnl), 0) / $1) * 100, 4) ELSE 0 END as total_pnl_percentage,
        $1 + COALESCE(SUM(pnl), 0) as total_value
      FROM trades
      WHERE portfolio_id = $2 AND status = 'closed'
    `;

    const result = await pool.query(query, [this.startingCapital, this.id]);
    const { total_pnl, total_pnl_percentage, total_value } = result.rows[0];

    await this.update({
      totalPnL: total_pnl,
      totalPnLPercentage: total_pnl_percentage,
      totalValue: total_value,
      currentCapital: total_value // For paper trading
    });
  }

  /**
   * Get open positions
   */
  async getOpenPositions() {
    const query = 'SELECT * FROM trades WHERE portfolio_id = $1 AND status = $2 ORDER BY entry_time DESC';
    const result = await pool.query(query, [this.id, 'open']);
    return result.rows;
  }

  /**
   * Get performance metrics
   */
  async getPerformanceMetrics() {
    const trades = await this.getTrades('closed', 1000);
    if (trades.length === 0) {
      return {
        totalReturn: 0,
        totalReturnPercentage: 0,
        sharpeRatio: 0,
        maxDrawdown: 0,
        winRate: 0,
        profitFactor: 0,
        expectancy: 0,
        totalTrades: 0
      };
    }

    // Calculate returns
    const returns = trades.map(trade => trade.pnl_percentage / 100);
    const avgReturn = returns.reduce((sum, r) => sum + r, 0) / returns.length;

    // Calculate Sharpe ratio (simplified)
    const stdDev = Math.sqrt(returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length);
    const sharpeRatio = stdDev > 0 ? avgReturn / stdDev : 0;

    // Calculate max drawdown
    let peak = 0;
    let maxDrawdown = 0;
    let runningReturn = 0;

    for (const trade of trades.sort((a, b) => new Date(a.exit_time) - new Date(b.exit_time))) {
      runningReturn += trade.pnl_percentage / 100;
      if (runningReturn > peak) {
        peak = runningReturn;
      }
      const drawdown = peak - runningReturn;
      if (drawdown > maxDrawdown) {
        maxDrawdown = drawdown;
      }
    }

    const winningTrades = trades.filter(t => t.pnl > 0);
    const losingTrades = trades.filter(t => t.pnl < 0);

    const winRate = trades.length > 0 ? (winningTrades.length / trades.length) * 100 : 0;
    const avgWin = winningTrades.length > 0 ? winningTrades.reduce((sum, t) => sum + t.pnl, 0) / winningTrades.length : 0;
    const avgLoss = losingTrades.length > 0 ? losingTrades.reduce((sum, t) => sum + t.pnl, 0) / losingTrades.length : 0;
    const profitFactor = Math.abs(avgLoss) > 0 ? (avgWin * winningTrades.length) / (Math.abs(avgLoss) * losingTrades.length) : 0;
    const expectancy = (avgWin * winRate / 100) + (avgLoss * (100 - winRate) / 100);

    return {
      totalReturn: trades.reduce((sum, t) => sum + t.pnl, 0),
      totalReturnPercentage: (trades.reduce((sum, t) => sum + t.pnl, 0) / this.startingCapital) * 100,
      sharpeRatio,
      maxDrawdown: maxDrawdown * 100,
      winRate,
      profitFactor,
      expectancy,
      totalTrades: trades.length,
      avgWin,
      avgLoss
    };
  }

  /**
   * Reset portfolio
   */
  async reset() {
    const query = `
      UPDATE portfolios
      SET current_capital = starting_capital,
          total_value = starting_capital,
          total_pnl = 0,
          total_pnl_percentage = 0,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
    `;

    await pool.query(query, [this.id]);

    // Close all open trades
    await pool.query('UPDATE trades SET status = $1 WHERE portfolio_id = $2 AND status = $3', ['cancelled', this.id, 'open']);

    // Clear equity curve
    await pool.query('DELETE FROM portfolio_equity WHERE portfolio_id = $1', [this.id]);

    // Add starting point back
    await this.addEquityPoint(this.startingCapital, this.startingCapital, 0);

    // Update instance
    this.currentCapital = this.startingCapital;
    this.totalValue = this.startingCapital;
    this.totalPnL = 0;
    this.totalPnLPercentage = 0;
  }

  /**
   * Delete portfolio (soft delete)
   */
  async delete() {
    const query = 'UPDATE portfolios SET is_active = false, updated_at = CURRENT_TIMESTAMP WHERE id = $1';
    await pool.query(query, [this.id]);
    this.isActive = false;
  }

  /**
   * To JSON for API responses
   */
  toJSON() {
    return {
      id: this.id,
      userId: this.userId,
      name: this.name,
      description: this.description,
      startingCapital: this.startingCapital,
      currentCapital: this.currentCapital,
      totalValue: this.totalValue,
      totalPnL: this.totalPnL,
      totalPnLPercentage: this.totalPnLPercentage,
      isPaperTrading: this.isPaperTrading,
      isActive: this.isActive,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt
    };
  }
}

// Helper functions
export const createPortfolio = Portfolio.create;
export const findPortfolioById = Portfolio.findById;
export const findPortfoliosByUserId = Portfolio.findByUserId;
export const getDefaultPortfolio = Portfolio.getDefaultPortfolio;
