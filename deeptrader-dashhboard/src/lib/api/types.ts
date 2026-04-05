export type HealthStatus = "healthy" | "degraded" | "critical" | "unknown";

export interface ProcessSummary {
  running: boolean;
  uptime?: number;
  memory?: number;
  pid?: number;
  status?: string;
}

export interface DataCollectorStatus {
  name: string;
  running: boolean;
  pid?: number;
  status: string;
}

export interface MonitoringDashboardResponse {
  timestamp: string;
  uptime: number;
  nodejs: {
    server: ProcessSummary;
    dataCollectors: {
      total: number;
      running: number;
      healthy: boolean;
      details: DataCollectorStatus[];
    };
  };
  python: {
    workers: {
      total: number;
      running: number;
      healthy: boolean;
      details: { name: string; status: string }[];
    };
    controlManager: {
      running: boolean;
    };
  };
  redis: {
    connected: boolean;
    pubsub: {
      channels: string[];
      active: boolean;
    };
    streams: {
      channels: string[];
      active: boolean;
    };
  };
  health: HealthStatus | string;
}

export interface FastScalperMetrics {
  decisionsPerSec: number;
  positions: number;
  maxPositions: number;
  dailyPnl: number;
  completedTrades: number;
  webSocketStatus: string;
}

export interface SymbolWarmupStatus {
  amt: { status: string; progress: number } | null;
  htf: { status: string; progress: number; candles?: number } | null;
  ready: boolean;
  reasons?: string[];
}

export interface FastScalperStatusResponse {
  status: string;
  message?: string;
  uptime?: number;
  memory?: number;
  cpu?: number;
  restarts?: number;
  pid?: number;
  metrics?: FastScalperMetrics;
  symbols?: string[];
  environment?: string;
  timestamp: string;
  // System status
  serviceHealth?: {
    services: Record<string, boolean>;
    allReady: boolean;
    missing: string[];
  };
  websocket?: {
    publicConnected: boolean;
    privateConnected: boolean;
    status: string;
    messagesReceived: number;
  };
  warmup?: {
    allWarmedUp: boolean;
    symbols: Record<string, SymbolWarmupStatus>;
  };
  pendingOrders?: Array<{
    symbol: string;
    side: string;
    type: string;
    price: number;
    size: number;
    status: string;
    timestamp: number;
  }>;
}

export interface FastScalperRejectionRecord {
  timestamp: string;
  reason: string;
  symbol?: string;
  profile?: string;
  [key: string]: unknown;
}

export interface FastScalperRejectionsResponse {
  recent: FastScalperRejectionRecord[];
  counts: Record<string, number>;
  timestamp: string;
}

export interface AlertRecord {
  severity: "critical" | "error" | "warning";
  component: string;
  name: string;
  message: string;
  timestamp: string;
}

export interface MonitoringAlertsResponse {
  timestamp: string;
  alerts: AlertRecord[];
  warnings: AlertRecord[];
  total: number;
}

export interface BotWorkerStatus {
  status: string;
  pid?: number;
  uptime?: number;
}

export interface BotStatus {
  platform: {
    status: string;
    uptime: number;
  };
  trading: {
    isActive: boolean;
    mode: string | null;
    startTime: string | null;
    stopTime: string | null;
  };
  stats: {
    decisions: number;
    trades: number;
    wins: number;
    losses: number;
  };
  workers: {
    alwaysOn: Record<string, BotWorkerStatus>;
    trading: Record<string, BotWorkerStatus>;
  };
  dbBotStatus?: {
    id: string;
    state: string;
    name: string;
    environment: string;
  } | null;
}

// Legacy bot profile types (bot-config) used by older endpoints (keep a single unified shape)
export interface BotProfileVersion {
  id: string;
  bot_profile_id: string;
  version_number: number;
  status?: string;
  config_blob?: Record<string, any>;
  checksum?: string;
  notes?: string | null;
  created_by?: string | null;
  promoted_by?: string | null;
  created_at?: string;
  activated_at?: string | null;
  // camelCase variants for newer API responses
  botProfileId?: string;
  versionNumber?: number;
  config?: Record<string, unknown>;
  createdBy?: string | null;
  promotedBy?: string | null;
  createdAt?: string;
  activatedAt?: string | null;
}

