/**
 * Master Seed Script
 * 
 * Runs all seed scripts in the correct order to populate a fresh database
 * with essential default data.
 * 
 * Usage: node scripts/seed-all.js
 * 
 * What gets seeded:
 * 1. Admin user (for initial login)
 * 2. Canonical profiles (from Python definitions)
 * 3. Strategy templates (from Python definitions)
 * 4. Profile-strategy links
 */

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const seeds = [
  {
    name: 'Admin User',
    script: 'seed-admin-user.js',
    description: 'Creates default admin user for initial login'
  },
  {
    name: 'Canonical Profiles',
    script: 'seed-canonical-profiles.js',
    description: 'Loads 20+ trading profiles from Python definitions'
  },
  {
    name: 'Strategy Templates',
    script: 'seed-strategies.js',
    description: 'Loads strategy templates from Python definitions'
  },
  {
    name: 'Profile-Strategy Links',
    script: 'link-profile-strategies.js',
    description: 'Links strategies to their appropriate profiles'
  }
];

async function runScript(scriptPath, name) {
  return new Promise((resolve, reject) => {
    console.log(`\n📦 Running: ${name}`);
    console.log(`   Script: ${scriptPath}`);
    
    const child = spawn('node', [scriptPath], {
      cwd: __dirname,
      stdio: 'inherit'
    });
    
    child.on('close', (code) => {
      if (code === 0) {
        console.log(`   ✅ ${name} completed`);
        resolve();
      } else {
        console.log(`   ⚠️ ${name} exited with code ${code}`);
        // Don't reject - continue with other seeds
        resolve();
      }
    });
    
    child.on('error', (err) => {
      console.error(`   ❌ Error running ${name}:`, err.message);
      resolve(); // Continue anyway
    });
  });
}

async function main() {
  console.log('🌱 DeepTrader Database Seeding');
  console.log('================================');
  console.log('');
  console.log('This will populate the database with essential default data.');
  console.log('');
  console.log('Seeds to run:');
  seeds.forEach((seed, i) => {
    console.log(`  ${i + 1}. ${seed.name} - ${seed.description}`);
  });
  
  const startTime = Date.now();
  
  for (const seed of seeds) {
    const scriptPath = path.join(__dirname, seed.script);
    await runScript(scriptPath, seed.name);
  }
  
  const duration = ((Date.now() - startTime) / 1000).toFixed(1);
  
  console.log('\n================================');
  console.log(`✅ Seeding complete in ${duration}s`);
  console.log('');
  console.log('Next steps:');
  console.log('  1. Start the backend: cd deeptrader-backend && node server.js');
  console.log('  2. Login with admin@deeptrader.com / admin123');
  console.log('  3. Create your user account and start trading!');
}

main().catch(console.error);
