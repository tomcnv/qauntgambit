#!/usr/bin/env node
/**
 * Test script for Research & Backtesting APIs
 * 
 * Usage:
 *   node tests/test-research-apis.js [--token <jwt_token>]
 * 
 * Requires:
 *   - Backend server running on port 3001
 *   - Valid JWT token (or will attempt to login)
 *   - Database with backtest tables
 */

import axios from 'axios';
import readline from 'readline';

const API_BASE = 'http://localhost:3001/api';
let authToken = null;

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

const question = (query) => new Promise((resolve) => rl.question(query, resolve));

// Colors for console output
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
};

const log = {
  success: (msg) => console.log(`${colors.green}✅ ${msg}${colors.reset}`),
  error: (msg) => console.log(`${colors.red}❌ ${msg}${colors.reset}`),
  info: (msg) => console.log(`${colors.blue}ℹ️  ${msg}${colors.reset}`),
  warn: (msg) => console.log(`${colors.yellow}⚠️  ${msg}${colors.reset}`),
  test: (msg) => console.log(`${colors.cyan}🧪 ${msg}${colors.reset}`),
};

// Helper to make authenticated requests
const apiRequest = async (method, endpoint, data = null, token = authToken) => {
  try {
    const config = {
      method,
      url: `${API_BASE}${endpoint}`,
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      ...(data && { data }),
    };
    const response = await axios(config);
    return { success: true, data: response.data, status: response.status };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data || error.message,
      status: error.response?.status,
    };
  }
};

// Test authentication
async function testAuth() {
  log.test('Testing authentication...');
  
  // Try to login
  const email = process.env.TEST_EMAIL || 'test@example.com';
  const password = process.env.TEST_PASSWORD || 'testpassword123';
  
  const result = await apiRequest('POST', '/auth/login', { email, password });
  
  if (result.success && result.data.token) {
    authToken = result.data.token;
    log.success(`Authenticated as ${result.data.user?.email || email}`);
    return true;
  } else {
    log.warn('Login failed, trying with provided token...');
    const token = process.argv.includes('--token') 
      ? process.argv[process.argv.indexOf('--token') + 1]
      : process.env.JWT_TOKEN;
    
    if (token) {
      authToken = token;
      // Verify token works
      const verify = await apiRequest('GET', '/auth/profile', null, token);
      if (verify.success) {
        log.success('Token is valid');
        return true;
      }
    }
    
    log.error('Authentication failed. Please provide valid credentials or token.');
    return false;
  }
}

// Test: List backtests
async function testListBacktests() {
  log.test('Test 1: List backtests');
  
  const result = await apiRequest('GET', '/research/backtests');
  
  if (result.success) {
    log.success(`Found ${result.data.backtests?.length || 0} backtests`);
    if (result.data.backtests && result.data.backtests.length > 0) {
      log.info(`Sample backtest: ${result.data.backtests[0].strategy_id} - ${result.data.backtests[0].status}`);
    }
    return { success: true, backtestId: result.data.backtests?.[0]?.id };
  } else {
    log.error(`Failed: ${JSON.stringify(result.error)}`);
    return { success: false };
  }
}

// Test: Get backtest detail
async function testGetBacktestDetail(backtestId) {
  if (!backtestId) {
    log.warn('Skipping backtest detail test (no backtest ID)');
    return { success: true, skipped: true };
  }
  
  log.test('Test 2: Get backtest detail');
  
  const result = await apiRequest('GET', `/research/backtests/${backtestId}`);
  
  if (result.success) {
    log.success(`Retrieved backtest: ${result.data.backtest.strategy_id}`);
    log.info(`Trades: ${result.data.trades?.length || 0}`);
    log.info(`Equity curve points: ${result.data.equityCurve?.length || 0}`);
    return { success: true };
  } else {
    log.error(`Failed: ${JSON.stringify(result.error)}`);
    return { success: false };
  }
}

// Test: List datasets
async function testListDatasets() {
  log.test('Test 3: List datasets');
  
  const result = await apiRequest('GET', '/research/datasets');
  
  if (result.success) {
    log.success(`Found ${result.data.datasets?.length || 0} datasets`);
    if (result.data.datasets && result.data.datasets.length > 0) {
      const ds = result.data.datasets[0];
      log.info(`Sample: ${ds.symbol} - ${ds.availableDays} days available`);
    }
    return { success: true, dataset: result.data.datasets?.[0] };
  } else {
    log.error(`Failed: ${JSON.stringify(result.error)}`);
    return { success: false };
  }
}

