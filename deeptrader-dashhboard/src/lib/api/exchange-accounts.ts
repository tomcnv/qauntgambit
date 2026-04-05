/**
 * Exchange Accounts API Client
 * 
 * Functions for interacting with exchange accounts, policies, and related endpoints.
 */

import { api } from './client';

const toPercentDisplay = (value?: number) => {
  if (value === undefined || value === null) return value;
  return value > 1 ? value : value * 100;
};

const toDecimalValue = (value?: number) => {
  if (value === undefined || value === null) return value;
  return value > 1 ? value / 100 : value;
};

const normalizeExchangePolicyForUI = (policy: ExchangePolicy): ExchangePolicy => ({
  ...policy,
  max_daily_loss_pct: toPercentDisplay(policy.max_daily_loss_pct) ?? policy.max_daily_loss_pct,
  max_margin_used_pct: toPercentDisplay(policy.max_margin_used_pct) ?? policy.max_margin_used_pct,
  max_gross_exposure_pct: toPercentDisplay(policy.max_gross_exposure_pct) ?? policy.max_gross_exposure_pct,
  max_net_exposure_pct: toPercentDisplay(policy.max_net_exposure_pct) ?? policy.max_net_exposure_pct,
  circuit_breaker_loss_pct: toPercentDisplay(policy.circuit_breaker_loss_pct) ?? policy.circuit_breaker_loss_pct,
});

const normalizeExchangePolicyForApi = (params: UpdatePolicyParams): UpdatePolicyParams => ({
  ...params,
  maxDailyLossPct: toDecimalValue(params.maxDailyLossPct),
  maxMarginUsedPct: toDecimalValue(params.maxMarginUsedPct),
  maxGrossExposurePct: toDecimalValue(params.maxGrossExposurePct),
  maxNetExposurePct: toDecimalValue(params.maxNetExposurePct),
  circuitBreakerLossPct: toDecimalValue(params.circuitBreakerLossPct),
});

const normalizeBotBudgetForUI = (budget: BotBudget): BotBudget => ({
  ...budget,
  max_daily_loss_pct: toPercentDisplay(budget.max_daily_loss_pct),
  max_margin_used_pct: toPercentDisplay(budget.max_margin_used_pct),
  max_exposure_pct: toPercentDisplay(budget.max_exposure_pct),
});

const normalizeBotBudgetForApi = (budget: Partial<BotBudget>): Partial<BotBudget> => ({
  ...budget,
  max_daily_loss_pct: toDecimalValue(budget.max_daily_loss_pct),
  max_margin_used_pct: toDecimalValue(budget.max_margin_used_pct),
  max_exposure_pct: toDecimalValue(budget.max_exposure_pct),
});

// =============================================================================
// Types
// =============================================================================