export interface BotProfile {
  id: string;
  name: string;
  environment: string;
  engine_type?: string;
  engineType?: string;
  description?: string | null;
  status?: string;
  owner_id?: string | null;
  ownerId?: string | null;
  active_version_id?: string | null;
  activeVersionId?: string | null;
  activeVersion?: BotProfileVersion | null;
  metadata?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface TradeProfile {
  user_id: string;
  active_credential_id: string | null;
  active_exchange: string | null;
  trading_mode: "paper" | "live";
  token_lists: Record<string, string[]>;
  credential_exchange?: string | null;
  credential_label?: string | null;
  credential_status?: string | null;
  bot_status?: string | null;
}

export interface TradingPosition {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  stop_loss?: number;
  take_profit?: number;
  reference_price?: number | null;
  opened_at?: number | null;
  age_sec?: number | null;
  guard_status?: string | null;
  prediction_confidence?: number | null;
}

export interface PendingOrder {
  order_id: string;
  symbol: string;
  side: string;
  size: number;
  price: number;
  status: string;
  filled_size?: number;
  remaining_size?: number;
  created_at?: string;
}

export interface RecentTrade {
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  size: number;
  pnl: number;
  timestamp: number;
  profile?: string;
}

export interface TradingMetrics {
  daily_pnl?: number;
  decisions_per_sec?: number;
  open_positions?: number;
  trades_today?: number;
  account_balance?: number;
  total_exposure?: number;
  timestamp?: number;
  [key: string]: unknown;
}

export interface ExecutionStats {
  fill?: Record<string, unknown>;
  quality?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TradingSnapshot {
  positions: TradingPosition[];
  pendingOrders: PendingOrder[];
  metrics: TradingMetrics;
  execution: ExecutionStats;
  risk: Record<string, unknown>;
  exchangeStatus: Record<string, unknown>;
  performance: Record<string, unknown>;
  recentTrades: RecentTrade[];
  updatedAt: number;
  strategies?: Array<{
    id: string;
    name: string;
    status: string;
    pnl?: number;
    trades?: number;
    winRate?: number;
  }>;
}

export type StageRejectionSummary = Record<string, Record<string, number>>;

export interface FeatureHealthEntry {
  status?: string;
  last_profile?: string;
  last_reason?: string;
  consecutive_failures?: number;
  consecutive_successes?: number;
  regime?: {
    trend?: string;
    volatility?: string;
    value_location?: string;
    session?: string;
    risk_mode?: string;
  };
  [key: string]: unknown;
}

export type FeatureHealthSnapshot = Record<string, FeatureHealthEntry>;

export interface ComponentDiagnosticEntry {
  call_count?: number;
  error_count?: number;
  last_error?: string | null;
  timestamp?: number;
}

export type ComponentDiagnostics = Record<string, ComponentDiagnosticEntry>;

export interface AllocatorPositionScore {
  symbol: string;
  side: string;
  score: number;
  momentum_score?: number;
  regime_score?: number;
  profile_score?: number;
  age_sec?: number;
  unrealized_pnl?: number;
  profile_id?: string;
}

export interface AllocatorSnapshot {
  enabled?: boolean;
  stats?: Record<string, number>;
  metrics?: Record<string, number>;
  position_scores?: AllocatorPositionScore[];
  config?: Record<string, number | string>;
  last_decision?: Record<string, unknown>;
  timestamp?: number;
}

export interface DecisionTrace {
  symbol: string;
  timestamp: number;
  stages_executed?: string[];
  stage_timings?: Record<string, number>;
  stage_results?: Record<string, string>;
  rejection_stage?: string | null;
  rejection_reason?: string | null;
  final_result?: string;
  profile_id?: string | null;
  signal_side?: string | null;
  signal_confidence?: number | null;
  total_latency_ms?: number;
  [key: string]: unknown;
}

export interface SignalLabSnapshot {
  stageRejections: StageRejectionSummary;
  featureHealth: FeatureHealthSnapshot;
  componentDiagnostics: ComponentDiagnostics;
  allocator: AllocatorSnapshot;
  bladeStatus: Record<string, unknown>;
  bladeSignals: Record<string, unknown>;
  bladeMetrics: Record<string, unknown>;
  eventBus: Record<string, unknown>;
  recentDecisions: DecisionTrace[];
  updatedAt: number;
}

export interface ServiceHealthSnapshot {
  services: Record<string, boolean>;
  missing: string[];
  all_ready: boolean;
  timestamp: number;
}

export interface ResourceUsageSnapshot {
  process_cpu_percent?: number;
  process_memory_mb?: number;
  system_cpu_percent?: number;
  system_memory_percent?: number;
  system_memory_used_gb?: number;
  system_memory_total_gb?: number;
  timestamp?: number;
  [key: string]: unknown;
}

export interface ComponentDiagnosticsSnapshot {
  [component: string]: {
    call_count?: number;
    error_count?: number;
    last_error?: string | null;
    timestamp?: number;
  };
}

export interface HealthSnapshot {
  serviceHealth: ServiceHealthSnapshot | null;
  resourceUsage: ResourceUsageSnapshot | null;
  componentDiagnostics: ComponentDiagnosticsSnapshot | null;
  botStatus: BotStatus;
  fastScalper: FastScalperStatusResponse;
  updatedAt: number;
}

export interface FastScalperLogsResponse {
  logs: string[];
  timestamp: string;
}

// (Removed duplicate definitions; unified above)

export interface BotProfilesResponse {
  bots: BotProfile[];
}

export interface BotProfileDetailResponse {
  bot: BotProfile;
  versions: BotProfileVersion[];
}

export interface ActivateBotVersionResponse {
  message: string;
  bot: BotProfile;
  version: BotProfileVersion;
}

export interface CandlestickData {
  time: number; // Unix timestamp in seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface CandlestickResponse {
  symbol: string;
  timeframe: string;
  candles: CandlestickData[];
  count: number;
  updatedAt: number;
}

export interface DrawdownDataPoint {
  time: string;
  hour: string;
  equity: number;
  drawdown: number;
  peak: number;
}

export interface DrawdownResponse {
  drawdown: DrawdownDataPoint[];
  currentDrawdown: number;
  maxDrawdown: number;
  accountBalance: number;
  count: number;
  updatedAt: number;
}

export interface StrategyParameter {
  key: string;
  value: any;
  description?: string;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  category: string;
  defaultParams: Record<string, any>;
  paramDescriptions: Record<string, string>;
  inUse?: Array<{
    profileId: string;
    profileName: string;
    environment: string;
  }>;
  inUseCount?: number;
}

export interface StrategiesResponse {
  strategies: Strategy[];
}

export interface StrategyResponse {
  strategy: Strategy;
}

export interface SignalConfig {
  // Signal Generation
  minConfirmations: number;
  minRiskReward: number;
  
  // Cooldown Settings
  standardCooldownSec: number;
  lossCooldownSec: number;
  chopCooldownSec: number;
  
  // User Filters
  minConfidenceThreshold: number;
  minDataCompleteness: number;
  requireDataQuality: boolean;
  
  // Stage Configuration
  stages: {
    profileRouting?: { enabled: boolean };
    signalGeneration?: { enabled: boolean; minConfirmations?: number; minRiskReward?: number };
    orderbookPrediction?: { enabled: boolean; minConfidence?: number };
    riskValidation?: { enabled: boolean };
    positionSizing?: { enabled: boolean };
  };
  
  // Rejection Thresholds
  maxRejectionsPerSymbol?: number;
  maxRejectionsPerStage?: number;
}

export interface SignalConfigResponse {
  config: SignalConfig;
}

export interface AllocatorConfig {
  // Preemption thresholds
  scoreUpgradeFactor: number;
  minScoreToPreempt: number;
  
  // Guardrails
  minHoldTimeSec: number;
  maxPreemptionsPerSymbolPerMin: number;
  maxPreemptionsPerMin: number;
  staleSlotAgeSec: number;
  staleSlotMomentumThreshold: number;
  staleSlotMinScoreDelta: number;
  staleSlotUpgradeFactor: number;
  staleSlotAllowNegativePnl: boolean;
  
  // Transaction cost awareness
  requirePositiveExpectedGain: boolean;
  minExpectedGainUsd: number;
  expectedGainMultiplier: number;
  
