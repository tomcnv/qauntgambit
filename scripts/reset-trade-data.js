#!/usr/bin/env node
/**
 * Reset Trade Data Script
 * 
 * Clears all trade data from the system:
 * - Backend PostgreSQL (orders, trades, positions, trading_decisions, etc.)
 * - Python Bot TimescaleDB (telemetry, order events, position events, etc.)
 * - Redis (position snapshots, order history, execution state)
 * 
 * Usage: node scripts/reset-trade-data.js
 * 
 * IMPORTANT: This is a destructive operation. Make sure you want to do this!
 */

import pkg from 'pg';
const { Pool } = pkg;
import { createClient } from 'redis';
import dotenv from 'dotenv';
import readline from 'readline';

dotenv.config();

// ============ Configuration ============
const BACKEND_DB_CONFIG = {
  host: process.env.DB_HOST || 'localhost',
  port: process.env.DB_PORT || 5432,
  database: process.env.DB_NAME || 'deeptrader',
  user: process.env.DB_USER || 'deeptrader_user',
  password: process.env.DB_PASSWORD || 'deeptrader_pass',
};

const TIMESCALE_DB_CONFIG = {
  host: process.env.TIMESCALE_HOST || process.env.DB_HOST || 'localhost',
  port: process.env.TIMESCALE_PORT || 5432,
  database: process.env.TIMESCALE_DB || 'quantgambit',
  user: process.env.TIMESCALE_USER || process.env.DB_USER || 'deeptrader_user',
  password: process.env.TIMESCALE_PASSWORD || process.env.DB_PASSWORD || 'deeptrader_pass',
};

const REDIS_URL = process.env.REDIS_URL || process.env.BOT_REDIS_URL || 'redis://localhost:6379';

// ============ Tables to clear ============

// Backend database tables (deeptrader)
const BACKEND_TABLES = [
  // Core trading tables
  'orders',
  'trades',
  'positions',
  'position_updates',
  'trading_decisions',
  'trading_activity',
  
  // Paper trading
  'paper_orders',
  'paper_positions', 
  'paper_trades',
  'paper_position_history',
  'paper_position_alerts',
  'paper_position_tags',
  
  // TCA & Analytics
  'trade_costs',
  'position_impacts',
  
  // Backtesting (optional - comment out if you want to keep)
  'backtest_trades',
  'backtest_metrics',
  'backtest_runs',
  
  // Bot logs (optional - comment out if you want to keep)
  'bot_logs',
];

// Timescale/Python bot tables
const TIMESCALE_TABLES = [
  // Telemetry events
  'decision_events',
  'order_events',
  'prediction_events',
  'latency_events',
  'fee_events',
  'risk_events',
  'position_events',
  'orderbook_events',
  'guardrail_events',
  'order_update_events',
  'market_data_provider_events',
  
  // Order lifecycle
  'order_states',
  'order_lifecycle_events',
  'order_intents',
  'order_errors',
  
  // Analytics & signals
  'signals',
  'risk_incidents',
  'sltp_events',
  'market_context',
  'timeline_events',
  
  // Backtest data (optional - comment out if you want to keep)
  'backtest_trades',
  'backtest_metrics', 
  'backtest_runs',
  'backtest_equity_curve',
  'backtest_symbol_equity_curve',
  'backtest_symbol_metrics',
  'backtest_decision_snapshots',
  'backtest_position_snapshots',
];

// Redis patterns to clear
const REDIS_PATTERNS = [
  'quantgambit:*:positions:*',
  'quantgambit:*:orders:*',
  'quantgambit:*:execution:*',
  'quantgambit:*:order:*',
  'quantgambit:*:kill_switch:*',
  'quantgambit:*:equity:*',
  'quantgambit:*:pnl:*',
  'quantgambit:*:signals:*',
];

// ============ Helper Functions ============

async function prompt(question) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });
  
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.toLowerCase());
    });
  });
}

async function clearPostgresTables(pool, tables, dbName) {
  console.log(`\n📊 Clearing tables in ${dbName}...`);
  let totalDeleted = 0;
  
  for (const table of tables) {
    try {
      // Check if table exists
      const checkResult = await pool.query(`
        SELECT EXISTS (
          SELECT FROM information_schema.tables 
          WHERE table_schema = 'public' 
          AND table_name = $1
        )
      `, [table]);
      
      if (!checkResult.rows[0].exists) {
        console.log(`  ⏭️  ${table}: table doesn't exist, skipping`);
        continue;
      }
      
      // Get row count before
      const countResult = await pool.query(`SELECT COUNT(*) as count FROM ${table}`);
      const rowCount = parseInt(countResult.rows[0].count);
      
      if (rowCount === 0) {
        console.log(`  ⏭️  ${table}: already empty`);
        continue;
      }
      
      // TRUNCATE is faster than DELETE for full table clear
      await pool.query(`TRUNCATE TABLE ${table} CASCADE`);
      console.log(`  ✅ ${table}: deleted ${rowCount} rows`);
      totalDeleted += rowCount;
      
    } catch (err) {
      if (err.message.includes('does not exist')) {
        console.log(`  ⏭️  ${table}: table doesn't exist, skipping`);
      } else {
        console.log(`  ⚠️  ${table}: ${err.message}`);
      }
    }
  }
  
  return totalDeleted;
}

