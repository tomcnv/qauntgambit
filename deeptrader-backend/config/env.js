import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

export function loadLayeredEnv({ envFile = process.env.ENV_FILE || '.env' } = {}) {
  const loaded = [];
  const candidates = [path.join(PROJECT_ROOT, '.env')];
  if (envFile && envFile !== '.env') {
    candidates.push(path.isAbsolute(envFile) ? envFile : path.join(PROJECT_ROOT, envFile));
  }

  for (const candidate of candidates) {
    const result = dotenv.config({ path: candidate, override: false });
    if (!result.error) {
      loaded.push(candidate);
    }
  }

  return loaded;
}
