/**
 * Pipeline Health Dashboard
 * 
 * Visualizes every layer of the trading engine with real-time status,
 * latency metrics, and throughput information.
 */

import { useState } from "react";
import { DashBar } from "../../components/DashBar";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  Pause,
  RefreshCw,
  Server,
  XCircle,
  Zap,
  Database,
  Brain,
  Shield,
  Send,
  GitCompare,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Separator } from "../../components/ui/separator";
import { cn, formatSymbolDisplay } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { usePipelineHealth, useResetKillSwitch, LayerHealth, WorkerHealth, SymbolStatus } from "../../lib/api/quant-hooks";
import { ShadowComparisonPanel } from "../../components/ShadowComparisonPanel";
import { getAuthUser } from "../../store/auth-store";
import { useBotId } from "../../store/scope-store";
import toast from "react-hot-toast";

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const formatLatency = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined || ms === 0) return "--";
  if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

const formatThroughput = (rate: number | null | undefined): string => {
  if (rate === null || rate === undefined || rate === 0) return "0/s";
  if (rate < 1) return `${(rate * 60).toFixed(1)}/min`;
  if (rate >= 1000) return `${(rate / 1000).toFixed(1)}k/s`;
  return `${rate.toFixed(0)}/s`;
};

const formatAge = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return "waiting";
  if (seconds < 1) return "just now";
  if (seconds < 60) return `${seconds.toFixed(0)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};

const formatPct = (value: number | null | undefined): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return `${value.toFixed(1)}%`;
};

const formatSigned = (value: number | null | undefined, digits = 2): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}`;
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case "healthy":
      return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
    case "degraded":
      return <AlertTriangle className="h-4 w-4 text-amber-500" />;
    case "down":
      return <XCircle className="h-4 w-4 text-red-500" />;
    case "idle":
      return <Pause className="h-4 w-4 text-slate-400" />;
    default:
      return <Clock className="h-4 w-4 text-slate-400" />;
  }
};

const getStatusColor = (status: string): string => {
  switch (status) {
    case "healthy":
      return "bg-emerald-500/10 text-emerald-600 border-emerald-500/30";
    case "degraded":
      return "bg-amber-500/10 text-amber-600 border-amber-500/30";
    case "down":
      return "bg-red-500/10 text-red-600 border-red-500/30";
    case "idle":
      return "bg-slate-500/10 text-slate-500 border-slate-500/30";
    default:
      return "bg-slate-500/10 text-slate-500 border-slate-500/30";
  }
};

const getLayerIcon = (name: string) => {
  switch (name) {
    case "ingest":
      return <Server className="h-5 w-5" />;
    case "feature":
      return <Database className="h-5 w-5" />;
    case "decision":
      return <Brain className="h-5 w-5" />;
    case "risk":
      return <Shield className="h-5 w-5" />;
    case "execution":
      return <Send className="h-5 w-5" />;
    case "reconciliation":
      return <GitCompare className="h-5 w-5" />;
    default:
      return <Activity className="h-5 w-5" />;
  }
};

// ============================================================================
// COMPONENTS
// ============================================================================

interface LayerCardProps {
  layer: LayerHealth;
  isExpanded: boolean;
  onToggle: () => void;
}