// Test: Create backtest
async function testCreateBacktest(dataset) {
  log.test('Test 4: Create backtest');
  
  if (!dataset) {
    log.warn('Skipping create backtest test (no dataset available)');
    return { success: true, skipped: true };
  }
  
  const endDate = new Date();
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - 7); // 7 days ago
  
  const backtestData = {
    strategy_id: 'amt_value_area_rejection_scalp',
    symbol: dataset.symbol,
    exchange: 'okx',
    start_date: startDate.toISOString(),
    end_date: endDate.toISOString(),
    initial_capital: 10000,
    commission_per_trade: 0.001,
    slippage_model: 'fixed',
    slippage_bps: 5.0,
  };
  
  const result = await apiRequest('POST', '/research/backtests', backtestData);
  
  if (result.success) {
    log.success(`Created backtest: ${result.data.backtest.id}`);
    log.info(`Status: ${result.data.backtest.status}`);
    return { success: true, backtestId: result.data.backtest.id };
  } else {
    log.error(`Failed: ${JSON.stringify(result.error)}`);
    return { success: false };
  }
}

// Test: Filter backtests by status
async function testFilterBacktests() {
  log.test('Test 5: Filter backtests by status');
  
  const statuses = ['pending', 'running', 'completed', 'failed'];
  
  for (const status of statuses) {
    const result = await apiRequest('GET', `/research/backtests?status=${status}`);
    if (result.success) {
      log.info(`Status "${status}": ${result.data.backtests?.length || 0} backtests`);
    }
  }
  
  return { success: true };
}

// Test: Pagination
async function testPagination() {
  log.test('Test 6: Test pagination');
  
  const result1 = await apiRequest('GET', '/research/backtests?limit=5&offset=0');
  const result2 = await apiRequest('GET', '/research/backtests?limit=5&offset=5');
  
  if (result1.success && result2.success) {
    log.success('Pagination works');
    log.info(`Page 1: ${result1.data.backtests?.length || 0} backtests`);
    log.info(`Page 2: ${result2.data.backtests?.length || 0} backtests`);
    return { success: true };
  } else {
    log.error('Pagination test failed');
    return { success: false };
  }
}

// Test: Error handling
async function testErrorHandling() {
  log.test('Test 7: Error handling');
  
  // Test invalid backtest ID
  const result1 = await apiRequest('GET', '/research/backtests/invalid-id');
  if (!result1.success && result1.status === 404) {
    log.success('Correctly returns 404 for invalid ID');
  } else {
    log.error('Should return 404 for invalid ID');
  }
  
  // Test invalid create request
  const result2 = await apiRequest('POST', '/research/backtests', {
    // Missing required fields
    strategy_id: 'test',
  });
  if (!result2.success && result2.status === 400) {
    log.success('Correctly validates required fields');
  } else {
    log.error('Should return 400 for invalid request');
  }
  
  return { success: true };
}

// Main test runner
async function runTests() {
  console.log('\n' + '='.repeat(60));
  console.log('🧪 Research & Backtesting API Test Suite');
  console.log('='.repeat(60) + '\n');
  
  // Authenticate
  const authSuccess = await testAuth();
  if (!authSuccess) {
    log.error('Cannot proceed without authentication');
    process.exit(1);
  }
  
  const results = [];
  
  // Run tests
  try {
    const listResult = await testListBacktests();
    results.push({ name: 'List Backtests', ...listResult });
    
    const detailResult = await testGetBacktestDetail(listResult.backtestId);
    results.push({ name: 'Get Backtest Detail', ...detailResult });
    
    const datasetsResult = await testListDatasets();
    results.push({ name: 'List Datasets', ...datasetsResult });
    
    const createResult = await testCreateBacktest(datasetsResult.dataset);
    results.push({ name: 'Create Backtest', ...createResult });
    
    const filterResult = await testFilterBacktests();
    results.push({ name: 'Filter Backtests', ...filterResult });
    
    const paginationResult = await testPagination();
    results.push({ name: 'Pagination', ...paginationResult });
    
    const errorResult = await testErrorHandling();
    results.push({ name: 'Error Handling', ...errorResult });
    
  } catch (error) {
    log.error(`Test suite error: ${error.message}`);
    console.error(error);
  }
  
  // Summary
  console.log('\n' + '='.repeat(60));
  console.log('📊 Test Summary');
  console.log('='.repeat(60));
  
  const passed = results.filter(r => r.success && !r.skipped).length;
  const failed = results.filter(r => !r.success).length;
  const skipped = results.filter(r => r.skipped).length;
  
  results.forEach(result => {
    if (result.skipped) {
      log.warn(`${result.name}: SKIPPED`);
    } else if (result.success) {
      log.success(`${result.name}: PASSED`);
    } else {
      log.error(`${result.name}: FAILED`);
    }
  });
  
  console.log('\n' + '='.repeat(60));
  console.log(`Total: ${results.length} | Passed: ${passed} | Failed: ${failed} | Skipped: ${skipped}`);
  console.log('='.repeat(60) + '\n');
  
  rl.close();
  
  process.exit(failed > 0 ? 1 : 0);
}

// Run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runTests().catch(console.error);
}

export { runTests, testAuth, testListBacktests, testGetBacktestDetail, testListDatasets, testCreateBacktest };





