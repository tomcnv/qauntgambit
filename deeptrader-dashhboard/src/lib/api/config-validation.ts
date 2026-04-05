/**
 * Bot Configuration Validation API Client
 * 
 * Validates bot configuration for consistency before trading.
 */

import { apiRequest } from './http';

// Types
export type ValidationSeverity = 'error' | 'warning' | 'info';

export interface ValidationIssue {
  id: string;
  ruleName?: string;
  severity: ValidationSeverity;
  field: string | null;
  message: string;
  detail?: string;
  suggestion?: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  info: ValidationIssue[];
  summary: string;
  botId?: string;
  botName?: string;
}

export interface PreflightResult {
  canStart: boolean;
  reason: string;
  botId?: string;
  botName?: string;
  tradingMode?: string;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  info: ValidationIssue[];
  summary: string;
  suggestedFixes?: Record<string, unknown>;
}

export interface BotConfigForValidation {
  tradingMode?: string;
  environment?: string;
  venue?: string;
  isDemo?: boolean;
  tradingCapitalUsd?: string | number;
  enabledSymbols?: string[];
  riskConfig?: {
    maxPositions?: number;
    positionSizePct?: number;
    maxDailyLossPct?: number;
    maxTotalExposurePct?: number;
    maxExposurePerSymbolPct?: number;
    maxLeverage?: number;
    leverageMode?: string;
    maxPositionsPerSymbol?: number;
    maxDailyLossPerSymbolPct?: number;
  };
  executionConfig?: {
    stopLossPct?: number;
    takeProfitPct?: number;
    trailingStopEnabled?: boolean;
    trailingStopPct?: number;
    maxHoldTimeHours?: number;
  };
}

/**
 * Validate a configuration object
 */
export async function validateConfig(config: BotConfigForValidation): Promise<ValidationResult> {
  return apiRequest<ValidationResult>('/config-validation/validate', {
    method: 'POST',
    data: config
  });
}

/**
 * Validate a saved bot's configuration
 */
export async function validateBot(botId: string): Promise<ValidationResult> {
  return apiRequest<ValidationResult>(`/config-validation/bot/${botId}`);
}

/**
 * Pre-flight check before starting a bot
 */
export async function preflightCheck(botId: string): Promise<PreflightResult> {
  return apiRequest<PreflightResult>(`/config-validation/can-start/${botId}`, {
    method: 'POST'
  });
}

// Binance USDT-M Futures has a FLAT $100 minimum notional for ALL symbols
// This is the actual exchange limit - orders below this are rejected
const BINANCE_MIN_NOTIONAL_USD = 100;

// Symbol minimum CONTRACT sizes (for precision, not dollar minimums)
const SYMBOL_MIN_CONTRACTS: Record<string, number> = {
  'BTC-USDT-SWAP': 0.001,
  'ETH-USDT-SWAP': 0.001,
  'SOL-USDT-SWAP': 0.1,
  'DOGE-USDT-SWAP': 1.0,
  'XRP-USDT-SWAP': 1.0,
  'AVAX-USDT-SWAP': 0.1,
  'LINK-USDT-SWAP': 0.1,
  'MATIC-USDT-SWAP': 1.0,
};

// Get minimum notional - Binance enforces $100 minimum for all symbols
function getMinimumNotional(_symbol: string): number {
  return BINANCE_MIN_NOTIONAL_USD;
}

/**
 * Client-side validation (same rules as backend for instant feedback)
 */
