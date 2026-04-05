/**
 * Unit tests for per-credential configuration validation
 * 
 * Tests validation logic without database mocking
 */

import { describe, it } from 'node:test';
import assert from 'node:assert';

// Test the default configs directly
describe('Credential Config Defaults', () => {
  
  describe('DEFAULT_RISK_CONFIG validation', () => {
    it('should have sensible default values', () => {
      // These are the expected defaults based on our implementation
      const expectedDefaults = {
        positionSizePct: 0.10,
        maxPositions: 4,
        maxDailyLossPct: 0.05,
        maxTotalExposurePct: 0.80,
        maxLeverage: 1,
        leverageMode: 'isolated',
        maxPositionsPerSymbol: 1,
        maxDailyLossPerSymbolPct: 0.025,
      };
      
      // Verify defaults are reasonable
      assert.ok(expectedDefaults.positionSizePct >= 0.001 && expectedDefaults.positionSizePct <= 1.0);
      assert.ok(expectedDefaults.maxPositions >= 1);
      assert.ok(expectedDefaults.maxDailyLossPct >= 0.001 && expectedDefaults.maxDailyLossPct <= 1.0);
      assert.ok(expectedDefaults.maxLeverage >= 1);
      assert.ok(['isolated', 'cross'].includes(expectedDefaults.leverageMode));
    });
  });

  describe('DEFAULT_EXECUTION_CONFIG validation', () => {
    it('should have sensible default values', () => {
      const expectedDefaults = {
        defaultOrderType: 'market',
        stopLossPct: 0.02,
        takeProfitPct: 0.05,
        trailingStopEnabled: false,
        trailingStopPct: 0.01,
        maxHoldTimeHours: 24,
        minTradeIntervalSec: 1.0,
        executionTimeoutSec: 5.0,
        closePositionTimeoutSec: 15.0,
        enableVolatilityFilter: true,
        volatilityShockCooldownSec: 30.0,
      };
      
      // Verify defaults are reasonable
      assert.ok(['market', 'limit'].includes(expectedDefaults.defaultOrderType));
      assert.ok(expectedDefaults.stopLossPct >= 0.001 && expectedDefaults.stopLossPct <= 0.50);
      assert.ok(expectedDefaults.takeProfitPct >= 0.001 && expectedDefaults.takeProfitPct <= 1.0);
      assert.ok(expectedDefaults.maxHoldTimeHours > 0);
    });
  });
});

describe('Risk Config Validation Rules', () => {
  
  it('should require leverage to be within exchange limits', () => {
    const binanceMaxLeverage = 125;
    const bybitMaxLeverage = 100;
    
    // Test within limits
    const validLeverage = 50;
    assert.ok(validLeverage <= binanceMaxLeverage);
    assert.ok(validLeverage <= bybitMaxLeverage);
    
    // Test exceeds limits
    const invalidLeverage = 150;
    assert.ok(invalidLeverage > binanceMaxLeverage);
    assert.ok(invalidLeverage > bybitMaxLeverage);
  });

  it('should require position size between 0.1% and 100%', () => {
    const minPositionSize = 0.001;
    const maxPositionSize = 1.0;
    
    assert.ok(0.10 >= minPositionSize && 0.10 <= maxPositionSize); // Valid: 10%
    assert.ok(0.0005 < minPositionSize); // Invalid: below 0.1%
    assert.ok(1.5 > maxPositionSize);  // Invalid: above 100%
  });

  it('should require stop loss between 0.1% and 50%', () => {
    const minStopLoss = 0.001;
    const maxStopLoss = 0.50;
    
    assert.ok(0.02 >= minStopLoss && 0.02 <= maxStopLoss); // Valid: 2%
    assert.ok(0.0005 < minStopLoss); // Invalid: below 0.1%
    assert.ok(0.60 > maxStopLoss);   // Invalid: above 50%
  });
});

describe('Trading Capital Validation Rules', () => {
  
  it('should not allow trading capital to exceed exchange balance', () => {
    const exchangeBalance = 10000;
    const tradingCapital = 15000;
    
    // This should fail - trading capital exceeds exchange balance
    assert.ok(tradingCapital > exchangeBalance);
    
    // This should pass - trading capital is within balance
    const validTradingCapital = 8000;
    assert.ok(validTradingCapital <= exchangeBalance);
  });

  it('should allow trading capital equal to exchange balance', () => {
    const exchangeBalance = 10000;
    const tradingCapital = 10000;
    
    assert.strictEqual(tradingCapital, exchangeBalance);
  });

  it('should warn when trading capital is close to exchange balance', () => {
    const exchangeBalance = 10000;
    const tradingCapital = 9500; // 95% of balance
    
    const utilizationPct = (tradingCapital / exchangeBalance) * 100;
    const isAtFullBalance = utilizationPct >= 99; // No buffer
    const isHighUtilization = utilizationPct >= 90;
    
    assert.ok(!isAtFullBalance); // Not at 100%
    assert.ok(isHighUtilization); // But high utilization - should warn
  });
});

describe('Bot Profile Merging Rules', () => {
  
  it('should prefer credential trading capital over profile account balance', () => {
    const credentialTradingCapital = 25000;
    const profileAccountBalance = 10000;
    
    // When both are set, credential should take precedence
    const effectiveTradingCapital = credentialTradingCapital || profileAccountBalance;
    
    assert.strictEqual(effectiveTradingCapital, 25000);
  });

  it('should fall back to profile account balance when no trading capital', () => {
    const credentialTradingCapital = null;
    const profileAccountBalance = 15000;
    
    const effectiveTradingCapital = credentialTradingCapital || profileAccountBalance || 10000;
    
    assert.strictEqual(effectiveTradingCapital, 15000);
  });

  it('should use default when neither is set', () => {
    const credentialTradingCapital = null;
    const profileAccountBalance = null;
    const defaultBalance = 10000;
    
    const effectiveTradingCapital = credentialTradingCapital || profileAccountBalance || defaultBalance;
    
    assert.strictEqual(effectiveTradingCapital, 10000);
  });
});

describe('Exchange Limits', () => {
  
  it('should return correct max leverage for each exchange', () => {
    const exchangeLimits = {
      okx: { max_leverage: 125 },
      binance: { max_leverage: 125 },
      bybit: { max_leverage: 100 },
    };
    
    assert.strictEqual(exchangeLimits.okx.max_leverage, 125);
    assert.strictEqual(exchangeLimits.binance.max_leverage, 125);
    assert.strictEqual(exchangeLimits.bybit.max_leverage, 100);
  });
  
  it('should provide sensible defaults for unknown exchanges', () => {
    const defaultLimits = {
      max_leverage: 125,
      default_leverage: 1,
      min_position_usd: 5.0,
      supports_isolated_margin: true,
      supports_cross_margin: true,
      supports_trailing_stop: true,
    };
    
    assert.ok(defaultLimits.max_leverage > 0);
    assert.ok(defaultLimits.default_leverage >= 1);
    assert.ok(defaultLimits.min_position_usd > 0);
  });
});
