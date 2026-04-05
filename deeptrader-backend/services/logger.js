/**
 * Lightweight structured logging helpers to keep console noise consistent
 * while preventing sensitive information from leaking.
 */

const MAX_VALUE_LENGTH = 500;

function sanitizeContext(context = {}) {
  return Object.entries(context).reduce((acc, [key, value]) => {
    if (value === undefined || value === null) {
      return acc;
    }
    if (typeof value === 'string' && value.length > MAX_VALUE_LENGTH) {
      acc[key] = `${value.slice(0, MAX_VALUE_LENGTH)}…`;
      return acc;
    }
    acc[key] = value;
    return acc;
  }, { timestamp: new Date().toISOString() });
}

function logStructuredEvent(level = 'info', scope = 'app', message = '', context = {}) {
  const payload = sanitizeContext({ scope, ...context });
  if (level === 'error') {
    console.error(`❌ ${message}`, payload);
  } else if (level === 'warn') {
    console.warn(`⚠️ ${message}`, payload);
  } else {
    console.log(`ℹ️ ${message}`, payload);
  }
}

export { logStructuredEvent };