function LayerCard({ layer, isExpanded, onToggle }: LayerCardProps) {
  const hasBlockers = layer.blockers && layer.blockers.length > 0;
  const hasLatency = layer.latency_p99_ms > 0;
  const hasThroughput = layer.throughput_per_sec > 0;
  const isDecisionLayer = layer.name === "decision";
  const hasSymbolStatus = isDecisionLayer && layer.symbol_status && layer.symbol_status.length > 0;
  const symbolStatusSorted = hasSymbolStatus
    ? [...(layer.symbol_status || [])].sort((a, b) => a.symbol.localeCompare(b.symbol))
    : [];

  return (
    <div className="relative">
      {/* Connector Line */}
      <div className="absolute left-1/2 -translate-x-1/2 -top-4 h-4 w-0.5 bg-border" />
      
      <Card className={cn(
        "transition-all duration-200",
        layer.status === "down" && "border-red-500/50 bg-red-500/5",
        layer.status === "degraded" && "border-amber-500/50 bg-amber-500/5",
      )}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={cn(
                "p-2 rounded-lg",
                layer.status === "healthy" && "bg-emerald-500/10 text-emerald-600",
                layer.status === "degraded" && "bg-amber-500/10 text-amber-600",
                layer.status === "down" && "bg-red-500/10 text-red-600",
                layer.status === "idle" && "bg-slate-500/10 text-slate-500",
              )}>
                {getLayerIcon(layer.name)}
              </div>
              <div>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  {layer.display_name}
                  {isDecisionLayer && (
                    <span className="text-xs font-mono text-muted-foreground">
                      {formatThroughput(layer.throughput_per_sec)}
                    </span>
                  )}
                  <Badge variant="outline" className={cn("text-xs", getStatusColor(layer.status))}>
                    {getStatusIcon(layer.status)}
                    <span className="ml-1 capitalize">{layer.status}</span>
                  </Badge>
                </CardTitle>
                {hasSymbolStatus && (
                  <div className="mt-2 rounded-md border bg-background/40 overflow-x-auto">
                    <div className="min-w-[1180px]">
                      <div className="grid grid-cols-[140px_130px_minmax(260px,1fr)_220px_220px_130px_100px] gap-2 px-2 py-1.5 text-[10px] text-muted-foreground uppercase tracking-wide">
                        <div>Symbol</div>
                        <div>Status</div>
                        <div>Reason</div>
                        <div>Profile</div>
                        <div>Strategy</div>
                        <div>Session</div>
                        <div className="text-right">Last</div>
                      </div>
                      <Separator />
                      <div className="divide-y">
                        {symbolStatusSorted.map((sym) => (
                          <div
                            key={sym.symbol}
                            className="grid grid-cols-[140px_130px_minmax(260px,1fr)_220px_220px_130px_100px] gap-2 px-2 py-1.5 text-xs items-center"
                          >
                            <div className="font-mono whitespace-nowrap">{formatSymbolDisplay(sym.symbol)}</div>
                            <div className="whitespace-nowrap">
                              <Badge
                                variant="outline"
                                className={cn("text-[10px] px-1.5 py-0 h-5 font-mono", getStatusColor(sym.status))}
                              >
                                {getStatusIcon(sym.status)}
                                <span className="ml-1 capitalize">{sym.status}</span>
                              </Badge>
                            </div>
                            <div className="font-mono text-muted-foreground truncate">{sym.rejection_reason || "—"}</div>
                            <div className="font-mono truncate">{sym.profile_id || "—"}</div>
                            <div className="font-mono truncate">{sym.strategy_id || "—"}</div>
                            <div className="font-mono text-muted-foreground truncate">{sym.session || "—"}</div>
                            <div className="text-right text-muted-foreground whitespace-nowrap">
                              {sym.age_sec !== null ? formatAge(sym.age_sec) : "waiting"}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
                {layer.status === "idle" && layer.name === "execution" ? (
                  <CardDescription className="text-xs text-muted-foreground">
                    Waiting for trading signals
                  </CardDescription>
                ) : layer.age_sec !== null ? (
                  <CardDescription className="text-xs">
                    Last event: {formatAge(layer.age_sec)}
                  </CardDescription>
                ) : null}
              </div>
            </div>

            <div className="flex items-center gap-4">
              {/* Latency Stats */}
              {hasLatency && (
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">p99 latency</p>
                  <p className={cn(
                    "text-sm font-mono font-semibold",
                    layer.latency_p99_ms > 50 ? "text-amber-600" : "text-emerald-600"
                  )}>
                    {formatLatency(layer.latency_p99_ms)}
                  </p>
                </div>
              )}

              {/* Throughput (Decision moved inline next to title) */}
              {!isDecisionLayer && (
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">throughput</p>
                  <p className="text-sm font-mono font-semibold">
                    {formatThroughput(layer.throughput_per_sec)}
                  </p>
                </div>
              )}

              {/* Expand Button */}
              <Button
                variant="ghost"
                size="sm"
                onClick={onToggle}
                className="h-8 w-8 p-0"
              >
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </CardHeader>

        {/* Blockers Alert */}
        {hasBlockers && (
          <CardContent className="pt-0 pb-2">
            <div className="flex flex-wrap gap-2">
              {layer.blockers.map((blocker, idx) => (
                <Badge
                  key={idx}
                  variant="destructive"
                  className="text-xs font-mono"
                >
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  {blocker}
                </Badge>
              ))}
            </div>
          </CardContent>
        )}

        {/* Expanded Details */}
        {isExpanded && (
          <CardContent className="pt-0">
            <Separator className="my-3" />
            
            {/* Latency Breakdown */}
            {hasLatency && (
              <div className="grid grid-cols-4 gap-4 mb-4">
                <div className="p-2 rounded-md bg-muted/50 text-center">
                  <p className="text-xs text-muted-foreground">p50</p>
                  <p className="text-sm font-mono font-semibold text-emerald-600">
                    {formatLatency(layer.latency_p50_ms)}
                  </p>
                </div>
                <div className="p-2 rounded-md bg-muted/50 text-center">
                  <p className="text-xs text-muted-foreground">p95</p>
                  <p className="text-sm font-mono font-semibold text-amber-600">
                    {formatLatency(layer.latency_p95_ms)}
                  </p>
                </div>
                <div className="p-2 rounded-md bg-muted/50 text-center">
                  <p className="text-xs text-muted-foreground">p99</p>
                  <p className={cn(
                    "text-sm font-mono font-semibold",
                    layer.latency_p99_ms > 50 ? "text-red-600" : "text-emerald-600"
                  )}>
                    {formatLatency(layer.latency_p99_ms)}
                  </p>
                </div>
                <div className="p-2 rounded-md bg-muted/50 text-center">
                  <p className="text-xs text-muted-foreground">processed</p>
                  <p className="text-sm font-mono font-semibold">
                    {layer.events_processed.toLocaleString()}
                  </p>
                </div>
              </div>
            )}

            {/* Workers */}
            {layer.workers && layer.workers.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">
                  Workers
                </p>
                <div className="space-y-1">
                  {layer.workers.map((worker, idx) => (
                    <WorkerRow key={idx} worker={worker} />
                  ))}
                </div>
              </div>
            )}

            {/* Rejection Stats */}
            {layer.events_rejected > 0 && (
              <div className="mt-3 p-2 rounded-md bg-amber-500/10 border border-amber-500/30">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-amber-700">Events Rejected</span>
                  <span className="font-mono font-semibold text-amber-700">
                    {layer.events_rejected.toLocaleString()}
                  </span>
                </div>
                <Progress 
                  value={(layer.events_rejected / (layer.events_processed + layer.events_rejected)) * 100} 
                  className="h-1 mt-1 bg-amber-200"
                />
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Arrow Down to Next Layer */}
      <div className="flex justify-center py-2">
        <ArrowDown className="h-5 w-5 text-muted-foreground/50" />
      </div>
    </div>
  );
}

function WorkerRow({ worker }: { worker: WorkerHealth }) {
  const hasError = worker.error_message && worker.error_message.length > 0;
  const isDown = worker.status === "down";
  const isDegraded = worker.status === "degraded";
  const hasMdsQuality = worker.mds_quality_score !== undefined && worker.mds_quality_score !== null;
  const hasL1Rate = worker.orderbook_event_rate_l1_eps !== undefined && worker.orderbook_event_rate_l1_eps !== null;
  const hasL2Rate = worker.orderbook_event_rate_l2_eps !== undefined && worker.orderbook_event_rate_l2_eps !== null;
  
  return (
    <div className={cn(
      "flex items-center justify-between py-1.5 px-2 rounded-md",
      isDown && "bg-red-500/10 border border-red-500/30",
      isDegraded && !isDown && "bg-amber-500/10 border border-amber-500/30",
      !isDown && !isDegraded && "hover:bg-muted/50"
    )}>
      <div className="flex items-center gap-2 min-w-0">
        {getStatusIcon(worker.status)}
        <div className="min-w-0">
          <span className="text-sm">{worker.name}</span>
          {hasError && (
            <div className="text-xs text-red-600 font-mono truncate">
              ⚠ {worker.error_message}
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-4 text-xs text-muted-foreground flex-shrink-0">
        {worker.latency_p99_ms > 0 && (
          <span className="font-mono">{formatLatency(worker.latency_p99_ms)}</span>
        )}
        {worker.throughput_per_sec !== undefined && worker.throughput_per_sec !== null && (
          <span className={cn(
            "font-mono",
            worker.throughput_per_sec === 0 && isDegraded && "text-amber-600"
          )}>
            {formatThroughput(worker.throughput_per_sec)}
          </span>
        )}
        {hasMdsQuality && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <span className={cn(
                  "font-mono",
                  (worker.mds_quality_score ?? 0) < 60 ? "text-red-600" : (worker.mds_quality_score ?? 0) < 80 ? "text-amber-600" : "text-emerald-600"
                )}>
                  Q:{(worker.mds_quality_score ?? 0).toFixed(1)}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                MDS quality score (0-100): freshness + integrity + throughput
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
        {(hasL1Rate || hasL2Rate) && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <span className="font-mono text-muted-foreground">
                  L1/L2 {hasL1Rate ? (worker.orderbook_event_rate_l1_eps ?? 0).toFixed(1) : "--"}/{hasL2Rate ? (worker.orderbook_event_rate_l2_eps ?? 0).toFixed(1) : "--"}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Avg orderbook events/sec (L1 and L2)
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
        {worker.last_event_ts && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <span className="font-mono text-muted-foreground">
                  {formatAge((Date.now() / 1000) - worker.last_event_ts)}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Last event at {new Date(worker.last_event_ts * 1000).toLocaleTimeString()}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function PipelineHealthPage() {
  const botId = useBotId();
  const { data, isLoading, error, refetch, dataUpdatedAt } = usePipelineHealth(5000);
  const resetKillSwitch = useResetKillSwitch();
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());

  const handleOverrideKillSwitch = async () => {
    const confirmed = window.confirm(
      "Override kill switch and re-enable trading for this bot runtime?"
    );
    if (!confirmed) return;
    const user = getAuthUser();
    const operatorId = user?.email || user?.username || user?.id || "dashboard_override";
    try {
      await resetKillSwitch.mutateAsync(operatorId);
      toast.success("Kill switch override applied");
      await refetch();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to override kill switch";
      toast.error(message);
    }
  };

  const toggleLayer = (name: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const expandAll = () => {
    if (data?.layers) {
      setExpandedLayers(new Set(data.layers.map((l) => l.name)));
    }
  };

  const collapseAll = () => {
    setExpandedLayers(new Set());
  };

  if (!botId) {
    return (
      <div className="flex flex-col min-h-screen bg-background">
        <DashBar />
        <main className="flex-1 p-6">
          <Card className="max-w-md mx-auto">
            <CardContent className="pt-6 text-center">
              <Pause className="h-12 w-12 text-slate-400 mx-auto mb-4" />
              <h2 className="text-lg font-semibold mb-2">No Bot Selected</h2>
              <p className="text-sm text-muted-foreground">
                Select a bot scope before viewing pipeline health. This page no longer falls back to a default bot.
              </p>
            </CardContent>
          </Card>
        </main>
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <div className="flex flex-col min-h-screen bg-background">
        <DashBar />
        <main className="flex-1 p-6">
          <div className="flex items-center justify-center h-96">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        </main>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col min-h-screen bg-background">
        <DashBar />
        <main className="flex-1 p-6">
          <Card className="max-w-md mx-auto">
            <CardContent className="pt-6 text-center">
              <XCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
              <h2 className="text-lg font-semibold mb-2">Failed to Load Pipeline Health</h2>
              <p className="text-sm text-muted-foreground mb-4">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
              <Button onClick={() => refetch()}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Retry
              </Button>
            </CardContent>
          </Card>
        </main>
      </div>
    );
  }

  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "never";

  return (
    <TooltipProvider>
      <div className="flex flex-col min-h-screen bg-background">
        <DashBar />
        
        <main className="flex-1 px-3 py-6 md:px-4 lg:px-6">
          <div className="max-w-7xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                  <Activity className="h-6 w-6" />
                  Pipeline Health
                </h1>
                <p className="text-sm text-muted-foreground mt-1">
                  Real-time status of all trading engine layers
                </p>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  Updated: {lastUpdated}
                </span>
                <Button variant="outline" size="sm" onClick={() => refetch()}>
                  <RefreshCw className="h-4 w-4 mr-1" />
                  Refresh
                </Button>
                <Button variant="outline" size="sm" onClick={expandAll}>
                  Expand All
                </Button>
                <Button variant="outline" size="sm" onClick={collapseAll}>
                  Collapse
                </Button>
              </div>
            </div>

            {/* Overall Status Card */}
            {data && (
              <Card className={cn(
                "mb-6",
                data.overall_status === "down" && "border-red-500/50 bg-red-500/5",
                data.overall_status === "degraded" && "border-amber-500/50 bg-amber-500/5",
                data.overall_status === "healthy" && "border-emerald-500/50 bg-emerald-500/5",
              )}>
                <CardContent className="pt-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className={cn(
                        "p-3 rounded-xl",
                        data.overall_status === "healthy" && "bg-emerald-500/20 text-emerald-600",
                        data.overall_status === "degraded" && "bg-amber-500/20 text-amber-600",
                        data.overall_status === "down" && "bg-red-500/20 text-red-600",
                      )}>
                        <Zap className="h-8 w-8" />
                      </div>
                      <div>
                        <h2 className="text-xl font-bold capitalize">{data.overall_status}</h2>
                        <p className="text-sm text-muted-foreground">
                          {data.kill_switch_active ? (
                            <span className="inline-flex items-center gap-2">
                              <span className="text-red-600 font-medium">Kill Switch ACTIVE</span>
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={handleOverrideKillSwitch}
                                disabled={resetKillSwitch.isPending}
                                className="h-7 px-2 text-xs"
                              >
                                {resetKillSwitch.isPending ? (
                                  <>
                                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                    Overriding...
                                  </>
                                ) : (
                                  "Override"
                                )}
                              </Button>
                            </span>
                          ) : (
                            "Trading pipeline operational"
                          )}
                        </p>
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-6 text-center">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-help">
                            <p className="text-2xl font-bold font-mono">
                              {formatLatency(data.tick_to_execution_p99_ms)}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              tick→exec p99
                            </p>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>End-to-end latency from market tick to execution intent</p>
                        </TooltipContent>
                      </Tooltip>

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-help">
                            <p className="text-2xl font-bold font-mono">
                              {data.decisions_per_minute.toFixed(1)}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              decisions/min
                            </p>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Trading decisions accepted per minute</p>
                        </TooltipContent>
                      </Tooltip>

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-help">
                            <p className="text-2xl font-bold font-mono">
                              {data.fills_per_hour.toFixed(1)}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              fills/hour
                            </p>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Order fills executed per hour</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {data?.prediction && (
              <Card className="mb-6">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Brain className="h-4 w-4" />
                    Prediction Mode
                  </CardTitle>
                  <CardDescription>
                    Active provider routing and ONNX gate status
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className={cn("font-mono", getStatusColor(
                      data.prediction.onnx_status === "active" ? "healthy"
                        : data.prediction.onnx_status === "partial" ? "degraded"
                        : data.prediction.onnx_status === "blocked" ? "down"
                        : "idle",
                    ))}>
                      ONNX: {data.prediction.onnx_status}
                    </Badge>
                    <Badge variant="outline" className="font-mono">
                      Mode: {data.prediction.mode}
                    </Badge>
                    {data.prediction.moe_enabled && (
                      <Badge variant="outline" className="font-mono">
                        Experts: {data.prediction.moe_experts_with_calibration}/{data.prediction.moe_experts_total}
                      </Badge>
                    )}
                    <Badge variant="outline" className="font-mono">
                      Primary: {data.prediction.live_primary_source}
                    </Badge>
                    <Badge variant="outline" className="font-mono">
                      Gate: {data.prediction.score_gate_mode}
                    </Badge>
                    <Badge variant="outline" className="font-mono">
                      Snapshot: {data.prediction.score_snapshot_provider}/{data.prediction.score_snapshot_status}
                    </Badge>
                    {data.prediction.score_snapshot_age_sec !== null && (
                      <Badge variant="outline" className="font-mono">
                        Updated {formatAge(data.prediction.score_snapshot_age_sec)}
                      </Badge>
                    )}
                    {data.prediction.moe_enabled && data.prediction.moe_latest_calibration_age_sec !== null && (
                      <Badge variant="outline" className="font-mono">
                        Expert cal {formatAge(data.prediction.moe_latest_calibration_age_sec)}
                      </Badge>
                    )}
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <div className="rounded border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Live ONNX share</p>
                      <p className="font-mono font-semibold">{formatPct(data.prediction.onnx_live_share_pct)}</p>
                    </div>
                    <div className="rounded border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Fallback rate</p>
                      <p className="font-mono font-semibold">{formatPct(data.prediction.fallback_rate_pct)}</p>
                    </div>
                    <div className="rounded border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Live source mix</p>
                      <p className="font-mono text-xs truncate">
                        {Object.entries(data.prediction.live_source_counts)
                          .map(([k, v]) => `${k}:${v}`)
                          .join("  ") || "—"}
                      </p>
                    </div>
                    <div className="rounded border px-3 py-2">
                      <p className="text-xs text-muted-foreground">Gate status mix</p>
                      <p className="font-mono text-xs truncate">
                        {Object.entries(data.prediction.gate_status_counts)
                          .map(([k, v]) => `${k}:${v}`)
                          .join("  ") || "—"}
                      </p>
                    </div>
                  </div>

                  {data.prediction.moe_enabled && data.prediction.moe_expert_status.length > 0 && (
                    <div className="rounded border bg-background/40">
                      <div className="grid grid-cols-12 gap-2 px-2 py-1.5 text-[10px] text-muted-foreground uppercase tracking-wide">
                        <div className="col-span-3">Expert</div>
                        <div className="col-span-3">Source</div>
                        <div className="col-span-2 text-right">Classes</div>
                        <div className="col-span-4 text-right">Calibration age</div>
                      </div>
                      <Separator />
                      <div className="divide-y">
                        {data.prediction.moe_expert_status.map((item) => (
                          <div key={item.id} className="grid grid-cols-12 gap-2 px-2 py-1.5 text-xs font-mono">
                            <div className="col-span-3">{item.id}</div>
                            <div className="col-span-3">{item.calibration_source}</div>
                            <div className="col-span-2 text-right">{item.calibrated_classes}</div>
                            <div className="col-span-4 text-right">
                              {item.age_sec !== null ? formatAge(item.age_sec) : "--"}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {data.prediction.symbols.length > 0 && (
                    <div className="rounded border bg-background/40">
                      <div className="grid grid-cols-12 gap-2 px-2 py-1.5 text-[10px] text-muted-foreground uppercase tracking-wide">
                        <div className="col-span-2">Symbol</div>
                        <div className="col-span-2">Status</div>
                        <div className="col-span-2 text-right">Samples</div>
                        <div className="col-span-2 text-right">ML</div>
                        <div className="col-span-2 text-right">Exact</div>
                        <div className="col-span-2 text-right">ECE</div>
                      </div>
                      <Separator />
                      <div className="divide-y">
                        {data.prediction.symbols.map((item) => (
                          <div key={item.symbol} className="grid grid-cols-12 gap-2 px-2 py-1.5 text-xs font-mono">
                            <div className="col-span-2">{formatSymbolDisplay(item.symbol)}</div>
                            <div className="col-span-2">{item.status}</div>
                            <div className="col-span-2 text-right">{item.samples}</div>
                            <div className="col-span-2 text-right">{item.ml_score?.toFixed(1) ?? "--"}</div>
                            <div className="col-span-2 text-right">
                              {item.exact_accuracy !== null ? formatPct(item.exact_accuracy * 100) : "--"}
                            </div>
                            <div className="col-span-2 text-right">
                              {item.ece_top1 !== null ? formatPct(item.ece_top1 * 100) : "--"}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {data.prediction.directional_canary && (
                    <div className="rounded border bg-background/40 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                            Directional Canary (Close Fills)
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            Source: canonical close-order events (deduped by order identity)
                          </p>
                        </div>
                        <Badge variant="outline" className="font-mono text-xs">
                          Samples: {data.prediction.directional_canary.samples_close_fills}
                        </Badge>
                      </div>
                      {data.prediction.directional_canary.long.expectancy_net_pnl !== null &&
                        data.prediction.directional_canary.short.expectancy_net_pnl !== null &&
                        data.prediction.directional_canary.long.expectancy_net_pnl < 0 &&
                        data.prediction.directional_canary.short.expectancy_net_pnl < 0 && (
                          <div className="mb-2 flex items-start gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-700">
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span>Both long and short expectancy are negative. Keep size constrained and tune gating before expansion.</span>
                          </div>
                        )}
                      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                        <div className="rounded border px-3 py-2">
                          <p className="text-xs text-muted-foreground">Long win rate</p>
                          <p className="font-mono font-semibold">
                            {data.prediction.directional_canary.long.win_rate === null
                              ? "--"
                              : formatPct(data.prediction.directional_canary.long.win_rate * 100)}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Exp: {formatSigned(data.prediction.directional_canary.long.expectancy_net_pnl, 4)} net
                          </p>
                          <p className="text-xs text-muted-foreground">
                            PnL samples: {data.prediction.directional_canary.long.pnl_samples}
                          </p>
                        </div>
                        <div className="rounded border px-3 py-2">
                          <p className="text-xs text-muted-foreground">Short win rate</p>
                          <p className="font-mono font-semibold">
                            {data.prediction.directional_canary.short.win_rate === null
                              ? "--"
                              : formatPct(data.prediction.directional_canary.short.win_rate * 100)}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            Exp: {formatSigned(data.prediction.directional_canary.short.expectancy_net_pnl, 4)} net
                          </p>
                          <p className="text-xs text-muted-foreground">
                            PnL samples: {data.prediction.directional_canary.short.pnl_samples}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  {data.prediction.rolling_performance && (
                    <div className="rounded border bg-background/40 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                            Rolling Source Performance
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            Realized close-fill net PnL by prediction source (1h/6h windows)
                          </p>
                        </div>
                      </div>
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        {(["1h", "6h"] as const).map((windowKey) => {
                          const windowStats = data.prediction?.rolling_performance?.[windowKey];
                          if (!windowStats) {
                            return (
                              <div key={windowKey} className="rounded border px-3 py-2">
                                <p className="text-xs text-muted-foreground">{windowKey}</p>
                                <p className="text-xs text-muted-foreground">No data</p>
                              </div>
                            );
                          }
                          const bySource = Object.entries(windowStats.by_source || {}).sort(
                            (a, b) => (b[1]?.n || 0) - (a[1]?.n || 0),
                          );
                          return (
                            <div key={windowKey} className="rounded border px-3 py-2">
                              <div className="mb-2 flex items-center justify-between">
                                <p className="text-xs font-medium text-muted-foreground">{windowKey}</p>
                                <span className="text-[11px] font-mono text-muted-foreground">
                                  n={windowStats.total?.n ?? 0}
                                </span>
                              </div>
                              <div className="mb-2 grid grid-cols-3 gap-2 text-xs">
                                <div>
                                  <p className="text-muted-foreground">Win</p>
                                  <p className="font-mono">
                                    {windowStats.total?.win_rate !== null && windowStats.total?.win_rate !== undefined
                                      ? formatPct((windowStats.total.win_rate || 0) * 100)
                                      : "--"}
                                  </p>
                                </div>
                                <div>
                                  <p className="text-muted-foreground">Avg</p>
                                  <p className="font-mono">{formatSigned(windowStats.total?.avg_net_pnl, 4)}</p>
                                </div>
                                <div>
                                  <p className="text-muted-foreground">Sum</p>
                                  <p className="font-mono">{formatSigned(windowStats.total?.sum_net_pnl, 2)}</p>
                                </div>
                              </div>
                              <div className="space-y-1">
                                {bySource.slice(0, 4).map(([source, stats]) => (
                                  <div key={source} className="flex items-center justify-between text-[11px] font-mono">
                                    <span className="truncate pr-2">{source}</span>
                                    <span>
                                      n={stats?.n ?? 0} | win{" "}
                                      {stats?.win_rate !== null && stats?.win_rate !== undefined
                                        ? formatPct((stats.win_rate || 0) * 100)
                                        : "--"}{" "}
                                      | avg {formatSigned(stats?.avg_net_pnl, 3)}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {data.prediction.entry_quality_readiness && (
                    <div className="rounded border bg-background/40 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                            Entry Quality Readiness
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            Feed/feature health and entry gate outcomes over the recent sample window
                          </p>
                        </div>
                        <Badge variant={data.prediction.entry_quality_readiness.ready ? "default" : "destructive"} className="font-mono text-xs">
                          {data.prediction.entry_quality_readiness.ready ? "Ready" : "Not Ready"}
                        </Badge>
                      </div>
                      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                        <div className="rounded border px-3 py-2">
                          <p className="text-xs text-muted-foreground">Green readiness</p>
                          <p className="font-mono font-semibold">{formatPct(data.prediction.entry_quality_readiness.green_pct)}</p>
                          <p className="text-xs text-muted-foreground">
                            Samples: {data.prediction.entry_quality_readiness.sample_count}
                          </p>
                        </div>
                        <div className="rounded border px-3 py-2">
                          <p className="text-xs text-muted-foreground">Gate blocked</p>
                          <p className="font-mono font-semibold">{formatPct(data.prediction.entry_quality_readiness.blocked_pct)}</p>
                          <p className="text-xs text-muted-foreground">
                            Target max: {formatPct(data.prediction.entry_quality_readiness.thresholds.max_blocked_pct)}
                          </p>
                        </div>
                        <div className="rounded border px-3 py-2">
                          <p className="text-xs text-muted-foreground">Gate fallback</p>
                          <p className="font-mono font-semibold">{formatPct(data.prediction.entry_quality_readiness.fallback_pct)}</p>
                          <p className="text-xs text-muted-foreground">
                            Decision samples: {data.prediction.entry_quality_readiness.decision_sample_count}
                          </p>
                        </div>
                      </div>

                      {data.prediction.entry_quality_readiness.blockers.length > 0 && (
                        <div className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-700">
                          Blockers: {data.prediction.entry_quality_readiness.blockers.join(", ")}
                        </div>
                      )}

                      {data.prediction.entry_quality_readiness.top_blocking_reasons.length > 0 && (
                        <div className="mt-2 rounded border bg-background/50 p-2">
                          <p className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">
                            Top Blocking Reasons
                          </p>
                          <div className="grid grid-cols-1 gap-1">
                            {data.prediction.entry_quality_readiness.top_blocking_reasons.slice(0, 5).map((item) => (
                              <div key={item.reason} className="flex items-center justify-between text-xs font-mono">
                                <span className="truncate pr-2">{item.reason}</span>
                                <span>{item.count}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* Shadow Prediction Health */}
            <div className="mb-6">
              <ShadowComparisonPanel />
            </div>

            {/* Pipeline Flow */}
            {data && (
              <div className="space-y-0 pt-4">
                {data.layers.map((layer) => (
                  <LayerCard
                    key={layer.name}
                    layer={layer}
                    isExpanded={expandedLayers.has(layer.name)}
                    onToggle={() => toggleLayer(layer.name)}
                  />
                ))}

                {/* End Marker */}
                <div className="text-center pt-4">
                  <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted text-muted-foreground text-sm">
                    <CheckCircle2 className="h-4 w-4" />
                    End of Pipeline
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
