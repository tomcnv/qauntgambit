/**
 * Guardian Orchestrator Service
 * 
 * Manages Position Guardian processes for tenants.
 * Starts guardian when: verified exchange + live bot exists
 * Stops guardian when: no live bots remain for tenant
 */

import Redis from 'ioredis';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import pool from '../config/database.js';

const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379');

function isAwsRuntime() {
  return !!(process.env.AWS_EXECUTION_ENV || process.env.ECS_CONTAINER_METADATA_URI_V4);
}

// Guardian process orchestration is a *local dev* concern by default.
// In AWS, the core-api container should never try to spawn PM2 (not installed),
// and certainly should not crash if it's missing.
const guardianLaunchMode = (process.env.GUARDIAN_LAUNCH_MODE || (isAwsRuntime() ? 'disabled' : 'pm2')).toLowerCase();

/**
 * Check if a tenant needs a guardian running
 * Tenant needs guardian when they have:
 * - At least one verified exchange account
 * - At least one bot in live mode on that account
 * 
 * Note: Relationship is bot_instances -> bot_exchange_configs -> exchange_accounts
 */
async function getTenantGuardianAccounts(tenantId) {
  const query = `
    SELECT DISTINCT
      ea.id as account_id,
      ea.venue,
      ea.is_demo,
      ea.secret_id,
      array_agg(DISTINCT bi.id) as bot_ids
    FROM exchange_accounts ea
    JOIN bot_exchange_configs bec ON bec.exchange_account_id = ea.id
    JOIN bot_instances bi ON bi.id = bec.bot_instance_id
    WHERE ea.tenant_id = $1
      AND ea.status = 'verified'
      AND ea.secret_id IS NOT NULL
      AND bi.trading_mode = 'live'
      AND bi.is_active = true
      AND bi.deleted_at IS NULL
    GROUP BY ea.id, ea.venue, ea.is_demo, ea.secret_id
  `;
  
  try {
    const result = await pool.query(query, [tenantId]);
    return result.rows.map(row => ({
      account_id: row.account_id,
      venue: row.venue,
      is_testnet: row.is_demo,  // Map is_demo to is_testnet for backwards compatibility
      secret_id: row.secret_id,
      bot_ids: row.bot_ids || [],
    }));
  } catch (error) {
    console.error('[GuardianOrchestrator] Error fetching accounts:', error);
    return [];
  }
}

/**
 * Update the Redis key that tells the guardian which accounts to monitor
 */
async function updateGuardianAccounts(tenantId, accounts) {
  const key = `guardian:tenant:${tenantId}:accounts`;
  
  try {
    if (accounts.length === 0) {
      await redis.del(key);
      console.log(`[GuardianOrchestrator] Cleared guardian accounts for tenant ${tenantId}`);
    } else {
      await redis.set(key, JSON.stringify(accounts), 'EX', 300); // 5 min TTL, guardian refreshes
      console.log(`[GuardianOrchestrator] Updated guardian accounts for tenant ${tenantId}:`, accounts.length);
    }
    return true;
  } catch (error) {
    console.error('[GuardianOrchestrator] Error updating Redis:', error);
    return false;
  }
}

/**
 * Check if a guardian is running for this tenant
 */
async function isGuardianRunning(tenantId) {
  const healthKey = `guardian:tenant:${tenantId}:health`;
  
  try {
    const health = await redis.get(healthKey);
    if (!health) return false;
    
    const parsed = JSON.parse(health);
    const age = Date.now() / 1000 - parsed.timestamp;
    
    // Consider running if heartbeat within last 30 seconds
    return age < 30 && parsed.status === 'running';
  } catch (error) {
    return false;
  }
}

/**
 * Start a guardian process for a tenant
 */
async function startGuardian(tenantId) {
  if (guardianLaunchMode !== 'pm2') {
    console.log(`[GuardianOrchestrator] Guardian launch disabled (mode=${guardianLaunchMode})`);
    return false;
  }

  const guardianName = `guardian-${tenantId.substring(0, 8)}`;
  
  console.log(`[GuardianOrchestrator] Starting guardian for tenant ${tenantId}`);
  
  // Use __dirname to get correct project root
  const backendDir = path.dirname(new URL(import.meta.url).pathname);
  const projectRoot = path.resolve(backendDir, '..', '..');
  const pythonDir = path.join(projectRoot, 'quantgambit-python');
  const pm2Path = process.env.PM2_PATH || 'pm2';

  // If a full path is provided, validate it so we fail gracefully instead of crashing.
  if (pm2Path.includes('/') && !fs.existsSync(pm2Path)) {
    console.error(`[GuardianOrchestrator] PM2 not found at ${pm2Path}; skipping guardian start`);
    return false;
  }
  
  console.log(`[GuardianOrchestrator] Project root: ${projectRoot}`);
  console.log(`[GuardianOrchestrator] Python dir: ${pythonDir}`);
  
  const env = {
    ...process.env,
    TENANT_ID: tenantId,
    REDIS_URL: process.env.REDIS_URL || `redis://${process.env.REDIS_HOST || 'localhost'}:${process.env.REDIS_PORT || 6379}`,
    GUARDIAN_POLL_SEC: '5',
    GUARDIAN_REFRESH_SEC: '60',
    PATH: process.env.PATH + ':/opt/homebrew/bin',
  };
  
  try {
    // Check if already running via pm2
    const checkProc = spawn(pm2Path, ['describe', guardianName], { stdio: 'pipe', env });
    
    return new Promise((resolve) => {
      let output = '';
      checkProc.stdout?.on('data', (data) => { output += data.toString(); });
      checkProc.on('error', (err) => {
        // Never crash core-api if PM2 isn't available.
        console.error(`[GuardianOrchestrator] PM2 describe failed:`, err.message || err);
        resolve(false);
      });
      checkProc.on('close', async (code) => {
        if (code === 0 && output.includes('online')) {
          console.log(`[GuardianOrchestrator] Guardian ${guardianName} already running`);
          resolve(true);
          return;
        }
        
        // Start the guardian using venv311 (same as control-manager)
        const pythonPath = path.join(pythonDir, 'venv311/bin/python');
        const startArgs = [
          'start',
          pythonPath,
          '--name', guardianName,
          '--interpreter', 'none',
          '--',
          '-m', 'quantgambit.guardian.tenant_guardian',
        ];
        
        console.log(`[GuardianOrchestrator] Running: ${pm2Path} ${startArgs.join(' ')}`);
        
        const startProc = spawn(pm2Path, startArgs, {
          cwd: pythonDir,
          env,
          stdio: 'inherit',
        });
        
        startProc.on('error', (err) => {
          console.error(`[GuardianOrchestrator] Spawn error:`, err);
          resolve(false);
        });
        
        startProc.on('close', (startCode) => {
          if (startCode === 0) {
            console.log(`[GuardianOrchestrator] Guardian ${guardianName} started`);
            resolve(true);
          } else {
            console.error(`[GuardianOrchestrator] Failed to start guardian, exit code: ${startCode}`);
            resolve(false);
          }
        });
      });
    });
  } catch (error) {
    console.error('[GuardianOrchestrator] Error starting guardian:', error);
    return false;
  }
}

