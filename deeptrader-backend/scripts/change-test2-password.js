#!/usr/bin/env node
/**
 * Change password for test2@example.com
 */

import { loadLayeredEnv } from '../config/env.js';
import { findUserByEmail } from '../models/User.js';

loadLayeredEnv();

const TEST2_EMAIL = 'test2@example.com';
const NEW_PASSWORD = 'gotom123';

async function changePassword() {
  try {
    const email = TEST2_EMAIL.toLowerCase().trim();
    const user = await findUserByEmail(email);

    if (!user) {
      console.error(`❌ User ${email} not found`);
      console.log('   The user may not exist in the database.');
      process.exit(1);
    }

    await user.changePassword(NEW_PASSWORD);
    console.log(`✅ Password changed successfully for ${email}`);
    console.log(`   New password: ${NEW_PASSWORD}`);
    process.exit(0);
  } catch (error) {
    console.error('❌ Failed to change password:', error.message);
    process.exit(1);
  }
}

changePassword();
