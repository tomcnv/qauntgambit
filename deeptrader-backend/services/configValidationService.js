/**
 * Bot Configuration Validation Service
 * 
 * Validates bot configuration for consistency and sanity before trading.
 * Returns errors (blocking) and warnings (informational).
 */

// Validation severity levels
const SEVERITY = {
  ERROR: 'error',      // Must fix before trading
  WARNING: 'warning',  // Should review, but won't block
  INFO: 'info'         // Informational only
};

// Exchange minimum requirements
const EXCHANGE_MINIMUMS = {
  binance: {
    minCapital: 10,
    maxLeverage: 125,
    minPositionUsd: 5
  },
  okx: {
    minCapital: 10,
    maxLeverage: 100,
    minPositionUsd: 5
  },
  bybit: {
    minCapital: 10,
    maxLeverage: 100,
    minPositionUsd: 1
  }
};

// Binance USDT-M Futures has a FLAT $100 minimum notional for ALL symbols
// This is the actual exchange limit - orders below this are rejected
const BINANCE_MIN_NOTIONAL_USD = 100;

// Symbol minimum CONTRACT sizes (for precision, not dollar minimums)
const SYMBOL_MIN_CONTRACTS = {
  'BTC-USDT-SWAP': 0.001,
  'ETH-USDT-SWAP': 0.001,
  'SOL-USDT-SWAP': 0.1,
  'DOGE-USDT-SWAP': 1.0,
  'XRP-USDT-SWAP': 1.0,
  'AVAX-USDT-SWAP': 0.1,
  'LINK-USDT-SWAP': 0.1,
  'MATIC-USDT-SWAP': 1.0,
};

const normalizePercent = (value, fallback) => {
  if (value === null || value === undefined) return fallback;
  const num = Number(value);
  if (Number.isNaN(num)) return fallback;
  return num > 1 ? num / 100 : num;
};

const formatPercent = (value, digits = 2) => {
  if (value === null || value === undefined) return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return "N/A";
  return `${(num * 100).toFixed(digits)}%`;
};

const preservePercentScale = (rawValue, normalizedValue) => {
  const raw = Number(rawValue);
  if (!Number.isNaN(raw) && raw > 1) {
    return normalizedValue * 100;
  }
  return normalizedValue;
};

// Get minimum notional - Binance enforces $100 minimum for all symbols
function getMinimumNotional(symbol) {
  // Binance has a flat $100 minimum notional requirement
  return BINANCE_MIN_NOTIONAL_USD;
}

/**
 * Validation rules - each rule returns null if valid, or a validation result object
 */