/**
 * Stop a guardian process for a tenant
 */
async function stopGuardian(tenantId) {
  if (guardianLaunchMode !== 'pm2') {
    console.log(`[GuardianOrchestrator] Guardian stop disabled (mode=${guardianLaunchMode})`);
    return false;
  }

  const guardianName = `guardian-${tenantId.substring(0, 8)}`;
  const pm2Path = process.env.PM2_PATH || 'pm2';
  
  console.log(`[GuardianOrchestrator] Stopping guardian for tenant ${tenantId}`);
  
  try {
    const proc = spawn(pm2Path, ['delete', guardianName], { stdio: 'inherit' });
    
    return new Promise((resolve) => {
      proc.on('error', (err) => {
        console.error(`[GuardianOrchestrator] Stop spawn error:`, err);
        resolve(false);
      });
      proc.on('close', (code) => {
        if (code === 0) {
          console.log(`[GuardianOrchestrator] Guardian ${guardianName} stopped`);
        }
        resolve(true);
      });
    });
  } catch (error) {
    console.error('[GuardianOrchestrator] Error stopping guardian:', error);
    return false;
  }
}

/**
 * Main orchestration function - call when bot state changes
 * 
 * @param {string} tenantId - Tenant ID
 * @param {string} trigger - What triggered this check ('bot_start', 'bot_stop', 'mode_change')
 */
async function orchestrateGuardian(tenantId, trigger = 'unknown') {
  console.log(`[GuardianOrchestrator] Orchestrating for tenant ${tenantId}, trigger: ${trigger}`);
  
  // Get accounts that need guardian coverage
  const accounts = await getTenantGuardianAccounts(tenantId);
  
  // Update Redis with current accounts
  await updateGuardianAccounts(tenantId, accounts);

  // In AWS we currently don't spawn the guardian from inside the core-api container.
  // This avoids crashes when PM2 isn't present and lets us move guardian orchestration
  // to a dedicated ECS task/service later.
  if (guardianLaunchMode !== 'pm2') {
    console.log(`[GuardianOrchestrator] Skipping process management (mode=${guardianLaunchMode})`);
    return {
      tenantId,
      accountsNeedingCoverage: accounts.length,
      guardianRunning: await isGuardianRunning(tenantId),
      launchMode: guardianLaunchMode,
    };
  }
  
  const guardianRunning = await isGuardianRunning(tenantId);
  const needsGuardian = accounts.length > 0;
  
  if (needsGuardian && !guardianRunning) {
    // Need guardian but not running - start it
    console.log(`[GuardianOrchestrator] Starting guardian - ${accounts.length} accounts need coverage`);
    await startGuardian(tenantId);
  } else if (!needsGuardian && guardianRunning) {
    // Guardian running but no longer needed - stop it
    console.log(`[GuardianOrchestrator] Stopping guardian - no accounts need coverage`);
    await stopGuardian(tenantId);
  } else if (needsGuardian && guardianRunning) {
    console.log(`[GuardianOrchestrator] Guardian already running, accounts updated`);
  } else {
    console.log(`[GuardianOrchestrator] No guardian needed, none running`);
  }
  
  return {
    tenantId,
    accountsNeedingCoverage: accounts.length,
    guardianRunning: needsGuardian,
  };
}

/**
 * Get guardian status for a tenant
 */
async function getGuardianStatus(tenantId) {
  const accounts = await getTenantGuardianAccounts(tenantId);
  const running = await isGuardianRunning(tenantId);
  
  let health = null;
  try {
    const healthData = await redis.get(`guardian:tenant:${tenantId}:health`);
    if (healthData) {
      health = JSON.parse(healthData);
    }
  } catch (error) {
    // Ignore
  }
  
  return {
    tenantId,
    needsGuardian: accounts.length > 0,
    isRunning: running,
    accountsCovered: accounts.length,
    accounts: accounts.map(a => ({ id: a.account_id, venue: a.venue })),
    health,
  };
}

export default {
  orchestrateGuardian,
  getGuardianStatus,
  getTenantGuardianAccounts,
  isGuardianRunning,
  startGuardian,
  stopGuardian,
};

export {
  orchestrateGuardian,
  getGuardianStatus,
  getTenantGuardianAccounts,
  isGuardianRunning,
  startGuardian,
  stopGuardian,
};

