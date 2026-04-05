/**
 * Integration tests for Reporting API endpoints
 */

import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import axios from 'axios';

const BASE_URL = 'http://localhost:3001/api/reporting';

describe('Reporting API Integration Tests', () => {
  let templateId;
  let reportId;
  let strategyName = `test-strategy-${Date.now()}`;

  before(async () => {
    // Wait a bit for server to be ready
    await new Promise(resolve => setTimeout(resolve, 1000));
  });

  describe('Report Templates', () => {
    it('should create a report template', async () => {
      const response = await axios.post(`${BASE_URL}/templates`, {
        name: 'Daily Performance Report',
        reportType: 'daily',
        description: 'Daily trading performance summary',
        config: {
          sections: ['pnl', 'trades', 'risk'],
          charts: ['equity_curve', 'drawdown'],
        },
        scheduleCron: '0 9 * * *', // 9 AM daily
        enabled: true,
        recipients: ['admin@example.com'],
      });

      assert.strictEqual(response.status, 201);
      assert.strictEqual(response.data.success, true);
      assert.ok(response.data.data.id);
      assert.strictEqual(response.data.data.name, 'Daily Performance Report');
      assert.strictEqual(response.data.data.report_type, 'daily');
      
      templateId = response.data.data.id;
    });

    it('should get report templates', async () => {
      const response = await axios.get(`${BASE_URL}/templates`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      assert.ok(response.data.data.length > 0);
    });

    it('should filter templates by type', async () => {
      const response = await axios.get(`${BASE_URL}/templates?reportType=daily`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      response.data.data.forEach(template => {
        assert.strictEqual(template.report_type, 'daily');
      });
    });
  });

  describe('Generated Reports', () => {
    it('should store a generated report', async () => {
      const periodStart = new Date();
      periodStart.setDate(periodStart.getDate() - 1);
      const periodEnd = new Date();

      const response = await axios.post(`${BASE_URL}/reports`, {
        templateId: templateId,
        reportType: 'daily',
        periodStart: periodStart.toISOString(),
        periodEnd: periodEnd.toISOString(),
        reportData: {
          totalPnl: 1234.56,
          totalTrades: 42,
          winRate: 65.5,
          sharpeRatio: 1.85,
        },
        status: 'completed',
        recipients: ['admin@example.com'],
      });

      assert.strictEqual(response.status, 201);
      assert.strictEqual(response.data.success, true);
      assert.ok(response.data.data.id);
      assert.strictEqual(response.data.data.report_type, 'daily');
      assert.strictEqual(response.data.data.status, 'completed');
      
      reportId = response.data.data.id;
    });

    it('should get generated reports', async () => {
      const response = await axios.get(`${BASE_URL}/reports`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      assert.ok(response.data.data.length > 0);
    });

    it('should filter reports by type', async () => {
      const response = await axios.get(`${BASE_URL}/reports?reportType=daily`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      response.data.data.forEach(report => {
        assert.strictEqual(report.report_type, 'daily');
      });
    });
  });

  describe('Strategy Portfolio', () => {
    it('should store strategy portfolio metrics', async () => {
      const response = await axios.post(`${BASE_URL}/portfolio/strategies`, {
        strategyName: strategyName,
        strategyFamily: 'scalper',
        calculationDate: new Date().toISOString().split('T')[0],
        totalPnl: 5000.00,
        realizedPnl: 4500.00,
        unrealizedPnl: 500.00,
        dailyReturn: 0.025,
        weeklyReturn: 0.15,
        monthlyReturn: 0.45,
        maxDrawdown: -0.08,
        sharpeRatio: 2.1,
        sortinoRatio: 2.5,
        totalTrades: 150,
        winningTrades: 95,
        losingTrades: 55,
        winRate: 63.33,
        avgWin: 100.00,
        avgLoss: -50.00,
        profitFactor: 2.0,
        currentExposure: 10000.00,
        maxExposure: 15000.00,
        exposurePct: 66.67,
        riskBudgetPct: 40.0,
        capitalAllocation: 100000.00,
      });

      assert.strictEqual(response.status, 201);
      assert.strictEqual(response.data.success, true);
      assert.ok(response.data.data.id);
      assert.strictEqual(response.data.data.strategy_name, strategyName);
      assert.strictEqual(Number(response.data.data.total_pnl), 5000.00);
    });

    it('should get strategy portfolio metrics', async () => {
      const response = await axios.get(`${BASE_URL}/portfolio/strategies`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      assert.ok(response.data.data.length > 0);
    });

    it('should filter strategies by name', async () => {
      const response = await axios.get(`${BASE_URL}/portfolio/strategies?strategyName=${strategyName}`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      response.data.data.forEach(strategy => {
        assert.strictEqual(strategy.strategy_name, strategyName);
      });
    });
  });

  describe('Strategy Correlations', () => {
    it('should store strategy correlation', async () => {
      const strategyB = `test-strategy-b-${Date.now()}`;
      
      const response = await axios.post(`${BASE_URL}/portfolio/correlations`, {
        strategyA: strategyName,
        strategyB: strategyB,
        calculationDate: new Date().toISOString().split('T')[0],
        correlationCoefficient: 0.35,
        correlationPeriodDays: 30,
        covariance: 0.0012,
        beta: 0.8,
      });

      assert.strictEqual(response.status, 201);
      assert.strictEqual(response.data.success, true);
      assert.ok(response.data.data.id);
      assert.strictEqual(response.data.data.strategy_a, strategyName);
      assert.strictEqual(response.data.data.strategy_b, strategyB);
      assert.strictEqual(Number(response.data.data.correlation_coefficient), 0.35);
    });

    it('should get strategy correlations', async () => {
      const response = await axios.get(`${BASE_URL}/portfolio/correlations`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
    });

    it('should filter correlations by strategy', async () => {
      const response = await axios.get(`${BASE_URL}/portfolio/correlations?strategyName=${strategyName}`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      response.data.data.forEach(corr => {
        assert.ok(
          corr.strategy_a === strategyName || corr.strategy_b === strategyName
        );
      });
    });
  });

  describe('Portfolio Summary', () => {
    it('should store portfolio summary', async () => {
      const response = await axios.post(`${BASE_URL}/portfolio/summary`, {
        calculationDate: new Date().toISOString().split('T')[0],
        totalPortfolioPnl: 15000.00,
        totalRealizedPnl: 14000.00,
        totalUnrealizedPnl: 1000.00,
        portfolioDailyReturn: 0.03,
        portfolioWeeklyReturn: 0.18,
        portfolioMonthlyReturn: 0.55,
        portfolioYtdReturn: 2.5,
        portfolioMaxDrawdown: -0.12,
        portfolioSharpeRatio: 1.95,
        portfolioSortinoRatio: 2.3,
        totalPortfolioTrades: 500,
        portfolioWinRate: 62.5,
        totalExposure: 50000.00,
        totalRiskBudget: 100000.00,
        riskBudgetUtilizationPct: 50.0,
        activeStrategiesCount: 3,
      });

      assert.strictEqual(response.status, 201);
      assert.strictEqual(response.data.success, true);
      assert.ok(response.data.data.id);
      assert.strictEqual(Number(response.data.data.total_portfolio_pnl), 15000.00);
    });

    it('should get portfolio summary', async () => {
      const response = await axios.get(`${BASE_URL}/portfolio/summary`);

      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data.success, true);
      assert.ok(Array.isArray(response.data.data));
      assert.ok(response.data.data.length > 0);
    });
  });

  describe('Error Handling', () => {
    it('should return 400 for missing required fields in template', async () => {
      try {
        await axios.post(`${BASE_URL}/templates`, {
          description: 'Missing name and reportType',
        });
        assert.fail('Should have thrown an error');
      } catch (error) {
        assert.strictEqual(error.response.status, 400);
        assert.ok(error.response.data.error.includes('Missing required fields'));
      }
    });

    it('should return 400 for missing required fields in report', async () => {
      try {
        await axios.post(`${BASE_URL}/reports`, {
          reportType: 'daily',
          // Missing periodStart and periodEnd
        });
        assert.fail('Should have thrown an error');
      } catch (error) {
        assert.strictEqual(error.response.status, 400);
        assert.ok(error.response.data.error.includes('Missing required fields'));
      }
    });

    it('should return 400 for missing required fields in strategy portfolio', async () => {
      try {
        await axios.post(`${BASE_URL}/portfolio/strategies`, {
          totalPnl: 1000,
          // Missing strategyName and calculationDate
        });
        assert.fail('Should have thrown an error');
      } catch (error) {
        assert.strictEqual(error.response.status, 400);
        assert.ok(error.response.data.error.includes('Missing required fields'));
      }
    });
  });
});




