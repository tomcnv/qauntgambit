import { useMemo, useState } from "react";
import {
  Activity,
  Bot,
  BrainCircuit,
  DollarSign,
  Eye,
  History,
  Info,
  Layers3,
  LogOut,
  Moon,
  Shield,
  Settings2,
  Sun,
  Target,
  TrendingUp,
} from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import Logo from "../../components/logo";
import useAuthStore from "../../store/auth-store";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Separator } from "../../components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useTheme } from "../../components/theme-provider";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "../../components/ui/sheet";
import { Skeleton } from "../../components/ui/skeleton";
import {
  useBotExchangeConfigs,
  useBotInstance,
  useBotPositions,
  useDrawdownData,
  useOverviewData,
  useTradeHistory,
} from "../../lib/api/hooks";
import { usePipelineHealth } from "../../lib/api/quant-hooks";
import { TradeInspectorDrawer } from "../../components/trade-history/TradeInspectorDrawer";
import { mapRawTrade } from "../../components/trade-history/hooks";
import { cn } from "../../lib/utils";

const PARAMETER_HELP: Record<string, string> = {
  enabled: "Controls whether this venue configuration can place new trades. If false, execution is blocked even if signals pass.",
  exchange: "Determines which venue receives orders and where balances, fees, and fills are sourced from.",
  market_type: "Changes the trading mechanics and risk model, such as spot inventory handling versus perpetual positioning.",
  trading_capital_usd: "Sets the capital budget the sizing layer can allocate. Larger values allow larger positions and broader exposure.",
  enabled_symbols: "Defines the symbols the bot is allowed to evaluate and trade. Symbols not listed will never be traded.",
  template_name: "Selects the strategy template that controls signal generation, gating, and execution style.",
  template_slug: "Internal strategy template identifier used to route the bot to the correct trading logic.",
  bot_type: "Determines which runtime path and behavior family this bot uses, including prediction and execution flow.",
  min_confidence: "Raises or lowers the confidence bar required before the bot can act on a signal.",
  require_baseline_alignment: "When enabled, the bot only trades if the secondary signal agrees with the baseline strategy direction.",
  sessions: "Restricts trading to specific market sessions. Outside these sessions, entries are blocked.",
  prediction_provider: "Selects the signal engine that produces directional opinions for entries and exits.",
  max_spread_bps: "Blocks trades when the spread is wider than this threshold, reducing poor entries in low-liquidity conditions.",
  sentiment_required: "Prevents trading unless the required context or sentiment enrichment is available and fresh.",
  risk_per_trade_pct: "Controls how much account risk is committed on each trade sizing decision.",
  riskPerTradePct: "Controls how much account risk is committed on each trade sizing decision.",
  positionSizePct: "Sets the base fraction of available capital or equity that the bot tries to allocate to a new trade before other caps are applied.",
  max_position_size_usd: "Caps single-position exposure so no one trade can exceed this notional amount.",
  maxPositionSizeUsd: "Hard cap on the dollar size of any one position, even if capital and confidence would allow more.",
  min_position_size_usd: "Smallest order size the bot is allowed to place. Signals below this size are rounded up or skipped.",
  minPositionSizeUsd: "Smallest order size the bot is allowed to place. Signals below this size are rounded up or skipped.",
  maxExposurePerSymbolPct: "Maximum share of account equity the bot may allocate to a single symbol. At 25, one market cannot consume more than 25% of deployable exposure.",
  max_exposure_per_symbol_pct: "Maximum share of account equity the bot may allocate to a single symbol. At 25, one market cannot consume more than 25% of deployable exposure.",
  maxTotalExposurePct: "Maximum combined exposure the bot may hold across all open positions before new entries are blocked.",
  max_total_exposure_pct: "Maximum combined exposure the bot may hold across all open positions before new entries are blocked.",
  maxExposurePct: "Overall exposure ceiling used to prevent the portfolio from becoming too concentrated or overextended.",
  max_exposure_pct: "Overall exposure ceiling used to prevent the portfolio from becoming too concentrated or overextended.",
  maxPositions: "Maximum number of open positions the bot may hold at the same time.",
  max_positions: "Maximum number of open positions the bot may hold at the same time.",
  maxPositionsPerSymbol: "Limits the bot to this many simultaneous positions in the same symbol, reducing stacking into one market.",
  max_positions_per_symbol: "Limits the bot to this many simultaneous positions in the same symbol, reducing stacking into one market.",
  maxDrawdownPct: "Kill-switch style drawdown threshold. If account equity falls this far from its peak, the bot stops opening new risk.",
  max_drawdown_pct: "Kill-switch style drawdown threshold. If account equity falls this far from its peak, the bot stops opening new risk.",
  maxDailyLossPct: "Daily loss limit. Once realized and unrealized losses reach this threshold for the day, trading is blocked.",
  max_daily_loss_pct: "Daily loss limit. Once realized and unrealized losses reach this threshold for the day, trading is blocked.",
  maxDailyLossPerSymbolPct: "Per-symbol daily loss cap that stops the bot from repeatedly losing money in the same market on the same day.",
  max_daily_loss_per_symbol_pct: "Per-symbol daily loss cap that stops the bot from repeatedly losing money in the same market on the same day.",
  maxLeverage: "Maximum leverage the bot is allowed to apply when trading leveraged markets.",
  max_leverage: "Maximum leverage the bot is allowed to apply when trading leveraged markets.",
  leverageMode: "Selects isolated or cross leverage behavior, which changes how margin risk is shared across positions.",
  leverage_mode: "Selects isolated or cross leverage behavior, which changes how margin risk is shared across positions.",
  stopLossPct: "Default stop-loss distance used to cut losing trades if the strategy has stop management enabled.",
  stop_loss_pct: "Default stop-loss distance used to cut losing trades if the strategy has stop management enabled.",
  takeProfitPct: "Default take-profit distance used to lock in gains if the strategy has profit targets enabled.",
  take_profit_pct: "Default take-profit distance used to lock in gains if the strategy has profit targets enabled.",
  trailingStopPct: "Trailing-stop distance used to protect gains while allowing winning positions room to run.",
  trailing_stop_pct: "Trailing-stop distance used to protect gains while allowing winning positions room to run.",
  cooldown_ms: "Forces a waiting period between actions, reducing overtrading and repeated rapid-fire entries.",
  fee_bps: "Feeds into profitability and EV checks so the bot can reject trades that do not clear expected costs.",
  slippage_bps: "Sets the slippage budget used when deciding whether execution conditions are acceptable.",
  profile_overrides: "Applies bot-specific behavior overrides on top of the shared strategy defaults.",
  exchange_balance: "Current venue balance snapshot used for monitoring and, in some paths, to bound deployable capital.",
  equity: "Current account equity used by risk controls, drawdown checks, and portfolio monitoring.",
  net_pnl: "Aggregated realized profit and loss used for reporting and drawdown tracking.",
  template_id: "Reference to the strategy template record selected for this bot.",
  exchange_account_name: "Display label for the connected exchange account. This is informational and does not change trading logic.",
};

type ConfigEntry = {
  section: string;
  path: string;
  key: string;
  value: string;
};

function formatCurrency(value: number | null | undefined) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

function asFiniteNumber(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatPercent(value: number | null | undefined, digits = 2) {
  return `${formatNumber(value, digits)}%`;
}

function formatDateTime(value: string | number | null | undefined) {
  if (!value) return "—";
  const parsed = typeof value === "number" ? new Date(value) : new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
}

function formatConfigValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "string") return value || "—";
  return JSON.stringify(value);
}