  // Feature flag
  enabled: boolean;
}

export interface AllocatorConfigResponse {
  config: AllocatorConfig;
}

export interface MarketContext {
  symbol: string;
  timestamp: number;
  trend_bias?: string; // 'long', 'short', 'neutral'
  trend_confidence?: number;
  trend_strength?: number;
  volatility_regime?: string; // 'high', 'normal', 'low'
  volatility_percentile?: number;
  atr_ratio?: number;
  liquidity_regime?: string; // 'deep', 'normal', 'thin'
  bid_depth_usd?: number;
  ask_depth_usd?: number;
  spread_bps?: number;
  orderflow_imbalance?: number;
  orderflow_confidence?: number;
  predicted_direction?: string;
  market_regime?: string; // 'range', 'breakout', 'squeeze', 'chop'
  regime_confidence?: number;
}

export interface ContextCacheHealth {
  age_ms: number;
  stale: boolean;
  timestamp: number;
}

export interface MarketContextResponse {
  contexts: Record<string, MarketContext>;
  featureHealth: FeatureHealthSnapshot;
  cacheHealth: Record<string, ContextCacheHealth>;
  updatedAt: number;
}

// Research & Backtesting Types
export interface BacktestRun {
  id: string;
  user_id: string;
  strategy_id: string;
  symbol: string;
  exchange: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  commission_per_trade: number;
  slippage_model: string;
  slippage_bps: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  total_return_percent?: number;
  sharpe_ratio?: number;
  max_drawdown_percent?: number;
  win_rate?: number;
  total_trades?: number;
  profit_factor?: number;
  created_at: string;
  completed_at?: string;
  error_message?: string;
}

export interface BacktestTrade {
  id: string;
  backtest_run_id: string;
  symbol: string;
  side: 'buy' | 'sell';
  entry_price: number;
  exit_price?: number;
  size: number;
  entry_time: string;
  exit_time?: string;
  pnl?: number;
  pnl_percent?: number;
  commission: number;
  slippage: number;
  duration_seconds?: number;
  exit_reason?: string;
}

export interface EquityCurvePoint {
  time: string;
  value: number;
}

/**
 * Breakdown of rejection reasons by category.
 * Feature: backtest-diagnostics
 * Validates: Requirements 1.2, 2.1
 */
export interface RejectionBreakdown {
  spread_too_wide: number;
  depth_too_thin: number;
  snapshot_stale: number;
  vol_shock: number;
}

/**
 * Execution diagnostics for understanding backtest behavior.
 * Feature: backtest-diagnostics
 * Validates: Requirements 2.1, 2.2
 */
export interface ExecutionDiagnostics {
  // Snapshot processing
  total_snapshots: number;
  snapshots_processed: number;
  snapshots_skipped: number;
  
  // Global gate rejections (safety filters)
  global_gate_rejections: number;
  rejection_breakdown: RejectionBreakdown;
  
  // Profile and signal stats
  profiles_selected: number;
  signals_generated: number;
  cooldown_rejections: number;
  
