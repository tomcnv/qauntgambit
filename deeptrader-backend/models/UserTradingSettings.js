/**
 * User Trading Settings Model
 * Stores user preferences for AI trading behavior and order types
 */

import pool from '../config/database.js';
import { v4 as uuidv4 } from 'uuid';

class UserTradingSettings {
  /**
   * Get user trading settings, create defaults if none exist
   */
  static async getSettings(userId) {
    let query = `SELECT * FROM user_trading_settings WHERE user_id = $1`;
    const { rows } = await pool.query(query, [userId]);

    if (rows.length > 0) {
      return rows[0];
    }

    // Create default settings
    return await this.createDefaultSettings(userId);
  }

  /**
   * Create default trading settings for a new user
   */
  static async createDefaultSettings(userId) {
    const defaultSettings = {
      userId,
      enabledOrderTypes: ['bracket'], // Default to bracket orders only
      orderTypeSettings: {
        market: {
          enabled: false,
          slippageLimit: 0.005, // 0.5% max slippage
          postOnly: false
        },
        limit: {
          enabled: false,
          timeInForce: 'GTC', // Good Till Cancelled
          postOnly: true,
          icebergQty: null
        },
        stop_loss: {
          enabled: false,
          timeInForce: 'GTC',
          reduceOnly: true,
          closePosition: false
        },
        stop_limit: {
          enabled: false,
          timeInForce: 'GTC',
          reduceOnly: true
        },
        trailing_stop: {
          enabled: false,
          activationPrice: null, // Calculated dynamically
          callbackRate: 0.01, // 1% trailing
          reduceOnly: true
        },
        take_profit: {
          enabled: false,
          timeInForce: 'GTC',
          reduceOnly: true,
          closePosition: false
        },
        bracket: {
          enabled: true, // Default enabled
          stopLossPercent: 0.02, // 2% stop loss
          takeProfitPercent: 0.05, // 5% take profit
          timeInForce: 'GTC'
        },
        oco: {
          enabled: false,
          timeInForce: 'GTC'
        }
      },
      riskProfile: 'moderate',
      maxConcurrentPositions: 4,
      maxPositionSizePercent: 0.10, // 10% of capital per position
      maxTotalExposurePercent: 0.40, // 40% total exposure
      aiConfidenceThreshold: 7.0, // 0-10 scale
      tradingInterval: 300000, // 5 minutes
      enabledTokens: ['SOLUSDT'],
      // Per-token overrides (safe defaults, inherit from globals if not set)
      perTokenSettings: {
        BTCUSDT: { enabled: false, positionSizePct: 0.10, leverage: 1 },
        ETHUSDT: { enabled: false, positionSizePct: 0.10, leverage: 1 },
        SOLUSDT: { enabled: true, positionSizePct: 0.25, leverage: 1 },
        TAOUSDT: { enabled: false, positionSizePct: 0.05, leverage: 1 },
        ZECUSDT: { enabled: false, positionSizePct: 0.05, leverage: 1 },
      },
      dayTradingEnabled: false,
      scalpingMode: false,
      trailingStopsEnabled: true,
      partialProfitsEnabled: true,
      timeBasedExitsEnabled: true,
      multiTimeframeConfirmation: false,
      // Day Trading Mode settings
      dayTradingMaxHoldingHours: 8.0,
      dayTradingStartTime: '09:30:00',
      dayTradingEndTime: '15:30:00',
      dayTradingForceCloseTime: '15:45:00',
      dayTradingDaysOnly: false,
      // Scalping Mode settings
      scalpingTargetProfitPercent: 0.005,
      scalpingMaxHoldingMinutes: 15,
      scalpingMinVolumeMultiplier: 2.0,
      // Trailing Stops settings
      trailingStopActivationPercent: 0.02,
      trailingStopCallbackPercent: 0.01,
      trailingStopStepPercent: 0.005,
      // Partial Profit Taking settings
      partialProfitLevels: [
        { percent: 25, target: 0.03 },
        { percent: 25, target: 0.05 },
        { percent: 25, target: 0.08 },
        { percent: 25, target: 0.12 }
      ],
      // Time-Based Exits settings
      timeExitMaxHoldingHours: 24.0,
      timeExitBreakEvenHours: 4.0,
      timeExitWeekendClose: true,
      // Multi-Timeframe Confirmation settings
      mtfRequiredTimeframes: ['15m', '1h', '4h'],
      mtfMinConfirmations: 2,
      mtfTrendAlignmentRequired: true,
      // Leverage & Margin Trading settings
      leverageEnabled: false,
      maxLeverage: 1.0,
      leverageMode: 'isolated',
      liquidationBufferPercent: 0.05,
      marginCallThresholdPercent: 0.20,
      availableLeverageLevels: [1, 2, 3, 5, 10]
    };

    const query = `
      INSERT INTO user_trading_settings (
        id, user_id, enabled_order_types, order_type_settings, risk_profile,
        max_concurrent_positions, max_position_size_percent, max_total_exposure_percent,
        ai_confidence_threshold, trading_interval, enabled_tokens, per_token_settings, day_trading_enabled,
        scalping_mode, trailing_stops_enabled, partial_profits_enabled,
        time_based_exits_enabled, multi_timeframe_confirmation,
        day_trading_max_holding_hours, day_trading_start_time, day_trading_end_time,
        day_trading_force_close_time, day_trading_days_only,
        scalping_target_profit_percent, scalping_max_holding_minutes, scalping_min_volume_multiplier,
        trailing_stop_activation_percent, trailing_stop_callback_percent, trailing_stop_step_percent,
        partial_profit_levels,
        time_exit_max_holding_hours, time_exit_break_even_hours, time_exit_weekend_close,
        mtf_required_timeframes, mtf_min_confirmations, mtf_trend_alignment_required,
        leverage_enabled, max_leverage, leverage_mode, liquidation_buffer_percent,
        margin_call_threshold_percent, available_leverage_levels
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18,
                $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31, $32, $33, $34, $35, $36,
                $37, $38, $39, $40, $41, $42)
      RETURNING *
    `;

    const values = [
      uuidv4(),
      userId,
      defaultSettings.enabledOrderTypes, // PostgreSQL ARRAY - pass as-is
      JSON.stringify(defaultSettings.orderTypeSettings), // JSONB - stringify
      defaultSettings.riskProfile,
      defaultSettings.maxConcurrentPositions,
      defaultSettings.maxPositionSizePercent,
      defaultSettings.maxTotalExposurePercent,
      defaultSettings.aiConfidenceThreshold,
      defaultSettings.tradingInterval,
      defaultSettings.enabledTokens, // PostgreSQL ARRAY - pass as-is
      JSON.stringify(defaultSettings.perTokenSettings),
      defaultSettings.dayTradingEnabled,
      defaultSettings.scalpingMode,
      defaultSettings.trailingStopsEnabled,
      defaultSettings.partialProfitsEnabled,
      defaultSettings.timeBasedExitsEnabled,
      defaultSettings.multiTimeframeConfirmation,
      defaultSettings.dayTradingMaxHoldingHours,
      defaultSettings.dayTradingStartTime,
      defaultSettings.dayTradingEndTime,
      defaultSettings.dayTradingForceCloseTime,
      defaultSettings.dayTradingDaysOnly,
      defaultSettings.scalpingTargetProfitPercent,
      defaultSettings.scalpingMaxHoldingMinutes,
      defaultSettings.scalpingMinVolumeMultiplier,
      defaultSettings.trailingStopActivationPercent,
      defaultSettings.trailingStopCallbackPercent,
      defaultSettings.trailingStopStepPercent,
      JSON.stringify(defaultSettings.partialProfitLevels),
      defaultSettings.timeExitMaxHoldingHours,
      defaultSettings.timeExitBreakEvenHours,
      defaultSettings.timeExitWeekendClose,
      defaultSettings.mtfRequiredTimeframes,
      defaultSettings.mtfMinConfirmations,
      defaultSettings.mtfTrendAlignmentRequired,
      defaultSettings.leverageEnabled,
      defaultSettings.maxLeverage,
      defaultSettings.leverageMode,
      defaultSettings.liquidationBufferPercent,
      defaultSettings.marginCallThresholdPercent,
      defaultSettings.availableLeverageLevels
    ];

    const { rows } = await pool.query(query, values);
    return rows[0];
  }