function humanizeKey(path: string) {
  const key = path.split(".").pop() || path;
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getParameterDescription(entry: ConfigEntry) {
  const leafKey = entry.path.split(".").pop() || entry.key;
  const mapped = PARAMETER_HELP[leafKey] || PARAMETER_HELP[entry.key] || PARAMETER_HELP[entry.path];
  if (mapped) return mapped;

  if (/(^|_|\.)id$/.test(entry.path) || leafKey.endsWith("_id")) {
    return "Reference identifier used to link this bot, account, or config internally. It does not directly change trading behavior.";
  }

  if (leafKey.endsWith("_at") || leafKey.endsWith("_ts") || leafKey.endsWith("_time")) {
    return "Timestamp field used for tracking freshness, sequencing, or audit history. It does not directly change trading decisions.";
  }

  if (leafKey.includes("symbol")) {
    return "Symbol-scoping field that determines which market this part of the configuration applies to.";
  }

  if (leafKey.includes("balance")) {
    return "Balance snapshot used for monitoring account state and, where applicable, to constrain sizing and exposure.";
  }

  if (leafKey.includes("equity")) {
    return "Equity-related field used by monitoring, drawdown protection, and risk controls.";
  }

  if (leafKey.includes("risk")) {
    return "Risk-management field that influences position sizing, exposure limits, or protective guardrails.";
  }

  if (leafKey.includes("position")) {
    return "Position-control field that influences inventory limits, exposure, or monitoring of open trades.";
  }

  if (leafKey.includes("spread") || leafKey.includes("slippage") || leafKey.includes("fee")) {
    return "Execution-quality threshold used to decide whether trading conditions are still economical enough to enter or exit.";
  }

  if (leafKey.includes("session")) {
    return "Session-control field that determines when the bot is allowed to evaluate or place trades.";
  }

  if (leafKey.includes("provider") || leafKey.includes("model")) {
    return "Signal or model-routing field that changes which prediction engine or logic path the bot uses.";
  }

  if (entry.section === "Viewer Scope") {
    return "Viewer access-scoping field used to limit what this account can see. It does not change trading behavior.";
  }

  if (entry.section === "Scoped Metrics") {
    return "Monitoring metric shown for transparency. It reflects current bot state more than it controls trading behavior.";
  }

  return "Supporting runtime field shown for transparency. This value may influence monitoring or routing, but it is not a primary trade-decision threshold.";
}

function flattenConfig(section: string, value: unknown, parentPath = ""): ConfigEntry[] {
  if (value === null || value === undefined) {
    return [{
      section,
      path: parentPath || section.toLowerCase(),
      key: parentPath.split(".").pop() || section,
      value: "—",
    }];
  }

  if (Array.isArray(value)) {
    return [{
      section,
      path: parentPath,
      key: parentPath.split(".").pop() || section,
      value: value.length === 0 ? "[]" : value.map((item) => formatConfigValue(item)).join(", "),
    }];
  }

  if (typeof value !== "object") {
    return [{
      section,
      path: parentPath,
      key: parentPath.split(".").pop() || section,
      value: formatConfigValue(value),
    }];
  }

  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => {
    const path = parentPath ? `${parentPath}.${key}` : key;
    if (child && typeof child === "object" && !Array.isArray(child)) {
      return flattenConfig(section, child, path);
    }
    return [{
      section,
      path,
      key,
      value: formatConfigValue(child),
    }];
  });
}

function resolvePositionSize(position: any) {
  return asFiniteNumber(position?.quantity ?? position?.size ?? position?.contracts) ?? 0;
}

function resolvePositionMarkPrice(position: any) {
  return (
    asFiniteNumber(
      position?.mark_price ??
        position?.current_price ??
        position?.markPrice ??
        position?.entry_price ??
        position?.entryPrice,
    ) ?? 0
  );
}

function resolvePositionEntryPrice(position: any) {
  return asFiniteNumber(position?.entry_price ?? position?.entryPrice) ?? 0;
}

function resolvePositionNotional(position: any) {
  const explicit =
    asFiniteNumber(position?.notional_usd ?? position?.notionalUsd ?? position?.exposure_usd ?? position?.exposureUsd) ??
    null;
  if (explicit != null && explicit > 0) return Math.abs(explicit);
  return Math.abs(resolvePositionSize(position) * resolvePositionMarkPrice(position));
}

function resolvePositionExposure(position: any) {
  const explicit = asFiniteNumber(position?.exposure_usd ?? position?.exposureUsd) ?? null;
  if (explicit != null && explicit > 0) return Math.abs(explicit);
  return resolvePositionNotional(position);
}

function resolvePositionPnl(position: any) {
  return (
    asFiniteNumber(position?.unrealizedPnl ?? position?.unrealized_pnl ?? position?.pnl ?? position?.unrealized) ?? 0
  );
}

function resolvePositionPnlPct(position: any) {
  const explicit = asFiniteNumber(position?.pnl_pct ?? position?.pnlPct ?? position?.unrealized_pnl_pct);
  if (explicit != null) return explicit;
  const entry = resolvePositionEntryPrice(position);
  const mark = resolvePositionMarkPrice(position);
  if (entry <= 0 || mark <= 0) return 0;
  const direction = String(position?.side || "").toUpperCase();
  const rawPct = ((mark - entry) / entry) * 100;
  return direction === "SHORT" || direction === "SELL" ? rawPct * -1 : rawPct;
}

function resolvePositionSide(position: any) {
  return String(position?.side || position?.direction || "LONG").toUpperCase();
}

function positionPnlClass(value: number) {
  if (value > 0) return "text-emerald-600 dark:text-emerald-400";
  if (value < 0) return "text-rose-600 dark:text-rose-400";
  return "text-foreground";
}

function buildSentimentItems(overviewData: any, enabledSymbols: string[], positions: any[], trades: any[]) {
  const sentimentRoot = overviewData?.sentiment ?? overviewData?.liveStatus?.sentiment ?? {};
  const candidateSymbols = [
    ...enabledSymbols,
    ...positions.map((position: any) => String(position?.symbol || "").toUpperCase()),
    ...trades.map((trade: any) => String(trade?.symbol || "").toUpperCase()),
  ].filter(Boolean);
  const orderedSymbols = Array.from(new Set(candidateSymbols));
  const symbolList = orderedSymbols.length > 0 ? orderedSymbols : Object.keys(sentimentRoot).filter((key) => key !== "global");
  const items = symbolList.map((symbol) => {
    const selected = sentimentRoot?.[symbol] || null;
    const sentiment = selected?.sentiment || {};
    const events = selected?.events || {};
    const score = asFiniteNumber(sentiment?.combined_sentiment ?? selected?.score ?? events?.narrative_bias) ?? 0;
    const sourceQuality = asFiniteNumber(sentiment?.source_quality) ?? 0;
    const ageMs = asFiniteNumber(sentiment?.age_ms ?? events?.age_ms) ?? 0;
    return {
      symbol,
      score,
      news: asFiniteNumber(sentiment?.news_sentiment) ?? score,
      social: asFiniteNumber(sentiment?.social_sentiment) ?? score,
      sourceQuality,
      summary: String(sentiment?.summary || selected?.summary || "").trim(),
      topics: Array.isArray(sentiment?.top_topics) ? sentiment.top_topics.slice(0, 3) : [],
      eventFlags: Array.isArray(events?.event_flags) ? events.event_flags.slice(0, 3) : [],
      fresh: !Boolean(sentiment?.is_stale),
      ageMs,
      hasData: Boolean(selected),
    };
  });

  if (items.length > 0) return items;

  const globalSelected = sentimentRoot?.global || null;
  const globalSentiment = globalSelected?.sentiment || {};
  const globalEvents = globalSelected?.events || {};
  const globalScore = asFiniteNumber(globalSentiment?.combined_sentiment ?? globalSelected?.score ?? globalEvents?.narrative_bias) ?? 0;
  return [{
    symbol: "Market",
    score: globalScore,
    news: asFiniteNumber(globalSentiment?.news_sentiment) ?? globalScore,
    social: asFiniteNumber(globalSentiment?.social_sentiment) ?? globalScore,
    sourceQuality: asFiniteNumber(globalSentiment?.source_quality) ?? 0,
    summary: String(globalSentiment?.summary || globalSelected?.summary || "").trim(),
    topics: Array.isArray(globalSentiment?.top_topics) ? globalSentiment.top_topics.slice(0, 3) : [],
    eventFlags: Array.isArray(globalEvents?.event_flags) ? globalEvents.event_flags.slice(0, 3) : [],
    fresh: !Boolean(globalSentiment?.is_stale),
    ageMs: asFiniteNumber(globalSentiment?.age_ms ?? globalEvents?.age_ms) ?? 0,
    hasData: Boolean(globalSelected),
  }];
}

