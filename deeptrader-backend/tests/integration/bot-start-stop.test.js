process.env.NODE_ENV = 'test';
process.env.FORCE_NO_ACTIVE_CONFIG = 'true';
process.env.AUTO_START_PY_CONTROL = 'false';
process.env.ALLOW_UNAUTHENTICATED = 'true';

import test from 'node:test';
import assert from 'node:assert';
import http from 'node:http';
import { once } from 'node:events';

// Defer importing the app until after env is set to avoid booting services in tests
const { app } = await import('../../server.js');

// Helper to start/stop the express app on a random port for tests
function createTestServer() {
  const server = http.createServer(app);
  return new Promise((resolve) => {
    server.listen(0, () => {
      const { port } = server.address();
      resolve({ server, port });
    });
  });
}

// Minimal helper to perform HTTP requests
async function requestJson(port, path, options = {}) {
  const payload = options.body ? JSON.stringify(options.body) : null;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };
  const requestOptions = {
    hostname: 'localhost',
    port,
    path,
    method: options.method || 'GET',
    headers,
  };
  const req = http.request(requestOptions);
  if (payload) req.write(payload);
  req.end();
  const [res] = await once(req, 'response');
  const data = await new Promise((resolve) => {
    let body = '';
    res.on('data', (chunk) => (body += chunk.toString()));
    res.on('end', () => resolve(body));
  });
  const json = data ? JSON.parse(data) : {};
  return { status: res.statusCode, json };
}

test('bot start should fail when no active config', async (t) => {
  const { server, port } = await createTestServer();
  t.after(() => server.close());

  const res = await requestJson(port, '/api/bot/start', { method: 'POST' });
  assert.strictEqual(res.status, 400);
  assert.ok(res.json.message.includes('No active bot-exchange configuration'));
});