  // Derived summary
  summary: string;
  primary_issue?: string;
  suggestions: string[];
}

export interface BacktestDetailResponse {
  backtest: BacktestRun;
  trades: BacktestTrade[];
  equityCurve: EquityCurvePoint[];
  metrics?: BacktestMetrics;
  execution_diagnostics?: ExecutionDiagnostics;
}

export interface BacktestMetrics {
  realized_pnl?: number;
  total_fees?: number;
  total_trades?: number;
  win_rate?: number;
  max_drawdown_pct?: number;
  avg_slippage_bps?: number;
  total_return_pct?: number;
  profit_factor?: number;
  avg_trade_pnl?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  trades_per_day?: number;
  fee_drag_pct?: number;
  slippage_drag_pct?: number;
  gross_profit?: number;
  gross_loss?: number;
  avg_win?: number;
  avg_loss?: number;
  largest_win?: number;
  largest_loss?: number;
  winning_trades?: number;
  losing_trades?: number;
}

export interface BacktestsResponse {
  backtests: BacktestRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface Dataset {
  symbol: string;
  earliestDate: string;
  latestDate: string;
  candleCount: number;
  availableDays: number;
}

export interface DatasetsResponse {
  datasets: Dataset[];
}

// Chessboard Profile Specifications
export interface ProfileConditions {
  min_trend_strength?: number;
  max_trend_strength?: number;
  required_trend?: string;
  min_volatility?: number;
  max_volatility?: number;
  required_volatility?: string;
  required_value_location?: string;
  min_distance_from_vah?: number;
  min_distance_from_val?: number;
  min_distance_from_poc?: number;
  required_session?: string;
  allowed_sessions?: string[];
  required_risk_mode?: string;
  min_spread?: number;
  max_spread?: number;
  min_trades_per_second?: number;
  min_orderbook_depth?: number;
  min_rotation_factor?: number;
  max_rotation_factor?: number;
}

export interface ProfileRiskParameters {
  risk_per_trade_pct: number;
  max_leverage: number;
  max_positions_per_symbol: number;
  max_total_positions: number;
  stop_loss_pct: number;
  take_profit_pct?: number;
  sl_tp_policy: string;
  trailing_stop_trigger_pct?: number;
  trailing_stop_distance_pct?: number;
  adaptive_sl_use_atr: boolean;
  adaptive_sl_atr_multiplier: number;
  adaptive_tp_use_value_area: boolean;
  max_hold_time_seconds?: number;
  min_hold_time_seconds?: number;
  daily_risk_budget_usd?: number;
  max_drawdown_pct?: number;
}

export interface ProfileLifecycle {
  warmup_duration_seconds: number;
  warmup_data_points_required: number;
  cooldown_duration_seconds: number;
  cooldown_close_positions: boolean;
  disable_after_consecutive_losses?: number;
  disable_after_drawdown_pct?: number;
  disable_after_error_count?: number;
  reenable_after_seconds?: number;
  reenable_requires_manual: boolean;
}

export interface ChessboardProfileSpec {
  id: string;
  name: string;
  description: string;
  version: string;
  conditions: ProfileConditions;
  risk: ProfileRiskParameters;
  lifecycle: ProfileLifecycle;
  strategy_ids: string[];
  strategy_params: Record<string, Record<string, any>>;
  min_win_rate: number;
  min_profit_factor: number;
  created_at: string;
  updated_at: string;
  author: string;
  tags: string[];
}

export interface ProfileSpecsResponse {
  timestamp: number;
  specs: ChessboardProfileSpec[];
  message?: string;
}

// Profile Routing Metrics (runtime data from bot)
export interface ProfileInstance {
  profile_id: string;
  symbol: string;
  state: 'active' | 'warming' | 'cooling' | 'disabled' | 'error';
  trades_count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  consecutive_losses: number;
  max_drawdown: number;
  error_count: number;
  updated_at: string;
}

export interface ProfileMetricsResponse {
  timestamp: number;
  total_profiles: number;
  total_instances: number;
  active_instances: number;
  warming_instances: number;
  cooling_instances: number;
  disabled_instances: number;
  error_instances: number;
  instances: ProfileInstance[];
  message?: string;
}

// Profile Router Metrics (selection & rejection data)
export interface ProfileRejection {
  profile_id: string;
  reasons: string[];
}

export interface LiveProfileSelection {
  profile_id: string;
  symbol: string;
  score: number;
  confidence: number;
  timestamp: number;
}

export interface ProfileScoreEntry {
  profile_id: string;
  score: number;
  confidence: number;
  adjusted_score?: number;
  data_quality_score?: number;
  risk_bias_multiplier?: number;
  reasons?: string[];
  eligible?: boolean;
  eligibility_reasons?: string[];
}

export interface ProfileRouterResponse {
  timestamp: number;
  total_trades: number;
  total_wins: number;
  overall_win_rate: number;
  total_pnl: number;
  avg_pnl_per_trade: number;
  active_profiles: number;
  registered_profiles: number;
  ml_enabled: boolean;
  top_profiles: Array<{
    profile_id: string;
    trades: number;
    win_rate: number;
    avg_pnl: number;
    total_pnl: number;
    symbols: string[];
  }>;
  live_top_profiles: LiveProfileSelection[];
  selection_history: Record<string, Array<{
    timestamp: number;
    profile_id: string;
    score: number;
    confidence: number;
  }>>;
  rejection_summary: Record<string, ProfileRejection[]>;
  top_rejection_reasons: Array<[string, number]>;
  symbol?: string;
  risk_mode?: string;
  selected_profile_id?: string | null;
  last_scores?: ProfileScoreEntry[];
  message?: string;
}

// Trade Cost Analysis (TCA) Types
export interface TradeCost {
  id: string;
  tradeId: string;
  symbol: string;
  profileId?: string;
  executionPrice: number;
  decisionMidPrice: number;
  slippageBps: number;
  fees: number;
  fundingCost: number;
  totalCost: number;
  orderSize?: number;
  side?: "long" | "short";
  timestamp: string;
}

export interface TCAAnalysisItem {
  symbol: string;
  profile_id?: string;
  total_trades: number;
  total_volume: number;
  avg_slippage_bps: number;
  avg_fees: number;
  avg_funding_cost: number;
  total_cost: number;
  avg_cost_pct: number;
}

export interface TCAAnalysisResponse {
  success: boolean;
  data: TCAAnalysisItem[];
  filters: {
    symbol?: string;
    profileId?: string;
    startDate?: string;
    endDate?: string;
    periodType?: string;
  };
}

export interface CapacityCurvePoint {
  notionalBucket: string;
  notionalMin: number;
  notionalMax?: number;
  avgSlippageBps: number;
  avgFees: number;
  tradeCount: number;
  totalVolume: number;
}

export interface CapacityCurveResponse {
  success: boolean;
  profileId: string;
  curve: CapacityCurvePoint[];
}

export interface TradeCostResponse {
  success: boolean;
  cost?: TradeCost;
  message?: string;
}

export interface CreateBacktestRequest {
  name?: string;
  strategy_id: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
  /** If true, bypass data validation thresholds (e.g., gaps in data) */
  force_run?: boolean;
  config?: {
    /** Maker fee in basis points (e.g., 2 = 0.02%) */
    maker_fee_bps?: number;
    /** Taker fee in basis points (e.g., 5.5 = 0.055%) */
    taker_fee_bps?: number;
    /** Slippage model: 'none', 'fixed', or 'realistic' */
    slippage_model?: string;
    /** Slippage in basis points */
    slippage_bps?: number;
    /** @deprecated Use maker_fee_bps and taker_fee_bps instead */
    commission_per_trade?: number;
    [key: string]: any;
  };
}

export interface BacktestPreflightResponse {
  ok: boolean;
  symbol_requested: string;
  symbol_candidates: string[];
  requested_start: string;
  requested_end: string;
  decision_events_count: number;
  market_candles_count: number;
  decision_events_range: {
    start?: string | null;
    end?: string | null;
  };
  market_candles_range: {
    start?: string | null;
    end?: string | null;
  };
  require_decision_events: boolean;
  message: string;
}

// Risk Metrics (VaR/ES) Types
export interface VaRCalculation {
  id: string;
  portfolio_id?: string;
  symbol?: string;
  profile_id?: string;
  method: 'historical' | 'monte_carlo' | 'parametric';
  confidence_level: number;
  time_horizon_days: number;
  var_value: number;
  expected_shortfall: number;
  calculated_at: string;
  metadata?: Record<string, any>;
}

export interface VaRCalculationsResponse {
  success: boolean;
  data: VaRCalculation[];
}

export interface CalculateVaRRequest {
  portfolioId?: string;
  symbol?: string;
  profileId?: string;
  method: 'historical' | 'monte_carlo';
  confidenceLevel?: number;
  timeHorizonDays?: number;
  lookbackDays?: number;
  numSimulations?: number;
}

export interface CalculateVaRResponse {
  success: boolean;
  var: number;
  expectedShortfall: number;
  method: string;
  confidenceLevel: number;
  timeHorizonDays: number;
}

export interface ScenarioTest {
  id: string;
  scenario_name: string;
  scenario_type: string;
  shock_params: Record<string, any>;
  portfolio_pnl: number;
  max_drawdown: number;
  affected_positions: number;
  created_at: string;
  scenario_params?: Record<string, any>;
}

export interface ScenarioTestRequest {
  scenarioName: string;
  scenarioType: 'price_shock' | 'liquidity_shock' | 'volatility_shock' | 'correlation_breakdown';
  shockParams: Record<string, any>;
}

export interface ScenarioTestResponse {
  success: boolean;
  scenario: ScenarioTest;
}

export interface ScenarioResultsResponse {
  success: boolean;
  data: ScenarioTest[];
}

// Component VaR
export interface ComponentVaR {
  symbol: string;
  direction: string;
  var_value: number;
  pct_of_total: number;
  notional: number;
}

export interface ComponentVaRResponse {
  success: boolean;
  data: ComponentVaR[];
  totalVar: number;
}

export interface ScenarioFactorImpact {
  name: string;
  impact: number;
  cumulative: number;
}

export interface ScenarioFactorResponse {
  success: boolean;
  scenario: ScenarioTest | null;
  factors: ScenarioFactorImpact[];
}

// Extended scenario detail when we add per-position impacts
export interface ScenarioPositionImpact {
  symbol: string;
  side?: string;
  size?: number;
  entry_price?: number;
  pnl?: number;
  pnl_pct?: number;
}

export interface ScenarioDetailResponse {
  success: boolean;
  scenario: ScenarioTest | null;
  factors: ScenarioFactorImpact[];
  positions?: ScenarioPositionImpact[];
}

export interface CorrelationRecord {
  id?: string;
  strategy_a: string;
  strategy_b: string;
  correlation_coefficient: number;
  correlation_period_days?: number;
  calculation_date?: string;
}

export interface CorrelationsResponse {
  success: boolean;
  data: CorrelationRecord[];
}

export interface RiskLimitsResponse {
  success: boolean;
  policy: Record<string, any>;
}

// Promotion Workflow Types
export interface Promotion {
  id: string;
  promotion_type: 'research_to_paper' | 'paper_to_live' | 'rollback';
  source_environment: string;
  target_environment: string;
  bot_profile_id: string;
  bot_version_id: string;
  status: 'pending' | 'approved' | 'rejected' | 'completed' | 'cancelled';
  requested_by: string;
  approved_by?: string;
  rejected_by?: string;
  backtest_summary?: Record<string, any>;
  paper_trading_stats?: Record<string, any>;
  requires_approval: boolean;
  risk_assessment?: Record<string, any>;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

export interface PromotionsResponse {
  success: boolean;
  data: Promotion[];
}

export interface CreatePromotionRequest {
  promotionType: 'research_to_paper' | 'paper_to_live' | 'rollback';
  sourceEnvironment: string;
  targetEnvironment: string;
  botProfileId: string;
  botVersionId: string;
  backtestSummary?: Record<string, any>;
  paperTradingStats?: Record<string, any>;
  requiresApproval?: boolean;
}

export interface ConfigDiff {
  added: Record<string, any>;
  removed: Record<string, any>;
  modified: Record<string, { before: any; after: any }>;
}

export interface ConfigDiffResponse {
  success: boolean;
  diff: ConfigDiff;
}

// Audit Log Types
export interface AuditLogEntry {
  id: string;
  user_id?: string;
  action_type: string;
  action_category: string;
  resource_type?: string;
  resource_id?: string;
  action_description: string;
  action_details?: Record<string, any>;
  before_state?: Record<string, any>;
  after_state?: Record<string, any>;
  ip_address?: string;
  user_agent?: string;
  severity: 'info' | 'warning' | 'error' | 'critical';
  created_at: string;
}

export interface AuditLogResponse {
  success: boolean;
  data: AuditLogEntry[];
  count: number;
  limit: number;
  offset: number;
}

export interface AuditDecisionTrace {
  id: string;
  trade_id: string;
  symbol: string;
  timestamp: string;
  decision_type: 'entry' | 'exit' | 'reject' | 'adjust';
  decision_outcome: 'approved' | 'rejected' | 'adjusted';
  signal_data?: Record<string, any>;
  market_context?: Record<string, any>;
  stage_results: Record<string, any>;
  rejection_reasons?: Record<string, any>;
  final_decision?: Record<string, any>;
  execution_result?: Record<string, any>;
  trace_metadata?: Record<string, any>;
  created_at: string;
}

export interface DecisionTracesResponse {
  success: boolean;
  data: AuditDecisionTrace[];
  count: number;
  limit: number;
  offset: number;
}

export interface ExportAuditLogRequest {
  exportType?: 'json' | 'csv';
  format?: 'json' | 'csv';
  startDate?: string;
  endDate?: string;
  actionType?: string;
  actionCategory?: string;
  resourceType?: string;
  severity?: string;
}

export interface ExportAuditLogResponse {
  success: boolean;
  message: string;
  export: {
    exportId: string;
    filePath: string;
    fileName: string;
    recordCount: number;
    fileSize: number;
  };
}

// Replay & Incident Analysis Types
export interface ReplaySnapshot {
  id: string;
  symbol: string;
  timestamp: string;
  market_data: {
    candles?: Array<{ time: number; open: number; high: number; low: number; close: number; volume?: number }>;
    orderbook?: { bids: number[][]; asks: number[][] };
    trades?: Array<{ time: number; price: number; size: number; side: string }>;
  };
  decision_context: {
    signal?: { side: string; strength: number };
    profile?: string;
    allocator?: { score: number };
    [key: string]: any;
  };
  position_state?: {
    size: number;
    side: string | null;
    entry_price?: number;
    [key: string]: any;
  };
  pnl_state?: {
    unrealized: number;
    realized: number;
    [key: string]: any;
  };
  snapshot_type: string;
  incident_id?: string;
  created_at: string;
}

export interface Incident {
  id: string;
  incident_type: 'large_loss' | 'unexpected_behavior' | 'data_issue' | 'system_error';
  severity: 'low' | 'medium' | 'high' | 'critical';
  start_time: string;
  end_time: string;
  affected_symbols: string[];
  title: string;
  description?: string;
  pnl_impact?: number;
  positions_affected?: number;
  trades_affected?: number;
  status: 'open' | 'investigating' | 'resolved' | 'closed';
  resolution_notes?: string;
  detected_at: string;
  resolved_at?: string;
  created_at: string;
  updated_at: string;
}

export interface ReplaySession {
  id: string;
  incident_id?: string;
  symbol: string;
  start_time: string;
  end_time: string;
  created_by?: string;
  session_name?: string;
  notes?: string;
  created_at: string;
  last_accessed_at: string;
}

export interface ReplayData {
  snapshots: ReplaySnapshot[];
  traces: DecisionTrace[];
  trades: Array<{
    id: string;
    symbol: string;
    entry_time: string;
    exit_time?: string;
    side: string;
    size: number;
    entry_price: number;
    exit_price?: number;
    pnl?: number;
  }>;
  positions: Array<{
    id: string;
    symbol: string;
    side: string;
    size: number;
    entry_price: number;
    current_price: number;
    opened_at: string;
    closed_at?: string;
  }>;
}

export interface ReplayDataResponse {
  success: boolean;
  data: ReplayData;
}

export interface IncidentsResponse {
  success: boolean;
  data: Incident[];
  count: number;
}

export interface IncidentResponse {
  success: boolean;
  data: Incident;
}

export interface ReplaySessionsResponse {
  success: boolean;
  data: ReplaySession[];
}

// Reporting Types
export interface ReportTemplate {
  id: string;
  name: string;
  report_type: 'daily' | 'weekly' | 'monthly' | 'custom';
  description?: string;
  config: Record<string, any>;
  schedule_cron?: string;
  enabled: boolean;
  recipients: string[];
  created_by?: string;
  created_at: string;
  updated_at: string;
}

export interface GeneratedReport {
  id: string;
  template_id?: string;
  report_type: string;
  period_start: string;
  period_end: string;
  report_data: Record<string, any>;
  pdf_path?: string;
  html_path?: string;
  json_path?: string;
  status: 'generating' | 'completed' | 'failed';
  error_message?: string;
  generated_at: string;
  generated_by?: string;
  sent_at?: string;
  recipients: string[];
  created_at: string;
}

export interface StrategyPortfolio {
  id: string;
  strategy_name: string;
  strategy_family?: string;
  bot_profile_id?: string;
  calculation_date: string;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  daily_return?: number;
  weekly_return?: number;
  monthly_return?: number;
  ytd_return?: number;
  max_drawdown?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  calmar_ratio?: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate?: number;
  avg_win?: number;
  avg_loss?: number;
  profit_factor?: number;
  current_exposure?: number;
  max_exposure?: number;
  exposure_pct?: number;
  risk_budget_pct?: number;
  capital_allocation?: number;
  created_at: string;
  updated_at: string;
}

export interface StrategyCorrelation {
  id: string;
  strategy_a: string;
  strategy_b: string;
  calculation_date: string;
  correlation_coefficient?: number;
  correlation_period_days: number;
  covariance?: number;
  beta?: number;
  created_at: string;
}

export interface PortfolioSummary {
  id: string;
  calculation_date: string;
  total_portfolio_pnl: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  portfolio_daily_return?: number;
  portfolio_weekly_return?: number;
  portfolio_monthly_return?: number;
  portfolio_ytd_return?: number;
  portfolio_max_drawdown?: number;
  portfolio_sharpe_ratio?: number;
  portfolio_sortino_ratio?: number;
  total_portfolio_trades: number;
  portfolio_win_rate?: number;
  total_exposure?: number;
  total_risk_budget?: number;
  risk_budget_utilization_pct?: number;
  active_strategies_count: number;
  created_at: string;
  updated_at: string;
}

export interface ReportTemplatesResponse {
  success: boolean;
  data: ReportTemplate[];
  count: number;
}

export interface GeneratedReportsResponse {
  success: boolean;
  data: GeneratedReport[];
  count: number;
}

export interface StrategyPortfolioResponse {
  success: boolean;
  data: StrategyPortfolio[];
  count: number;
}

export interface StrategyCorrelationsResponse {
  success: boolean;
  data: StrategyCorrelation[];
  count: number;
}

export interface PortfolioSummaryResponse {
  success: boolean;
  data: PortfolioSummary[];
  count: number;
}

// Data Quality Types
export interface DataQualityMetric {
  id: string;
  symbol: string;
  timeframe: string;
  metric_date: string;
  total_candles_expected: number;
  total_candles_received: number;
  missing_candles_count: number;
  duplicate_candles_count: number;
  avg_ingest_latency_ms?: number;
  max_ingest_latency_ms?: number;
  min_ingest_latency_ms?: number;
  outlier_count: number;
  gap_count: number;
  invalid_price_count: number;
  timestamp_drift_seconds?: number;
  quality_score: number;
  status: 'healthy' | 'degraded' | 'critical';
  created_at: string;
  updated_at: string;
}

export interface FeedGap {
  id: string;
  symbol: string;
  timeframe: string;
  gap_start_time: string;
  gap_end_time: string;
  gap_duration_seconds: number;
  expected_candles_count?: number;
  missing_candles_count?: number;
  detected_at: string;
  resolved_at?: string;
  resolution_method?: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  notes?: string;
  created_at: string;
}

export interface DataQualityAlert {
  id: string;
  symbol: string;
  alert_type: 'missing_data' | 'high_latency' | 'outlier' | 'gap' | 'low_quality_score';
  severity: 'low' | 'medium' | 'high' | 'critical';
  threshold_value?: number;
  actual_value?: number;
  threshold_type?: string;
  detected_at: string;
  resolved_at?: string;
  status: 'open' | 'acknowledged' | 'resolved' | 'closed';
  description?: string;
  resolution_notes?: string;
  created_at: string;
  updated_at: string;
}

export interface SymbolDataHealth {
  symbol: string;
  timeframe: string;
  health_status: 'healthy' | 'degraded' | 'critical' | 'unknown';
  quality_score: number;
  last_metric_time?: string;
  last_candle_time?: string;
  last_update_time?: string;
  active_gaps_count: number;
  active_alerts_count: number;
  avg_latency_ms?: number;
  updated_at: string;
}

export interface QualityMetricsResponse {
  success: boolean;
  data: DataQualityMetric[];
  count: number;
}

export interface FeedGapsResponse {
  success: boolean;
  data: FeedGap[];
  count: number;
}

export interface QualityAlertsResponse {
  success: boolean;
  data: DataQualityAlert[];
  count: number;
}

export interface SymbolHealthResponse {
  success: boolean;
  data: SymbolDataHealth | SymbolDataHealth[];
}

// ═══════════════════════════════════════════════════════════════
// BOT-CENTRIC ARCHITECTURE TYPES
// ═══════════════════════════════════════════════════════════════

export type BotEnvironment = 'dev' | 'paper' | 'live';
export type BotConfigState = 'created' | 'ready' | 'running' | 'paused' | 'error' | 'blocked' | 'decommissioned';
export type AllocatorRole = 'core' | 'satellite' | 'hedge' | 'experimental';

export interface StrategyTemplate {
  id: string;
  name: string;
  slug: string;
  description?: string;
  strategy_family: string;
  timeframe: string;
  default_profile_bundle: Record<string, unknown>;
  default_risk_config: RiskConfig;
  default_execution_config: ExecutionConfig;
  supported_exchanges: string[];
  recommended_symbols: string[];
  version: number;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
}

export interface RiskConfig {
  positionSizePct?: number;
  maxPositions?: number;
  maxDailyLossPct?: number;
  maxTotalExposurePct?: number;
  maxExposurePerSymbolPct?: number;
  maxLeverage?: number;
  leverageMode?: 'isolated' | 'cross';
  maxPositionsPerSymbol?: number;
  maxDailyLossPerSymbolPct?: number;
  minPositionSizeUsd?: number;
  maxPositionSizeUsd?: number | null;
  maxPositionsPerStrategy?: number;
  maxDrawdownPct?: number;
}

export interface ExecutionConfig {
  defaultOrderType?: 'market' | 'limit';
  stopLossPct?: number;
  takeProfitPct?: number;
  trailingStopEnabled?: boolean;
  trailingStopPct?: number;
  maxHoldTimeHours?: number;
  minTradeIntervalSec?: number;
  executionTimeoutSec?: number;
  enableVolatilityFilter?: boolean;
  orderIntentMaxAgeSec?: number;
}

export type MarketType = "perp" | "spot";
export type BotType = "standard" | "ai_spot_swing";

export interface BotInstance {
  id: string;
  user_id: string;
  name: string;
  description?: string;
  strategy_template_id?: string;
  allocator_role: AllocatorRole;
  market_type: MarketType;
  bot_type?: BotType;
  default_risk_config: RiskConfig;
  default_execution_config: ExecutionConfig;
  profile_overrides: Record<string, unknown>;
  tags: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
  // Joined fields
  template_name?: string;
  template_slug?: string;
  strategy_family?: string;
  // Exchange configs
  exchangeConfigs?: BotExchangeConfig[];
}

export interface BotExchangeConfig {
  id: string;
  bot_instance_id: string;
  credential_id: string;
  exchange_account_id?: string;  // New field for exchange_accounts system
  environment: BotEnvironment;
  trading_capital_usd?: number;
  enabled_symbols: string[];
  risk_config: RiskConfig;
  execution_config: ExecutionConfig;
  profile_overrides: Record<string, unknown>;
  state: BotConfigState;
  last_state_change?: string;
  last_error?: string;
  is_active: boolean;
  activated_at?: string;
  last_heartbeat_at?: string;
  decisions_count: number;
  trades_count: number;
  config_version: number;
  notes?: string;
  created_at: string;
  updated_at: string;
  // Joined fields
  exchange?: string;
  exchange_account_label?: string;
  exchange_account_venue?: string;
  credential_label?: string;
  is_demo?: boolean;
  credential_status?: string;
  exchange_balance?: number;
  bot_name?: string;
}

export interface BotSymbolConfig {
  id: string;
  bot_exchange_config_id: string;
  symbol: string;
  enabled: boolean;
  max_exposure_pct?: number;
  max_position_size_usd?: number;
  max_positions: number;
  max_leverage?: number;
  symbol_risk_config: RiskConfig;
  symbol_profile_overrides: Record<string, unknown>;
  preferred_order_type?: string;
  max_slippage_bps?: number;
  metadata?: Record<string, unknown>;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface TenantRiskPolicy {
  id: string;
  user_id: string;
  max_daily_loss_pct: number;
  max_daily_loss_usd?: number;
  max_total_exposure_pct: number;
  max_single_position_pct: number;
  max_per_symbol_exposure_pct: number;
  max_leverage: number;
  allowed_leverage_levels: number[];
  max_concurrent_positions: number;
  max_concurrent_bots: number;
  max_symbols: number;
  total_capital_limit_usd?: number;
  min_reserve_pct: number;
  live_trading_enabled: boolean;
  allowed_environments: BotEnvironment[];
  allowed_exchanges: string[];
  trading_hours_enabled: boolean;
  circuit_breaker_enabled: boolean;
  circuit_breaker_loss_pct: number;
  circuit_breaker_cooldown_minutes: number;
  policy_version: number;
  created_at: string;
  updated_at: string;
}

export interface BotConfigVersion {
  id: string;
  bot_exchange_config_id: string;
  version_number: number;
  trading_capital_usd?: number;
  enabled_symbols: string[];
  risk_config: RiskConfig;
  execution_config: ExecutionConfig;
  change_summary?: string;
  change_type?: string;
  was_activated: boolean;
  activated_at?: string;
  created_at: string;
}

// API Responses
export interface BotInstancesResponse {
  bots: BotInstance[];
}

export interface BotInstanceResponse {
  bot: BotInstance;
}

export interface BotExchangeConfigsResponse {
  configs: BotExchangeConfig[];
}

export interface BotExchangeConfigResponse {
  config: BotExchangeConfig;
  symbolConfigs?: BotSymbolConfig[];
  versions?: BotConfigVersion[];
}

export interface StrategyTemplatesResponse {
  templates: StrategyTemplate[];
}

export interface TenantRiskPolicyResponse {
  policy: TenantRiskPolicy;
}

export interface ActiveConfigResponse {
  active: BotExchangeConfig | null;
  symbols: BotSymbolConfig[];
  policy: TenantRiskPolicy;
}

// ═══════════════════════════════════════════════════════════════
// TRADE HISTORY TYPES
// ═══════════════════════════════════════════════════════════════

export interface TradeDecisionTrace {
  profileId?: string;
  profileName?: string;
  strategyId?: string;
  strategyName?: string;
  signalSide?: string;
  signalConfidence?: number;
  signalStrength?: number;
  stagesExecuted?: string[];
  stageTiming?: Record<string, number>;
  stageResults?: Record<string, any>;
  dataQuality?: Record<string, any>;
  totalLatencyMs?: number;
  rejectionStage?: string;
  rejectionReason?: string;
  rejectionDetails?: any;
  finalResult?: string;
  rawTrace?: any;
}

export interface RuntimePredictionPayload {
  ts?: string | number;
  timestamp?: string | number;
  symbol?: string;
  direction?: string;
  confidence?: number;
  source?: string;
  provider_version?: string;
  reason?: string | null;
  reason_codes?: string[];
  risk_flags?: string[];
  expected_move_bps?: number | null;
  horizon_sec?: number | null;
  valid_for_ms?: number | null;
  provider_latency_ms?: number | null;
  fallback_used?: boolean;
  raw_score?: number | null;
  reject?: boolean;
  [key: string]: unknown;
}

export interface RuntimePredictionSnapshotResponse {
  payload: RuntimePredictionPayload | null;
}

export interface PredictionEventsResponse {
  items: RuntimePredictionPayload[];
  total: number;
}

export interface TradeHistoryEntry {
  id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  size: number;
  pnl: number;
  fees: number;
  pnlPercent: number | null;
  timestamp: number;
  formattedTimestamp: string | null;
  holdingDuration: number | null;
  exitReason: string | null;
  decisionTrace: TradeDecisionTrace | null;
  entry_fee_usd?: number | null;
  exit_fee_usd?: number | null;
  total_fees_usd?: number | null;
  entry_slippage_bps?: number | null;
  exit_slippage_bps?: number | null;
  spread_cost_bps?: number | null;
  total_cost_bps?: number | null;
  mid_at_send?: number | null;
  expected_price_at_send?: number | null;
  send_ts?: number | null;
  ack_ts?: number | null;
  first_fill_ts?: number | null;
  final_fill_ts?: number | null;
  post_only_reject_count?: number | null;
  cancel_after_timeout_count?: number | null;
  order_type?: string | null;
  post_only?: boolean | null;
}

export interface TradeHistoryStats {
  totalTrades: number;
  totalPnl: number;
  totalPnL?: number; // Alias for compatibility
  winningTrades: number;
  losingTrades: number;
  breakEvenTrades: number;
  avgPnl: number;
  avgWin?: number;
  avgLoss?: number;
  largestWin: number;
  largestLoss: number;
  maxWin?: number;
  maxLoss?: number;
  winRate: number;
  profitFactor?: number;
  sharpe?: number;
  totalFees?: number;
  netPnl?: number;
  avgFeesPerTrade?: number;
  pnlHistory?: Array<{ date: string; pnl: number; netPnl?: number; fees?: number }>;
}

export interface TradeHistoryFilters {
  symbol: string | null;
  side: string | null;
  startDate: string | null;
  endDate: string | null;
}

export interface TradeHistoryResponse {
  trades: TradeHistoryEntry[];
  pagination: {
    total: number;
    limit: number;
    offset: number;
    hasMore: boolean;
  };
  stats: TradeHistoryStats;
  filters: TradeHistoryFilters;
  updatedAt: number;
}

export interface TradeDetailExit {
  reason: string;
  details: any | null;
}

export interface TradeDetailMarketContext {
  regime?: string;
  volatility?: number;
  trend?: string;
  session?: string;
}

export interface TradeDetailRelatedTrace {
  timestamp: number;
  result: string;
  stages: string[];
  latencyMs: number;
}

export interface TradeDetail {
  id: string;
  symbol: string;
  side: string;
  entryPrice: number;
  exitPrice: number;
  size: number;
  pnl: number;
  pnlPercent: number | null;
  timestamp: number;
  formattedTimestamp: string | null;
  decision: TradeDecisionTrace | null;
  exit: TradeDetailExit;
  marketContext: TradeDetailMarketContext | null;
  relatedTraces: TradeDetailRelatedTrace[];
}

export interface TradeDetailResponse {
  trade: TradeDetail;
  updatedAt: number;
}

// Additional VaR/Risk Types (used by client.ts)
export interface ComponentVaRResponse {
  success: boolean;
  components: Array<{
    symbol: string;
    var: number;
    contribution: number;
    weight: number;
  }>;
  total: number;
  timestamp: string;
}

export interface RiskLimitsResponse {
  success: boolean;
  limits: {
    maxPositionSize: number;
    maxDailyLoss: number;
    maxDrawdown: number;
    maxExposure: number;
    maxConcentration: number;
    varLimit: number;
  };
  current: {
    positionSize: number;
    dailyLoss: number;
    drawdown: number;
    exposure: number;
    concentration: number;
    var: number;
  };
  utilization: Record<string, number>;
}

// Signals Page Types
export interface DecisionFunnelData {
  timeWindow: string;
  stages: {
    marketTicks: number;
    predictionsProduced: number;
    signalsTriggered: number;
    passedFilters: number;
    passedRiskGates: number;
    ordersSent: number;
    fills: number;
  };
  conversionRates: {
    predictions: number;
    signals: number;
    filters: number;
    risk: number;
    orders: number;
    fills: number;
  };
  updatedAt: number;
}

export interface SymbolStatus {
  symbol: string;
  status: 'tradable' | 'no_signal' | 'blocked' | 'cooling_down' | 'risk_paused' | 'data_stale';
  profile: string;
  signal: {
    side: string | null;
    strength: number;
    confidence: number;
  };
  blockingStage: string | null;
  blockingReason: string | null;
  lastDecision: string | null;
  lastDecisionOutcome: string | null;
  latencyP95: number;
}

export interface SymbolStatusResponse {
  symbols: SymbolStatus[];
  configuredCount: number;
  updatedAt: number;
}

export interface DecisionHistoryItem {
  id: string;
  timestamp: string;
  outcome: string;
  decisionType: string | null;
  rejectionStage: string | null;
  rejectionReason: string | null;
  thresholds: Record<string, any>;
  actuals: Record<string, any>;
  stageTimings: Record<string, number>;
  profile: string | null;
  signal: {
    side: string | null;
    strength: number;
    confidence: number;
  };
  latency: number;
}

export interface DecisionHistoryResponse {
  symbol: string;
  decisions: DecisionHistoryItem[];
  count: number;
  updatedAt: number;
}

export interface StatusNarrativeResponse {
  narrative: string;
  metrics: {
    tradesCount: number;
    signalsCount: number;
    rejectsCount: number;
    topRejectionStage: string;
    topRejectionPct: number;
    topRejectionReasons?: Array<{
      reason: string;
      count: number;
      pct: number;
    }>;
    wsStatus: string;
    orderbookAge: number | string;
    modelWarmup: number;
    signalGenerationIssue?: boolean;
  };
  timeWindow: string;
  updatedAt: number;
}

export interface ConfirmationReadinessResponse {
  timeWindow: string;
  decisionCount: number;
  decisionsWithShadow: number;
  comparisonCount: number;
  mismatchCount: number;
  disagreementPct: number;
  contractViolations: number;
  modeCounts: Record<string, number>;
  topDiffReasons: Array<{ reason: string; count: number }>;
  thresholds: {
    maxDisagreementPct: number;
    minComparisons: number;
    maxContractViolations: number;
  };
  checks: {
    min_comparisons_met: boolean;
    disagreement_within_limit: boolean;
    contract_violations_within_limit: boolean;
  };
  readyForEnforce: boolean;
  marketOutcome: {
    horizonMinutes: number;
    totalSamples: number;
    evaluatedSamples: number;
    cohorts: Record<string, {
      samples: number;
      evaluated: number;
      positiveRate: number | null;
      meanMarkoutBps: number | null;
      medianMarkoutBps: number | null;
      netPositiveRate?: number | null;
      meanNetMarkoutBps?: number | null;
      medianNetMarkoutBps?: number | null;
    }>;
    metric?: string;
    estimatedCostBpsFallback?: number;
    deltaUnifiedMinusLegacyBps: number | null;
    deltaUnifiedMinusLegacyGrossBps?: number | null;
    deltaUnifiedMinusLegacyNetBps?: number | null;
  };
  outcomeThresholds: {
    minOutcomeSamples: number;
    minUnifiedOnlyMeanBps: number;
    minUnifiedVsLegacyDeltaBps: number;
  };
  outcomeChecks: {
    unified_only_samples_met: boolean;
    unified_only_mean_markout_ok: boolean;
    unified_vs_legacy_delta_ok: boolean;
  };
  outcomeReadyForEnforce: boolean;
  recommendedReadyForEnforce: boolean;
  updatedAt: number;
}

export interface DataSettings {
  tenant_id: string;
  trade_history_retention_days: number | null;
  replay_snapshot_retention_days: number | null;
  backtest_equity_sample_every: number;
  backtest_max_equity_points: number;
  backtest_max_symbol_equity_points: number;
  backtest_max_decision_snapshots: number;
  backtest_max_position_snapshots: number;
  capture_decision_traces: boolean;
  capture_feature_values: boolean;
  capture_orderbook: boolean;
}


// ═══════════════════════════════════════════════════════════════
// LOSS PREVENTION TYPES
// ═══════════════════════════════════════════════════════════════

export interface LossPreventionMetrics {
  total_signals_rejected: number;
  rejection_breakdown: Record<string, number>;
  estimated_losses_avoided_usd: number;
  average_loss_per_trade_usd: number;
  low_confidence_count: number;
  strategy_trend_mismatch_count: number;
  fee_trap_count: number;
  session_mismatch_count: number;
  window_start: number;
  window_end: number;
}

export interface LossPreventionMetricsResponse {
  success: boolean;
  data: LossPreventionMetrics;
  error?: string;
  updatedAt: number;
}


// ═══════════════════════════════════════════════════════════════
// DATA BACKFILL TYPES
// ═══════════════════════════════════════════════════════════════

export interface BackfillRequest {
  symbol: string;
  exchange: string;
  start_date: string;
  end_date: string;
  timeframe: string;
}

export interface BackfillResponse {
  job_id: string;
  status: string;
  message: string;
  symbol: string;
  exchange: string;
  start_date: string;
  end_date: string;
  timeframe: string;
}

export interface BackfillProgressResponse {
  job_id: string;
  status: string;
  total_candles: number;
  inserted_candles: number;
  skipped_candles: number;
  failed_batches: number;
  current_date: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface BackfillResultResponse {
  job_id: string;
  symbol: string;
  exchange: string;
  start_date: string;
  end_date: string;
  timeframe: string;
  total_candles: number;
  inserted_candles: number;
  skipped_candles: number;
  failed_batches: number;
  duration_sec: number;
  status: string;
  error: string | null;
}

export interface GapBackfillRequest {
  gap_id: string;
  symbol: string;
  exchange: string;
  start_time: string;
  end_time: string;
  timeframe: string;
}

export interface BackfillJobsResponse {
  jobs: Array<{
    job_id: string;
    status: string;
    request: BackfillRequest | null;
    gap_id: string | null;
    error: string | null;
  }>;
  total: number;
}