const validationRules = [
  // ═══════════════════════════════════════════════════════════════
  // CRITICAL ERRORS - Will prevent trading
  // ═══════════════════════════════════════════════════════════════
  
  {
    id: 'position_size_vs_symbol_exposure',
    name: 'Position size exceeds per-symbol exposure limit',
    check: (config) => {
      const positionSize = normalizePercent(config.riskConfig?.positionSizePct, 0.10);
      const maxExposure = normalizePercent(config.riskConfig?.maxExposurePerSymbolPct, 0.20);
      
      if (positionSize > maxExposure) {
        return {
          severity: SEVERITY.ERROR,
          field: 'positionSizePct',
          message: `Position size (${formatPercent(positionSize)}) exceeds max exposure per symbol (${formatPercent(maxExposure)})`,
          detail: 'Every trade will be rejected by the risk validator. Set max exposure per symbol >= position size.',
          suggestion: `Set "Max Exposure Per Symbol" to at least ${formatPercent(positionSize)}`
        };
      }
      return null;
    }
  },
  
  {
    id: 'total_exposure_overflow',
    name: 'Max positions exceed total exposure',
    check: (config) => {
      const positionSize = normalizePercent(config.riskConfig?.positionSizePct, 0.10);
      const maxPositions = config.riskConfig?.maxPositions || 4;
      const maxTotalExposure = normalizePercent(config.riskConfig?.maxTotalExposurePct, 0.80);
      
      const worstCaseExposure = positionSize * maxPositions;
      
      if (worstCaseExposure > maxTotalExposure) {
        return {
          severity: SEVERITY.ERROR,
          field: 'maxPositions',
          message: `Max positions (${maxPositions}) × position size (${formatPercent(positionSize)}) = ${formatPercent(worstCaseExposure)} exceeds total exposure limit (${formatPercent(maxTotalExposure)})`,
          detail: 'You won\'t be able to open all configured positions simultaneously.',
          suggestion: `Either reduce max positions to ${Math.floor(maxTotalExposure / positionSize)} or increase total exposure to ${formatPercent(worstCaseExposure)}`
        };
      }
      return null;
    }
  },
  
  {
    id: 'minimum_capital',
    name: 'Trading capital too low',
    check: (config) => {
      const capital = parseFloat(config.tradingCapitalUsd) || 0;
      const exchange = (config.venue || 'binance').toLowerCase();
      const minCapital = EXCHANGE_MINIMUMS[exchange]?.minCapital || 10;
      
      if (capital < minCapital) {
        return {
          severity: SEVERITY.ERROR,
          field: 'tradingCapitalUsd',
          message: `Trading capital ($${capital}) is below minimum ($${minCapital})`,
          detail: `${exchange} requires at least $${minCapital} to place orders.`,
          suggestion: `Set trading capital to at least $${minCapital}`
        };
      }
      return null;
    }
  },
  
  {
    id: 'leverage_range',
    name: 'Leverage out of range',
    check: (config) => {
      const leverage = config.riskConfig?.maxLeverage || 1;
      const exchange = (config.venue || 'binance').toLowerCase();
      const maxLeverage = EXCHANGE_MINIMUMS[exchange]?.maxLeverage || 100;
      
      if (leverage < 1) {
        return {
          severity: SEVERITY.ERROR,
          field: 'maxLeverage',
          message: `Leverage (${leverage}x) must be at least 1x`,
          suggestion: 'Set leverage to 1x or higher'
        };
      }
      
      if (leverage > maxLeverage) {
        return {
          severity: SEVERITY.ERROR,
          field: 'maxLeverage',
          message: `Leverage (${leverage}x) exceeds ${exchange} maximum (${maxLeverage}x)`,
          suggestion: `Set leverage to ${maxLeverage}x or lower`
        };
      }
      return null;
    }
  },
  
  {
    id: 'no_symbols',
    name: 'No trading symbols selected',
    check: (config) => {
      const symbols = config.enabledSymbols || [];
      
      if (!symbols || symbols.length === 0) {
        return {
          severity: SEVERITY.ERROR,
          field: 'enabledSymbols',
          message: 'No trading symbols selected',
          detail: 'The bot needs at least one symbol to trade.',
          suggestion: 'Select at least one trading pair (e.g., BTC-USDT-SWAP)'
        };
      }
      return null;
    }
  },
  
  {
    id: 'position_size_too_small',
    name: 'Position size too small for exchange',
    check: (config) => {
      const capital = parseFloat(config.tradingCapitalUsd) || 0;
      const positionPct = normalizePercent(config.riskConfig?.positionSizePct, 0.10);
      const leverage = config.riskConfig?.maxLeverage || 1;
      const exchange = (config.venue || 'binance').toLowerCase();
      const minPosition = EXCHANGE_MINIMUMS[exchange]?.minPositionUsd || 5;
      
      // Margin available for position
      const marginAvailable = capital * positionPct;
      // Effective position size with leverage
      const effectivePositionSize = marginAvailable * leverage;
      
      if (effectivePositionSize < minPosition) {
        return {
          severity: SEVERITY.ERROR,
          field: 'positionSizePct',
          message: `Position size ($${effectivePositionSize.toFixed(2)}) is below ${exchange} minimum ($${minPosition})`,
          detail: `With $${capital} capital, ${formatPercent(positionPct)} position size, and ${leverage}x leverage, orders may be rejected.`,
          suggestion: `Increase capital, position size, or leverage so each trade is at least $${minPosition}`
        };
      }
      return null;
    }
  },
  
  {
    id: 'binance_minimum_notional',
    name: 'Binance minimum notional not met',
    check: (config) => {
      const capital = parseFloat(config.tradingCapitalUsd) || 0;
      const positionPct = normalizePercent(config.riskConfig?.positionSizePct, 0.10);
      const leverage = Math.max(1, config.riskConfig?.maxLeverage || 1);
      const symbols = config.enabledSymbols || [];
      
      // Margin available for position
      const marginAvailable = capital * positionPct;
      // Effective position size with leverage (notional value)
      const effectiveNotional = marginAvailable * leverage;
      
      // Binance enforces $100 minimum notional for ALL symbols
      const minNotional = BINANCE_MIN_NOTIONAL_USD;
      
      if (symbols.length > 0 && effectiveNotional < minNotional) {
        const minMarginRequired = minNotional / leverage;
        const minCapital = Math.ceil(minMarginRequired / positionPct);
        const minPositionPct = Math.ceil(minMarginRequired / capital * 100);
        
        return {
          severity: SEVERITY.ERROR,
          field: 'tradingCapitalUsd',
          message: `Position notional ($${effectiveNotional.toFixed(0)}) is below Binance minimum ($${minNotional})`,
          detail: `Binance requires at least $100 notional per order. With $${marginAvailable.toFixed(0)} margin and ${leverage}x leverage, your notional is only $${effectiveNotional.toFixed(0)}.`,
          suggestion: `Increase capital to at least $${minCapital}, or position size to ${minPositionPct}%, or use higher leverage.`
        };
      }
      return null;
    }
  },
  
  // ═══════════════════════════════════════════════════════════════
  // WARNINGS - Should review but won't block trading
  // ═══════════════════════════════════════════════════════════════
  
  {
    id: 'stop_loss_vs_take_profit',
    name: 'Stop loss larger than take profit',
    check: (config) => {
      const stopLoss = normalizePercent(config.executionConfig?.stopLossPct, 0.02);
      const takeProfit = normalizePercent(config.executionConfig?.takeProfitPct, 0.05);
      
      if (stopLoss >= takeProfit) {
        return {
          severity: SEVERITY.WARNING,
          field: 'stopLossPct',
          message: `Stop loss (${formatPercent(stopLoss)}) >= take profit (${formatPercent(takeProfit)})`,
          detail: 'Your risk/reward ratio is unfavorable. You\'ll need >50% win rate to be profitable.',
          suggestion: `Consider a smaller stop loss or larger take profit for better risk/reward`
        };
      }
      return null;
    }
  },
  
  {
    id: 'high_daily_loss_limit',
    name: 'High daily loss limit',
    check: (config) => {
      const maxDailyLoss = normalizePercent(config.riskConfig?.maxDailyLossPct, 0.05);
      
      if (maxDailyLoss > 0.10) {
        return {
          severity: SEVERITY.WARNING,
          field: 'maxDailyLossPct',
          message: `Daily loss limit (${formatPercent(maxDailyLoss)}) is very high`,
          detail: 'A daily loss of >10% can quickly deplete your account.',
          suggestion: 'Consider setting a more conservative daily loss limit (2-5%)'
        };
      }
      return null;
    }
  },
  
  {
    id: 'high_leverage_warning',
    name: 'High leverage warning',
    check: (config) => {
      const leverage = config.riskConfig?.maxLeverage || 1;
      
      if (leverage > 10) {
        return {
          severity: SEVERITY.WARNING,
          field: 'maxLeverage',
          message: `High leverage (${leverage}x) increases liquidation risk`,
          detail: 'With high leverage, small price movements can trigger liquidation.',
          suggestion: 'Consider using lower leverage (1-5x) for more safety'
        };
      }
      return null;
    }
  },
  
  {
    id: 'large_position_size',
    name: 'Large position size warning',
    check: (config) => {
      const positionSize = normalizePercent(config.riskConfig?.positionSizePct, 0.10);
      
      if (positionSize > 0.50) {
        return {
          severity: SEVERITY.WARNING,
          field: 'positionSizePct',
          message: `Large position size (${formatPercent(positionSize)}) concentrates risk`,
          detail: 'Putting >50% of your capital in a single trade is risky.',
          suggestion: 'Consider smaller position sizes (5-20%) for better diversification'
        };
      }
      return null;
    }
  },
  
  {
    id: 'too_many_symbols',
    name: 'Many symbols may dilute focus',
    check: (config) => {
      const symbols = config.enabledSymbols || [];
      
      if (symbols.length > 10) {
        return {
          severity: SEVERITY.INFO,
          field: 'enabledSymbols',
          message: `Trading ${symbols.length} symbols may dilute focus`,
          detail: 'More symbols means more opportunities but also more complexity.',
          suggestion: 'Consider focusing on 3-5 high-liquidity symbols'
        };
      }
      return null;
    }
  },
  
  {
    id: 'trailing_stop_vs_take_profit',
    name: 'Trailing stop may exit before take profit',
    check: (config) => {
      const trailingEnabled = config.executionConfig?.trailingStopEnabled;
      const trailingPct = normalizePercent(config.executionConfig?.trailingStopPct, 0.01);
      const takeProfit = normalizePercent(config.executionConfig?.takeProfitPct, 0.05);
      
      if (trailingEnabled && trailingPct < takeProfit * 0.5) {
        return {
          severity: SEVERITY.INFO,
          field: 'trailingStopPct',
          message: `Tight trailing stop (${formatPercent(trailingPct)}) may exit before take profit (${formatPercent(takeProfit)})`,
          detail: 'The trailing stop will likely trigger before reaching take profit on volatile moves.',
          suggestion: 'This can be intentional to lock in profits, but be aware of the trade-off'
        };
      }
      return null;
    }
  },
  
  // ═══════════════════════════════════════════════════════════════
  // PAPER TRADING SPECIFIC
  // ═══════════════════════════════════════════════════════════════
  
  {
    id: 'paper_trading_notice',
    name: 'Paper trading mode',
    check: (config) => {
      if (config.tradingMode === 'paper' || config.environment === 'paper') {
        return {
          severity: SEVERITY.INFO,
          field: 'tradingMode',
          message: 'Paper trading mode - no real money at risk',
          detail: 'Trades will be simulated. Switch to live mode when ready for real trading.'
        };
      }
      return null;
    }
  },
  
  {
    id: 'testnet_notice',
    name: 'Testnet mode',
    check: (config) => {
      if (config.isTestnet) {
        return {
          severity: SEVERITY.INFO,
          field: 'isTestnet',
          message: 'Testnet mode - using exchange testnet',
          detail: 'Orders will be placed on the exchange testnet with fake funds.'
        };
      }
      return null;
    }
  }
];