function sentimentTone(score: number) {
  if (score >= 0.2) return "Bullish";
  if (score <= -0.2) return "Bearish";
  return "Neutral";
}

function sentimentBadgeClass(score: number) {
  if (score >= 0.2) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (score <= -0.2) return "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300";
  return "border-border/60 bg-muted/40 text-muted-foreground";
}

function toneBadgeClass(tone: "positive" | "negative" | "warning" | "info" | "neutral") {
  switch (tone) {
    case "positive":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "negative":
      return "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300";
    case "warning":
      return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
    case "info":
      return "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300";
    default:
      return "border-border/60 bg-muted/40 text-muted-foreground";
  }
}

function statusTone(status: string | null | undefined): "positive" | "negative" | "warning" | "info" | "neutral" {
  const normalized = String(status || "").toLowerCase();
  if (["healthy", "ready", "running", "clear", "ok", "fresh", "synced"].includes(normalized)) return "positive";
  if (["degraded", "error", "failed", "blocked", "critical", "active"].includes(normalized)) return "negative";
  if (["warning", "warmup", "warming", "lagging"].includes(normalized)) return "warning";
  if (["idle", "unknown", "pending", "no data"].includes(normalized)) return "neutral";
  return "info";
}

function sideTone(side: string | null | undefined): "positive" | "negative" | "neutral" {
  const normalized = String(side || "").toLowerCase();
  if (normalized === "buy" || normalized === "long") return "positive";
  if (normalized === "sell" || normalized === "short") return "negative";
  return "neutral";
}

function formatLatency(value: number | null | undefined) {
  const numeric = asFiniteNumber(value);
  if (numeric == null) return "—";
  return `${formatNumber(numeric, 1)} ms`;
}

function formatAgeSeconds(value: number | null | undefined) {
  const numeric = asFiniteNumber(value);
  if (numeric == null) return "—";
  if (numeric < 1) return `${formatNumber(numeric * 1000, 0)} ms ago`;
  return `${formatNumber(numeric, 1)}s ago`;
}

