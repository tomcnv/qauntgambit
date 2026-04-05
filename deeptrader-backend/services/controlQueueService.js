import Redis from 'ioredis';
import { v4 as uuidv4 } from 'uuid';

const ALLOWED_TYPES = new Set(['start_bot', 'stop_bot', 'pause_bot', 'halt_bot', 'flatten_positions']);
const DEFAULT_REQUESTER = 'dashboard';

const redisUrl = process.env.REDIS_URL;
const redisOptions = redisUrl
  ? redisUrl
  : {
      host: process.env.REDIS_HOST || 'localhost',
      port: Number(process.env.REDIS_PORT || 6379),
      password: process.env.REDIS_PASSWORD || undefined,
      lazyConnect: true,
      maxRetriesPerRequest: 3,
    };

const redis = new Redis(redisOptions);

redis.on('error', (err) => {
  console.error('❌ controlQueueService Redis error:', err.message);
});

function requireScope(tenantId, botId) {
  if (!tenantId) {
    throw new Error('tenant_id_required');
  }
  if (!botId) {
    throw new Error('bot_id_required');
  }
}

function commandStreamName(tenantId, botId) {
  requireScope(tenantId, botId);
  return `commands:control:${tenantId}:${botId}`;
}

function resultStreamName(tenantId, botId) {
  requireScope(tenantId, botId);
  return `events:control_result:${tenantId}:${botId}`;
}

function statusLockKey(tenantId, botId) {
  requireScope(tenantId, botId);
  return `control:bot_status:${tenantId}:${botId}`;
}

function startLockKey(tenantId, botId) {
  requireScope(tenantId, botId);
  return `control:start_lock:${tenantId}:${botId}`;
}

function serviceHealthKey(botId) {
  return botId ? `bot:${botId}:service_health` : null;
}

async function ensureConnected() {
  if (redis.status === 'ready' || redis.status === 'connecting') return redis;
  await redis.connect();
  return redis;
}

function parseFields(fields) {
  const obj = {};
  for (let i = 0; i < fields.length; i += 2) {
    obj[fields[i]] = fields[i + 1];
  }
  if (!obj.data) return null;
  try {
    return JSON.parse(obj.data);
  } catch {
    return null;
  }
}

async function checkStartGuard(tenantId, botId) {
  const client = await ensureConnected();
  const key = startLockKey(tenantId, botId);
  const lock = await client.get(key);
  if (lock) {
    throw new Error('start_in_progress');
  }
}

async function setStartLock(tenantId, botId, ttlSec = 300) {
  const client = await ensureConnected();
  const key = startLockKey(tenantId, botId);
  await client.set(key, '1', 'EX', ttlSec);
}

export async function clearStartLock(tenantId, botId) {
  const client = await ensureConnected();
  const key = startLockKey(tenantId, botId);
  await client.del(key);
}

export async function getStartLockState(tenantId, botId) {
  const client = await ensureConnected();
  const key = startLockKey(tenantId, botId);
  const exists = await client.exists(key);
  const ttl = await client.ttl(key);
  return { locked: !!exists, ttl };
}

export async function enqueueCommand({ type, tenantId, botId, requestedBy, reason, payload }) {
  if (!ALLOWED_TYPES.has(type)) {
    const list = Array.from(ALLOWED_TYPES).join(', ');
    throw new Error(`unsupported_command_type:${type}. Allowed: ${list}`);
  }
  requireScope(tenantId, botId);

  if (type === 'start_bot') {
    await checkStartGuard(tenantId, botId);
  }

  const client = await ensureConnected();
  const commandId = uuidv4();
  const stream = commandStreamName(tenantId, botId);
  const now = new Date().toISOString();
  const scope = {
    tenant_id: tenantId,
    bot_id: botId,
  };

  const command = {
    command_id: commandId,
    type,
    scope,
    requested_by: requestedBy || DEFAULT_REQUESTER,
    requested_at: now,
    schema_version: 'v1',
    reason: reason || null,
    payload: payload || null,
  };

  await client.xadd(stream, '*', 'data', JSON.stringify(command));
  if (type === 'start_bot') {
    await setStartLock(tenantId, botId);
  }

  return { commandId, stream };
}

export async function fetchCommandResults({ tenantId, botId, commandId, limit = 20 }) {
  const client = await ensureConnected();
  const stream = resultStreamName(tenantId, botId);
  const entries = await client.xrevrange(stream, '+', '-', 'COUNT', limit);
  const results = [];

  for (const [, fields] of entries) {
    const parsed = parseFields(fields);
    if (!parsed) continue;
    if (commandId && parsed.command_id !== commandId) continue;
    results.push(parsed);
  }
  return results;
}

export function buildCommandStreams({ tenantId, botId }) {
  return {
    commandStream: commandStreamName(tenantId, botId),
    resultStream: resultStreamName(tenantId, botId),
  };
}

export async function clearCommandStream(tenantId, botId) {
  const client = await ensureConnected();
  const stream = commandStreamName(tenantId, botId);
  await client.xtrim(stream, 'MAXLEN', 0);
}
