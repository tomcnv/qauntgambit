import { useState, useMemo, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { useTradeHistory, useTradeDetail } from "../../lib/api/hooks";
import { useLocation } from "react-router-dom";
import type { TradeHistoryEntry, TradeDetail } from "../../lib/api/types";
import { cn, formatQuantity } from "../../lib/utils";
import { useScopeStore } from "../../store/scope-store";
import {
  TrendingUp,
  TrendingDown,
  ChevronLeft,
  ChevronRight,
  Search,
  Filter,
  X,
  Eye,
  Clock,
  Target,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  Brain,
  Zap,
} from "lucide-react";

const formatUsd = (value?: number) =>
  value === undefined || Number.isNaN(value)
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);

const formatPercent = (value?: number | null) =>
  value === undefined || value === null || Number.isNaN(value)
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

const formatDate = (timestamp?: number | null) => {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const formatTime = (timestamp?: number | null) => {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const formatDateTime = (timestamp?: number | null) => {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const getExitReasonBadge = (reason?: string | null) => {
  if (!reason) return null;
  
  const config: Record<string, { color: string; label: string }> = {
    stop_loss: { color: "bg-red-500/10 text-red-300 border-red-400/30", label: "Stop Loss" },
    take_profit: { color: "bg-emerald-500/10 text-emerald-300 border-emerald-400/30", label: "Take Profit" },
    signal_exit: { color: "bg-blue-500/10 text-blue-300 border-blue-400/30", label: "Signal Exit" },
    break_even: { color: "bg-gray-500/10 text-gray-300 border-gray-400/30", label: "Break Even" },
    time_exit: { color: "bg-amber-500/10 text-amber-300 border-amber-400/30", label: "Time Exit" },
    manual: { color: "bg-purple-500/10 text-purple-300 border-purple-400/30", label: "Manual" },
  };
  
  const cfg = config[reason] || { color: "bg-gray-500/10 text-gray-300 border-gray-400/30", label: reason };
  
  return (
    <Badge className={cn("text-xs", cfg.color)}>
      {cfg.label}
    </Badge>
  );
};

// Stats Summary Card
function StatsSummary({ stats }: { stats?: any }) {
  if (!stats) return null;
  
  const netPnl = (stats.netPnl ?? stats.totalPnl) || 0;
  const totalFees = stats.totalFees || 0;
  
  return (
    <div className="space-y-4">
      {/* Main Stats Row */}
      <div className="grid gap-4 md:grid-cols-4 lg:grid-cols-5">
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Trades</p>
            <p className="mt-1 text-2xl font-semibold text-white">{stats.totalTrades}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Gross P&L</p>
            <p className={cn("mt-1 text-2xl font-semibold", stats.totalPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              {formatUsd(stats.totalPnl)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-yellow-500/20 bg-yellow-500/5">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-yellow-400/80">Total Fees</p>
            <p className="mt-1 text-2xl font-semibold text-yellow-400">-{formatUsd(totalFees)}</p>
            <p className="text-xs text-yellow-400/60">{formatUsd(stats.avgFeesPerTrade || 0)}/trade</p>
          </CardContent>
        </Card>
        <Card className={cn("border-2", netPnl >= 0 ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5")}>
          <CardContent className="pt-4">
            <p className={cn("text-xs uppercase tracking-[0.3em]", netPnl >= 0 ? "text-emerald-400/80" : "text-red-400/80")}>Net P&L</p>
            <p className={cn("mt-1 text-2xl font-semibold", netPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              {formatUsd(netPnl)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Win Rate</p>
            <p className="mt-1 text-2xl font-semibold text-white">{stats.winRate?.toFixed(1)}%</p>
          </CardContent>
        </Card>
      </div>
      
      {/* Secondary Stats Row */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Avg P&L</p>
            <p className={cn("mt-1 text-2xl font-semibold", stats.avgPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              {formatUsd(stats.avgPnl)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Winners</p>
            <p className="mt-1 text-2xl font-semibold text-emerald-400">{stats.winningTrades}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Losers</p>
            <p className="mt-1 text-2xl font-semibold text-red-400">{stats.losingTrades}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Best Trade</p>
            <p className="mt-1 text-2xl font-semibold text-emerald-400">{formatUsd(stats.largestWin)}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/30">
          <CardContent className="pt-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Worst Trade</p>
            <p className="mt-1 text-2xl font-semibold text-red-400">{formatUsd(stats.largestLoss)}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// Trade Row Component
function TradeRow({ trade, onSelect, showBot = false }: { trade: TradeHistoryEntry; onSelect: () => void; showBot?: boolean }) {
  const resolveTradePnl = useCallback((row: any) => {
    const toNum = (value: any) => {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    };
    const netRaw = row?.net_pnl ?? row?.netPnl;
    const grossRaw = row?.gross_pnl ?? row?.grossPnl;
    const feesRaw = row?.total_fees_usd ?? row?.totalFees ?? row?.fees ?? row?.fee;
    const fees = toNum(feesRaw);
    const net = netRaw != null ? toNum(netRaw) : (grossRaw != null ? toNum(grossRaw) - fees : toNum(row?.pnl));
    const gross = grossRaw != null ? toNum(grossRaw) : (netRaw != null ? net + fees : toNum(row?.pnl) + fees);
    return { net, gross, fees };
  }, []);
  const { net: netPnl, gross } = resolveTradePnl(trade);
  const pnlColor = netPnl >= 0 ? "text-emerald-400" : "text-red-400";
  const sideBadge = trade.side === "long" || trade.side === "buy" ? "success" : "warning";
  
  return (
    <div
      onClick={onSelect}
      className="group flex items-center gap-4 rounded-xl border border-white/5 bg-white/5 p-4 transition cursor-pointer hover:border-white/20 hover:bg-white/10"
    >
      {/* P&L Icon */}
      <div className={cn("flex h-10 w-10 items-center justify-center rounded-full", netPnl >= 0 ? "bg-emerald-500/10" : "bg-red-500/10")}>
        {netPnl >= 0 ? (
          <ArrowUpRight className={cn("h-5 w-5", pnlColor)} />
        ) : (
          <ArrowDownRight className={cn("h-5 w-5", pnlColor)} />
        )}
      </div>
      
      {/* Symbol & Side */}
      <div className="min-w-[140px]">
        <div className="flex items-center gap-2 flex-wrap">
          {showBot && (
            <Badge variant="outline" className="text-[10px] px-1.5 text-muted-foreground border-white/15">
              {(trade as any).bot_name || (trade as any).botName || (trade as any).bot_id || "—"}
            </Badge>
          )}
          <span className="font-semibold text-white">{trade.symbol}</span>
          <Badge variant={sideBadge} className="text-xs uppercase">
            {trade.side}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">{formatDateTime(trade.timestamp)}</p>
      </div>
      
      {/* Entry/Exit Prices */}
      <div className="hidden md:block min-w-[120px]">
        <p className="text-xs text-muted-foreground">Entry → Exit</p>
        <p className="text-sm text-white">
          {trade.entry_price?.toFixed(2)} → {trade.exit_price?.toFixed(2)}
        </p>
      </div>
      
      {/* Size */}
      <div className="hidden lg:block min-w-[80px]">
        <p className="text-xs text-muted-foreground">Size</p>
        <p className="text-sm text-white">{formatQuantity(trade.size)}</p>
      </div>
      
      {/* Fees */}
      <div className="hidden xl:block min-w-[70px] text-right">
        <p className="text-xs text-muted-foreground">Fees</p>
        <p className="text-sm text-yellow-400">-{formatUsd(trade.fees || 0)}</p>
      </div>
      
      {/* Net P&L */}
      <div className="min-w-[100px] text-right">
        <p className={cn("text-lg font-semibold", pnlColor)}>{formatUsd(netPnl)}</p>
        <p className="text-xs text-muted-foreground">gross: {formatUsd(gross)}</p>
      </div>
      
      {/* Exit Reason */}
      <div className="hidden xl:block min-w-[100px]">
        {getExitReasonBadge(trade.exitReason)}
      </div>
      
      {/* Decision Trace Indicator */}
      <div className="flex items-center gap-2">
        {trade.decisionTrace && (
          <Badge className="bg-primary/10 text-primary border-primary/30 text-xs">
            <Brain className="h-3 w-3 mr-1" />
            Trace
          </Badge>
        )}
        <Eye className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition" />
      </div>
    </div>
  );
}

// Trade Detail Panel
function TradeDetailPanel({ tradeId, onClose }: { tradeId: string; onClose: () => void }) {
  const { data, isLoading, error } = useTradeDetail(tradeId);
  const trade = data?.trade;
  
  if (isLoading) {
    return (
      <Card className="border-white/5 bg-black/30">
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }
  
  if (error || !trade) {
    return (
      <Card className="border-white/5 bg-black/30">
        <CardContent className="py-12 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-amber-400" />
          <p className="mt-2 text-sm text-muted-foreground">Failed to load trade details</p>
          <Button variant="ghost" size="sm" className="mt-4" onClick={onClose}>
            Close
          </Button>
        </CardContent>
      </Card>
    );
  }
  
  const resolveTradePnl = useCallback((row: any) => {
    const toNum = (value: any) => {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    };
    const netRaw = row?.net_pnl ?? row?.netPnl;
    const grossRaw = row?.gross_pnl ?? row?.grossPnl;
    const feesRaw = row?.total_fees_usd ?? row?.totalFees ?? row?.fees ?? row?.fee;
    const fees = toNum(feesRaw);
    const net = netRaw != null ? toNum(netRaw) : (grossRaw != null ? toNum(grossRaw) - fees : toNum(row?.pnl));
    const gross = grossRaw != null ? toNum(grossRaw) : (netRaw != null ? net + fees : toNum(row?.pnl) + fees);
    return { net, gross, fees };
  }, []);
  const { net: netPnl, gross, fees } = resolveTradePnl(trade);
  const pnlColor = netPnl >= 0 ? "text-emerald-400" : "text-red-400";
  
  return (
    <Card className="border-white/5 bg-black/30">
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-3">
            <span className="text-2xl">{trade.symbol}</span>
            <Badge variant={trade.side === "long" || trade.side === "buy" ? "success" : "warning"} className="uppercase">
              {trade.side}
            </Badge>
            {getExitReasonBadge(trade.exit?.reason)}
          </CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            {trade.formattedTimestamp}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Trade Summary */}
        <div className="grid gap-4 md:grid-cols-5">
          <div className="rounded-xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Entry Price</p>
            <p className="mt-1 text-xl font-semibold text-white">{formatUsd(trade.entryPrice)}</p>
          </div>
          <div className="rounded-xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Exit Price</p>
            <p className="mt-1 text-xl font-semibold text-white">{formatUsd(trade.exitPrice)}</p>
          </div>
          <div className="rounded-xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Size</p>
            <p className="mt-1 text-xl font-semibold text-white">{formatQuantity(trade.size)}</p>
          </div>
          <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-yellow-400/80">Fees</p>
            <p className="mt-1 text-xl font-semibold text-yellow-400">-{formatUsd(fees)}</p>
          </div>
          <div className={cn("rounded-xl border p-4", netPnl >= 0 ? "border-emerald-500/20 bg-emerald-500/5" : "border-red-500/20 bg-red-500/5")}>
            <p className={cn("text-xs uppercase tracking-[0.3em]", pnlColor)}>Net P&L</p>
            <p className={cn("mt-1 text-xl font-semibold", pnlColor)}>
              {formatUsd(netPnl)}
            </p>
            <p className="text-xs text-muted-foreground">gross: {formatUsd(gross)}</p>
          </div>
        </div>
        
        {/* Decision Details */}
        {trade.decision && (
          <div className="space-y-4">
            <h3 className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
              <Brain className="h-4 w-4" />
              Decision Details
            </h3>
            
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {trade.decision.profileId && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Profile</p>
                  <p className="text-sm font-medium text-white">{trade.decision.profileName || trade.decision.profileId}</p>
                </div>
              )}
              {trade.decision.strategyId && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Strategy</p>
                  <p className="text-sm font-medium text-white">{trade.decision.strategyName || trade.decision.strategyId}</p>
                </div>
              )}
              {trade.decision.signalConfidence !== undefined && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Signal Confidence</p>
                  <p className="text-sm font-medium text-white">{(trade.decision.signalConfidence * 100).toFixed(1)}%</p>
                </div>
              )}
              {trade.decision.totalLatencyMs !== undefined && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Decision Latency</p>
                  <p className="text-sm font-medium text-white">{trade.decision.totalLatencyMs?.toFixed(1)}ms</p>
                </div>
              )}
            </div>
            
            {/* Pipeline Stages */}
            {trade.decision.stagesExecuted && trade.decision.stagesExecuted.length > 0 && (
              <div className="rounded-xl border border-white/5 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground mb-3">Pipeline Stages</p>
                <div className="flex flex-wrap gap-2">
                  {trade.decision.stagesExecuted.map((stage, i) => (
                    <Badge key={i} className="bg-primary/10 text-primary border-primary/30">
                      {stage}
                      {trade.decision?.stageTiming?.[stage] && (
                        <span className="ml-1 opacity-70">({trade.decision.stageTiming[stage]}ms)</span>
                      )}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            
            {/* Stage Results */}
            {trade.decision.stageResults && Object.keys(trade.decision.stageResults).length > 0 && (
              <div className="rounded-xl border border-white/5 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground mb-3">Stage Results</p>
                <pre className="text-xs text-muted-foreground overflow-x-auto bg-black/30 p-3 rounded-lg">
                  {JSON.stringify(trade.decision.stageResults, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
        
        {/* Market Context */}
        {trade.marketContext && (
          <div className="space-y-4">
            <h3 className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Market Context
            </h3>
            <div className="grid gap-4 md:grid-cols-4">
              {trade.marketContext.regime && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Regime</p>
                  <p className="text-sm font-medium text-white capitalize">{trade.marketContext.regime}</p>
                </div>
              )}
              {trade.marketContext.trend && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Trend</p>
                  <p className="text-sm font-medium text-white capitalize">{trade.marketContext.trend}</p>
                </div>
              )}
              {trade.marketContext.volatility !== undefined && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Volatility</p>
                  <p className="text-sm font-medium text-white">{trade.marketContext.volatility}</p>
                </div>
              )}
              {trade.marketContext.session && (
                <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                  <p className="text-xs text-muted-foreground">Session</p>
                  <p className="text-sm font-medium text-white capitalize">{trade.marketContext.session}</p>
                </div>
              )}
            </div>
          </div>
        )}
        
        {/* Related Traces */}
        {trade.relatedTraces && trade.relatedTraces.length > 0 && (
          <div className="space-y-4">
            <h3 className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
              <Zap className="h-4 w-4" />
              Related Decision Traces ({trade.relatedTraces.length})
            </h3>
            <div className="space-y-2">
              {trade.relatedTraces.map((trace, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 px-4 py-2">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground">{formatTime(trace.timestamp)}</span>
                    <Badge variant="outline" className="text-xs">{trace.result}</Badge>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{trace.stages?.length || 0} stages</span>
                    <span>{trace.latencyMs?.toFixed(1)}ms</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function TradeHistoryPage() {
  const location = useLocation();
  const isBotScopeRoute = location.pathname.includes("/bots/");
  
  // Get scoping from scope store
  const { exchangeAccountId, botId, level: scopeLevel } = useScopeStore();
  
  const [filters, setFilters] = useState({
    symbol: "",
    side: "",
    startDate: "",
    endDate: "",
    limit: 100,
    offset: 0,
  });
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  
  // Build query params with scoping
  const { data, isLoading, isFetching } = useTradeHistory({
    ...filters,
    symbol: filters.symbol || undefined,
    side: filters.side || undefined,
    startDate: filters.startDate || undefined,
    endDate: filters.endDate || undefined,
    // Add scoping parameters
    exchangeAccountId: exchangeAccountId || undefined,
    botId: botId || undefined,
  });
  
  const trades = data?.trades || [];
  const stats = data?.stats;
  const pagination = data?.pagination;
  
  const hasFilters = filters.symbol || filters.side || filters.startDate || filters.endDate;
  
  const clearFilters = () => {
    setFilters({
      symbol: "",
      side: "",
      startDate: "",
      endDate: "",
      limit: 100,
      offset: 0,
    });
  };
  
  const nextPage = () => {
    if (pagination?.hasMore) {
      setFilters((f) => ({ ...f, offset: f.offset + f.limit }));
    }
  };
  
  const prevPage = () => {
    setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - f.limit) }));
  };
  
  // If a trade is selected, show the detail view
  if (selectedTradeId) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" onClick={() => setSelectedTradeId(null)}>
            <ChevronLeft className="h-4 w-4 mr-2" />
            Back to History
          </Button>
        </div>
        <TradeDetailPanel tradeId={selectedTradeId} onClose={() => setSelectedTradeId(null)} />
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Trade History</h1>
          <p className="text-sm text-muted-foreground">
            View all trades with full decision details and exit analysis
            {scopeLevel === "bot" && botId && (
              <span className="ml-2 text-primary">• Bot scoped</span>
            )}
            {scopeLevel === "exchange" && exchangeAccountId && (
              <span className="ml-2 text-primary">• Exchange scoped</span>
            )}
            {scopeLevel === "tenant" && (
              <span className="ml-2 text-muted-foreground/70">• All bots</span>
            )}
          </p>
        </div>
        {isFetching && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
      </div>
      
      {/* Stats Summary */}
      <StatsSummary stats={stats} />
      
      {/* Filters */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-2 w-40">
              <Label htmlFor="symbol" className="text-xs">Symbol</Label>
              <Input
                id="symbol"
                placeholder="e.g. BTC-USDT-SWAP"
                value={filters.symbol}
                onChange={(e) => setFilters({ ...filters, symbol: e.target.value, offset: 0 })}
              />
            </div>
            <div className="space-y-2 w-32">
              <Label htmlFor="side" className="text-xs">Side</Label>
              <select
                id="side"
                value={filters.side}
                onChange={(e) => setFilters({ ...filters, side: e.target.value, offset: 0 })}
                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
              >
                <option value="">All</option>
                <option value="long">Long</option>
                <option value="short">Short</option>
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </div>
            <div className="space-y-2 w-40">
              <Label htmlFor="startDate" className="text-xs">From</Label>
              <Input
                id="startDate"
                type="date"
                value={filters.startDate}
                onChange={(e) => setFilters({ ...filters, startDate: e.target.value, offset: 0 })}
              />
            </div>
            <div className="space-y-2 w-40">
              <Label htmlFor="endDate" className="text-xs">To</Label>
              <Input
                id="endDate"
                type="date"
                value={filters.endDate}
                onChange={(e) => setFilters({ ...filters, endDate: e.target.value, offset: 0 })}
              />
            </div>
            {hasFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="gap-2">
                <X className="h-4 w-4" />
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      
      {/* Trade List */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Trades ({pagination?.total || 0})
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={prevPage}
              disabled={filters.offset === 0}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground">
              {filters.offset + 1}–{Math.min(filters.offset + filters.limit, pagination?.total || 0)} of {pagination?.total || 0}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={nextPage}
              disabled={!pagination?.hasMore}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex h-64 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !botId && !exchangeAccountId ? (
            <div className="py-12 text-center">
              <BarChart3 className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <p className="mt-4 text-sm text-muted-foreground">Select a bot or exchange account to view trades</p>
              <p className="mt-1 text-xs text-muted-foreground/70">Use the scope selector in the header to choose a bot</p>
            </div>
          ) : trades.length === 0 ? (
            <div className="py-12 text-center">
              <BarChart3 className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <p className="mt-4 text-sm text-muted-foreground">No trades found</p>
              {hasFilters && (
                <Button variant="ghost" size="sm" onClick={clearFilters} className="mt-2">
                  Clear filters
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {trades.map((trade) => (
                <TradeRow
                  key={trade.id}
                  trade={trade}
                  showBot={!isBotScopeRoute}
                  onSelect={() => setSelectedTradeId(trade.id)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}


