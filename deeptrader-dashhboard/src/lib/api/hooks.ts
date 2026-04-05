import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useScopeHydrated } from "../../store/scope-store";
import {
  apiFetch,
  fetchFastScalperStatus,
  fetchFastScalperRejections,
  fetchMonitoringAlerts,
  fetchBotStatus,
  fetchTradingSnapshot,
  fetchSignalLabSnapshot,
  fetchDecisionFunnel,
  fetchSymbolStatus,
  fetchSymbolDecisions,
  fetchStatusNarrative,
  fetchConfirmationReadiness,
  fetchHealthSnapshot,
  fetchFastScalperLogs,
  fetchBotProfiles,
  fetchBotProfileDetail,
  fetchActiveBot,
  setActiveBot,
  fetchCandlestickData,
  fetchDrawdownData,
  fetchTradingSettings,
  fetchDataSettings,
  updateDataSettings,
  fetchOrderTypes,
  fetchStrategies,
  fetchStrategyById,
  fetchSignalConfig,
  updateSignalConfig,
  fetchAllocatorConfig,
  updateAllocatorConfig,
  fetchMarketContext,
  fetchBacktests,
  fetchBacktestDetail,
  fetchDatasets,
  fetchResearchStrategies,
  fetchBacktestPreflight,
  createBacktest,
  cancelBacktest,
  rerunBacktest,
  promoteBacktestConfig,
  deleteBacktest,
  startModelTraining,
  fetchActiveModelInfo,
  fetchModelTrainingJobs,
  fetchModelTrainingJob,
  promoteModelTrainingJob,
  fetchProfileSpecs,
  fetchProfileMetrics,
  fetchProfileRouter,
  fetchTCAAnalysis,
  fetchCapacityCurve,
  fetchTradeCost,
  calculateHistoricalVaR,
  calculateMonteCarloVaR,
  fetchVaRCalculations,
  runScenarioTest,
  fetchScenarioResults,
  fetchScenarioDetail,
  fetchWarmupStatus,
  fetchStrategyStatus,
  fetchPromotions,
  createPromotion,
  approvePromotion,
  rejectPromotion,
  completePromotion,
  fetchPromotionDetail,
  fetchConfigDiff,
  fetchAuditLog,
  exportAuditLog,
  fetchDecisionTrace,
  fetchDecisionTraces,
  fetchReplayData,
  fetchIncidents,
  fetchIncidentSnapshot,
  fetchIncident,
  createIncident,
  acknowledgeIncident,
  assignIncidentOwner,
  resolveIncident,
  updateIncidentStatus,
  fetchIncidentTimeline,
  addIncidentTimelineEvent,
  fetchIncidentEvidence,
  exportIncident,
  IncidentFilters,
  createReplaySession,
  fetchReplaySessions,
  fetchQualityMetrics,
  fetchQualityMetricsTimeseries,
  storeQualityMetrics,
  fetchFeedGaps,
  recordFeedGap,
  resolveFeedGap,
  fetchQualityAlerts,
  createQualityAlert,
  updateAlertStatus,
  fetchSymbolHealth,
  fetchReportTemplates,
  createReportTemplate,
  fetchGeneratedReports,
  storeGeneratedReport,
  fetchStrategyPortfolio,
  storeStrategyPortfolio,
  fetchStrategyCorrelations,
  storeStrategyCorrelation,
  fetchPortfolioSummary,
  storePortfolioSummary,
  TradingSettings,
  fetchTradeProfile,
  fetchAccountSettings,
  updateAccountSettings,
  fetchViewerAccounts,
  createViewerAccount,
  updateViewerAccount,
  deleteViewerAccount,
  fetchComponentVaR,
  fetchScenarioFactors,
  fetchCorrelations,
  fetchRiskLimits,
  fetchScenarioDetailWithFactors,
  fetchWfoRuns,
  fetchWfoRun,
  createWfoRun,
  // Forensic Replay API
  fetchReplayEvents,
  fetchReplaySnapshot,
  compareReplaySessions,
  fetchSessionIntegrity,
  fetchIntegrityByTimeRange,
  fetchFeatureDictionary,
  createReplayAnnotation,
  fetchReplayAnnotations,
  deleteReplayAnnotation,
  fetchOutcomeSummary,
  CompareSessionsRequest,
} from "./client";
import {
  FastScalperRejectionsResponse,
  SignalLabSnapshot,
  HealthSnapshot,
  FastScalperLogsResponse,
  BotProfilesResponse,
  BotProfileDetailResponse,
  BotProfile,
  TCAAnalysisResponse,
  CapacityCurveResponse,
  TradeCostResponse,
  CandlestickResponse,
  DrawdownResponse,
  TradeProfile,
  DataSettings,
} from "./types";
import type { AccountSettings, ViewerAccountPayload } from "./client";

export const useOverviewData = (params?: { exchangeAccountId?: string | null; botId?: string | null }) => {
  const scopeHydrated = useScopeHydrated();
  return useQuery({
    queryKey: ["ops-snapshot", params?.exchangeAccountId, params?.botId],
    queryFn: async () => {
      const settled = await Promise.allSettled([
        fetchFastScalperStatus({ botId: params?.botId || undefined }),
        fetchBotStatus({ botId: params?.botId || undefined }),
        (params?.exchangeAccountId || params?.botId)
          ? import("./client").then((m) =>
              m.fetchDashboardMetrics({
                exchangeAccountId: params.exchangeAccountId || undefined,
                botId: params.botId || undefined,
              }),
            )
          : Promise.resolve(null),
        import("./client")
          .then((m) =>
            m.api
              .get("/dashboard/live-status", {
                params: {
                  exchangeAccountId: params?.exchangeAccountId || undefined,
                  botId: params?.botId || undefined,
                },
              })
              .then((res) => res.data),
          )
          .catch(() => null),
      ]);

      const fastScalper = settled[0].status === "fulfilled" ? settled[0].value : null;
      const botStatus = settled[1].status === "fulfilled" ? settled[1].value : null;
      const scopedMetrics = settled[2].status === "fulfilled" ? settled[2].value : null;
      const liveStatus = settled[3].status === "fulfilled" ? settled[3].value : null;
      const dashboard = null;
      const alerts = null;
      return { fastScalper, dashboard, alerts, botStatus, scopedMetrics, liveStatus };
    },
    refetchInterval: 15000,
    // Refetch on window focus to catch status changes
    refetchOnWindowFocus: false,
    // Keep data fresh
    staleTime: 8000,
    placeholderData: (previousData) => previousData,
    enabled: scopeHydrated,
  });
};

export const useTradeProfile = () =>
  useQuery<TradeProfile>({
    queryKey: ["trade-profile"],
    queryFn: fetchTradeProfile,
    staleTime: 10_000,
  });

export const useTradingOpsData = (params?: { botId?: string; exchangeAccountId?: string }) =>
  useQuery({
    queryKey: ["fast-scalper-detail", params?.exchangeAccountId, params?.botId],
    queryFn: async () => {
      const [fastScalper, rejections, trading] = await Promise.all([
        fetchFastScalperStatus({ botId: params?.botId }),
        fetchFastScalperRejections(),
        fetchTradingSnapshot({ botId: params?.botId, exchangeAccountId: params?.exchangeAccountId }),
      ]);
      return { fastScalper, rejections, trading };
    },
    refetchInterval: 5000,
  });

export const useTradingSnapshot = (params?: { exchangeAccountId?: string; botId?: string }) =>
  useQuery({
    queryKey: ["trading-snapshot", params?.exchangeAccountId, params?.botId],
    queryFn: () => fetchTradingSnapshot(params),
    refetchInterval: 5000,
    staleTime: 2000,
  });

type SignalLabQueryResult = {
  rejections: FastScalperRejectionsResponse;
  snapshot: SignalLabSnapshot;
};

export const useSignalLabData = () =>
  useQuery<SignalLabQueryResult>({
    queryKey: ["fast-scalper-rejections"],
    queryFn: async () => {
      const [rejections, snapshot] = await Promise.all([
        fetchFastScalperRejections(),
        fetchSignalLabSnapshot(),
      ]);
      return { rejections, snapshot };
    },
    refetchInterval: 10_000,
  });

export const useIntelligenceData = () =>
  useQuery({
    queryKey: ["monitoring-alerts"],
    queryFn: fetchMonitoringAlerts,
    refetchInterval: 10_000,
  });

export const useHealthSnapshot = (params?: { botId?: string; tenantId?: string | null }) =>
  useQuery<HealthSnapshot>({
    queryKey: ["system-health", params?.tenantId, params?.botId],
    queryFn: () => fetchHealthSnapshot({ botId: params?.botId }),
    refetchInterval: 15000,
    staleTime: 8000,
  });