/**
 * Validate a bot configuration
 * @param {Object} config - Bot configuration object
 * @returns {Object} Validation result with errors, warnings, and info
 */
function validateConfig(config) {
  const results = {
    valid: true,
    errors: [],
    warnings: [],
    info: [],
    summary: ''
  };
  
  if (!config) {
    results.valid = false;
    results.errors.push({
      id: 'no_config',
      severity: SEVERITY.ERROR,
      message: 'No configuration provided',
      field: null
    });
    results.summary = '1 error: No configuration provided';
    return results;
  }
  
  // Run all validation rules
  for (const rule of validationRules) {
    try {
      const result = rule.check(config);
      if (result) {
        result.id = rule.id;
        result.ruleName = rule.name;
        
        switch (result.severity) {
          case SEVERITY.ERROR:
            results.errors.push(result);
            results.valid = false;
            break;
          case SEVERITY.WARNING:
            results.warnings.push(result);
            break;
          case SEVERITY.INFO:
            results.info.push(result);
            break;
        }
      }
    } catch (e) {
      console.error(`Validation rule ${rule.id} failed:`, e);
    }
  }
  
  // Generate summary
  const parts = [];
  if (results.errors.length > 0) {
    parts.push(`${results.errors.length} error${results.errors.length > 1 ? 's' : ''}`);
  }
  if (results.warnings.length > 0) {
    parts.push(`${results.warnings.length} warning${results.warnings.length > 1 ? 's' : ''}`);
  }
  if (parts.length === 0) {
    results.summary = 'Configuration valid';
  } else {
    results.summary = parts.join(', ');
  }
  
  return results;
}

