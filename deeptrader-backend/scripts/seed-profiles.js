#!/usr/bin/env node
/**
 * Seed profiles and strategy instances for testing
 */

import pool from '../config/database.js';
import { randomUUID } from 'crypto';

async function seed() {
  try {
    // Get the first user
    const users = await pool.query('SELECT id FROM users LIMIT 1');
    if (users.rows.length === 0) {
      console.error('❌ No users found. Create a user first.');
      process.exit(1);
    }
    const userId = users.rows[0].id;
    console.log('👤 Using user:', userId);
    
    console.log('\n🌱 Seeding strategy instances...');
    
    // Create some strategy instances
    const instances = [
      {
        id: randomUUID(),
        templateId: 'momentum_rider',
        name: 'BTC Momentum Fast',
        description: 'Fast momentum strategy for BTC with tight stops',
        params: { lookback_period: 14, momentum_threshold: 0.02, stop_loss_pct: 1.5 }
      },
      {
        id: randomUUID(),
        templateId: 'mean_reversion',
        name: 'ETH Mean Reversion',
        description: 'Mean reversion for ETH using Bollinger Bands',
        params: { bb_period: 20, bb_std: 2.0, rsi_oversold: 30, rsi_overbought: 70 }
      },
      {
        id: randomUUID(),
        templateId: 'breakout_hunter',
        name: 'Breakout Scanner',
        description: 'Multi-timeframe breakout detection',
        params: { consolidation_periods: 20, breakout_threshold: 1.5, volume_multiplier: 2.0 }
      },
      {
        id: randomUUID(),
        templateId: 'scalper_pro',
        name: 'Quick Scalper',
        description: 'High-frequency scalping on 1m timeframe',
        params: { take_profit_pct: 0.3, stop_loss_pct: 0.15, max_hold_minutes: 15 }
      }
    ];
    
    for (const inst of instances) {
      await pool.query(
        `INSERT INTO strategy_instances (id, user_id, template_id, name, description, params) 
         VALUES ($1, $2, $3, $4, $5, $6)
         ON CONFLICT (user_id, name) DO NOTHING`,
        [inst.id, userId, inst.templateId, inst.name, inst.description, JSON.stringify(inst.params)]
      );
      console.log('  ✅ Created instance:', inst.name);
    }
    
    console.log('\n🌱 Seeding profiles...');
    
    // Create profiles with different environments
    const profiles = [
      {
        id: randomUUID(),
        name: 'Conservative Momentum',
        description: 'Safe momentum trading with strict risk controls',
        environment: 'dev',
        strategyComposition: [
          { strategy_instance_id: instances[0].id, weight: 0.7, priority: 1 },
          { strategy_instance_id: instances[1].id, weight: 0.3, priority: 2 }
        ],
        riskConfig: { max_leverage: 2, stop_loss_pct: 2, take_profit_pct: 4, risk_per_trade_pct: 1, max_drawdown_pct: 10 },
        conditions: { required_session: 'any', required_volatility: 'any', required_trend: 'any', max_spread_bps: 20 },
        lifecycle: { cooldown_after_loss_seconds: 300, warmup_candles: 5 },
        execution: { order_type: 'limit', slippage_tolerance_bps: 10 },
        isActive: true
      },
      {
        id: randomUUID(),
        name: 'Aggressive Breakout',
        description: 'High-conviction breakout trades with larger position sizes',
        environment: 'dev',
        strategyComposition: [
          { strategy_instance_id: instances[2].id, weight: 0.8, priority: 1 },
          { strategy_instance_id: instances[0].id, weight: 0.2, priority: 2 }
        ],
        riskConfig: { max_leverage: 5, stop_loss_pct: 3, take_profit_pct: 9, risk_per_trade_pct: 2, max_drawdown_pct: 15 },
        conditions: { required_session: 'us', required_volatility: 'high', required_trend: 'any', max_spread_bps: 30 },
        lifecycle: { cooldown_after_loss_seconds: 600, warmup_candles: 10 },
        execution: { order_type: 'market', slippage_tolerance_bps: 25 },
        isActive: false
      },
      {
        id: randomUUID(),
        name: 'Paper Test Profile',
        description: 'Profile promoted to paper trading for validation',
        environment: 'paper',
        strategyComposition: [
          { strategy_instance_id: instances[0].id, weight: 0.5, priority: 1 },
          { strategy_instance_id: instances[1].id, weight: 0.5, priority: 2 }
        ],
        riskConfig: { max_leverage: 3, stop_loss_pct: 2.5, take_profit_pct: 5, risk_per_trade_pct: 1.5, max_drawdown_pct: 12 },
        conditions: { required_session: 'any', required_volatility: 'medium', required_trend: 'any', max_spread_bps: 15 },
        lifecycle: { cooldown_after_loss_seconds: 180, warmup_candles: 3 },
        execution: { order_type: 'limit', slippage_tolerance_bps: 5 },
        isActive: true
      },
      {
        id: randomUUID(),
        name: 'Scalper Live',
        description: 'Battle-tested scalping profile for live trading',
        environment: 'live',
        strategyComposition: [
          { strategy_instance_id: instances[3].id, weight: 1.0, priority: 1 }
        ],
        riskConfig: { max_leverage: 2, stop_loss_pct: 0.5, take_profit_pct: 1, risk_per_trade_pct: 0.5, max_drawdown_pct: 5 },
        conditions: { required_session: 'us', required_volatility: 'low', required_trend: 'any', max_spread_bps: 5 },
        lifecycle: { cooldown_after_loss_seconds: 60, warmup_candles: 1 },
        execution: { order_type: 'limit', slippage_tolerance_bps: 3 },
        isActive: false
      }
    ];
    
    for (const p of profiles) {
      await pool.query(
        `INSERT INTO user_chessboard_profiles 
         (id, user_id, name, description, environment, strategy_composition, risk_config, conditions, lifecycle, execution, is_active, status) 
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'active')
         ON CONFLICT (user_id, name, environment) DO NOTHING`,
        [p.id, userId, p.name, p.description, p.environment, 
         JSON.stringify(p.strategyComposition), JSON.stringify(p.riskConfig), 
         JSON.stringify(p.conditions), JSON.stringify(p.lifecycle), JSON.stringify(p.execution), p.isActive]
      );
      console.log('  ✅ Created profile:', p.name, '(' + p.environment + ')');
    }
    
    // Verify
    const count = await pool.query('SELECT COUNT(*) FROM user_chessboard_profiles');
    console.log('\n📊 Total profiles:', count.rows[0].count);
    
    const instCount = await pool.query('SELECT COUNT(*) FROM strategy_instances');
    console.log('📊 Total strategy instances:', instCount.rows[0].count);
    
    console.log('\n✅ Seeding complete!');
  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

seed();


