/**
 * Seed all strategies from the Python registry into the database
 * These are the canonical trading strategies available for use in profiles
 */

import pool from '../config/database.js';

const STRATEGIES = [
  {
    template_id: 'amt_value_area_rejection_scalp',
    name: 'AMT Value Area Rejection Scalp',
    description: 'Trade rejections from value area boundaries with AMT confirmation. Best for mean-reversion in ranging markets.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      rotation_threshold: 3.0,
      risk_per_trade_pct: 0.5,
      rejection_distance_pct: 0.05,
      stop_loss_pct: 0.3,
      take_profit_pct: 0.5,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'poc_magnet_scalp',
    name: 'POC Magnet Scalp',
    description: 'Trade price attraction to Point of Control. Price tends to revert to POC in balanced markets.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      poc_distance_threshold_pct: 0.3,
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.4,
      take_profit_pct: 0.6,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'breakout_scalp',
    name: 'Breakout Scalp',
    description: 'Capture momentum when price breaks value area boundaries with strong confirmation. Best in high volatility.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      rotation_threshold: 7.0,
      risk_per_trade_pct: 1.0,
      breakout_confirmation_pct: 0.15,
      stop_loss_pct: 1.0,
      take_profit_pct: 0.7,
      max_spread: 0.003,
      min_atr_ratio: 1.0,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'mean_reversion_fade',
    name: 'Mean Reversion Fade',
    description: 'Fade extended moves back to the mean. Works in range-bound markets with clear support/resistance.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      extension_threshold: 2.0,
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.5,
      take_profit_pct: 0.8,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'trend_pullback',
    name: 'Trend Pullback',
    description: 'Enter trend continuation after a pullback to support/resistance. Best in strong trending markets.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      trend_strength_threshold: 0.6,
      pullback_depth_pct: 0.5,
      risk_per_trade_pct: 0.75,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.2,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'chop_zone_avoid',
    name: 'Chop Zone Avoid',
    description: 'Risk management strategy to avoid trading during choppy/indecisive market conditions.',
    params: {
      chop_threshold: 0.5,
      range_threshold_pct: 0.3,
      min_directional_move: 0.2,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'opening_range_breakout',
    name: 'Opening Range Breakout',
    description: 'Trade breakouts from the opening range established in the first 30 minutes of the session.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      opening_range_minutes: 30,
      breakout_confirmation_pct: 0.1,
      risk_per_trade_pct: 0.75,
      stop_loss_pct: 0.5,
      take_profit_pct: 1.0,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'asia_range_scalp',
    name: 'Asia Range Scalp',
    description: 'Scalp within the Asia session range. Best during lower volatility Asian trading hours.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      range_boundary_buffer_pct: 0.1,
      risk_per_trade_pct: 0.4,
      stop_loss_pct: 0.3,
      take_profit_pct: 0.4,
      max_spread: 0.0015,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'europe_open_vol',
    name: 'Europe Open Volatility',
    description: 'Capitalize on the volatility spike during European market open (8-10 AM London).',
    params: {
      allow_longs: true,
      allow_shorts: true,
      vol_spike_threshold: 1.5,
      risk_per_trade_pct: 0.6,
      stop_loss_pct: 0.5,
      take_profit_pct: 0.8,
      max_spread: 0.003,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'us_open_momentum',
    name: 'US Open Momentum',
    description: 'Ride the momentum during US market open. Highest liquidity and volatility period.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      momentum_threshold: 0.7,
      risk_per_trade_pct: 0.8,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.0,
      max_spread: 0.003,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'overnight_thin',
    name: 'Overnight Thin Liquidity',
    description: 'Trade during low-liquidity overnight hours with tight stops and small positions.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      liquidity_threshold: 0.3,
      risk_per_trade_pct: 0.3,
      stop_loss_pct: 0.25,
      take_profit_pct: 0.35,
      max_spread: 0.001,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'high_vol_breakout',
    name: 'High Volatility Breakout',
    description: 'Aggressive breakout strategy for high volatility regimes. Wider stops, larger targets.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      vol_percentile_threshold: 80,
      risk_per_trade_pct: 1.0,
      stop_loss_pct: 1.2,
      take_profit_pct: 1.5,
      max_spread: 0.004,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'low_vol_grind',
    name: 'Low Volatility Grind',
    description: 'Patient accumulation strategy for low volatility regimes. Tight stops, frequent small wins.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      vol_percentile_threshold: 30,
      risk_per_trade_pct: 0.3,
      stop_loss_pct: 0.2,
      take_profit_pct: 0.25,
      max_spread: 0.001,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'vol_expansion',
    name: 'Volatility Expansion',
    description: 'Trade the transition from low to high volatility. Catch the early momentum of regime changes.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      expansion_ratio_threshold: 1.8,
      risk_per_trade_pct: 0.7,
      stop_loss_pct: 0.6,
      take_profit_pct: 1.0,
      max_spread: 0.003,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'liquidity_hunt',
    name: 'Liquidity Hunt',
    description: 'Identify and trade around liquidity pools (stop clusters). Advanced order flow strategy.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      liquidity_cluster_threshold: 0.5,
      risk_per_trade_pct: 0.6,
      stop_loss_pct: 0.4,
      take_profit_pct: 0.8,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'order_flow_imbalance',
    name: 'Order Flow Imbalance',
    description: 'Trade based on buy/sell order flow imbalance. Requires order book data analysis.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      imbalance_threshold: 0.6,
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.35,
      take_profit_pct: 0.6,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'spread_compression',
    name: 'Spread Compression',
    description: 'Trade when spreads compress indicating increased liquidity and directional conviction.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      compression_threshold: 0.5,
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.3,
      take_profit_pct: 0.5,
      max_spread: 0.001,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'vwap_reversion',
    name: 'VWAP Reversion',
    description: 'Trade reversions to VWAP (Volume Weighted Average Price). Institutional trading benchmark.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      vwap_deviation_threshold: 0.3,
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.4,
      take_profit_pct: 0.6,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'volume_profile_cluster',
    name: 'Volume Profile Cluster',
    description: 'Trade at high volume nodes identified by volume profile analysis. Key support/resistance.',
    params: {
      allow_longs: true,
      allow_shorts: true,
      cluster_threshold: 0.7,
      risk_per_trade_pct: 0.5,
      stop_loss_pct: 0.4,
      take_profit_pct: 0.7,
      max_spread: 0.002,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'drawdown_recovery',
    name: 'Drawdown Recovery',
    description: 'Risk management strategy to reduce size and become conservative during drawdown periods.',
    params: {
      drawdown_threshold_pct: 5.0,
      recovery_threshold_pct: 2.0,
      size_reduction_factor: 0.5,
      min_win_rate_for_recovery: 0.55,
    },
    status: 'active',
    is_system_template: true,
  },
  {
    template_id: 'max_profit_protection',
    name: 'Max Profit Protection',
    description: 'Lock in profits when the session is significantly profitable. Tighten stops to protect gains.',
    params: {
      profit_threshold_pct: 2.0,
      trailing_stop_activation_pct: 1.5,
      trailing_stop_distance_pct: 0.5,
    },
    status: 'active',
    is_system_template: true,
  },
];

async function seedStrategies() {
  console.log('🌱 Seeding 21 canonical strategies from Python registry...\n');
  
  let created = 0;
  let skipped = 0;
  
  for (const strategy of STRATEGIES) {
    // Check if already exists
    const existing = await pool.query(
      'SELECT id FROM strategy_instances WHERE template_id = $1 AND is_system_template = true',
      [strategy.template_id]
    );
    
    if (existing.rows.length > 0) {
      console.log(`  ⏭️  ${strategy.name} (already exists)`);
      skipped++;
      continue;
    }
    
    // Insert strategy
    await pool.query(
      `INSERT INTO strategy_instances 
       (template_id, name, description, params, status, is_system_template, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())`,
      [
        strategy.template_id,
        strategy.name,
        strategy.description,
        JSON.stringify(strategy.params),
        strategy.status,
        strategy.is_system_template,
      ]
    );
    
    console.log(`  ✅ ${strategy.name}`);
    created++;
  }
  
  console.log(`\n📊 Summary: ${created} created, ${skipped} skipped (already exist)`);
  
  // Show final count
  const result = await pool.query('SELECT COUNT(*) as count FROM strategy_instances WHERE is_system_template = true');
  console.log(`📈 Total system template strategies: ${result.rows[0].count}`);
  
  await pool.end();
}

seedStrategies().catch(console.error);

