import Redis from 'ioredis';

const DEFAULT_SLIPPAGE_ROLLUP_WINDOW_SEC = Number(process.env.RUNTIME_SLIPPAGE_ROLLUP_WINDOW_SEC || 3600);
const DEFAULT_SLIPPAGE_ROLLUP_BACKFILL_COUNT = Number(process.env.RUNTIME_SLIPPAGE_ROLLUP_BACKFILL_COUNT || 400);
const SLIPPAGE_ROLLUP_STATE_TTL_SEC = Number(process.env.RUNTIME_SLIPPAGE_ROLLUP_STATE_TTL_SEC || 86400);
const SLIPPAGE_ROLLUP_STATE_PREFIX = 'deeptrader:rollup:slippage';
const SLIPPAGE_ALERT_TARGET_BPS = Number(process.env.RUNTIME_SLIPPAGE_ALERT_TARGET_BPS || 5);
const SLIPPAGE_ALERT_MIN_SAMPLES = Number(process.env.RUNTIME_SLIPPAGE_ALERT_MIN_SAMPLES || 8);
const SLIPPAGE_ALERT_COOLDOWN_SEC = Number(process.env.RUNTIME_SLIPPAGE_ALERT_COOLDOWN_SEC || 900);

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildStreams() {
  const envStreams = process.env.RUNTIME_STREAMS;
  if (envStreams) {
    return envStreams.split(',').map((s) => s.trim()).filter(Boolean);
  }
  const tenant = process.env.TENANT_ID;
  const bot = process.env.BOT_ID;
  if (tenant && bot) {
    return [
      `events:decisions:${tenant}:${bot}`,
      `events:order:${tenant}:${bot}`,
      `events:position_lifecycle:${tenant}:${bot}`,
      `events:positions:${tenant}:${bot}`,
      `events:guardrail:${tenant}:${bot}`,
      `events:prediction:${tenant}:${bot}`,
      `events:latency:${tenant}:${bot}`,
      `events:order_update:${tenant}:${bot}`,
      `events:features:${tenant}:${bot}`,
      `events:risk_decisions:${tenant}:${bot}`,
      `events:blocked_signal:${tenant}:${bot}`,
      `quantgambit:${tenant}:${bot}:blocked_signals`,
    ];
  }
  return [
    'events:decisions',
    'events:order',
    'events:position_lifecycle',
    'events:positions',
    'events:guardrail',
    'events:prediction',
    'events:latency',
    'events:order_update',
    'events:features',
    'events:risk_decisions',
    'events:blocked_signal',
  ];
}

const STREAMS = buildStreams();

function isPositionLifecycleStream(streamName) {
  return String(streamName || '').includes('position_lifecycle');
}

function parseStreamMessage(fields) {
  const payload = {};
  for (let i = 0; i < fields.length; i += 2) {
    payload[fields[i]] = fields[i + 1];
  }
  if (!payload.data) {
    return null;
  }
  try {
    return JSON.parse(payload.data);
  } catch (error) {
    return null;
  }
}

class SlippageRollupTracker {
  constructor(windowSec = DEFAULT_SLIPPAGE_ROLLUP_WINDOW_SEC) {
    this.windowSec = Number.isFinite(windowSec) && windowSec > 0 ? windowSec : 3600;
    this.byKey = new Map();
  }

  _updateKey(key, slippageBps, timestampSec) {
    const now = Number.isFinite(timestampSec) ? timestampSec : Date.now() / 1000;
    let bucket = this.byKey.get(key);
    if (!bucket) {
      bucket = { entries: [], sum: 0 };
      this.byKey.set(key, bucket);
    }
    bucket.entries.push({ ts: now, v: slippageBps });
    bucket.sum += slippageBps;

    const cutoff = now - this.windowSec;
    while (bucket.entries.length > 0 && bucket.entries[0].ts < cutoff) {
      const removed = bucket.entries.shift();
      bucket.sum -= removed.v;
    }

    if (bucket.entries.length === 0) {
      this.byKey.delete(key);
      return { avg: null, count: 0 };
    }
    return { avg: bucket.sum / bucket.entries.length, count: bucket.entries.length };
  }

