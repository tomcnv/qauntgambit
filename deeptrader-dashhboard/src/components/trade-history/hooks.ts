/**
 * Hooks for Quant-Grade Trade History page
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useScopeStore } from '../../store/scope-store';
import { apiFetch, fetchPredictionHistory, fetchTradeDetail, fetchTradeHistory } from '../../lib/api/client';
import type { RuntimePredictionPayload } from '../../lib/api/types';
import {
  CohortFilters,
  AdvancedFilters,
  SavedView,
  QuantTrade,
  CohortStats,
  DEFAULT_COHORT_FILTERS,
  DEFAULT_ADVANCED_FILTERS,
  EMPTY_COHORT_STATS,
  TimeRange,
} from './types';

// ═══════════════════════════════════════════════════════════════
// DATE HELPERS
// ═══════════════════════════════════════════════════════════════

function getDateRangeFromTimeRange(timeRange: TimeRange): { startDate: string; endDate: string } {
  const now = new Date();
  const endDate = now.toISOString().split('T')[0];
  let startDate: string;
  
  switch (timeRange) {
    case '1D':
      startDate = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      break;
    case '7D':
      startDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      break;
    case '30D':
      startDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      break;
    case '90D':
      startDate = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      break;
    case 'YTD':
      startDate = `${now.getFullYear()}-01-01`;
      break;
    case 'ALL':
    default:
      startDate = '2020-01-01'; // Reasonable far-back date
      break;
  }
  
  return { startDate, endDate };
}

export function mapRawTrade(t: any): QuantTrade {
  const parseNum = (value: any): number | undefined => {
    if (value === null || value === undefined || value === '') return undefined;
    const n = Number(value);
    return Number.isFinite(n) ? n : undefined;
  };
  const parseEpochMs = (value: any): number | undefined => {
    const n = parseNum(value);
    if (n === undefined) return undefined;
    return n < 1e12 ? n * 1000 : n;
  };
  const fees = parseFloat(t.total_fees_usd ?? t.fees ?? t.fee ?? 0);
  const grossPnl = parseFloat(t.gross_pnl ?? t.realized_pnl ?? t.realizedPnl ?? t.pnl ?? 0);
  // Backend `net_pnl` (or `pnl` in normalized payloads) is already net-of-fees.
  // Do not subtract fees again in the UI mapper.
  const netPnl = parseFloat(t.net_pnl ?? t.netPnl ?? t.pnl ?? t.realized_pnl ?? 0);
  const makerPercent = parseNum(t.makerPercent ?? t.maker_percent);
  const liquidityRaw = String(t.liquidity ?? "").toLowerCase();
  const liquidity =
    liquidityRaw === "maker" || makerPercent === 1
      ? "maker"
      : liquidityRaw === "taker" || makerPercent === 0
      ? "taker"
      : typeof makerPercent === "number"
      ? "mixed"
      : "unknown";
  const rawSide = String(
    t.position_side ??
    t.positionSide ??
    t.original_side ??
    t.originalSide ??
    t.side ??
    ""
  ).toLowerCase();

  return {
    id: t.id || t.trade_id || `${t.symbol}-${t.timestamp}`,
    timestamp: t.timestamp || new Date(t.executed_at || t.created_at).getTime(),
    symbol: t.symbol,
    side: (rawSide as 'long' | 'short' | 'buy' | 'sell') || 'buy',
    profileId: t.profile_id || t.profileId,
    profileName: t.profile_name || t.profileName,
    strategyId: t.strategy_id || t.strategyId,
    strategyName: t.strategy_name || t.strategyName || t.strategy,
    botId: t.bot_id || t.botId,
    botName: t.bot_name || t.botName,
    quantity: parseFloat(t.quantity || t.size || 0),
    notional:
      parseFloat(t.notional || 0) ||
      parseFloat(t.quantity || 0) * parseFloat(t.entry_price || t.entryPrice || 0),
    leverage: parseFloat(t.leverage || 1),
    riskPercent: t.risk_percent || t.riskPercent,
    holdTimeSeconds: t.hold_time_seconds || t.holdTimeSeconds || 0,
    entryPrice: parseFloat(t.entry_price || t.entryPrice || 0),
    exitPrice: parseFloat(t.exit_price || t.exitPrice || 0),
    entryTime: t.entry_time || t.entryTime || t.timestamp,
    exitTime: t.exit_time || t.exitTime,
    realizedPnl: grossPnl,
    pnlBps: t.pnl_bps || t.pnlBps || 0,
    fees,
    netPnl,
    rMultiple: t.r_multiple || t.rMultiple,
    mae: t.mae,
    mfe: t.mfe,
    maeBps: t.mae_bps || t.maeBps,
    mfeBps: t.mfe_bps || t.mfeBps,
    slippageBps: t.slippage_bps || t.slippageBps || t.slippage,
    entrySlippageBps: parseNum(t.entry_slippage_bps ?? t.entrySlippageBps),
    exitSlippageBps: parseNum(t.exit_slippage_bps ?? t.exitSlippageBps),
    latencyMs: t.latency_ms || t.latencyMs || t.latency,
    liquidity,
    makerPercent,
    fillsCount: t.fills_count || t.fillsCount || 1,
    rejections: t.rejections || 0,
    entryFeeUsd: parseNum(t.entry_fee_usd ?? t.entryFeeUsd),
    exitFeeUsd: parseNum(t.exit_fee_usd ?? t.exitFeeUsd),
    totalFeesUsd: parseNum(t.total_fees_usd ?? t.totalFeesUsd),
    spreadCostBps: parseNum(t.spread_cost_bps ?? t.spreadCostBps),
    totalCostBps: parseNum(t.total_cost_bps ?? t.totalCostBps),
    midAtSend: parseNum(t.mid_at_send ?? t.midAtSend),
    expectedPriceAtSend: parseNum(t.expected_price_at_send ?? t.expectedPriceAtSend),
    sendTs: parseEpochMs(t.send_ts ?? t.sendTs),
    ackTs: parseEpochMs(t.ack_ts ?? t.ackTs),
    firstFillTs: parseEpochMs(t.first_fill_ts ?? t.firstFillTs),
    finalFillTs: parseEpochMs(t.final_fill_ts ?? t.finalFillTs),
    postOnlyRejectCount: parseNum(t.post_only_reject_count ?? t.postOnlyRejectCount),
    cancelAfterTimeoutCount: parseNum(t.cancel_after_timeout_count ?? t.cancelAfterTimeoutCount),
    orderType: t.order_type || t.orderType,
    postOnly: t.post_only ?? t.postOnly,
    decisionOutcome: t.decision_outcome || t.decisionOutcome,
    // Prefer explicit normalized reason fields before generic reason.
    exitReason: t.exit_reason || t.exitReason || t.close_reason || t.closed_by || t.reason,
    primaryReason: t.primary_reason || t.primaryReason,
    incidentId: t.incident_id || t.incidentId,
    decisionTraceId: t.decision_trace_id || t.decisionTraceId,
    hasDecisionTrace: !!(t.decision_trace_id || t.decisionTraceId || t.decisionTrace),
    tags: t.tags || [],
    notes: t.notes,
  };
}

// ═══════════════════════════════════════════════════════════════
// useFilteredTrades - Fetches and filters trades based on cohort
// ═══════════════════════════════════════════════════════════════

interface UseFilteredTradesParams {
  filters: CohortFilters;
  advancedFilters?: AdvancedFilters;
  limit?: number;
  offset?: number;
}

interface UseFilteredTradesResult {
  trades: QuantTrade[];
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  pagination: {
    total: number;
    hasMore: boolean;
    offset: number;
    limit: number;
  };
  refetch: () => void;
}

export function useFilteredTrades({
  filters,
  advancedFilters,
  limit = 100,
  offset = 0,
}: UseFilteredTradesParams): UseFilteredTradesResult {
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  
  // Compute date range from timeRange preset
  const dateRange = useMemo(() => {
    if (filters.timeRange === 'CUSTOM' && filters.startDate && filters.endDate) {
      return { startDate: filters.startDate, endDate: filters.endDate };
    }
    return getDateRangeFromTimeRange(filters.timeRange);
  }, [filters.timeRange, filters.startDate, filters.endDate]);
  
  // Build query params
  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      limit: String(limit),
      offset: String(offset),
    };
    
    // Scope
    if (scopeLevel === 'exchange' && exchangeAccountId) {
      params.exchangeAccountId = exchangeAccountId;
    } else if (scopeLevel === 'bot' && botId) {
      // Always carry exchangeAccountId for bot scope to keep backend filters satisfied
      if (exchangeAccountId) {
        params.exchangeAccountId = exchangeAccountId;
      }
      params.botId = botId;
    }
    
    // Date range
    params.startDate = dateRange.startDate;
    params.endDate = dateRange.endDate;
    
    // Symbol filter
    if (filters.symbols.length > 0) {
      params.symbol = filters.symbols.join(',');
    }
    
    // Side filter
    if (filters.side !== 'all') {
      params.side = filters.side;
    }
    
    // Outcome filter (will be applied client-side for now)
    if (filters.minPnl !== undefined) {
      params.minPnl = String(filters.minPnl);
    }
    if (filters.maxPnl !== undefined) {
      params.maxPnl = String(filters.maxPnl);
    }
    
    // Advanced filters - execution
    if (advancedFilters?.slippageMin !== undefined) {
      params.slippageMin = String(advancedFilters.slippageMin);
    }
    if (advancedFilters?.slippageMax !== undefined) {
      params.slippageMax = String(advancedFilters.slippageMax);
    }
    if (advancedFilters?.latencyMin !== undefined) {
      params.latencyMin = String(advancedFilters.latencyMin);
    }
    if (advancedFilters?.latencyMax !== undefined) {
      params.latencyMax = String(advancedFilters.latencyMax);
    }
    
    // Advanced filters - session
    if (advancedFilters?.session && advancedFilters.session !== 'all') {
      params.session = advancedFilters.session;
    }
    
    return params;
  }, [
    limit, offset, scopeLevel, exchangeAccountId, botId,
    dateRange, filters, advancedFilters
  ]);
  
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['trade-history-v2', queryParams],
    queryFn: () => fetchTradeHistory(queryParams),
    staleTime: 15000,
    refetchInterval: 60000,
  });
  
  // Transform and apply client-side filters
  const trades = useMemo<QuantTrade[]>(() => {
    const rawTrades = data?.trades || [];
    
    return rawTrades
      .map((t: any): QuantTrade => mapRawTrade(t))
      .filter((trade: QuantTrade) => {
        // Apply client-side outcome filter
        if (filters.outcome !== 'all') {
          const isWin = trade.netPnl > 0;
          const isLoss = trade.netPnl < 0;
          if (filters.outcome === 'win' && !isWin) return false;
          if (filters.outcome === 'loss' && !isLoss) return false;
          if (filters.outcome === 'flat' && (isWin || isLoss)) return false;
        }
        
        // Apply strategy/profile filters if needed
        if (filters.strategies.length > 0 && trade.strategyId && !filters.strategies.includes(trade.strategyId)) {
          return false;
        }
        if (filters.profiles.length > 0 && trade.profileId && !filters.profiles.includes(trade.profileId)) {
          return false;
        }
        if (filters.bots.length > 0 && trade.botId && !filters.bots.includes(trade.botId)) {
          return false;
        }
        
        return true;
      });
  }, [data?.trades, filters]);
  
  // Check if any client-side filters are active
  const hasClientSideFilters = useMemo(() => {
    return filters.outcome !== 'all' ||
           filters.strategies.length > 0 ||
           filters.profiles.length > 0 ||
           filters.bots.length > 0;
  }, [filters.outcome, filters.strategies, filters.profiles, filters.bots]);

  const pagination = useMemo(() => {
    // If client-side filters are active, use the filtered trades length
    // Otherwise use the server's total count
    const total = hasClientSideFilters 
      ? trades.length 
      : (data?.pagination?.total || trades.length);
    
    return {
      total,
      hasMore: hasClientSideFilters ? false : (data?.pagination?.hasMore || false),
      offset: hasClientSideFilters ? 0 : offset,
      limit,
    };
  }, [data?.pagination, trades.length, offset, limit, hasClientSideFilters]);
  
  return {
    trades,
    isLoading,
    isFetching,
    error: error as Error | null,
    pagination,
    refetch,
  };
}

// ═══════════════════════════════════════════════════════════════
// useCohortStats - Calculates statistics from filtered trades
// ═══════════════════════════════════════════════════════════════

export function useCohortStats(trades: QuantTrade[]): CohortStats {
  return useMemo(() => {
    if (trades.length === 0) return EMPTY_COHORT_STATS;
    
    const winningTrades = trades.filter(t => t.netPnl > 0);
    const losingTrades = trades.filter(t => t.netPnl < 0);
    const flatTrades = trades.filter(t => t.netPnl === 0);
    
    const grossPnl = trades.reduce((sum, t) => sum + t.realizedPnl, 0);
    const totalFees = trades.reduce((sum, t) => sum + t.fees, 0);
    const netPnl = trades.reduce((sum, t) => sum + t.netPnl, 0);
    
    const pnlValues = trades.map(t => t.netPnl).sort((a, b) => a - b);
    const medianPnl = pnlValues.length > 0 
      ? pnlValues[Math.floor(pnlValues.length / 2)] 
      : 0;
    
    // Profit factor
    const totalWins = winningTrades.reduce((sum, t) => sum + t.netPnl, 0);
    const totalLosses = Math.abs(losingTrades.reduce((sum, t) => sum + t.netPnl, 0));
    const profitFactor = totalLosses > 0 ? totalWins / totalLosses : totalWins > 0 ? Infinity : 0;
    
    // Execution averages
    const avgSlippageBps = trades.reduce((sum, t) => sum + (t.slippageBps || 0), 0) / trades.length;
    const avgLatencyMs = trades.reduce((sum, t) => sum + (t.latencyMs || 0), 0) / trades.length;
    
    // MAE/MFE
    const tradesWithMae = trades.filter(t => t.maeBps !== undefined);
    const tradesWithMfe = trades.filter(t => t.mfeBps !== undefined);
    const avgMaeBps = tradesWithMae.length > 0 
      ? tradesWithMae.reduce((sum, t) => sum + (t.maeBps || 0), 0) / tradesWithMae.length 
      : undefined;
    const avgMfeBps = tradesWithMfe.length > 0 
      ? tradesWithMfe.reduce((sum, t) => sum + (t.mfeBps || 0), 0) / tradesWithMfe.length 
      : undefined;
    
    // R-Multiple average
    const tradesWithR = trades.filter(t => t.rMultiple !== undefined);
    const avgR = tradesWithR.length > 0 
      ? tradesWithR.reduce((sum, t) => sum + (t.rMultiple || 0), 0) / tradesWithR.length 
      : undefined;
    
    // Best/Worst by symbol
    const symbolPnl = trades.reduce((acc, t) => {
      acc[t.symbol] = (acc[t.symbol] || 0) + t.netPnl;
      return acc;
    }, {} as Record<string, number>);
    const symbolEntries = Object.entries(symbolPnl).sort((a, b) => b[1] - a[1]);
    const bestSymbol = symbolEntries.length > 0 ? symbolEntries[0][0] : undefined;
    const worstSymbol = symbolEntries.length > 0 ? symbolEntries[symbolEntries.length - 1][0] : undefined;
    
    // Best/Worst by profile
    const profilePnl = trades.reduce((acc, t) => {
      const key = t.profileName || t.profileId || 'unknown';
      acc[key] = (acc[key] || 0) + t.netPnl;
      return acc;
    }, {} as Record<string, number>);
    const profileEntries = Object.entries(profilePnl).sort((a, b) => b[1] - a[1]);
    const bestProfile = profileEntries.length > 0 && profileEntries[0][0] !== 'unknown' ? profileEntries[0][0] : undefined;
    const worstProfile = profileEntries.length > 0 && profileEntries[profileEntries.length - 1][0] !== 'unknown' 
      ? profileEntries[profileEntries.length - 1][0] 
      : undefined;
    
    // Distributions for histograms
    const pnlDistribution = createDistribution(trades.map(t => t.netPnl), 20);
    const holdTimeDistribution = createDistribution(trades.map(t => t.holdTimeSeconds / 60), 20); // in minutes
    const slippageDistribution = createDistribution(trades.map(t => t.slippageBps || 0), 20);
    
    // Rejection rate (trades with rejected decisions / total evaluated)
    const rejectedCount = trades.filter(t => t.decisionOutcome === 'rejected').length;
    const rejectRate = trades.length > 0 ? (rejectedCount / trades.length) * 100 : 0;
    
    return {
      totalTrades: trades.length,
      winningTrades: winningTrades.length,
      losingTrades: losingTrades.length,
      flatTrades: flatTrades.length,
      winRate: trades.length > 0 ? (winningTrades.length / trades.length) * 100 : 0,
      grossPnl,
      totalFees,
      netPnl,
      avgPnl: netPnl / trades.length,
      medianPnl,
      avgR,
      profitFactor,
      avgSlippageBps,
      avgLatencyMs,
      rejectRate,
      avgMaeBps,
      avgMfeBps,
      bestSymbol,
      worstSymbol,
      bestProfile,
      worstProfile,
      largestWin: winningTrades.length > 0 ? Math.max(...winningTrades.map(t => t.netPnl)) : 0,
      largestLoss: losingTrades.length > 0 ? Math.min(...losingTrades.map(t => t.netPnl)) : 0,
      pnlDistribution,
      holdTimeDistribution,
      slippageDistribution,
    };
  }, [trades]);
}

// Helper to create histogram distribution
function createDistribution(values: number[], bins: number): number[] {
  if (values.length === 0) return [];
  
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const binWidth = range / bins;
  
  const distribution = new Array(bins).fill(0);
  values.forEach(v => {
    const binIndex = Math.min(Math.floor((v - min) / binWidth), bins - 1);
    distribution[binIndex]++;
  });
  
  return distribution;
}

// ═══════════════════════════════════════════════════════════════
// useSavedViews - Manages saved filter views in localStorage
// ═══════════════════════════════════════════════════════════════

const SAVED_VIEWS_KEY = 'deeptrader_trade_history_views';

export function useSavedViews() {
  const [views, setViews] = useState<SavedView[]>(() => {
    try {
      const stored = localStorage.getItem(SAVED_VIEWS_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  
  // Persist to localStorage whenever views change
  useEffect(() => {
    try {
      localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(views));
    } catch (e) {
      console.error('Failed to save views to localStorage:', e);
    }
  }, [views]);
  
  const saveView = useCallback((
    name: string,
    filters: CohortFilters,
    advancedFilters?: AdvancedFilters,
    columnPreset: 'execution' | 'risk' | 'research' | 'all' = 'all'
  ) => {
    const newView: SavedView = {
      id: `view_${Date.now()}`,
      name,
      filters,
      advancedFilters,
      columnPreset,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    
    setViews(prev => [...prev, newView]);
    return newView;
  }, []);
  
  const updateView = useCallback((id: string, updates: Partial<SavedView>) => {
    setViews(prev => prev.map(v => 
      v.id === id 
        ? { ...v, ...updates, updatedAt: new Date().toISOString() }
        : v
    ));
  }, []);
  
  const deleteView = useCallback((id: string) => {
    setViews(prev => prev.filter(v => v.id !== id));
  }, []);
  
  const setDefaultView = useCallback((id: string) => {
    setViews(prev => prev.map(v => ({
      ...v,
      isDefault: v.id === id,
    })));
  }, []);
  
  const getDefaultView = useCallback(() => {
    return views.find(v => v.isDefault);
  }, [views]);
  
  return {
    views,
    saveView,
    updateView,
    deleteView,
    setDefaultView,
    getDefaultView,
  };
}

// ═══════════════════════════════════════════════════════════════
// useTradeInspector - Fetches detailed data for trade inspector
// ═══════════════════════════════════════════════════════════════

function toEpochMs(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e12 ? value : value * 1000;
  }
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric > 1e12 ? numeric : numeric * 1000;
    }
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function chooseMatchedPrediction(
  items: RuntimePredictionPayload[],
  symbol: string | null | undefined,
  centerMs: number
): RuntimePredictionPayload | null {
  const normalizedSymbol = String(symbol || '').toUpperCase();
  const candidates = items.filter((item) => {
    const itemSymbol = String(item.symbol || '').toUpperCase();
    return !normalizedSymbol || !itemSymbol || itemSymbol === normalizedSymbol;
  });
  if (!candidates.length) return null;
  return [...candidates].sort((a, b) => {
    const aTs = toEpochMs(a.ts ?? a.timestamp) ?? 0;
    const bTs = toEpochMs(b.ts ?? b.timestamp) ?? 0;
    const aDelta = Math.abs(aTs - centerMs);
    const bDelta = Math.abs(bTs - centerMs);
    if (aDelta !== bDelta) return aDelta - bDelta;
    return bTs - aTs;
  })[0] ?? null;
}

export function useTradeInspector(
  tradeId: string | null,
  options?: { symbol?: string | null; botId?: string | null; entryTime?: number | null; timestamp?: number | null }
) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['trade-inspector', tradeId, options?.botId, options?.symbol, options?.entryTime, options?.timestamp],
    queryFn: async () => {
      if (!tradeId) return null;
      const detail = await fetchTradeDetail(tradeId);
      const detailTrade = detail?.trade as Record<string, unknown> | undefined;
      const botId = options?.botId || (typeof detailTrade?.botId === 'string' ? detailTrade.botId : null);
      if (!botId) {
        return { ...detail, aiTrace: null };
      }
      const centerMs =
        options?.entryTime ??
        toEpochMs(detailTrade?.entryTime) ??
        options?.timestamp ??
        Date.now();
      const symbol =
        options?.symbol ||
        (typeof detailTrade?.symbol === 'string' ? detailTrade.symbol : null);
      const predictionHistory = await fetchPredictionHistory({
        botId,
        symbol: symbol || undefined,
        limit: 50,
      }).catch(() => ({ items: [], total: 0 }));
      const items = Array.isArray(predictionHistory?.items) ? predictionHistory.items : [];
      const matchedPrediction = chooseMatchedPrediction(items, symbol, centerMs);
      return {
        ...detail,
        aiTrace: {
          matchedPrediction,
          recentPredictions: items.slice(0, 8),
          botId,
          systemOutcome:
            (detail?.decisionTrace as Record<string, unknown> | undefined)?.outcome as string | undefined ??
            (detailTrade?.decisionOutcome as string | undefined) ??
            null,
          systemReason:
            (detail?.decisionTrace as Record<string, unknown> | undefined)?.primaryReason as string | undefined ??
            null,
        },
      };
    },
    enabled: !!tradeId,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  });
  
  return {
    data: data?.trade || null,
    decisionTrace: data?.decisionTrace || null,
    aiTrace: data?.aiTrace || null,
    fills: data?.fills || [],
    marketContext: data?.marketContext || null,
    isLoading,
    error: error as Error | null,
  };
}

// ═══════════════════════════════════════════════════════════════
// useDecisionTraces - Fetches decision traces for blocked toggle
// ═══════════════════════════════════════════════════════════════

export function useBlockedDecisions(params?: {
  startDate?: string;
  endDate?: string;
  symbol?: string;
  limit?: number;
}) {
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  
  const queryParams = useMemo(() => {
    const p: Record<string, string> = {
      decisionOutcome: 'rejected',
      limit: String(params?.limit || 100),
    };
    
    if (scopeLevel === 'exchange' && exchangeAccountId) {
      p.exchangeAccountId = exchangeAccountId;
    } else if (scopeLevel === 'bot' && botId) {
      p.botId = botId;
    }
    
    if (params?.startDate) p.startDate = params.startDate;
    if (params?.endDate) p.endDate = params.endDate;
    if (params?.symbol) p.symbol = params.symbol;
    
    return p;
  }, [scopeLevel, exchangeAccountId, botId, params]);
  
  const { data, isLoading, error } = useQuery({
    queryKey: ['blocked-decisions', queryParams],
    queryFn: async () => {
      const searchParams = new URLSearchParams(queryParams);
      const response = await apiFetch(`/dashboard/decision-traces?${searchParams.toString()}`);
      
      if (!response.ok) {
        throw new Error('Failed to fetch blocked decisions');
      }
      
      return response.json();
    },
    staleTime: 30000,
  });
  
  return {
    traces: data?.traces || [],
    stats: data?.stats || null,
    isLoading,
    error: error as Error | null,
  };
}
