/**
 * Bot Management Types & Constants
 * Shared types across bot management components
 */

import type { BotEnvironment, BotInstance, BotExchangeConfig, TenantRiskPolicy, BotConfigState, MarketType } from "../../lib/api/types";

// Re-export for convenience
export type { BotEnvironment, BotInstance, BotExchangeConfig, TenantRiskPolicy, BotConfigState, MarketType };
export type BotKind = "standard" | "ai_spot_swing";

// ═══════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════

export const ENVIRONMENTS: { value: BotEnvironment | "all"; label: string; color: string; bgColor: string }[] = [
  { value: "all", label: "All", color: "text-primary-foreground", bgColor: "bg-primary" },
  { value: "dev", label: "Dev", color: "text-purple-100", bgColor: "bg-purple-600" },
  { value: "paper", label: "Paper", color: "text-cyan-100", bgColor: "bg-cyan-600" },
  { value: "live", label: "Live", color: "text-green-100", bgColor: "bg-green-600" },
];

export const STATUS_FILTERS = [
  { value: "all", label: "All Status" },
  { value: "running", label: "Running" },
  { value: "paused", label: "Paused" },
  { value: "ready", label: "Ready" },
  { value: "blocked", label: "Blocked" },
  { value: "error", label: "Error" },
];

export const ALLOCATOR_ROLES = [
  { value: "core", label: "Core", description: "Primary trading strategy" },
  { value: "satellite", label: "Satellite", description: "Secondary opportunistic" },
  { value: "hedge", label: "Hedge", description: "Risk reduction positions" },
  { value: "experimental", label: "Experimental", description: "Testing new strategies" },
];

export const TRADING_MODES = [
  { 
    value: "paper", 
    label: "Paper Trading", 
    description: "Simulated orders, no real money",
    icon: "📄",
    color: "text-cyan-400",
    bgColor: "bg-cyan-600",
  },
  { 
    value: "live", 
    label: "Live Trading", 
    description: "Real orders on exchange",
    icon: "💰",
    color: "text-green-400",
    bgColor: "bg-green-600",
  },
];

export const SYMBOL_OPTIONS = [
  { id: "BTC-USDT-SWAP", label: "BTC", hint: "Min notional ~$80", marketType: "perp" as const },
  { id: "ETH-USDT-SWAP", label: "ETH", hint: "Min notional ~$40", marketType: "perp" as const },
  { id: "SOL-USDT-SWAP", label: "SOL", hint: "Min notional ~$15", marketType: "perp" as const },
  { id: "DOGE-USDT-SWAP", label: "DOGE", hint: "Min notional ~$10", marketType: "perp" as const },
  { id: "XRP-USDT-SWAP", label: "XRP", hint: "Min notional ~$10", marketType: "perp" as const },
  { id: "AVAX-USDT-SWAP", label: "AVAX", hint: "Min notional ~$20", marketType: "perp" as const },
  { id: "LINK-USDT-SWAP", label: "LINK", hint: "Min notional ~$15", marketType: "perp" as const },
  { id: "MATIC-USDT-SWAP", label: "MATIC", hint: "Min notional ~$10", marketType: "perp" as const },
  // Spot symbols
  { id: "BTCUSDT", label: "BTC", hint: "Spot", marketType: "spot" as const },
  { id: "ETHUSDT", label: "ETH", hint: "Spot", marketType: "spot" as const },
  { id: "SOLUSDT", label: "SOL", hint: "Spot", marketType: "spot" as const },
  { id: "DOGEUSDT", label: "DOGE", hint: "Spot", marketType: "spot" as const },
  { id: "XRPUSDT", label: "XRP", hint: "Spot", marketType: "spot" as const },
  { id: "AVAXUSDT", label: "AVAX", hint: "Spot", marketType: "spot" as const },
  { id: "LINKUSDT", label: "LINK", hint: "Spot", marketType: "spot" as const },
];

export const QUICK_ADD_SYMBOLS_PERP = [
  "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP",
  "XRP-USDT-SWAP", "AVAX-USDT-SWAP", "LINK-USDT-SWAP", "MATIC-USDT-SWAP",
];