async function clearRedis(redisUrl) {
  console.log('\n🔴 Clearing Redis keys...');
  
  let client;
  try {
    client = createClient({ url: redisUrl });
    client.on('error', (err) => console.log('Redis error:', err.message));
    await client.connect();
    
    let totalDeleted = 0;
    
    for (const pattern of REDIS_PATTERNS) {
      const keys = await client.keys(pattern);
      if (keys.length > 0) {
        await client.del(keys);
        console.log(`  ✅ ${pattern}: deleted ${keys.length} keys`);
        totalDeleted += keys.length;
      } else {
        console.log(`  ⏭️  ${pattern}: no matching keys`);
      }
    }
    
    return totalDeleted;
  } catch (err) {
    console.log(`  ⚠️  Redis error: ${err.message}`);
    return 0;
  } finally {
    if (client) {
      await client.quit();
    }
  }
}

// ============ Main ============

async function main() {
  console.log('═══════════════════════════════════════════════════════════════');
  console.log('              🗑️  TRADE DATA RESET SCRIPT');
  console.log('═══════════════════════════════════════════════════════════════');
  console.log('\nThis will DELETE all trade data from:');
  console.log('  • Backend PostgreSQL (orders, trades, positions, etc.)');
  console.log('  • TimescaleDB (telemetry, order events, etc.)');
  console.log('  • Redis (position snapshots, order history, etc.)');
  console.log('\n⚠️  WARNING: This operation cannot be undone!\n');
  
  const answer = await prompt('Are you sure you want to proceed? (yes/no): ');
  
  if (answer !== 'yes') {
    console.log('\n❌ Operation cancelled.');
    process.exit(0);
  }
  
  console.log('\n🚀 Starting reset...');
  
  let backendPool = null;
  let timescalePool = null;
  let stats = { backend: 0, timescale: 0, redis: 0 };
  
  try {
    // Clear Backend PostgreSQL
    console.log(`\n📡 Connecting to backend database (${BACKEND_DB_CONFIG.database})...`);
    backendPool = new Pool(BACKEND_DB_CONFIG);
    await backendPool.query('SELECT 1');
    console.log('✅ Connected to backend database');
    stats.backend = await clearPostgresTables(backendPool, BACKEND_TABLES, BACKEND_DB_CONFIG.database);
    
  } catch (err) {
    console.log(`⚠️  Backend database error: ${err.message}`);
  }
  
  try {
    // Clear TimescaleDB (only if different from backend)
    if (TIMESCALE_DB_CONFIG.database !== BACKEND_DB_CONFIG.database || 
        TIMESCALE_DB_CONFIG.host !== BACKEND_DB_CONFIG.host) {
      console.log(`\n📡 Connecting to TimescaleDB (${TIMESCALE_DB_CONFIG.database})...`);
      timescalePool = new Pool(TIMESCALE_DB_CONFIG);
      await timescalePool.query('SELECT 1');
      console.log('✅ Connected to TimescaleDB');
      stats.timescale = await clearPostgresTables(timescalePool, TIMESCALE_TABLES, TIMESCALE_DB_CONFIG.database);
    } else {
      // Same database - check for timescale tables
      console.log(`\n📊 Checking for TimescaleDB tables in ${BACKEND_DB_CONFIG.database}...`);
      stats.timescale = await clearPostgresTables(backendPool, TIMESCALE_TABLES, BACKEND_DB_CONFIG.database);
    }
    
  } catch (err) {
    console.log(`⚠️  TimescaleDB error: ${err.message}`);
  }
  
  // Clear Redis
  stats.redis = await clearRedis(REDIS_URL);
  
  // Close connections
  if (backendPool) await backendPool.end();
  if (timescalePool) await timescalePool.end();
  
  // Summary
  console.log('\n═══════════════════════════════════════════════════════════════');
  console.log('                      📊 SUMMARY');
  console.log('═══════════════════════════════════════════════════════════════');
  console.log(`  Backend DB rows deleted:   ${stats.backend.toLocaleString()}`);
  console.log(`  TimescaleDB rows deleted:  ${stats.timescale.toLocaleString()}`);
  console.log(`  Redis keys deleted:        ${stats.redis.toLocaleString()}`);
  console.log('═══════════════════════════════════════════════════════════════');
  console.log('\n✅ Trade data reset complete! You can now start trading fresh.');
  console.log('\n💡 Next steps:');
  console.log('   1. Restart your bot instances');
  console.log('   2. Verify your exchange connections');
  console.log('   3. Start monitoring your new trades');
}

main().catch((err) => {
  console.error('\n❌ Fatal error:', err);
  process.exit(1);
});
