/**
 * Types for Quant-Grade Trade History page
 */

// ═══════════════════════════════════════════════════════════════
// FILTER TYPES
// ═══════════════════════════════════════════════════════════════

export type TimeRange = '1D' | '7D' | '30D' | '90D' | 'YTD' | 'ALL' | 'CUSTOM';
export type Outcome = 'win' | 'loss' | 'flat' | 'all';
export type Side = 'long' | 'short' | 'all';
export type ColumnPreset = 'execution' | 'risk' | 'research' | 'all';
export type TradingSession = 'asia' | 'europe' | 'us' | 'all';

export interface CohortFilters {
  // Time
  timeRange: TimeRange;
  startDate?: string; // ISO date
  endDate?: string;   // ISO date
  
  // Identity
  symbols: string[];
  strategies: string[];
  profiles: string[];
  bots: string[];
  
  // Outcome
  outcome: Outcome;
  side: Side;
  
  // Min P&L filter
  minPnl?: number;
  maxPnl?: number;
}

export interface AdvancedFilters {
  // Execution Quality
  slippageMin?: number;   // bps
  slippageMax?: number;   // bps
  latencyMin?: number;    // ms
  latencyMax?: number;    // ms
  fillType?: 'maker' | 'taker' | 'all';
  
  // Risk
  exposureMin?: number;   // percent
  exposureMax?: number;   // percent
  leverageMin?: number;
  leverageMax?: number;
  riskGateResult?: 'passed' | 'blocked' | 'all';
  
  // Market Regime
  volBucket?: 'low' | 'medium' | 'high' | 'all';
  spreadBucket?: 'tight' | 'normal' | 'wide' | 'all';
  session?: TradingSession;
  
  // MAE/MFE
  maeMin?: number;  // bps
  maeMax?: number;  // bps
  mfeMin?: number;  // bps
  mfeMax?: number;  // bps
}

export interface SavedView {
  id: string;
  name: string;
  filters: CohortFilters;
  advancedFilters?: AdvancedFilters;
  columnPreset: ColumnPreset;
  createdAt: string;
  updatedAt: string;
  isDefault?: boolean;
}

// ═══════════════════════════════════════════════════════════════
// TRADE DATA TYPES
// ═══════════════════════════════════════════════════════════════

export interface QuantTrade {
  id: string;
  
  // Identity
  timestamp: number;
  symbol: string;
  side: 'long' | 'short' | 'buy' | 'sell';
  profileId?: string;
  profileName?: string;
  strategyId?: string;
  strategyName?: string;
  botId?: string;
  botName?: string;
  
  // Position
  quantity: number;
  notional: number;
  leverage: number;
  riskPercent?: number;
  
  // Entry/Exit
  holdTimeSeconds: number;
  entryPrice: number;
  exitPrice: number;
  entryTime: number;
  exitTime?: number;
  
  // P&L
  realizedPnl: number;
  pnlBps: number;
  fees: number;
  netPnl: number;
  rMultiple?: number;
  
  // MAE/MFE (Max Adverse/Favorable Excursion)
  mae?: number;  // dollar amount
  mfe?: number;  // dollar amount
  maeBps?: number;
  mfeBps?: number;
  
  // Execution
  slippageBps?: number;
  entrySlippageBps?: number;
  exitSlippageBps?: number;
  latencyMs?: number;
  liquidity?: 'maker' | 'taker' | 'mixed' | 'unknown';
  makerPercent?: number;
  fillsCount?: number;
  rejections?: number;
  entryFeeUsd?: number;
  exitFeeUsd?: number;
  totalFeesUsd?: number;
  spreadCostBps?: number;
  totalCostBps?: number;
  midAtSend?: number;
  expectedPriceAtSend?: number;
  sendTs?: number;
  ackTs?: number;
  firstFillTs?: number;
  finalFillTs?: number;
  postOnlyRejectCount?: number;
  cancelAfterTimeoutCount?: number;
  orderType?: string;
  postOnly?: boolean;
  
  // State
  decisionOutcome?: 'approved' | 'rejected';
  exitReason?: string;
  primaryReason?: string;
  incidentId?: string;
  
  // Trace
  decisionTraceId?: string;
  hasDecisionTrace?: boolean;
  
  // Tags
  tags?: string[];
  notes?: string;
}

// ═══════════════════════════════════════════════════════════════
// COHORT STATS
// ═══════════════════════════════════════════════════════════════

export interface CohortStats {
  // Counts
  totalTrades: number;
  winningTrades: number;
  losingTrades: number;
  flatTrades: number;
  
  // Win Rate
  winRate: number;
  
  // P&L
  grossPnl: number;
  totalFees: number;
  netPnl: number;
  avgPnl: number;
  medianPnl: number;
  
  // Risk-Adjusted
  avgR?: number;
  profitFactor: number;
  
  // Execution
  avgSlippageBps: number;
  avgLatencyMs: number;
  
  // Rejection
  rejectRate: number;
  
  // MAE/MFE
  avgMaeBps?: number;
  avgMfeBps?: number;
  
