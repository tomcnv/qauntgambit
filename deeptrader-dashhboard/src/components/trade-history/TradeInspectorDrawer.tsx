/**
 * TradeInspectorDrawer - Unified trade detail drawer with chart & comprehensive analysis
 * 
 * This is the STANDARD component to use everywhere a user views trade details.
 * Width: 800px for optimal screen real estate usage
 * Features: Price chart, 5-tab navigation (Summary, Fills, Trace, Context, Notes)
 */

import { useState, useMemo } from 'react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '../ui/sheet';
import { Separator } from '../ui/separator';
import { cn, formatQuantity } from '../../lib/utils';
import {
  X,
  Play,
  Download,
  Link,
  AlertTriangle,
  Clock,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Activity,
  Zap,
  Target,
  ShieldAlert,
  ChevronRight,
  ChevronLeft,
  ChevronLeftIcon,
  ChevronRightIcon,
  CheckCircle,
  XCircle,
  Circle,
  BarChart3,
  Brain,
  FileText,
  Tag,
  Plus,
  Loader2,
  ExternalLink,
  Bot,
} from 'lucide-react';
import { QuantTrade, DecisionTrace, TradeFill, MarketContext, DecisionStage, AIPredictionTrace } from './types';
import { useTradeInspector } from './hooks';
import { useCandlestickData } from '../../lib/api/hooks';
import { CandlestickChart, ExecutionMarker } from '../dashboard/candlestick-chart';
import { TradeCopilotIcon } from '@/components/copilot/TradeCopilotIcon';
import { QuantTrade as CopilotQuantTrade } from '@/store/copilot-store';

/** Map trade-history QuantTrade to copilot store QuantTrade shape */
function toCopilotTrade(trade: QuantTrade): CopilotQuantTrade {
  return {
    id: trade.id,
    symbol: trade.symbol,
    side: trade.side,
    entry_price: trade.entryPrice,
    exit_price: trade.exitPrice,
    pnl: trade.netPnl,
    holdingDuration: trade.holdTimeSeconds * 1000,
    decisionTrace: trade.decisionTraceId,
    size: trade.quantity,
    timestamp: trade.timestamp,
  };
}

// Flexible trade input - accepts either QuantTrade or API trade format
export interface TradeInput {
  id?: string;
  // Identity
  timestamp?: number | string;
  symbol?: string;
  side?: string;
  profileId?: string;
  profileName?: string;
  profile_id?: string;
  profile?: string;
  strategyId?: string;
  strategyName?: string;
  strategy_id?: string;
  strategy?: string;
  botId?: string;
  botName?: string;
  // Position
  quantity?: number;
  size?: number;
  notional?: number;
  leverage?: number;
  riskPercent?: number;
  // Entry/Exit
  holdTimeSeconds?: number;
  entryPrice?: number;
  entry_price?: number;
  exitPrice?: number;
  exit_price?: number;
  entryTime?: number | string;
  entry_time?: string;
  exitTime?: number | string;
  exit_time?: string;
  // P&L
  realizedPnl?: number;
  pnl?: number;
  pnlBps?: number;
  pnlPercent?: number;
  fees?: number;
  netPnl?: number;
  rMultiple?: number;
  // MAE/MFE
  mae?: number;
  mfe?: number;
  maeBps?: number;
  mfeBps?: number;
  // Execution
  slippageBps?: number;
  entrySlippageBps?: number;
  exitSlippageBps?: number;
  slippage_bps?: number;
  entry_slippage_bps?: number;
  exit_slippage_bps?: number;
  slippage?: number;
  latencyMs?: number;
  latency_ms?: number;
  latency?: number;
  makerPercent?: number;
  fillsCount?: number;
  rejections?: number;
  entryFeeUsd?: number;
  exitFeeUsd?: number;
  totalFeesUsd?: number;
  entry_fee_usd?: number;
  exit_fee_usd?: number;
  total_fees_usd?: number;
  spreadCostBps?: number;
  totalCostBps?: number;
  spread_cost_bps?: number;
  total_cost_bps?: number;
  midAtSend?: number;
  expectedPriceAtSend?: number;
  mid_at_send?: number;
  expected_price_at_send?: number;
  sendTs?: number;
  ackTs?: number;
  firstFillTs?: number;
  finalFillTs?: number;
  send_ts?: number;
  ack_ts?: number;
  first_fill_ts?: number;
  final_fill_ts?: number;
  postOnlyRejectCount?: number;
  cancelAfterTimeoutCount?: number;
  post_only_reject_count?: number;
  cancel_after_timeout_count?: number;
  orderType?: string;
  order_type?: string;
  postOnly?: boolean;
  post_only?: boolean;
  // State
  decisionOutcome?: string;
  decision_outcome?: string;
  decision_id?: string;
  exitReason?: string;
  exit_reason?: string;
  primaryReason?: string;
  incidentId?: string;
  // Trace
  decisionTraceId?: string;
  hasDecisionTrace?: boolean;
  // Tags
  tags?: string[];
  notes?: string;
}

