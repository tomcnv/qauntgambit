import { loadLayeredEnv } from '../config/env.js';
import { createUser, findUserByEmail } from '../models/User.js';

loadLayeredEnv();

const DEFAULT_EMAIL = process.env.ADMIN_EMAIL || 'ops@deeptrader.local';
const DEFAULT_USERNAME = process.env.ADMIN_USERNAME || 'control';
const DEFAULT_PASSWORD = process.env.ADMIN_PASSWORD || 'ControlTower!23';
const DEFAULT_FIRST = process.env.ADMIN_FIRST_NAME || 'Control';
const DEFAULT_LAST = process.env.ADMIN_LAST_NAME || 'Tower';

async function seedAdmin() {
  try {
    const email = DEFAULT_EMAIL.toLowerCase().trim();
    let user = await findUserByEmail(email);

    if (!user) {
      user = await createUser({
        email,
        username: DEFAULT_USERNAME,
        password: DEFAULT_PASSWORD,
        firstName: DEFAULT_FIRST,
        lastName: DEFAULT_LAST,
      });
      console.log(`✅ Created admin user ${email} (username: ${DEFAULT_USERNAME})`);
    } else if (process.env.ADMIN_RESET_PASSWORD !== 'false') {
      await user.changePassword(DEFAULT_PASSWORD);
      console.log(`🔐 Reset password for ${email}`);
    } else {
      console.log(`ℹ️ Admin user ${email} already exists (password untouched)`);
    }

    console.log('Use these credentials to log in to the dashboard:');
    console.log(`  Email:    ${email}`);
    console.log(`  Username: ${user.username}`);
    console.log(`  Password: ${DEFAULT_PASSWORD}`);
    process.exit(0);
  } catch (error) {
    console.error('❌ Failed to seed admin user:', error.message);
    process.exit(1);
  }
}

seedAdmin();





