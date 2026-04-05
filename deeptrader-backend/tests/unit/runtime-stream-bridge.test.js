import test from 'node:test';
import assert from 'node:assert/strict';

import {
  mapEventToWs,
  SlippageRollupTracker,
  persistSlippageRollupSnapshot,
  warmupSlippageRollup,
  isPositionLifecycleStream,
  maybeEmitSlippageAlert,
} from '../../services/runtimeStreamBridge.js';

test('mapEventToWs maps closed position lifecycle', () => {
  const mapped = mapEventToWs({
    event_type: 'position_lifecycle',
    bot_id: 'b1',
    tenant_id: 't1',
    symbol: 'ETHUSDT',
    payload: {
      event_type: 'closed',
      symbol: 'ETHUSDT',
      side: 'buy',
      realized_slippage_bps: 6.5,
    },
  });

  assert.ok(mapped);
  assert.equal(mapped.event, 'bot:position_closed');
  assert.equal(mapped.data.symbol, 'ETHUSDT');
  assert.equal(mapped.data.realized_slippage_bps, 6.5);
});

test('slippage rollup tracks symbol-side and global rolling averages', () => {
  const tracker = new SlippageRollupTracker(3600);

  const evt1 = tracker.ingestClosedPosition({
    event_type: 'position_lifecycle',
    symbol: 'ETHUSDT',
    timestamp: 1000,
    payload: {
      event_type: 'closed',
      symbol: 'ETHUSDT',
      side: 'buy',
      realized_slippage_bps: 10,
    },
  });
  assert.ok(evt1);
  assert.equal(evt1.event, 'bot:execution_slippage_rollup');
  assert.equal(evt1.data.avg_realized_slippage_bps_symbol_side, 10);
  assert.equal(evt1.data.sample_count_symbol_side, 1);
  assert.equal(evt1.data.avg_realized_slippage_bps_overall, 10);
  assert.equal(evt1.data.sample_count_overall, 1);

  const evt2 = tracker.ingestClosedPosition({
    event_type: 'position_lifecycle',
    symbol: 'ETHUSDT',
    timestamp: 1100,
    payload: {
      event_type: 'closed',
      symbol: 'ETHUSDT',
      side: 'buy',
      realized_slippage_bps: 20,
    },
  });
  assert.ok(evt2);
  assert.equal(evt2.data.sample_count_symbol_side, 2);
  assert.equal(evt2.data.sample_count_overall, 2);
  assert.equal(evt2.data.avg_realized_slippage_bps_symbol_side, 15);
  assert.equal(evt2.data.avg_realized_slippage_bps_overall, 15);
});

test('slippage rollup evicts stale samples outside the rolling window', () => {
  const tracker = new SlippageRollupTracker(60);

  tracker.ingestClosedPosition({
    event_type: 'position_lifecycle',
    symbol: 'BTCUSDT',
    timestamp: 1000,
    payload: {
      event_type: 'closed',
      symbol: 'BTCUSDT',
      side: 'sell',
      realized_slippage_bps: 5,
    },
  });

  const fresh = tracker.ingestClosedPosition({
    event_type: 'position_lifecycle',
    symbol: 'BTCUSDT',
    timestamp: 1070,
    payload: {
      event_type: 'closed',
      symbol: 'BTCUSDT',
      side: 'sell',
      realized_slippage_bps: 15,
    },
  });

  assert.ok(fresh);
  assert.equal(fresh.data.sample_count_symbol_side, 1);
  assert.equal(fresh.data.avg_realized_slippage_bps_symbol_side, 15);
  assert.equal(fresh.data.sample_count_overall, 1);
  assert.equal(fresh.data.avg_realized_slippage_bps_overall, 15);
});

test('isPositionLifecycleStream detects lifecycle streams', () => {
  assert.equal(isPositionLifecycleStream('events:position_lifecycle'), true);
  assert.equal(isPositionLifecycleStream('events:position_lifecycle:t1:b1'), true);
  assert.equal(isPositionLifecycleStream('events:order'), false);
});