  ingestClosedPosition(event) {
    const payload = event?.payload || {};
    const lifecycleType = String(payload.event_type || '').toLowerCase();
    if (lifecycleType !== 'closed') return null;

    const realizedSlippageBps = toFiniteNumber(payload.realized_slippage_bps);
    if (realizedSlippageBps === null) return null;

    const symbol = payload.symbol || event.symbol || null;
    const side = String(payload.side || '').toLowerCase() || 'unknown';
    if (!symbol) return null;

    const timestampSec = toFiniteNumber(event.timestamp)
      || toFiniteNumber(payload.exit_timestamp)
      || (Date.now() / 1000);

    const symbolSide = `${symbol}:${side}`;
    const symbolSideRollup = this._updateKey(symbolSide, realizedSlippageBps, timestampSec);
    const globalRollup = this._updateKey('__all__', realizedSlippageBps, timestampSec);

    return {
      event: 'bot:execution_slippage_rollup',
      data: {
        symbol,
        side,
        window_sec: this.windowSec,
        as_of_ts: timestampSec,
        latest_realized_slippage_bps: realizedSlippageBps,
        avg_realized_slippage_bps_symbol_side: symbolSideRollup.avg,
        sample_count_symbol_side: symbolSideRollup.count,
        avg_realized_slippage_bps_overall: globalRollup.avg,
        sample_count_overall: globalRollup.count,
      },
      meta: {
        botId: event.bot_id || payload.bot_id || payload.botId,
        tenantId: event.tenant_id || payload.tenant_id || payload.tenantId,
        exchange: event.exchange || payload.exchange,
        symbol,
      },
    };
  }
}

function buildSlippageStateKeys(rollupEvent) {
  const tenantId = rollupEvent?.meta?.tenantId;
  const botId = rollupEvent?.meta?.botId;
  const symbol = rollupEvent?.data?.symbol;
  const side = rollupEvent?.data?.side;
  if (!tenantId || !botId || !symbol || !side) {
    return null;
  }
  return {
    symbolSide: `${SLIPPAGE_ROLLUP_STATE_PREFIX}:${tenantId}:${botId}:${symbol}:${side}`,
    overall: `${SLIPPAGE_ROLLUP_STATE_PREFIX}:${tenantId}:${botId}:__overall__`,
  };
}

async function persistSlippageRollupSnapshot(redis, rollupEvent) {
  if (!redis || !rollupEvent) return;
  const keys = buildSlippageStateKeys(rollupEvent);
  if (!keys) return;

  const nowSec = Date.now() / 1000;
  const payload = {
    ...rollupEvent.data,
    updated_at: nowSec,
  };
  const overallPayload = {
    window_sec: rollupEvent.data?.window_sec,
    as_of_ts: rollupEvent.data?.as_of_ts,
    avg_realized_slippage_bps_overall: rollupEvent.data?.avg_realized_slippage_bps_overall,
    sample_count_overall: rollupEvent.data?.sample_count_overall,
    updated_at: nowSec,
  };

  await redis.set(keys.symbolSide, JSON.stringify(payload), 'EX', SLIPPAGE_ROLLUP_STATE_TTL_SEC);
  await redis.set(keys.overall, JSON.stringify(overallPayload), 'EX', SLIPPAGE_ROLLUP_STATE_TTL_SEC);
}