export const QUICK_ADD_SYMBOLS_SPOT = [
  "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "AVAXUSDT", "LINKUSDT",
];

export const QUICK_ADD_SYMBOLS = QUICK_ADD_SYMBOLS_PERP;

export const MARKET_TYPES = [
  {
    value: "perp" as const,
    label: "Scalp / Futures",
    description: "Leveraged perpetual futures with tight TP/SL targets",
    icon: "⚡",
    color: "text-amber-400",
    bgColor: "bg-amber-600",
  },
  {
    value: "spot" as const,
    label: "Spot Trading",
    description: "Buy and hold with intelligent entry timing and DCA",
    icon: "💎",
    color: "text-blue-400",
    bgColor: "bg-blue-600",
  },
];

export const BOT_TYPES = [
  {
    value: "standard" as const,
    label: "Standard Bot",
    description: "Existing rules/model-driven bot stack",
    icon: "Bot",
  },
  {
    value: "ai_spot_swing" as const,
    label: "AI Spot / Swing",
    description: "DeepSeek-assisted spot and swing bot with sentiment/context routing",
    icon: "Sparkles",
  },
];

// ═══════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════

export type WizardStep = "start" | "identity" | "exchange" | "capital" | "advanced" | "symbols" | "review";

export type ExchangeAccountOption = {
  id: string;
  venue: string;
  label: string;
  environment: string;
  status: string;
  is_demo?: boolean;
  exchange_balance?: number;
  available_balance?: number;
  balance_currency?: string;
  running_bot_count?: number;
  bot_count?: number;
};

export interface RiskFormState {
  positionSizePct: number;
  minPositionSizeUsd: number;
  maxPositionSizeUsd: number;
  maxPositions: number;
  maxPositionsPerStrategy: number;
  maxLeverage: number;
  leverageMode: "isolated" | "cross";
  maxDailyLossPct: number;
  maxTotalExposurePct: number;
  maxExposurePerSymbolPct: number; // Max exposure per single symbol (should be >= positionSizePct)
  maxPositionsPerSymbol: number;
  maxDailyLossPerSymbolPct: number;
  maxDrawdownPct: number;
}

export type ThrottleMode = "scalping" | "swing" | "conservative";

export interface ExecutionFormState {
  defaultOrderType: "market" | "limit";
  stopLossPct: number;
  takeProfitPct: number;
  trailingStopEnabled: boolean;
  trailingStopPct: number;
  maxHoldTimeHours: number;
  minTradeIntervalSec: number;
  executionTimeoutSec: number;
  enableVolatilityFilter: boolean;
  throttleMode: ThrottleMode;
  orderIntentMaxAgeSec: number;
}

export type TradingMode = "paper" | "live";

export interface BotFormState {
  // Identity
  name: string;
  description: string;
  allocatorRole: string;
  templateId: string;
  marketType: MarketType;
  
  // Exchange
  credentialId: string;
  environment: BotEnvironment;
  
  // Trading Mode (bot-level paper trading)
  tradingMode: TradingMode;
  
  // Capital
  tradingCapital: number | "";
  
  // Risk
  risk: RiskFormState;
  
  // Execution
  execution: ExecutionFormState;
  
  // Symbols
  enabledSymbols: string[];
  symbolOverrides: Record<string, { minNotionalUsd?: number; maxLeverage?: number }>;
  
  // Meta
  notes: string;
  activate: boolean;
}

export const DEFAULT_RISK_STATE: RiskFormState = {
  positionSizePct: 10,
  minPositionSizeUsd: 10,
  maxPositionSizeUsd: 0,
  maxPositions: 4,
  maxPositionsPerStrategy: 0,
  maxLeverage: 1,
  leverageMode: "isolated",
  maxDailyLossPct: 5,
  maxTotalExposurePct: 80,
  maxExposurePerSymbolPct: 25, // Default higher than positionSizePct to allow trades
  maxPositionsPerSymbol: 1,
  maxDailyLossPerSymbolPct: 2.5,
  maxDrawdownPct: 10,
};

