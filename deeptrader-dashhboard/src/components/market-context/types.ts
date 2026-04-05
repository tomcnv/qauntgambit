// ============================================================================
// SYMBOL ROW - Extended for Quant-Grade Dashboard
// ============================================================================

export type SymbolRow = {
  // Core identifiers
  symbol: string;
  pinned: boolean;
  instrumentType: 'futures' | 'perp' | 'spot';  // Inferred from symbol name
  
  // Spread metrics
  spread: number;
  spreadBaseline: number;
  spreadChange: number;
  spreadP50: number;
  spreadP95: number;
  
  // Volatility metrics
  vol: number;
  volBaseline: number;
  volChange: number;
  volPercentile: number;
  
  // Liquidity metrics
  depth: number;
  depthBaseline: number;
  liquidityScore: number;
  
  // Other market data
  churn: number;
  funding: number;
  fundingSpike: boolean;
  
  // Edge calculations
  expectedEdge: number;      // Model's estimated edge in bps
  headwind: number;          // spread + slip + fees in bps
  netEdge: number;           // expectedEdge - headwind
  
  // Regime & status
  regime: string | null;
  tradable: boolean;
  blockedReason: string | null;
  anomalyFlags: string[];
  allocationState: 'allowed' | 'throttled' | 'blocked';
  
  // Optional
  staleness?: number;
};

// ============================================================================
// GATE STATUS - For threshold vs actual display
// ============================================================================

export type GateStatus = {
  name: string;
  key: string;
  threshold: number | string;
  actual: number | string;
  unit: string;
  passed: boolean;
  severity: 'ok' | 'warning' | 'critical';
  blocking?: boolean;
  unknown?: boolean;
  description?: string;
};

// ============================================================================
// REGIME EVENT - For timeline display
// ============================================================================

export type RegimeEvent = {
  id: string;
  timestamp: number;
  time: string;
  type: 'spread' | 'volatility' | 'liquidity' | 'funding' | 'venue' | 'anomaly';
  title: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  symbols: string[];
  previousValue?: string;
  newValue?: string;
};

// ============================================================================
// REJECTION REASON - For why-not-trading breakdown
// ============================================================================

export type RejectionReason = {
  reason: string;
  count: number;
  percentage: number;
  stage?: string;
};

// ============================================================================
// TRADING STATUS - Aggregated decision stats
// ============================================================================

export type TradingStatus = {
  tradesToday: number;
  decisionsPerSecond: number;
  approvedCount: number;
  rejectedCount: number;
  passRate: number;
  topRejectionReasons: RejectionReason[];
  statusSummary: string;
  isTrading: boolean;
  blockedSymbolCount: number;
  totalSymbolCount: number;
};

// ============================================================================
// BOT FIT SCORE - Profile compatibility breakdown
// ============================================================================

export type BotFitScore = {
  overall: number;           // 0-100
  microstructureFit: number; // 0-100
  regimeFit: number;         // 0-100
  executionFit: number;      // 0-100
  riskFit: number;           // 0-100
  recommendations: string[];
  expectedConcentration?: number;
};

// ============================================================================
// VENUE HEALTH - Exchange/feed health metrics
// ============================================================================

export type VenueHealth = {
  status: 'healthy' | 'degraded' | 'down';
  latencyP50: number;
  latencyP95: number;
  rejectRate: number;
  websocketGaps: number;
  lastHeartbeatAge: number;
  feedHealth: 'ok' | 'stale' | 'disconnected';
};

// ============================================================================
// SAFETY METRICS - Risk budget usage
// ============================================================================

export type SafetyMetrics = {
  dailyLossUsed: number;      // USD amount of daily loss used
  dailyLossLimit: number;     // USD max daily loss from guardrails
  dailyLossRemaining: number; // USD remaining before hitting limit
  exposureUsed: number;       // USD current exposure
  exposureCap: number;        // USD max exposure from guardrails
  exposureUsedPct?: number;   // Percentage of exposure cap used
  killSwitchStatus: 'armed' | 'triggered' | 'disabled';
};

// ============================================================================
// MARKET FIT DATA - Combined data structure for the page
// ============================================================================

export type MarketFitData = {
  // Symbol data
  symbols: SymbolRow[];
  
  // Trading status
  tradingStatus: TradingStatus;
  
  // Gates
  gates: GateStatus[];
  
  // Regime events
  regimeEvents: RegimeEvent[];
  
  // Bot fit
  botFit: BotFitScore;
  
  // Venue health
  venueHealth: VenueHealth;
  
  // Safety
  safety: SafetyMetrics;
  
  // Bot info
  botName: string | null;
  botRunning: boolean;
  botRunningSince: string | null;
  profileName: string | null;
  profileVersion: string | null;
  
  // Regime summaries
  spreadRegime: 'normal' | 'widened' | 'extreme';
  volRegime: 'normal' | 'elevated' | 'spike';
  liqRegime: 'normal' | 'thin' | 'cliffy';
  
  // Loading states
  isLoading: boolean;
  error: Error | null;
};

// ============================================================================
// FILTER STATE
// ============================================================================

export type MarketContextFilters = {
  universe: 'futures' | 'perp' | 'spot';
  view: 'tradable' | 'blocked' | 'watchlist' | 'all';
  window: '5m' | '1h' | '6h' | '24h';
  anomaliesOnly: boolean;
  exchange: string;
};