  // Best/Worst
  bestSymbol?: string;
  worstSymbol?: string;
  bestProfile?: string;
  worstProfile?: string;
  largestWin: number;
  largestLoss: number;
  
  // Distributions (for histograms)
  pnlDistribution: number[];
  holdTimeDistribution: number[];
  slippageDistribution: number[];
}

// ═══════════════════════════════════════════════════════════════
// DECISION TRACE TYPES
// ═══════════════════════════════════════════════════════════════

export interface DecisionTrace {
  id: string;
  tradeId: string;
  timestamp: number;
  symbol: string;
  
  // Pipeline
  stages: DecisionStage[];
  totalLatencyMs: number;
  outcome: 'approved' | 'rejected';
  
  // Result
  finalScore?: number;
  primaryReason?: string;
}

export interface AIPredictionTrace {
  matchedPrediction?: Record<string, unknown> | null;
  recentPredictions: Array<Record<string, unknown>>;
  botId?: string | null;
  systemOutcome?: string | null;
  systemReason?: string | null;
}

export interface DecisionStage {
  name: string;
  inputs: Record<string, unknown>;
  output: {
    score?: number;
    pass: boolean;
    reason?: string;
  };
  latencyMs: number;
  features?: Record<string, number>;
}

// ═══════════════════════════════════════════════════════════════
// INSPECTOR TYPES
// ═══════════════════════════════════════════════════════════════

export interface TradeInspectorData {
  trade: QuantTrade;
  decisionTrace?: DecisionTrace;
  aiTrace?: AIPredictionTrace | null;
  fills: TradeFill[];
  marketContext?: MarketContext;
  notes?: TradeNote[];
  relatedIncidents?: string[];
}

export interface TradeFill {
  id: string;
  timestamp: number;
  venueOrderId?: string;
  quantity: number;
  price: number;
  fee: number;
  liquidity: 'maker' | 'taker';
  slippageBps?: number;
}

export interface MarketContext {
  regime?: 'trending' | 'ranging' | 'volatile' | 'quiet';
  trend?: 'bullish' | 'bearish' | 'neutral';
  volatility?: 'low' | 'medium' | 'high';
  session?: TradingSession;
  spread?: number;
  volume24h?: number;
}

export interface TradeNote {
  id: string;
  content: string;
  createdAt: string;
  author?: string;
}

// ═══════════════════════════════════════════════════════════════
// TABLE COLUMN DEFINITIONS
// ═══════════════════════════════════════════════════════════════

export interface ColumnDef {
  id: string;
  header: string;
  category: 'identity' | 'position' | 'entryExit' | 'pnl' | 'execution' | 'state';
  width?: number;
  align?: 'left' | 'right' | 'center';
  pinned?: boolean;
  sortable?: boolean;
}

export const COLUMN_PRESETS: Record<ColumnPreset, string[]> = {
  execution: [
    'timestamp', 'symbol', 'side', 'netPnl', 'slippageBps', 'latencyMs', 
    'makerPercent', 'fillsCount', 'holdTime'
  ],
  risk: [
    'timestamp', 'symbol', 'side', 'netPnl', 'leverage', 'riskPercent',
    'mae', 'mfe', 'rMultiple', 'exitReason'
  ],
  research: [
    'timestamp', 'symbol', 'side', 'profile', 'strategy', 'netPnl',
    'decisionOutcome', 'primaryReason', 'hasTrace'
  ],
  all: [
    'timestamp', 'symbol', 'side', 'profile', 'quantity', 'notional',
    'leverage', 'holdTime', 'entryPrice', 'exitPrice', 'realizedPnl',
    'fees', 'netPnl', 'mae', 'mfe', 'slippageBps', 'latencyMs',
    'exitReason', 'hasTrace'
  ],
};

// ═══════════════════════════════════════════════════════════════
// HELPER / DEFAULT VALUES
// ═══════════════════════════════════════════════════════════════

export const DEFAULT_COHORT_FILTERS: CohortFilters = {
  timeRange: '7D',
  symbols: [],
  strategies: [],
  profiles: [],
  bots: [],
  outcome: 'all',
  side: 'all',
};

export const DEFAULT_ADVANCED_FILTERS: AdvancedFilters = {
  fillType: 'all',
  riskGateResult: 'all',
  volBucket: 'all',
  spreadBucket: 'all',
  session: 'all',
};

export const EMPTY_COHORT_STATS: CohortStats = {
  totalTrades: 0,
  winningTrades: 0,
  losingTrades: 0,
  flatTrades: 0,
  winRate: 0,
  grossPnl: 0,
  totalFees: 0,
  netPnl: 0,
  avgPnl: 0,
  medianPnl: 0,
  profitFactor: 0,
  avgSlippageBps: 0,
  avgLatencyMs: 0,
  rejectRate: 0,
  largestWin: 0,
  largestLoss: 0,
  pnlDistribution: [],
  holdTimeDistribution: [],
  slippageDistribution: [],
};