// Warmup status for trading data (AMT, HTF candles)
export const useWarmupStatus = (botId?: string | null, tenantId?: string | null) =>
  useQuery({
    queryKey: ["warmup-status", botId],
    queryFn: () => fetchWarmupStatus(botId, tenantId),
    refetchInterval: 5000, // Check every 5 seconds during warmup
    staleTime: 2000,
    enabled: !!botId, // Only fetch if botId is available
  });

// Control status (start lock)
export const useControlStatus = (botId?: string | null, tenantId?: string | null) =>
  useQuery({
    queryKey: ["control-status", tenantId, botId],
    queryFn: () => fetchControlStatus(botId, tenantId),
    refetchInterval: 4000,
    staleTime: 2000,
    enabled: !!botId,
  });

// Strategy evaluation status
export const useStrategyStatus = () =>
  useQuery({
    queryKey: ["strategy-status"],
    queryFn: fetchStrategyStatus,
    refetchInterval: 10000, // Check every 10 seconds
    staleTime: 5000,
  });

export const useFastScalperLogs = () =>
  useQuery<FastScalperLogsResponse>({
    queryKey: ["fast-scalper-logs"],
    queryFn: fetchFastScalperLogs,
    refetchInterval: 5000,
  });

export const useBotProfiles = () =>
  useQuery<BotProfilesResponse>({
    queryKey: ["bot-profiles"],
    queryFn: fetchBotProfiles,
    refetchInterval: 30_000,
  });

export const useBotProfileDetail = (botId?: string) =>
  useQuery<BotProfileDetailResponse>({
    queryKey: ["bot-profile", botId],
    queryFn: () => fetchBotProfileDetail(botId as string),
    enabled: Boolean(botId),
    refetchInterval: 15_000,
  });

export const useActiveBot = () =>
  useQuery<{ bot: BotProfile | null }>({
    queryKey: ["active-bot"],
    queryFn: () => fetchActiveBot(),
    refetchInterval: 30_000,
  });

// Signals page hooks
export const useDecisionFunnel = (params?: { timeWindow?: string; botId?: string; exchangeAccountId?: string }) =>
  useQuery({
    queryKey: ["decision-funnel", params?.timeWindow, params?.botId, params?.exchangeAccountId],
    queryFn: () => fetchDecisionFunnel(params),
    refetchInterval: 10_000,
    staleTime: 5000,
  });

export const useSymbolStatus = (params?: { botId?: string; exchangeAccountId?: string }) =>
  useQuery({
    queryKey: ["symbol-status", params?.botId, params?.exchangeAccountId],
    queryFn: () => fetchSymbolStatus(params),
    refetchInterval: 10_000,
    staleTime: 5000,
  });

export const useSymbolDecisions = (symbol: string | null, params?: { botId?: string; exchangeAccountId?: string }) =>
  useQuery({
    queryKey: ["symbol-decisions", symbol, params?.botId, params?.exchangeAccountId],
    queryFn: () => fetchSymbolDecisions(symbol!, params),
    enabled: !!symbol,
    refetchInterval: 10_000,
    staleTime: 5000,
  });

export const useStatusNarrative = (params?: { timeWindow?: string; botId?: string; exchangeAccountId?: string }) =>
  useQuery({
    queryKey: ["status-narrative", params?.timeWindow, params?.botId, params?.exchangeAccountId],
    queryFn: () => fetchStatusNarrative(params),
    refetchInterval: 10_000,
    staleTime: 5000,
  });

export const useConfirmationReadiness = (params?: { timeWindow?: string; botId?: string; exchangeAccountId?: string }) =>
  useQuery({
    queryKey: ["confirmation-readiness", params?.timeWindow, params?.botId, params?.exchangeAccountId],
    queryFn: () => fetchConfirmationReadiness(params),
    refetchInterval: 10_000,
    staleTime: 5000,
  });

export const useSetActiveBot = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId }: { botId: string }) => setActiveBot(botId),
    onMutate: async ({ botId }) => {
      await queryClient.cancelQueries({ queryKey: ["active-bot"] });
      const previousActiveBot = queryClient.getQueryData(["active-bot"]);

      // Best-effort: find name/details from cached bot instances list (if present)
      let nextBot: any = { id: botId };
      const instanceQueries = queryClient.getQueriesData({ queryKey: ["bot-instances"] });
      for (const [, data] of instanceQueries) {
        const bots = (data as any)?.bots;
        if (!Array.isArray(bots)) continue;
        const found = bots.find((b: any) => b?.id === botId);
        if (found) {
          nextBot = {
            id: found.id,
            name: found.name,
            exchange: found.exchange || found.exchange_name,
            environment: found.environment,
            market_type: found.market_type,
          };
          break;
        }
      }

      queryClient.setQueryData(["active-bot"], { bot: nextBot });
      return { previousActiveBot };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previousActiveBot) {
        queryClient.setQueryData(["active-bot"], ctx.previousActiveBot);
      }
    },
    onSuccess: (data) => {
      if ((data as any)?.bot) {
        queryClient.setQueryData(["active-bot"], { bot: (data as any).bot });
      }
      queryClient.invalidateQueries({ queryKey: ["active-bot"] });
      queryClient.invalidateQueries({ queryKey: ["bot-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
    },
  });
};

// TCA Hooks
export const useTCAAnalysis = (filters?: {
  symbol?: string;
  profileId?: string;
  startDate?: string;
  endDate?: string;
  periodType?: "daily" | "weekly" | "monthly";
}) =>
  useQuery<TCAAnalysisResponse>({
    queryKey: ["tca-analysis", filters],
    queryFn: () => fetchTCAAnalysis(filters),
    refetchInterval: 60_000, // Refresh every minute
  });

export const useCapacityCurve = (
  profileId: string | null,
  startDate?: string,
  endDate?: string
) =>
  useQuery<CapacityCurveResponse>({
    queryKey: ["capacity-curve", profileId, startDate, endDate],
    queryFn: () => fetchCapacityCurve(profileId as string, startDate, endDate),
    enabled: !!profileId,
    refetchInterval: 60_000,
  });

export const useTradeCost = (tradeId: string | null) =>
  useQuery<TradeCostResponse>({
    queryKey: ["trade-cost", tradeId],
    queryFn: () => fetchTradeCost(tradeId as string),
    enabled: !!tradeId,
  });

export const useCandlestickData = (
  symbol: string | null, 
  timeframe: string = "1m", 
  limit: number = 288,
  startTime?: number,
  endTime?: number
) =>
  useQuery<CandlestickResponse>({
    queryKey: ["candlestick", symbol, timeframe, limit, startTime, endTime],
    queryFn: () => fetchCandlestickData(symbol as string, timeframe, limit, startTime, endTime),
    enabled: Boolean(symbol),
    refetchInterval: startTime ? false : 30_000, // Don't refetch historical data
    // Keep historical requests mostly stable, but still refresh periodically
    // so an initial empty response can recover after backend fixes/restarts.
    staleTime: startTime ? 60_000 : 10_000,
  });

export const useDrawdownData = (
  hours: number = 24,
  exchangeAccountId?: string | null,
  botId?: string | null
) =>
  useQuery<DrawdownResponse>({
    queryKey: ["drawdown", hours, exchangeAccountId, botId],
    queryFn: () => fetchDrawdownData(hours, exchangeAccountId || undefined, botId || undefined),
    refetchInterval: 60_000, // Refetch every minute
    staleTime: 30_000, // Consider data stale after 30 seconds
  });

// Settings hooks
export const useTradingSettings = () =>
  useQuery<TradingSettings>({
    queryKey: ["trading-settings"],
    queryFn: () => fetchTradingSettings(),
    staleTime: 60_000, // Settings don't change often
  });

export const useAccountSettings = () =>
  useQuery<AccountSettings>({
    queryKey: ["account-settings"],
    queryFn: fetchAccountSettings,
    staleTime: 60_000,
  });

export const useUpdateAccountSettings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateAccountSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["account-settings"] });
    },
  });
};

export const useViewerAccounts = (enabled = true) =>
  useQuery({
    queryKey: ["viewer-accounts"],
    queryFn: fetchViewerAccounts,
    staleTime: 15_000,
    enabled,
  });

export const useCreateViewerAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ViewerAccountPayload) => createViewerAccount(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["viewer-accounts"] });
    },
  });
};

