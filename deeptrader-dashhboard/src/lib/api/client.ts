import axios from "axios";
import { getAuthToken, getAuthUser } from "../../store/auth-store";
import { useScopeStore } from "../../store/scope-store";
import { buildScopedParams } from "./params";
import {
  MonitoringDashboardResponse,
  FastScalperStatusResponse,
  FastScalperRejectionsResponse,
  MonitoringAlertsResponse,
  BotStatus,
  TradeProfile,
  TradingSnapshot,
  SignalLabSnapshot,
  HealthSnapshot,
  FastScalperLogsResponse,
  BotProfilesResponse,
  BotProfileDetailResponse,
  ActivateBotVersionResponse,
  CandlestickResponse,
  DrawdownResponse,
  StrategiesResponse,
  StrategyResponse,
  SignalConfig,
  SignalConfigResponse,
  AllocatorConfig,
  AllocatorConfigResponse,
  MarketContextResponse,
  BacktestRun,
  BacktestDetailResponse,
  BacktestsResponse,
  CreateBacktestRequest,
  BacktestPreflightResponse,
  DatasetsResponse,
  ProfileSpecsResponse,
  ProfileMetricsResponse,
  ProfileRouterResponse,
  TCAAnalysisResponse,
  CapacityCurveResponse,
  TradeCostResponse,
  CalculateVaRRequest,
  CalculateVaRResponse,
  VaRCalculationsResponse,
  ScenarioTestRequest,
  ScenarioTestResponse,
  ScenarioResultsResponse,
  CreatePromotionRequest,
  PromotionsResponse,
  Promotion,
  ConfigDiffResponse,
  AuditLogResponse,
  DecisionTracesResponse,
  AuditDecisionTrace,
  ExportAuditLogRequest,
  ExportAuditLogResponse,
  ReplayDataResponse,
  IncidentsResponse,
  IncidentResponse,
  ReplaySessionsResponse,
  Incident,
  ReplaySession,
  QualityMetricsResponse,
  FeedGapsResponse,
  QualityAlertsResponse,
  SymbolHealthResponse,
  DataQualityMetric,
  FeedGap,
  DataQualityAlert,
  SymbolDataHealth,
  ReportTemplatesResponse,
  GeneratedReportsResponse,
  StrategyPortfolioResponse,
  StrategyCorrelationsResponse,
  PortfolioSummaryResponse,
  ReportTemplate,
  GeneratedReport,
  StrategyPortfolio,
  StrategyCorrelation,
  PortfolioSummary,
  BotProfile,
  BotProfileVersion,
  ComponentVaRResponse,
  RiskLimitsResponse,
  VaRCalculation,
  ScenarioFactorResponse,
  ScenarioDetailResponse,
  CorrelationsResponse,
  DecisionFunnelData,
  SymbolStatusResponse,
  DecisionHistoryResponse,
  StatusNarrativeResponse,
  ConfirmationReadinessResponse,
  DataSettings,
} from "./types";
import type { ViewerScope } from "./auth";

const CORE_ROUTE_PREFIXES = [
  "/auth",
  "/settings",
  "/exchange-credentials",
  "/exchange-accounts",
  "/profiles",
  "/user-profiles",
  "/strategy-instances",
  "/deployment",
  "/symbol-locks",
  "/promotions",
  "/audit",
  "/config-validation",
  "/models",
  "/control",
];

function isOwnershipScopedBotRoute(path: string): boolean {
  if (!path.startsWith("/bot-instances")) return false;
  if (
    path.startsWith("/bot-instances/active") ||
    path.startsWith("/bot-instances/policy")
  ) {
    return false;
  }
  return true;
}

function isRuntimeScopedBotRoute(path: string): boolean {
  return (
    path.startsWith("/quant/pipeline/health") ||
    path.startsWith("/dashboard/live-status") ||
    path.startsWith("/python/bot/status") ||
    path.startsWith("/dashboard/warmup")
  );
}

function getProxyPortSuffix(): string {
  // Only preserve the port when we are actually behind the nginx proxy port.
  // If you open the dashboard on the Vite dev port (e.g. :5173) we must NOT
  // reuse that port for API calls (it will hit the frontend server and return HTML).
  if (typeof window === "undefined") return "";
  const port = window.location.port;
  if (!port) return "";
  return port === "8080" ? `:${port}` : "";
}

function getCoreApiBaseUrl(): string {
  if (import.meta.env.VITE_CORE_API_BASE_URL) {
    return import.meta.env.VITE_CORE_API_BASE_URL;
  }
  // Dynamic detection for remote access
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    
    // Handle quantgambit.local domains (via nginx proxy)
    if (hostname.endsWith('quantgambit.local')) {
      // If we're not on the nginx proxy port, assume local dev and hit localhost directly.
      // This prevents calling api.quantgambit.local:<vite_port>.
      if (window.location.port && window.location.port !== "8080") {
        return "http://localhost:3001/api";
      }
      return `${protocol}//api.quantgambit.local${getProxyPortSuffix()}/api`;
    }

    if (hostname.endsWith('quantgambit.com')) {
      return `${protocol}//api.quantgambit.com/api`;
    }
    
    // Handle IP-based access (remote machines) or any non-localhost hostname
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return `${protocol}//${hostname}:3001/api`;
    }
  }
  return "http://localhost:3001/api";
}

function getBotApiBaseUrl(): string {
  if (import.meta.env.VITE_BOT_API_BASE_URL) {
    return import.meta.env.VITE_BOT_API_BASE_URL;
  }
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    
    // Handle quantgambit.local domains (via nginx proxy)
    if (hostname.endsWith('quantgambit.local')) {
      // If we're not on the nginx proxy port, assume local dev and hit localhost directly.
      // This prevents calling bot.quantgambit.local:<vite_port>.
      if (window.location.port && window.location.port !== "8080") {
        return "http://localhost:3002/api";
      }
      return `${protocol}//bot.quantgambit.local${getProxyPortSuffix()}/api`;
    }

    if (hostname.endsWith('quantgambit.com')) {
      return `${protocol}//bot.quantgambit.com/api`;
    }
    
    // Handle IP-based access (remote machines) or any non-localhost hostname
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return `${protocol}//${hostname}:3002/api`;
    }
  }
  return "http://localhost:3002/api";
}

export const CORE_API_BASE_URL = getCoreApiBaseUrl();
export const BOT_API_BASE_URL = getBotApiBaseUrl();

// Lazy getters for dynamic URL resolution (for components that need fresh values)
export const getCoreApiUrl = () => getCoreApiBaseUrl();
export const getBotApiUrl = () => getBotApiBaseUrl();

const api = axios.create({
  timeout: 8000,
});

// Set baseURL dynamically on each request to handle IP-based access
api.interceptors.request.use((config) => {
  // Dynamically determine base URL for each request
  const urlPath = config.url ?? "";
  if (CORE_ROUTE_PREFIXES.some((prefix) => urlPath.startsWith(prefix))) {
    config.baseURL = getCoreApiBaseUrl();
  } else {
    config.baseURL = getBotApiBaseUrl();
  }
  
  const token = getAuthToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
   // Attach scope identifiers for routing
  const scope = useScopeStore.getState();
  config.params = buildScopedParams(config.params, scope, import.meta.env.VITE_TENANT_ID as string | undefined);
  if (isOwnershipScopedBotRoute(urlPath) && config.params && typeof config.params === "object") {
    delete (config.params as Record<string, unknown>).tenant_id;
  }
  if (isRuntimeScopedBotRoute(urlPath) && config.params && typeof config.params === "object") {
    delete (config.params as Record<string, unknown>).tenant_id;
  }
  return config;
});

