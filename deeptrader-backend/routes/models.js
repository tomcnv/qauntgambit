/**
 * Model API Routes
 * 
 * Endpoints for the microstructure prediction model dashboard.
 * All data is precomputed by Python and stored in Redis.
 */

import express from 'express';
import redisState from '../services/redisState.js';

const router = express.Router();

/**
 * Helper to get bot-scoped Redis key
 */
async function getBotModelData(botId, keySuffix) {
  if (!botId) {
    return null;
  }
  
  try {
    const data = await redisState.getBotJson(botId, keySuffix);
    return data;
  } catch (error) {
    console.error(`Error fetching ${keySuffix} for bot ${botId}:`, error.message);
    return null;
  }
}

/**
 * GET /api/models/orderbook/pulse
 * 
 * Real-time model health summary
 * Query params: botId, window (5m|15m|1h|24h), symbol
 */
router.get('/orderbook/pulse', async (req, res) => {
  try {
    const { botId, window = '15m', symbol = 'ALL' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const pulse = await getBotModelData(botId, 'ob_model_pulse');
    
    if (!pulse) {
      // Return empty pulse structure
      return res.json({
        window,
        updated_at: new Date().toISOString(),
        predictions_made: 0,
        predictions_validated: 0,
        validation_errors: 0,
        neutral_predictions: 0,
        accuracy_pct: 0,
        rolling_accuracy_pct: 0,
        avg_predicted_move_bps: 0,
        avg_actual_move_bps: 0,
        pending_predictions: 0,
        freshness: {
          p50_prediction_age_ms: 0,
          p95_prediction_age_ms: 0,
          p50_orderbook_age_ms: 0,
          p95_orderbook_age_ms: 0,
        },
        usage: {
          eligible_rate_pct: 0,
          used_rate_pct: 0,
          blocked_by_model_count: 0,
        },
      });
    }
    
    res.json(pulse);
  } catch (error) {
    console.error('Error in /orderbook/pulse:', error);
    res.status(500).json({ error: 'Failed to fetch model pulse' });
  }
});

/**
 * GET /api/models/orderbook/accuracy-series
 * 
 * Rolling accuracy over time for line chart
 * Query params: botId, window (5m|15m|1h|24h), symbol
 */
router.get('/orderbook/accuracy-series', async (req, res) => {
  try {
    const { botId, window = '15m', symbol = 'ALL' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const series = await getBotModelData(botId, 'ob_model_accuracy_series');
    
    res.json(series || []);
  } catch (error) {
    console.error('Error in /orderbook/accuracy-series:', error);
    res.status(500).json({ error: 'Failed to fetch accuracy series' });
  }
});

/**
 * GET /api/models/orderbook/scoreboard
 * 
 * Per-symbol performance breakdown
 * Query params: botId, window (5m|15m|1h|24h)
 */
router.get('/orderbook/scoreboard', async (req, res) => {
  try {
    const { botId, window = '15m' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const scoreboard = await getBotModelData(botId, 'ob_model_scoreboard');
    
    res.json(scoreboard || []);
  } catch (error) {
    console.error('Error in /orderbook/scoreboard:', error);
    res.status(500).json({ error: 'Failed to fetch scoreboard' });
  }
});

/**
 * GET /api/models/orderbook/reliability
 * 
 * Confidence calibration bins for reliability curve
 * Query params: botId, window (5m|15m|1h|24h), symbol, min_conf
 */
router.get('/orderbook/reliability', async (req, res) => {
  try {
    const { botId, window = '15m', symbol = 'ALL', min_conf = '0.5' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const reliability = await getBotModelData(botId, 'ob_model_reliability');
    
    // Default bins if no data
    if (!reliability || reliability.length === 0) {
      return res.json([
        { bin_start: 0.50, bin_end: 0.60, n: 0, observed_accuracy: 0 },
        { bin_start: 0.60, bin_end: 0.70, n: 0, observed_accuracy: 0 },
        { bin_start: 0.70, bin_end: 0.80, n: 0, observed_accuracy: 0 },
        { bin_start: 0.80, bin_end: 0.90, n: 0, observed_accuracy: 0 },
        { bin_start: 0.90, bin_end: 1.00, n: 0, observed_accuracy: 0 },
      ]);
    }
    
    res.json(reliability);
  } catch (error) {
    console.error('Error in /orderbook/reliability:', error);
    res.status(500).json({ error: 'Failed to fetch reliability bins' });
  }
});

/**
 * GET /api/models/orderbook/pred-vs-actual
 * 
 * Scatter plot data: predicted vs actual moves
 * Query params: botId, window, symbol, min_conf, min_move
 */
router.get('/orderbook/pred-vs-actual', async (req, res) => {
  try {
    const { botId, window = '15m', symbol, min_conf = '0.65', min_move = '3' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    let data = await getBotModelData(botId, 'ob_model_pred_actual');
    
    if (!data) {
      return res.json([]);
    }
    
    // Filter by symbol if specified
    if (symbol && symbol !== 'ALL') {
      data = data.filter(p => p.symbol === symbol);
    }
    
    // Filter by confidence
    const minConf = parseFloat(min_conf);
    if (!isNaN(minConf)) {
      data = data.filter(p => p.confidence >= minConf);
    }
    
    // Filter by predicted move
    const minMove = parseFloat(min_move);
    if (!isNaN(minMove)) {
      data = data.filter(p => Math.abs(p.predicted_move_bps) >= minMove);
    }
    
    // Limit to 2000 points
    res.json(data.slice(-2000));
  } catch (error) {
    console.error('Error in /orderbook/pred-vs-actual:', error);
    res.status(500).json({ error: 'Failed to fetch pred vs actual data' });
  }
});

/**
 * GET /api/models/orderbook/error-dist
 * 
 * Signed error distribution statistics
 * Query params: botId, window, symbol, min_conf
 */
router.get('/orderbook/error-dist', async (req, res) => {
  try {
    const { botId, window = '15m', symbol = 'ALL', min_conf = '0.65' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const errorDist = await getBotModelData(botId, 'ob_model_error_dist');
    
    if (!errorDist) {
      return res.json({
        mean_error_bps: 0,
        mae_bps: 0,
        median_abs_error_bps: 0,
        histogram: [],
      });
    }
    
    res.json(errorDist);
  } catch (error) {
    console.error('Error in /orderbook/error-dist:', error);
    res.status(500).json({ error: 'Failed to fetch error distribution' });
  }
});

/**
 * GET /api/models/orderbook/filter-effectiveness
 * 
 * Filter confusion matrix and derived metrics
 * Query params: botId, window, symbol
 */
router.get('/orderbook/filter-effectiveness', async (req, res) => {
  try {
    const { botId, window = '15m', symbol = 'ALL' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const effectiveness = await getBotModelData(botId, 'ob_model_filter');
    
    if (!effectiveness) {
      return res.json({
        window,
        n_candidates: 0,
        blocked_bad: 0,
        blocked_good: 0,
        allowed_good: 0,
        allowed_bad: 0,
        block_precision_pct: 0,
        miss_rate_pct: 0,
        net_savings_bps: 0,
      });
    }
    
    res.json(effectiveness);
  } catch (error) {
    console.error('Error in /orderbook/filter-effectiveness:', error);
    res.status(500).json({ error: 'Failed to fetch filter effectiveness' });
  }
});

/**
 * GET /api/models/orderbook/blocked-candidates
 * 
 * Recent blocked candidates for auditing
 * Query params: botId, window, symbol, limit
 */
router.get('/orderbook/blocked-candidates', async (req, res) => {
  try {
    const { botId, window = '15m', symbol, limit = '200' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    let candidates = await getBotModelData(botId, 'ob_model_blocked');
    
    if (!candidates) {
      return res.json([]);
    }
    
    // Filter by symbol if specified
    if (symbol && symbol !== 'ALL') {
      candidates = candidates.filter(c => c.symbol === symbol);
    }
    
    // Limit results
    const maxLimit = Math.min(parseInt(limit) || 200, 500);
    res.json(candidates.slice(-maxLimit));
  } catch (error) {
    console.error('Error in /orderbook/blocked-candidates:', error);
    res.status(500).json({ error: 'Failed to fetch blocked candidates' });
  }
});

/**
 * GET /api/models/orderbook/threshold-sweep
 * 
 * Hypothetical threshold analysis
 * Query params: botId, window, symbol
 */
router.get('/orderbook/threshold-sweep', async (req, res) => {
  try {
    const { botId, window = '24h', symbol = 'ALL' } = req.query;
    
    if (!botId) {
      return res.status(400).json({ error: 'botId is required' });
    }
    
    const sweep = await getBotModelData(botId, 'ob_model_sweep');
    
    res.json(sweep || []);
  } catch (error) {
    console.error('Error in /orderbook/threshold-sweep:', error);
    res.status(500).json({ error: 'Failed to fetch threshold sweep' });
  }
});

export default router;
