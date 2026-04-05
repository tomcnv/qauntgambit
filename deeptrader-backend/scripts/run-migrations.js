#!/usr/bin/env node
/**
 * Legacy wrapper retained for compatibility.
 * Use ../run_all_migrations.sh as the authoritative platform migration entrypoint.
 */

import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const scriptPath = join(__dirname, '..', 'run_all_migrations.sh');

const child = spawn('bash', [scriptPath], { stdio: 'inherit' });
child.on('exit', (code) => {
  process.exit(code ?? 1);
});