export interface ExchangeAccount {
  id: string;
  tenant_id: string;
  venue: string;
  label: string;
  environment: 'dev' | 'paper' | 'live';
  secret_id?: string;
  is_demo: boolean;
  status: 'pending' | 'verified' | 'error' | 'disabled';
  last_verified_at?: string;
  verification_error?: string;
  permissions?: Record<string, boolean>;
  exchange_balance?: number;
  available_balance?: number;
  margin_used?: number;
  unrealized_pnl?: number;
  balance_currency: string;
  balance_updated_at?: string;
  active_bot_id?: string;
  active_bot_name?: string;
  active_bot_state?: string;
  bot_count?: number;
  running_bot_count?: number;
  kill_switch_enabled?: boolean;
  live_trading_enabled?: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ExchangePolicy {
  id: string;
  exchange_account_id: string;
  max_daily_loss_pct: number;
  max_daily_loss_usd?: number;
  daily_loss_used_usd: number;
  daily_loss_reset_at: string;
  max_margin_used_pct: number;
  max_gross_exposure_pct: number;
  max_net_exposure_pct: number;
  max_leverage: number;
  max_open_positions: number;
  kill_switch_enabled: boolean;
  kill_switch_triggered_at?: string;
  kill_switch_triggered_by?: string;
  kill_switch_reason?: string;
  circuit_breaker_enabled: boolean;
  circuit_breaker_loss_pct: number;
  circuit_breaker_cooldown_min: number;
  circuit_breaker_triggered_at?: string;
  live_trading_enabled: boolean;
  policy_version: number;
  created_at: string;
  updated_at: string;
}

export interface BotBudget {
  id: string;
  bot_instance_id: string;
  exchange_account_id: string;
  max_daily_loss_pct?: number;
  max_daily_loss_usd?: number;
  max_margin_used_pct?: number;
  max_exposure_pct?: number;
  max_open_positions?: number;
  max_leverage?: number;
  max_order_rate_per_min?: number;
  daily_loss_used_usd: number;
  margin_used_usd: number;
  current_positions: number;
  daily_reset_at: string;
  budget_version: number;
  bot_name?: string;
}

export interface SymbolLock {
  id: string;
  exchange_account_id: string;
  environment: string;
  symbol: string;
  owner_bot_id: string;
  owner_bot_name?: string;
  acquired_at: string;
  expires_at?: string;
  lease_heartbeat_at: string;
  conflict_count: number;
}

export interface CreateExchangeAccountParams {
  venue: string;
  label: string;
  environment?: 'dev' | 'paper' | 'live';
  isDemo?: boolean;
  paperCapital?: number;
  metadata?: Record<string, unknown>;
}

export interface UpdateExchangeAccountParams {
  label?: string;
  isDemo?: boolean;
  metadata?: Record<string, unknown>;
}

export interface UpdatePolicyParams {
  maxDailyLossPct?: number;
  maxDailyLossUsd?: number;
  maxMarginUsedPct?: number;
  maxGrossExposurePct?: number;
  maxNetExposurePct?: number;
  maxLeverage?: number;
  maxOpenPositions?: number;
  circuitBreakerEnabled?: boolean;
  circuitBreakerLossPct?: number;
  circuitBreakerCooldownMin?: number;
  liveTradingEnabled?: boolean;
}

export interface StoreCredentialsParams {
  apiKey: string;
  secretKey: string;
  passphrase?: string;
}

// =============================================================================
// Exchange Accounts API
// =============================================================================

export async function fetchExchangeAccounts(environment?: string): Promise<ExchangeAccount[]> {
  const params = environment ? { environment } : {};
  const response = await api.get<{ accounts: ExchangeAccount[] }>('/exchange-accounts', { params });
  return response.data.accounts;
}

export async function fetchExchangeAccount(id: string): Promise<{
  account: ExchangeAccount;
  policy: ExchangePolicy;
  bots: Array<Record<string, unknown>>;
  budgets: BotBudget[];
}> {
  const response = await api.get(`/exchange-accounts/${id}`);
  return response.data;
}

export async function createExchangeAccount(params: CreateExchangeAccountParams): Promise<ExchangeAccount> {
  const response = await api.post<{ account: ExchangeAccount }>('/exchange-accounts', params);
  return response.data.account;
}

export async function updateExchangeAccount(id: string, params: UpdateExchangeAccountParams): Promise<ExchangeAccount> {
  const response = await api.put<{ account: ExchangeAccount }>(`/exchange-accounts/${id}`, params);
  return response.data.account;
}

export interface LinkedBot {
  id: string;
  name: string;
  status: string;
}

export interface CanDeleteResponse {
  canDelete: boolean;
  reason?: 'RUNNING_BOTS' | 'LINKED_BOTS';
  message?: string;
  linkedBots?: LinkedBot[];
}

export async function checkCanDelete(id: string): Promise<CanDeleteResponse> {
  const response = await api.get<CanDeleteResponse>(`/exchange-accounts/${id}/can-delete`);
  return response.data;
}

export async function deleteExchangeAccount(id: string): Promise<void> {
  await api.delete(`/exchange-accounts/${id}`);
}

// =============================================================================
// Credentials & Verification
// =============================================================================

export async function storeCredentials(id: string, params: StoreCredentialsParams): Promise<void> {
  await api.post(`/exchange-accounts/${id}/credentials`, params);
}

export async function verifyCredentials(id: string): Promise<ExchangeAccount> {
  const response = await api.post<{ account: ExchangeAccount }>(`/exchange-accounts/${id}/verify`);
  return response.data.account;
}

export async function refreshBalance(id: string): Promise<ExchangeAccount> {
  const response = await api.post<{ account: ExchangeAccount }>(`/exchange-accounts/${id}/refresh-balance`);
  return response.data.account;
}

export async function updatePaperCapital(id: string, paperCapital: number): Promise<ExchangeAccount> {
  const response = await api.put<{ account: ExchangeAccount }>(`/exchange-accounts/${id}/paper-capital`, { paperCapital });
  return response.data.account;
}

// =============================================================================
// Exchange Policy
// =============================================================================

export async function fetchExchangePolicy(accountId: string): Promise<ExchangePolicy> {
  const response = await api.get<{ policy: ExchangePolicy }>(`/exchange-accounts/${accountId}/policy`);
  return normalizeExchangePolicyForUI(response.data.policy);
}

export async function updateExchangePolicy(accountId: string, params: UpdatePolicyParams): Promise<ExchangePolicy> {
  const response = await api.put<{ policy: ExchangePolicy }>(
    `/exchange-accounts/${accountId}/policy`,
    normalizeExchangePolicyForApi(params)
  );
  return normalizeExchangePolicyForUI(response.data.policy);
}

// =============================================================================
// Active Bot (SOLO mode)
// =============================================================================

export async function fetchActiveBot(accountId: string): Promise<Record<string, unknown> | null> {
  const response = await api.get<{ bot: Record<string, unknown> | null }>(`/exchange-accounts/${accountId}/active-bot`);
  return response.data.bot;
}

export async function switchActiveBot(accountId: string, botId: string): Promise<{ success: boolean }> {
  const response = await api.post(`/exchange-accounts/${accountId}/active-bot`, { botId });
  return response.data;
}

// =============================================================================
// Bots
// =============================================================================

export async function fetchAccountBots(accountId: string, includeInactive = false): Promise<Array<Record<string, unknown>>> {
  const response = await api.get<{ bots: Array<Record<string, unknown>> }>(
    `/exchange-accounts/${accountId}/bots`,
    { params: { includeInactive } }
  );
  return response.data.bots;
}

export async function fetchRunningBots(accountId: string): Promise<Array<Record<string, unknown>>> {
  const response = await api.get<{ bots: Array<Record<string, unknown>> }>(`/exchange-accounts/${accountId}/running-bots`);
  return response.data.bots;
}

// =============================================================================
// Kill Switch
// =============================================================================

export async function activateKillSwitch(accountId: string, reason?: string): Promise<{
  success: boolean;
  policy: ExchangePolicy;
  botsStopped: Array<{ botId: string; success: boolean }>;
}> {
  const response = await api.post(`/exchange-accounts/${accountId}/kill-switch`, { reason });
  return {
    ...response.data,
    policy: normalizeExchangePolicyForUI(response.data.policy),
  };
}

export async function deactivateKillSwitch(accountId: string): Promise<{ success: boolean; policy: ExchangePolicy }> {
  const response = await api.delete(`/exchange-accounts/${accountId}/kill-switch`);
  return {
    ...response.data,
    policy: normalizeExchangePolicyForUI(response.data.policy),
  };
}

// =============================================================================
// Budget Utilization
// =============================================================================

export async function fetchBudgetUtilization(accountId: string): Promise<BotBudget[]> {
  const response = await api.get<{ utilization: BotBudget[] }>(`/exchange-accounts/${accountId}/budget-utilization`);
  return response.data.utilization.map((budget) => normalizeBotBudgetForUI(budget));
}

// =============================================================================
// Symbol Locks
// =============================================================================

export async function fetchSymbolLocks(params: {
  exchangeAccountId: string;
  environment?: string;
  symbol?: string;
  botId?: string;
}): Promise<SymbolLock[]> {
  const response = await api.get<{ locks: SymbolLock[] }>('/symbol-locks', { params });
  return response.data.locks;
}

export async function fetchSymbolLockConflicts(params: {
  exchangeAccountId: string;
  environment: string;
  symbols: string[];
  botId: string;
}): Promise<{
  conflicts: Array<{ symbol: string; owner_bot_id: string; owner_bot_name?: string }>;
  hasConflicts: boolean;
}> {
  const response = await api.get('/symbol-locks/conflicts', {
    params: {
      ...params,
      symbols: params.symbols.join(','),
    },
  });
  return response.data;
}

export async function acquireSymbolLocks(params: {
  exchangeAccountId: string;
  environment: string;
  symbols: string[];
  botId: string;
}): Promise<{
  acquired: string[];
  failed: Array<{ symbol: string; ownerBotId: string; ownerBotName?: string }>;
  allAcquired: boolean;
}> {
  const response = await api.post('/symbol-locks/acquire', params);
  return response.data;
}

export async function releaseSymbolLocks(params: {
  botId: string;
  symbols?: string[];
}): Promise<{ success: boolean; released: string[] }> {
  const response = await api.post('/symbol-locks/release', params);
  return response.data;
}

export async function fetchSymbolLockSummary(params: {
  exchangeAccountId: string;
  environment?: string;
}): Promise<Array<{
  owner_bot_id: string;
  bot_name: string;
  symbol_count: number;
  symbols: string[];
}>> {
  const response = await api.get<{ summary: Array<unknown> }>('/symbol-locks/summary', { params });
  return response.data.summary as Array<{
    owner_bot_id: string;
    bot_name: string;
    symbol_count: number;
    symbols: string[];
  }>;
}

// =============================================================================
// Bot Lifecycle
// =============================================================================

export async function startBot(botId: string): Promise<{ success: boolean; bot_id: string; locks_acquired?: string[] }> {
  const response = await api.post(`/bot-instances/${botId}/start`);
  return response.data;
}

export async function stopBot(botId: string, reason?: string): Promise<{ success: boolean; bot_id: string }> {
  const response = await api.post(`/bot-instances/${botId}/stop`, { reason });
  return response.data;
}

export async function pauseBot(botId: string): Promise<{ success: boolean; bot_id: string }> {
  const response = await api.post(`/bot-instances/${botId}/pause`);
  return response.data;
}

export async function resumeBot(botId: string): Promise<{ success: boolean; bot_id: string }> {
  const response = await api.post(`/bot-instances/${botId}/resume`);
  return response.data;
}

// =============================================================================
// Bot Budget
// =============================================================================

export async function fetchBotBudget(botId: string): Promise<BotBudget | null> {
  const response = await api.get<{ budget: BotBudget | null }>(`/bot-instances/${botId}/budget`);
  return response.data.budget ? normalizeBotBudgetForUI(response.data.budget) : null;
}

export async function updateBotBudget(botId: string, budget: Partial<BotBudget>): Promise<BotBudget> {
  const response = await api.put<{ budget: BotBudget }>(
    `/bot-instances/${botId}/budget`,
    normalizeBotBudgetForApi(budget)
  );
  return normalizeBotBudgetForUI(response.data.budget);
}

export async function deleteBotBudget(botId: string): Promise<void> {
  await api.delete(`/bot-instances/${botId}/budget`);
}
