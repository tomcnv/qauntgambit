/**
 * Paper Trading React Query Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchPaperPositions,
  fetchPaperPosition,
  fetchPaperOrders,
  fetchPaperTrades,
  fetchPaperBalance,
  resetPaperAccount,
  fetchPaperTradingSummary,
  PaperPosition,
  PaperOrder,
  PaperTrade,
  PaperBalance,
  PaperTradingSummary,
} from './paper-trading';

// Query Keys
export const paperTradingKeys = {
  all: ['paper-trading'] as const,
  positions: (exchangeAccountId: string, status?: string) => 
    [...paperTradingKeys.all, 'positions', exchangeAccountId, status] as const,
  position: (exchangeAccountId: string, symbol: string) =>
    [...paperTradingKeys.all, 'position', exchangeAccountId, symbol] as const,
  orders: (exchangeAccountId: string) =>
    [...paperTradingKeys.all, 'orders', exchangeAccountId] as const,
  trades: (exchangeAccountId: string) =>
    [...paperTradingKeys.all, 'trades', exchangeAccountId] as const,
  balance: (exchangeAccountId: string) =>
    [...paperTradingKeys.all, 'balance', exchangeAccountId] as const,
  summary: (exchangeAccountId: string) =>
    [...paperTradingKeys.all, 'summary', exchangeAccountId] as const,
};

// =============================================================================
// Positions
// =============================================================================

export function usePaperPositions(
  exchangeAccountId: string | undefined,
  status: 'open' | 'closed' | 'all' = 'open'
) {
  return useQuery<PaperPosition[]>({
    queryKey: paperTradingKeys.positions(exchangeAccountId!, status),
    queryFn: () => fetchPaperPositions(exchangeAccountId!, status),
    enabled: !!exchangeAccountId,
    refetchInterval: 5000, // Refresh every 5 seconds
  });
}

export function usePaperPosition(
  exchangeAccountId: string | undefined,
  symbol: string
) {
  return useQuery<PaperPosition | null>({
    queryKey: paperTradingKeys.position(exchangeAccountId!, symbol),
    queryFn: () => fetchPaperPosition(exchangeAccountId!, symbol),
    enabled: !!exchangeAccountId && !!symbol,
    refetchInterval: 5000,
  });
}

// =============================================================================
// Orders
// =============================================================================

export function usePaperOrders(
  exchangeAccountId: string | undefined,
  params?: { status?: string; limit?: number }
) {
  return useQuery<PaperOrder[]>({
    queryKey: paperTradingKeys.orders(exchangeAccountId!),
    queryFn: () => fetchPaperOrders(exchangeAccountId!, params),
    enabled: !!exchangeAccountId,
    refetchInterval: 5000,
  });
}

// =============================================================================
// Trades
// =============================================================================

export function usePaperTrades(
  exchangeAccountId: string | undefined,
  params?: { limit?: number; offset?: number }
) {
  return useQuery<{ trades: PaperTrade[]; total: number }>({
    queryKey: paperTradingKeys.trades(exchangeAccountId!),
    queryFn: () => fetchPaperTrades(exchangeAccountId!, params),
    enabled: !!exchangeAccountId,
    refetchInterval: 10000, // Refresh every 10 seconds
  });
}

// =============================================================================
// Balance
// =============================================================================

export function usePaperBalance(exchangeAccountId: string | undefined) {
  return useQuery<PaperBalance>({
    queryKey: paperTradingKeys.balance(exchangeAccountId!),
    queryFn: () => fetchPaperBalance(exchangeAccountId!),
    enabled: !!exchangeAccountId,
    refetchInterval: 5000,
  });
}

// =============================================================================
// Summary
// =============================================================================

export function usePaperTradingSummary(exchangeAccountId: string | undefined) {
  return useQuery<PaperTradingSummary>({
    queryKey: paperTradingKeys.summary(exchangeAccountId!),
    queryFn: () => fetchPaperTradingSummary(exchangeAccountId!),
    enabled: !!exchangeAccountId,
    refetchInterval: 10000,
  });
}

// =============================================================================
// Reset Account
// =============================================================================

export function useResetPaperAccount() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ exchangeAccountId, initialBalance }: { 
      exchangeAccountId: string; 
      initialBalance?: number 
    }) => resetPaperAccount(exchangeAccountId, initialBalance),
    onSuccess: (_, { exchangeAccountId }) => {
      // Invalidate all paper trading queries for this account
      queryClient.invalidateQueries({
        queryKey: paperTradingKeys.all,
      });
      queryClient.invalidateQueries({
        predicate: (query) => 
          query.queryKey[0] === 'paper-trading' && 
          query.queryKey[2] === exchangeAccountId,
      });
    },
  });
}