// Normalize trade input to consistent format
function normalizeTradeInput(input: TradeInput): QuantTrade {
  const parseNum = (value?: number): number | undefined => (
    typeof value === 'number' && Number.isFinite(value) ? value : undefined
  );
  const parseEpoch = (value?: number): number | undefined => {
    const n = parseNum(value);
    if (n === undefined) return undefined;
    return n < 1e12 ? n * 1000 : n;
  };
  const parseTime = (value?: number | string): number | undefined => {
    if (value === undefined || value === null || value === '') return undefined;
    if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const timestamp = typeof input.timestamp === 'string' 
    ? new Date(input.timestamp).getTime() 
    : input.timestamp || Date.now();

  const entryTime = parseTime(input.entryTime) ?? parseTime(input.entry_time) ?? timestamp;
  const holdTimeSecondsInput = typeof input.holdTimeSeconds === 'number'
    ? input.holdTimeSeconds
    : undefined;
  const parsedExitTime = parseTime(input.exitTime) ?? parseTime(input.exit_time);
  const exitTime = parsedExitTime ?? (
    holdTimeSecondsInput !== undefined && holdTimeSecondsInput > 0
      ? entryTime + holdTimeSecondsInput * 1000
      : undefined
  );
  
  const entryPrice = input.entryPrice || input.entry_price || 0;
  const exitPrice = input.exitPrice || input.exit_price || 0;
  const pnl = input.pnl || input.realizedPnl || 0;
  const fees = input.fees || 0;
  
  return {
    id: input.id || '',
    timestamp,
    symbol: input.symbol || '',
    side: (input.side?.toLowerCase() as 'long' | 'short' | 'buy' | 'sell') || 'long',
    profileId: input.profileId || input.profile_id,
    profileName: input.profileName || input.profile,
    strategyId: input.strategyId || input.strategy_id,
    strategyName: input.strategyName || input.strategy,
    botId: input.botId,
    botName: input.botName,
    quantity: input.quantity || input.size || 0,
    notional: input.notional || 0,
    leverage: input.leverage || 1,
    riskPercent: input.riskPercent,
    holdTimeSeconds:
      holdTimeSecondsInput ??
      (exitTime !== undefined ? Math.max(0, Math.floor((exitTime - entryTime) / 1000)) : 0),
    entryPrice,
    exitPrice,
    entryTime,
    exitTime: exitTime,
    realizedPnl: pnl,
    pnlBps: input.pnlBps || (input.pnlPercent ? input.pnlPercent * 100 : 0),
    fees,
    netPnl: input.netPnl ?? (pnl - fees),
    rMultiple: input.rMultiple,
    mae: input.mae,
    mfe: input.mfe,
    maeBps: input.maeBps,
    mfeBps: input.mfeBps,
    slippageBps: input.slippageBps || input.slippage_bps || input.slippage,
    entrySlippageBps: input.entrySlippageBps || input.entry_slippage_bps,
    exitSlippageBps: input.exitSlippageBps || input.exit_slippage_bps,
    latencyMs: input.latencyMs || input.latency_ms || input.latency,
    makerPercent: input.makerPercent,
    fillsCount: input.fillsCount,
    rejections: input.rejections,
    entryFeeUsd: input.entryFeeUsd || input.entry_fee_usd,
    exitFeeUsd: input.exitFeeUsd || input.exit_fee_usd,
    totalFeesUsd: input.totalFeesUsd || input.total_fees_usd,
    spreadCostBps: input.spreadCostBps || input.spread_cost_bps,
    totalCostBps: input.totalCostBps || input.total_cost_bps,
    midAtSend: input.midAtSend || input.mid_at_send,
    expectedPriceAtSend: input.expectedPriceAtSend || input.expected_price_at_send,
    sendTs: parseEpoch(input.sendTs || input.send_ts),
    ackTs: parseEpoch(input.ackTs || input.ack_ts),
    firstFillTs: parseEpoch(input.firstFillTs || input.first_fill_ts),
    finalFillTs: parseEpoch(input.finalFillTs || input.final_fill_ts),
    postOnlyRejectCount: parseNum(input.postOnlyRejectCount || input.post_only_reject_count),
    cancelAfterTimeoutCount: parseNum(input.cancelAfterTimeoutCount || input.cancel_after_timeout_count),
    orderType: input.orderType || input.order_type,
    postOnly: input.postOnly ?? input.post_only,
    decisionOutcome: (input.decisionOutcome || input.decision_outcome) as 'approved' | 'rejected' | undefined,
    exitReason: input.exitReason || input.exit_reason,
    primaryReason: input.primaryReason,
    incidentId: input.incidentId,
    decisionTraceId: input.decisionTraceId || input.decision_id,
    hasDecisionTrace: input.hasDecisionTrace || !!input.decision_id,
    tags: input.tags,
    notes: input.notes,
  };
}

export interface TradeInspectorDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trade: QuantTrade | TradeInput | null;
  onReplay?: (trade: QuantTrade) => void;
  onExport?: (trade: QuantTrade) => void;
  onCreateIncident?: (trade: QuantTrade) => void;
  onNavigate?: (direction: 'prev' | 'next') => void;
  hasPrev?: boolean;
  hasNext?: boolean;
}

const formatUsd = (value?: number) =>
  value === undefined || Number.isNaN(value)
    ? '—'
    : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value);

const formatTime = (timestamp?: number) => {
  if (!timestamp) return '—';
  return new Date(timestamp).toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit',
    hour12: false 
  });
};