  /**
   * Update user trading settings
   */
  static async updateSettings(userId, settings) {
    // First, check if settings exist for this user
    const existing = await this.getSettings(userId);
    
    // If no settings exist, create defaults first
    if (!existing) {
      await this.createDefaultSettings(userId);
    }
    
    // Build dynamic UPDATE query based on provided fields
    const updates = [];
    const values = [userId];
    let paramIndex = 2;

    const fieldMappings = {
      enabledOrderTypes: 'enabled_order_types',
      orderTypeSettings: 'order_type_settings',
      riskProfile: 'risk_profile',
      maxConcurrentPositions: 'max_concurrent_positions',
      maxPositionSizePercent: 'max_position_size_percent',
      maxTotalExposurePercent: 'max_total_exposure_percent',
      aiConfidenceThreshold: 'ai_confidence_threshold',
      tradingInterval: 'trading_interval',
      enabledTokens: 'enabled_tokens',
      perTokenSettings: 'per_token_settings',
      dayTradingEnabled: 'day_trading_enabled',
      scalpingMode: 'scalping_mode',
      trailingStopsEnabled: 'trailing_stops_enabled',
      partialProfitsEnabled: 'partial_profits_enabled',
      timeBasedExitsEnabled: 'time_based_exits_enabled',
      multiTimeframeConfirmation: 'multi_timeframe_confirmation',
      dayTradingMaxHoldingHours: 'day_trading_max_holding_hours',
      dayTradingStartTime: 'day_trading_start_time',
      dayTradingEndTime: 'day_trading_end_time',
      dayTradingForceCloseTime: 'day_trading_force_close_time',
      dayTradingDaysOnly: 'day_trading_days_only',
      scalpingTargetProfitPercent: 'scalping_target_profit_percent',
      scalpingMaxHoldingMinutes: 'scalping_max_holding_minutes',
      scalpingMinVolumeMultiplier: 'scalping_min_volume_multiplier',
      trailingStopActivationPercent: 'trailing_stop_activation_percent',
      trailingStopCallbackPercent: 'trailing_stop_callback_percent',
      trailingStopStepPercent: 'trailing_stop_step_percent',
      partialProfitLevels: 'partial_profit_levels',
      timeExitMaxHoldingHours: 'time_exit_max_holding_hours',
      timeExitBreakEvenHours: 'time_exit_break_even_hours',
      timeExitWeekendClose: 'time_exit_weekend_close',
      mtfRequiredTimeframes: 'mtf_required_timeframes',
      mtfMinConfirmations: 'mtf_min_confirmations',
      mtfTrendAlignmentRequired: 'mtf_trend_alignment_required',
      leverageEnabled: 'leverage_enabled',
      maxLeverage: 'max_leverage',
      leverageMode: 'leverage_mode',
      liquidationBufferPercent: 'liquidation_buffer_percent',
      marginCallThresholdPercent: 'margin_call_threshold_percent',
      availableLeverageLevels: 'available_leverage_levels'
    };

    // JSONB fields that need stringification
    const jsonFields = ['orderTypeSettings', 'partialProfitLevels', 'perTokenSettings'];
    
    // PostgreSQL ARRAY fields that should be passed as-is (not stringified)
    const arrayFields = ['enabledOrderTypes', 'enabledTokens', 'mtfRequiredTimeframes', 'availableLeverageLevels'];

    for (const [camelKey, snakeKey] of Object.entries(fieldMappings)) {
      if (settings[camelKey] !== undefined) {
        updates.push(`${snakeKey} = $${paramIndex}`);
        let value;
        if (jsonFields.includes(camelKey)) {
          value = JSON.stringify(settings[camelKey]);
        } else if (arrayFields.includes(camelKey)) {
          // Pass array as-is for PostgreSQL array columns
          value = Array.isArray(settings[camelKey]) ? settings[camelKey] : [settings[camelKey]];
        } else {
          value = settings[camelKey];
        }
        values.push(value);
        paramIndex++;
      }
    }

    if (updates.length === 0) {
      throw new Error('No fields to update');
    }

    updates.push('updated_at = CURRENT_TIMESTAMP');

    const query = `
      UPDATE user_trading_settings
      SET ${updates.join(', ')}
      WHERE user_id = $1
      RETURNING *
    `;

    const { rows } = await pool.query(query, values);
    return rows[0];
  }

  /**
   * Get order type settings for a user
   */
  static async getOrderTypeSettings(userId, orderType) {
    const settings = await this.getSettings(userId);
    return settings.order_type_settings[orderType] || null;
  }

  /**
   * Check if order type is enabled for user
   */
  static async isOrderTypeEnabled(userId, orderType) {
    const settings = await this.getSettings(userId);
    return settings.enabled_order_types.includes(orderType);
  }

  /**
   * Get enabled order types for user
   */
  static async getEnabledOrderTypes(userId) {
    const settings = await this.getSettings(userId);
    return settings.enabled_order_types || [];
  }

  /**
   * Reset settings to defaults
   */
  static async resetToDefaults(userId) {
    // Delete existing settings
    await pool.query('DELETE FROM user_trading_settings WHERE user_id = $1', [userId]);

    // Create new defaults
    return await this.createDefaultSettings(userId);
  }
}

export default UserTradingSettings;