export const apiFetch = (path: string, options: RequestInit = {}) => {
  const token = getAuthToken();
  // Use dynamic URL resolution for fetch as well
  const baseUrl = CORE_ROUTE_PREFIXES.some((prefix) => path.startsWith(prefix))
    ? getCoreApiBaseUrl()
    : getBotApiBaseUrl();
  const headers = new Headers(options.headers ?? {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(`${baseUrl}${path}`, { ...options, headers });
};

export const fetchMonitoringDashboard = () =>
  api.get<MonitoringDashboardResponse>("/monitoring/dashboard").then((res) => res.data);

export const fetchFastScalperStatus = (params?: { botId?: string }) => {
  return api
    .get<FastScalperStatusResponse>("/monitoring/fast-scalper", {
      params: params?.botId ? { botId: params.botId } : undefined,
    })
    .then((res) => res.data);
};

export const fetchRuntimeConfig = (botId: string, tenantId?: string) => {
  const authUser = getAuthUser();
  const effectiveTenantId = tenantId || authUser?.id;
  return api
    .get<{ success: boolean; config: Record<string, unknown> | null }>(
      '/monitoring/runtime-config',
      { params: { bot_id: botId, tenant_id: effectiveTenantId } }
    )
    .then((res) => res.data.config);
};

export interface RuntimeKnobSpec {
  key: string;
  section: "risk_config" | "execution_config" | "profile_overrides";
  label: string;
  type: "int" | "float" | "bool" | "str";
  min?: number | null;
  max?: number | null;
  default?: number | boolean | string | null;
}

export interface RuntimeConfigEffectiveResponse {
  success: boolean;
  config: {
    id: string;
    config_version: number;
    trading_capital_usd: number | null;
    enabled_symbols: string[];
    risk_config: Record<string, unknown>;
    execution_config: Record<string, unknown>;
    profile_overrides: Record<string, unknown>;
  };
  knobs: RuntimeKnobSpec[];
}

export interface RuntimeConfigApplyRequest {
  botExchangeConfigId: string;
  actor?: string;
  enabledSymbols?: string[];
  riskConfig?: Record<string, unknown>;
  executionConfig?: Record<string, unknown>;
  profileOverrides?: Record<string, unknown>;
}

export interface RuntimeConfigExportResponse {
  success: boolean;
  botExchangeConfigId: string;
  configVersion: number;
  runtime_env: Record<string, string>;
  env_text: string;
  diagnostics: {
    unmapped_keys: string[];
    mapped_env_count: number;
    strict_mode: boolean;
  };
}

export interface RuntimeConfigImportRequest {
  botExchangeConfigId: string;
  envText?: string;
  runtimeEnv?: Record<string, string>;
  dryRun?: boolean;
  changeSummary?: string;
}

export interface RuntimeConfigImportResponse {
  success: boolean;
  dryRun: boolean;
  version?: number;
  config?: RuntimeConfigEffectiveResponse["config"];
  proposal?: {
    enabled_symbols: string[];
    risk_config: Record<string, unknown>;
    execution_config: Record<string, unknown>;
    profile_overrides: Record<string, unknown>;
    trading_capital_usd: number | null;
  };
  unmapped_env_keys: string[];
}

export const fetchRuntimeKnobs = () =>
  api
    .get<{ success: boolean; knobs: RuntimeKnobSpec[] }>("/dashboard/runtime-config/knobs")
    .then((res) => res.data);

export const fetchRuntimeConfigEffective = (botExchangeConfigId: string) =>
  api
    .get<RuntimeConfigEffectiveResponse>("/dashboard/runtime-config/effective", {
      params: { botExchangeConfigId },
    })
    .then((res) => res.data);

export const applyRuntimeConfig = (payload: RuntimeConfigApplyRequest) =>
  api
    .post<RuntimeConfigEffectiveResponse>("/dashboard/runtime-config/apply", payload)
    .then((res) => res.data);

export const fetchRuntimeConfigExport = (botExchangeConfigId: string) =>
  api
    .get<RuntimeConfigExportResponse>("/dashboard/runtime-config/export", {
      params: { botExchangeConfigId },
    })
    .then((res) => res.data);

export const importRuntimeConfigFromEnv = (payload: RuntimeConfigImportRequest) =>
  api
    .post<RuntimeConfigImportResponse>("/dashboard/runtime-config/import", payload)
    .then((res) => res.data);

// Fetch dashboard metrics with optional scope (paper trading aware)
export const fetchDashboardMetrics = (params?: { exchangeAccountId?: string; botId?: string }) => {
  return api.get("/dashboard/metrics", { params }).then((res) => {
    const result = res.data?.data ?? res.data;
    console.log('[fetchDashboardMetrics] Response:', { 
      exchange_balance: result?.exchange_balance,
      _isPaper: result?._isPaper,
      params 
    });
    return result;
  });
};

export const fetchFastScalperRejections = () =>
  api.get<FastScalperRejectionsResponse>("/monitoring/fast-scalper/rejections").then((res) => res.data);

export const fetchMonitoringAlerts = () =>
  api.get<MonitoringAlertsResponse>("/monitoring/alerts").then((res) => res.data);

export const fetchBotStatus = (params?: { botId?: string }) => {
  return api
    .get<BotStatus>("/python/bot/status", {
      params: params?.botId ? { bot_id: params.botId } : undefined,
    })
    .then((res) => res.data);
};

export const fetchTradeProfile = () =>
  api
    .get<{ profile: TradeProfile }>("/exchange-credentials/profile")
    .then((res) => res.data.profile);

export const fetchTradingSnapshot = (params?: { exchangeAccountId?: string; botId?: string }) => {
  return api
    .get<TradingSnapshot>("/dashboard/trading", { params })
    .then((res) => res.data);
};

export const fetchSignalLabSnapshot = () =>
  api.get<SignalLabSnapshot>("/dashboard/signals").then((res) => res.data);

// Signals page endpoints
export const fetchDecisionFunnel = (params?: { timeWindow?: string; botId?: string; exchangeAccountId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.timeWindow) queryParams.set('timeWindow', params.timeWindow);
  if (params?.botId) queryParams.set('botId', params.botId);
  if (params?.exchangeAccountId) queryParams.set('exchangeAccountId', params.exchangeAccountId);
  const queryString = queryParams.toString();
  return api.get<DecisionFunnelData>(`/dashboard/signals/funnel${queryString ? `?${queryString}` : ''}`).then((res) => res.data);
};

export const fetchSymbolStatus = (params?: { botId?: string; exchangeAccountId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.botId) queryParams.set('botId', params.botId);
  if (params?.exchangeAccountId) queryParams.set('exchangeAccountId', params.exchangeAccountId);
  const queryString = queryParams.toString();
  return api.get<SymbolStatusResponse>(`/dashboard/signals/symbols${queryString ? `?${queryString}` : ''}`).then((res) => res.data);
};

export const fetchSymbolDecisions = (symbol: string, params?: { botId?: string; exchangeAccountId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.botId) queryParams.set('botId', params.botId);
  if (params?.exchangeAccountId) queryParams.set('exchangeAccountId', params.exchangeAccountId);
  const queryString = queryParams.toString();
  return api.get<DecisionHistoryResponse>(`/dashboard/signals/decisions/${symbol}${queryString ? `?${queryString}` : ''}`).then((res) => res.data);
};

export const fetchStatusNarrative = (params?: { timeWindow?: string; botId?: string; exchangeAccountId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.timeWindow) queryParams.set('timeWindow', params.timeWindow);
  if (params?.botId) queryParams.set('botId', params.botId);
  if (params?.exchangeAccountId) queryParams.set('exchangeAccountId', params.exchangeAccountId);
  const queryString = queryParams.toString();
  return api.get<StatusNarrativeResponse>(`/dashboard/signals/narrative${queryString ? `?${queryString}` : ''}`).then((res) => res.data);
};

export const fetchConfirmationReadiness = (params?: { timeWindow?: string; botId?: string; exchangeAccountId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.timeWindow) queryParams.set('timeWindow', params.timeWindow);
  if (params?.botId) queryParams.set('botId', params.botId);
  if (params?.exchangeAccountId) queryParams.set('exchangeAccountId', params.exchangeAccountId);
  const queryString = queryParams.toString();
  return api.get<ConfirmationReadinessResponse>(`/dashboard/signals/confirmation-readiness${queryString ? `?${queryString}` : ''}`).then((res) => res.data);
};

// Warmup status for AMT/HTF data
export interface WarmupSymbolStatus {
  amt: {
    status: string;
    progress: number;
    ready: boolean;
    candles: number;
    lastUpdate: string | null;
  };
  htf: {
    status: string;
    progress: number;
    ready: boolean;
    candles: number;
    lastUpdate: string | null;
  };
  overallReady: boolean;
  overallProgress: number;
  reasons?: string[];
}

export interface WarmupStatus {
  symbols: Record<string, WarmupSymbolStatus>;
  overall: {
    progress: number;
    ready: boolean;
    symbolCount: number;
    sampleCount?: number;
    minSamples?: number;
    candleCount?: number;
    minCandles?: number;
  };
  botStatus: {
    heartbeatAlive: boolean;
    metricsAgeSeconds: number | null;
    servicesHealthy: boolean;
  };
  updatedAt: number;
}

export const fetchWarmupStatus = (botId?: string | null, tenantId?: string | null) =>
  api
    .get<WarmupStatus>("/dashboard/warmup", {
      params: { botId: botId || undefined, tenant_id: tenantId || undefined },
    })
    .then((res) => res.data);

export interface ControlStatusResponse {
  startLock: { locked: boolean; ttl: number };
}

export const fetchControlStatus = (botId?: string | null, tenantId?: string | null) =>
  api
    .get<ControlStatusResponse>("/control/status", {
      params: { botId: botId || undefined, tenantId: tenantId || undefined },
    })
    .then((res) => res.data);

// Strategy evaluation status
export interface StrategyStatus {
  strategy: {
    id: string;
    name: string;
    description: string;
  };
  conditions: {
    required: Array<{ name: string; description: string }>;
    weights: Record<string, number>;
  };
  featureStatus: Record<string, {
    hasFeatures: boolean;
    lastUpdate: string | null;
    dataCompleteness: number;
    hasValueArea: boolean;
    hasRotationFactor: boolean;
    hasBidAskImbalance: boolean;
    hasRSI: boolean;
    hasVolumeRatio: boolean;
  }>;
  recentEvaluations: Array<{
    symbol: string;
    timestamp: string;
    action: string;
    reason: string;
    score: number;
  }>;
  signalsGenerated: number;
  lastSignal: any | null;
  updatedAt: number;
}

export const fetchStrategyStatus = () =>
  api.get<StrategyStatus>("/dashboard/strategy-status").then((res) => res.data);

export const fetchHealthSnapshot = (params?: { botId?: string }) =>
  Promise.all([
    fetchFastScalperStatus({ botId: params?.botId }),
    api.get("/dashboard/state", { params: { botId: params?.botId } }).then((res) => res.data ?? res),
    api.get("/dashboard/live-status", { params: { botId: params?.botId } }).then((res) => res.data ?? res),
  ]).then(([fastScalper, snapshot, liveStatus]) => {
    const liveHealth = liveStatus?.health ?? {};
    const liveServices = liveHealth?.services ?? {};
    const heartbeatAgeSeconds =
      liveStatus?.heartbeat?.ageSeconds ??
      liveStatus?.heartbeat?.age_seconds ??
      null;
    const heartbeatAlive =
      typeof heartbeatAgeSeconds === "number"
        ? heartbeatAgeSeconds <= 60
        : String(liveStatus?.heartbeat?.status || "").toLowerCase() === "ok";
    return {
      status:
        liveHealth?.status ??
        snapshot?.botStatus?.platform?.status ??
        fastScalper?.status ??
        "unknown",
      botStatus: {
        heartbeatAlive,
      },
      services: liveServices,
      serviceHealth: snapshot.serviceHealth ?? liveStatus?.health ?? null,
      resourceUsage: snapshot.resourceUsage ?? null,
      componentDiagnostics: snapshot.componentDiagnostics ?? null,
      fastScalper,
      liveStatus,
      updatedAt: Date.now(),
    } satisfies HealthSnapshot;
  });

export const fetchFastScalperLogs = () =>
  api.get<FastScalperLogsResponse>("/monitoring/fast-scalper/logs").then((res) => res.data);

export const fetchBotProfiles = () =>
  api.get<BotProfilesResponse>("/bot-config/bots").then((res) => res.data);

export const fetchBotProfileDetail = (botId: string) =>
  api.get<BotProfileDetailResponse>(`/bot-config/bots/${botId}`).then((res) => res.data);

export const fetchActiveBot = () =>
  api.get<{ bot: BotProfile | null }>("/bot-config/active-bot").then((res) => res.data);

export const setActiveBot = (botId: string) =>
  api.post<{ message: string; bot: BotProfile }>("/bot-config/active-bot", { botId }).then((res) => res.data);

export const activateBotVersion = (botId: string, versionId: string) =>
  api
    .post<ActivateBotVersionResponse>(`/bot-config/bots/${botId}/activate`, { versionId })
    .then((res) => res.data);

export const fetchCandlestickData = (
  symbol: string, 
  timeframe: string = "1m", 
  limit: number = 288,
  startTime?: number,
  endTime?: number
) =>
  api
    .get<CandlestickResponse>(`/dashboard/candles/${symbol}`, {
      params: { 
        timeframe, 
        limit, 
        exchange: 'bybit',
        ...(startTime && { startTime }),
        ...(endTime && { endTime }),
      },
    })
    .then((res) => res.data);

export const fetchDrawdownData = (hours: number = 24, exchangeAccountId?: string, botId?: string) =>
  api
    .get<DrawdownResponse>(`/dashboard/drawdown`, {
      params: {
        hours,
        ...(exchangeAccountId && { exchangeAccountId }),
        ...(botId && { botId }),
      },
    })
    .then((res) => res.data);

// Settings API
export interface TradingSettings {
  enabledOrderTypes: string[];
  orderTypeSettings: Record<string, any>;
  riskProfile: "conservative" | "moderate" | "aggressive";
  // Global sizing & exposure
  maxConcurrentPositions: number;
  maxPositionSizePercent: number;
  maxTotalExposurePercent: number;
  aiConfidenceThreshold: number;
  tradingInterval: number;
  enabledTokens: string[];
  // Per-token overrides (optional fields)
  perTokenSettings?: Record<
    string,
    {
      enabled?: boolean;
      positionSizePct?: number;
      leverage?: number;
      notes?: string;
    }
  >;
  dayTradingEnabled: boolean;
  scalpingMode: boolean;
  trailingStopsEnabled: boolean;
  partialProfitsEnabled: boolean;
  timeBasedExitsEnabled: boolean;
  multiTimeframeConfirmation: boolean;
  dayTradingMaxHoldingHours: number;
  dayTradingStartTime: string;
  dayTradingEndTime: string;
  dayTradingForceCloseTime: string;
  dayTradingDaysOnly: boolean;
  scalpingTargetProfitPercent: number;
  scalpingMaxHoldingMinutes: number;
  scalpingMinVolumeMultiplier: number;
  trailingStopActivationPercent: number;
  trailingStopCallbackPercent: number;
  trailingStopStepPercent: number;
  partialProfitLevels: Array<{ percent: number; target: number }>;
  timeExitMaxHoldingHours: number;
  timeExitBreakEvenHours: number;
  timeExitWeekendClose: boolean;
  mtfRequiredTimeframes: string[];
  mtfMinConfirmations: number;
  mtfTrendAlignmentRequired: boolean;
  leverageEnabled: boolean;
  maxLeverage: number;
  leverageMode: string;
  liquidationBufferPercent: number;
  marginCallThresholdPercent: number;
  availableLeverageLevels: number[];
}

const percentFields = [
  "maxPositionSizePercent",
  "maxTotalExposurePercent",
  "scalpingTargetProfitPercent",
  "trailingStopActivationPercent",
  "trailingStopCallbackPercent",
  "trailingStopStepPercent",
  "liquidationBufferPercent",
  "marginCallThresholdPercent",
];

const toPercentDisplay = (value: unknown) => {
  if (value === null || value === undefined) return value as undefined;
  const num = Number(value);
  if (Number.isNaN(num)) return value as unknown as number;
  return num > 1 ? num : num * 100;
};

const toDecimalValue = (value: unknown) => {
  if (value === null || value === undefined) return value as undefined;
  const num = Number(value);
  if (Number.isNaN(num)) return value as unknown as number;
  return num > 1 ? num / 100 : num;
};

const normalizeTradingSettingsForUI = (settings: TradingSettings) => {
  const normalized = { ...settings };
  for (const field of percentFields) {
    if (field in normalized) {
      normalized[field] = toPercentDisplay(normalized[field as keyof TradingSettings]) as number;
    }
  }
  if (normalized.perTokenSettings) {
    const next: TradingSettings["perTokenSettings"] = {};
    for (const [symbol, cfg] of Object.entries(normalized.perTokenSettings)) {
      if (!cfg) continue;
      next[symbol] = {
        ...cfg,
        positionSizePct: cfg.positionSizePct === undefined ? cfg.positionSizePct : toPercentDisplay(cfg.positionSizePct),
      };
    }
    normalized.perTokenSettings = next;
  }
  if (normalized.orderTypeSettings?.bracket) {
    normalized.orderTypeSettings = {
      ...normalized.orderTypeSettings,
      bracket: {
        ...normalized.orderTypeSettings.bracket,
        stopLossPercent: toPercentDisplay(normalized.orderTypeSettings.bracket.stopLossPercent),
        takeProfitPercent: toPercentDisplay(normalized.orderTypeSettings.bracket.takeProfitPercent),
      },
    };
  }
  if (normalized.orderTypeSettings?.market) {
    normalized.orderTypeSettings = {
      ...normalized.orderTypeSettings,
      market: {
        ...normalized.orderTypeSettings.market,
        slippageLimit: toPercentDisplay(normalized.orderTypeSettings.market.slippageLimit),
      },
    };
  }
  if (normalized.orderTypeSettings?.trailing_stop) {
    normalized.orderTypeSettings = {
      ...normalized.orderTypeSettings,
      trailing_stop: {
        ...normalized.orderTypeSettings.trailing_stop,
        callbackRate: toPercentDisplay(normalized.orderTypeSettings.trailing_stop.callbackRate),
      },
    };
  }
  if (normalized.partialProfitLevels) {
    normalized.partialProfitLevels = normalized.partialProfitLevels.map((level) => ({
      ...level,
      target: toPercentDisplay(level.target),
    }));
  }
  return normalized;
};

const normalizeTradingSettingsForApi = (settings: Partial<TradingSettings>) => {
  const normalized = { ...settings } as Partial<TradingSettings>;
  for (const field of percentFields) {
    if (field in normalized) {
      normalized[field] = toDecimalValue(normalized[field as keyof TradingSettings]) as number;
    }
  }
  if (normalized.perTokenSettings) {
    const next: TradingSettings["perTokenSettings"] = {};
    for (const [symbol, cfg] of Object.entries(normalized.perTokenSettings)) {
      if (!cfg) continue;
      next[symbol] = {
        ...cfg,
        positionSizePct: cfg.positionSizePct === undefined ? cfg.positionSizePct : toDecimalValue(cfg.positionSizePct),
      };
    }
    normalized.perTokenSettings = next;
  }
  if (normalized.orderTypeSettings?.bracket) {
    normalized.orderTypeSettings = {
      ...normalized.orderTypeSettings,
      bracket: {
        ...normalized.orderTypeSettings.bracket,
        stopLossPercent: toDecimalValue(normalized.orderTypeSettings.bracket.stopLossPercent),
        takeProfitPercent: toDecimalValue(normalized.orderTypeSettings.bracket.takeProfitPercent),
      },
    };
  }
  if (normalized.orderTypeSettings?.market) {
    normalized.orderTypeSettings = {
      ...normalized.orderTypeSettings,
      market: {
        ...normalized.orderTypeSettings.market,
        slippageLimit: toDecimalValue(normalized.orderTypeSettings.market.slippageLimit),
      },
    };
  }
  if (normalized.orderTypeSettings?.trailing_stop) {
    normalized.orderTypeSettings = {
      ...normalized.orderTypeSettings,
      trailing_stop: {
        ...normalized.orderTypeSettings.trailing_stop,
        callbackRate: toDecimalValue(normalized.orderTypeSettings.trailing_stop.callbackRate),
      },
    };
  }
  if (normalized.partialProfitLevels) {
    normalized.partialProfitLevels = normalized.partialProfitLevels.map((level) => ({
      ...level,
      target: toDecimalValue(level.target),
    }));
  }
  return normalized;
};

export const fetchTradingSettings = () =>
  api.get<TradingSettings>("/settings/trading").then((res) => normalizeTradingSettingsForUI(res.data));

export const updateTradingSettings = (settings: Partial<TradingSettings>) =>
  api
    .put<{ message: string; settings: TradingSettings }>(
      "/settings/trading",
      normalizeTradingSettingsForApi(settings)
    )
    .then((res) => ({
      ...res.data,
      settings: normalizeTradingSettingsForUI(res.data.settings),
    }));

export const resetTradingSettings = () =>
  api
    .post<{ message: string; settings: TradingSettings }>("/settings/trading/reset")
    .then((res) => ({
      ...res.data,
      settings: normalizeTradingSettingsForUI(res.data.settings),
    }));

export type AccountSettings = {
  orgName: string;
  timezone: string;
  baseCurrency: string;
  language: string;
};

export type ViewerAccount = {
  id: string;
  tenantId: string;
  parentUserId?: string | null;
  email: string;
  username: string;
  firstName?: string | null;
  lastName?: string | null;
  role: string;
  isActive: boolean;
  viewerScope: ViewerScope;
  createdAt?: string;
  lastLogin?: string | null;
};

export type ViewerAccountPayload = {
  email: string;
  password?: string;
  firstName?: string;
  lastName?: string;
  botId: string;
  botName?: string | null;
  exchangeAccountId: string;
  exchangeAccountName?: string | null;
  isActive?: boolean;
};

export const fetchAccountSettings = () =>
  api.get<AccountSettings>("/settings/account").then((res) => res.data);

export const updateAccountSettings = (payload: Partial<AccountSettings>) =>
  api.put<AccountSettings>("/settings/account", payload).then((res) => res.data);

export const fetchViewerAccounts = () =>
  api.get<{ viewers: ViewerAccount[] }>("/settings/account/viewers").then((res) => res.data.viewers);

export const createViewerAccount = (payload: ViewerAccountPayload) =>
  api.post<{ viewer: ViewerAccount }>("/settings/account/viewers", payload).then((res) => res.data.viewer);

export const updateViewerAccount = (viewerId: string, payload: Partial<ViewerAccountPayload>) =>
  api.put<{ viewer: ViewerAccount }>(`/settings/account/viewers/${viewerId}`, payload).then((res) => res.data.viewer);

export const deleteViewerAccount = (viewerId: string) =>
  api.delete(`/settings/account/viewers/${viewerId}`).then((res) => res.data);

export const fetchOrderTypes = () =>
  api.get<{ orderTypes: Record<string, any>; riskProfiles: Record<string, any> }>("/settings/order-types").then((res) => res.data);

export const fetchDataSettings = (tenantId: string) =>
  api.get<DataSettings>("/settings/data", { params: { tenant_id: tenantId } }).then((res) => res.data);

export const updateDataSettings = (settings: DataSettings) =>
  api.post<{ success: boolean; settings: DataSettings }>("/settings/data", settings).then((res) => res.data);

// Bot Profile API
export const createBotProfile = (data: {
  name: string;
  environment?: string;
  engineType?: string;
  description?: string;
  config?: Record<string, any>;
  metadata?: Record<string, any>;
  activate?: boolean;
}) =>
  api.post<{ message: string; bot: BotProfile; version: BotProfileVersion }>("/bot-config/bots", data).then((res) => res.data);

export const createBotVersion = (
  botId: string,
  data: {
    baseVersionId?: string;
    overrides?: Record<string, any>;
    notes?: string;
    status?: string;
    promote?: boolean;
    activate?: boolean;
  }
) =>
  api
    .post<{ message: string; version: BotProfileVersion; activated?: boolean }>(`/bot-config/bots/${botId}/versions`, data)
    .then((res) => res.data);

// Strategy API
export const fetchStrategies = () =>
  api.get<StrategiesResponse>("/bot-config/strategies").then((res) => res.data);

export const fetchStrategyById = (strategyId: string) =>
  api.get<StrategyResponse>(`/bot-config/strategies/${strategyId}`).then((res) => res.data);

// Signal Configuration API
export const fetchSignalConfig = () =>
  api.get<SignalConfigResponse>("/settings/signal-config").then((res) => res.data);

export const updateSignalConfig = (config: Partial<SignalConfig>) =>
  api.put<{ message: string; config: SignalConfig }>("/settings/signal-config", config).then((res) => res.data);

// Allocator Configuration API
export const fetchAllocatorConfig = () =>
  api.get<AllocatorConfigResponse>("/settings/allocator").then((res) => res.data);

export const updateAllocatorConfig = (config: Partial<AllocatorConfig>) =>
  api.put<{ message: string; config: AllocatorConfig }>("/settings/allocator", config).then((res) => res.data);

// Market Context API
export const fetchMarketContext = (symbol?: string, botId?: string | null) =>
  api
    .get<MarketContextResponse>("/dashboard/market-context", {
      params: {
        ...(symbol ? { symbol } : {}),
        ...(botId ? { botId } : {}),
      },
    })
    .then((res) => res.data);

// Research & Backtesting API
export const fetchBacktests = (params?: { limit?: number; offset?: number; status?: string; strategy_id?: string }) =>
  api
    .get<BacktestsResponse>("/research/backtests", { params })
    .then((res) => res.data);

export const fetchBacktestDetail = (id: string) =>
  api
    .get<BacktestDetailResponse>(`/research/backtests/${id}`)
    .then((res) => res.data);

export const createBacktest = (data: CreateBacktestRequest) =>
  api
    .post<{ message: string; backtest: BacktestRun }>("/research/backtests", data)
    .then((res) => res.data);

export const fetchBacktestPreflight = (params: {
  symbol: string;
  start_date: string;
  end_date: string;
  require_decision_events?: boolean;
}) =>
  api
    .get<BacktestPreflightResponse>("/research/backtests/preflight", { params })
    .then((res) => res.data);

export const cancelBacktest = (id: string) =>
  api
    .delete<{ success: boolean; message: string; run_id: string; status: string }>(`/research/backtests/${id}`)
    .then((res) => res.data);

export const rerunBacktest = (id: string, options?: { force_run?: boolean }) =>
  api
    .post<{ run_id: string; status: string; message: string }>(`/research/backtests/${id}/rerun`, options || {})
    .then((res) => res.data);

export const promoteBacktestConfig = (
  id: string,
  options?: { bot_id?: string; notes?: string; activate?: boolean; status?: string },
) =>
  api
    .post<{
      success: boolean;
      run_id: string;
      bot_id: string;
      version_id: string;
      version_number: number;
      activated: boolean;
    }>(`/research/backtests/${id}/promote`, options || {})
    .then((res) => res.data);

export const deleteBacktest = (id: string) =>
  api
    .delete<{ success: boolean; message: string; run_id: string }>(`/research/backtests/${id}/delete`)
    .then((res) => res.data);

export interface ModelTrainingRequest {
  redis_url?: string;
  tenant_id?: string;
  bot_id?: string;
  stream?: string;
  label_source?: "future_return" | "tp_sl" | "policy_replay";
  limit?: number;
  hours?: number;
  walk_forward_folds?: number;
  drift_check?: boolean;
  allow_regression?: boolean;
  min_directional_f1?: number;
  min_ev_after_costs?: number;
  min_directional_f1_delta?: number;
  min_ev_delta?: number;
  keep_dataset?: boolean;
  use_v4_pipeline?: boolean;
  horizon_sec?: number;
  tp_bps?: number;
  sl_bps?: number;
}

export interface ModelTrainingJobSummary {
  id: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  label_source: string;
  stream: string;
  tenant_id?: string | null;
  bot_id?: string | null;
  exit_code?: number | null;
  promotion_status?: string | null;
}

export interface ActiveModelInfo {
  model_file?: string | null;
  config_file?: string | null;
  promoted_at?: string | null;
  promoted_from_job_id?: string | null;
  source_model_file?: string | null;
  source_config_file?: string | null;
  pointer_updated_at?: string | null;
}

export const startModelTraining = (payload: ModelTrainingRequest) =>
  api
    .post<{ success: boolean; job: ModelTrainingJobSummary }>("/research/model-training/jobs", payload)
    .then((res) => res.data);

export const fetchModelTrainingJobs = (limit = 20) =>
  api
    .get<ModelTrainingJobSummary[]>("/research/model-training/jobs", { params: { limit } })
    .then((res) => res.data);

export const fetchModelTrainingJob = (jobId: string) =>
  api
    .get<{ job: Record<string, any> }>(`/research/model-training/jobs/${jobId}`)
    .then((res) => res.data);

export const fetchActiveModelInfo = () =>
  api
    .get<ActiveModelInfo>("/research/model-training/active")
    .then((res) => res.data);

export const promoteModelTrainingJob = (jobId: string, payload?: { notes?: string }) =>
  api
    .post<{
      success: boolean;
      job_id: string;
      source_model_file: string;
      source_config_file: string;
      latest_model_path: string;
      latest_config_path: string;
    }>(`/research/model-training/jobs/${jobId}/promote`, payload || {})
    .then((res) => res.data);

// Warm Start API for Trading Pipeline Integration
// Feature: trading-pipeline-integration
// Requirements: 3.1, 3.6, 4.8
export interface WarmStartPosition {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  stop_loss?: number;
  take_profit?: number;
  timestamp?: string;
  unrealized_pnl?: number; // Added for live state display - Requirements 4.8
}

export interface WarmStartResponse {
  snapshot_time: string;
  positions: WarmStartPosition[];
  account_state: {
    equity: number;
    margin?: number;
    balance?: number;
    available_balance?: number;
  };
  candle_history: Record<string, any[]>;
  pipeline_state: Record<string, any>;
  is_stale: boolean;
  age_seconds: number;
  is_valid: boolean;
  validation_errors: string[];
}

export const fetchWarmStartState = () =>
  api
    .post<WarmStartResponse>("/research/backtest/warm-start")
    .then((res) => res.data);

// Walk-Forward Optimization API (redis-backed)
export const fetchWfoRuns = () =>
  api.get<{ runs: any[] }>("/research/walk-forward").then((res) => res.data);

export const fetchWfoRun = (id: string) =>
  api.get<{ run: any }>(`/research/walk-forward/${id}`).then((res) => res.data);

export const createWfoRun = (data: any) =>
  api.post<{ run: any }>("/research/walk-forward", data).then((res) => res.data);

export const fetchDatasets = (params?: { symbol?: string; start_date?: string; end_date?: string }) =>
  api
    .get<DatasetsResponse>("/research/datasets", { params })
    .then((res) => res.data);

// Research Strategies API (for backtesting)
export const fetchResearchStrategies = () =>
  api.get<{ strategies: any[]; total: number }>("/research/strategies").then((res) => res.data);

// Chessboard Profile Specs API
export const fetchProfileSpecs = (botId?: string | null) =>
  api
    .get<ProfileSpecsResponse>("/bot-config/profile-specs", {
      params: botId ? { botId } : undefined,
    })
    .then((res) => res.data);

// Profile Routing Metrics API (runtime data)
export const fetchProfileMetrics = (botId?: string | null) =>
  api
    .get<ProfileMetricsResponse>("/bot-config/profile-metrics", {
      params: botId ? { botId } : undefined,
    })
    .then((res) => res.data);

// Profile Router API (selection & rejection data)
export const fetchProfileRouter = (botId?: string | null) =>
  api
    .get<ProfileRouterResponse>("/bot-config/profile-router", {
      params: botId ? { botId } : undefined,
    })
    .then((res) => res.data);

// Trade Cost Analysis (TCA) API
export const fetchTCAAnalysis = (filters?: {
  symbol?: string;
  profileId?: string;
  startDate?: string;
  endDate?: string;
  periodType?: "daily" | "weekly" | "monthly";
}) =>
  api
    .get<TCAAnalysisResponse>("/tca/analysis", { params: filters })
    .then((res) => res.data);

export const fetchCapacityCurve = (
  profileId: string,
  startDate?: string,
  endDate?: string
) =>
  api
    .get<CapacityCurveResponse>(`/tca/capacity/${profileId}`, {
      params: { startDate, endDate },
    })
    .then((res) => res.data);

export const fetchTradeCost = (tradeId: string) =>
  api
    .get<TradeCostResponse>(`/tca/costs/${tradeId}`)
    .then((res) => res.data);

// Risk Metrics (VaR/ES) API
export const calculateHistoricalVaR = (params: CalculateVaRRequest) =>
  api
    .post<CalculateVaRResponse>("/risk/var/historical", params)
    .then((res) => res.data);

export const calculateMonteCarloVaR = (params: CalculateVaRRequest) =>
  api
    .post<CalculateVaRResponse>("/risk/var/monte-carlo", params)
    .then((res) => res.data);

export const fetchVaRCalculations = (params?: {
  portfolioId?: string;
  symbol?: string;
  profileId?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<VaRCalculationsResponse>("/risk/var", { params })
    .then((res) => res.data);

export const runScenarioTest = (params: ScenarioTestRequest) =>
  api
    .post<ScenarioTestResponse>("/risk/scenarios", params)
    .then((res) => res.data);

export const fetchScenarioResults = (params?: {
  limit?: number;
  offset?: number;
}) =>
  api
    .get<ScenarioResultsResponse>("/risk/scenarios", { params })
    .then((res) => res.data);

export const fetchScenarioDetail = (id: string) =>
  api
    .get<ScenarioTestResponse>(`/risk/scenarios/${id}`)
    .then((res) => res.data);

// Component VaR & factor impacts
export const fetchComponentVaR = () =>
  api.get<ComponentVaRResponse>("/risk/component-var").then((res) => res.data);

export const fetchScenarioFactors = () =>
  api.get<ScenarioFactorResponse>("/risk/scenarios/factors").then((res) => res.data);

export const fetchScenarioDetailWithFactors = (id: string) =>
  api.get<ScenarioDetailResponse>(`/risk/scenarios/${id}/factors`).then((res) => res.data);

export const fetchCorrelations = (params?: { strategyName?: string; limit?: number }) =>
  api.get<CorrelationsResponse>("/risk/correlations", { params }).then((res) => res.data);

export const fetchRiskLimits = () =>
  api.get<RiskLimitsResponse>("/risk/limits").then((res) => res.data);

export const updateRiskLimits = (updates: Record<string, unknown>) =>
  api.put<{ success: boolean; policy: TenantRiskPolicy; message: string }>("/risk/limits", updates).then((res) => res.data);

// VaR Snapshot API
export interface VaRSnapshotResponse {
  success: boolean;
  snapshot: {
    timestamp: string;
    scope: { exchangeAccountId?: string; botId?: string; portfolioId?: string };
    results: Array<{
      confidence: number;
      horizon: number;
      var: number;
      es: number;
      status: string;
    }>;
    dataCheck: { sufficient: boolean; tradeDays: number; totalTrades: number; required: number };
  } | null;
  dataStatus: { sufficient: boolean; tradeDays: number; totalTrades: number; required: number };
  latestAuto: VaRCalculation[];
  latestManual: VaRCalculation[];
  freshness: 'fresh' | 'recent' | 'aging' | 'stale';
  minDataDays: number;
}

export interface VaRDataStatusResponse {
  success: boolean;
  sufficient: boolean;
  tradeDays: number;
  totalTrades: number;
  required: number;
  minRequired: number;
  message: string;
}

export const fetchVaRSnapshot = () =>
  api.get<VaRSnapshotResponse>("/risk/var/snapshot").then((res) => res.data);

export const fetchVaRDataStatus = (params?: { exchangeAccountId?: string; botId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.exchangeAccountId) queryParams.set("exchangeAccountId", params.exchangeAccountId);
  if (params?.botId) queryParams.set("botId", params.botId);
  const query = queryParams.toString();
  return api.get<VaRDataStatusResponse>(`/risk/var/data-status${query ? `?${query}` : ""}`).then((res) => res.data);
};

export const forceVaRSnapshot = (params?: { exchangeAccountId?: string; botId?: string; portfolioId?: string }) =>
  api.post<{ success: boolean; message: string; results?: any[]; snapshotMeta?: any }>("/risk/var/force-snapshot", params).then((res) => res.data);

export const triggerVaRRefresh = (event: string, scope?: Record<string, string>) =>
  api.post<{ success: boolean; message: string; supportedEvents: string[] }>("/risk/var/trigger-refresh", { event, scope }).then((res) => res.data);

// Promotion Workflow API
export const fetchPromotions = (params?: {
  status?: string;
  promotionType?: string;
  botProfileId?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<PromotionsResponse>("/promotions", { params })
    .then((res) => res.data);

export const createPromotion = (data: CreatePromotionRequest) =>
  api
    .post<{ success: boolean; message: string; promotion: Promotion }>("/promotions", data)
    .then((res) => res.data);

export const approvePromotion = (id: string) =>
  api
    .put<{ success: boolean; message: string; promotion: Promotion }>(`/promotions/${id}/approve`)
    .then((res) => res.data);

export const rejectPromotion = (id: string, reason?: string) =>
  api
    .put<{ success: boolean; message: string; promotion: Promotion }>(`/promotions/${id}/reject`, { reason })
    .then((res) => res.data);

export const completePromotion = (id: string) =>
  api
    .put<{ success: boolean; message: string; promotion: Promotion }>(`/promotions/${id}/complete`)
    .then((res) => res.data);

export const fetchPromotionDetail = (id: string) =>
  api
    .get<{ success: boolean; promotion: Promotion }>(`/promotions/${id}`)
    .then((res) => res.data);

export const fetchConfigDiff = (params: {
  botProfileId: string;
  versionId1: string;
  versionId2: string;
}) =>
  api
    .get<ConfigDiffResponse>("/config/diff", { params })
    .then((res) => res.data);

// Audit Log API
export const fetchAuditLog = (params?: {
  userId?: string;
  actionType?: string;
  actionCategory?: string;
  resourceType?: string;
  resourceId?: string;
  severity?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<AuditLogResponse>("/audit", { params })
    .then((res) => res.data);

export const exportAuditLog = (params: ExportAuditLogRequest) =>
  api
    .get<ExportAuditLogResponse>("/audit/export", { params })
    .then((res) => res.data);

export const fetchDecisionTrace = (tradeId: string) =>
  api
    .get<{ success: boolean; trace: AuditDecisionTrace }>(`/audit/traces/${tradeId}`)
    .then((res) => res.data);

export const fetchDecisionTraces = (params?: {
  tradeId?: string;
  symbol?: string;
  decisionType?: string;
  decisionOutcome?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<DecisionTracesResponse>("/audit/traces", { params })
    .then((res) => res.data);

// Replay & Incident Analysis API
export const fetchReplayData = (symbol: string, startTime: string, endTime: string) =>
  api
    .get<ReplayDataResponse>(`/replay/data/${symbol}`, {
      params: { start: startTime, end: endTime },
    })
    .then((res) => res.data);

// ============================================================
// INCIDENTS API (Risk Ops Console)
// ============================================================

export interface IncidentFilters {
  incidentType?: string;
  severity?: string;
  status?: string;
  exchangeAccountId?: string;
  botId?: string;
  triggerRule?: string;
  startDate?: string;
  endDate?: string;
  search?: string;
  causedPause?: boolean;
  limit?: number;
  offset?: number;
}

export interface IncidentSnapshot {
  activeIncidents: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    total: number;
  };
  autoPauses24h: number;
  breaches24h: number;
  pnlImpact24h: number;
  recentIncidents: any[];
}

export interface IncidentTimelineEvent {
  id: string;
  incident_id: string;
  event_type: string;
  actor: string;
  event_data: any;
  created_at: string;
}

export interface IncidentEvidence {
  incident: any;
  trades: any[];
  positions: any[];
  pnlTimeline: { timestamp: string; pnl: number; cumulativePnl: number; symbol: string }[];
  exposureTimeline: { timestamp: string; exposure: number; symbol: string }[];
  summary: {
    totalTrades: number;
    totalPositions: number;
    totalPnl: number;
    peakExposure: number;
  };
}

export const fetchIncidents = (params?: IncidentFilters) =>
  api
    .get<{ success: boolean; incidents: any[]; total: number }>("/risk/incidents", { params })
    .then((res) => res.data);

export const fetchIncidentSnapshot = (params?: { exchangeAccountId?: string; botId?: string }) =>
  api
    .get<{ success: boolean; snapshot: IncidentSnapshot }>("/risk/incidents/snapshot", { params })
    .then((res) => res.data);

export const fetchIncident = (incidentId: string) =>
  api
    .get<{ success: boolean; incident: any }>(`/risk/incidents/${incidentId}`)
    .then((res) => res.data);

export const createIncident = (incident: {
  incidentType: string;
  severity?: string;
  title: string;
  description?: string;
  exchangeAccountId?: string;
  botId?: string;
  affectedSymbols?: string[];
  triggerRule?: string;
  triggerThreshold?: number;
  triggerActual?: number;
  actionTaken?: string;
  pnlImpact?: number;
}) =>
  api
    .post<{ success: boolean; incident: any }>("/risk/incidents", incident)
    .then((res) => res.data);

export const acknowledgeIncident = (incidentId: string) =>
  api
    .post<{ success: boolean; incident: any }>(`/risk/incidents/${incidentId}/acknowledge`)
    .then((res) => res.data);

export const assignIncidentOwner = (incidentId: string, ownerId: string) =>
  api
    .put<{ success: boolean; incident: any }>(`/risk/incidents/${incidentId}/assign`, { ownerId })
    .then((res) => res.data);

export const resolveIncident = (incidentId: string, resolutionNotes?: string, rootCause?: string) =>
  api
    .put<{ success: boolean; incident: any }>(`/risk/incidents/${incidentId}/resolve`, {
      resolutionNotes,
      rootCause,
    })
    .then((res) => res.data);

export const updateIncidentStatus = (
  incidentId: string,
  status: string,
  notes?: string
) =>
  api
    .put<{ success: boolean; incident: any }>(`/risk/incidents/${incidentId}/status`, {
      status,
      notes,
    })
    .then((res) => res.data);

export const fetchIncidentTimeline = (
  incidentId: string,
  params?: { limit?: number; offset?: number }
) =>
  api
    .get<{ success: boolean; events: IncidentTimelineEvent[] }>(
      `/risk/incidents/${incidentId}/timeline`,
      { params }
    )
    .then((res) => res.data);

export const addIncidentTimelineEvent = (
  incidentId: string,
  eventType: string,
  eventData?: any
) =>
  api
    .post<{ success: boolean }>(`/risk/incidents/${incidentId}/timeline`, {
      eventType,
      eventData,
    })
    .then((res) => res.data);

export const fetchIncidentEvidence = (incidentId: string) =>
  api
    .get<{ success: boolean; evidence: IncidentEvidence }>(`/risk/incidents/${incidentId}/evidence`)
    .then((res) => res.data);

export const exportIncident = (incidentId: string, format: 'json' | 'csv' = 'json') =>
  api
    .get(`/risk/incidents/${incidentId}/export`, {
      params: { format },
      responseType: format === 'json' ? 'json' : 'blob',
    })
    .then((res) => res.data);

export const createReplaySession = (session: {
  incidentId?: string;
  symbol: string;
  startTime: string;
  endTime: string;
  createdBy?: string;
  sessionName?: string;
  notes?: string;
}) =>
  api
    .post<{ success: boolean; data: ReplaySession }>("/replay/sessions", session)
    .then((res) => res.data);

export const fetchReplaySessions = (params?: {
  incidentId?: string;
  symbol?: string;
  limit?: number;
}) =>
  api
    .get<ReplaySessionsResponse>("/replay/sessions", { params })
    .then((res) => res.data);

// Data Quality API
export const fetchQualityMetrics = (params?: {
  symbol?: string;
  timeframe?: string;
  startDate?: string;
  endDate?: string;
  status?: string;
  minQualityScore?: number;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<QualityMetricsResponse>("/data-quality/metrics", { params })
    .then((res) => res.data);

export const fetchQualityMetricsTimeseries = (params?: {
  symbol?: string;
  timeframe?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
}) =>
  api
    .get<QualityMetricsResponse>("/data-quality/metrics/timeseries", { params })
    .then((res) => res.data);

export const storeQualityMetrics = (metrics: {
  symbol: string;
  timeframe: string;
  metricDate: string;
  totalCandlesExpected: number;
  totalCandlesReceived: number;
  missingCandlesCount?: number;
  duplicateCandlesCount?: number;
  avgIngestLatencyMs?: number;
  maxIngestLatencyMs?: number;
  minIngestLatencyMs?: number;
  outlierCount?: number;
  gapCount?: number;
  invalidPriceCount?: number;
  timestampDriftSeconds?: number;
  qualityScore?: number;
  status?: string;
}) =>
  api
    .post<{ success: boolean; data: DataQualityMetric }>("/data-quality/metrics", metrics)
    .then((res) => res.data);

export const fetchFeedGaps = (params?: {
  symbol?: string;
  timeframe?: string;
  startDate?: string;
  endDate?: string;
  severity?: string;
  resolved?: boolean;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<FeedGapsResponse>("/data-quality/gaps", { params })
    .then((res) => res.data);

export const recordFeedGap = (gap: {
  symbol: string;
  timeframe: string;
  gapStartTime: string;
  gapEndTime: string;
  gapDurationSeconds?: number;
  expectedCandlesCount?: number;
  missingCandlesCount?: number;
  severity?: string;
  notes?: string;
}) =>
  api
    .post<{ success: boolean; data: FeedGap }>("/data-quality/gaps", gap)
    .then((res) => res.data);

export const resolveFeedGap = (gapId: string, resolutionMethod: string, notes?: string) =>
  api
    .put<{ success: boolean; data: FeedGap }>(`/data-quality/gaps/${gapId}/resolve`, {
      resolutionMethod,
      notes,
    })
    .then((res) => res.data);

export const fetchQualityAlerts = (params?: {
  symbol?: string;
  timeframe?: string;
  alertType?: string;
  severity?: string;
  status?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<QualityAlertsResponse>("/data-quality/alerts", { params })
    .then((res) => res.data);

export const createQualityAlert = (alert: {
  symbol: string;
  alertType: string;
  severity?: string;
  thresholdValue?: number;
  actualValue?: number;
  thresholdType?: string;
  description?: string;
}) =>
  api
    .post<{ success: boolean; data: DataQualityAlert }>("/data-quality/alerts", alert)
    .then((res) => res.data);

export const updateAlertStatus = (alertId: string, status: string, resolutionNotes?: string) =>
  api
    .put<{ success: boolean; data: DataQualityAlert }>(`/data-quality/alerts/${alertId}/status`, {
      status,
      resolutionNotes,
    })
    .then((res) => res.data);

export const fetchSymbolHealth = (symbol?: string, params?: { timeframe?: string }) =>
  api
    .get<SymbolHealthResponse>(symbol ? `/data-quality/health/${symbol}` : "/data-quality/health", { params })
    .then((res) => res.data);

// Reporting API
export const fetchReportTemplates = (params?: {
  reportType?: string;
  enabled?: boolean;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<ReportTemplatesResponse>("/reporting/templates", { params })
    .then((res) => res.data);

export const createReportTemplate = (template: {
  name: string;
  reportType: string;
  description?: string;
  config?: Record<string, any>;
  scheduleCron?: string;
  enabled?: boolean;
  recipients?: string[];
  createdBy?: string;
}) =>
  api
    .post<{ success: boolean; data: ReportTemplate }>("/reporting/templates", template)
    .then((res) => res.data);

export const fetchGeneratedReports = (params?: {
  templateId?: string;
  reportType?: string;
  startDate?: string;
  endDate?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<GeneratedReportsResponse>("/reporting/reports", { params })
    .then((res) => res.data);

export const storeGeneratedReport = (report: {
  templateId?: string;
  reportType: string;
  periodStart: string;
  periodEnd: string;
  reportData?: Record<string, any>;
  pdfPath?: string;
  htmlPath?: string;
  jsonPath?: string;
  status?: string;
  errorMessage?: string;
  generatedBy?: string;
  recipients?: string[];
}) =>
  api
    .post<{ success: boolean; data: GeneratedReport }>("/reporting/reports", report)
    .then((res) => res.data);

export const fetchStrategyPortfolio = (params?: {
  strategyName?: string;
  strategyFamily?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<StrategyPortfolioResponse>("/reporting/portfolio/strategies", { params })
    .then((res) => res.data);

export const storeStrategyPortfolio = (strategy: {
  strategyName: string;
  strategyFamily?: string;
  botProfileId?: string;
  calculationDate: string;
  totalPnl?: number;
  realizedPnl?: number;
  unrealizedPnl?: number;
  dailyReturn?: number;
  weeklyReturn?: number;
  monthlyReturn?: number;
  ytdReturn?: number;
  maxDrawdown?: number;
  sharpeRatio?: number;
  sortinoRatio?: number;
  calmarRatio?: number;
  totalTrades?: number;
  winningTrades?: number;
  losingTrades?: number;
  winRate?: number;
  avgWin?: number;
  avgLoss?: number;
  profitFactor?: number;
  currentExposure?: number;
  maxExposure?: number;
  exposurePct?: number;
  riskBudgetPct?: number;
  capitalAllocation?: number;
}) =>
  api
    .post<{ success: boolean; data: StrategyPortfolio }>("/reporting/portfolio/strategies", strategy)
    .then((res) => res.data);

export const fetchStrategyCorrelations = (params?: {
  strategyName?: string;
  calculationDate?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<StrategyCorrelationsResponse>("/reporting/portfolio/correlations", { params })
    .then((res) => res.data);

export const storeStrategyCorrelation = (correlation: {
  strategyA: string;
  strategyB: string;
  calculationDate: string;
  correlationCoefficient: number;
  correlationPeriodDays?: number;
  covariance?: number;
  beta?: number;
}) =>
  api
    .post<{ success: boolean; data: StrategyCorrelation }>("/reporting/portfolio/correlations", correlation)
    .then((res) => res.data);

export const fetchPortfolioSummary = (params?: {
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  api
    .get<PortfolioSummaryResponse>("/reporting/portfolio/summary", { params })
    .then((res) => res.data);

export const storePortfolioSummary = (summary: {
  calculationDate: string;
  totalPortfolioPnl?: number;
  totalRealizedPnl?: number;
  totalUnrealizedPnl?: number;
  portfolioDailyReturn?: number;
  portfolioWeeklyReturn?: number;
  portfolioMonthlyReturn?: number;
  portfolioYtdReturn?: number;
  portfolioMaxDrawdown?: number;
  portfolioSharpeRatio?: number;
  portfolioSortinoRatio?: number;
  totalPortfolioTrades?: number;
  portfolioWinRate?: number;
  totalExposure?: number;
  totalRiskBudget?: number;
  riskBudgetUtilizationPct?: number;
  activeStrategiesCount?: number;
}) =>
  api
    .post<{ success: boolean; data: PortfolioSummary }>("/reporting/portfolio/summary", summary)
    .then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// BOT INSTANCES API
// ═══════════════════════════════════════════════════════════════

import type {
  BotInstance,
  BotExchangeConfig,
  BotSymbolConfig,
  StrategyTemplate,
  TenantRiskPolicy,
  BotInstancesResponse,
  BotInstanceResponse,
  BotExchangeConfigsResponse,
  BotExchangeConfigResponse,
  StrategyTemplatesResponse,
  TenantRiskPolicyResponse,
  ActiveConfigResponse,
  RiskConfig,
  ExecutionConfig,
  BotEnvironment,
  BotConfigVersion,
} from "./types";

const normalizeRiskConfigForUI = (config?: RiskConfig) => {
  if (!config) return config;
  return {
    ...config,
    positionSizePct: toPercentDisplay(config.positionSizePct),
    maxDailyLossPct: toPercentDisplay(config.maxDailyLossPct),
    maxTotalExposurePct: toPercentDisplay(config.maxTotalExposurePct),
    maxExposurePerSymbolPct: toPercentDisplay(config.maxExposurePerSymbolPct),
    maxDailyLossPerSymbolPct: toPercentDisplay(config.maxDailyLossPerSymbolPct),
    maxDrawdownPct: toPercentDisplay(config.maxDrawdownPct),
  };
};

const normalizeExecutionConfigForUI = (config?: ExecutionConfig) => {
  if (!config) return config;
  return {
    ...config,
    stopLossPct: toPercentDisplay(config.stopLossPct),
    takeProfitPct: toPercentDisplay(config.takeProfitPct),
    trailingStopPct: toPercentDisplay(config.trailingStopPct),
  };
};

const normalizeRiskConfigForApi = (config?: RiskConfig) => {
  if (!config) return config;
  return {
    ...config,
    positionSizePct: toDecimalValue(config.positionSizePct),
    maxDailyLossPct: toDecimalValue(config.maxDailyLossPct),
    maxTotalExposurePct: toDecimalValue(config.maxTotalExposurePct),
    maxExposurePerSymbolPct: toDecimalValue(config.maxExposurePerSymbolPct),
    maxDailyLossPerSymbolPct: toDecimalValue(config.maxDailyLossPerSymbolPct),
    maxDrawdownPct: toDecimalValue(config.maxDrawdownPct),
  };
};

const normalizeExecutionConfigForApi = (config?: ExecutionConfig) => {
  if (!config) return config;
  return {
    ...config,
    stopLossPct: toDecimalValue(config.stopLossPct),
    takeProfitPct: toDecimalValue(config.takeProfitPct),
    trailingStopPct: toDecimalValue(config.trailingStopPct),
  };
};

const normalizeBotExchangeConfigForUI = (config: BotExchangeConfig) => ({
  ...config,
  risk_config: normalizeRiskConfigForUI(config.risk_config) || config.risk_config,
  execution_config: normalizeExecutionConfigForUI(config.execution_config) || config.execution_config,
});

const normalizeBotInstanceForUI = (bot: BotInstance) => ({
  ...bot,
  default_risk_config: normalizeRiskConfigForUI(bot.default_risk_config) || bot.default_risk_config,
  default_execution_config: normalizeExecutionConfigForUI(bot.default_execution_config) || bot.default_execution_config,
  exchangeConfigs: bot.exchangeConfigs?.map((config) => normalizeBotExchangeConfigForUI(config)),
});

const normalizeBotSymbolConfigForUI = (symbol: BotSymbolConfig) => ({
  ...symbol,
  max_exposure_pct: toPercentDisplay(symbol.max_exposure_pct),
  symbol_risk_config: normalizeRiskConfigForUI(symbol.symbol_risk_config) || symbol.symbol_risk_config,
  symbol_profile_overrides: symbol.symbol_profile_overrides || {},
});

const normalizeBotConfigVersionForUI = (version: BotConfigVersion) => ({
  ...version,
  risk_config: normalizeRiskConfigForUI(version.risk_config) || version.risk_config,
  execution_config: normalizeExecutionConfigForUI(version.execution_config) || version.execution_config,
});

const normalizeBotInstancePayloadForApi = (data: Partial<BotInstance>) => ({
  ...data,
  default_risk_config: normalizeRiskConfigForApi(data.default_risk_config),
  default_execution_config: normalizeExecutionConfigForApi(data.default_execution_config),
});

const normalizeBotExchangeConfigPayloadForApi = (data: Partial<BotExchangeConfig>) => ({
  ...data,
  risk_config: normalizeRiskConfigForApi(data.risk_config),
  execution_config: normalizeExecutionConfigForApi(data.execution_config),
});

const normalizeBotSymbolConfigPayloadForApi = (data: Partial<BotSymbolConfig>) => ({
  ...data,
  max_exposure_pct: toDecimalValue(data.max_exposure_pct),
  symbol_risk_config: normalizeRiskConfigForApi(data.symbol_risk_config),
});

const normalizeTenantRiskPolicyForUI = (policy: TenantRiskPolicy) => ({
  ...policy,
  max_daily_loss_pct: toPercentDisplay(policy.max_daily_loss_pct),
  max_total_exposure_pct: toPercentDisplay(policy.max_total_exposure_pct),
  max_single_position_pct: toPercentDisplay(policy.max_single_position_pct),
  max_per_symbol_exposure_pct: toPercentDisplay(policy.max_per_symbol_exposure_pct),
  min_reserve_pct: toPercentDisplay(policy.min_reserve_pct),
  circuit_breaker_loss_pct: toPercentDisplay(policy.circuit_breaker_loss_pct),
});

const normalizeTenantRiskPolicyForApi = (policy: Partial<TenantRiskPolicy>) => ({
  ...policy,
  max_daily_loss_pct: toDecimalValue(policy.max_daily_loss_pct),
  max_total_exposure_pct: toDecimalValue(policy.max_total_exposure_pct),
  max_single_position_pct: toDecimalValue(policy.max_single_position_pct),
  max_per_symbol_exposure_pct: toDecimalValue(policy.max_per_symbol_exposure_pct),
  min_reserve_pct: toDecimalValue(policy.min_reserve_pct),
  circuit_breaker_loss_pct: toDecimalValue(policy.circuit_breaker_loss_pct),
});

const normalizeDashboardRiskLimitsForUI = (limits: any) => {
  if (!limits || typeof limits !== "object") return limits;
  const normalized: Record<string, any> = { ...limits };
  for (const [key, value] of Object.entries(limits)) {
    if (typeof value !== "number") continue;
    if (/(pct|percent)/i.test(key)) {
      normalized[key] = toPercentDisplay(value);
    }
  }
  return normalized;
};

const normalizeDashboardRiskForUI = (payload: any) => {
  if (!payload || typeof payload !== "object") return payload;
  if (payload.limits && typeof payload.limits === "object") {
    return {
      ...payload,
      limits: normalizeDashboardRiskLimitsForUI(payload.limits),
    };
  }
  const data = payload.data;
  if (!data || typeof data !== "object") return payload;
  if (!data.limits || typeof data.limits !== "object") return payload;
  return {
    ...payload,
    data: {
      ...data,
      limits: normalizeDashboardRiskLimitsForUI(data.limits),
    },
  };
};

// Strategy Templates
export const fetchStrategyTemplates = () =>
  api.get<StrategyTemplatesResponse>("/bot-instances/templates").then((res) => ({
    ...res.data,
    templates: res.data.templates.map((template) => ({
      ...template,
      default_risk_config: normalizeRiskConfigForUI(template.default_risk_config) || template.default_risk_config,
      default_execution_config: normalizeExecutionConfigForUI(template.default_execution_config) || template.default_execution_config,
    })),
  }));

export const fetchStrategyTemplate = (templateId: string) =>
  api.get<{ template: StrategyTemplate }>(`/bot-instances/templates/${templateId}`).then((res) => ({
    ...res.data,
    template: {
      ...res.data.template,
      default_risk_config: normalizeRiskConfigForUI(res.data.template.default_risk_config) || res.data.template.default_risk_config,
      default_execution_config: normalizeExecutionConfigForUI(res.data.template.default_execution_config) || res.data.template.default_execution_config,
    },
  }));

// Bot Instances
export const fetchBotInstances = (includeInactive = false) =>
  api
    .get<BotInstancesResponse>("/bot-instances", { params: { includeInactive } })
    .then((res) => ({ ...res.data, bots: res.data.bots.map((bot) => normalizeBotInstanceForUI(bot)) }));

export const fetchBotInstance = (botId: string) =>
  api.get<BotInstanceResponse>(`/bot-instances/${botId}`).then((res) => ({
    ...res.data,
    bot: normalizeBotInstanceForUI(res.data.bot),
  }));

export const createBotInstance = (data: {
  name: string;
  description?: string;
  strategyTemplateId?: string;
  allocatorRole?: string;
  botType?: "standard" | "ai_spot_swing";
  marketType?: "perp" | "spot";
  tradingMode?: "paper" | "live";  // Bot-level trading mode
  defaultRiskConfig?: RiskConfig;
  defaultExecutionConfig?: ExecutionConfig;
  profileOverrides?: Record<string, unknown>;
  aiProvider?: string;
  aiProfile?: string;
  aiShadowMode?: boolean;
  aiConfidenceFloor?: number;
  aiSentimentRequired?: boolean;
  aiRequireBaselineAlignment?: boolean;
  aiSessions?: string[];
  tags?: string[];
}) =>
  api
    .post<{ message: string; bot: BotInstance }>("/bot-instances", {
      ...data,
      defaultRiskConfig: normalizeRiskConfigForApi(data.defaultRiskConfig),
      defaultExecutionConfig: normalizeExecutionConfigForApi(data.defaultExecutionConfig),
    })
    .then((res) => ({ ...res.data, bot: normalizeBotInstanceForUI(res.data.bot) }));

export const updateBotInstance = (botId: string, data: Partial<BotInstance>) =>
  api
    .put<{ message: string; bot: BotInstance }>(
      `/bot-instances/${botId}`,
      normalizeBotInstancePayloadForApi(data)
    )
    .then((res) => ({ ...res.data, bot: normalizeBotInstanceForUI(res.data.bot) }));

export const deleteBotInstance = (botId: string) =>
  api.delete<{ message: string }>(`/bot-instances/${botId}`).then((res) => res.data);

// Bot Exchange Configs
export const fetchBotExchangeConfigs = (botId: string) =>
  api
    .get<BotExchangeConfigsResponse>(`/bot-instances/${botId}/exchanges`)
    .then((res) => ({ ...res.data, configs: res.data.configs.map((config) => normalizeBotExchangeConfigForUI(config)) }));

export const fetchBotExchangeConfig = (botId: string, configId: string) =>
  api.get<BotExchangeConfigResponse>(`/bot-instances/${botId}/exchanges/${configId}`).then((res) => ({
    ...res.data,
    config: normalizeBotExchangeConfigForUI(res.data.config),
    symbolConfigs: res.data.symbolConfigs?.map((symbol) => normalizeBotSymbolConfigForUI(symbol)),
    versions: res.data.versions?.map((version) => normalizeBotConfigVersionForUI(version)),
  }));

export const createBotExchangeConfig = (botId: string, data: {
  credentialId?: string;       // Legacy: user_exchange_credentials ID
  exchangeAccountId?: string;  // New: exchange_accounts ID (preferred)
  exchange?: string;           // Exchange name (e.g., 'binance')
  environment?: BotEnvironment;
  tradingCapitalUsd?: number;
  enabledSymbols?: string[];
  riskConfig?: RiskConfig;
  executionConfig?: ExecutionConfig;
  profileOverrides?: Record<string, unknown>;
  notes?: string;
}) =>
  api
    .post<{ message: string; config: BotExchangeConfig }>(`/bot-instances/${botId}/exchanges`, {
      ...data,
      riskConfig: normalizeRiskConfigForApi(data.riskConfig),
      executionConfig: normalizeExecutionConfigForApi(data.executionConfig),
    })
    .then((res) => ({ ...res.data, config: normalizeBotExchangeConfigForUI(res.data.config) }));

export const updateBotExchangeConfig = (botId: string, configId: string, data: Partial<BotExchangeConfig>) =>
  api
    .put<{ message: string; config: BotExchangeConfig }>(
      `/bot-instances/${botId}/exchanges/${configId}`,
      normalizeBotExchangeConfigPayloadForApi(data)
    )
    .then((res) => ({ ...res.data, config: normalizeBotExchangeConfigForUI(res.data.config) }));

export const deleteBotExchangeConfig = (botId: string, configId: string) =>
  api.delete<{ message: string }>(`/bot-instances/${botId}/exchanges/${configId}`).then((res) => res.data);

export const activateBotExchangeConfig = (botId: string, configId: string) =>
  api
    .post<{ message: string; config: BotExchangeConfig }>(`/bot-instances/${botId}/exchanges/${configId}/activate`)
    .then((res) => ({ ...res.data, config: normalizeBotExchangeConfigForUI(res.data.config) }));

export const deactivateBotExchangeConfig = (botId: string, configId: string) =>
  api
    .post<{ message: string; config: BotExchangeConfig }>(`/bot-instances/${botId}/exchanges/${configId}/deactivate`)
    .then((res) => ({ ...res.data, config: normalizeBotExchangeConfigForUI(res.data.config) }));

export const transitionBotExchangeConfigState = (botId: string, configId: string, state: string, errorMessage?: string) =>
  api
    .post<{ message: string; config: BotExchangeConfig }>(`/bot-instances/${botId}/exchanges/${configId}/state`, { state, errorMessage })
    .then((res) => ({ ...res.data, config: normalizeBotExchangeConfigForUI(res.data.config) }));

export const fetchBotExchangeConfigVersions = (botId: string, configId: string, limit = 20) =>
  api
    .get<{ versions: BotConfigVersion[] }>(`/bot-instances/${botId}/exchanges/${configId}/versions`, { params: { limit } })
    .then((res) => ({ ...res.data, versions: res.data.versions.map((version) => normalizeBotConfigVersionForUI(version)) }));

export const fetchBotExchangeConfigVersion = (botId: string, configId: string, versionNumber: number) =>
  api.get<{ version: BotConfigVersion }>(`/bot-instances/${botId}/exchanges/${configId}/versions/${versionNumber}`).then((res) => ({
    ...res.data,
    version: normalizeBotConfigVersionForUI(res.data.version),
  }));

export const rollbackBotExchangeConfig = (botId: string, configId: string, targetVersion: number) =>
  api
    .post<{ message: string; config: BotExchangeConfig; newVersion: number; rolledBackFrom: number }>(
      `/bot-instances/${botId}/exchanges/${configId}/versions/${targetVersion}/rollback`
    )
    .then((res) => ({ ...res.data, config: normalizeBotExchangeConfigForUI(res.data.config) }));

export interface VersionDiff {
  versionA: number;
  versionB: number;
  changes: Array<{
    field: string;
    label: string;
    from: unknown;
    to: unknown;
  }>;
}

export const compareBotExchangeConfigVersions = (botId: string, configId: string, versionA: number, versionB: number) =>
  api.get<{ diff: VersionDiff }>(`/bot-instances/${botId}/exchanges/${configId}/versions/compare`, { params: { versionA, versionB } }).then((res) => res.data);

export interface VersionPerformance {
  trade_count: number;
  filled_count: number;
  cancelled_count: number;
  total_volume: number;
  first_trade: string | null;
  last_trade: string | null;
}

export interface BotConfigVersionWithPerformance extends BotConfigVersion {
  performance: VersionPerformance;
}

export const fetchBotExchangeConfigVersionsWithPerformance = (botId: string, configId: string, limit = 10) =>
  api
    .get<{ versions: BotConfigVersionWithPerformance[] }>(`/bot-instances/${botId}/exchanges/${configId}/versions/performance`, { params: { limit } })
    .then((res) => ({
      ...res.data,
      versions: res.data.versions.map((version) => ({
        ...normalizeBotConfigVersionForUI(version),
        performance: version.performance,
      })),
    }));

// Symbol Configs
export const fetchBotSymbolConfigs = (botId: string, configId: string) =>
  api
    .get<{ symbols: BotSymbolConfig[] }>(`/bot-instances/${botId}/exchanges/${configId}/symbols`)
    .then((res) => ({ ...res.data, symbols: res.data.symbols.map((symbol) => normalizeBotSymbolConfigForUI(symbol)) }));

export const updateBotSymbolConfig = (botId: string, configId: string, symbol: string, data: Partial<BotSymbolConfig>) =>
  api
    .put<{ message: string; symbol: BotSymbolConfig }>(
      `/bot-instances/${botId}/exchanges/${configId}/symbols/${encodeURIComponent(symbol)}`,
      normalizeBotSymbolConfigPayloadForApi(data)
    )
    .then((res) => ({ ...res.data, symbol: normalizeBotSymbolConfigForUI(res.data.symbol) }));

export const bulkUpdateBotSymbolConfigs = (botId: string, configId: string, symbols: Record<string, Partial<BotSymbolConfig>>) =>
  api
    .put<{ message: string; symbols: BotSymbolConfig[] }>(`/bot-instances/${botId}/exchanges/${configId}/symbols`, {
      symbols: Object.fromEntries(
        Object.entries(symbols).map(([symbol, data]) => [symbol, normalizeBotSymbolConfigPayloadForApi(data)])
      ),
    })
    .then((res) => ({ ...res.data, symbols: res.data.symbols.map((symbol) => normalizeBotSymbolConfigForUI(symbol)) }));

export const deleteBotSymbolConfig = (botId: string, configId: string, symbol: string) =>
  api.delete<{ message: string }>(`/bot-instances/${botId}/exchanges/${configId}/symbols/${encodeURIComponent(symbol)}`).then((res) => res.data);

// Tenant Risk Policy
export const fetchTenantRiskPolicy = () =>
  api.get<TenantRiskPolicyResponse>("/bot-instances/policy").then((res) => ({
    ...res.data,
    policy: normalizeTenantRiskPolicyForUI(res.data.policy),
  }));

export const updateTenantRiskPolicy = (data: Partial<TenantRiskPolicy>) =>
  api
    .put<{ message: string; policy: TenantRiskPolicy }>("/bot-instances/policy", normalizeTenantRiskPolicyForApi(data))
    .then((res) => ({ ...res.data, policy: normalizeTenantRiskPolicyForUI(res.data.policy) }));

export const enableLiveTrading = () =>
  api.post<{ message: string; policy: TenantRiskPolicy }>("/bot-instances/policy/enable-live").then((res) => ({
    ...res.data,
    policy: normalizeTenantRiskPolicyForUI(res.data.policy),
  }));

// Active Config
export const fetchActiveConfig = () =>
  api.get<ActiveConfigResponse>("/bot-instances/active").then((res) => ({
    ...res.data,
    active: res.data.active ? normalizeBotExchangeConfigForUI(res.data.active) : null,
    symbols: res.data.symbols.map((symbol) => normalizeBotSymbolConfigForUI(symbol)),
    policy: normalizeTenantRiskPolicyForUI(res.data.policy),
  }));

// Security settings
export interface SecuritySettings {
  twoFactorEnabled: boolean;
  sessionTimeout: number;
  requireTwoFactorForLive: boolean;
}

export const fetchSecuritySettings = () =>
  api.get<SecuritySettings>("/settings/security").then((res) => res.data);

export const updateSecuritySettings = (payload: Partial<SecuritySettings>) =>
  api.put<SecuritySettings>("/settings/security", payload).then((res) => res.data);

// API keys
export interface ApiKeyMeta {
  id: string;
  label: string;
  createdAt: string;
  lastUsedAt?: string | null;
  prefix: string;
  apiKey?: string; // only returned on create
}

export const fetchApiKeys = () =>
  api.get<{ keys: ApiKeyMeta[] }>("/settings/api-keys").then((res) => res.data.keys);

export const createApiKey = (label?: string) =>
  api.post<{ key: ApiKeyMeta }>("/settings/api-keys", { label }).then((res) => res.data.key);

export const deleteApiKey = (id: string) =>
  api.delete(`/settings/api-keys/${id}`).then(() => ({ success: true }));

export const validateApiKey = (apiKey: string) =>
  api.post<{ valid: boolean; key: ApiKeyMeta }>("/settings/api-keys/validate", { apiKey }).then((res) => res.data);

export const validateTwoFactor = (code: string) =>
  api.post<{ valid: boolean; lastValidatedAt?: string }>("/settings/security/validate-2fa", { code }).then((res) => res.data);

export const enrollTwoFactor = () =>
  api.post<{ otpauthUrl: string; qr: string; secret: string }>("/settings/security/2fa/enroll").then((res) => res.data);

export const confirmTwoFactor = (code: string) =>
  api.post<{ enabled: boolean }>("/settings/security/2fa/confirm", { code }).then((res) => res.data);

export const disableTwoFactor = () =>
  api.post<{ disabled: boolean }>("/settings/security/2fa/disable").then((res) => res.data);

export const generateBackupCodes = () =>
  api.post<{ backupCodes: string[] }>("/settings/security/2fa/backup-codes").then((res) => res.data.backupCodes);

// Notifications settings
export interface NotificationChannel {
  id: string;
  type: string;
  label: string;
  enabled: boolean;
  config: Record<string, any>;
  createdAt?: string;
}

export interface NotificationRoutingRule {
  severity: string;
  channels: string[];
}

export const fetchNotificationChannels = () =>
  api.get<{ channels: NotificationChannel[] }>("/settings/notifications/channels").then((res) => res.data.channels);

export const createNotificationChannel = (payload: Partial<NotificationChannel> & { type: string }) =>
  api.post<{ channel: NotificationChannel }>("/settings/notifications/channels", payload).then((res) => res.data.channel);

export const updateNotificationChannel = (id: string, payload: Partial<NotificationChannel>) =>
  api.put<{ channel: NotificationChannel }>(`/settings/notifications/channels/${id}`, payload).then((res) => res.data.channel);

export const deleteNotificationChannel = (id: string) =>
  api.delete(`/settings/notifications/channels/${id}`).then(() => ({ success: true }));

export const fetchNotificationRouting = () =>
  api.get<{ rules: NotificationRoutingRule[] }>("/settings/notifications/routing").then((res) => res.data);

export const updateNotificationRouting = (routing: { rules: NotificationRoutingRule[] }) =>
  api.put<{ rules: NotificationRoutingRule[] }>("/settings/notifications/routing", routing).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// TRADE HISTORY API
// ═══════════════════════════════════════════════════════════════

import type {
  TradeHistoryResponse,
  TradeDetailResponse,
  RuntimePredictionSnapshotResponse,
  PredictionEventsResponse,
} from "./types";

export interface TradeHistoryParams {
  limit?: number;
  offset?: number;
  symbol?: string;
  side?: string;
  status?: string;
  includeAll?: boolean;
  showEntries?: boolean;
  startDate?: string;
  endDate?: string;
  minPnl?: number;
  maxPnl?: number;
  includeDecisionTrace?: boolean;
  exchangeAccountId?: string;
  botId?: string;
}

export const fetchTradeHistory = (params?: TradeHistoryParams) =>
  api
    .get<TradeHistoryResponse>("/dashboard/trade-history", { params })
    .then((res) => res.data);

export const fetchTradeDetail = (tradeId: string) =>
  api
    .get<TradeDetailResponse>(`/dashboard/trade-history/${tradeId}`)
    .then((res) => res.data);

export interface PredictionQueryParams {
  tenantId?: string;
  botId?: string;
  symbol?: string;
  limit?: number;
}

export const fetchRuntimePrediction = (params?: PredictionQueryParams) =>
  api
    .get<RuntimePredictionSnapshotResponse>("/runtime/prediction", {
      params: {
        tenant_id: params?.tenantId,
        bot_id: params?.botId,
        symbol: params?.symbol,
      },
    })
    .then((res) => res.data);

export const fetchPredictionHistory = (params?: PredictionQueryParams) =>
  api
    .get<PredictionEventsResponse>("/history/predictions", {
      params: {
        tenant_id: params?.tenantId,
        bot_id: params?.botId,
        symbol: params?.symbol,
        limit: params?.limit,
      },
    })
    .then((res) => res.data);

// Pending Orders / Execution stats
export const fetchPendingOrders = (params?: { exchangeAccountId?: string; botId?: string }) => {
  const queryParams: Record<string, string> = {};
  if (params?.exchangeAccountId) queryParams.exchangeAccountId = params.exchangeAccountId;
  if (params?.botId) queryParams.botId = params.botId;
  return api.get<{ orders: any[] }>("/dashboard/pending-orders", { params: queryParams }).then((res) => res.data);
};

export const cancelOrder = (orderId: string, symbol?: string, exchange?: string) =>
  api
    .post<{ success: boolean; message: string }>("/dashboard/orders/cancel", {
      orderId,
      symbol,
      exchange,
    })
    .then((res) => res.data);

export const replaceOrder = (params: { orderId: string; symbol?: string; exchange?: string; newPrice?: number; newSize?: number }) =>
  api
    .post<{ success: boolean; message: string }>("/dashboard/orders/replace", params)
    .then((res) => res.data);

export interface ExecutionStatsParams {
  exchangeAccountId?: string;
  botId?: string;
}

export const fetchExecutionStats = (params?: ExecutionStatsParams) => {
  return api.get<any>("/dashboard/execution", { params }).then((res) => res.data);
};

// Dashboard risk snapshot (supports scope filtering)
export const fetchDashboardRisk = (params?: { exchangeAccountId?: string; botId?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.exchangeAccountId) queryParams.set("exchangeAccountId", params.exchangeAccountId);
  if (params?.botId) queryParams.set("botId", params.botId);
  const query = queryParams.toString();
  return api
    .get<any>(`/dashboard/risk${query ? `?${query}` : ""}`)
    .then((res) => normalizeDashboardRiskForUI(res.data));
};

// ═══════════════════════════════════════════════════════════════
// EXCHANGE CREDENTIALS API (consolidated from exchange-credentials.tsx)
// ═══════════════════════════════════════════════════════════════

export interface ExchangeCredential {
  id: string;
  userId: string;
  exchange: string;
  label: string;
  status: "pending" | "verified" | "failed";
  isDemo: boolean;
  createdAt: string;
  verifiedAt?: string;
  balance?: number;
  tradingCapital?: number;
  riskConfig?: Record<string, unknown>;
  executionConfig?: Record<string, unknown>;
}

export interface ExchangeLimits {
  maxLeverage: number;
  minOrderSize: Record<string, number>;
  maxOrderSize: Record<string, number>;
}

export const fetchExchangeCredentials = () =>
  api.get<{ credentials: ExchangeCredential[] }>("/exchange-credentials").then((res) => res.data);

export const fetchExchangeProfile = () =>
  api.get<{ profile: TradeProfile }>("/exchange-credentials/profile").then((res) => res.data);

export const fetchExchangeLimits = (exchange: string) =>
  api.get<{ limits: ExchangeLimits }>(`/exchange-credentials/limits/${exchange}`).then((res) => res.data);

export const createExchangeCredential = (data: {
  exchange: string;
  label: string;
  isDemo: boolean;
  apiKey: string;
  secretKey: string;
  passphrase?: string;
}) =>
  api.post<{ credential: ExchangeCredential }>("/exchange-credentials", data).then((res) => res.data);

export const deleteExchangeCredential = (credentialId: string) =>
  api.delete<{ message: string }>(`/exchange-credentials/${credentialId}`).then((res) => res.data);

export const verifyExchangeCredential = (credentialId: string) =>
  api.post<{ credential: ExchangeCredential }>(`/exchange-credentials/${credentialId}/verify`).then((res) => res.data);

export const refreshCredentialBalance = (credentialId: string) =>
  api.post<{ credential: ExchangeCredential; balance: number }>(`/exchange-credentials/${credentialId}/refresh-balance`).then((res) => res.data);

export const updateCredentialRiskConfig = (credentialId: string, riskConfig: Record<string, unknown>) =>
  api.put<{ message: string }>(`/exchange-credentials/${credentialId}/config/risk`, riskConfig).then((res) => res.data);

export const updateCredentialExecutionConfig = (credentialId: string, executionConfig: Record<string, unknown>) =>
  api.put<{ message: string }>(`/exchange-credentials/${credentialId}/config/execution`, executionConfig).then((res) => res.data);

export const updateCredentialMetadata = (credentialId: string, data: { label?: string; isDemo?: boolean }) =>
  api.put<{ message: string }>(`/exchange-credentials/${credentialId}`, data).then((res) => res.data);

export const updateCredentialSecrets = (credentialId: string, secrets: { apiKey?: string; secretKey?: string; passphrase?: string }) =>
  api.put<{ message: string }>(`/exchange-credentials/${credentialId}/secrets`, secrets).then((res) => res.data);

export const updateAccountBalance = (accountBalance: number) =>
  api.put<{ message: string; profile: TradeProfile }>("/exchange-credentials/profile/balance", { accountBalance }).then((res) => res.data);

export const updateTradingCapital = (credentialId: string, tradingCapital: number) =>
  api.put<{ message: string }>(`/exchange-credentials/${credentialId}/trading-capital`, { tradingCapital }).then((res) => res.data);

export const setActiveCredential = (credentialId: string) =>
  api.put<{ message: string }>("/exchange-credentials/profile/active", { credentialId }).then((res) => res.data);

export const setTradingMode = (mode: "paper" | "live") =>
  api.put<{ message: string }>("/exchange-credentials/profile/mode", { mode }).then((res) => res.data);

export const updateEnabledTokens = (exchange: string, tokens: string[]) =>
  api.put<{ message: string }>(`/exchange-credentials/profile/tokens/${exchange}`, { tokens }).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// DASHBOARD ADDITIONAL ENDPOINTS
// ═══════════════════════════════════════════════════════════════

export interface ExchangePosition {
  symbol: string;
  side: "LONG" | "SHORT";
  quantity: number;
  entryPrice: number;
  markPrice: number;
  unrealizedPnl: number;
  leverage: number;
  marginType: string;
  liquidationPrice: number;
  breakEvenPrice: number;
  stopLoss: number | null;
  takeProfit: number | null;
}

export const fetchExchangePositions = () =>
  api.get<{ positions: ExchangePosition[]; exchange: string; isDemo: boolean }>("/dashboard/exchange-positions").then((res) => res.data);

// Bot positions from Redis (primary source for active bot positions)
export interface BotPosition {
  symbol: string;
  side: string;
  size: number;
  entry_price?: number | null;
  reference_price?: number | null;
  current_price?: number | null;
  pnl?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  opened_at?: number | null;
  age_sec?: number | null;
  guard_status?: string | null;
  prediction_confidence?: number | null;
  estimated_round_trip_fee_usd?: number | null;
  estimatedRoundTripFeeUsd?: number | null;
  estimated_net_unrealized_after_fees?: number | null;
  estimatedNetUnrealizedAfterFees?: number | null;
  exchange_account_id: string | null;
  bot_id: string | null;
}

export const fetchBotPositions = (options?: { exchangeAccountId?: string; botId?: string }) =>
  api.get<{ positions: BotPosition[]; data?: BotPosition[]; updatedAt?: number }>("/dashboard/positions", {
    params: {
      ...(options?.exchangeAccountId && { exchangeAccountId: options.exchangeAccountId }),
      ...(options?.botId && { botId: options.botId }),
    }
  }).then((res) => res.data);

export const fetchOrphanedPositions = () =>
  api.get<{
    orphanedPositions: ExchangePosition[];
    botPositions: unknown[];
    exchangePositions: ExchangePosition[];
    exchange: string;
  }>("/dashboard/orphaned-positions").then((res) => res.data);

export const closePosition = (symbol: string, side: string, quantity: number) =>
  api.post<{ orderId: string; status: string }>("/dashboard/close-position", { symbol, side, quantity }).then((res) => res.data);

export const closeAllOrphanedPositions = () =>
  api.post<{ closed: Array<{ symbol: string; success: boolean; error?: string }>; count: number }>("/dashboard/close-all-orphaned").then((res) => res.data);

export const closeAllPositions = (options?: { botId?: string; exchangeAccountId?: string }) =>
  (() => {
    const authUser = getAuthUser();
    const effectiveTenantId = authUser?.id;
    return api.post<{ 
      closed: Array<{ symbol: string; success: boolean; error?: string; type?: string }>; 
      count: number;
      paperClosed?: number;
      exchangeClosed?: number;
    }>("/dashboard/close-all-positions", { 
      action: "flatten",
      tenant_id: effectiveTenantId,
      bot_id: options?.botId,
      close_positions: true,
    }).then((res) => res.data);
  })();

export const cancelAllOrders = (options?: { botId?: string; exchangeAccountId?: string }) =>
  (() => {
    const authUser = getAuthUser();
    const effectiveTenantId = authUser?.id;
    return api.post<{ 
      success: boolean;
      cancelled: number;
      message?: string;
    }>("/dashboard/cancel-all-orders", { 
      action: "cancel_all",
      tenant_id: effectiveTenantId,
      bot_id: options?.botId,
      cancel_orders: true,
    }).then((res) => res.data);
  })();

export const fetchSlTpEvents = (limit = 50) =>
  api.get<{ events: unknown[]; count: number }>("/dashboard/sl-tp-events", { params: { limit } }).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// STRATEGY INSTANCES API
// ═══════════════════════════════════════════════════════════════

export interface StrategyInstance {
  id: string;
  user_id: string | null;
  template_id: string;
  name: string;
  description: string | null;
  params: Record<string, unknown>;
  status: 'active' | 'deprecated' | 'archived';
  usage_count: number;
  last_backtest_at: string | null;
  last_backtest_summary: Record<string, unknown> | null;
  version: number;
  created_at: string;
  updated_at: string;
  is_system_template?: boolean;
}

export interface StrategyInstancesResponse {
  success: boolean;
  instances: StrategyInstance[];
  count: number;
}

export const fetchStrategyInstances = (params?: { status?: string; templateId?: string; includeSystemTemplates?: boolean }) =>
  api.get<StrategyInstancesResponse>("/strategy-instances", { params }).then((res) => res.data);

export const fetchStrategyInstanceTemplates = () =>
  api.get<{ success: boolean; templates: StrategyInstance[]; count: number }>("/strategy-instances/templates").then((res) => res.data);

export const fetchStrategyInstance = (id: string) =>
  api.get<{ success: boolean; instance: StrategyInstance }>(`/strategy-instances/${id}`).then((res) => res.data);

export const fetchStrategyInstanceUsage = (id: string) =>
  api.get<{ success: boolean; instance_id: string; usage_count: number; profiles: Array<{ id: string; name: string; environment: string; status: string; is_active: boolean }> }>(`/strategy-instances/${id}/usage`).then((res) => res.data);

export const createStrategyInstance = (data: { templateId: string; name: string; description?: string; params?: Record<string, unknown> }) =>
  api.post<{ success: boolean; instance: StrategyInstance }>("/strategy-instances", data).then((res) => res.data);

export const updateStrategyInstance = (id: string, data: { name?: string; description?: string; params?: Record<string, unknown>; status?: string }) =>
  api.put<{ success: boolean; instance: StrategyInstance }>(`/strategy-instances/${id}`, data).then((res) => res.data);

export const cloneStrategyInstance = (id: string, name?: string) =>
  api.post<{ success: boolean; instance: StrategyInstance }>(`/strategy-instances/${id}/clone`, { name }).then((res) => res.data);

export const archiveStrategyInstance = (id: string) =>
  api.post<{ success: boolean; instance: StrategyInstance }>(`/strategy-instances/${id}/archive`).then((res) => res.data);

export const deprecateStrategyInstance = (id: string) =>
  api.post<{ success: boolean; instance: StrategyInstance }>(`/strategy-instances/${id}/deprecate`).then((res) => res.data);

export const restoreStrategyInstance = (id: string) =>
  api.post<{ success: boolean; instance: StrategyInstance }>(`/strategy-instances/${id}/restore`).then((res) => res.data);

export const deleteStrategyInstance = (id: string) =>
  api.delete<{ success: boolean; deleted: boolean; id: string }>(`/strategy-instances/${id}`).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// USER PROFILES API
// ═══════════════════════════════════════════════════════════════

export interface StrategyComposition {
  instance_id: string;
  weight: number;
  priority: number;
  enabled: boolean;
}

export interface ProfileRiskConfig {
  risk_per_trade_pct?: number;
  max_leverage?: number;
  max_positions?: number;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  max_drawdown_pct?: number;
  max_daily_loss_pct?: number;
}

export interface ProfileConditions {
  required_session?: string;
  required_volatility?: string;
  required_trend?: string;
  max_spread_bps?: number;
  min_depth_usd?: number;
  min_volume_24h?: number;
}

export interface ProfileLifecycle {
  cooldown_seconds?: number;
  disable_after_consecutive_losses?: number;
  protection_mode_threshold_pct?: number;
  warmup_seconds?: number;
  max_trades_per_hour?: number;
}

export interface ProfileExecution {
  order_type_preference?: string;
  maker_taker_bias?: number;
  max_slippage_bps?: number;
  time_in_force?: string;
  reduce_only_exits?: boolean;
}

export interface UserProfile {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  base_profile_id: string | null;
  environment: 'dev' | 'paper' | 'live';
  strategy_composition: StrategyComposition[];
  risk_config: ProfileRiskConfig;
  conditions: ProfileConditions;
  lifecycle: ProfileLifecycle;
  execution: ProfileExecution;
  status: 'draft' | 'active' | 'disabled' | 'archived';
  is_active: boolean;
  version: number;
  promoted_from_id: string | null;
  promoted_at: string | null;
  promotion_notes: string | null;
  paper_start_at: string | null;
  paper_trades_count: number;
  paper_pnl_total: number;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface ProfileVersion {
  id: string;
  profile_id: string;
  version: number;
  config_snapshot: Record<string, unknown>;
  change_summary: string | null;
  changed_by: string | null;
  change_reason: string | null;
  diff_from_previous: Record<string, unknown> | null;
  created_at: string;
}

export interface UserProfileWithVersions extends UserProfile {
  versions: ProfileVersion[];
}

export interface UserProfilesResponse {
  success: boolean;
  profiles: UserProfile[];
  count: number;
}

export const fetchUserProfiles = (params?: { environment?: string; status?: string; isActive?: boolean }) =>
  api.get<UserProfilesResponse>("/profiles", { params }).then((res) => res.data);

export const fetchUserProfile = (id: string) =>
  api.get<{ success: boolean; profile: UserProfileWithVersions }>(`/profiles/${id}`).then((res) => res.data);

export const fetchProfileDiff = (id: string, versionA: number, versionB: number) =>
  api.get<{ success: boolean; diff: { versionA: number; versionB: number; changes: Array<{ field: string; from: unknown; to: unknown }> } }>(`/profiles/${id}/diff/${versionA}/${versionB}`).then((res) => res.data);

export const createUserProfile = (data: {
  name: string;
  description?: string;
  baseProfileId?: string;
  environment?: string;
  strategyComposition?: StrategyComposition[];
  riskConfig?: ProfileRiskConfig;
  conditions?: ProfileConditions;
  lifecycle?: ProfileLifecycle;
  execution?: ProfileExecution;
  tags?: string[];
}) => api.post<{ success: boolean; profile: UserProfile }>("/profiles", data).then((res) => res.data);

export const updateUserProfile = (id: string, data: {
  name?: string;
  description?: string;
  strategyComposition?: StrategyComposition[];
  riskConfig?: ProfileRiskConfig;
  conditions?: ProfileConditions;
  lifecycle?: ProfileLifecycle;
  execution?: ProfileExecution;
  status?: string;
  isActive?: boolean;
  tags?: string[];
  changeReason?: string;
}) => api.put<{ success: boolean; profile: UserProfile }>(`/profiles/${id}`, data).then((res) => res.data);

export const promoteUserProfile = (id: string, notes?: string) =>
  api.post<{ success: boolean; profile: UserProfile; message: string }>(`/profiles/${id}/promote`, { notes }).then((res) => res.data);

export const cloneUserProfile = (id: string, data?: { name?: string; environment?: string }) =>
  api.post<{ success: boolean; profile: UserProfile; message: string }>(`/profiles/${id}/clone`, data).then((res) => res.data);

export const activateUserProfile = (id: string) =>
  api.post<{ success: boolean; profile: UserProfile }>(`/profiles/${id}/activate`).then((res) => res.data);

export const deactivateUserProfile = (id: string) =>
  api.post<{ success: boolean; profile: UserProfile }>(`/profiles/${id}/deactivate`).then((res) => res.data);

export const archiveUserProfile = (id: string) =>
  api.post<{ success: boolean; profile: UserProfile }>(`/profiles/${id}/archive`).then((res) => res.data);

export const deleteUserProfile = (id: string) =>
  api.delete<{ success: boolean; deleted: boolean; id: string }>(`/profiles/${id}`).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// DEPLOYMENT API
// ═══════════════════════════════════════════════════════════════

export interface MountedProfileInfo {
  id: string;
  name: string;
  environment: string;
  mountedVersion: number;
  currentVersion: number;
  isOutdated: boolean;
  status: string;
  isActive: boolean;
}

export interface DeploymentStatus {
  exchangeConfigId: string;
  exchange: string;
  environment: string;
  state: string;
  isActive: boolean;
  mountedProfile: MountedProfileInfo | null;
  mountedAt: string | null;
  lastHeartbeat: string | null;
  decisionsCount: number;
  tradesCount: number;
}

export interface DeploymentsResponse {
  success: boolean;
  deployments: DeploymentStatus[];
  count: number;
}

export const mountProfile = (exchangeConfigId: string, profileId: string) =>
  api.post<{ success: boolean; config: Record<string, unknown>; message: string }>("/deployment/mount", { exchangeConfigId, profileId }).then((res) => res.data);

export const unmountProfile = (exchangeConfigId: string) =>
  api.post<{ success: boolean; config: Record<string, unknown>; message: string }>("/deployment/unmount", { exchangeConfigId }).then((res) => res.data);

export const fetchDeploymentStatus = (exchangeConfigId: string) =>
  api.get<{ success: boolean; deployment: DeploymentStatus }>(`/deployment/status/${exchangeConfigId}`).then((res) => res.data);

export const refreshDeployment = (exchangeConfigId: string) =>
  api.post<{ success: boolean; config: Record<string, unknown>; message: string }>("/deployment/refresh", { exchangeConfigId }).then((res) => res.data);

export const fetchDeployments = (environment?: string) =>
  api.get<DeploymentsResponse>("/deployment/list", { params: { environment } }).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// FORENSIC REPLAY API
// ═══════════════════════════════════════════════════════════════

export interface ReplayEvent {
  id: string;
  timestamp: number;
  type: "decision" | "trade" | "position" | "snapshot" | "alert" | "rejection";
  symbol: string;
  severity?: "info" | "warning" | "error";
  data: Record<string, unknown>;
}

export interface ReplayEventsResponse {
  success: boolean;
  events: ReplayEvent[];
  total: number;
  hasMore: boolean;
}

export interface ReplaySnapshotResponse {
  success: boolean;
  data: {
    timestamp: string;
    symbol: string;
    marketSnapshot: {
      price?: number;
      spread?: number;
      volume?: number;
      depth?: Record<string, unknown>;
      gateStates?: Record<string, unknown>;
      regimeLabel?: string;
      dataQualityScore?: number;
    } | null;
    nearestDecision: {
      timestamp: string;
      outcome: string;
      stageResults?: Record<string, unknown>;
      gateResults?: Record<string, unknown>;
      featureContributions?: Array<{ name: string; value: number; zScore: number }>;
    } | null;
    currentPosition: {
      side: string;
      size: number;
      entryPrice: number;
      unrealizedPnl: number;
    } | null;
    recentTrades: Array<{
      id: string;
      timestamp: string;
      side: string;
      size: number;
      price: number;
      pnl: number | null;
    }>;
  };
}

export interface CompareSessionsRequest {
  baselineSessionId?: string;
  compareSessionId?: string;
  symbol: string;
  timeRange: { start: string; end: string };
}

export interface CompareSessionsResponse {
  success: boolean;
  data: {
    baselineSessionId?: string;
    compareSessionId?: string;
    symbol: string;
    timeRange: { start: string; end: string };
    summary: {
      baseline: { tradeCount: number; rejectCount: number; decisionCount: number; totalPnl: number; avgSlippage: number };
      compare: { tradeCount: number; rejectCount: number; decisionCount: number; totalPnl: number; avgSlippage: number };
      diff: { tradeCountDelta: number; rejectCountDelta: number; pnlDelta: number; avgSlippageDelta: number };
    };
    addedEvents: ReplayEvent[];
    removedEvents: ReplayEvent[];
    changedDecisions: Array<{
      timestamp: number;
      baseline: ReplayEvent;
      compare: ReplayEvent;
      changes: Record<string, unknown>;
    }>;
  };
}

export interface SessionIntegrityResponse {
  success: boolean;
  data: {
    sessionId: string;
    symbol: string;
    timeRange: { start: string; end: string };
    integrity: {
      score: string;
      snapshotCoverage: string;
      dataGaps: number;
      expectedSnapshots: number;
      actualSnapshots: number;
    };
    reproducibility: {
      datasetHash: string;
      configVersion: number | null;
      botId: string | null;
      exchangeAccountId: string | null;
    };
  };
}

export interface FeatureDictionaryResponse {
  success: boolean;
  data: Record<string, Array<{
    name: string;
    displayName: string;
    description: string;
    unit: string;
    typicalRange?: { min: number; max: number };
  }>>;
}

export interface ReplayAnnotation {
  id: string;
  session_id: string;
  timestamp: string;
  annotation_type: string;
  title: string;
  content: string;
  tags: string[];
  created_by: string;
  created_at: string;
}

export interface OutcomeSummaryResponse {
  success: boolean;
  data: {
    trades: {
      count: number;
      totalPnl: number;
      avgSlippageBps: string;
      maxPnl: number;
      minPnl: number;
    };
    decisions: {
      approved: number;
      rejected: number;
      avgLatencyMs: string;
    };
    maxDrawdown: number;
  };
}

// Fetch paginated replay events
export const fetchReplayEvents = (
  symbol: string,
  start: string,
  end: string,
  options?: { types?: string; limit?: number; offset?: number; includeDetails?: boolean }
) =>
  api.get<ReplayEventsResponse>(`/replay/${symbol}/events`, {
    params: { start, end, ...options },
  }).then((res) => res.data);

// Fetch snapshot at specific timestamp
export const fetchReplaySnapshot = (symbol: string, timestamp: string) =>
  api.get<ReplaySnapshotResponse>(`/replay/${symbol}/snapshot/${timestamp}`).then((res) => res.data);

// Compare two sessions
export const compareReplaySessions = (data: CompareSessionsRequest) =>
  api.post<CompareSessionsResponse>("/replay/compare", data).then((res) => res.data);

// Get session integrity metadata (legacy - requires session ID)
export const fetchSessionIntegrity = (sessionId: string) =>
  api.get<SessionIntegrityResponse>(`/replay/integrity/${sessionId}`).then((res) => res.data);

// Get integrity metrics by symbol and time range (no session ID required)
export const fetchIntegrityByTimeRange = (symbol: string, start: string, end: string) =>
  api.get<SessionIntegrityResponse>(`/replay/integrity`, {
    params: { symbol, start, end }
  }).then((res) => res.data);

// Get feature dictionary
export const fetchFeatureDictionary = () =>
  api.get<FeatureDictionaryResponse>("/replay/features/dictionary").then((res) => res.data);

// Create annotation
export const createReplayAnnotation = (data: {
  sessionId: string;
  timestamp: string;
  annotationType?: string;
  title?: string;
  content?: string;
  tags?: string[];
}) =>
  api.post<{ success: boolean; data: ReplayAnnotation }>("/replay/annotations", data).then((res) => res.data);

// Get annotations for session
export const fetchReplayAnnotations = (sessionId: string) =>
  api.get<{ success: boolean; data: ReplayAnnotation[] }>(`/replay/annotations/${sessionId}`).then((res) => res.data);

// Delete annotation
export const deleteReplayAnnotation = (annotationId: string) =>
  api.delete<{ success: boolean }>(`/replay/annotations/${annotationId}`).then((res) => res.data);

// Get outcome summary
export const fetchOutcomeSummary = (symbol: string, start: string, end: string) =>
  api.get<OutcomeSummaryResponse>("/replay/summary", { params: { symbol, start, end } }).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// LOSS PREVENTION API
// ═══════════════════════════════════════════════════════════════

export interface LossPreventionMetricsResponse {
  success: boolean;
  data: {
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
  };
  error?: string;
  updatedAt: number;
}

export const fetchLossPreventionMetrics = (params?: { 
  botId?: string; 
  tenantId?: string;
  windowHours?: number;
}) => {
  const queryParams = new URLSearchParams();
  if (params?.botId) queryParams.set('bot_id', params.botId);
  if (params?.tenantId) queryParams.set('tenant_id', params.tenantId);
  if (params?.windowHours) queryParams.set('window_hours', String(params.windowHours));
  const queryString = queryParams.toString();
  return api.get<LossPreventionMetricsResponse>(
    `/loss-prevention/metrics${queryString ? `?${queryString}` : ''}`
  ).then((res) => res.data);
};

// ═══════════════════════════════════════════════════════════════
// DATA BACKFILL API
// ═══════════════════════════════════════════════════════════════

import type {
  BackfillRequest,
  BackfillResponse,
  BackfillProgressResponse,
  BackfillResultResponse,
  GapBackfillRequest,
  BackfillJobsResponse,
} from "./types";

export const startBackfill = (request: BackfillRequest) =>
  api
    .post<BackfillResponse>("/research/backfill", request)
    .then((res) => res.data);

export const getBackfillProgress = (jobId: string) =>
  api
    .get<BackfillProgressResponse>(`/research/backfill/${jobId}/progress`)
    .then((res) => res.data);

export const getBackfillResult = (jobId: string) =>
  api
    .get<BackfillResultResponse>(`/research/backfill/${jobId}/result`)
    .then((res) => res.data);

export const backfillGap = (request: GapBackfillRequest) =>
  api
    .post<BackfillResponse>("/research/backfill/gap", request)
    .then((res) => res.data);

export const listBackfillJobs = () =>
  api
    .get<BackfillJobsResponse>("/research/backfill/jobs")
    .then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// SHADOW MODE COMPARISON API
// ═══════════════════════════════════════════════════════════════

export interface ShadowComparisonResult {
  timestamp: string;
  symbol: string;
  live_decision: string;
  shadow_decision: string;
  agrees: boolean;
  divergence_reason: string | null;
  live_rejection_stage: string | null;
  shadow_rejection_stage: string | null;
}

export interface ShadowMetrics {
  total_comparisons: number;
  agreements: number;
  disagreements: number;
  agreement_rate: number;
  divergence_by_reason: Record<string, number>;
  live_pnl_estimate: number;
  shadow_pnl_estimate: number;
}

export interface ShadowMetricsResponse {
  metrics: ShadowMetrics;
  enabled: boolean;
  shadow_config_version: string | null;
}

export interface ShadowComparisonsResponse {
  comparisons: ShadowComparisonResult[];
  total: number;
}

export interface PredictionScoreMetrics {
  provider: "shadow" | "live";
  lookback_hours: number;
  horizon_sec: number;
  flat_threshold_bps: number;
  samples: number;
  predictions_total: number;
  abstain_count: number;
  abstain_rate_pct: number;
  abstain_by_reason: Record<string, number>;
  exact_accuracy_pct: number;
  directional_accuracy_pct: number;
  directional_accuracy_nonflat_pct: number;
  directional_accuracy_all_pct: number;
  directional_coverage_pct: number;
  avg_confidence_pct: number;
  avg_realized_bps: number;
  ece_top1_pct: number | null;
  multiclass_brier: number | null;
  ml_score: number;
  promotion_score_v2: number;
}

export interface PredictionScoreResponse {
  enabled: boolean;
  metrics: PredictionScoreMetrics | null;
  reason: string | null;
}

const EMPTY_SHADOW_METRICS: ShadowMetrics = {
  total_comparisons: 0,
  agreements: 0,
  disagreements: 0,
  agreement_rate: 1,
  divergence_by_reason: {},
  live_pnl_estimate: 0,
  shadow_pnl_estimate: 0,
};

export const fetchShadowMetrics = async (): Promise<ShadowMetricsResponse> => {
  try {
    const res = await api.get<Record<string, unknown>>("/shadow/metrics");
    const data = res.data ?? {};

    // New wrapped shape
    if ("metrics" in data) {
      const wrapped = data as unknown as ShadowMetricsResponse;
      return {
        metrics: wrapped.metrics ?? EMPTY_SHADOW_METRICS,
        enabled: Boolean(wrapped.enabled),
        shadow_config_version: wrapped.shadow_config_version ?? null,
      };
    }

    // Legacy flat shape
    return {
      enabled: true,
      shadow_config_version:
        typeof data.shadow_config_version === "string" ? data.shadow_config_version : null,
      metrics: {
        total_comparisons: Number(data.total_comparisons ?? 0),
        agreements: Number(data.agreements ?? 0),
        disagreements: Number(data.disagreements ?? 0),
        agreement_rate: Number(data.agreement_rate ?? 1),
        divergence_by_reason: (data.divergence_by_reason as Record<string, number>) ?? {},
        live_pnl_estimate: Number(data.live_pnl_estimate ?? 0),
        shadow_pnl_estimate: Number(data.shadow_pnl_estimate ?? 0),
      },
    };
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 503) {
      return {
        enabled: false,
        shadow_config_version: null,
        metrics: EMPTY_SHADOW_METRICS,
      };
    }
    throw error;
  }
};

export const fetchShadowComparisons = async (params?: {
  limit?: number;
  start_time?: string;
  end_time?: string;
}): Promise<ShadowComparisonsResponse> => {
  try {
    const res = await api.get<Record<string, unknown>>("/shadow/comparisons", { params });
    const data = res.data ?? {};
    return {
      comparisons: (data.comparisons as ShadowComparisonResult[]) ?? [],
      total: Number(data.total ?? 0),
    };
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 503) {
      return { comparisons: [], total: 0 };
    }
    throw error;
  }
};

export const fetchPredictionScore = async (params?: {
  provider?: "shadow" | "live";
  lookback_hours?: number;
  horizon_sec?: number;
  flat_threshold_bps?: number;
  max_rows?: number;
}): Promise<PredictionScoreResponse> => {
  try {
    const res = await api.get<PredictionScoreResponse>("/shadow/prediction-score", { params });
    return res.data;
  } catch (error) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 404 || status === 503) {
      return { enabled: false, metrics: null, reason: "unavailable" };
    }
    throw error;
  }
};

// ═══════════════════════════════════════════════════════════════
// ERROR HANDLING UTILITIES
// ═══════════════════════════════════════════════════════════════

export interface ApiError {
  message: string;
  code?: string;
  details?: Record<string, unknown>;
  status?: number;
}

export function isApiError(error: unknown): error is { response: { data: ApiError; status: number } } {
  return (
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    typeof (error as { response?: unknown }).response === "object" &&
    (error as { response?: { data?: unknown } }).response?.data !== undefined
  );
}

export function extractApiError(error: unknown): ApiError {
  if (isApiError(error)) {
    const data = error.response.data;
    return {
      message: data.message || "An error occurred",
      code: data.code,
      details: data.details,
      status: error.response.status,
    };
  }
  if (error instanceof Error) {
    return { message: error.message };
  }
  return { message: "An unexpected error occurred" };
}

// Export the api instance for direct use when needed
export { api };
