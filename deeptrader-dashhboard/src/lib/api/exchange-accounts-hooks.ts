/**
 * Exchange Accounts React Query Hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as api from './exchange-accounts';

// =============================================================================
// Query Keys
// =============================================================================

export const exchangeAccountKeys = {
  all: ['exchange-accounts'] as const,
  list: (environment?: string) => [...exchangeAccountKeys.all, 'list', environment] as const,
  detail: (id: string) => [...exchangeAccountKeys.all, 'detail', id] as const,
  policy: (id: string) => [...exchangeAccountKeys.all, 'policy', id] as const,
  activeBot: (id: string) => [...exchangeAccountKeys.all, 'active-bot', id] as const,
  bots: (id: string) => [...exchangeAccountKeys.all, 'bots', id] as const,
  runningBots: (id: string) => [...exchangeAccountKeys.all, 'running-bots', id] as const,
  budgetUtilization: (id: string) => [...exchangeAccountKeys.all, 'budget-utilization', id] as const,
};

export const symbolLockKeys = {
  all: ['symbol-locks'] as const,
  list: (params: { exchangeAccountId: string; environment?: string }) =>
    [...symbolLockKeys.all, 'list', params] as const,
  conflicts: (params: { exchangeAccountId: string; environment: string; symbols: string[]; botId: string }) =>
    [...symbolLockKeys.all, 'conflicts', params] as const,
  summary: (params: { exchangeAccountId: string; environment?: string }) =>
    [...symbolLockKeys.all, 'summary', params] as const,
};

export const botBudgetKeys = {
  all: ['bot-budgets'] as const,
  detail: (botId: string) => [...botBudgetKeys.all, 'detail', botId] as const,
};

// =============================================================================
// Exchange Account Hooks
// =============================================================================

export function useExchangeAccounts(environment?: string) {
  return useQuery({
    queryKey: exchangeAccountKeys.list(environment),
    queryFn: () => api.fetchExchangeAccounts(environment),
  });
}

export function useExchangeAccount(id: string | null) {
  return useQuery({
    queryKey: exchangeAccountKeys.detail(id || ''),
    queryFn: () => api.fetchExchangeAccount(id!),
    enabled: !!id,
  });
}

export function useCreateExchangeAccount() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.createExchangeAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.all });
    },
  });
}

export function useUpdateExchangeAccount() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, params }: { id: string; params: api.UpdateExchangeAccountParams }) =>
      api.updateExchangeAccount(id, params),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.list() });
    },
  });
}

export function useDeleteExchangeAccount() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.deleteExchangeAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.all });
    },
  });
}

// =============================================================================
// Credentials & Verification Hooks
// =============================================================================

export function useStoreCredentials() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, params }: { id: string; params: api.StoreCredentialsParams }) =>
      api.storeCredentials(id, params),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(id) });
    },
  });
}

export function useVerifyCredentials() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.verifyCredentials,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.list() });
    },
  });
}

export function useRefreshBalance() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.refreshBalance,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.list() });
    },
  });
}

export function useUpdatePaperCapital() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ id, paperCapital }: { id: string; paperCapital: number }) =>
      api.updatePaperCapital(id, paperCapital),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.list() });
    },
  });
}

// =============================================================================
// Exchange Policy Hooks
// =============================================================================

export function useExchangePolicy(accountId: string | null) {
  return useQuery({
    queryKey: exchangeAccountKeys.policy(accountId || ''),
    queryFn: () => api.fetchExchangePolicy(accountId!),
    enabled: !!accountId,
  });
}

export function useUpdateExchangePolicy() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ accountId, params }: { accountId: string; params: api.UpdatePolicyParams }) =>
      api.updateExchangePolicy(accountId, params),
    onSuccess: (_, { accountId }) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.policy(accountId) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(accountId) });
    },
  });
}

// =============================================================================
// Active Bot Hooks (SOLO mode)
// =============================================================================

export function useActiveBot(accountId: string | null) {
  return useQuery({
    queryKey: exchangeAccountKeys.activeBot(accountId || ''),
    queryFn: () => api.fetchActiveBot(accountId!),
    enabled: !!accountId,
  });
}

export function useSwitchActiveBot() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ accountId, botId }: { accountId: string; botId: string }) =>
      api.switchActiveBot(accountId, botId),
    onSuccess: (_, { accountId }) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.activeBot(accountId) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(accountId) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.runningBots(accountId) });
    },
  });
}

// =============================================================================
// Account Bots Hooks
// =============================================================================

export function useAccountBots(accountId: string | null, includeInactive = false) {
  return useQuery({
    queryKey: exchangeAccountKeys.bots(accountId || ''),
    queryFn: () => api.fetchAccountBots(accountId!, includeInactive),
    enabled: !!accountId,
  });
}

export function useRunningBots(accountId: string | null) {
  return useQuery({
    queryKey: exchangeAccountKeys.runningBots(accountId || ''),
    queryFn: () => api.fetchRunningBots(accountId!),
    enabled: !!accountId,
    refetchInterval: 5000, // Refresh every 5 seconds
  });
}

// =============================================================================
// Kill Switch Hooks
// =============================================================================

export function useActivateKillSwitch() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ accountId, reason }: { accountId: string; reason?: string }) =>
      api.activateKillSwitch(accountId, reason),
    onSuccess: (_, { accountId }) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.policy(accountId) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(accountId) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.runningBots(accountId) });
    },
  });
}

export function useDeactivateKillSwitch() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.deactivateKillSwitch,
    onSuccess: (_, accountId) => {
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.policy(accountId) });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.detail(accountId) });
    },
  });
}

// =============================================================================
// Budget Utilization Hooks
// =============================================================================

export function useBudgetUtilization(accountId: string | null) {
  return useQuery({
    queryKey: exchangeAccountKeys.budgetUtilization(accountId || ''),
    queryFn: () => api.fetchBudgetUtilization(accountId!),
    enabled: !!accountId,
  });
}

// =============================================================================
// Symbol Lock Hooks
// =============================================================================

export function useSymbolLocks(params: {
  exchangeAccountId: string;
  environment?: string;
  symbol?: string;
  botId?: string;
} | null) {
  return useQuery({
    queryKey: symbolLockKeys.list(params || { exchangeAccountId: '' }),
    queryFn: () => api.fetchSymbolLocks(params!),
    enabled: !!params?.exchangeAccountId,
  });
}

export function useSymbolLockConflicts(params: {
  exchangeAccountId: string;
  environment: string;
  symbols: string[];
  botId: string;
} | null) {
  return useQuery({
    queryKey: symbolLockKeys.conflicts(params || { exchangeAccountId: '', environment: '', symbols: [], botId: '' }),
    queryFn: () => api.fetchSymbolLockConflicts(params!),
    enabled: !!params?.exchangeAccountId && !!params?.symbols?.length,
  });
}

export function useSymbolLockSummary(params: {
  exchangeAccountId: string;
  environment?: string;
} | null) {
  return useQuery({
    queryKey: symbolLockKeys.summary(params || { exchangeAccountId: '' }),
    queryFn: () => api.fetchSymbolLockSummary(params!),
    enabled: !!params?.exchangeAccountId,
  });
}

export function useAcquireSymbolLocks() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.acquireSymbolLocks,
    onSuccess: (_, params) => {
      queryClient.invalidateQueries({ queryKey: symbolLockKeys.all });
    },
  });
}

export function useReleaseSymbolLocks() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.releaseSymbolLocks,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: symbolLockKeys.all });
    },
  });
}

// =============================================================================
// Bot Lifecycle Hooks
// =============================================================================

export function useStartBot() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.startBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bot-instances'] });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.all });
      queryClient.invalidateQueries({ queryKey: symbolLockKeys.all });
    },
  });
}

export function useStopBot() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ botId, reason }: { botId: string; reason?: string }) =>
      api.stopBot(botId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bot-instances'] });
      queryClient.invalidateQueries({ queryKey: exchangeAccountKeys.all });
      queryClient.invalidateQueries({ queryKey: symbolLockKeys.all });
    },
  });
}

export function usePauseBot() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.pauseBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bot-instances'] });
    },
  });
}

export function useResumeBot() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.resumeBot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bot-instances'] });
    },
  });
}

// =============================================================================
// Bot Budget Hooks
// =============================================================================

export function useBotBudget(botId: string | null) {
  return useQuery({
    queryKey: botBudgetKeys.detail(botId || ''),
    queryFn: () => api.fetchBotBudget(botId!),
    enabled: !!botId,
  });
}

export function useUpdateBotBudget() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ({ botId, budget }: { botId: string; budget: Partial<api.BotBudget> }) =>
      api.updateBotBudget(botId, budget),
    onSuccess: (_, { botId }) => {
      queryClient.invalidateQueries({ queryKey: botBudgetKeys.detail(botId) });
    },
  });
}

export function useDeleteBotBudget() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: api.deleteBotBudget,
    onSuccess: (_, botId) => {
      queryClient.invalidateQueries({ queryKey: botBudgetKeys.detail(botId) });
    },
  });
}