const formatDateTime = (timestamp?: number) => {
  if (!timestamp) return '—';
  return new Date(timestamp).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatBps = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} bps` : '—';

const formatConfidence = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';

const formatPredictionTime = (value: unknown) => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return formatDateTime(value > 1e12 ? value : value * 1000);
  }
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return formatDateTime(numeric > 1e12 ? numeric : numeric * 1000);
    }
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? formatDateTime(parsed) : '—';
  }
  return '—';
};

// ═══════════════════════════════════════════════════════════════
// PRICE ACTION CHART COMPONENT
// ═══════════════════════════════════════════════════════════════

function TradePriceChart({ trade }: { trade: QuantTrade }) {
  const toMillis = (value?: number | string): number | null => {
    if (value === undefined || value === null) return null;
    const parsed = typeof value === 'string' ? Date.parse(value) : Number(value);
    if (!Number.isFinite(parsed)) return null;
    return parsed < 1e12 ? parsed * 1000 : parsed;
  };

  const entryMs = toMillis(trade.entryTime) ?? toMillis(trade.timestamp) ?? Date.now();
  const fallbackExitMs = entryMs + Math.max((trade.holdTimeSeconds || 0) * 1000, 60_000);
  const exitMs = toMillis(trade.exitTime) ?? fallbackExitMs;
  const durationSec = Math.max(60, Math.floor((exitMs - entryMs) / 1000));

  const timeframe = durationSec <= 3 * 3600 ? "1m" : durationSec <= 24 * 3600 ? "5m" : "15m";
  // Keep enough market context for readability, even on short holds.
  const padSec = Math.max(15 * 60, Math.floor(durationSec * 0.25));
  const windowStartMs = Math.max(0, entryMs - (padSec * 1000));
  const windowEndMs = exitMs + (padSec * 1000);
  const timeframeSec = timeframe === "1m" ? 60 : timeframe === "5m" ? 300 : 900;
  const limit = Math.max(120, Math.min(2000, Math.ceil((windowEndMs - windowStartMs) / (timeframeSec * 1000)) + 20));

  const { data: candleData, isLoading: loadingCandles } = useCandlestickData(
    trade.symbol || null,
    timeframe,
    limit,
    windowStartMs,
    windowEndMs,
  );
  const { data: fallbackCandleData, isLoading: loadingFallbackCandles } = useCandlestickData(
    trade.symbol || null,
    timeframe,
    Math.max(limit, 240),
  );
  
  const windowCandles = candleData?.candles || [];
  const fallbackCandles = fallbackCandleData?.candles || [];
  const candles = windowCandles.length >= 20 ? windowCandles : fallbackCandles;
  const isChartDataLimited = windowCandles.length > 0 && windowCandles.length < 20;
  const isCandlesLoading = loadingCandles || (windowCandles.length < 20 && loadingFallbackCandles);
  
  // Build execution markers for entry and exit
  const executionMarkers = useMemo((): ExecutionMarker[] => {
    if (candles.length === 0) return [];
    
    const sideStr = (trade.side || "").toLowerCase();
    const isBuy = sideStr === "buy" || sideStr === "long";
    
    const markers: ExecutionMarker[] = [];
    
    // Helper to find nearest candle time
    const findNearestCandleTime = (targetTime: number, preferFuture = false): number => {
      if (preferFuture) {
        const future = candles.find((c) => c.time >= targetTime);
        if (future) return future.time;
      }
      let nearest = candles[0].time;
      let minDiff = Math.abs(candles[0].time - targetTime);
      
      for (const candle of candles) {
        const diff = Math.abs(candle.time - targetTime);
        if (diff < minDiff) {
          minDiff = diff;
          nearest = candle.time;
        }
      }
      return nearest;
    };
    
    // Get entry time
    const entryTimeTarget = Math.floor(entryMs / 1000);
    
    // Get exit time
    const exitTimeTarget = Math.floor(exitMs / 1000);
    
    // Entry marker
    if (trade.entryPrice) {
      const entryCandleTime = findNearestCandleTime(entryTimeTarget);
      markers.push({
        time: entryCandleTime,
        price: trade.entryPrice,
        side: isBuy ? "buy" : "sell",
        size: trade.quantity,
      });
    }
    
    // Exit marker
    if (trade.exitPrice) {
      let exitCandleTime = findNearestCandleTime(exitTimeTarget, true);
      // If both markers collapse to one candle for sub-minute holds, nudge exit marker.
      if (markers.length > 0 && exitCandleTime === markers[0].time && candles.length > 1) {
        const currentIdx = candles.findIndex((c) => c.time === exitCandleTime);
        if (currentIdx >= 0 && currentIdx < candles.length - 1) {
          exitCandleTime = candles[currentIdx + 1].time;
        }
      }
      markers.push({
        time: exitCandleTime,
        price: trade.exitPrice,
        side: isBuy ? "sell" : "buy", // Exit is opposite of entry
        size: trade.quantity,
      });
    }
    
    // Ensure markers are sorted by time
    markers.sort((a, b) => a.time - b.time);
    
    return markers;
  }, [candles, trade, entryMs, exitMs]);
  
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Price Action</p>
        {isCandlesLoading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
      </div>
      {candles.length > 0 ? (
        <>
          <CandlestickChart 
          data={candles} 
          executionMarkers={executionMarkers}
          height={220}
          className="rounded-lg overflow-hidden"
        />
          {isChartDataLimited && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Limited historical candles in selected time window; showing broader recent context.
            </p>
          )}
        </>
      ) : (
        <div className="h-[220px] flex items-center justify-center text-muted-foreground text-sm bg-muted/50 rounded-lg">
          {isCandlesLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading chart...
            </div>
          ) : (
            "No chart data available"
          )}
        </div>
      )}
      <div className="mt-3 flex items-center justify-center gap-6 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" /> Entry @ ${trade.entryPrice?.toLocaleString()}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500" /> Exit @ ${trade.exitPrice?.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// TAB 1: SUMMARY
// ═══════════════════════════════════════════════════════════════

function SummaryTab({ 
  trade, 
  onReplay,
  onExport,
}: { 
  trade: QuantTrade; 
  onReplay?: () => void;
  onExport?: () => void;
}) {
  const netPnl = trade.netPnl;
  const isProfitable = netPnl >= 0;
  
  // Timeline stages
  const timelineStages = [
    { label: 'Signal', time: trade.entryTime, status: 'complete' },
    { label: 'Decision', time: trade.entryTime, status: trade.decisionOutcome === 'rejected' ? 'rejected' : 'complete' },
    { label: 'Order', time: trade.entryTime, status: 'complete' },
    { label: 'Fill', time: trade.entryTime, status: 'complete' },
    { label: 'Exit', time: trade.exitTime || trade.timestamp, status: trade.exitTime ? 'complete' : 'pending' },
  ];
  
  return (
    <div className="space-y-6">
      {/* Price Action Chart - PROMINENT */}
      <TradePriceChart trade={trade} />
      
      {/* Trade Timeline */}
      <div className="space-y-3">
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Timeline</h4>
        <div className="flex items-center gap-1">
          {timelineStages.map((stage, i) => (
            <div key={stage.label} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={cn(
                  "h-6 w-6 rounded-full flex items-center justify-center",
                  stage.status === 'complete' && "bg-emerald-500/20 text-emerald-500",
                  stage.status === 'rejected' && "bg-red-500/20 text-red-500",
                  stage.status === 'pending' && "bg-muted text-muted-foreground"
                )}>
                  {stage.status === 'complete' && <CheckCircle className="h-3.5 w-3.5" />}
                  {stage.status === 'rejected' && <XCircle className="h-3.5 w-3.5" />}
                  {stage.status === 'pending' && <Circle className="h-3.5 w-3.5" />}
                </div>
                <span className="text-[10px] text-muted-foreground mt-1">{stage.label}</span>
              </div>
              {i < timelineStages.length - 1 && (
                <ChevronRight className="h-3 w-3 text-muted-foreground/30 mx-1" />
              )}
            </div>
          ))}
        </div>
      </div>
      
      <Separator className="bg-border" />
      
      {/* Entry/Exit Details */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-3">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Entry</h4>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Price</span>
              <span className="font-mono">${trade.entryPrice.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Quantity</span>
              <span className="font-mono">{formatQuantity(trade.quantity)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Notional</span>
              <span className="font-mono">{formatUsd(trade.notional)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Time</span>
              <span className="font-mono text-xs">{formatTime(trade.entryTime)}</span>
            </div>
          </div>
        </div>
        <div className="space-y-3">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Exit</h4>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Price</span>
              <span className="font-mono">${trade.exitPrice.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Reason</span>
              <Badge variant="outline" className="text-[10px]">
                {trade.exitReason || 'unknown'}
              </Badge>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Hold Time</span>
              <span className="font-mono text-xs">
                {trade.holdTimeSeconds < 60 
                  ? `${trade.holdTimeSeconds}s`
                  : trade.holdTimeSeconds < 3600 
                    ? `${Math.floor(trade.holdTimeSeconds / 60)}m`
                    : `${Math.floor(trade.holdTimeSeconds / 3600)}h`
                }
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Time</span>
              <span className="font-mono text-xs">{formatTime(trade.exitTime)}</span>
            </div>
          </div>
        </div>
      </div>
      
      <Separator className="bg-muted" />
      
      {/* P&L Breakdown */}
      <div className="space-y-3">
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">P&L Breakdown</h4>
        <div className={cn(
          "rounded-lg border p-4",
          isProfitable ? "border-emerald-500/20 bg-emerald-500/5" : "border-red-500/20 bg-red-500/5"
        )}>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Net P&L</span>
            <span className={cn(
              "text-2xl font-bold",
              isProfitable ? "text-emerald-500" : "text-red-500"
            )}>
              {formatUsd(netPnl)}
            </span>
          </div>
          <div className="mt-3 space-y-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Gross P&L</span>
              <span className="font-mono">{formatUsd(trade.realizedPnl)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Fees</span>
              <span className="font-mono text-amber-500">-{formatUsd(trade.fees)}</span>
            </div>
            {trade.pnlBps !== undefined && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Return</span>
                <span className="font-mono">{trade.pnlBps.toFixed(1)} bps</span>
              </div>
            )}
            {trade.rMultiple !== undefined && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">R-Multiple</span>
                <span className={cn(
                  "font-mono",
                  trade.rMultiple >= 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {trade.rMultiple >= 0 ? '+' : ''}{trade.rMultiple.toFixed(2)}R
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
      
      <Separator className="bg-muted" />
      
      {/* Key Metrics */}
      <div className="space-y-3">
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Execution Metrics</h4>
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg bg-muted p-3 text-center">
            <p className="text-[10px] text-muted-foreground uppercase">Slippage</p>
            <p className={cn(
              "text-lg font-semibold font-mono",
              (typeof trade.slippageBps === 'number' && trade.slippageBps > 3) ? "text-amber-500" : "text-foreground"
            )}>
              {typeof trade.slippageBps === 'number' ? trade.slippageBps.toFixed(1) : '—'}<span className="text-xs">bp</span>
            </p>
          </div>
          <div className="rounded-lg bg-muted p-3 text-center">
            <p className="text-[10px] text-muted-foreground uppercase">Latency</p>
            <p className={cn(
              "text-lg font-semibold font-mono",
              (typeof trade.latencyMs === 'number' && trade.latencyMs > 100) ? "text-amber-500" : "text-foreground"
            )}>
              {typeof trade.latencyMs === 'number' ? trade.latencyMs.toFixed(0) : '—'}<span className="text-xs">ms</span>
            </p>
          </div>
          <div className="rounded-lg bg-muted p-3 text-center">
            <p className="text-[10px] text-muted-foreground uppercase">Maker %</p>
            <p className="text-lg font-semibold font-mono">
              {typeof trade.makerPercent === 'number'
                ? `${(trade.makerPercent * 100).toFixed(0)}%` 
                : '—'
              }
            </p>
          </div>
        </div>
      </div>

      {(trade.totalCostBps !== undefined || trade.entryFeeUsd !== undefined || trade.exitFeeUsd !== undefined) && (
        <>
          <Separator className="bg-muted" />
          <div className="space-y-3">
            <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Cost Attribution</h4>
            <div className="rounded-lg bg-muted border border-border p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Entry Fee</span>
                <span className="font-mono">{formatUsd(trade.entryFeeUsd)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Exit Fee</span>
                <span className="font-mono">{formatUsd(trade.exitFeeUsd)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Spread Cost</span>
                <span className="font-mono">{trade.spreadCostBps !== undefined ? `${trade.spreadCostBps.toFixed(2)} bps` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total Cost</span>
                <span className="font-mono">{trade.totalCostBps !== undefined ? `${trade.totalCostBps.toFixed(2)} bps` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Post-Only Rejects</span>
                <span className="font-mono">{trade.postOnlyRejectCount ?? 0}</span>
              </div>
            </div>
          </div>
        </>
      )}
      
      {/* MAE/MFE */}
      {(trade.mae !== undefined || trade.mfe !== undefined) && (
        <>
          <Separator className="bg-muted" />
          <div className="space-y-3">
            <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Risk Excursion</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                <p className="text-[10px] text-red-500/80 uppercase">MAE (Max Adverse)</p>
                <p className="text-lg font-semibold font-mono text-red-500">
                  {trade.maeBps !== undefined ? `${trade.maeBps.toFixed(0)}bp` : formatUsd(trade.mae)}
                </p>
              </div>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                <p className="text-[10px] text-emerald-500/80 uppercase">MFE (Max Favorable)</p>
                <p className="text-lg font-semibold font-mono text-emerald-500">
                  {trade.mfeBps !== undefined ? `${trade.mfeBps.toFixed(0)}bp` : formatUsd(trade.mfe)}
                </p>
              </div>
            </div>
          </div>
        </>
      )}
      
      <Separator className="bg-muted" />
      
      {/* Quick Links */}
      <div className="flex flex-wrap gap-2">
        {onReplay && (
          <Button variant="outline" size="sm" onClick={onReplay} className="gap-1.5">
            <Play className="h-3.5 w-3.5" />
            Replay
          </Button>
        )}
        {onExport && (
          <Button variant="outline" size="sm" onClick={onExport} className="gap-1.5">
            <Download className="h-3.5 w-3.5" />
            Export
          </Button>
        )}
        {trade.incidentId && (
          <Button variant="outline" size="sm" className="gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" />
            View Incident
          </Button>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// TAB 2: FILLS
// ═══════════════════════════════════════════════════════════════

function FillsTab({ trade, fills }: { trade: QuantTrade; fills: TradeFill[] }) {
  const totalFee = fills.reduce((sum, f) => sum + (typeof f.fee === 'number' ? f.fee : 0), 0);
  const avgSlippage = fills.length > 0 
    ? fills.reduce((sum, f) => sum + (typeof f.slippageBps === 'number' ? f.slippageBps : 0), 0) / fills.length 
    : 0;
  const hasAvgSlippage = fills.some((f) => typeof f.slippageBps === 'number');
  const firstFill = fills[0];
  const hasExpectedPrice = firstFill?.slippageBps !== undefined && firstFill?.price !== undefined;
  const side = (trade.side || '').toLowerCase();
  const isBuy = side === 'buy' || side === 'long';
  const expectedPrice = hasExpectedPrice
    ? (
        isBuy
          ? firstFill!.price / (1 + (firstFill!.slippageBps! / 10000))
          : firstFill!.price / (1 - (firstFill!.slippageBps! / 10000))
      )
    : null;
  
  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-muted p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">Fills</p>
          <p className="text-lg font-semibold">{fills.length || trade.fillsCount || 1}</p>
        </div>
        <div className="rounded-lg bg-muted p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">Total Fees</p>
          <p className="text-lg font-semibold text-amber-500">{formatUsd(totalFee || trade.fees)}</p>
        </div>
        <div className="rounded-lg bg-muted p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">Avg Slippage</p>
          <p className="text-lg font-semibold">
            {hasAvgSlippage
              ? `${avgSlippage.toFixed(1)}bp`
              : (typeof trade.slippageBps === 'number' ? `${trade.slippageBps.toFixed(1)}bp` : '—')}
          </p>
        </div>
      </div>
      
      {/* Fills Table */}
      {fills.length > 0 ? (
        <div className="space-y-3">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Fill Details</h4>
          <div className="border border-border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">Time</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Qty</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Price</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Fee</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">Slip</th>
                  <th className="px-3 py-2 text-center text-xs font-medium text-muted-foreground">Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {fills.map((fill) => (
                  <tr key={fill.id} className="hover:bg-muted">
                    <td className="px-3 py-2 font-mono text-xs">{formatTime(fill.timestamp)}</td>
                    <td className="px-3 py-2 text-right font-mono">{formatQuantity(fill.quantity)}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {typeof fill.price === 'number' ? `$${fill.price.toFixed(2)}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-amber-500">
                      {typeof fill.fee === 'number' ? `$${fill.fee.toFixed(4)}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {typeof fill.slippageBps === 'number' ? `${fill.slippageBps.toFixed(1)}bp` : '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge 
                        variant="outline" 
                        className={cn(
                          "text-[10px]",
                          fill.liquidity === 'maker' ? "bg-emerald-500/10 text-emerald-500" : "bg-blue-500/10 text-blue-500"
                        )}
                      >
                        {fill.liquidity}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-muted-foreground">
          <Zap className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No detailed fill data available</p>
          <p className="text-xs mt-1">Single fill trades may not have decomposition</p>
        </div>
      )}
      
      {/* Slippage Decomposition */}
      {typeof trade.slippageBps === 'number' && (
        <div className="space-y-3">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Slippage Analysis</h4>
          <div className="rounded-lg bg-muted border border-border p-4 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Expected Price (pre-slippage)</span>
              <span className="font-mono">
                {expectedPrice !== null && Number.isFinite(expectedPrice)
                  ? `$${expectedPrice.toFixed(2)}`
                  : 'not recorded'}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Realized Price</span>
              <span className="font-mono">${trade.entryPrice.toFixed(2)}</span>
            </div>
            <Separator className="bg-border" />
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Total Slippage</span>
              <span className={cn(
                "font-mono font-medium",
                trade.slippageBps > 3 ? "text-amber-500" : "text-foreground"
              )}>
                {trade.slippageBps.toFixed(2)} bps
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// TAB 3: DECISION TRACE
// ═══════════════════════════════════════════════════════════════

function AIPredictionPanel({ aiTrace }: { aiTrace?: AIPredictionTrace | null }) {
  const matched = aiTrace?.matchedPrediction as Record<string, unknown> | null | undefined;
  const recent = Array.isArray(aiTrace?.recentPredictions) ? aiTrace.recentPredictions : [];
  if (!matched && recent.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-muted/40 p-4">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-muted-foreground" />
          <p className="text-sm font-medium">AI Provider</p>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">No AI prediction payload was matched to this trade.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Bot className="h-4 w-4 text-primary" />
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">AI Provider</h4>
      </div>

      {matched && (
        <div className="rounded-lg border border-border bg-muted/40 p-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">{String(matched.source || 'unknown')}</p>
              <p className="text-xs text-muted-foreground">
                {String(matched.provider_version || '—')} • {formatPredictionTime(matched.ts ?? matched.timestamp)}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{String(matched.direction || '—')}</Badge>
              {matched.fallback_used ? <Badge variant="outline" className="text-amber-500">fallback</Badge> : null}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="rounded-md bg-background/80 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Confidence</p>
              <p className="mt-1 font-semibold">{formatConfidence(matched.confidence as number | null | undefined)}</p>
            </div>
            <div className="rounded-md bg-background/80 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Expected Move</p>
              <p className="mt-1 font-semibold">{formatBps(matched.expected_move_bps as number | null | undefined)}</p>
            </div>
            <div className="rounded-md bg-background/80 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Horizon</p>
              <p className="mt-1 font-semibold">
                {typeof matched.horizon_sec === 'number' ? `${matched.horizon_sec}s` : '—'}
              </p>
            </div>
            <div className="rounded-md bg-background/80 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Provider Latency</p>
              <p className="mt-1 font-semibold">
                {typeof matched.provider_latency_ms === 'number' ? `${matched.provider_latency_ms.toFixed(0)}ms` : '—'}
              </p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-md bg-background/80 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Reason Codes</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {Array.isArray(matched.reason_codes) && matched.reason_codes.length ? (
                  matched.reason_codes.map((reason) => (
                    <Badge key={String(reason)} variant="secondary">{String(reason)}</Badge>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">None</span>
                )}
              </div>
            </div>
            <div className="rounded-md bg-background/80 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Risk Flags</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {Array.isArray(matched.risk_flags) && matched.risk_flags.length ? (
                  matched.risk_flags.map((flag) => (
                    <Badge key={String(flag)} variant="outline" className="text-amber-500 border-amber-500/30">
                      {String(flag)}
                    </Badge>
                  ))
                ) : (
                  <span className="text-sm text-muted-foreground">None</span>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-md bg-background/80 p-3">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-muted-foreground" />
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">System Handling</p>
            </div>
            <p className="mt-2 text-sm">
              Outcome: <span className="font-semibold">{aiTrace?.systemOutcome || 'unknown'}</span>
            </p>
            <p className="text-sm text-muted-foreground">
              {aiTrace?.systemReason || (matched.reject ? String(matched.reason || 'prediction rejected') : 'No explicit rejection reason recorded')}
            </p>
          </div>

          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">Raw AI payload</summary>
            <pre className="mt-2 overflow-x-auto rounded-md bg-background/80 p-3 text-xs">
              {JSON.stringify(matched, null, 2)}
            </pre>
          </details>
        </div>
      )}

      {recent.length > 0 && (
        <div className="rounded-lg border border-border bg-muted/20 p-4">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Recent AI Predictions</p>
          <div className="mt-3 space-y-2">
            {recent.slice(0, 5).map((item, index) => {
              const prediction = item as Record<string, unknown>;
              return (
                <div key={`${String(prediction.ts || prediction.timestamp || index)}`} className="flex items-center justify-between rounded-md bg-background/70 px-3 py-2 text-sm">
                  <div>
                    <p className="font-medium">{String(prediction.direction || '—')} • {formatConfidence(prediction.confidence as number | null | undefined)}</p>
                    <p className="text-xs text-muted-foreground">{formatPredictionTime(prediction.ts ?? prediction.timestamp)}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-xs">{formatBps(prediction.expected_move_bps as number | null | undefined)}</p>
                    <p className="text-xs text-muted-foreground">{String(prediction.source || 'unknown')}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function DecisionTraceTab({ trade, trace, aiTrace }: { trade: QuantTrade; trace?: DecisionTrace | null; aiTrace?: AIPredictionTrace | null }) {
  const hasAiTrace = !!aiTrace?.matchedPrediction || (Array.isArray(aiTrace?.recentPredictions) && aiTrace.recentPredictions.length > 0);
  if (!trace && !trade.hasDecisionTrace && !hasAiTrace) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Brain className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm">No decision trace available</p>
        <p className="text-xs mt-1">Decision traces capture the full pipeline execution</p>
      </div>
    );
  }
  
  const stages = trace?.stages || [];
  
  return (
    <div className="space-y-6">
      <AIPredictionPanel aiTrace={aiTrace} />

      {/* Trace Summary */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-muted p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">Outcome</p>
          <Badge 
            variant="outline" 
            className={cn(
              "mt-1",
              trace?.outcome === 'approved' ? "bg-emerald-500/10 text-emerald-500" : "bg-red-500/10 text-red-500"
            )}
          >
            {trace?.outcome || trade.decisionOutcome || 'unknown'}
          </Badge>
        </div>
        <div className="rounded-lg bg-muted p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">Stages</p>
          <p className="text-lg font-semibold">{stages.length}</p>
        </div>
        <div className="rounded-lg bg-muted p-3 text-center">
          <p className="text-[10px] text-muted-foreground uppercase">Total Latency</p>
          <p className="text-lg font-semibold">{trace?.totalLatencyMs?.toFixed(0) || '—'}ms</p>
        </div>
      </div>
      
      {/* Pipeline Visualization */}
      {stages.length > 0 ? (
        <div className="space-y-3">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Pipeline Stages</h4>
          <div className="space-y-2">
            {stages.map((stage, i) => {
              const output = stage.output ?? { pass: false, score: undefined, reason: undefined };
              const latencyMs = typeof stage.latencyMs === 'number' ? stage.latencyMs : null;
              const score = typeof output.score === 'number' ? output.score : null;
              return (
              <div
                key={`${stage.name}-${i}`}
                className={cn(
                  "rounded-lg border p-4",
                  output.pass 
                    ? "border-border bg-muted" 
                    : "border-red-500/20 bg-red-500/5"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {output.pass ? (
                      <CheckCircle className="h-4 w-4 text-emerald-500" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-500" />
                    )}
                    <span className="font-medium">{stage.name}</span>
                  </div>
                  <span className="text-xs text-muted-foreground font-mono">
                    {latencyMs !== null ? `${latencyMs.toFixed(1)}ms` : '—'}
                  </span>
                </div>
                
                {score !== null && (
                  <div className="flex items-center gap-2 text-sm mb-2">
                    <span className="text-muted-foreground">Score:</span>
                    <span className="font-mono">{score.toFixed(4)}</span>
                  </div>
                )}
                
                {output.reason && (
                  <p className="text-sm text-muted-foreground">{output.reason}</p>
                )}
                
                {stage.features && Object.keys(stage.features).length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
                      Features ({Object.keys(stage.features).length})
                    </summary>
                    <pre className="mt-2 text-xs bg-muted/80 rounded p-2 overflow-x-auto">
                      {JSON.stringify(stage.features, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            )})}
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-muted-foreground">
          <p className="text-sm">Loading trace details...</p>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// TAB 4: MARKET CONTEXT
// ═══════════════════════════════════════════════════════════════

function MarketContextTab({ trade, context }: { trade: QuantTrade; context?: MarketContext | null }) {
  return (
    <div className="space-y-6">
      {/* Price Action Chart */}
      <TradePriceChart trade={trade} />
      
      {/* Regime Overview */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-muted/50 border border-border p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Regime</p>
          <p className="text-lg font-semibold capitalize">{context?.regime || '—'}</p>
        </div>
        <div className="rounded-lg bg-muted/50 border border-border p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Trend</p>
          <p className={cn(
            "text-lg font-semibold capitalize",
            context?.trend === 'bullish' && "text-emerald-500",
            context?.trend === 'bearish' && "text-red-500"
          )}>
            {context?.trend || '—'}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 border border-border p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Volatility</p>
          <p className={cn(
            "text-lg font-semibold capitalize",
            context?.volatility === 'high' && "text-amber-500"
          )}>
            {context?.volatility || '—'}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 border border-border p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Session</p>
          <p className="text-lg font-semibold capitalize">{context?.session || '—'}</p>
        </div>
      </div>
      
      {/* Additional Context */}
      {(context?.spread !== undefined || context?.volume24h !== undefined) && (
        <div className="space-y-3">
          <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Market Data</h4>
          <div className="grid grid-cols-2 gap-3">
            {context?.spread !== undefined && (
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[10px] text-muted-foreground uppercase">Spread</p>
                <p className="text-lg font-semibold font-mono">{context.spread.toFixed(2)} bps</p>
              </div>
            )}
            {context?.volume24h !== undefined && (
              <div className="rounded-lg bg-muted p-3">
                <p className="text-[10px] text-muted-foreground uppercase">24h Volume</p>
                <p className="text-lg font-semibold font-mono">{formatUsd(context.volume24h)}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// TAB 5: NOTES
// ═══════════════════════════════════════════════════════════════

function NotesTab({ trade, onCreateIncident }: { trade: QuantTrade; onCreateIncident?: () => void }) {
  const [notes, setNotes] = useState(trade.notes || '');
  const [tags, setTags] = useState<string[]>(trade.tags || []);
  const [newTag, setNewTag] = useState('');
  
  const addTag = () => {
    if (newTag.trim() && !tags.includes(newTag.trim())) {
      setTags([...tags, newTag.trim()]);
      setNewTag('');
    }
  };
  
  const removeTag = (tag: string) => {
    setTags(tags.filter(t => t !== tag));
  };
  
  return (
    <div className="space-y-6">
      {/* Notes */}
      <div className="space-y-3">
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Notes</h4>
        <Textarea
          placeholder="Add notes about this trade..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="min-h-[120px] bg-muted border-border"
        />
        <p className="text-[10px] text-muted-foreground">
          Notes are saved locally. Backend persistence coming soon.
        </p>
      </div>
      
      {/* Tags */}
      <div className="space-y-3">
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Tags</h4>
        <div className="flex flex-wrap gap-2">
          {tags.map(tag => (
            <Badge
              key={tag}
              variant="outline"
              className="gap-1 cursor-pointer hover:bg-muted/80"
              onClick={() => removeTag(tag)}
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
              <X className="h-2.5 w-2.5" />
            </Badge>
          ))}
          <div className="flex items-center gap-1">
            <Input
              placeholder="Add tag..."
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addTag()}
              className="h-6 w-24 text-xs bg-muted border-border"
            />
            <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={addTag}>
              <Plus className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>
      
      {/* Incident Link */}
      <Separator className="bg-muted" />
      <div className="space-y-3">
        <h4 className="text-xs uppercase tracking-wider text-muted-foreground">Incident Tracking</h4>
        {trade.incidentId ? (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <span className="text-sm">Linked to incident</span>
              </div>
              <Button variant="outline" size="sm" className="gap-1.5">
                <Link className="h-3.5 w-3.5" />
                View
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <Button 
              variant="outline" 
              size="sm" 
              className="gap-1.5"
              onClick={onCreateIncident}
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              Create Incident
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Link className="h-3.5 w-3.5" />
              Link to Existing
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════

export function TradeInspectorDrawer({
  open,
  onOpenChange,
  trade: tradeInput,
  onReplay,
  onExport,
  onCreateIncident,
  onNavigate,
  hasPrev = false,
  hasNext = false,
}: TradeInspectorDrawerProps) {
  const [activeTab, setActiveTab] = useState('summary');
  
  // Normalize trade input to QuantTrade format
  const trade = useMemo(() => {
    if (!tradeInput) return null;
    // Check if it's already a QuantTrade (has netPnl property)
    if ('netPnl' in tradeInput && tradeInput.netPnl !== undefined) {
      return tradeInput as QuantTrade;
    }
    return normalizeTradeInput(tradeInput as TradeInput);
  }, [tradeInput]);
  
  // Fetch additional data when trade changes
  const { data: inspectorTradeData, decisionTrace, aiTrace, fills, marketContext, isLoading } = useTradeInspector(
    trade?.id || null,
    {
      symbol: trade?.symbol || null,
      botId: trade?.botId || null,
      entryTime: trade?.entryTime || null,
      timestamp: trade?.timestamp || null,
    }
  );
  const inspectorTrade = useMemo(() => {
    if (!trade) return null;
    if (!inspectorTradeData) return trade;
    return normalizeTradeInput({
      ...(trade as unknown as Record<string, unknown>),
      ...(inspectorTradeData as Record<string, unknown>),
    });
  }, [trade, inspectorTradeData]);
  
  if (!inspectorTrade) return null;
  
  const isProfitable = inspectorTrade.netPnl >= 0;
  const sideValue = (inspectorTrade.side || '').toLowerCase();
  const directionLabel = sideValue === 'sell' || sideValue === 'short' ? 'short' : 'long';
  
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent 
        side="right" 
        className="w-[800px] sm:max-w-[800px] overflow-y-auto p-0"
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-background/95 backdrop-blur-sm">
          <SheetHeader className="p-6 pb-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                {/* P&L indicator */}
                <div className={cn(
                  "h-12 w-12 rounded-xl flex items-center justify-center",
                  isProfitable ? "bg-emerald-500/15" : "bg-red-500/15"
                )}>
                  {isProfitable ? (
                    <TrendingUp className="h-6 w-6 text-emerald-500" />
                  ) : (
                    <TrendingDown className="h-6 w-6 text-red-500" />
                  )}
                </div>
                <div>
                  <SheetTitle className="flex items-center gap-3 text-xl">
                    {inspectorTrade.symbol?.replace(/-USDT-SWAP|-USDT/, '')}
                    <Badge 
                      variant="outline"
                      className={cn(
                        "text-xs uppercase font-semibold px-2",
                        directionLabel === 'long'
                          ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/30" 
                          : "bg-red-500/10 text-red-500 border-red-500/30"
                      )}
                    >
                      {directionLabel}
                    </Badge>
                    {inspectorTrade.strategyName && (
                      <Badge variant="outline" className="text-xs font-normal bg-muted">
                        {inspectorTrade.strategyName}
                      </Badge>
                    )}
                  </SheetTitle>
                  <p className="text-sm text-muted-foreground mt-0.5">{formatDateTime(inspectorTrade.timestamp)}</p>
                </div>
              </div>
              
              {/* P&L and navigation */}
              <div className="flex items-center gap-4">
                <div className={cn(
                  "text-right",
                  isProfitable ? "text-emerald-500" : "text-red-500"
                )}>
                  <p className="text-2xl font-bold tracking-tight">{formatUsd(inspectorTrade.netPnl)}</p>
                  <p className="text-xs text-muted-foreground">net P&L</p>
                </div>
                
                {/* Navigation buttons */}
                {onNavigate && (hasPrev || hasNext) && (
                  <div className="flex items-center gap-1 ml-2 border-l border-border pl-4">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      disabled={!hasPrev}
                      onClick={() => onNavigate('prev')}
                    >
                      <ChevronLeftIcon className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      disabled={!hasNext}
                      onClick={() => onNavigate('next')}
                    >
                      <ChevronRightIcon className="h-4 w-4" />
                    </Button>
                  </div>
                )}

                {/* Copilot icon */}
                <TradeCopilotIcon trade={toCopilotTrade(inspectorTrade)} />
              </div>
            </div>
          </SheetHeader>
          
          {/* Tabs */}
          <div className="px-6">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="w-full grid grid-cols-5 bg-muted/50 h-10">
                <TabsTrigger value="summary" className="text-sm">Summary</TabsTrigger>
                <TabsTrigger value="fills" className="text-sm">Fills</TabsTrigger>
                <TabsTrigger value="trace" className="text-sm flex items-center gap-1.5">
                  Trace
                  {inspectorTrade.hasDecisionTrace && <Brain className="h-3.5 w-3.5 text-primary" />}
                </TabsTrigger>
                <TabsTrigger value="context" className="text-sm">Context</TabsTrigger>
                <TabsTrigger value="notes" className="text-sm">Notes</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>
        
        {/* Tab Content */}
        <div className="p-6">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsContent value="summary" className="m-0 mt-0">
              <SummaryTab 
                trade={inspectorTrade} 
                onReplay={onReplay ? () => onReplay(inspectorTrade) : undefined}
                onExport={onExport ? () => onExport(inspectorTrade) : undefined}
              />
            </TabsContent>
            
            <TabsContent value="fills" className="m-0 mt-0">
              <FillsTab trade={inspectorTrade} fills={fills || []} />
            </TabsContent>
            
            <TabsContent value="trace" className="m-0 mt-0">
              <DecisionTraceTab trade={inspectorTrade} trace={decisionTrace} aiTrace={aiTrace} />
            </TabsContent>
            
            <TabsContent value="context" className="m-0 mt-0">
              <MarketContextTab trade={inspectorTrade} context={marketContext} />
            </TabsContent>
            
            <TabsContent value="notes" className="m-0 mt-0">
              <NotesTab 
                trade={inspectorTrade} 
                onCreateIncident={onCreateIncident ? () => onCreateIncident(inspectorTrade) : undefined}
              />
            </TabsContent>
          </Tabs>
        </div>
        
        {/* Loading indicator */}
        {isLoading && (
          <div className="absolute top-4 right-16 z-20">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default TradeInspectorDrawer;
