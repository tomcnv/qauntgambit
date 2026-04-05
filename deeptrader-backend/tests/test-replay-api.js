/**
 * API endpoint tests for Replay functionality
 * Run with: node tests/test-replay-api.js
 */

import fetch from 'node-fetch';

const BASE_URL = process.env.API_URL || 'http://localhost:3001';
let authToken = null;

// Test helper functions
async function login() {
  const response = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: process.env.TEST_EMAIL || 'test@example.com',
      password: process.env.TEST_PASSWORD || 'test123',
    }),
  });

  if (response.ok) {
    const data = await response.json();
    authToken = data.token;
    return authToken;
  } else {
    console.warn('⚠️  Could not login, some tests may fail');
    return null;
  }
}

async function testEndpoint(method, path, body = null, description) {
  try {
    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
    };

    if (authToken) {
      options.headers['Authorization'] = `Bearer ${authToken}`;
    }

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(`${BASE_URL}${path}`, options);
    const data = await response.json();

    if (response.ok) {
      console.log(`✅ ${description}`);
      return { success: true, data };
    } else {
      console.log(`❌ ${description}: ${data.error || response.statusText}`);
      return { success: false, error: data.error || response.statusText };
    }
  } catch (error) {
    console.log(`❌ ${description}: ${error.message}`);
    return { success: false, error: error.message };
  }
}

async function runTests() {
  console.log('🧪 Testing Replay API Endpoints\n');
  console.log(`Base URL: ${BASE_URL}\n`);

  // Try to login (optional - some endpoints may not require auth)
  await login();

  const testSymbol = 'BTC-USDT-SWAP';
  const testStartTime = new Date('2025-01-01T00:00:00Z').toISOString();
  const testEndTime = new Date('2025-01-01T23:59:59Z').toISOString();

  let testIncidentId = null;

  console.log('📋 Testing Incident Management\n');

  // Test: Create incident
  const createIncidentResult = await testEndpoint(
    'POST',
    '/api/replay/incidents',
    {
      incidentType: 'large_loss',
      severity: 'high',
      startTime: testStartTime,
      endTime: testEndTime,
      affectedSymbols: [testSymbol],
      title: 'API Test Incident',
      description: 'Testing incident creation via API',
      pnlImpact: -1000.50,
      positionsAffected: 2,
      tradesAffected: 5,
    },
    'Create incident'
  );

  if (createIncidentResult.success && createIncidentResult.data?.data?.id) {
    testIncidentId = createIncidentResult.data.data.id;
  }

  // Test: Get incidents list
  await testEndpoint(
    'GET',
    '/api/replay/incidents?limit=10',
    null,
    'Get incidents list'
  );

  // Test: Get incident by ID
  if (testIncidentId) {
    await testEndpoint(
      'GET',
      `/api/replay/incidents/${testIncidentId}`,
      null,
      'Get incident by ID'
    );

    // Test: Update incident status
    await testEndpoint(
      'PUT',
      `/api/replay/incidents/${testIncidentId}/status`,
      {
        status: 'investigating',
        resolutionNotes: 'API test - investigating',
      },
      'Update incident status'
    );
  }

  console.log('\n📊 Testing Replay Data\n');

  // Test: Get replay data for symbol
  await testEndpoint(
    'GET',
    `/api/replay/${testSymbol}?start=${testStartTime}&end=${testEndTime}`,
    null,
    'Get replay data for symbol'
  );

  console.log('\n🎬 Testing Replay Sessions\n');

  // Test: Create replay session
  const createSessionResult = await testEndpoint(
    'POST',
    '/api/replay/sessions',
    {
      incidentId: testIncidentId,
      symbol: testSymbol,
      startTime: testStartTime,
      endTime: testEndTime,
      sessionName: 'API Test Session',
      notes: 'Testing session creation',
    },
    'Create replay session'
  );

  // Test: Get replay sessions
  await testEndpoint(
    'GET',
    '/api/replay/sessions?limit=10',
    null,
    'Get replay sessions'
  );

  console.log('\n✅ API Tests Complete!\n');
}

// Run tests
runTests().catch(console.error);





