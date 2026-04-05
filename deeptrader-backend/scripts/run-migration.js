/**
 * Run database migration
 * Usage: node scripts/run-migration.js migrations/filename.sql
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';
import pool from '../config/database.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runMigration(migrationFile) {
  const filename = path.basename(migrationFile);
  try {
    const migrationPath = path.join(__dirname, '..', migrationFile);
    console.log(`📄 Reading migration: ${migrationPath}`);
    
    const sql = fs.readFileSync(migrationPath, 'utf8');
    const checksum = crypto.createHash('sha256').update(sql, 'utf8').digest('hex');

    // Track which migrations ran to prevent drift across environments.
    // This is structure-only: it does not touch application data.
    await pool.query(`
      CREATE TABLE IF NOT EXISTS public.schema_migrations (
        id BIGSERIAL PRIMARY KEY,
        filename TEXT UNIQUE NOT NULL,
        checksum TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);

    const existing = await pool.query(
      `SELECT filename, checksum, applied_at
       FROM public.schema_migrations
       WHERE filename = $1`,
      [filename]
    );
    if (existing.rows.length > 0) {
      const row = existing.rows[0];
      if (row.checksum !== checksum) {
        throw new Error(
          `Migration ${filename} already applied with different checksum (applied_at=${row.applied_at}). ` +
          `Refusing to re-run; create a new migration instead.`
        );
      }
      console.log(`⏭️  Migration already applied (skipping): ${filename}`);
      process.exit(0);
    }

    const baselineStateExists = await pool.query(`
      SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'schema_baseline_state'
      ) AS exists
    `);
    if (baselineStateExists.rows[0]?.exists) {
      const baseline = await pool.query(
        `SELECT schema_checksum
         FROM public.schema_baseline_state
         WHERE schema_name = 'platform'
         LIMIT 1`
      );
      const baselineChecksum = baseline.rows[0]?.schema_checksum;
      if (baselineChecksum && baselineChecksum === checksum) {
        await pool.query(
          `INSERT INTO public.schema_migrations (filename, checksum)
           VALUES ($1, $2)
           ON CONFLICT (filename) DO NOTHING`,
          [filename, checksum]
        );
        console.log(`⏭️  Migration baseline already bootstrapped (recorded and skipping): ${filename}`);
        process.exit(0);
      }
    }

    if (filename === '000_golden_platform_schema.sql') {
      const usersExists = await pool.query(`
        SELECT EXISTS (
          SELECT FROM information_schema.tables
          WHERE table_schema = 'public'
            AND table_name = 'users'
        ) AS exists
      `);
      if (usersExists.rows[0]?.exists) {
        await pool.query(
          `INSERT INTO public.schema_migrations (filename, checksum)
           VALUES ($1, $2)
           ON CONFLICT (filename) DO NOTHING`,
          [filename, checksum]
        );
        console.log(`⏭️  Golden platform baseline detected from existing schema (recorded and skipping): ${filename}`);
        process.exit(0);
      }
    }

    console.log(`🔄 Executing migration...`);

    // Run in a transaction so partial application doesn't create more drift.
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(sql);
      await client.query(
        `INSERT INTO public.schema_migrations (filename, checksum)
         VALUES ($1, $2)`,
        [filename, checksum]
      );
      await client.query('COMMIT');
    } catch (err) {
      try {
        await client.query('ROLLBACK');
      } catch {
        // ignore rollback failures; original error is more important
      }
      throw err;
    } finally {
      client.release();
    }

    console.log(`✅ Migration completed successfully: ${filename}`);
    
    process.exit(0);
  } catch (error) {
    console.error(`❌ Migration failed:`, error);
    process.exit(1);
  }
}

const migrationFile = process.argv[2];
if (!migrationFile) {
  console.error('Usage: node scripts/run-migration.js migrations/filename.sql');
  process.exit(1);
}

runMigration(migrationFile);