export const useUpdateViewerAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ viewerId, payload }: { viewerId: string; payload: Partial<ViewerAccountPayload> }) =>
      updateViewerAccount(viewerId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["viewer-accounts"] });
    },
  });
};

export const useDeleteViewerAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (viewerId: string) => deleteViewerAccount(viewerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["viewer-accounts"] });
    },
  });
};

export const useUpdateTradingSettings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateTradingSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trading-settings"] });
    },
  });
};

export const useResetTradingSettings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: resetTradingSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trading-settings"] });
    },
  });
};

export const useDataSettings = (tenantId?: string) =>
  useQuery<DataSettings>({
    queryKey: ["data-settings", tenantId],
    queryFn: () => fetchDataSettings(tenantId as string),
    enabled: Boolean(tenantId),
    staleTime: 60_000,
  });

export const useUpdateDataSettings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateDataSettings,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["data-settings", variables.tenant_id] });
    },
  });
};

export const useOrderTypes = () =>
  useQuery<{ orderTypes: Record<string, any>; riskProfiles: Record<string, any> }>({
    queryKey: ["order-types"],
    queryFn: () => fetchOrderTypes(),
    staleTime: 300_000, // Order types are static
  });

// Strategy hooks
export const useStrategies = () =>
  useQuery({
    queryKey: ["strategies"],
    queryFn: () => fetchStrategies(),
    refetchInterval: 30_000, // Refetch every 30 seconds
    staleTime: 15_000,
  });

export const useStrategyById = (strategyId?: string) =>
  useQuery({
    queryKey: ["strategy", strategyId],
    queryFn: () => fetchStrategyById(strategyId as string),
    enabled: Boolean(strategyId),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

// Signal Configuration hooks
export const useSignalConfig = () =>
  useQuery({
    queryKey: ["signal-config"],
    queryFn: () => fetchSignalConfig(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

// Allocator Configuration hooks
export const useAllocatorConfig = () =>
  useQuery({
    queryKey: ["allocator-config"],
    queryFn: () => fetchAllocatorConfig(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

// Market Context hooks
export const useMarketContext = (params?: { symbol?: string; botId?: string | null }) =>
  useQuery({
    queryKey: ["market-context", params?.symbol, params?.botId],
    queryFn: () => fetchMarketContext(params?.symbol, params?.botId),
    refetchInterval: 15_000, // Refetch every 15 seconds for real-time updates
    staleTime: 5_000,
  });

// Research & Backtesting Hooks
export const useBacktests = (params?: { limit?: number; offset?: number; status?: string; strategy_id?: string }) =>
  useQuery({
    queryKey: ["backtests", params],
    queryFn: () => fetchBacktests(params),
    refetchInterval: 10000, // Refetch every 10 seconds for running backtests
  });

export const useBacktestDetail = (id: string) => {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["backtest", id],
    queryFn: () => fetchBacktestDetail(id),
    enabled: !!id,
    refetchInterval: (data) => {
      // Refetch if backtest is still running
      const status = (data as any)?.backtest?.status;
      return status === "running" ? 5000 : false;
    },
  });
};

export const useDatasets = (params?: { symbol?: string; start_date?: string; end_date?: string }) =>
  useQuery({
    queryKey: ["datasets", params],
    queryFn: () => fetchDatasets(params),
  });

export const useBacktestPreflight = (params?: {
  symbol?: string;
  start_date?: string;
  end_date?: string;
  require_decision_events?: boolean;
}) =>
  useQuery({
    queryKey: ["backtest-preflight", params],
    queryFn: () =>
      fetchBacktestPreflight({
        symbol: params!.symbol!,
        start_date: params!.start_date!,
        end_date: params!.end_date!,
        require_decision_events: params?.require_decision_events ?? true,
      }),
    enabled: Boolean(params?.symbol && params?.start_date && params?.end_date),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

// Research Strategies Hook (for backtesting - uses /research/strategies endpoint)
export const useResearchStrategies = () =>
  useQuery({
    queryKey: ["research-strategies"],
    queryFn: () => fetchResearchStrategies(),
    staleTime: 60_000, // Strategies don't change often
  });

export const useCreateBacktest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createBacktest,
    onSuccess: () => {
      // Invalidate backtests list to refetch
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
    },
  });
};

export const useCancelBacktest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: cancelBacktest,
    onSuccess: (_, runId) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      queryClient.invalidateQueries({ queryKey: ["backtest", runId] });
    },
  });
};

export const useRerunBacktest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, force_run }: { id: string; force_run?: boolean }) => rerunBacktest(id, { force_run }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
    },
  });
};

export const usePromoteBacktestConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      bot_id,
      notes,
      activate,
      status,
    }: {
      id: string;
      bot_id?: string;
      notes?: string;
      activate?: boolean;
      status?: string;
    }) => promoteBacktestConfig(id, { bot_id, notes, activate, status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-bot"] });
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
    },
  });
};

export const useDeleteBacktest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteBacktest,
    onSuccess: (_, runId) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      queryClient.invalidateQueries({ queryKey: ["backtest", runId] });
    },
  });
};

export const useModelTrainingJobs = (limit = 20) =>
  useQuery({
    queryKey: ["model-training-jobs", limit],
    queryFn: () => fetchModelTrainingJobs(limit),
    refetchInterval: 5000,
    staleTime: 1000,
  });

export const useActiveModelInfo = () =>
  useQuery({
    queryKey: ["active-model-info"],
    queryFn: fetchActiveModelInfo,
    refetchInterval: 15000,
    staleTime: 5000,
  });

export const useModelTrainingJob = (jobId?: string | null) =>
  useQuery({
    queryKey: ["model-training-job", jobId],
    queryFn: () => fetchModelTrainingJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (data) => {
      const status = (data as any)?.job?.status;
      return status === "running" || status === "queued" ? 3000 : false;
    },
    staleTime: 1000,
  });

export const useStartModelTraining = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startModelTraining,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["model-training-jobs"] });
    },
  });
};

export const usePromoteModelTrainingJob = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, notes }: { jobId: string; notes?: string }) =>
      promoteModelTrainingJob(jobId, { notes }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["model-training-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["model-training-job", variables.jobId] });
    },
  });
};

// Chessboard Profile Specs Hook
export const useProfileSpecs = (botId?: string | null) =>
  useQuery({
    queryKey: ["profile-specs", botId],
    queryFn: () => fetchProfileSpecs(botId),
    refetchInterval: 30_000, // Refetch every 30 seconds
    staleTime: 10_000,
  });

// Profile Routing Metrics Hook (runtime data)
export const useProfileMetrics = (botId?: string | null) =>
  useQuery({
    queryKey: ["profile-metrics", botId],
    queryFn: () => fetchProfileMetrics(botId),
    refetchInterval: 5_000, // Refetch every 5 seconds (real-time routing data)
    staleTime: 3_000,
  });

// Profile Router Hook (selection & rejection data)
export const useProfileRouter = (botId?: string | null) =>
  useQuery({
    queryKey: ["profile-router", botId],
    queryFn: () => fetchProfileRouter(botId),
    refetchInterval: 5_000, // Refetch every 5 seconds
    staleTime: 3_000,
  });

// Risk Metrics (VaR/ES) Hooks
export const useVaRCalculations = (params?: {
  portfolioId?: string;
  symbol?: string;
  profileId?: string;
  limit?: number;
  offset?: number;
  confidenceLevel?: number;
}) =>
  useQuery({
    queryKey: ["var-calculations", params],
    queryFn: () => fetchVaRCalculations(params),
    refetchInterval: 60000, // Refresh every minute
    staleTime: 30000,
  });

export const useScenarioResults = (params?: { limit?: number; offset?: number }) =>
  useQuery({
    queryKey: ["scenario-results", params],
    queryFn: () => fetchScenarioResults(params),
    refetchInterval: 60000,
    staleTime: 30000,
  });

// Mutations for running VaR calculations
export const useRunHistoricalVaR = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: calculateHistoricalVaR,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["var-calculations"] });
      queryClient.invalidateQueries({ queryKey: ["component-var"] });
    },
  });
};

export const useRunMonteCarloVaR = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: calculateMonteCarloVaR,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["var-calculations"] });
      queryClient.invalidateQueries({ queryKey: ["component-var"] });
    },
  });
};

// Mutation for running scenario tests
export const useRunScenarioTest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: runScenarioTest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scenario-results"] });
      queryClient.invalidateQueries({ queryKey: ["scenario-factors"] });
    },
  });
};

export const useComponentVaR = () =>
  useQuery({
    queryKey: ["component-var"],
    queryFn: fetchComponentVaR,
    refetchInterval: 60000,
  });