test('persistSlippageRollupSnapshot writes symbol-side and overall keys', async () => {
  const writes = [];
  const fakeRedis = {
    async set(key, value, exLiteral, ttl) {
      writes.push({ key, value: JSON.parse(value), exLiteral, ttl });
      return 'OK';
    },
  };

  await persistSlippageRollupSnapshot(fakeRedis, {
    event: 'bot:execution_slippage_rollup',
    data: {
      symbol: 'ETHUSDT',
      side: 'buy',
      window_sec: 3600,
      as_of_ts: 1234,
      latest_realized_slippage_bps: 7,
      avg_realized_slippage_bps_symbol_side: 6.5,
      sample_count_symbol_side: 4,
      avg_realized_slippage_bps_overall: 5.2,
      sample_count_overall: 11,
    },
    meta: {
      tenantId: 't1',
      botId: 'b1',
    },
  });

  assert.equal(writes.length, 2);
  assert.ok(writes[0].key.includes('deeptrader:rollup:slippage:t1:b1:ETHUSDT:buy'));
  assert.ok(writes[1].key.includes('deeptrader:rollup:slippage:t1:b1:__overall__'));
  assert.equal(writes[0].exLiteral, 'EX');
  assert.equal(typeof writes[0].ttl, 'number');
});

test('warmupSlippageRollup ingests closed lifecycle entries from streams', async () => {
  const tracker = new SlippageRollupTracker(3600);
  const payload = JSON.stringify({
    event_type: 'position_lifecycle',
    tenant_id: 't1',
    bot_id: 'b1',
    symbol: 'BTCUSDT',
    payload: {
      event_type: 'closed',
      symbol: 'BTCUSDT',
      side: 'sell',
      realized_slippage_bps: 8,
      exit_timestamp: 2000,
    },
  });
  const fakeRedis = {
    async xrevrange(stream) {
      if (stream.includes('position_lifecycle')) {
        return [['100-0', ['data', payload]]];
      }
      return [];
    },
  };

  const ingested = await warmupSlippageRollup(
    fakeRedis,
    ['events:position_lifecycle:t1:b1', 'events:order:t1:b1'],
    tracker,
  );
  assert.equal(ingested, 1);

  const next = tracker.ingestClosedPosition({
    event_type: 'position_lifecycle',
    symbol: 'BTCUSDT',
    timestamp: 2010,
    payload: {
      event_type: 'closed',
      symbol: 'BTCUSDT',
      side: 'sell',
      realized_slippage_bps: 12,
    },
  });
  assert.ok(next);
  assert.equal(next.data.sample_count_symbol_side, 2);
  assert.equal(next.data.avg_realized_slippage_bps_symbol_side, 10);
});

test('maybeEmitSlippageAlert emits and respects cooldown', async () => {
  const writes = new Map();
  const fakeRedis = {
    async get(key) {
      return writes.get(key) ?? null;
    },
    async set(key, value) {
      writes.set(key, value);
      return 'OK';
    },
  };
  const sent = [];
  const broadcast = (payload) => sent.push(payload);

  const rollupEvent = {
    event: 'bot:execution_slippage_rollup',
    data: {
      symbol: 'ETHUSDT',
      side: 'buy',
      window_sec: 3600,
      avg_realized_slippage_bps_symbol_side: 7.0,
      sample_count_symbol_side: 12,
    },
    meta: { tenantId: 't1', botId: 'b1' },
  };

  const first = await maybeEmitSlippageAlert(fakeRedis, rollupEvent, broadcast);
  const second = await maybeEmitSlippageAlert(fakeRedis, rollupEvent, broadcast);

  assert.equal(first, true);
  assert.equal(second, false);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].event, 'bot:alert');
  assert.equal(sent[0].data.type, 'execution_slippage_alert');
});
