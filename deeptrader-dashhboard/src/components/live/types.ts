// Types for Live Trading components

export interface LiveStatus {
  heartbeat: {
    status: 'ok' | 'stale' | 'dead';
    lastTickMs: number;
    ageSeconds: number;
  };
  websocket: {
    market: boolean;
    orders: boolean;
    positions: boolean;
  };
  lastDecision: {
    status: 'approved' | 'rejected' | 'none';
    reason?: string;
    timestamp?: string;
    symbol?: string;
  };
  lastOrder: {
    status: 'submitted' | 'filled' | 'canceled' | 'rejected' | 'none';
    latencyMs?: number;
    timestamp?: string;
    symbol?: string;
  };
  riskState: {
    status: 'ok' | 'throttled' | 'paused';
    guardrail?: string;
    pausedBy?: 'user' | 'guardrail' | 'connectivity';
  };
  dataQuality: {
    score: number; // 0-100
    gapCount: number;
    staleSymbols: string[];
  };
}

export interface SymbolStats {
  symbol: string;
  netPnl: number;
  fillsCount: number;
  avgSlippage: number;
  avgLatency: number;
  volume: number;
  lastPrice?: number;
}

export interface OpsMetrics {
  exposure: {
    net: number;
    gross: number;
    maxAllowedPct: number;
    currentPct: number;
  };
  pendingOrders: {
    count: number;
    oldestAgeSeconds: number;
  };
  rejectRate: {
    last5m: number;
    last1h: number;
    topReason: string;
    topReasonCount: number;
  };
  slippage: {
    p50: number;
    p95: number;
    avg: number;
  };
  pnl: {
    realized: number;
    unrealized: number;
    fees: number;
    net: number;
    tradesCount: number;
  };
}

export interface RejectFunnel {
  evaluated: number;
  gated: number;
  approved: number;
  ordered: number;
  filled: number;
}

export interface GateStats {
  name: string;
  blocking: boolean;
  current: number;
  threshold: number;
  unit: string;
}

export interface Anomaly {
  id: string;
  type: 'latency_spike' | 'slippage_outlier' | 'partial_fill' | 'exchange_reject' | 'stale_data' | 'position_mismatch';
  timestamp: string;
  symbol?: string;
  severity: 'warning' | 'critical';
  message: string;
  value?: number;
  threshold?: number;
}

export interface LiveTapeFilters {
  timeRange: '5m' | '15m' | '1h' | '24h' | 'all';
  symbols: string[];
  strategies: string[];
  anomaliesOnly: boolean;
  hideReconciled: boolean;
}

export interface FillRow {
  id: string;
  time: string;
  timestamp: number;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  entryPrice: number;
  exitPrice?: number;
  pnl?: number;
  stopLoss?: number;
  takeProfit?: number;
  strategy?: string;
  latency?: number;
  slippage?: number;
  fee?: number;
  orderType?: 'maker' | 'taker';
  expectedPrice?: number;
  decisionId?: string;
  reconciled?: boolean;
}

export interface OrderRow {
  id: string;
  time: string;
  timestamp: number;
  symbol: string;
  side: 'BUY' | 'SELL';
  type: string;
  quantity: number;
  price: number;
  status: string;
  filledQty?: number;
  avgPrice?: number;
}

export interface PositionRow {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  quantity: number;
  entryPrice: number;
  markPrice: number;
  unrealizedPnl: number;
  stopLoss?: number;
  takeProfit?: number;
  leverage: number;
}