export default function ViewerDashboardPage() {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const viewerScope = user?.viewerScope;
  const { theme, toggleTheme } = useTheme();
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [showSettingsSheet, setShowSettingsSheet] = useState(false);
  const [selectedPosition, setSelectedPosition] = useState<any | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<any | null>(null);
  const [activityTab, setActivityTab] = useState("positions");
  const [positionsPage, setPositionsPage] = useState(1);
  const [tradesPage, setTradesPage] = useState(1);
  const [decisionsPage, setDecisionsPage] = useState(1);

  const botId = viewerScope?.botId;
  const exchangeAccountId = viewerScope?.exchangeAccountId;

  const { data: overviewData, isLoading: overviewLoading } = useOverviewData({ botId, exchangeAccountId });
  const { data: botInstanceData } = useBotInstance(botId || "");
  const { data: exchangeConfigsData } = useBotExchangeConfigs(botId || "");
  const { data: drawdownData, isLoading: drawdownLoading, isFetching: drawdownFetching } = useDrawdownData(24, exchangeAccountId, botId);
  const { data: pipelineHealth } = usePipelineHealth(5000);
  const viewerTradeHistoryParams = useMemo(() => {
    const today = new Date();
    const todayStr = today.toLocaleDateString("en-CA");
    return {
      limit: 5000,
      startDate: todayStr,
      endDate: todayStr,
      includeAll: false,
      exchangeAccountId: exchangeAccountId || undefined,
      botId: botId || undefined,
    };
  }, [exchangeAccountId, botId]);
  const { data: tradeHistoryData, isLoading: tradeHistoryLoading, isFetching: tradeHistoryFetching } = useTradeHistory(viewerTradeHistoryParams);
  const { data: positionsData } = useBotPositions({
    exchangeAccountId: exchangeAccountId || undefined,
    botId: botId || undefined,
  });

  if (!viewerScope || !botId || !exchangeAccountId) {
    return (
      <div className="min-h-screen bg-background p-8">
        <Card className="mx-auto max-w-2xl">
          <CardHeader>
            <CardTitle>Viewer Scope Missing</CardTitle>
            <CardDescription>This viewer account is not assigned to a bot yet.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => logout()}>Sign Out</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const bot = botInstanceData?.bot;
  const tradingInfo = overviewData?.botStatus?.trading as any;
  const fastScalperMetrics = (overviewData?.fastScalper as any)?.metrics || {};
  const scopedMetrics = (overviewData?.scopedMetrics as any) || {};
  const hasScopedMetrics = scopedMetrics && Object.keys(scopedMetrics).length > 0;
  const hasTradingMetrics = tradingInfo?.metrics && Object.keys(tradingInfo.metrics).length > 0;
  const hasFastScalperMetrics = fastScalperMetrics && Object.keys(fastScalperMetrics).length > 0;
  const metrics = hasScopedMetrics
    ? scopedMetrics
    : hasTradingMetrics
      ? tradingInfo.metrics
      : hasFastScalperMetrics
        ? fastScalperMetrics
        : {};
  const trades = tradeHistoryData?.trades || [];
  const positions = positionsData?.positions || positionsData?.data || [];
  const resolveTradePnl = (trade: any) => {
    const netRaw = trade?.net_pnl ?? trade?.netPnl;
    const grossRaw = trade?.gross_pnl ?? trade?.grossPnl;
    const feesRaw = trade?.total_fees_usd ?? trade?.totalFees ?? trade?.fees ?? trade?.fee;
    const fees = asFiniteNumber(feesRaw) ?? 0;
    const net = netRaw != null ? (asFiniteNumber(netRaw) ?? 0) : (grossRaw != null ? (asFiniteNumber(grossRaw) ?? 0) - fees : (asFiniteNumber(trade?.pnl) ?? 0));
    const gross = grossRaw != null ? (asFiniteNumber(grossRaw) ?? 0) : (netRaw != null ? net + fees : (asFiniteNumber(trade?.pnl) ?? 0) + fees);
    return { net, gross, fees };
  };
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayTrades = trades.filter((trade: any) => new Date(trade.timestamp || trade.closedAt) >= todayStart);
  const dailyAgg = todayTrades.reduce((acc: { net: number; gross: number; fees: number }, trade: any) => {
    const { net, gross, fees } = resolveTradePnl(trade);
    acc.net += net;
    acc.gross += gross;
    acc.fees += fees;
    return acc;
  }, { net: 0, gross: 0, fees: 0 });
  const tradeStats = tradeHistoryData?.stats || {};
  const metricDailyPnlRaw = asFiniteNumber(metrics?.daily_pnl ?? metrics?.dailyPnl);
  const tradeHistoryPnlRaw = asFiniteNumber(tradeStats?.totalPnl ?? tradeStats?.totalPnL ?? tradeStats?.netPnl);
  const metricDailyFeesRaw = asFiniteNumber(metrics?.daily_fees ?? tradeStats?.totalFees);
  const preferTradeHistoryPnl =
    tradeHistoryPnlRaw != null &&
    (
      metricDailyPnlRaw == null ||
      (
        Math.abs(metricDailyPnlRaw) < 0.01 &&
        Math.abs(tradeHistoryPnlRaw) >= 0.01
      )
    );
  const realizedPnl = preferTradeHistoryPnl
    ? (tradeHistoryPnlRaw ?? 0)
    : (metricDailyPnlRaw ?? dailyAgg.net);
  const dailyFees = metricDailyFeesRaw ?? Math.abs(asFiniteNumber(tradeStats?.totalFees) ?? dailyAgg.fees);
  const dailyPnlGross =
    metricDailyPnlRaw != null
      ? (realizedPnl + dailyFees)
      : (asFiniteNumber(tradeStats?.grossPnl ?? tradeStats?.gross_pnl) ?? dailyAgg.gross);
  const tradesToday = asFiniteNumber(tradeHistoryData?.totalCount) ?? todayTrades.length;
  const unrealizedPnl =
    positions.length > 0
      ? positions.reduce((sum, position) => sum + resolvePositionPnl(position), 0)
      : (asFiniteNumber(metrics?.unrealized_pnl ?? metrics?.unrealizedPnl ?? overviewData?.liveStatus?.risk?.unrealized_pnl) ?? 0);
  const totalPnl = realizedPnl + unrealizedPnl;
  const hasAuthoritativeRealizedPnl = metricDailyPnlRaw != null || tradeHistoryPnlRaw != null || todayTrades.length > 0;
  const pnlPending = !hasAuthoritativeRealizedPnl && (overviewLoading || tradeHistoryLoading || tradeHistoryFetching);
  const winRate = tradeHistoryData?.stats?.winRate ?? 0;
  const hasAuthoritativeEquityCurve = (drawdownData?.drawdown || []).length > 1;
  const chartData =
    hasAuthoritativeEquityCurve
      ? (drawdownData?.drawdown || []).map((point) => ({
          time: point.hour || point.time,
          equity: asFiniteNumber(point.equity ?? point.value ?? point.balance) ?? 0,
        }))
      : [];
  const activeConfig =
    exchangeConfigsData?.configs?.find((config) => config.exchange_account_id === exchangeAccountId) ||
    exchangeConfigsData?.configs?.[0] ||
    bot?.exchangeConfigs?.find((config) => config.exchange_account_id === exchangeAccountId) ||
    bot?.exchangeConfigs?.[0];
  const venue = activeConfig?.exchange || activeConfig?.exchange_account_venue || activeConfig?.exchange_account_label || "Bybit";
  const enabledSymbols = activeConfig?.enabled_symbols || [];
  const tradingCapital = asFiniteNumber(
    activeConfig?.trading_capital_usd ??
      activeConfig?.tradingCapitalUsd ??
      scopedMetrics?.exchange_balance ??
      scopedMetrics?.account_equity,
  );
  const capitalInUse = positions.length > 0
    ? positions.reduce((sum, position) => sum + Math.max(0, resolvePositionExposure(position) || resolvePositionNotional(position) || 0), 0)
    : (asFiniteNumber(metrics?.gross_exposure ?? metrics?.grossExposure ?? overviewData?.liveStatus?.risk?.gross_exposure) ?? 0);
  const availableToDeploy =
    tradingCapital != null && tradingCapital >= 0
      ? Math.max(tradingCapital - capitalInUse, 0)
      : null;
  const decisionLayer = pipelineHealth?.layers?.find((layer) => layer.name === "decision");
  const ingestLayer = pipelineHealth?.layers?.find((layer) => layer.name === "ingest");
  const sentimentItems = buildSentimentItems(overviewData, enabledSymbols, positions, trades);
  const displayOverallStatus =
    pipelineHealth?.overall_status === "degraded" &&
    (pipelineHealth?.layers || []).every((layer) => ["healthy", "idle"].includes(String(layer?.status || "")))
      ? "healthy"
      : pipelineHealth?.overall_status || "unknown";

  const configEntries = useMemo(() => {
    const sections = [
      { section: "Bot", value: bot || {} },
      { section: "Exchange Config", value: activeConfig || {} },
      { section: "Viewer Scope", value: viewerScope || {} },
      { section: "Scoped Metrics", value: scopedMetrics || {} },
    ];
    return sections
      .flatMap(({ section, value }) => flattenConfig(section, value))
      .filter((entry) => entry.path && entry.value !== "—");
  }, [activeConfig, bot, scopedMetrics, viewerScope]);
  const capitalPending = overviewLoading && availableToDeploy == null;
  const PAGE_SIZE = {
    positions: 6,
    trades: 8,
    decisions: 5,
  };
  const positionsPageCount = Math.max(1, Math.ceil(positions.length / PAGE_SIZE.positions));
  const tradesPageCount = Math.max(1, Math.ceil(trades.length / PAGE_SIZE.trades));
  const decisionsPageCount = Math.max(1, Math.ceil(trades.length / PAGE_SIZE.decisions));
  const visiblePositions = positions.slice((Math.min(positionsPage, positionsPageCount) - 1) * PAGE_SIZE.positions, Math.min(positionsPage, positionsPageCount) * PAGE_SIZE.positions);
  const visibleTrades = trades.slice((Math.min(tradesPage, tradesPageCount) - 1) * PAGE_SIZE.trades, Math.min(tradesPage, tradesPageCount) * PAGE_SIZE.trades);
  const visibleDecisions = trades.slice((Math.min(decisionsPage, decisionsPageCount) - 1) * PAGE_SIZE.decisions, Math.min(decisionsPage, decisionsPageCount) * PAGE_SIZE.decisions);
  const symbolStatus = decisionLayer?.symbol_status || [];
  const topDecisionBlockers = Array.from(new Set((decisionLayer?.blockers || []).slice(0, 6)));

  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-border/60 bg-card/70 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <Logo size="md" />
              <h1 className="text-xl font-semibold">{viewerScope.botName || bot?.name || "Bot Viewer"}</h1>
              <Badge variant="outline">Viewer</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {viewerScope.exchangeAccountName || exchangeAccountId}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={toggleTheme}>
              {theme === "dark" ? <Sun className="mr-2 h-4 w-4" /> : <Moon className="mr-2 h-4 w-4" />}
              {theme === "dark" ? "Light" : "Dark"}
            </Button>
            <Button variant="outline" onClick={() => setShowSettingsSheet(true)}>
              <Settings2 className="mr-2 h-4 w-4" />
              Bot Settings
            </Button>
            <Button variant="outline" onClick={() => setShowConfigModal(true)}>
              <Info className="mr-2 h-4 w-4" />
              Full Config
            </Button>
            <Button variant="outline" onClick={() => logout()}>
              <LogOut className="mr-2 h-4 w-4" />
              Sign Out
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1600px] space-y-6 px-6 py-6">
        <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
          <Card className="border-border/70 shadow-sm">
            <CardHeader className="pb-3">
              <CardDescription>Net PnL</CardDescription>
              <CardTitle className={cn("text-3xl tracking-tight", positionPnlClass(totalPnl))}>
                {pnlPending ? <Skeleton className="h-9 w-36" /> : formatCurrency(totalPnl)}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              {pnlPending ? (
                <span>Loading realized and unrealized performance…</span>
              ) : (
                <>
                  <div>{tradesToday > 0 ? `${tradesToday} trades today` : "No closed trades today"}</div>
                  <div>Realized Gross {formatCurrency(dailyPnlGross)} · Fees {formatCurrency(-Math.abs(dailyFees))} · Live Unreal {formatCurrency(unrealizedPnl)}</div>
                </>
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70 shadow-sm">
            <CardHeader className="pb-3">
              <CardDescription>Available To Deploy</CardDescription>
              <CardTitle className="text-3xl tracking-tight">
                {capitalPending ? <Skeleton className="h-9 w-32" /> : availableToDeploy != null ? formatCurrency(availableToDeploy) : "Unavailable"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              {availableToDeploy != null ? (
                <>
                  <div>Allocated {formatCurrency(tradingCapital)} · In Use {formatCurrency(capitalInUse)}</div>
                  <div>Capital budget reserved for this bot after current open exposure.</div>
                </>
              ) : (
                "Authoritative bot allocation data is not available for this bot scope."
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70 shadow-sm">
            <CardHeader className="pb-3">
              <CardDescription>Unrealized PnL</CardDescription>
              <CardTitle className={cn("text-3xl tracking-tight", positionPnlClass(unrealizedPnl))}>
                {formatCurrency(unrealizedPnl)}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              <div>{positions.length} open position{positions.length === 1 ? "" : "s"} · Mark-to-market exposure</div>
              <div>Live impact from currently open positions only.</div>
            </CardContent>
          </Card>

          <Card className="border-border/70 shadow-sm">
            <CardHeader className="pb-3">
              <CardDescription>Win Rate</CardDescription>
              <CardTitle className="text-3xl tracking-tight">{formatNumber(winRate, 1)}%</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-muted-foreground">
              <div>Recent closed trades</div>
              <div>{trades.length} trade{trades.length === 1 ? "" : "s"} in current viewer history.</div>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_420px]">
          <div className="space-y-6">
            <Card className="border-border/70 shadow-sm">
              <CardHeader className="flex flex-col gap-2 border-b border-border/50 pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4" />
                    Equity Curve
                  </CardTitle>
                  <CardDescription>Last 24 hours of realized and mark-to-market account movement for this bot scope</CardDescription>
                </div>
                <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(chartData.length > 0 ? "info" : "neutral"))}>
                  {chartData.length > 0 ? "24h loaded" : "Awaiting scoped history"}
                </Badge>
              </CardHeader>
              <CardContent className="h-[360px] pt-6">
                {chartData.length === 0 ? (
                  <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border/60 text-sm text-muted-foreground">
                    No recent scoped equity series is available yet.
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-border/40" />
                      <XAxis dataKey="time" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                      <YAxis tickFormatter={(value) => `$${Math.round(Number(value))}`} tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                      <Tooltip formatter={(value) => formatCurrency(Number(value))} />
                      <Area type="monotone" dataKey="equity" stroke="hsl(var(--primary))" strokeWidth={2} fill="hsl(var(--primary) / 0.16)" />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70 shadow-sm">
              <CardHeader className="flex flex-col gap-4 border-b border-border/50 pb-4 xl:flex-row xl:items-center xl:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <History className="h-4 w-4" />
                    Activity
                  </CardTitle>
                  <CardDescription>Open positions, recent trades, and executed decisions in one scoped workspace</CardDescription>
                </div>
                <Tabs value={activityTab} onValueChange={setActivityTab}>
                  <TabsList className="grid w-full grid-cols-3 xl:w-[360px]">
                    <TabsTrigger value="positions">Positions</TabsTrigger>
                    <TabsTrigger value="trades">Trades</TabsTrigger>
                    <TabsTrigger value="decisions">Decisions</TabsTrigger>
                  </TabsList>
                </Tabs>
              </CardHeader>
              <CardContent className="pt-6">
                <Tabs value={activityTab} onValueChange={setActivityTab}>
                  <TabsContent value="positions" className="mt-0">
                    <div className="rounded-xl border border-border/60">
                      <ScrollArea className="h-[560px]">
                        {visiblePositions.length === 0 ? (
                          <div className="flex h-[520px] items-center justify-center text-sm text-muted-foreground">No open positions.</div>
                        ) : (
                          <Table className="min-w-[980px]">
                            <TableHeader className="sticky top-0 z-10 bg-background/95 backdrop-blur">
                              <TableRow>
                                <TableHead>Symbol</TableHead>
                                <TableHead>Side</TableHead>
                                <TableHead>Opened</TableHead>
                                <TableHead className="text-right">Entry</TableHead>
                                <TableHead className="text-right">Mark</TableHead>
                                <TableHead className="text-right">Exposure</TableHead>
                                <TableHead className="text-right">PnL</TableHead>
                                <TableHead>SL / TP</TableHead>
                                <TableHead className="text-right">Action</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {visiblePositions.map((position) => (
                                <TableRow key={`${position.symbol}-${position.side}-${position.entry_time || position.updated_at}`}>
                                  <TableCell>
                                    <div className="font-medium">{position.symbol}</div>
                                    <div className="text-xs text-muted-foreground">size {formatNumber(resolvePositionSize(position), 6)}</div>
                                  </TableCell>
                                  <TableCell>
                                    <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(sideTone(resolvePositionSide(position))))}>
                                      {resolvePositionSide(position)}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="text-muted-foreground">{formatDateTime(position.entry_time || position.opened_at || position.updated_at)}</TableCell>
                                  <TableCell className="text-right font-medium">{formatNumber(resolvePositionEntryPrice(position), 2)}</TableCell>
                                  <TableCell className="text-right font-medium">{formatNumber(resolvePositionMarkPrice(position), 2)}</TableCell>
                                  <TableCell className="text-right font-medium">{formatCurrency(resolvePositionExposure(position))}</TableCell>
                                  <TableCell className="text-right">
                                    <div className={cn("font-medium", positionPnlClass(resolvePositionPnl(position)))}>{formatCurrency(resolvePositionPnl(position))}</div>
                                    <div className={cn("text-xs", positionPnlClass(resolvePositionPnlPct(position)))}>{formatPercent(resolvePositionPnlPct(position), 2)}</div>
                                  </TableCell>
                                  <TableCell>
                                    <div className="text-sm">{position.stopLoss ?? position.stop_loss ? formatNumber(position.stopLoss ?? position.stop_loss, 2) : "—"}</div>
                                    <div className="text-xs text-muted-foreground">{position.takeProfit ?? position.take_profit ? formatNumber(position.takeProfit ?? position.take_profit, 2) : "—"}</div>
                                  </TableCell>
                                  <TableCell className="text-right">
                                    <Button variant="outline" size="sm" onClick={() => setSelectedPosition(position)}>
                                      <Eye className="mr-2 h-4 w-4" />
                                      View
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                      </ScrollArea>
                      <div className="flex items-center justify-between border-t border-border/60 px-4 py-3 text-sm text-muted-foreground">
                        <span>Page {Math.min(positionsPage, positionsPageCount)} of {positionsPageCount}</span>
                        <div className="flex gap-2">
                          <Button variant="outline" size="sm" disabled={Math.min(positionsPage, positionsPageCount) <= 1} onClick={() => setPositionsPage((page) => Math.max(page - 1, 1))}>Previous</Button>
                          <Button variant="outline" size="sm" disabled={Math.min(positionsPage, positionsPageCount) >= positionsPageCount} onClick={() => setPositionsPage((page) => Math.min(page + 1, positionsPageCount))}>Next</Button>
                        </div>
                      </div>
                    </div>
                  </TabsContent>

                  <TabsContent value="trades" className="mt-0">
                    <div className="rounded-xl border border-border/60">
                      <ScrollArea className="h-[560px]">
                        {visibleTrades.length === 0 ? (
                          <div className="flex h-[520px] items-center justify-center text-sm text-muted-foreground">No recent trades.</div>
                        ) : (
                          <Table className="min-w-[1120px]">
                            <TableHeader className="sticky top-0 z-10 bg-background/95 backdrop-blur">
                              <TableRow>
                                <TableHead>Trade</TableHead>
                                <TableHead>Time</TableHead>
                                <TableHead className="text-right">Entry / Exit</TableHead>
                                <TableHead className="text-right">Size</TableHead>
                                <TableHead className="text-right">Net PnL</TableHead>
                                <TableHead className="text-right">Fees</TableHead>
                                <TableHead>SL / TP</TableHead>
                                <TableHead>Exit Reason</TableHead>
                                <TableHead className="text-right">Action</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {visibleTrades.map((trade) => (
                                <TableRow key={trade.id}>
                                  <TableCell>
                                    <div className="flex items-center gap-2">
                                      <span className="font-medium">{trade.symbol}</span>
                                      <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(sideTone(trade.side)))}>
                                        {String(trade.side || "trade").toUpperCase()}
                                      </Badge>
                                    </div>
                                    <div className="text-xs text-muted-foreground">{trade.profileName || trade.profileId || trade.strategyName || trade.strategyId || "Executed trade"}</div>
                                  </TableCell>
                                  <TableCell className="text-muted-foreground">{trade.formattedTimestamp || formatDateTime(trade.timestamp)}</TableCell>
                                  <TableCell className="text-right font-medium">{formatNumber(trade.entryPrice || trade.entry_price, 2)} → {formatNumber(trade.exitPrice || trade.exit_price, 2)}</TableCell>
                                  <TableCell className="text-right font-medium">{formatNumber(trade.size, 6)}</TableCell>
                                  <TableCell className="text-right">
                                    <div className={cn("font-medium", positionPnlClass(Number(trade.netPnl ?? trade.pnl ?? 0)))}>{formatCurrency(trade.netPnl ?? trade.pnl)}</div>
                                    <div className="text-xs text-muted-foreground">{trade.pnlPercent != null ? formatPercent(trade.pnlPercent, 2) : "—"}</div>
                                  </TableCell>
                                  <TableCell className="text-right font-medium">{formatCurrency(trade.totalFeesUsd ?? trade.fees ?? 0)}</TableCell>
                                  <TableCell>
                                    <div className="text-sm">{trade.stopLoss || trade.stop_loss ? formatNumber(trade.stopLoss || trade.stop_loss, 2) : "—"}</div>
                                    <div className="text-xs text-muted-foreground">{trade.takeProfit || trade.take_profit ? formatNumber(trade.takeProfit || trade.take_profit, 2) : "—"}</div>
                                  </TableCell>
                                  <TableCell className="max-w-[180px] text-muted-foreground">{trade.exitReason || trade.exit_reason || trade.reason || "—"}</TableCell>
                                  <TableCell className="text-right">
                                    <Button variant="outline" size="sm" onClick={() => setSelectedTrade(mapRawTrade(trade))}>
                                      <Eye className="mr-2 h-4 w-4" />
                                      View
                                    </Button>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        )}
                      </ScrollArea>
                      <div className="flex items-center justify-between border-t border-border/60 px-4 py-3 text-sm text-muted-foreground">
                        <span>Page {Math.min(tradesPage, tradesPageCount)} of {tradesPageCount}</span>
                        <div className="flex gap-2">
                          <Button variant="outline" size="sm" disabled={Math.min(tradesPage, tradesPageCount) <= 1} onClick={() => setTradesPage((page) => Math.max(page - 1, 1))}>Previous</Button>
                          <Button variant="outline" size="sm" disabled={Math.min(tradesPage, tradesPageCount) >= tradesPageCount} onClick={() => setTradesPage((page) => Math.min(page + 1, tradesPageCount))}>Next</Button>
                        </div>
                      </div>
                    </div>
                  </TabsContent>

                  <TabsContent value="decisions" className="mt-0">
                    <div className="rounded-xl border border-border/60">
                      <ScrollArea className="h-[560px]">
                        {visibleDecisions.length === 0 ? (
                          <div className="flex h-[520px] items-center justify-center text-sm text-muted-foreground">No executed decisions yet.</div>
                        ) : (
                          <div className="space-y-4 p-4">
                            {visibleDecisions.map((trade) => (
                              <div key={`decision-${trade.id}`} className="rounded-2xl border border-border/60 bg-card/60 p-4">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div className="space-y-2">
                                    <div className="flex items-center gap-2">
                                      <span className="text-base font-semibold">{trade.symbol}</span>
                                      <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(sideTone(trade.side)))}>
                                        {String(trade.side || "trade").toUpperCase()}
                                      </Badge>
                                      <Badge variant="outline" className={cn("rounded-full", toneBadgeClass("info"))}>Executed</Badge>
                                    </div>
                                    <p className="text-xs text-muted-foreground">{formatDateTime(trade.entryTime || trade.timestamp || trade.createdAt)}</p>
                                  </div>
                                  <div className="text-right">
                                    <div className={cn("text-base font-semibold", positionPnlClass(Number(trade.netPnl ?? trade.pnl ?? 0)))}>{formatCurrency(trade.netPnl ?? trade.pnl)}</div>
                                    <div className="text-xs text-muted-foreground">
                                      Confidence {trade.decision?.signalConfidence != null ? formatPercent(Number(trade.decision.signalConfidence) * 100, 1) : "—"}
                                    </div>
                                  </div>
                                </div>

                                <div className="mt-4 grid gap-3 lg:grid-cols-4">
                                  <div className="rounded-xl border border-border/60 p-3">
                                    <div className="text-xs text-muted-foreground">Entry / Exit</div>
                                    <div className="mt-1 text-sm font-medium">{formatNumber(trade.entryPrice || trade.entry_price, 2)} → {formatNumber(trade.exitPrice || trade.exit_price, 2)}</div>
                                  </div>
                                  <div className="rounded-xl border border-border/60 p-3">
                                    <div className="text-xs text-muted-foreground">Size</div>
                                    <div className="mt-1 text-sm font-medium">{formatNumber(trade.size, 6)}</div>
                                  </div>
                                  <div className="rounded-xl border border-border/60 p-3">
                                    <div className="text-xs text-muted-foreground">Profile / Strategy</div>
                                    <div className="mt-1 text-sm font-medium">{trade.decision?.profileName || trade.decision?.profileId || "—"} / {trade.decision?.strategyName || trade.decision?.strategyId || "—"}</div>
                                  </div>
                                  <div className="rounded-xl border border-border/60 p-3">
                                    <div className="text-xs text-muted-foreground">Latency</div>
                                    <div className="mt-1 text-sm font-medium">{formatLatency(trade.decision?.totalLatencyMs)}</div>
                                  </div>
                                </div>

                                <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr,0.8fr]">
                                  <div className="rounded-xl border border-border/60 p-4">
                                    <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">Why It Happened</div>
                                    <div className="space-y-2 text-sm">
                                      <div><span className="text-muted-foreground">Primary reason: </span>{trade.primaryReason || trade.decision?.primaryReason || trade.reason || "No summarized reason captured"}</div>
                                      <div><span className="text-muted-foreground">Market context: </span>{trade.marketContext?.regime || "—"} · {trade.marketContext?.trend || "—"} · session {trade.marketContext?.session || "—"}</div>
                                      {trade.decision?.stagesExecuted?.length ? <div><span className="text-muted-foreground">Stages passed: </span>{trade.decision.stagesExecuted.join(", ")}</div> : null}
                                    </div>
                                  </div>
                                  <div className="rounded-xl border border-border/60 p-4">
                                    <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">Decision Payload</div>
                                    <pre className="max-h-48 overflow-auto rounded-lg bg-muted/50 p-3 text-[11px] leading-5 text-muted-foreground">
{JSON.stringify({
  decision: trade.decision || null,
  marketContext: trade.marketContext || null,
  finalDecision: trade.finalDecision || null,
}, null, 2)}
                                    </pre>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </ScrollArea>
                      <div className="flex items-center justify-between border-t border-border/60 px-4 py-3 text-sm text-muted-foreground">
                        <span>Page {Math.min(decisionsPage, decisionsPageCount)} of {decisionsPageCount}</span>
                        <div className="flex gap-2">
                          <Button variant="outline" size="sm" disabled={Math.min(decisionsPage, decisionsPageCount) <= 1} onClick={() => setDecisionsPage((page) => Math.max(page - 1, 1))}>Previous</Button>
                          <Button variant="outline" size="sm" disabled={Math.min(decisionsPage, decisionsPageCount) >= decisionsPageCount} onClick={() => setDecisionsPage((page) => Math.min(page + 1, decisionsPageCount))}>Next</Button>
                        </div>
                      </div>
                    </div>
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card className="border-border/70 shadow-sm">
              <CardHeader className="border-b border-border/50 pb-4">
                <CardTitle className="flex items-center gap-2">
                  <Layers3 className="h-4 w-4" />
                  Pipeline Health
                </CardTitle>
                <CardDescription>Read-only runtime and decision quality for the assigned bot</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5 pt-6">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-border/60 p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Overall</div>
                    <div className="mt-3 flex items-center justify-between">
                      <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(statusTone(displayOverallStatus)))}>{displayOverallStatus}</Badge>
                      <span className="text-xs text-muted-foreground">{formatNumber(pipelineHealth?.decisions_per_minute ?? 0, 1)} / min</span>
                    </div>
                  </div>
                  <div className="rounded-xl border border-border/60 p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Execution</div>
                    <div className="mt-3 flex items-center justify-between">
                      <span className="text-lg font-semibold">{formatLatency(pipelineHealth?.tick_to_execution_p99_ms)}</span>
                      <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(pipelineHealth?.kill_switch_active ? "negative" : "positive"))}>
                        {pipelineHealth?.kill_switch_active ? "Kill Switch Active" : "Kill Switch Clear"}
                      </Badge>
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  {[ingestLayer, decisionLayer].filter(Boolean).map((layer) => (
                    <div key={layer?.name} className="rounded-xl border border-border/60 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="font-medium">{layer?.display_name}</div>
                          <div className="mt-1 text-xs text-muted-foreground">{formatNumber(layer?.throughput_per_sec ?? 0, 2)} events/s · p95 {formatLatency(layer?.latency_p95_ms)}</div>
                        </div>
                        <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(statusTone(layer?.status)))}>{layer?.status || "unknown"}</Badge>
                      </div>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        <div className="rounded-lg bg-muted/35 px-3 py-2 text-sm">
                          <span className="text-muted-foreground">Processed </span>
                          <span className="font-medium">{layer?.events_processed || 0}</span>
                        </div>
                        <div className="rounded-lg bg-muted/35 px-3 py-2 text-sm">
                          <span className="text-muted-foreground">Rejected </span>
                          <span className="font-medium">{layer?.events_rejected || 0}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {topDecisionBlockers.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Current blockers</div>
                    <div className="flex flex-wrap gap-2">
                      {topDecisionBlockers.map((blocker) => (
                        <Badge key={blocker} variant="outline" className={cn("rounded-full", toneBadgeClass("warning"))}>{blocker}</Badge>
                      ))}
                    </div>
                  </div>
                )}

                <div className="space-y-3">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Symbol status</div>
                  <div className="space-y-3">
                    {symbolStatus.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">No symbol-level status yet.</div>
                    ) : (
                      symbolStatus.map((symbol) => (
                        <div key={symbol.symbol} className="rounded-xl border border-border/60 p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="font-medium">{symbol.symbol}</div>
                              <div className="mt-1 text-xs text-muted-foreground">{symbol.profile_id || "default profile"} · {symbol.strategy_id || "default strategy"}</div>
                            </div>
                            <Badge variant="outline" className={cn("rounded-full", toneBadgeClass(statusTone(symbol.status)))}>{symbol.status}</Badge>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
                            <span>{symbol.decisions_count || 0} decisions</span>
                            <span>Last update {formatAgeSeconds(symbol.age_sec)}</span>
                          </div>
                          {symbol.rejection_reason ? (
                            <div className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                              {symbol.rejection_reason}
                            </div>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/70 shadow-sm">
              <CardHeader className="border-b border-border/50 pb-4">
                <CardTitle className="flex items-center gap-2">
                  <BrainCircuit className="h-4 w-4" />
                  AI Sentiment Index
                </CardTitle>
                <CardDescription>Slow-moving narrative context per tracked symbol</CardDescription>
              </CardHeader>
              <CardContent className="pt-6">
                <ScrollArea className="h-[560px] pr-4">
                  <div className="space-y-4">
                    {sentimentItems.map((item) => (
                      <div key={item.symbol} className="rounded-2xl border border-border/60 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="font-medium">{item.symbol}</div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {item.hasData ? (item.fresh ? "Fresh" : "Stale") : "No data"}
                              {item.ageMs > 0 ? ` · ${Math.round(item.ageMs / 1000)}s old` : ""}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-2xl font-semibold">{formatNumber(item.score, 2)}</div>
                            <Badge variant="outline" className={cn("rounded-full", sentimentBadgeClass(item.score))}>{sentimentTone(item.score)}</Badge>
                          </div>
                        </div>

                        <div className="mt-4 grid grid-cols-3 gap-3">
                          <div className="rounded-xl border border-border/60 p-3">
                            <div className="text-xs text-muted-foreground">News</div>
                            <div className="mt-1 text-base font-semibold">{formatNumber(item.news, 2)}</div>
                          </div>
                          <div className="rounded-xl border border-border/60 p-3">
                            <div className="text-xs text-muted-foreground">Social</div>
                            <div className="mt-1 text-base font-semibold">{formatNumber(item.social, 2)}</div>
                          </div>
                          <div className="rounded-xl border border-border/60 p-3">
                            <div className="text-xs text-muted-foreground">Quality</div>
                            <div className="mt-1 text-base font-semibold">{formatNumber(item.sourceQuality * 100, 0)}%</div>
                          </div>
                        </div>

                        <div className="mt-4 rounded-xl border border-border/60 p-3 text-sm text-muted-foreground">
                          {item.summary || `No AI sentiment summary is available for ${item.symbol} yet.`}
                        </div>

                        <div className="mt-4 space-y-3">
                          <div>
                            <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">Topics</div>
                            <div className="flex flex-wrap gap-2">
                              {item.topics.length > 0 ? item.topics.map((topic) => (
                                <Badge key={topic} variant="outline" className={cn("rounded-full", toneBadgeClass("info"))}>{topic}</Badge>
                              )) : <span className="text-sm text-muted-foreground">None</span>}
                            </div>
                          </div>
                          <div>
                            <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">Event Flags</div>
                            <div className="flex flex-wrap gap-2">
                              {item.eventFlags.length > 0 ? item.eventFlags.map((flag) => (
                                <Badge key={flag} variant="outline" className={cn("rounded-full", toneBadgeClass("warning"))}>{flag}</Badge>
                              )) : <span className="text-sm text-muted-foreground">None</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        </section>
      </div>

      <Dialog open={Boolean(selectedPosition)} onOpenChange={(open) => !open && setSelectedPosition(null)}>
        <DialogContent className="flex h-[min(82vh,860px)] max-w-[min(94vw,980px)] flex-col overflow-hidden p-0">
          <div className="shrink-0 border-b border-border/60 px-6 py-4">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Target className="h-5 w-5" />
                Position Details
              </DialogTitle>
              <DialogDescription>
                Read-only details for the currently open position.
              </DialogDescription>
            </DialogHeader>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            {selectedPosition ? (
              <div className="space-y-6 px-6 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-xl font-semibold">{selectedPosition.symbol}</div>
                    <div className="text-sm text-muted-foreground">
                      {resolvePositionSide(selectedPosition)} · size {formatNumber(resolvePositionSize(selectedPosition), 6)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={`text-xl font-semibold ${positionPnlClass(resolvePositionPnl(selectedPosition))}`}>
                      {formatCurrency(resolvePositionPnl(selectedPosition))}
                    </div>
                    <div className={`text-sm ${positionPnlClass(resolvePositionPnlPct(selectedPosition))}`}>
                      {formatPercent(resolvePositionPnlPct(selectedPosition), 2)}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-lg border border-border/60 p-4">
                    <div className="text-xs text-muted-foreground">Entry Price</div>
                    <div className="mt-1 text-lg font-semibold">{formatNumber(resolvePositionEntryPrice(selectedPosition), 2)}</div>
                  </div>
                  <div className="rounded-lg border border-border/60 p-4">
                    <div className="text-xs text-muted-foreground">Mark Price</div>
                    <div className="mt-1 text-lg font-semibold">{formatNumber(resolvePositionMarkPrice(selectedPosition), 2)}</div>
                  </div>
                  <div className="rounded-lg border border-border/60 p-4">
                    <div className="text-xs text-muted-foreground">Notional</div>
                    <div className="mt-1 text-lg font-semibold">{formatCurrency(resolvePositionNotional(selectedPosition))}</div>
                  </div>
                  <div className="rounded-lg border border-border/60 p-4">
                    <div className="text-xs text-muted-foreground">Estimated Fees</div>
                    <div className="mt-1 text-lg font-semibold">
                      {formatCurrency(selectedPosition.estimatedRoundTripFeeUsd ?? selectedPosition.estimated_round_trip_fee_usd ?? 0)}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-xl border border-border/60 p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                      <Shield className="h-4 w-4" />
                      Risk Controls
                    </div>
                    <div className="space-y-3 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Stop Loss</span>
                        <span>{selectedPosition.stopLoss ?? selectedPosition.stop_loss ? formatNumber(selectedPosition.stopLoss ?? selectedPosition.stop_loss, 2) : "—"}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Take Profit</span>
                        <span>{selectedPosition.takeProfit ?? selectedPosition.take_profit ? formatNumber(selectedPosition.takeProfit ?? selectedPosition.take_profit, 2) : "—"}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Guard Status</span>
                        <span>{selectedPosition.guard_status || "—"}</span>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border border-border/60 p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                      <DollarSign className="h-4 w-4" />
                      Position Accounting
                    </div>
                    <div className="space-y-3 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Exposure</span>
                        <span>{formatCurrency(resolvePositionExposure(selectedPosition))}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Net After Est. Fees</span>
                        <span>{formatCurrency(selectedPosition.estimatedNetUnrealizedAfterFees ?? selectedPosition.estimated_net_unrealized_after_fees ?? resolvePositionPnl(selectedPosition))}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Prediction Confidence</span>
                        <span>{selectedPosition.prediction_confidence != null ? `${formatNumber(Number(selectedPosition.prediction_confidence) * 100, 1)}%` : "—"}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-border/60 p-4">
                  <div className="mb-2 text-sm font-medium">Raw Position Payload</div>
                  <pre className="overflow-auto rounded-lg bg-muted/40 p-4 text-[11px] leading-5 text-muted-foreground">
{JSON.stringify(selectedPosition, null, 2)}
                  </pre>
                </div>
              </div>
            ) : null}
          </ScrollArea>
          <div className="shrink-0 border-t border-border/60 px-6 py-4">
            <DialogFooter className="justify-end">
              <Button variant="outline" onClick={() => setSelectedPosition(null)}>Close</Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      <Sheet open={showSettingsSheet} onOpenChange={setShowSettingsSheet}>
        <SheetContent side="right" className="w-[720px] sm:max-w-[720px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Bot Settings
            </SheetTitle>
            <SheetDescription>
              Read-only summary of the active bot configuration and trading scope.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-5 text-sm">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-border/60 p-4">
                <div className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">Identity</div>
                <div className="space-y-3">
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Bot Type</span><span>{bot?.bot_type || "standard"}</span></div>
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Market</span><span>{bot?.market_type || activeConfig?.market_type || "spot"}</span></div>
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Strategy</span><span>{bot?.template_name || bot?.template_slug || activeConfig?.template_name || "Default"}</span></div>
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Venue</span><span>{venue}</span></div>
                </div>
              </div>
              <div className="rounded-xl border border-border/60 p-4">
                <div className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">Trading Scope</div>
                <div className="space-y-3">
                  <div className="flex items-start justify-between gap-4"><span className="text-muted-foreground">Symbols</span><span className="text-right">{enabledSymbols.join(", ") || "Not configured"}</span></div>
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Trading Capital</span><span>{formatCurrency(tradingCapital)}</span></div>
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Exchange Account</span><span>{viewerScope.exchangeAccountName || exchangeAccountId}</span></div>
                  <div className="flex items-center justify-between"><span className="text-muted-foreground">Viewer Scope</span><Badge variant="outline">Read Only</Badge></div>
                </div>
              </div>
            </div>
            <Separator />
            <div>
              <div className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">Why These Settings Matter</div>
              <div className="grid gap-3">
                <div className="rounded-lg border border-border/60 p-3">
                  <div className="font-medium">Market and Strategy</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    These determine whether the bot trades spot or derivatives, which signal engine it uses, and how entries and exits are structured.
                  </div>
                </div>
                <div className="rounded-lg border border-border/60 p-3">
                  <div className="font-medium">Symbols and Capital</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    These define which instruments are eligible to trade and how much capital the sizing and exposure controls are allowed to allocate.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </SheetContent>
      </Sheet>

      <TradeInspectorDrawer
        open={Boolean(selectedTrade)}
        onOpenChange={(open) => !open && setSelectedTrade(null)}
        trade={selectedTrade}
      />

      <Dialog open={showConfigModal} onOpenChange={setShowConfigModal}>
        <DialogContent className="flex h-[min(86vh,920px)] max-w-[min(96vw,1400px)] flex-col overflow-hidden p-0">
          <DialogHeader className="border-b border-border/60 px-6 py-5">
            <DialogTitle>Full Trading Configuration</DialogTitle>
            <DialogDescription>
              Read-only view of the current bot, exchange, and scope parameters that influence trading behavior.
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-8 px-6 py-6">
              {Array.from(new Set(configEntries.map((entry) => entry.section))).map((section) => (
                <section key={section} className="space-y-4">
                  <div className="space-y-1">
                    <h3 className="text-sm font-semibold uppercase tracking-[0.25em] text-muted-foreground">{section}</h3>
                    <p className="text-sm text-muted-foreground">
                      Read-only parameters currently influencing this bot for the selected viewer scope.
                    </p>
                  </div>
                  <div className="grid gap-4 xl:grid-cols-2">
                    {configEntries
                      .filter((entry) => entry.section === section)
                      .map((entry) => {
                        const helpText = getParameterDescription(entry);
                        const leafKey = entry.path.split(".").pop() || entry.key;
                        const showPath = entry.path.includes(".") && !/(^|_|\.)id$/.test(entry.path) && !leafKey.endsWith("_id");
                        return (
                          <div key={`${entry.section}-${entry.path}`} className="rounded-2xl border border-border/60 bg-card/60 p-4 shadow-sm">
                            <div className="space-y-3">
                              <div className="flex items-start justify-between gap-4">
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2">
                                    <div className="rounded-full border border-border/60 bg-muted/40 p-1.5 text-muted-foreground">
                                      <Info className="h-3.5 w-3.5" />
                                    </div>
                                    <div className="text-sm font-semibold text-foreground">{humanizeKey(entry.path)}</div>
                                  </div>
                                  {showPath ? (
                                    <div className="mt-2 truncate pl-8 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                                      {entry.path}
                                    </div>
                                  ) : null}
                                </div>
                                <div className="max-w-[46%] rounded-xl border border-border/60 bg-background/80 px-3 py-2 text-right font-mono text-xs text-foreground">
                                  {entry.value}
                                </div>
                              </div>
                              <p className="pl-8 text-sm leading-6 text-muted-foreground">
                                {helpText}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </section>
              ))}
            </div>
          </ScrollArea>
          <div className="flex shrink-0 items-center justify-between border-t border-border/60 bg-card/95 px-6 py-4 backdrop-blur">
            <p className="text-sm text-muted-foreground">
              {configEntries.length} parameters visible in this read-only viewer scope.
            </p>
            <Button onClick={() => setShowConfigModal(false)}>Close</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