export const DEFAULT_EXECUTION_STATE: ExecutionFormState = {
  defaultOrderType: "market",
  stopLossPct: 2,
  takeProfitPct: 5,
  trailingStopEnabled: false,
  trailingStopPct: 1,
  maxHoldTimeHours: 24,
  minTradeIntervalSec: 1,
  executionTimeoutSec: 5,
  enableVolatilityFilter: true,
  throttleMode: "swing",
  orderIntentMaxAgeSec: 0,
};

// Spot-specific defaults — wider targets, no leverage, limit orders
export const SPOT_RISK_DEFAULTS: RiskFormState = {
  positionSizePct: 15,
  minPositionSizeUsd: 20,
  maxPositionSizeUsd: 0,
  maxPositions: 6,
  maxPositionsPerStrategy: 0,
  maxLeverage: 1,
  leverageMode: "isolated",
  maxDailyLossPct: 8,
  maxTotalExposurePct: 90,
  maxExposurePerSymbolPct: 30,
  maxPositionsPerSymbol: 3,
  maxDailyLossPerSymbolPct: 4,
  maxDrawdownPct: 15,
};

export const SPOT_EXECUTION_DEFAULTS: ExecutionFormState = {
  defaultOrderType: "limit",
  stopLossPct: 5,
  takeProfitPct: 15,
  trailingStopEnabled: true,
  trailingStopPct: 3,
  maxHoldTimeHours: 168,
  minTradeIntervalSec: 60,
  executionTimeoutSec: 30,
  enableVolatilityFilter: true,
  throttleMode: "conservative",
  orderIntentMaxAgeSec: 0,
};

export const THROTTLE_MODES = [
  { 
    value: "scalping" as const, 
    label: "Scalping", 
    description: "High frequency (15s intervals, 50 entries/hour)",
    icon: "⚡",
  },
  { 
    value: "swing" as const, 
    label: "Swing", 
    description: "Moderate frequency (60s intervals, 10 entries/hour)",
    icon: "📊",
  },
  { 
    value: "conservative" as const, 
    label: "Conservative", 
    description: "Low frequency (120s intervals, 6 entries/hour)",
    icon: "🛡️",
  },
];

// ═══════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════

export function getStateColor(state: BotConfigState) {
  switch (state) {
    case "running": return "bg-green-500";
    case "paused": return "bg-yellow-500";
    case "blocked": return "bg-red-600";
    case "error": return "bg-red-500";
    case "decommissioned": return "bg-gray-600";
    case "created":
    case "ready":
    default: return "bg-gray-400";
  }
}

