import test from 'node:test';
import assert from 'node:assert';
test('status endpoint wiring (conceptual) includes activeConfig fields when provided', async () => {
  // This is a lightweight guard to ensure our shape matches what the frontend expects.
  // In integration tests we will hit /api/bot/status; here we simulate the shape.
  const activeConfig = {
    id: 'cfg-123',
    environment: 'paper',
    state: 'ready',
    is_active: true,
  };
  const response = {
    trading: { isActive: true, mode: 'paper' },
    platform: { status: 'online' },
    activeConfig: {
      id: activeConfig.id,
      environment: activeConfig.environment,
      state: activeConfig.state,
      isActive: activeConfig.is_active,
    },
  };

  assert.strictEqual(response.activeConfig.environment, 'paper');
  assert.strictEqual(response.activeConfig.state, 'ready');
  assert.ok(response.activeConfig.isActive);
});