export const useScenarioFactors = () =>
  useQuery({
    queryKey: ["scenario-factors"],
    queryFn: fetchScenarioFactors,
    refetchInterval: 60000,
  });

export const useScenarioDetailWithFactors = (id?: string) =>
  useQuery({
    queryKey: ["scenario-factors", id],
    queryFn: () => fetchScenarioDetailWithFactors(id as string),
    enabled: !!id,
    refetchInterval: 60000,
  });

export const useCorrelations = (params?: { strategyName?: string; limit?: number }) =>
  useQuery({
    queryKey: ["correlations", params],
    queryFn: () => fetchCorrelations(params),
    staleTime: 60000,
  });

export const useRiskLimits = () =>
  useQuery({
    queryKey: ["risk-limits"],
    queryFn: fetchRiskLimits,
    staleTime: 60000,
  });

export const useUpdateRiskLimits = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (updates: Record<string, unknown>) =>
      import("./client").then((m) => m.updateRiskLimits(updates)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk-limits"] });
      queryClient.invalidateQueries({ queryKey: ["tenant-risk-policy"] });
      // Trigger VaR refresh on risk limit changes
      import("./client").then((m) => m.triggerVaRRefresh("risk:limits_changed")).catch(() => {});
    },
  });
};

// VaR Snapshot hooks
export const useVaRSnapshot = () =>
  useQuery({
    queryKey: ["var-snapshot"],
    queryFn: () => import("./client").then((m) => m.fetchVaRSnapshot()),
    staleTime: 30000, // 30 seconds
    refetchInterval: 60000, // Refetch every minute
  });

export const useVaRDataStatus = (params?: { exchangeAccountId?: string; botId?: string }) =>
  useQuery({
    queryKey: ["var-data-status", params?.exchangeAccountId, params?.botId],
    queryFn: () => import("./client").then((m) => m.fetchVaRDataStatus(params)),
    staleTime: 60000,
  });

export const useForceVaRSnapshot = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params?: { exchangeAccountId?: string; botId?: string; portfolioId?: string }) =>
      import("./client").then((m) => m.forceVaRSnapshot(params)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["var-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["var-calculations"] });
      queryClient.invalidateQueries({ queryKey: ["var-data-status"] });
    },
  });
};

export const useScenarioDetail = (id: string) =>
  useQuery({
    queryKey: ["scenario-detail", id],
    queryFn: () => fetchScenarioDetail(id),
    enabled: !!id,
  });

// Promotion Workflow Hooks
export const usePromotions = (params?: {
  status?: string;
  promotionType?: string;
  botProfileId?: string;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["promotions", params],
    queryFn: () => fetchPromotions(params),
  });

export const usePromotionDetail = (id: string) =>
  useQuery({
    queryKey: ["promotion-detail", id],
    queryFn: () => fetchPromotionDetail(id),
    enabled: !!id,
  });

export const useConfigDiff = (botProfileId: string, versionId1: string, versionId2: string) =>
  useQuery({
    queryKey: ["config-diff", botProfileId, versionId1, versionId2],
    queryFn: () => fetchConfigDiff({ botProfileId, versionId1, versionId2 }),
    enabled: !!botProfileId && !!versionId1 && !!versionId2,
  });

// Audit Log Hooks
export const useAuditLog = (params?: {
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
  useQuery({
    queryKey: ["audit-log", params],
    queryFn: () => fetchAuditLog(params),
  });

export const useDecisionTrace = (tradeId: string) =>
  useQuery({
    queryKey: ["decision-trace", tradeId],
    queryFn: () => fetchDecisionTrace(tradeId),
    enabled: !!tradeId,
  });

export const useDecisionTraces = (params?: {
  tradeId?: string;
  symbol?: string;
  decisionType?: string;
  decisionOutcome?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["decision-traces", params],
    queryFn: () => fetchDecisionTraces(params),
  });

// Replay & Incident Analysis Hooks
export const useReplayData = (symbol: string | null, startTime: string | null, endTime: string | null) =>
  useQuery({
    queryKey: ["replay-data", symbol, startTime, endTime],
    queryFn: () => fetchReplayData(symbol!, startTime!, endTime!),
    enabled: !!symbol && !!startTime && !!endTime,
  });

// ============================================================
// INCIDENTS HOOKS (Risk Ops Console)
// ============================================================

export const useIncidents = (params?: IncidentFilters) =>
  useQuery({
    queryKey: ["incidents", params],
    queryFn: () => fetchIncidents(params),
    refetchInterval: 30000, // Refresh every 30 seconds
  });

export const useIncidentSnapshot = (params?: { exchangeAccountId?: string; botId?: string }) =>
  useQuery({
    queryKey: ["incident-snapshot", params],
    queryFn: () => fetchIncidentSnapshot(params),
    refetchInterval: 15000, // Refresh every 15 seconds for ops awareness
  });

export const useIncident = (incidentId: string | null) =>
  useQuery({
    queryKey: ["incident", incidentId],
    queryFn: () => fetchIncident(incidentId!),
    enabled: !!incidentId,
  });

export const useIncidentTimeline = (incidentId: string | null, params?: { limit?: number; offset?: number }) =>
  useQuery({
    queryKey: ["incident-timeline", incidentId, params],
    queryFn: () => fetchIncidentTimeline(incidentId!, params),
    enabled: !!incidentId,
  });

export const useIncidentEvidence = (incidentId: string | null) =>
  useQuery({
    queryKey: ["incident-evidence", incidentId],
    queryFn: () => fetchIncidentEvidence(incidentId!),
    enabled: !!incidentId,
  });

export const useCreateIncident = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createIncident,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["incident-snapshot"] });
    },
  });
};

export const useAcknowledgeIncident = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (incidentId: string) => acknowledgeIncident(incidentId),
    onSuccess: (_, incidentId) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      queryClient.invalidateQueries({ queryKey: ["incident-snapshot"] });
    },
  });
};

export const useAssignIncidentOwner = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ incidentId, ownerId }: { incidentId: string; ownerId: string }) =>
      assignIncidentOwner(incidentId, ownerId),
    onSuccess: (_, { incidentId }) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
    },
  });
};

export const useResolveIncident = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ incidentId, resolutionNotes, rootCause }: { incidentId: string; resolutionNotes?: string; rootCause?: string }) =>
      resolveIncident(incidentId, resolutionNotes, rootCause),
    onSuccess: (_, { incidentId }) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      queryClient.invalidateQueries({ queryKey: ["incident-snapshot"] });
    },
  });
};

export const useUpdateIncidentStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ incidentId, status, notes }: { incidentId: string; status: string; notes?: string }) =>
      updateIncidentStatus(incidentId, status, notes),
    onSuccess: (_, { incidentId }) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      queryClient.invalidateQueries({ queryKey: ["incident-snapshot"] });
    },
  });
};

export const useAddIncidentTimelineEvent = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ incidentId, eventType, eventData }: { incidentId: string; eventType: string; eventData?: any }) =>
      addIncidentTimelineEvent(incidentId, eventType, eventData),
    onSuccess: (_, { incidentId }) => {
      queryClient.invalidateQueries({ queryKey: ["incident-timeline", incidentId] });
    },
  });
};

export const useExportIncident = () => {
  return useMutation({
    mutationFn: ({ incidentId, format }: { incidentId: string; format: 'json' | 'csv' }) =>
      exportIncident(incidentId, format),
  });
};

export const useReplaySessions = (params?: {
  incidentId?: string;
  symbol?: string;
  limit?: number;
}) =>
  useQuery({
    queryKey: ["replay-sessions", params],
    queryFn: () => fetchReplaySessions(params),
  });

export const useCreateReplaySession = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createReplaySession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["replay-sessions"] });
    },
  });
};

// Data Quality Hooks
export const useQualityMetrics = (params?: {
  symbol?: string;
  timeframe?: string;
  startDate?: string;
  endDate?: string;
  status?: string;
  minQualityScore?: number;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["quality-metrics", params],
    queryFn: () => fetchQualityMetrics(params),
    refetchInterval: 30000, // Refresh every 30 seconds
  });

export const useQualityMetricsTimeseries = (params?: {
  symbol?: string;
  timeframe?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
}) =>
  useQuery({
    queryKey: ["quality-metrics-timeseries", params],
    queryFn: () => fetchQualityMetricsTimeseries(params),
    refetchInterval: 60000,
  });

// Walk-Forward Hooks
export const useWfoRuns = () =>
  useQuery({
    queryKey: ["wfo-runs"],
    queryFn: fetchWfoRuns,
    refetchInterval: 15000,
  });

