/**
 * Types for the Microstructure Prediction Model Dashboard
 * 
 * These types match the API contracts defined in the plan.
 */

export type TimeWindow = "5m" | "15m" | "1h" | "24h";

export type Direction = "up" | "down" | "neutral";

export type BlockReason = 
  | "low_confidence" 
  | "low_move" 
  | "neutral" 
  | "stale_prediction" 
  | "stale_orderbook"
  | "direction_mismatch";

export interface ModelPulse {
  window: TimeWindow;
  updated_at: string; // ISO timestamp
  
  predictions_made: number;
  predictions_validated: number;
  validation_errors: number;
  neutral_predictions: number;
  
  accuracy_pct: number;
  rolling_accuracy_pct: number;
  avg_predicted_move_bps: number;
  avg_actual_move_bps: number;
  pending_predictions: number;

  freshness: {
    p50_prediction_age_ms: number;
    p95_prediction_age_ms: number;
    p50_orderbook_age_ms: number;
    p95_orderbook_age_ms: number;
  };

  usage: {
    eligible_rate_pct: number;
    used_rate_pct: number;
    blocked_by_model_count: number;
  };
}

export interface AccuracyPoint {
  ts: string; // ISO timestamp
  rolling_accuracy_pct: number;
  validated: number;
  made: number;
}

export interface SymbolScoreboardRow {
  symbol: string;

  directional_made: number;
  validated: number;
  validation_rate_pct: number;

  accuracy_pct: number;
  rolling_accuracy_pct: number;
  avg_predicted_move_bps: number;
  avg_actual_move_bps: number;

  bias: {
    up_pct: number;
    down_pct: number;
    neutral_pct: number;
  };

  confidence: {
    median: number;
    p95: number;
  };

  freshness: {
    p95_prediction_age_ms: number;
    stale_pred_skip_pct: number;
    stale_book_skip_pct: number;
  };
}

export interface ReliabilityBin {
  bin_start: number; // e.g. 0.60
  bin_end: number;   // e.g. 0.70
  n: number;
  observed_accuracy: number; // 0-1
}

export interface PredActualPoint {
  ts: string; // ISO timestamp
  symbol: string;
  direction: Direction;
  confidence: number; // 0-1
  predicted_move_bps: number; // signed
  actual_move_bps: number; // signed (3s forward)
}

export interface ErrorDistribution {
  mean_error_bps: number;
  mae_bps: number;
  median_abs_error_bps: number;
  histogram: Array<{ bucket_center_bps: number; count: number }>;
}

export interface FilterEffectiveness {
  window: TimeWindow;
  n_candidates: number;

  // 2x2 outcomes
  blocked_bad: number;   // good block ✅
  blocked_good: number;  // missed opportunity ❌
  allowed_good: number;  // ✅
  allowed_bad: number;   // ❌

  // derived KPIs
  block_precision_pct: number;
  miss_rate_pct: number;
  net_savings_bps: number;
}

export interface BlockedCandidateRow {
  ts: string; // ISO timestamp
  symbol: string;
  direction: Direction;
  confidence: number;
  predicted_move_bps: number;

  block_reason: BlockReason;

  actual_move_bps_3s?: number | null;
  would_have_been_edge_bps_3s?: number | null;

  replay_url: string;
}

export interface ThresholdSweepPoint {
  threshold_type: "min_confidence" | "min_predicted_move_bps";
  x: number; // threshold value
  block_precision_pct: number;
  miss_rate_pct: number;
  net_savings_bps: number;
  n_candidates: number;
}

// API Query Parameters
export interface ModelQueryParams {
  botId: string;
  window?: TimeWindow;
  symbol?: string;
}

export interface PredActualQueryParams extends ModelQueryParams {
  min_conf?: number;
  min_move?: number;
}

export interface BlockedCandidatesQueryParams extends ModelQueryParams {
  limit?: number;
}

