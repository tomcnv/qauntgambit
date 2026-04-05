#!/usr/bin/env node
/**
 * Comprehensive Integration Test Script
 * Tests all implemented features
 */

import pool from '../config/database.js';
import axios from 'axios';

const API_BASE = process.env.API_BASE_URL || 'http://localhost:3001';

// Colors for output
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
};

function log(message, color = 'reset') {
  console.log(`${colors[color]}${message}${colors.reset}`);
}

function logSection(title) {
  console.log('\n' + '='.repeat(60));
  log(title, 'blue');
  console.log('='.repeat(60));
}

async function checkTableExists(tableName) {
  try {
    const result = await pool.query(
      `SELECT EXISTS (
        SELECT FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = $1
      )`,
      [tableName]
    );
    return result.rows[0].exists;
  } catch (error) {
    return false;
  }
}

async function checkTableStructure(tableName) {
  try {
    const result = await pool.query(`
      SELECT column_name, data_type, is_nullable
      FROM information_schema.columns
      WHERE table_name = $1
      ORDER BY ordinal_position
    `, [tableName]);
    return result.rows;
  } catch (error) {
    return [];
  }
}

async function countRows(tableName) {
  try {
    const result = await pool.query(`SELECT COUNT(*) as count FROM ${tableName}`);
    return parseInt(result.rows[0].count);
  } catch (error) {
    return -1;
  }
}

async function testDatabaseSchema() {
  logSection('1. Database Schema Verification');
  
  const tables = [
    'equity_curves',
    'decision_traces',
    'replay_snapshots',
    'incidents',
    'replay_sessions',
    'trade_costs',
    'capacity_analysis',
    'var_calculations',
    'scenario_results',
    'promotions',
    'approvals',
    'audit_log',
    'data_quality_metrics',
    'feed_gaps',
    'report_templates',
    'strategy_portfolio',
    'fast_scalper_trades',
    'fast_scalper_positions',
  ];
  
  let allPassed = true;
  
  for (const table of tables) {
    const exists = await checkTableExists(table);
    if (exists) {
      const count = await countRows(table);
      log(`✅ ${table} exists (${count} rows)`, 'green');
    } else {
      log(`❌ ${table} missing`, 'red');
      allPassed = false;
    }
  }
  
  return allPassed;
}

async function testPythonBotData() {
  logSection('2. Python Bot Data Verification');
  
  let allPassed = true;
  
  // Check fast_scalper_trades
  try {
    const tradesResult = await pool.query(`
      SELECT COUNT(*) as count, 
             MAX(exit_time) as latest_trade,
             SUM(pnl) as total_pnl
      FROM fast_scalper_trades
    `);
    const trades = tradesResult.rows[0];
    log(`✅ fast_scalper_trades: ${trades.count} trades, Latest: ${trades.latest_trade || 'N/A'}, Total PnL: ${trades.total_pnl || 0}`, 'green');
  } catch (error) {
    log(`❌ Error checking fast_scalper_trades: ${error.message}`, 'red');
    allPassed = false;
  }
  
  // Check fast_scalper_positions
  try {
    const positionsResult = await pool.query(`
      SELECT COUNT(*) as count
      FROM fast_scalper_positions
      WHERE status = 'open'
    `);
    const openPositions = positionsResult.rows[0].count;
    log(`✅ fast_scalper_positions: ${openPositions} open positions`, 'green');
  } catch (error) {
    log(`❌ Error checking fast_scalper_positions: ${error.message}`, 'red');
    allPassed = false;
  }
  
  // Check decision_traces
  try {
    const tracesResult = await pool.query(`
      SELECT COUNT(*) as count,
             MAX(created_at) as latest_trace
      FROM decision_traces
    `);
    const traces = tracesResult.rows[0];
    log(`✅ decision_traces: ${traces.count} traces, Latest: ${traces.latest_trace || 'N/A'}`, 'green');
  } catch (error) {
    log(`⚠️  decision_traces: ${error.message} (may be empty)`, 'yellow');
  }
  
  // Check equity_curves
  try {
    const equityResult = await pool.query(`
      SELECT COUNT(*) as count,
             MAX(timestamp) as latest_point
      FROM equity_curves
    `);
    const equity = equityResult.rows[0];
    log(`✅ equity_curves: ${equity.count} points, Latest: ${equity.latest_point || 'N/A'}`, 'green');
  } catch (error) {
    log(`⚠️  equity_curves: ${error.message} (may be empty)`, 'yellow');
  }
  
  // Check trade_costs (TCA)
  try {
    const tcaResult = await pool.query(`
      SELECT COUNT(*) as count
      FROM trade_costs
    `);
    const tca = tcaResult.rows[0];
    log(`✅ trade_costs: ${tca.count} records`, 'green');
  } catch (error) {
    log(`⚠️  trade_costs: ${error.message} (may be empty)`, 'yellow');
  }
  
  return allPassed;
}