export const useWfoRun = (id: string | null) =>
  useQuery({
    queryKey: ["wfo-run", id],
    queryFn: () => fetchWfoRun(id as string),
    enabled: !!id,
    refetchInterval: 15000,
  });

export const useCreateWfoRun = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createWfoRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wfo-runs"] });
    },
  });
};

export const useStoreQualityMetrics = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storeQualityMetrics,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quality-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["symbol-health"] });
    },
  });
};

export const useFeedGaps = (params?: {
  symbol?: string;
  timeframe?: string;
  startDate?: string;
  endDate?: string;
  severity?: string;
  resolved?: boolean;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["feed-gaps", params],
    queryFn: () => fetchFeedGaps(params),
    refetchInterval: 30000,
  });

export const useRecordFeedGap = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: recordFeedGap,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feed-gaps"] });
      queryClient.invalidateQueries({ queryKey: ["symbol-health"] });
    },
  });
};

export const useResolveFeedGap = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ gapId, resolutionMethod, notes }: { gapId: string; resolutionMethod: string; notes?: string }) =>
      resolveFeedGap(gapId, resolutionMethod, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feed-gaps"] });
      queryClient.invalidateQueries({ queryKey: ["symbol-health"] });
    },
  });
};

export const useQualityAlerts = (params?: {
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
  useQuery({
    queryKey: ["quality-alerts", params],
    queryFn: () => fetchQualityAlerts(params),
    refetchInterval: 30000,
  });

export const useCreateQualityAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createQualityAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quality-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["symbol-health"] });
    },
  });
};

export const useUpdateAlertStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, status, resolutionNotes }: { alertId: string; status: string; resolutionNotes?: string }) =>
      updateAlertStatus(alertId, status, resolutionNotes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quality-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["symbol-health"] });
    },
  });
};

export const useSymbolHealth = (symbol?: string, params?: { timeframe?: string }) =>
  useQuery({
    queryKey: ["symbol-health", symbol, params?.timeframe],
    queryFn: () => fetchSymbolHealth(symbol, params),
    refetchInterval: 30000,
  });

// Reporting Hooks
export const useReportTemplates = (params?: {
  reportType?: string;
  enabled?: boolean;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["report-templates", params],
    queryFn: () => fetchReportTemplates(params),
  });

export const useCreateReportTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createReportTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["report-templates"] });
    },
  });
};

export const useGeneratedReports = (params?: {
  templateId?: string;
  reportType?: string;
  startDate?: string;
  endDate?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["generated-reports", params],
    queryFn: () => fetchGeneratedReports(params),
    refetchInterval: 60000, // Refresh every minute
  });

export const useStoreGeneratedReport = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storeGeneratedReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["generated-reports"] });
    },
  });
};

export const useStrategyPortfolio = (params?: {
  strategyName?: string;
  strategyFamily?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["strategy-portfolio", params],
    queryFn: () => fetchStrategyPortfolio(params),
    refetchInterval: 30000,
  });

export const useStoreStrategyPortfolio = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storeStrategyPortfolio,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
    },
  });
};

export const useStrategyCorrelations = (params?: {
  strategyName?: string;
  calculationDate?: string;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["strategy-correlations", params],
    queryFn: () => fetchStrategyCorrelations(params),
    refetchInterval: 60000,
  });

export const useStoreStrategyCorrelation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storeStrategyCorrelation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-correlations"] });
    },
  });
};

export const usePortfolioSummary = (params?: {
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}) =>
  useQuery({
    queryKey: ["portfolio-summary", params],
    queryFn: () => fetchPortfolioSummary(params),
    refetchInterval: 30000,
  });

export const useStorePortfolioSummary = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: storePortfolioSummary,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] });
    },
  });
};

// ═══════════════════════════════════════════════════════════════
// BOT INSTANCES HOOKS
// ═══════════════════════════════════════════════════════════════

import {
  fetchStrategyTemplates,
  fetchStrategyTemplate,
  fetchBotInstances,
  fetchBotInstance,
  createBotInstance,
  updateBotInstance,
  deleteBotInstance,
  fetchBotExchangeConfigs,
  fetchBotExchangeConfig,
  createBotExchangeConfig,
  updateBotExchangeConfig,
  deleteBotExchangeConfig,
  activateBotExchangeConfig,
  deactivateBotExchangeConfig,
  transitionBotExchangeConfigState,
  fetchBotExchangeConfigVersions,
  fetchBotExchangeConfigVersionsWithPerformance,
  rollbackBotExchangeConfig,
  compareBotExchangeConfigVersions,
  fetchBotSymbolConfigs,
  updateBotSymbolConfig,
  bulkUpdateBotSymbolConfigs,
  deleteBotSymbolConfig,
  fetchTenantRiskPolicy,
  updateTenantRiskPolicy,
  enableLiveTrading,
  updateTradingSettings,
  resetTradingSettings,
  fetchNotificationChannels,
  createNotificationChannel,
  updateNotificationChannel,
  deleteNotificationChannel,
  fetchNotificationRouting,
  updateNotificationRouting,
  fetchSecuritySettings,
  updateSecuritySettings,
  fetchApiKeys,
  createApiKey,
  deleteApiKey,
  validateApiKey,
  validateTwoFactor,
  enrollTwoFactor,
  confirmTwoFactor,
  disableTwoFactor,
  generateBackupCodes,
  fetchActiveConfig,
  cancelOrder,
  replaceOrder,
} from "./client";

// Strategy Templates
export const useStrategyTemplates = () =>
  useQuery({
    queryKey: ["strategy-templates"],
    queryFn: fetchStrategyTemplates,
    staleTime: 60000,
  });

export const useStrategyTemplate = (templateId: string) =>
  useQuery({
    queryKey: ["strategy-template", templateId],
    queryFn: () => fetchStrategyTemplate(templateId),
    enabled: !!templateId,
  });

// Bot Instances
export const useBotInstances = (includeInactive = false) =>
  useQuery({
    queryKey: ["bot-instances", { includeInactive }],
    queryFn: () => fetchBotInstances(includeInactive),
    refetchInterval: 10000,
  });

export const useBotInstance = (botId: string) =>
  useQuery({
    queryKey: ["bot-instance", botId],
    queryFn: () => fetchBotInstance(botId),
    enabled: !!botId,
  });

export const useCreateBotInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createBotInstance,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
    },
  });
};

export const useUpdateBotInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, data }: { botId: string; data: Parameters<typeof updateBotInstance>[1] }) =>
      updateBotInstance(botId, data),
    onSuccess: (_, { botId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["bot-instance", botId] });
    },
  });
};

export const useDeleteBotInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteBotInstance,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
    },
  });
};

// Bot Exchange Configs
export const useBotExchangeConfigs = (botId: string) =>
  useQuery({
    queryKey: ["bot-exchange-configs", botId],
    queryFn: () => fetchBotExchangeConfigs(botId),
    enabled: !!botId,
    refetchInterval: 5000,
  });

export const useBotExchangeConfig = (botId: string, configId: string) =>
  useQuery({
    queryKey: ["bot-exchange-config", botId, configId],
    queryFn: () => fetchBotExchangeConfig(botId, configId),
    enabled: !!botId && !!configId,
  });

export const useCreateBotExchangeConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, data }: { botId: string; data: Parameters<typeof createBotExchangeConfig>[1] }) =>
      createBotExchangeConfig(botId, data),
    onSuccess: (_, { botId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-configs", botId] });
    },
  });
};

export const useUpdateBotExchangeConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId, data }: { botId: string; configId: string; data: Parameters<typeof updateBotExchangeConfig>[2] }) =>
      updateBotExchangeConfig(botId, configId, data),
    onSuccess: (_, { botId, configId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-configs", botId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-config", botId, configId] });
    },
  });
};

export const useDeleteBotExchangeConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId }: { botId: string; configId: string }) =>
      deleteBotExchangeConfig(botId, configId),
    onSuccess: (_, { botId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-configs", botId] });
    },
  });
};

export const useActivateBotExchangeConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId }: { botId: string; configId: string }) =>
      activateBotExchangeConfig(botId, configId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      // Activating a config also sets the user's active credential + exchange + trading mode (phase-1 bot scoping).
      queryClient.invalidateQueries({ queryKey: ["trade-profile"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-positions"] });
      queryClient.invalidateQueries({ queryKey: ["orphaned-positions"] });
      queryClient.invalidateQueries({ queryKey: ["pending-orders"] });
      queryClient.invalidateQueries({ queryKey: ["trade-history"] });
      queryClient.invalidateQueries({ queryKey: ["drawdown"] });
    },
  });
};

export const useDeactivateBotExchangeConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId }: { botId: string; configId: string }) =>
      deactivateBotExchangeConfig(botId, configId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      queryClient.invalidateQueries({ queryKey: ["trade-profile"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-positions"] });
      queryClient.invalidateQueries({ queryKey: ["orphaned-positions"] });
      queryClient.invalidateQueries({ queryKey: ["pending-orders"] });
      queryClient.invalidateQueries({ queryKey: ["trade-history"] });
      queryClient.invalidateQueries({ queryKey: ["drawdown"] });
    },
  });
};

export const useBotExchangeConfigVersions = (botId: string, configId: string, limit = 20) =>
  useQuery({
    queryKey: ["bot-exchange-config-versions", botId, configId, limit],
    queryFn: () => fetchBotExchangeConfigVersions(botId, configId, limit),
    enabled: !!botId && !!configId,
  });

export const useBotExchangeConfigVersionsWithPerformance = (botId: string, configId: string, limit = 10) =>
  useQuery({
    queryKey: ["bot-exchange-config-versions-performance", botId, configId, limit],
    queryFn: () => fetchBotExchangeConfigVersionsWithPerformance(botId, configId, limit),
    enabled: !!botId && !!configId,
  });

export const useRollbackBotExchangeConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId, targetVersion }: { botId: string; configId: string; targetVersion: number }) =>
      rollbackBotExchangeConfig(botId, configId, targetVersion),
    onSuccess: (_, { botId, configId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-config-versions", botId, configId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-config-versions-performance", botId, configId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-config", botId, configId] });
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
    },
  });
};

export const useCompareBotExchangeConfigVersions = (botId: string, configId: string, versionA: number, versionB: number) =>
  useQuery({
    queryKey: ["bot-exchange-config-versions-compare", botId, configId, versionA, versionB],
    queryFn: () => compareBotExchangeConfigVersions(botId, configId, versionA, versionB),
    enabled: !!botId && !!configId && !!versionA && !!versionB,
  });

// Symbol Configs
export const useBotSymbolConfigs = (botId: string, configId: string) =>
  useQuery({
    queryKey: ["bot-symbol-configs", botId, configId],
    queryFn: () => fetchBotSymbolConfigs(botId, configId),
    enabled: !!botId && !!configId,
  });

export const useUpdateBotSymbolConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId, symbol, data }: { botId: string; configId: string; symbol: string; data: Parameters<typeof updateBotSymbolConfig>[3] }) =>
      updateBotSymbolConfig(botId, configId, symbol, data),
    onSuccess: (_, { botId, configId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-symbol-configs", botId, configId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-config", botId, configId] });
    },
  });
};

export const useBulkUpdateBotSymbolConfigs = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, configId, symbols }: { botId: string; configId: string; symbols: Parameters<typeof bulkUpdateBotSymbolConfigs>[2] }) =>
      bulkUpdateBotSymbolConfigs(botId, configId, symbols),
    onSuccess: (_, { botId, configId }) => {
      queryClient.invalidateQueries({ queryKey: ["bot-symbol-configs", botId, configId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-config", botId, configId] });
    },
  });
};

// Tenant Risk Policy
export const useTenantRiskPolicy = () =>
  useQuery({
    queryKey: ["tenant-risk-policy"],
    queryFn: fetchTenantRiskPolicy,
    staleTime: 30000,
  });

export const useUpdateTenantRiskPolicy = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateTenantRiskPolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tenant-risk-policy"] });
    },
  });
};

export const useEnableLiveTrading = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: enableLiveTrading,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tenant-risk-policy"] });
    },
  });
};

// Notifications
export const useNotificationChannels = () =>
  useQuery({
    queryKey: ["notification-channels"],
    queryFn: fetchNotificationChannels,
    staleTime: 30000,
  });

export const useCreateNotificationChannel = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createNotificationChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
    },
  });
};

export const useUpdateNotificationChannel = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) => updateNotificationChannel(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
    },
  });
};

export const useDeleteNotificationChannel = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteNotificationChannel(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
    },
  });
};

export const useNotificationRouting = () =>
  useQuery({
    queryKey: ["notification-routing"],
    queryFn: fetchNotificationRouting,
    staleTime: 30000,
  });

export const useUpdateNotificationRouting = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateNotificationRouting,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-routing"] });
    },
  });
};

// Security
export const useSecuritySettings = () =>
  useQuery({
    queryKey: ["security-settings"],
    queryFn: fetchSecuritySettings,
    staleTime: 30000,
  });

export const useUpdateSecuritySettings = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateSecuritySettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["security-settings"] });
    },
  });
};

export const useApiKeys = () =>
  useQuery({
    queryKey: ["api-keys"],
    queryFn: fetchApiKeys,
    staleTime: 30000,
  });

export const useCreateApiKey = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
};

export const useDeleteApiKey = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
};

export const useValidateApiKey = () =>
  useMutation({
    mutationFn: (apiKey: string) => validateApiKey(apiKey),
  });

export const useValidateTwoFactor = () =>
  useMutation({
    mutationFn: (code: string) => validateTwoFactor(code),
  });

export const useEnrollTwoFactor = () =>
  useMutation({
    mutationFn: enrollTwoFactor,
  });

export const useConfirmTwoFactor = () =>
  useMutation({
    mutationFn: (code: string) => confirmTwoFactor(code),
  });

export const useDisableTwoFactor = () =>
  useMutation({
    mutationFn: disableTwoFactor,
  });

export const useGenerateBackupCodes = () =>
  useMutation({
    mutationFn: generateBackupCodes,
  });

// Active Config
export const useActiveConfig = () =>
  useQuery({
    queryKey: ["active-config"],
    queryFn: fetchActiveConfig,
    refetchInterval: 5000,
  });

// ═══════════════════════════════════════════════════════════════
// TRADE HISTORY HOOKS
// ═══════════════════════════════════════════════════════════════

import {
  fetchTradeHistory,
  fetchTradeDetail,
  fetchRuntimePrediction,
  fetchPredictionHistory,
  fetchPendingOrders,
  fetchExecutionStats,
  fetchDashboardRisk,
  type TradeHistoryParams,
  type PredictionQueryParams,
} from "./client";

export const useTradeHistory = (params?: TradeHistoryParams) => {
  const scopeHydrated = useScopeHydrated();
  return useQuery({
    // Use specific keys for better cache invalidation on scope change
    queryKey: [
      "trade-history",
      params?.exchangeAccountId,
      params?.botId,
      params?.limit,
      params?.symbol,
      params?.startDate,
      params?.endDate,
    ],
    queryFn: () => fetchTradeHistory(params),
    staleTime: 10000, // 10s - shorter to catch scope changes faster
    refetchInterval: 30000, // Refresh every 30s
    placeholderData: (previousData) => previousData, // Keep showing old data while refetching
    enabled: scopeHydrated,
  });
};

export const useTradeDetail = (tradeId: string | null) =>
  useQuery({
    queryKey: ["trade-detail", tradeId],
    queryFn: () => fetchTradeDetail(tradeId!),
    enabled: !!tradeId,
    staleTime: 60000,
  });

export const useRuntimePrediction = (params?: PredictionQueryParams) =>
  useQuery({
    queryKey: ["runtime-prediction", params?.tenantId, params?.botId, params?.symbol],
    queryFn: () => fetchRuntimePrediction(params),
    enabled: !!params?.botId,
    staleTime: 5000,
    refetchInterval: 5000,
  });

export const usePredictionHistory = (params?: PredictionQueryParams) =>
  useQuery({
    queryKey: ["prediction-history", params?.tenantId, params?.botId, params?.symbol, params?.limit],
    queryFn: () => fetchPredictionHistory(params),
    enabled: !!params?.botId,
    staleTime: 10000,
    refetchInterval: 15000,
  });

export const usePendingOrders = (params?: { exchangeAccountId?: string | null; botId?: string | null }) =>
  useQuery({
    queryKey: ["pending-orders", params?.exchangeAccountId, params?.botId],
    queryFn: () => fetchPendingOrders({
      exchangeAccountId: params?.exchangeAccountId || undefined,
      botId: params?.botId || undefined,
    }),
    refetchInterval: 10000,
    staleTime: 5000,
  });

export const useCancelOrder = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, symbol, exchange }: { orderId: string; symbol?: string; exchange?: string }) =>
      cancelOrder(orderId, symbol, exchange),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-orders"] });
    },
  });
};