/**
 * Validate and get a simple pass/fail with reason
 * @param {Object} config - Bot configuration
 * @returns {Object} { canTrade: boolean, reason: string }
 */
function canTrade(config) {
  const validation = validateConfig(config);
  
  if (validation.valid) {
    return {
      canTrade: true,
      reason: 'Configuration valid'
    };
  }
  
  return {
    canTrade: false,
    reason: validation.errors[0]?.message || 'Invalid configuration'
  };
}

/**
 * Get suggested fixes for common issues
 * @param {Object} config - Bot configuration  
 * @returns {Object} Suggested configuration changes
 */
function getSuggestedFixes(config) {
  const fixes = {};
  const validation = validateConfig(config);
  
  for (const error of validation.errors) {
    if (error.id === 'position_size_vs_symbol_exposure') {
      const rawPositionSize = config.riskConfig?.positionSizePct;
      const positionSize = normalizePercent(rawPositionSize, 0.25);
      fixes.maxExposurePerSymbolPct = preservePercentScale(rawPositionSize, positionSize);
    }
    if (error.id === 'total_exposure_overflow') {
      const rawPositionSize = config.riskConfig?.positionSizePct;
      const positionSize = normalizePercent(rawPositionSize, 0.10);
      const maxPositions = config.riskConfig?.maxPositions || 4;
      const totalExposure = positionSize * maxPositions;
      fixes.maxTotalExposurePct = preservePercentScale(rawPositionSize, totalExposure);
    }
  }
  
  return fixes;
}

export default {
  validateConfig,
  canTrade,
  getSuggestedFixes,
  SEVERITY,
  validationRules
};

export { validateConfig, canTrade, getSuggestedFixes, SEVERITY };