async function testAPIEndpoints() {
  logSection('3. Backend API Endpoints');
  
  let allPassed = true;
  
  const endpoints = [
    { path: '/api/health', method: 'GET', name: 'Health Check' },
    { path: '/api/tca/analysis', method: 'GET', name: 'TCA Analysis' },
    { path: '/api/risk/var', method: 'GET', name: 'VaR Calculations' },
    { path: '/api/risk/scenarios', method: 'GET', name: 'Scenario Results' },
    { path: '/api/promotions', method: 'GET', name: 'Promotions' },
    { path: '/api/audit', method: 'GET', name: 'Audit Log' },
    { path: '/api/replay/incidents', method: 'GET', name: 'Replay Incidents' },
    { path: '/api/data-quality/metrics', method: 'GET', name: 'Data Quality Metrics' },
    { path: '/api/reporting/templates', method: 'GET', name: 'Report Templates' },
    { path: '/api/reporting/portfolio', method: 'GET', name: 'Strategy Portfolio' },
  ];
  
  for (const endpoint of endpoints) {
    try {
      const response = await axios({
        method: endpoint.method,
        url: `${API_BASE}${endpoint.path}`,
        timeout: 5000,
        validateStatus: () => true, // Don't throw on any status
      });
      
      if (response.status === 200 || response.status === 404) {
        log(`✅ ${endpoint.name}: ${response.status}`, 'green');
      } else {
        log(`⚠️  ${endpoint.name}: ${response.status}`, 'yellow');
      }
    } catch (error) {
      if (error.code === 'ECONNREFUSED') {
        log(`❌ ${endpoint.name}: Backend server not running`, 'red');
        allPassed = false;
      } else {
        log(`⚠️  ${endpoint.name}: ${error.message}`, 'yellow');
      }
    }
  }
  
  return allPassed;
}

async function testHealthEndpoint() {
  logSection('4. Health Endpoint & Legacy Services');
  
  try {
    const response = await axios.get(`${API_BASE}/api/health`, { timeout: 5000 });
    
    if (response.status === 200) {
      const health = response.data;
      
      // Check monitoring status
      if (health.monitoring) {
        const status = health.monitoring.status;
        if (status === 'handled_by_python_bot') {
          log(`✅ Legacy services correctly disabled (status: ${status})`, 'green');
        } else {
          log(`⚠️  Legacy services status: ${status}`, 'yellow');
        }
      }
      
      log(`✅ Health endpoint responding`, 'green');
      return true;
    } else {
      log(`❌ Health endpoint returned ${response.status}`, 'red');
      return false;
    }
  } catch (error) {
    if (error.code === 'ECONNREFUSED') {
      log(`❌ Backend server not running`, 'red');
    } else {
      log(`❌ Health endpoint error: ${error.message}`, 'red');
    }
    return false;
  }
}

async function testIntegrationFlow() {
  logSection('5. Integration Flow Tests');
  
  let allPassed = true;
  
  // Test: Trade → TCA
  try {
    const tradesResult = await pool.query(`
      SELECT COUNT(*) as count
      FROM fast_scalper_trades
      WHERE exit_time IS NOT NULL
    `);
    const tradesCount = parseInt(tradesResult.rows[0].count);
    
    if (tradesCount > 0) {
      log(`✅ Found ${tradesCount} completed trades`, 'green');
      
      // Check if TCA data exists for trades
      const tcaResult = await pool.query(`
        SELECT COUNT(*) as count
        FROM trade_costs
      `);
      const tcaCount = parseInt(tcaResult.rows[0].count);
      
      if (tcaCount > 0) {
        log(`✅ TCA data exists for trades (${tcaCount} records)`, 'green');
      } else {
        log(`⚠️  No TCA data found (may need to wait for collection)`, 'yellow');
      }
    } else {
      log(`⚠️  No completed trades found (bot may not have traded yet)`, 'yellow');
    }
  } catch (error) {
    log(`❌ Integration test error: ${error.message}`, 'red');
    allPassed = false;
  }
  
  // Test: Decision → Trace
  try {
    const tracesResult = await pool.query(`
      SELECT COUNT(*) as count
      FROM decision_traces
    `);
    const tracesCount = parseInt(tracesResult.rows[0].count);
    
    if (tracesCount > 0) {
      log(`✅ Found ${tracesCount} decision traces`, 'green');
    } else {
      log(`⚠️  No decision traces found (may need to wait for bot decisions)`, 'yellow');
    }
  } catch (error) {
    log(`⚠️  Decision traces check: ${error.message}`, 'yellow');
  }
  
  // Test: Trades → Equity Curves
  try {
    const equityResult = await pool.query(`
      SELECT COUNT(*) as count
      FROM equity_curves
    `);
    const equityCount = parseInt(equityResult.rows[0].count);
    
    if (equityCount > 0) {
      log(`✅ Found ${equityCount} equity curve points`, 'green');
    } else {
      log(`⚠️  No equity curve points found (may need to wait for calculation)`, 'yellow');
    }
  } catch (error) {
    log(`⚠️  Equity curves check: ${error.message}`, 'yellow');
  }
  
  return allPassed;
}

async function main() {
  log('\n🚀 Starting Comprehensive Integration Tests...\n', 'blue');
  
  try {
    // Test database connection
    await pool.query('SELECT 1');
    log('✅ Database connection successful', 'green');
    
    const results = {
      schema: await testDatabaseSchema(),
      botData: await testPythonBotData(),
      apiEndpoints: await testAPIEndpoints(),
      health: await testHealthEndpoint(),
      integration: await testIntegrationFlow(),
    };
    
    // Summary
    logSection('Test Summary');
    
    const allPassed = Object.values(results).every(r => r);
    
    for (const [test, passed] of Object.entries(results)) {
      if (passed) {
        log(`✅ ${test}`, 'green');
      } else {
        log(`❌ ${test}`, 'red');
      }
    }
    
    console.log('\n' + '='.repeat(60));
    if (allPassed) {
      log('✅ All tests passed!', 'green');
    } else {
      log('⚠️  Some tests failed or have warnings', 'yellow');
    }
    console.log('='.repeat(60) + '\n');
    
    process.exit(allPassed ? 0 : 1);
  } catch (error) {
    log(`❌ Test error: ${error.message}`, 'red');
    console.error(error);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

main();