export const useReplaceOrder = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { orderId: string; symbol?: string; exchange?: string; newPrice?: number; newSize?: number }) =>
      replaceOrder(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-orders"] });
    },
  });
};

export const useExecutionStats = (params?: { exchangeAccountId?: string; botId?: string }) => {
  const scopeHydrated = useScopeHydrated();
  return useQuery({
    queryKey: ["dashboard-execution", params?.exchangeAccountId, params?.botId],
    queryFn: () => fetchExecutionStats(params),
    refetchInterval: 15000,
    staleTime: 10000,
    enabled: scopeHydrated,
  });
};

export const useDashboardRisk = (params?: { exchangeAccountId?: string; botId?: string }) =>
  useQuery({
    queryKey: ["dashboard-risk", params?.exchangeAccountId, params?.botId],
    queryFn: () => fetchDashboardRisk(params),
    refetchInterval: 15000,
    staleTime: 10000,
  });

// ═══════════════════════════════════════════════════════════════
// EXCHANGE CREDENTIALS HOOKS
// ═══════════════════════════════════════════════════════════════

import {
  fetchExchangeCredentials,
  fetchExchangeProfile,
  fetchExchangeLimits,
  createExchangeCredential,
  deleteExchangeCredential,
  verifyExchangeCredential,
  refreshCredentialBalance,
  updateCredentialRiskConfig,
  updateCredentialExecutionConfig,
  updateCredentialMetadata,
  updateCredentialSecrets,
  updateAccountBalance,
  updateTradingCapital,
  setActiveCredential,
  setTradingMode,
  updateEnabledTokens,
  fetchExchangePositions,
  fetchBotPositions,
  fetchOrphanedPositions,
  closePosition,
  closeAllOrphanedPositions,
  fetchSlTpEvents,
  type ExchangeCredential,
} from "./client";

export const useExchangeCredentials = () =>
  useQuery({
    queryKey: ["exchange-credentials"],
    queryFn: fetchExchangeCredentials,
    staleTime: 30000,
  });

export const useExchangeProfile = () =>
  useQuery({
    queryKey: ["exchange-profile"],
    queryFn: fetchExchangeProfile,
    staleTime: 30000,
  });

export const useExchangeLimits = (exchange: string) =>
  useQuery({
    queryKey: ["exchange-limits", exchange],
    queryFn: () => fetchExchangeLimits(exchange),
    enabled: !!exchange,
    staleTime: 300000,
  });

export const useCreateExchangeCredential = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createExchangeCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
  });
};

export const useDeleteExchangeCredential = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteExchangeCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
  });
};

export const useVerifyExchangeCredential = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: verifyExchangeCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
  });
};

export const useRefreshCredentialBalance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: refreshCredentialBalance,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
  });
};

export const useUpdateCredentialRiskConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ credentialId, riskConfig }: { credentialId: string; riskConfig: Record<string, unknown> }) =>
      updateCredentialRiskConfig(credentialId, riskConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
  });
};

export const useUpdateCredentialExecutionConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ credentialId, executionConfig }: { credentialId: string; executionConfig: Record<string, unknown> }) =>
      updateCredentialExecutionConfig(credentialId, executionConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
  });
};

export const useSetActiveCredential = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: setActiveCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
  });
};

export const useSetTradingMode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: setTradingMode,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
  });
};

// ═══════════════════════════════════════════════════════════════
// DASHBOARD POSITION HOOKS
// ═══════════════════════════════════════════════════════════════

export const useExchangePositions = () =>
  useQuery({
    queryKey: ["exchange-positions"],
    queryFn: fetchExchangePositions,
    refetchInterval: 10000,
  });

// Bot positions from Redis (primary for active bot)
export const useBotPositions = (options?: { exchangeAccountId?: string; botId?: string }) =>
  useQuery({
    queryKey: ["bot-positions", options?.exchangeAccountId, options?.botId],
    queryFn: () => fetchBotPositions(options),
    refetchInterval: 5000, // Faster refresh for live positions
  });

export const useOrphanedPositions = () =>
  useQuery({
    queryKey: ["orphaned-positions"],
    queryFn: fetchOrphanedPositions,
    refetchInterval: 15000,
  });

export const useClosePosition = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ symbol, side, quantity }: { symbol: string; side: string; quantity: number }) =>
      closePosition(symbol, side, quantity),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-positions"] });
      queryClient.invalidateQueries({ queryKey: ["orphaned-positions"] });
    },
  });
};

export const useCloseAllOrphanedPositions = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: closeAllOrphanedPositions,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-positions"] });
      queryClient.invalidateQueries({ queryKey: ["orphaned-positions"] });
    },
  });
};

export const useSlTpEvents = (limit = 50) =>
  useQuery({
    queryKey: ["sl-tp-events", limit],
    queryFn: () => fetchSlTpEvents(limit),
    refetchInterval: 10000,
  });

// ============================================================================
// Mode-aware bot lifecycle hooks (new exchange-first architecture)
// ============================================================================

import { startBotById, stopBotById, pauseBotById, resumeBotById } from "./control";

/**
 * Start a specific bot using mode-aware lifecycle service
 * Respects operating modes (SOLO/TEAM/PROP)
 */
export const useStartBotById = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, options }: { botId: string; options?: { force?: boolean } }) =>
      startBotById(botId, options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
    },
  });
};

/**
 * Stop a specific bot using mode-aware lifecycle service
 */
export const useStopBotById = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => stopBotById(botId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
    },
  });
};

/**
 * Pause a specific bot (keeps positions, stops new orders)
 */
export const usePauseBotById = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => pauseBotById(botId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
    },
  });
};

/**
 * Resume a paused bot
 */
export const useResumeBotById = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => resumeBotById(botId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
    },
  });
};

// ═══════════════════════════════════════════════════════════════
// STRATEGY INSTANCES HOOKS
// ═══════════════════════════════════════════════════════════════

import {
  fetchStrategyInstances,
  fetchStrategyInstanceTemplates,
  fetchStrategyInstance,
  fetchStrategyInstanceUsage,
  createStrategyInstance,
  updateStrategyInstance,
  cloneStrategyInstance,
  archiveStrategyInstance,
  deprecateStrategyInstance,
  restoreStrategyInstance,
  deleteStrategyInstance,
  fetchUserProfiles,
  fetchUserProfile,
  fetchProfileDiff,
  createUserProfile,
  updateUserProfile,
  promoteUserProfile,
  cloneUserProfile,
  activateUserProfile,
  deactivateUserProfile,
  archiveUserProfile,
  deleteUserProfile,
  mountProfile,
  unmountProfile,
  fetchDeploymentStatus,
  refreshDeployment,
  fetchDeployments,
} from "./client";

/**
 * Fetch all strategy instances for the current user (including system templates)
 */
export const useStrategyInstances = (params?: { status?: string; templateId?: string; includeSystemTemplates?: boolean }) => {
  return useQuery({
    queryKey: ["strategy-instances", params],
    queryFn: () => fetchStrategyInstances(params),
  });
};

/**
 * Fetch system template strategy instances (library)
 */
export const useStrategyInstanceTemplates = () => {
  return useQuery({
    queryKey: ["strategy-instance-templates"],
    queryFn: () => fetchStrategyInstanceTemplates(),
  });
};

/**
 * Fetch a single strategy instance
 */
export const useStrategyInstance = (id: string) => {
  return useQuery({
    queryKey: ["strategy-instance", id],
    queryFn: () => fetchStrategyInstance(id),
    enabled: !!id,
  });
};

/**
 * Fetch usage information for a strategy instance
 */
export const useStrategyInstanceUsage = (id: string) => {
  return useQuery({
    queryKey: ["strategy-instance-usage", id],
    queryFn: () => fetchStrategyInstanceUsage(id),
    enabled: !!id,
  });
};

/**
 * Create a new strategy instance
 */
export const useCreateStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createStrategyInstance,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
    },
  });
};

/**
 * Update a strategy instance
 */
export const useUpdateStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateStrategyInstance>[1] }) =>
      updateStrategyInstance(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
      queryClient.invalidateQueries({ queryKey: ["strategy-instance", variables.id] });
    },
  });
};

/**
 * Clone a strategy instance
 */
export const useCloneStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name?: string }) => cloneStrategyInstance(id, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
    },
  });
};

/**
 * Archive a strategy instance
 */
export const useArchiveStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: archiveStrategyInstance,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
      queryClient.invalidateQueries({ queryKey: ["strategy-instance", id] });
    },
  });
};

/**
 * Deprecate a strategy instance
 */