async function warmupSlippageRollup(redis, streams, slippageRollup) {
  if (!redis || !slippageRollup) return 0;
  const lifecycleStreams = (streams || []).filter(isPositionLifecycleStream);
  if (lifecycleStreams.length === 0) return 0;

  const backfillCount = Number.isFinite(DEFAULT_SLIPPAGE_ROLLUP_BACKFILL_COUNT)
    && DEFAULT_SLIPPAGE_ROLLUP_BACKFILL_COUNT > 0
    ? DEFAULT_SLIPPAGE_ROLLUP_BACKFILL_COUNT
    : 400;

  let ingested = 0;
  for (const stream of lifecycleStreams) {
    try {
      const rows = await redis.xrevrange(stream, '+', '-', 'COUNT', backfillCount);
      if (!Array.isArray(rows) || rows.length === 0) continue;
      for (const row of rows.slice().reverse()) {
        const fields = Array.isArray(row) ? row[1] : null;
        const event = parseStreamMessage(fields);
        if (!event) continue;
        const rollup = slippageRollup.ingestClosedPosition(event);
        if (!rollup) continue;
        ingested += 1;
      }
    } catch (error) {
      console.error(`❌ Slippage rollup warmup failed for ${stream}:`, error.message);
    }
  }
  return ingested;
}

function buildSlippageAlertStateKey(rollupEvent) {
  const tenantId = rollupEvent?.meta?.tenantId;
  const botId = rollupEvent?.meta?.botId;
  const symbol = rollupEvent?.data?.symbol;
  const side = rollupEvent?.data?.side;
  if (!tenantId || !botId || !symbol || !side) return null;
  return `${SLIPPAGE_ROLLUP_STATE_PREFIX}:alert:${tenantId}:${botId}:${symbol}:${side}`;
}

async function maybeEmitSlippageAlert(redis, rollupEvent, broadcast) {
  if (!redis || !rollupEvent || typeof broadcast !== 'function') return false;
  const avgBps = toFiniteNumber(rollupEvent?.data?.avg_realized_slippage_bps_symbol_side);
  const sampleCount = toFiniteNumber(rollupEvent?.data?.sample_count_symbol_side) || 0;
  const targetBps = Number.isFinite(SLIPPAGE_ALERT_TARGET_BPS) && SLIPPAGE_ALERT_TARGET_BPS > 0
    ? SLIPPAGE_ALERT_TARGET_BPS
    : 5;
  const minSamples = Number.isFinite(SLIPPAGE_ALERT_MIN_SAMPLES) && SLIPPAGE_ALERT_MIN_SAMPLES > 0
    ? SLIPPAGE_ALERT_MIN_SAMPLES
    : 8;
  const cooldownSec = Number.isFinite(SLIPPAGE_ALERT_COOLDOWN_SEC) && SLIPPAGE_ALERT_COOLDOWN_SEC > 0
    ? SLIPPAGE_ALERT_COOLDOWN_SEC
    : 900;

  if (avgBps === null || sampleCount < minSamples || avgBps <= targetBps) {
    return false;
  }

  const stateKey = buildSlippageAlertStateKey(rollupEvent);
  if (!stateKey) return false;

  const nowSec = Date.now() / 1000;
  const lastRaw = await redis.get(stateKey);
  const lastAlertSec = toFiniteNumber(lastRaw) || 0;
  if (lastAlertSec > 0 && (nowSec - lastAlertSec) < cooldownSec) {
    return false;
  }

  await redis.set(stateKey, String(nowSec), 'EX', cooldownSec);
  const symbol = rollupEvent?.data?.symbol;
  const side = rollupEvent?.data?.side;
  broadcast({
    event: 'bot:alert',
    data: {
      type: 'execution_slippage_alert',
      severity: avgBps > targetBps * 1.5 ? 'high' : 'warning',
      symbol,
      side,
      avg_realized_slippage_bps: avgBps,
      target_slippage_bps: targetBps,
      sample_count: sampleCount,
      window_sec: rollupEvent?.data?.window_sec,
      message: `Realized slippage ${avgBps.toFixed(2)}bps exceeds target ${targetBps.toFixed(2)}bps`,
      triggered_at: nowSec,
    },
    meta: rollupEvent?.meta || {},
  });
  return true;
}

