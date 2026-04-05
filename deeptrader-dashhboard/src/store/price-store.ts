import { create } from 'zustand';

export type PriceUpdate = {
  symbol: string;
  price: number;
  change24h: number;
  changePct: number;
  high24h: number;
  low24h: number;
  volume: number;
  timestamp: number;
};

type PriceState = {
  prices: Map<string, PriceUpdate>;
  lastUpdate: number;
  
  // Actions
  updatePrice: (update: PriceUpdate) => void;
  getPrice: (symbol: string) => PriceUpdate | undefined;
  getPriceValue: (symbol: string) => number | undefined;
};

// Normalize symbol to match stored format (e.g., "BTC-USDT-SWAP" -> "BTCUSDT")
function normalizeSymbol(symbol: string): string {
  let normalized = symbol.trim().toUpperCase();
  if (normalized.includes(':')) {
    normalized = normalized.split(':')[0];
  }
  normalized = normalized
    .replace(/-SWAP$/i, '')
    .replace(/-PERP$/i, '')
    .replace(/-PERPETUAL$/i, '')
    .replace(/SWAP/i, '')
    .replace(/PERP/i, '')
    .replace(/PERPETUAL/i, '');
  return normalized.replace(/[^A-Z0-9]/g, '');
}

export const usePriceStore = create<PriceState>((set, get) => ({
  prices: new Map(),
  lastUpdate: 0,
  
  updatePrice: (update: PriceUpdate) => {
    set((state) => {
      const newPrices = new Map(state.prices);
      newPrices.set(update.symbol, update);
      return { prices: newPrices, lastUpdate: Date.now() };
    });
  },
  
  getPrice: (symbol: string) => {
    const normalized = normalizeSymbol(symbol);
    return get().prices.get(normalized);
  },
  
  getPriceValue: (symbol: string) => {
    const normalized = normalizeSymbol(symbol);
    return get().prices.get(normalized)?.price;
  },
}));

// Helper hook to get a specific symbol's price with auto-subscription
export function useCurrentPrice(symbol: string | null | undefined): number | undefined {
  const getPriceValue = usePriceStore((s) => s.getPriceValue);
  const lastUpdate = usePriceStore((s) => s.lastUpdate); // Subscribe to updates
  
  if (!symbol) return undefined;
  return getPriceValue(symbol);
}

// Helper hook to get all prices
export function useAllPrices(): Map<string, PriceUpdate> {
  return usePriceStore((s) => s.prices);
}


