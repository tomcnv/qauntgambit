/**
 * Unified Trading Hooks
 * 
 * These hooks automatically select the appropriate data source based on the
 * exchange account's configuration:
 * - Demo mode (is_demo=true): Fetch from exchange demo API (Bybit/OKX only)
 * - Paper simulation (environment='paper', is_demo=false): Fetch from paper trading tables
 * - Live mode (environment='live'): Fetch from exchange API (mainnet)
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query';
import { useExchangeAccount } from './exchange-accounts-hooks';
import {
  fetchPaperPositions,
  fetchPaperOrders,
  fetchPaperTrades,
  fetchPaperBalance,
  fetchPaperTradingSummary,
  PaperPosition,
  PaperOrder,
  PaperTrade,
  PaperBalance,
  PaperTradingSummary,
} from './paper-trading';
import { fetchBotPositions } from './client';
import type { ExchangeAccount } from './exchange-accounts';

// =============================================================================
// Types
// =============================================================================

export type TradingMode = 'live' | 'demo' | 'paper_simulation';

export interface UnifiedPosition {
  id: string;
  symbol: string;
  side: 'long' | 'short' | 'LONG' | 'SHORT';
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct?: number;
  leverage?: number;
  margin_used?: number;
  stop_loss?: number | null;
  take_profit?: number | null;
  reference_price?: number | null;
  opened_at?: number | null;
  age_sec?: number | null;
  guard_status?: string | null;
  prediction_confidence?: number | null;
  source: TradingMode;
}

export interface UnifiedBalance {
  total_balance: number;
  available_balance: number;
  margin_used: number;
  unrealized_pnl: number;
  equity: number;
  currency: string;
  source: TradingMode;
}

// =============================================================================
// Utility: Determine Trading Mode
// =============================================================================

export function determineTradingMode(account: ExchangeAccount | null | undefined): TradingMode {
  if (!account) return 'live';
  
  if (account.is_demo) {
    return 'demo';
  }
  
  if (account.environment === 'paper') {
    return 'paper_simulation';
  }
  
  return 'live';
}

// =============================================================================
// Hook: Use Trading Mode
// =============================================================================

export function useTradingMode(exchangeAccountId: string | undefined | null) {
  const { data: accountData } = useExchangeAccount(exchangeAccountId ?? null);
  
  return {
    mode: determineTradingMode(accountData?.account),
    account: accountData?.account,
    isPaperSimulation: accountData?.account?.environment === 'paper' && !accountData?.account?.is_demo,
    isDemo: accountData?.account?.is_demo || false,
    isLive: accountData?.account?.environment === 'live' && !accountData?.account?.is_demo,
  };
}

// =============================================================================
// Hook: Unified Positions
// =============================================================================

export function useUnifiedPositions(exchangeAccountId: string | undefined | null) {
  const { mode, isPaperSimulation } = useTradingMode(exchangeAccountId);
  
  // Paper simulation positions
  const paperQuery = useQuery({
    queryKey: ['unified-positions', 'paper', exchangeAccountId],
    queryFn: () => fetchPaperPositions(exchangeAccountId!, 'open'),
    enabled: !!exchangeAccountId && isPaperSimulation,
    refetchInterval: 5000,
  });
  
  // Live/demo positions from bot
  const liveQuery = useQuery({
    queryKey: ['unified-positions', 'live', exchangeAccountId],
    queryFn: () => fetchBotPositions({ exchangeAccountId: exchangeAccountId ?? undefined }),
    // Allow fleet aggregates (no exchangeAccountId) in live/demo mode
    enabled: !isPaperSimulation,
    refetchInterval: 5000,
  });
  
  // Transform to unified format
  const positions: UnifiedPosition[] = isPaperSimulation
    ? (paperQuery.data || []).map((p: PaperPosition) => ({
        id: p.id,
        symbol: p.symbol,
        side: p.side,
        size: p.size,
        entry_price: p.entry_price,
        current_price: p.current_price || p.entry_price,
        unrealized_pnl: p.unrealized_pnl,
        unrealized_pnl_pct: p.unrealized_pnl_pct,
        leverage: p.leverage,
        margin_used: p.margin_used,
        stop_loss: p.stop_loss,
        take_profit: p.take_profit,
        source: 'paper_simulation' as TradingMode,
      }))
    : ((liveQuery.data as any)?.positions || liveQuery.data?.data || []).map((p: any) => ({
        id: p.id || `${p.symbol}-${p.side}`,
        symbol: p.symbol,
        side: p.side?.toLowerCase() || p.side,
        size: p.qty || p.size || p.quantity,
        entry_price: p.entryPrice || p.entry_price,
        current_price: p.markPrice || p.current_price || p.entryPrice || p.entry_price,
        unrealized_pnl: p.unrealizedPnl || p.unrealized_pnl || 0,
        unrealized_pnl_pct: p.unrealizedPnlPercent || p.unrealized_pnl_pct,
        leverage: p.leverage,
        margin_used: p.marginUsed || p.margin_used,
        stop_loss: p.stopLoss || p.stop_loss,
        take_profit: p.takeProfit || p.take_profit,
        reference_price: p.referencePrice || p.reference_price,
        opened_at: p.openedAt || p.opened_at,
        age_sec: p.ageSec || p.age_sec,
        guard_status: p.guardStatus || p.guard_status,
        prediction_confidence: p.predictionConfidence || p.prediction_confidence,
        source: mode,
      }));
  
  return {
    positions,
    isLoading: isPaperSimulation ? paperQuery.isLoading : liveQuery.isLoading,
    error: isPaperSimulation ? paperQuery.error : liveQuery.error,
    refetch: isPaperSimulation ? paperQuery.refetch : liveQuery.refetch,
    mode,
    isPaperSimulation,
  };
}

// =============================================================================
// Hook: Unified Balance
// =============================================================================

export function useUnifiedBalance(exchangeAccountId: string | undefined | null) {
  const { mode, isPaperSimulation } = useTradingMode(exchangeAccountId);
  
  // Paper simulation balance
  const paperQuery = useQuery({
    queryKey: ['unified-balance', 'paper', exchangeAccountId],
    queryFn: () => fetchPaperBalance(exchangeAccountId!),
    enabled: !!exchangeAccountId && isPaperSimulation,
    refetchInterval: 10000,
  });
  
  // For live/demo, we'll use the exchange account's cached balance
  const { data: accountData } = useExchangeAccount(exchangeAccountId ?? null);
  
  const balance: UnifiedBalance | null = isPaperSimulation && paperQuery.data
    ? {
        total_balance: paperQuery.data.balance,
        available_balance: paperQuery.data.available_balance,
        margin_used: paperQuery.data.balance - paperQuery.data.available_balance,
        unrealized_pnl: paperQuery.data.unrealized_pnl || 0,
        equity: paperQuery.data.equity || paperQuery.data.balance,
        currency: paperQuery.data.currency || 'USDT',
        source: 'paper_simulation',
      }
    : accountData?.account ? {
        total_balance: accountData.account.exchange_balance || 0,
        available_balance: accountData.account.available_balance || 0,
        margin_used: accountData.account.margin_used || 0,
        unrealized_pnl: accountData.account.unrealized_pnl || 0,
        equity: (accountData.account.exchange_balance || 0) + (accountData.account.unrealized_pnl || 0),
        currency: accountData.account.balance_currency || 'USDT',
        source: mode,
      }
    : null;
  
  return {
    balance,
    isLoading: isPaperSimulation ? paperQuery.isLoading : false,
    error: isPaperSimulation ? paperQuery.error : null,
    mode,
    isPaperSimulation,
  };
}

// =============================================================================
// Hook: Unified Trading Summary
// =============================================================================

export function useUnifiedTradingSummary(exchangeAccountId: string | undefined) {
  const { mode, isPaperSimulation } = useTradingMode(exchangeAccountId);
  
  const paperQuery = useQuery({
    queryKey: ['unified-summary', 'paper', exchangeAccountId],
    queryFn: () => fetchPaperTradingSummary(exchangeAccountId!),
    enabled: !!exchangeAccountId && isPaperSimulation,
    refetchInterval: 30000,
  });
  
  return {
    summary: isPaperSimulation ? paperQuery.data : null,
    isLoading: isPaperSimulation ? paperQuery.isLoading : false,
    error: isPaperSimulation ? paperQuery.error : null,
    mode,
    isPaperSimulation,
    // Only meaningful in paper simulation mode
    isAvailable: isPaperSimulation,
  };
}

// =============================================================================
// Hook: Unified Trades/Orders
// =============================================================================

export function useUnifiedTrades(
  exchangeAccountId: string | undefined,
  limit: number = 100
) {
  const { mode, isPaperSimulation } = useTradingMode(exchangeAccountId);
  
  const paperQuery = useQuery({
    queryKey: ['unified-trades', 'paper', exchangeAccountId, limit],
    queryFn: () => fetchPaperTrades(exchangeAccountId!, { limit }),
    enabled: !!exchangeAccountId && isPaperSimulation,
    refetchInterval: 10000,
  });
  
  // For live mode, we'd fetch from the existing trade history endpoint
  // This is a stub - in production you'd fetch from your trade history API
  
  return {
    trades: isPaperSimulation ? paperQuery.data?.trades || [] : [],
    total: isPaperSimulation ? paperQuery.data?.total || 0 : 0,
    isLoading: isPaperSimulation ? paperQuery.isLoading : false,
    error: isPaperSimulation ? paperQuery.error : null,
    mode,
    isPaperSimulation,
  };
}

export function useUnifiedOrders(exchangeAccountId: string | undefined) {
  const { mode, isPaperSimulation } = useTradingMode(exchangeAccountId);
  
  const paperQuery = useQuery({
    queryKey: ['unified-orders', 'paper', exchangeAccountId],
    queryFn: () => fetchPaperOrders(exchangeAccountId!, { status: 'open' }),
    enabled: !!exchangeAccountId && isPaperSimulation,
    refetchInterval: 5000,
  });
  
  return {
    orders: isPaperSimulation ? paperQuery.data || [] : [],
    isLoading: isPaperSimulation ? paperQuery.isLoading : false,
    error: isPaperSimulation ? paperQuery.error : null,
    mode,
    isPaperSimulation,
  };
}