export function getStateBadge(state: BotConfigState) {
  switch (state) {
    case "running": return "bg-green-500/20 text-green-400 border-green-500/30";
    case "paused": return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
    case "blocked": return "bg-red-600/20 text-red-400 border-red-600/50";
    case "error": return "bg-red-500/20 text-red-400 border-red-500/30";
    case "decommissioned": return "bg-gray-600/20 text-gray-400 border-gray-600/30";
    case "created":
    case "ready":
    default: return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
}

export function getEnvironmentBadge(env: BotEnvironment) {
  switch (env) {
    case "live": return "bg-green-500/20 text-green-400 border-green-500/30";
    case "paper": return "bg-cyan-500/20 text-cyan-400 border-cyan-500/30";
    case "dev": return "bg-purple-500/20 text-purple-400 border-purple-500/30";
    default: return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
}

export function getTradingModeBadge(mode: TradingMode) {
  switch (mode) {
    case "live": return "bg-green-500/20 text-green-400 border-green-500/30";
    case "paper": return "bg-cyan-500/20 text-cyan-400 border-cyan-500/30";
    default: return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
}

export function getTradingModeLabel(mode: TradingMode) {
  const modeInfo = TRADING_MODES.find(m => m.value === mode);
  return modeInfo ? `${modeInfo.icon} ${modeInfo.label}` : mode;
}

// ═══════════════════════════════════════════════════════════════
// COMBINED TRADING MODE (isDemo + environment)
// ═══════════════════════════════════════════════════════════════
// These combine the API type (prod/demo) with trading mode (live/paper)
// 🔥 Live Trading = prod API + live trading (real money, real orders)
// 📝 Paper Mode = prod API + paper trading (simulated orders)
// 🧪 Demo Trading = demo API + live trading (demo account)
// 🧪 Demo Paper = demo API + paper trading (rare, testing)

export function getCombinedTradingModeLabel(isDemo: boolean | undefined, environment: string): string {
  if (isDemo && environment === 'live') return '🧪 Demo Trading';
  if (isDemo && environment === 'paper') return '🧪 Demo Paper';
  if (!isDemo && environment === 'live') return '🔥 Live Trading';
  if (!isDemo && environment === 'paper') return '📝 Paper Mode';
  return '🔧 Dev Mode';
}

export function getCombinedTradingModeBadgeClass(isDemo: boolean | undefined, environment: string): string {
  if (isDemo && environment === 'live') return 'text-[10px] border-amber-500/50 text-amber-400 bg-amber-500/20';
  if (isDemo && environment === 'paper') return 'text-[10px] border-amber-500/30 text-amber-300 bg-amber-500/10';
  if (!isDemo && environment === 'live') return 'text-[10px] border-red-500/50 text-red-400 bg-red-500/20';
  if (!isDemo && environment === 'paper') return 'text-[10px] border-blue-500/50 text-blue-400 bg-blue-500/20';
  return 'text-[10px] border-purple-500/50 text-purple-400 bg-purple-500/20';
}

export function getRoleBadge(role: string) {
  switch (role) {
    case "core": return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    case "satellite": return "bg-indigo-500/20 text-indigo-400 border-indigo-500/30";
    case "hedge": return "bg-amber-500/20 text-amber-400 border-amber-500/30";
    case "experimental": return "bg-pink-500/20 text-pink-400 border-pink-500/30";
    default: return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
}

export function getMarketTypeBadge(marketType: string) {
  switch (marketType) {
    case "spot": return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    case "perp": return "bg-amber-500/20 text-amber-400 border-amber-500/30";
    default: return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
}

export function getMarketTypeLabel(marketType: string) {
  return marketType === "spot" ? "💎 Spot" : "⚡ Futures";
}

export function getSymbolsForMarketType(marketType: MarketType) {
  return SYMBOL_OPTIONS.filter((s) => s.marketType === marketType);
}

export function getQuickAddSymbols(marketType: MarketType) {
  return marketType === "spot" ? QUICK_ADD_SYMBOLS_SPOT : QUICK_ADD_SYMBOLS_PERP;
}

export function formatCurrency(value: number | undefined | null): string {
  if (value === undefined || value === null || isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatPnL(value: number): string {
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  return value >= 0 ? `+${formatted}` : `-${formatted}`;
}

export function initializeFormFromBot(bot: BotInstance, config?: BotExchangeConfig): Partial<BotFormState> {
  const rc = bot.default_risk_config || {};
  const ec = bot.default_execution_config || {};
  const crc = config?.risk_config || {};
  const cec = config?.execution_config || {};
  const env = config?.environment || "paper";
  
  return {
    name: bot.name,
    description: bot.description || "",
    allocatorRole: bot.allocator_role || "core",
    templateId: bot.strategy_template_id || "",
    marketType: (bot as any).market_type || "perp",
    credentialId: config?.exchange_account_id || config?.credential_id || "",
    environment: env,
    // If backend lacks a trading_mode field, fall back to the config environment
    tradingMode: (bot as any).trading_mode || env || "paper",
    tradingCapital: config?.trading_capital_usd ?? 1000,
    enabledSymbols: config?.enabled_symbols || ["BTC-USDT-SWAP"],
    risk: {
      positionSizePct: crc.positionSizePct ?? rc.positionSizePct ?? DEFAULT_RISK_STATE.positionSizePct,
      minPositionSizeUsd: crc.minPositionSizeUsd ?? rc.minPositionSizeUsd ?? DEFAULT_RISK_STATE.minPositionSizeUsd,
      maxPositionSizeUsd: crc.maxPositionSizeUsd ?? rc.maxPositionSizeUsd ?? DEFAULT_RISK_STATE.maxPositionSizeUsd,
      maxPositions: crc.maxPositions ?? rc.maxPositions ?? DEFAULT_RISK_STATE.maxPositions,
      maxPositionsPerStrategy: crc.maxPositionsPerStrategy ?? rc.maxPositionsPerStrategy ?? DEFAULT_RISK_STATE.maxPositionsPerStrategy,
      maxLeverage: crc.maxLeverage ?? rc.maxLeverage ?? DEFAULT_RISK_STATE.maxLeverage,
      leverageMode: crc.leverageMode ?? rc.leverageMode ?? DEFAULT_RISK_STATE.leverageMode,
      maxDailyLossPct: crc.maxDailyLossPct ?? rc.maxDailyLossPct ?? DEFAULT_RISK_STATE.maxDailyLossPct,
      maxTotalExposurePct: crc.maxTotalExposurePct ?? rc.maxTotalExposurePct ?? DEFAULT_RISK_STATE.maxTotalExposurePct,
      maxExposurePerSymbolPct: crc.maxExposurePerSymbolPct ?? rc.maxExposurePerSymbolPct ?? DEFAULT_RISK_STATE.maxExposurePerSymbolPct,
      maxPositionsPerSymbol: crc.maxPositionsPerSymbol ?? rc.maxPositionsPerSymbol ?? DEFAULT_RISK_STATE.maxPositionsPerSymbol,
      maxDailyLossPerSymbolPct: crc.maxDailyLossPerSymbolPct ?? rc.maxDailyLossPerSymbolPct ?? DEFAULT_RISK_STATE.maxDailyLossPerSymbolPct,
      maxDrawdownPct: crc.maxDrawdownPct ?? rc.maxDrawdownPct ?? DEFAULT_RISK_STATE.maxDrawdownPct,
    },
    execution: {
      defaultOrderType: cec.defaultOrderType ?? ec.defaultOrderType ?? DEFAULT_EXECUTION_STATE.defaultOrderType,
      stopLossPct: cec.stopLossPct ?? ec.stopLossPct ?? DEFAULT_EXECUTION_STATE.stopLossPct,
      takeProfitPct: cec.takeProfitPct ?? ec.takeProfitPct ?? DEFAULT_EXECUTION_STATE.takeProfitPct,
      trailingStopEnabled: cec.trailingStopEnabled ?? ec.trailingStopEnabled ?? DEFAULT_EXECUTION_STATE.trailingStopEnabled,
      trailingStopPct: cec.trailingStopPct ?? ec.trailingStopPct ?? DEFAULT_EXECUTION_STATE.trailingStopPct,
      maxHoldTimeHours: cec.maxHoldTimeHours ?? ec.maxHoldTimeHours ?? DEFAULT_EXECUTION_STATE.maxHoldTimeHours,
      minTradeIntervalSec: cec.minTradeIntervalSec ?? ec.minTradeIntervalSec ?? DEFAULT_EXECUTION_STATE.minTradeIntervalSec,
      executionTimeoutSec: cec.executionTimeoutSec ?? ec.executionTimeoutSec ?? DEFAULT_EXECUTION_STATE.executionTimeoutSec,
      enableVolatilityFilter: cec.enableVolatilityFilter ?? ec.enableVolatilityFilter ?? DEFAULT_EXECUTION_STATE.enableVolatilityFilter,
      throttleMode: cec.throttleMode ?? ec.throttleMode ?? DEFAULT_EXECUTION_STATE.throttleMode,
      orderIntentMaxAgeSec: cec.orderIntentMaxAgeSec ?? ec.orderIntentMaxAgeSec ?? DEFAULT_EXECUTION_STATE.orderIntentMaxAgeSec,
    },
  };
}