export const useDeprecateStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deprecateStrategyInstance,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
      queryClient.invalidateQueries({ queryKey: ["strategy-instance", id] });
    },
  });
};

/**
 * Restore a strategy instance
 */
export const useRestoreStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: restoreStrategyInstance,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
      queryClient.invalidateQueries({ queryKey: ["strategy-instance", id] });
    },
  });
};

/**
 * Delete a strategy instance
 */
export const useDeleteStrategyInstance = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteStrategyInstance,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategy-instances"] });
    },
  });
};

// ═══════════════════════════════════════════════════════════════
// USER PROFILES HOOKS
// ═══════════════════════════════════════════════════════════════

/**
 * Fetch all user profiles
 */
export const useUserProfiles = (params?: { environment?: string; status?: string; isActive?: boolean }) => {
  return useQuery({
    queryKey: ["user-profiles", params],
    queryFn: () => fetchUserProfiles(params),
  });
};

/**
 * Fetch a single user profile with versions
 */
export const useUserProfile = (id: string) => {
  return useQuery({
    queryKey: ["user-profile", id],
    queryFn: () => fetchUserProfile(id),
    enabled: !!id,
  });
};

/**
 * Fetch diff between two profile versions
 */
export const useProfileDiff = (id: string, versionA: number, versionB: number) => {
  return useQuery({
    queryKey: ["profile-diff", id, versionA, versionB],
    queryFn: () => fetchProfileDiff(id, versionA, versionB),
    enabled: !!id && versionA > 0 && versionB > 0,
  });
};

/**
 * Create a new user profile
 */
export const useCreateUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createUserProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
    },
  });
};

/**
 * Update a user profile
 */
export const useUpdateUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateUserProfile>[1] }) =>
      updateUserProfile(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["user-profile", variables.id] });
    },
  });
};

/**
 * Promote a user profile to the next environment
 */
export const usePromoteUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) => promoteUserProfile(id, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
    },
  });
};

/**
 * Clone a user profile (including system templates)
 */
export const useCloneUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name, environment }: { id: string; name?: string; environment?: string }) => 
      cloneUserProfile(id, { name, environment }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
    },
  });
};

/**
 * Activate a user profile
 */
export const useActivateUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: activateUserProfile,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["user-profile", id] });
    },
  });
};

/**
 * Deactivate a user profile
 */
export const useDeactivateUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deactivateUserProfile,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["user-profile", id] });
    },
  });
};

/**
 * Archive a user profile
 */
export const useArchiveUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: archiveUserProfile,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["user-profile", id] });
    },
  });
};

/**
 * Delete a user profile
 */
export const useDeleteUserProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteUserProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-profiles"] });
    },
  });
};

// ═══════════════════════════════════════════════════════════════
// DEPLOYMENT HOOKS
// ═══════════════════════════════════════════════════════════════

/**
 * Fetch all deployments
 */
export const useDeployments = (environment?: string) => {
  return useQuery({
    queryKey: ["deployments", environment],
    queryFn: () => fetchDeployments(environment),
  });
};

/**
 * Fetch deployment status for an exchange config
 */
export const useDeploymentStatus = (exchangeConfigId: string) => {
  return useQuery({
    queryKey: ["deployment-status", exchangeConfigId],
    queryFn: () => fetchDeploymentStatus(exchangeConfigId),
    enabled: !!exchangeConfigId,
  });
};

/**
 * Mount a profile to an exchange config
 */
export const useMountProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ exchangeConfigId, profileId }: { exchangeConfigId: string; profileId: string }) =>
      mountProfile(exchangeConfigId, profileId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      queryClient.invalidateQueries({ queryKey: ["deployment-status", variables.exchangeConfigId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-configs"] });
    },
  });
};

/**
 * Unmount a profile from an exchange config
 */
export const useUnmountProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: unmountProfile,
    onSuccess: (_, exchangeConfigId) => {
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      queryClient.invalidateQueries({ queryKey: ["deployment-status", exchangeConfigId] });
      queryClient.invalidateQueries({ queryKey: ["bot-exchange-configs"] });
    },
  });
};

/**
 * Refresh a deployment to the latest profile version
 */
export const useRefreshDeployment = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: refreshDeployment,
    onSuccess: (_, exchangeConfigId) => {
      queryClient.invalidateQueries({ queryKey: ["deployments"] });
      queryClient.invalidateQueries({ queryKey: ["deployment-status", exchangeConfigId] });
    },
  });
};

// ═══════════════════════════════════════════════════════════════
// FORENSIC REPLAY HOOKS
// ═══════════════════════════════════════════════════════════════

/**
 * Fetch paginated replay events for a symbol and time range
 */
export const useReplayEvents = (
  symbol: string,
  start: string,
  end: string,
  options?: { types?: string; limit?: number; offset?: number; includeDetails?: boolean },
  enabled = true
) => {
  return useQuery({
    queryKey: ["replay-events", symbol, start, end, options],
    queryFn: () => fetchReplayEvents(symbol, start, end, options),
    enabled: enabled && !!symbol && !!start && !!end,
    staleTime: 30000, // 30 seconds
  });
};

/**
 * Fetch snapshot at specific timestamp
 */
export const useReplaySnapshot = (symbol: string, timestamp: string, enabled = true) => {
  return useQuery({
    queryKey: ["replay-snapshot", symbol, timestamp],
    queryFn: () => fetchReplaySnapshot(symbol, timestamp),
    enabled: enabled && !!symbol && !!timestamp,
    staleTime: 60000, // 1 minute
  });
};

/**
 * Compare two replay sessions
 */
export const useCompareReplaySessions = () => {
  return useMutation({
    mutationFn: (data: CompareSessionsRequest) => compareReplaySessions(data),
  });
};

/**
 * Fetch session integrity metadata (legacy - requires session ID)
 */
export const useSessionIntegrity = (sessionId: string, enabled = true) => {
  return useQuery({
    queryKey: ["session-integrity", sessionId],
    queryFn: () => fetchSessionIntegrity(sessionId),
    enabled: enabled && !!sessionId,
    staleTime: 60000, // 1 minute
  });
};

/**
 * Fetch integrity metrics by symbol and time range (no session ID required)
 */
export const useIntegrityByTimeRange = (symbol: string, start: string, end: string, enabled = true) => {
  return useQuery({
    queryKey: ["integrity-by-range", symbol, start, end],
    queryFn: () => fetchIntegrityByTimeRange(symbol, start, end),
    enabled: enabled && !!symbol && !!start && !!end,
    staleTime: 60000, // 1 minute
  });
};

/**
 * Fetch feature dictionary for tooltips
 */
export const useFeatureDictionary = () => {
  return useQuery({
    queryKey: ["feature-dictionary"],
    queryFn: fetchFeatureDictionary,
    staleTime: 300000, // 5 minutes - rarely changes
  });
};

/**
 * Fetch annotations for a session
 */
export const useReplayAnnotations = (sessionId: string, enabled = true) => {
  return useQuery({
    queryKey: ["replay-annotations", sessionId],
    queryFn: () => fetchReplayAnnotations(sessionId),
    enabled: enabled && !!sessionId,
  });
};

/**
 * Create annotation mutation
 */
export const useCreateReplayAnnotation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createReplayAnnotation,
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["replay-annotations", variables.sessionId] });
    },
  });
};

/**
 * Delete annotation mutation
 */
export const useDeleteReplayAnnotation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteReplayAnnotation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["replay-annotations"] });
    },
  });
};

/**
 * Fetch outcome summary for symbol and time range
 */
export const useOutcomeSummary = (symbol: string, start: string, end: string, enabled = true) => {
  return useQuery({
    queryKey: ["outcome-summary", symbol, start, end],
    queryFn: () => fetchOutcomeSummary(symbol, start, end),
    enabled: enabled && !!symbol && !!start && !!end,
    staleTime: 30000,
  });
};

/**
 * Fetch live status for StatusStrip and OpsKPICards
 */
export const useLiveStatus = (params?: { exchangeAccountId?: string | null; botId?: string | null }) => {
  return useQuery({
    queryKey: ["live-status", params?.exchangeAccountId, params?.botId],
    queryFn: async () => {
      const response = await api.get("/dashboard/live-status", {
        params: {
          ...(params?.exchangeAccountId ? { exchangeAccountId: params.exchangeAccountId } : {}),
          ...(params?.botId ? { botId: params.botId } : {}),
        },
      });
      return response.data?.data || response.data;
    },
    refetchInterval: 3000, // Fast refresh for live data
    staleTime: 2000,
    placeholderData: (previousData) => previousData,
  });
};
