/**
 * React Query hooks for the Microstructure Prediction Model Dashboard
 */

import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { getAuthToken } from '../../store/auth-store';
import { botApiBaseUrl } from '../quantgambit-url';
import type {
  TimeWindow,
  ModelPulse,
  AccuracyPoint,
  SymbolScoreboardRow,
  ReliabilityBin,
  PredActualPoint,
  ErrorDistribution,
  FilterEffectiveness,
  BlockedCandidateRow,
  ThresholdSweepPoint,
} from '../../types/orderbookModel';

// Dynamic URL detection for remote access
function getBotApiBaseUrl(): string {
  return botApiBaseUrl();
}

// Create axios instance without static baseURL
const api = axios.create({
  timeout: 8000,
});

// Add auth and dynamic baseURL interceptor
api.interceptors.request.use((config) => {
  config.baseURL = getBotApiBaseUrl();
  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ============================================================================
// API Client Functions
// ============================================================================

export async function fetchOrderbookModelPulse(
  botId: string,
  window: TimeWindow = '15m',
  symbol: string = 'ALL'
): Promise<ModelPulse> {
  const response = await api.get('/models/orderbook/pulse', {
    params: { botId, window, symbol },
  });
  return response.data;
}

export async function fetchOrderbookModelAccuracySeries(
  botId: string,
  window: TimeWindow = '15m',
  symbol: string = 'ALL'
): Promise<AccuracyPoint[]> {
  const response = await api.get('/models/orderbook/accuracy-series', {
    params: { botId, window, symbol },
  });
  return response.data;
}

export async function fetchOrderbookModelScoreboard(
  botId: string,
  window: TimeWindow = '15m'
): Promise<SymbolScoreboardRow[]> {
  const response = await api.get('/models/orderbook/scoreboard', {
    params: { botId, window },
  });
  return response.data;
}

export async function fetchOrderbookModelReliability(
  botId: string,
  window: TimeWindow = '15m',
  symbol: string = 'ALL',
  minConf: number = 0.5
): Promise<ReliabilityBin[]> {
  const response = await api.get('/models/orderbook/reliability', {
    params: { botId, window, symbol, min_conf: minConf },
  });
  return response.data;
}

export async function fetchOrderbookModelPredVsActual(
  botId: string,
  window: TimeWindow = '15m',
  symbol?: string,
  minConf: number = 0.65,
  minMove: number = 3
): Promise<PredActualPoint[]> {
  const response = await api.get('/models/orderbook/pred-vs-actual', {
    params: { botId, window, symbol, min_conf: minConf, min_move: minMove },
  });
  return response.data;
}

export async function fetchOrderbookModelErrorDist(
  botId: string,
  window: TimeWindow = '15m',
  symbol: string = 'ALL',
  minConf: number = 0.65
): Promise<ErrorDistribution> {
  const response = await api.get('/models/orderbook/error-dist', {
    params: { botId, window, symbol, min_conf: minConf },
  });
  return response.data;
}

export async function fetchOrderbookModelFilterEffectiveness(
  botId: string,
  window: TimeWindow = '15m',
  symbol: string = 'ALL'
): Promise<FilterEffectiveness> {
  const response = await api.get('/models/orderbook/filter-effectiveness', {
    params: { botId, window, symbol },
  });
  return response.data;
}

export async function fetchOrderbookModelBlockedCandidates(
  botId: string,
  window: TimeWindow = '15m',
  symbol?: string,
  limit: number = 200
): Promise<BlockedCandidateRow[]> {
  const response = await api.get('/models/orderbook/blocked-candidates', {
    params: { botId, window, symbol, limit },
  });
  return response.data;
}

export async function fetchOrderbookModelThresholdSweep(
  botId: string,
  window: TimeWindow = '24h',
  symbol: string = 'ALL'
): Promise<ThresholdSweepPoint[]> {
  const response = await api.get('/models/orderbook/threshold-sweep', {
    params: { botId, window, symbol },
  });
  return response.data;
}

// ============================================================================
// React Query Hooks
// ============================================================================

/**
 * Hook for real-time model health summary
 * Refetches every 5 seconds
 */
export function useOrderbookModelPulse(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol: string = 'ALL'
) {
  return useQuery({
    queryKey: ['orderbook-model', 'pulse', botId, window, symbol],
    queryFn: () => fetchOrderbookModelPulse(botId!, window, symbol),
    enabled: !!botId,
    refetchInterval: 5000, // 5 seconds
    staleTime: 4000,
  });
}

/**
 * Hook for rolling accuracy time series
 * Refetches every 10 seconds
 */
export function useOrderbookModelAccuracySeries(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol: string = 'ALL'
) {
  return useQuery({
    queryKey: ['orderbook-model', 'accuracy-series', botId, window, symbol],
    queryFn: () => fetchOrderbookModelAccuracySeries(botId!, window, symbol),
    enabled: !!botId,
    refetchInterval: 10000, // 10 seconds
    staleTime: 8000,
  });
}

/**
 * Hook for per-symbol performance scoreboard
 * Refetches every 5 seconds
 */
export function useOrderbookModelScoreboard(
  botId: string | null | undefined,
  window: TimeWindow = '15m'
) {
  return useQuery({
    queryKey: ['orderbook-model', 'scoreboard', botId, window],
    queryFn: () => fetchOrderbookModelScoreboard(botId!, window),
    enabled: !!botId,
    refetchInterval: 5000,
    staleTime: 4000,
  });
}

/**
 * Hook for confidence calibration bins
 * Refetches every 15 seconds
 */
export function useOrderbookModelReliability(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol: string = 'ALL',
  minConf: number = 0.5
) {
  return useQuery({
    queryKey: ['orderbook-model', 'reliability', botId, window, symbol, minConf],
    queryFn: () => fetchOrderbookModelReliability(botId!, window, symbol, minConf),
    enabled: !!botId,
    refetchInterval: 15000,
    staleTime: 12000,
  });
}

/**
 * Hook for prediction vs actual scatter data
 * Refetches every 10 seconds
 */
export function useOrderbookModelPredVsActual(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol?: string,
  minConf: number = 0.65,
  minMove: number = 3
) {
  return useQuery({
    queryKey: ['orderbook-model', 'pred-vs-actual', botId, window, symbol, minConf, minMove],
    queryFn: () => fetchOrderbookModelPredVsActual(botId!, window, symbol, minConf, minMove),
    enabled: !!botId,
    refetchInterval: 10000,
    staleTime: 8000,
  });
}

/**
 * Hook for error distribution statistics
 * Refetches every 15 seconds
 */
export function useOrderbookModelErrorDist(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol: string = 'ALL',
  minConf: number = 0.65
) {
  return useQuery({
    queryKey: ['orderbook-model', 'error-dist', botId, window, symbol, minConf],
    queryFn: () => fetchOrderbookModelErrorDist(botId!, window, symbol, minConf),
    enabled: !!botId,
    refetchInterval: 15000,
    staleTime: 12000,
  });
}

/**
 * Hook for filter effectiveness metrics
 * Refetches every 5 seconds
 */
export function useOrderbookModelFilterEffectiveness(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol: string = 'ALL'
) {
  return useQuery({
    queryKey: ['orderbook-model', 'filter-effectiveness', botId, window, symbol],
    queryFn: () => fetchOrderbookModelFilterEffectiveness(botId!, window, symbol),
    enabled: !!botId,
    refetchInterval: 5000,
    staleTime: 4000,
  });
}

/**
 * Hook for blocked candidates table
 * Refetches every 10 seconds
 */
export function useOrderbookModelBlockedCandidates(
  botId: string | null | undefined,
  window: TimeWindow = '15m',
  symbol?: string,
  limit: number = 200
) {
  return useQuery({
    queryKey: ['orderbook-model', 'blocked-candidates', botId, window, symbol, limit],
    queryFn: () => fetchOrderbookModelBlockedCandidates(botId!, window, symbol, limit),
    enabled: !!botId,
    refetchInterval: 10000,
    staleTime: 8000,
  });
}

/**
 * Hook for threshold sweep analysis
 * Refetches every 30 seconds (less frequent - this is for tuning)
 */
export function useOrderbookModelThresholdSweep(
  botId: string | null | undefined,
  window: TimeWindow = '24h',
  symbol: string = 'ALL'
) {
  return useQuery({
    queryKey: ['orderbook-model', 'threshold-sweep', botId, window, symbol],
    queryFn: () => fetchOrderbookModelThresholdSweep(botId!, window, symbol),
    enabled: !!botId,
    refetchInterval: 30000,
    staleTime: 25000,
  });
}
