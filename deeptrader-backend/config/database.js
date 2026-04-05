/**
 * Database Configuration
 * PostgreSQL connection and configuration
 */

import pkg from 'pg';
const { Pool } = pkg;
import { loadLayeredEnv } from './env.js';

loadLayeredEnv();

// Database configuration
const dbConfig = {
  host: process.env.DB_HOST || 'localhost',
  port: process.env.DB_PORT || 5432,
  database: process.env.DB_NAME || 'deeptrader',
  user: process.env.DB_USER || 'deeptrader_user',
  password: process.env.DB_PASSWORD || 'deeptrader_pass',
  max: 20, // Maximum number of clients in the pool
  idleTimeoutMillis: 10000, // Close idle clients after 10 seconds
  connectionTimeoutMillis: 5000, // Return error after 5 seconds if no connection
  allowExitOnIdle: false, // Keep pool alive
  // TCP keepalive settings to prevent connection drops
  keepAlive: true,
  keepAliveInitialDelayMillis: 10000,
};

// Only force TLS when explicitly enabled or when targeting a known managed endpoint.
// Docker-internal service names like `postgres_platform` are plain TCP and break if we
// assume "non-localhost => SSL".
const dbHost = String(process.env.DB_HOST || 'localhost').trim().toLowerCase();
const explicitSsl = String(process.env.DB_SSL || '').trim().toLowerCase();
const sslForcedOn = ['true', '1', 'yes', 'require', 'on'].includes(explicitSsl);
const sslForcedOff = ['false', '0', 'no', 'disable', 'off'].includes(explicitSsl);
const looksLikeManagedPostgres =
  dbHost.endsWith('.rds.amazonaws.com') ||
  dbHost.endsWith('.amazonaws.com') ||
  dbHost.includes('neon.tech') ||
  dbHost.includes('supabase.co') ||
  dbHost.includes('render.com');

if (!sslForcedOff && (sslForcedOn || looksLikeManagedPostgres)) {
  dbConfig.ssl = { rejectUnauthorized: false };
}

// Create connection pool
const pool = new Pool(dbConfig);

// Event handlers
pool.on('connect', (client) => {
  console.log('🔗 New client connected to PostgreSQL');
});

pool.on('error', (err, client) => {
  // Don't crash the process - just log and let the pool handle reconnection
  console.error('⚠️ PostgreSQL idle client error (will auto-reconnect):', err.message);
});

// Test connection
export const testConnection = async () => {
  try {
    const client = await pool.connect();
    console.log('✅ PostgreSQL connected successfully');
    client.release();
    return true;
  } catch (err) {
    console.error('❌ PostgreSQL connection failed:', err.message);
    return false;
  }
};

// Query helper with error handling
export const query = async (text, params) => {
  const start = Date.now();
  try {
    const res = await pool.query(text, params);
    const duration = Date.now() - start;
    console.log(`📊 Query executed in ${duration}ms:`, text.split('\n')[0]);
    return res;
  } catch (err) {
    console.error('❌ Query error:', err);
    throw err;
  }
};

// Transaction helper
export const transaction = async (callback) => {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await callback(client);
    await client.query('COMMIT');
    return result;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
};

// Health check
export const healthCheck = async () => {
  try {
    await pool.query('SELECT 1');
    return { status: 'healthy', database: 'connected' };
  } catch (err) {
    return { status: 'unhealthy', database: 'disconnected', error: err.message };
  }
};

// Graceful shutdown
process.on('SIGINT', async () => {
  console.log('🛑 Closing PostgreSQL pool...');
  await pool.end();
  console.log('✅ PostgreSQL pool closed');
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.log('🛑 Closing PostgreSQL pool...');
  await pool.end();
  console.log('✅ PostgreSQL pool closed');
  process.exit(0);
});

export default pool;