export function validateConfigClient(config: BotConfigForValidation): ValidationResult {
  const result: ValidationResult = {
    valid: true,
    errors: [],
    warnings: [],
    info: [],
    summary: ''
  };

  const riskConfig = config.riskConfig || {};
  const execConfig = config.executionConfig || {};

  // Position size vs symbol exposure
  const positionSize = riskConfig.positionSizePct || 10;
  const maxExposure = riskConfig.maxExposurePerSymbolPct || 20;
  
  if (positionSize > maxExposure) {
    result.errors.push({
      id: 'position_size_vs_symbol_exposure',
      severity: 'error',
      field: 'positionSizePct',
      message: `Position size (${positionSize}%) exceeds max exposure per symbol (${maxExposure}%)`,
      detail: 'Every trade will be rejected by the risk validator.',
      suggestion: `Set "Max Exposure Per Symbol" to at least ${positionSize}%`
    });
    result.valid = false;
  }

  // Total exposure overflow
  const maxPositions = riskConfig.maxPositions || 4;
  const maxTotalExposure = riskConfig.maxTotalExposurePct || 80;
  const worstCaseExposure = positionSize * maxPositions;
  
  if (worstCaseExposure > maxTotalExposure) {
    result.errors.push({
      id: 'total_exposure_overflow',
      severity: 'error',
      field: 'maxPositions',
      message: `Max positions × position size = ${worstCaseExposure}% exceeds total exposure limit (${maxTotalExposure}%)`,
      suggestion: `Reduce max positions to ${Math.floor(maxTotalExposure / positionSize)} or increase total exposure`
    });
    result.valid = false;
  }

  // Minimum capital
  const capital = parseFloat(String(config.tradingCapitalUsd || 0));
  if (capital < 10) {
    result.errors.push({
      id: 'minimum_capital',
      severity: 'error',
      field: 'tradingCapitalUsd',
      message: `Trading capital ($${capital}) is below minimum ($10)`,
      suggestion: 'Set trading capital to at least $10'
    });
    result.valid = false;
  }

  // Leverage
  const leverage = Math.max(1, riskConfig.maxLeverage || 1);
  
  // Position size too small (accounting for leverage)
  const marginAvailable = capital * (positionSize / 100);
  const effectivePositionSize = marginAvailable * leverage;
  
  if (effectivePositionSize < 5) {
    result.errors.push({
      id: 'position_size_too_small',
      severity: 'error',
      field: 'positionSizePct',
      message: `Position size ($${effectivePositionSize.toFixed(2)}) is below exchange minimum ($5)`,
      suggestion: 'Increase capital, position size, or leverage'
    });
    result.valid = false;
  }

  // No symbols
  const symbols = config.enabledSymbols || [];
  if (symbols.length === 0) {
    result.errors.push({
      id: 'no_symbols',
      severity: 'error',
      field: 'enabledSymbols',
      message: 'No trading symbols selected',
      suggestion: 'Select at least one trading pair'
    });
    result.valid = false;
  }

  // Binance enforces $100 minimum notional for ALL symbols
  const minNotional = BINANCE_MIN_NOTIONAL_USD;
  
  if (symbols.length > 0 && effectivePositionSize < minNotional) {
    const minMarginRequired = minNotional / leverage;
    result.errors.push({
      id: 'binance_minimum_notional',
      severity: 'error',
      field: 'tradingCapitalUsd',
      message: `Position notional ($${effectivePositionSize.toFixed(0)}) is below Binance minimum ($${minNotional})`,
      detail: `Binance requires at least $100 notional per order. With $${marginAvailable.toFixed(0)} margin and ${leverage}x leverage, your notional is only $${effectivePositionSize.toFixed(0)}.`,
      suggestion: `Increase capital to at least $${Math.ceil(minMarginRequired / (positionSize / 100))}, or increase position size to ${Math.ceil(minMarginRequired / capital * 100)}%, or use higher leverage.`
    });
    result.valid = false;
  }

  if (leverage < 1) {
    result.errors.push({
      id: 'leverage_range',
      severity: 'error',
      field: 'maxLeverage',
      message: 'Leverage must be at least 1x'
    });
    result.valid = false;
  }

  // === WARNINGS ===

  // Stop loss vs take profit
  const stopLoss = execConfig.stopLossPct || 2;
  const takeProfit = execConfig.takeProfitPct || 5;
  if (stopLoss >= takeProfit) {
    result.warnings.push({
      id: 'stop_loss_vs_take_profit',
      severity: 'warning',
      field: 'stopLossPct',
      message: `Stop loss (${stopLoss}%) >= take profit (${takeProfit}%)`,
      detail: 'Your risk/reward ratio is unfavorable.'
    });
  }

  // High leverage
  if (leverage > 10) {
    result.warnings.push({
      id: 'high_leverage_warning',
      severity: 'warning',
      field: 'maxLeverage',
      message: `High leverage (${leverage}x) increases liquidation risk`
    });
  }

  // Large position size
  if (positionSize > 50) {
    result.warnings.push({
      id: 'large_position_size',
      severity: 'warning',
      field: 'positionSizePct',
      message: `Large position size (${positionSize}%) concentrates risk`
    });
  }

  // High daily loss
  const maxDailyLoss = riskConfig.maxDailyLossPct || 5;
  if (maxDailyLoss > 10) {
    result.warnings.push({
      id: 'high_daily_loss_limit',
      severity: 'warning',
      field: 'maxDailyLossPct',
      message: `Daily loss limit (${maxDailyLoss}%) is very high`
    });
  }

  // === INFO ===

  if (config.tradingMode === 'paper' || config.environment === 'paper') {
    result.info.push({
      id: 'paper_trading_notice',
      severity: 'info',
      field: 'tradingMode',
      message: 'Paper trading mode - no real money at risk'
    });
  }

  if (config.isDemo) {
    result.info.push({
      id: 'demo_notice',
      severity: 'info',
      field: 'isDemo',
      message: 'Demo mode - using exchange demo trading (Bybit/OKX only)'
    });
  }

  // Generate summary
  const parts: string[] = [];
  if (result.errors.length > 0) {
    parts.push(`${result.errors.length} error${result.errors.length > 1 ? 's' : ''}`);
  }
  if (result.warnings.length > 0) {
    parts.push(`${result.warnings.length} warning${result.warnings.length > 1 ? 's' : ''}`);
  }
  result.summary = parts.length > 0 ? parts.join(', ') : 'Configuration valid';

  return result;
}




