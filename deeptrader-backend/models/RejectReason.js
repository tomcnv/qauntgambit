/**
 * Reject Reason Model
 * 
 * Structured reason codes for order rejections and errors.
 * Used by the enforcement service and logged for telemetry.
 */

/**
 * Reason code scopes
 */
export const Scopes = {
  TENANT: 'tenant',
  EXCHANGE: 'exchange',
  BOT: 'bot',
  SYMBOL: 'symbol',
  VENUE: 'venue',
  DATA: 'data',
  SYSTEM: 'system',
};

/**
 * All rejection reason codes
 */
export const RejectCodes = {
  // === Tenant Scope ===
  TENANT_LIVE_DISABLED: {
    code: 'TENANT_LIVE_DISABLED',
    scope: Scopes.TENANT,
    message: 'Live trading is not enabled for this account',
    severity: 'error',
  },
  TENANT_MODE_VIOLATION: {
    code: 'TENANT_MODE_VIOLATION',
    scope: Scopes.TENANT,
    message: 'Action not allowed in current operating mode',
    severity: 'error',
  },
  TENANT_PERMISSION_DENIED: {
    code: 'TENANT_PERMISSION_DENIED',
    scope: Scopes.TENANT,
    message: 'User does not have permission for this action',
    severity: 'error',
  },
  TENANT_APPROVAL_REQUIRED: {
    code: 'TENANT_APPROVAL_REQUIRED',
    scope: Scopes.TENANT,
    message: 'This action requires approval',
    severity: 'warning',
  },
  
  // === Exchange Account Scope ===
  EXCHANGE_KILL_SWITCH_ACTIVE: {
    code: 'EXCHANGE_KILL_SWITCH_ACTIVE',
    scope: Scopes.EXCHANGE,
    message: 'Kill switch is active - all trading blocked',
    severity: 'critical',
  },
  EXCHANGE_CIRCUIT_BREAKER: {
    code: 'EXCHANGE_CIRCUIT_BREAKER',
    scope: Scopes.EXCHANGE,
    message: 'Circuit breaker triggered - in cooldown period',
    severity: 'critical',
  },
  EXCHANGE_MAX_DAILY_LOSS: {
    code: 'EXCHANGE_MAX_DAILY_LOSS',
    scope: Scopes.EXCHANGE,
    message: 'Daily loss limit reached for this exchange account',
    severity: 'error',
  },
  EXCHANGE_MAX_MARGIN: {
    code: 'EXCHANGE_MAX_MARGIN',
    scope: Scopes.EXCHANGE,
    message: 'Maximum margin usage reached',
    severity: 'error',
  },
  EXCHANGE_MAX_EXPOSURE: {
    code: 'EXCHANGE_MAX_EXPOSURE',
    scope: Scopes.EXCHANGE,
    message: 'Maximum exposure limit reached',
    severity: 'error',
  },
  EXCHANGE_MAX_POSITIONS: {
    code: 'EXCHANGE_MAX_POSITIONS',
    scope: Scopes.EXCHANGE,
    message: 'Maximum open positions reached',
    severity: 'error',
  },
  EXCHANGE_MAX_LEVERAGE: {
    code: 'EXCHANGE_MAX_LEVERAGE',
    scope: Scopes.EXCHANGE,
    message: 'Requested leverage exceeds account limit',
    severity: 'error',
  },
  EXCHANGE_LIVE_DISABLED: {
    code: 'EXCHANGE_LIVE_DISABLED',
    scope: Scopes.EXCHANGE,
    message: 'Live trading not enabled for this exchange account',
    severity: 'error',
  },
  EXCHANGE_NOT_VERIFIED: {
    code: 'EXCHANGE_NOT_VERIFIED',
    scope: Scopes.EXCHANGE,
    message: 'Exchange credentials not verified',
    severity: 'error',
  },
  EXCHANGE_DISCONNECTED: {
    code: 'EXCHANGE_DISCONNECTED',
    scope: Scopes.EXCHANGE,
    message: 'Exchange connection lost',
    severity: 'error',
  },
  
  // === Bot Scope ===
  BOT_NOT_RUNNING: {
    code: 'BOT_NOT_RUNNING',
    scope: Scopes.BOT,
    message: 'Bot is not in running state',
    severity: 'error',
  },
  BOT_BUDGET_REQUIRED: {
    code: 'BOT_BUDGET_REQUIRED',
    scope: Scopes.BOT,
    message: 'Budget configuration required in PROP mode',
    severity: 'error',
  },
  BOT_BUDGET_DAILY_LOSS: {
    code: 'BOT_BUDGET_DAILY_LOSS',
    scope: Scopes.BOT,
    message: 'Bot daily loss budget exceeded',
    severity: 'error',
  },
  BOT_BUDGET_MARGIN: {
    code: 'BOT_BUDGET_MARGIN',
    scope: Scopes.BOT,
    message: 'Bot margin budget exceeded',
    severity: 'error',
  },
  BOT_BUDGET_POSITIONS: {
    code: 'BOT_BUDGET_POSITIONS',
    scope: Scopes.BOT,
    message: 'Bot position limit reached',
    severity: 'error',
  },
  BOT_BUDGET_LEVERAGE: {
    code: 'BOT_BUDGET_LEVERAGE',
    scope: Scopes.BOT,
    message: 'Requested leverage exceeds bot budget',
    severity: 'error',
  },
  BOT_BUDGET_ORDER_RATE: {
    code: 'BOT_BUDGET_ORDER_RATE',
    scope: Scopes.BOT,
    message: 'Order rate limit exceeded',
    severity: 'warning',
  },
  SOLO_MODE_BOT_ALREADY_RUNNING: {
    code: 'SOLO_MODE_BOT_ALREADY_RUNNING',
    scope: Scopes.BOT,
    message: 'Another bot is already running (SOLO mode allows only one)',
    severity: 'error',
  },
  
  // === Symbol Scope ===
  SYMBOL_LOCK_CONFLICT: {
    code: 'SYMBOL_LOCK_CONFLICT',
    scope: Scopes.SYMBOL,
    message: 'Symbol is owned by another bot',
    severity: 'error',
  },
  SYMBOL_NOT_ENABLED: {
    code: 'SYMBOL_NOT_ENABLED',
    scope: Scopes.SYMBOL,
    message: 'Symbol not in bot enabled list',
    severity: 'error',
  },
  SYMBOL_NOT_TRADEABLE: {
    code: 'SYMBOL_NOT_TRADEABLE',
    scope: Scopes.SYMBOL,
    message: 'Symbol is not currently tradeable',
    severity: 'warning',
  },
  
  // === Venue (Exchange Rule) Scope ===
  MIN_NOTIONAL_VIOLATION: {
    code: 'MIN_NOTIONAL_VIOLATION',
    scope: Scopes.VENUE,
    message: 'Order size below minimum notional',
    severity: 'error',
  },
  MAX_NOTIONAL_VIOLATION: {
    code: 'MAX_NOTIONAL_VIOLATION',
    scope: Scopes.VENUE,
    message: 'Order size exceeds maximum notional',
    severity: 'error',
  },
  TICK_SIZE_VIOLATION: {
    code: 'TICK_SIZE_VIOLATION',
    scope: Scopes.VENUE,
    message: 'Price does not match tick size',
    severity: 'error',
  },
  LOT_SIZE_VIOLATION: {
    code: 'LOT_SIZE_VIOLATION',
    scope: Scopes.VENUE,
    message: 'Quantity does not match lot size',
    severity: 'error',
  },
  MAX_LEVERAGE_VIOLATION: {
    code: 'MAX_LEVERAGE_VIOLATION',
    scope: Scopes.VENUE,
    message: 'Leverage exceeds exchange maximum',
    severity: 'error',
  },
  RATE_LIMIT_EXCEEDED: {
    code: 'RATE_LIMIT_EXCEEDED',
    scope: Scopes.VENUE,
    message: 'Exchange rate limit exceeded',
    severity: 'warning',
  },
  INSUFFICIENT_BALANCE: {
    code: 'INSUFFICIENT_BALANCE',
    scope: Scopes.VENUE,
    message: 'Insufficient balance for order',
    severity: 'error',
  },
  
  // === Data Quality Scope ===
  DATA_QUALITY_DEGRADED: {
    code: 'DATA_QUALITY_DEGRADED',
    scope: Scopes.DATA,
    message: 'Market data quality is degraded',
    severity: 'warning',
  },
  DATA_STALE: {
    code: 'DATA_STALE',
    scope: Scopes.DATA,
    message: 'Market data is stale',
    severity: 'error',
  },
  
  // === System Scope ===
  SYSTEM_ERROR: {
    code: 'SYSTEM_ERROR',
    scope: Scopes.SYSTEM,
    message: 'Internal system error',
    severity: 'critical',
  },
  VALIDATION_ERROR: {
    code: 'VALIDATION_ERROR',
    scope: Scopes.SYSTEM,
    message: 'Request validation failed',
    severity: 'error',
  },
};

/**
 * Create a rejection response
 */
export function createReject(reasonCode, details = {}) {
  const reason = RejectCodes[reasonCode] || {
    code: reasonCode,
    scope: Scopes.SYSTEM,
    message: 'Unknown error',
    severity: 'error',
  };
  
  return {
    allowed: false,
    code: reason.code,
    scope: reason.scope,
    message: reason.message,
    severity: reason.severity,
    details,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Create an allowed response
 */
export function createAllow(traceId = null) {
  return {
    allowed: true,
    trace_id: traceId,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Get all codes by scope
 */
export function getCodesByScope(scope) {
  return Object.values(RejectCodes).filter(r => r.scope === scope);
}

/**
 * Get all codes by severity
 */
export function getCodesBySeverity(severity) {
  return Object.values(RejectCodes).filter(r => r.severity === severity);
}

export default {
  Scopes,
  RejectCodes,
  createReject,
  createAllow,
  getCodesByScope,
  getCodesBySeverity,
};







