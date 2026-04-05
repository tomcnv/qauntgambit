#!/usr/bin/env node
/**
 * Complete test runner: setup user + run tests
 */

import axios from 'axios';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const API_BASE = 'http://localhost:3001/api';
const TEST_EMAIL = `test-${Date.now()}@example.com`;
const TEST_PASSWORD = 'testpassword123';

let authToken = null;

async function setupUser() {
  try {
    // Try login first
    const loginRes = await axios.post(`${API_BASE}/auth/login`, {
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
    });
    authToken = loginRes.data.token;
    console.log('✅ Logged in as test user');
    return true;
  } catch (error) {
    // Try register
    try {
      const registerRes = await axios.post(`${API_BASE}/auth/register`, {
        email: TEST_EMAIL,
        password: TEST_PASSWORD,
        username: `testuser-${Date.now()}`,
      });
      authToken = registerRes.data.token;
      console.log('✅ Registered and logged in as test user');
      return true;
    } catch (regError) {
      console.error('❌ Failed to setup user:', regError.response?.data || regError.message);
      return false;
    }
  }
}

async function testEndpoint(name, method, endpoint, body = null) {
  try {
    const options = {
      method,
      url: `${API_BASE}${endpoint}`,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authToken}`,
      },
      ...(body && { data: body }),
    };
    
    const response = await axios(options);
    console.log(`✅ ${name}: PASSED (${response.status})`);
    return { success: true, data: response.data };
  } catch (error) {
    const status = error.response?.status || 'ERROR';
    const message = error.response?.data?.message || error.message;
    console.log(`❌ ${name}: FAILED (${status}) - ${message}`);
    return { success: false, error: message };
  }
}

async function runTests() {
  console.log('\n' + '='.repeat(60));
  console.log('🧪 Research API Test Suite');
  console.log('='.repeat(60) + '\n');
  
  // Setup user
  if (!(await setupUser())) {
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
  } else {
    console.log('⚠️  Skipping backtest detail test (no backtests found)');
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
  } else {
    console.log('⚠️  Skipping create backtest test (no datasets found)');
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

runTests().catch(console.error);