function mapEventToWs(event) {
  const type = event.event_type;
  const payload = event.payload || {};
  const meta = {
    botId: event.bot_id || payload.bot_id || payload.botId,
    tenantId: event.tenant_id || payload.tenant_id || payload.tenantId,
    exchange: event.exchange || payload.exchange,
    symbol: event.symbol || payload.symbol,
  };
  // Handle both 'decision' and 'decisions' event types
  if (type === 'decision' || type === 'decisions') {
    return { event: 'bot:decision', data: payload, meta };
  }
  if (type === 'risk_decision' || type === 'risk_decisions') {
    return { event: 'bot:risk_decision', data: payload, meta };
  }
  if (type === 'features' || type === 'feature') {
    return { event: 'bot:features', data: payload, meta };
  }
  if (type === 'prediction') {
    return { event: 'bot:signal', data: payload, meta };
  }
  if (type === 'positions') {
    return { event: 'bot:position_update', data: payload, meta };
  }
  if (type === 'position_lifecycle') {
    const lifecycleType = String(payload.event_type || '').toLowerCase();
    if (lifecycleType === 'closed') {
      return { event: 'bot:position_closed', data: payload, meta };
    }
    if (lifecycleType === 'opened') {
      return { event: 'bot:position_opened', data: payload, meta };
    }
    return { event: 'bot:position_update', data: payload, meta };
  }
  if (type === 'guardrail') {
    // Check if this is a blocked signal event (loss prevention)
    if (payload.type === 'signal_blocked') {
      return { event: 'loss_prevention_update', data: payload, meta };
    }
    return { event: 'bot:alert', data: payload, meta };
  }
  if (type === 'order_update') {
    return { event: 'bot:order', data: payload, meta };
  }
  if (type === 'order') {
    const status = String(payload.status || '').toLowerCase();
    const wsEvent = status === 'filled' || status === 'closed' ? 'bot:trade' : 'bot:order';
    return { event: wsEvent, data: payload, meta };
  }
  if (type === 'latency') {
    return { event: 'bot:status', data: payload, meta };
  }
  // Handle blocked signal events directly (loss prevention)
  if (type === 'blocked_signal' || type === 'signal_blocked') {
    return { event: 'loss_prevention_update', data: payload, meta };
  }
  return null;
}

export async function startRuntimeStreamBridge({ broadcast }) {
  const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379';
  const redis = new Redis(redisUrl);
  const slippageRollup = new SlippageRollupTracker();
  const lastIds = Object.fromEntries(STREAMS.map((stream) => [stream, '$']));

  redis.on('error', (error) => {
    console.error('❌ Runtime stream bridge Redis error:', error.message);
  });

  const warmed = await warmupSlippageRollup(redis, STREAMS, slippageRollup);
  if (warmed > 0) {
    console.log(`📈 Slippage rollup warmup complete (${warmed} closed positions)`);
  }

  const readLoop = async () => {
    while (true) {
      try {
        const streamsArgs = [];
        for (const stream of STREAMS) {
          streamsArgs.push(stream);
        }
        for (const stream of STREAMS) {
          streamsArgs.push(lastIds[stream] || '$');
        }

        const result = await redis.xread('BLOCK', 1000, 'COUNT', 50, 'STREAMS', ...streamsArgs);
        if (!result) {
          continue;
        }

        for (const [stream, messages] of result) {
          for (const [id, fields] of messages) {
            lastIds[stream] = id;
            const event = parseStreamMessage(fields);
            if (!event) {
              continue;
            }
            const mapped = mapEventToWs(event);
            if (mapped) {
              broadcast(mapped);
            }
            const rollup = slippageRollup.ingestClosedPosition(event);
            if (rollup) {
              await persistSlippageRollupSnapshot(redis, rollup);
              broadcast(rollup);
              await maybeEmitSlippageAlert(redis, rollup, broadcast);
            }
          }
        }
      } catch (error) {
        console.error('❌ Runtime stream bridge read error:', error.message);
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }
  };

  readLoop().catch((error) => {
    console.error('❌ Runtime stream bridge crashed:', error.message);
  });

  console.log('📡 Runtime stream bridge active (Redis Streams → WebSocket)');
}

export {
  buildStreams,
  parseStreamMessage,
  mapEventToWs,
  SlippageRollupTracker,
  persistSlippageRollupSnapshot,
  warmupSlippageRollup,
  isPositionLifecycleStream,
  maybeEmitSlippageAlert,
};
