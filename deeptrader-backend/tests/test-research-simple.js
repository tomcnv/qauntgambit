#!/usr/bin/env node
/**
 * Simple test script for Research APIs
 * Uses fetch instead of axios for better compatibility
 */

const API_BASE = 'http://localhost:3001/api';

// Colors
const green = '\x1b[32m';
const red = '\x1b[31m';
const yellow = '\x1b[33m';
const blue = '\x1b[34m';
const reset = '\x1b[0m';

const log = {
  success: (msg) => console.log(`${green}✅ ${msg}${reset}`),
  error: (msg) => console.log(`${red}❌ ${msg}${reset}`),
  info: (msg) => console.log(`${blue}ℹ️  ${msg}${reset}`),
  test: (msg) => console.log(`${blue}🧪 ${msg}${reset}`),
};

let authToken = null;

async function login() {
  log.test('Logging in...');
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: process.env.TEST_EMAIL || 'test@example.com',
        password: process.env.TEST_PASSWORD || 'testpassword123',
      }),
    });
    
    if (response.ok) {
      const data = await response.json();
      authToken = data.token;
      log.success('Authenticated');
      return true;
    } else {
      log.error(`Login failed: ${response.status}`);
      return false;
    }
  } catch (error) {
    log.error(`Login error: ${error.message}`);
    return false;
  }
}

async function testEndpoint(name, method, endpoint, body = null) {
  log.test(`Testing: ${name}`);
  try {
    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(authToken && { Authorization: `Bearer ${authToken}` }),
      },
      ...(body && { body: JSON.stringify(body) }),
    };
    
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    const data = await response.json();
    
    if (response.ok) {
      log.success(`${name}: PASSED (${response.status})`);
      return { success: true, data };
    } else {
      log.error(`${name}: FAILED (${response.status})`);
      console.log('Response:', JSON.stringify(data, null, 2));
      return { success: false, data };
    }
  } catch (error) {
    log.error(`${name}: ERROR - ${error.message}`);
    return { success: false, error: error.message };
  }
}

async function runTests() {
  console.log('\n' + '='.repeat(60));
  console.log('🧪 Research API Test Suite');
  console.log('='.repeat(60) + '\n');
  
  // Authenticate
  const authSuccess = await login();
  if (!authSuccess) {
    log.error('Cannot proceed without authentication');
    process.exit(1);
  }
  
  const results = [];
  
  // Test 1: List backtests
  const listResult = await testEndpoint('List Backtests', 'GET', '/research/backtests');
  results.push(listResult);
  
  // Test 2: List datasets
  const datasetsResult = await testEndpoint('List Datasets', 'GET', '/research/datasets');
  results.push(datasetsResult);
  
  // Test 3: Get backtest detail (if we have one)
  if (listResult.success && listResult.data?.backtests?.length > 0) {
    const backtestId = listResult.data.backtests[0].id;
    const detailResult = await testEndpoint('Get Backtest Detail', 'GET', `/research/backtests/${backtestId}`);
    results.push(detailResult);
  }
  
  // Test 4: Create backtest
  if (datasetsResult.success && datasetsResult.data?.datasets?.length > 0) {
    const dataset = datasetsResult.data.datasets[0];
    const endDate = new Date();
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - 7);
    
    const createResult = await testEndpoint('Create Backtest', 'POST', '/research/backtests', {
      strategy_id: 'amt_value_area_rejection_scalp',
      symbol: dataset.symbol,
      exchange: 'okx',
      start_date: startDate.toISOString(),
      end_date: endDate.toISOString(),
      initial_capital: 10000,
    });
    results.push(createResult);
  }
  
  // Test 5: Filter by status
  await testEndpoint('Filter Backtests (pending)', 'GET', '/research/backtests?status=pending');
  await testEndpoint('Filter Backtests (completed)', 'GET', '/research/backtests?status=completed');
  
  // Summary
  console.log('\n' + '='.repeat(60));
  console.log('📊 Test Summary');
  console.log('='.repeat(60));
  
  const passed = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;
  
  console.log(`Total: ${results.length} | Passed: ${passed} | Failed: ${failed}`);
  console.log('='.repeat(60) + '\n');
  
  process.exit(failed > 0 ? 1 : 0);
}

// Check if fetch is available (Node 18+)
if (typeof fetch === 'undefined') {
  console.error('This script requires Node.js 18+ with native fetch support');
  console.error('Or install node-fetch: npm install node-fetch');
  process.exit(1);
}

runTests().catch(console.error);





