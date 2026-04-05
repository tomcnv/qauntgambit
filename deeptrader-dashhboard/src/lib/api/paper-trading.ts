/**
 * Paper Trading API Client
 * 
 * Functions for interacting with paper trading data (simulated orders, positions, balances).
 */

import { api } from './client';

// =============================================================================
// Types
// =============================================================================

export interface PaperPosition {
  id: string;
  user_id: string;
  bot_instance_id?: string;
  exchange_account_id: string;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  current_price?: number;
  leverage: number;
  margin_used: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss?: number;
  take_profit?: number;
  status: 'open' | 'closed' | 'liquidated';
  opened_at: string;
  closed_at?: string;
  close_reason?: string;
  realized_pnl?: number;
  fees_paid: number;
}

export interface PaperOrder {
  id: string;
  user_id: string;
  bot_instance_id?: string;
  exchange_account_id: string;
  symbol: string;
  side: 'buy' | 'sell';
  order_type: string;
  quantity: number;
  price?: number;
  stop_price?: number;
  status: 'pending' | 'open' | 'filled' | 'partial' | 'cancelled' | 'rejected';
  filled_quantity: number;
  avg_fill_price?: number;
  time_in_force: string;
  reduce_only: boolean;
  simulated_at: string;
  filled_at?: string;
  cancelled_at?: string;
  reject_reason?: string;
}

export interface PaperTrade {
  id: string;
  user_id: string;
  bot_instance_id?: string;
  exchange_account_id: string;
  paper_order_id?: string;
  paper_position_id?: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  fee: number;
  fee_currency: string;
  realized_pnl: number;
  executed_at: string;
}

export interface PaperBalance {
  id: string;
  exchange_account_id: string;
  currency: string;
  balance: number;
  available_balance: number;
  initial_balance: number;
  total_realized_pnl: number;
  total_fees_paid: number;
  unrealized_pnl: number;
  equity: number;
  created_at: string;
  updated_at: string;
}

export interface PaperTradingSummary {
  // Balance
  initial_balance: number;
  current_balance: number;
  available_balance: number;
  equity: number;
  
  // PnL
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  return_pct: number;
  
  // Positions
  open_positions: number;
  total_margin_used: number;
  
  // Trade statistics
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_fees: number;
  
  // Closed positions
  total_closed_positions: number;
  avg_pnl_per_position: number;
}

// =============================================================================
// Paper Trading API
// =============================================================================

export async function fetchPaperPositions(
  exchangeAccountId: string,
  status: 'open' | 'closed' | 'all' = 'open'
): Promise<PaperPosition[]> {
  const response = await api.get<{ positions: PaperPosition[] }>(
    `/paper-trading/positions/${exchangeAccountId}`,
    { params: { status } }
  );
  return response.data.positions;
}

export async function fetchPaperPosition(
  exchangeAccountId: string,
  symbol: string
): Promise<PaperPosition | null> {
  const response = await api.get<{ position: PaperPosition | null }>(
    `/paper-trading/positions/${exchangeAccountId}/${symbol}`
  );
  return response.data.position;
}

export async function fetchPaperOrders(
  exchangeAccountId: string,
  params?: { status?: string; limit?: number }
): Promise<PaperOrder[]> {
  const response = await api.get<{ orders: PaperOrder[] }>(
    `/paper-trading/orders/${exchangeAccountId}`,
    { params }
  );
  return response.data.orders;
}

export async function fetchPaperTrades(
  exchangeAccountId: string,
  params?: { limit?: number; offset?: number }
): Promise<{ trades: PaperTrade[]; total: number }> {
  const response = await api.get<{ trades: PaperTrade[]; total: number }>(
    `/paper-trading/trades/${exchangeAccountId}`,
    { params }
  );
  return response.data;
}

export async function fetchPaperBalance(
  exchangeAccountId: string
): Promise<PaperBalance> {
  const response = await api.get<{ balance: PaperBalance }>(
    `/paper-trading/balance/${exchangeAccountId}`
  );
  return response.data.balance;
}

export async function resetPaperAccount(
  exchangeAccountId: string,
  initialBalance: number = 10000
): Promise<{ success: boolean; balance: PaperBalance }> {
  const response = await api.post(
    `/paper-trading/reset/${exchangeAccountId}`,
    { initialBalance }
  );
  return response.data;
}

export async function fetchPaperTradingSummary(
  exchangeAccountId: string
): Promise<PaperTradingSummary> {
  const response = await api.get<{ summary: PaperTradingSummary }>(
    `/paper-trading/summary/${exchangeAccountId}`
  );
  return response.data.summary;
}
