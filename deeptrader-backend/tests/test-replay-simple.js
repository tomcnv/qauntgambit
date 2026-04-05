/**
 * Simple test script for Replay API
 * Run after restarting the backend server: node tests/test-replay-simple.js
 */

const BASE_URL = 'http://localhost:3001';

async function test() {
  console.log('🧪 Testing Replay API Endpoints\n');

  // Test 1: Get incidents (should return empty array or existing incidents)
  try {
    const res1 = await fetch(`${BASE_URL}/api/replay/incidents?limit=5`);
    const data1 = await res1.json();
    console.log('✅ GET /api/replay/incidents:', data1.success ? 'SUCCESS' : 'FAILED');
    if (data1.success) {
      console.log(`   Found ${data1.data?.length || 0} incidents\n`);
    }
  } catch (e) {
    console.log('❌ GET /api/replay/incidents: ERROR -', e.message, '\n');
  }

  // Test 2: Create an incident
  try {
    const res2 = await fetch(`${BASE_URL}/api/replay/incidents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        incidentType: 'large_loss',
        severity: 'high',
        startTime: new Date('2025-01-01T00:00:00Z').toISOString(),
        endTime: new Date('2025-01-01T23:59:59Z').toISOString(),
        affectedSymbols: ['BTC-USDT-SWAP'],
        title: 'Test Incident',
        description: 'Testing replay API',
      }),
    });
    const data2 = await res2.json();
    console.log('✅ POST /api/replay/incidents:', data2.success ? 'SUCCESS' : 'FAILED');
    if (data2.success && data2.data?.id) {
      console.log(`   Created incident ID: ${data2.data.id}\n`);
      return data2.data.id;
    }
  } catch (e) {
    console.log('❌ POST /api/replay/incidents: ERROR -', e.message, '\n');
  }

  // Test 3: Get replay data (may be empty if no snapshots exist)
  try {
    const start = new Date('2025-01-01T00:00:00Z').toISOString();
    const end = new Date('2025-01-01T23:59:59Z').toISOString();
    const res3 = await fetch(`${BASE_URL}/api/replay/BTC-USDT-SWAP?start=${start}&end=${end}`);
    const data3 = await res3.json();
    console.log('✅ GET /api/replay/:symbol:', data3.success ? 'SUCCESS' : 'FAILED');
    if (data3.success) {
      console.log(`   Snapshots: ${data3.data?.snapshots?.length || 0}`);
      console.log(`   Traces: ${data3.data?.traces?.length || 0}\n`);
    }
  } catch (e) {
    console.log('❌ GET /api/replay/:symbol: ERROR -', e.message, '\n');
  }

  console.log('✅ All tests complete!\n');
}

test().catch(console.error);





