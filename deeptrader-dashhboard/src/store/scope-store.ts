/**
 * Scope Store
 * 
 * Manages the current viewing scope: Fleet | Exchange Account | Bot
 * This determines what data is shown in tables and charts.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ScopeLevel = 'fleet' | 'exchange' | 'bot';
export type Environment = 'all' | 'live' | 'paper' | 'dev';
export type TimeWindow = '15m' | '1h' | '4h' | '24h' | '7d';

export interface ScopeState {
  // Current scope level
  level: ScopeLevel;
  hasHydrated: boolean;
  
  // Selected IDs (null when at higher scope)
  exchangeAccountId: string | null;
  exchangeAccountName: string | null;
  botId: string | null;
  botName: string | null;
  
  // Filters
  environment: Environment;
  timeWindow: TimeWindow;
  
  // Actions
  setFleetScope: () => void;
  setExchangeScope: (id: string, name?: string) => void;
  setBotScope: (exchangeId: string, exchangeName: string | null, botId: string, botName?: string) => void;
  setEnvironment: (env: Environment) => void;
  setTimeWindow: (window: TimeWindow) => void;
  setHasHydrated: (hydrated: boolean) => void;
  
  // Helpers
  getScopeLabel: () => string;
  getScopeParams: () => Record<string, string>;
}

export const useScopeStore = create<ScopeState>()(
  persist(
    (set, get) => ({
      // Initial state - fleet scope
      level: 'fleet',
      hasHydrated: false,
      exchangeAccountId: null,
      exchangeAccountName: null,
      botId: null,
      botName: null,
      environment: 'all',
      timeWindow: '1h',
      
      // Actions
      setFleetScope: () => set({
        level: 'fleet',
        exchangeAccountId: null,
        exchangeAccountName: null,
        botId: null,
        botName: null,
      }),
      
      setExchangeScope: (id, name) => set({
        level: 'exchange',
        exchangeAccountId: id,
        exchangeAccountName: name || null,
        botId: null,
        botName: null,
      }),
      
      setBotScope: (exchangeId, exchangeName, botId, botName) => set({
        level: 'bot',
        exchangeAccountId: exchangeId,
        exchangeAccountName: exchangeName,
        botId,
        botName: botName || null,
      }),
      
      setEnvironment: (env) => set({ environment: env }),
      
      setTimeWindow: (window) => set({ timeWindow: window }),
      setHasHydrated: (hydrated) => set({ hasHydrated: hydrated }),
      
      // Helpers
      getScopeLabel: () => {
        const state = get();
        switch (state.level) {
          case 'fleet':
            return 'Fleet';
          case 'exchange':
            return state.exchangeAccountName || 'Exchange Account';
          case 'bot':
            return state.botName || 'Bot';
          default:
            return 'Fleet';
        }
      },
      
      getScopeParams: () => {
        const state = get();
        const params: Record<string, string> = {};
        
        if (state.exchangeAccountId) {
          params.exchangeAccountId = state.exchangeAccountId;
        }
        if (state.botId) {
          params.botId = state.botId;
        }
        if (state.environment !== 'all') {
          params.environment = state.environment;
        }
        
        return params;
      },
    }),
    {
      name: 'quantgambit-scope',
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
      partialize: (state) => ({
        level: state.level,
        exchangeAccountId: state.exchangeAccountId,
        exchangeAccountName: state.exchangeAccountName,
        botId: state.botId,
        botName: state.botName,
        environment: state.environment,
        timeWindow: state.timeWindow,
      }),
    }
  )
);

// Selector hooks for specific parts of the state
export const useScopeLevel = () => useScopeStore((s) => s.level);
export const useScopeHydrated = () => useScopeStore((s) => s.hasHydrated);
export const useExchangeAccountId = () => useScopeStore((s) => s.exchangeAccountId);
export const useBotId = () => useScopeStore((s) => s.botId);
export const useEnvironmentFilter = () => useScopeStore((s) => s.environment);
export const useTimeWindow = () => useScopeStore((s) => s.timeWindow);

// Helper to check if we're at a specific scope
export const useIsFleetScope = () => useScopeStore((s) => s.level === 'fleet');
export const useIsExchangeScope = () => useScopeStore((s) => s.level === 'exchange');
export const useIsBotScope = () => useScopeStore((s) => s.level === 'bot');






