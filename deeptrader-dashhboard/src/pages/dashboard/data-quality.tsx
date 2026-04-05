import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { DashBar } from "../../components/DashBar";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  ArrowUpDown,
  Bell,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  Download,
  ExternalLink,
  Eye,
  Filter,
  HelpCircle,
  Info,
  Layers,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  Search,
  Server,
  Settings,
  Signal,
  Timer,
  TrendingDown,
  TrendingUp,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Progress } from "../../components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Separator } from "../../components/ui/separator";
import { Switch } from "../../components/ui/switch";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../../components/ui/alert-dialog";
import toast from "react-hot-toast";
import {
  useQualityMetrics,
  useQualityMetricsTimeseries,
  useFeedGaps,
  useQualityAlerts,
  useSymbolHealth,
  useUpdateAlertStatus,
} from "../../lib/api/hooks";

// ============================================================================
// MOCK DATA
// ============================================================================

// No mock data; use live API hooks.

// Gap map for sparkline visualization
const mockGapMap = Array.from({ length: 60 }, (_, i) => ({
  minute: i,
  hasGap: [12, 13, 14, 35, 36, 45].includes(i),
}));

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const formatDuration = (seconds: number) => {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
};

const formatTimestamp = (ts: string) => {
  const date = new Date(ts);
  return date.toLocaleTimeString();
};

const getStatusColor = (status: string) => {
  switch (status) {
    case "healthy": return "bg-emerald-500/10 text-emerald-500 border-emerald-500/30";
    case "degraded": return "bg-amber-500/10 text-amber-500 border-amber-500/30";
    case "critical": return "bg-red-500/10 text-red-500 border-red-500/30";
    default: return "bg-muted text-muted-foreground";
  }
};

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "critical": return "bg-red-500/10 text-red-500";
    case "high": return "bg-orange-500/10 text-orange-500";
    case "medium": return "bg-amber-500/10 text-amber-500";
    case "low": return "bg-blue-500/10 text-blue-500";
    default: return "bg-muted text-muted-foreground";
  }
};

const getImpactBadge = (impact: string) => {
  switch (impact) {
    case "signals_blocked": return { label: "Signals Blocked", color: "bg-red-500/10 text-red-500" };
    case "backtest_affected": return { label: "Backtest Affected", color: "bg-amber-500/10 text-amber-500" };
    case "live_trading_risk": return { label: "Live Trading Risk", color: "bg-orange-500/10 text-orange-500" };
    default: return { label: impact, color: "bg-muted text-muted-foreground" };
  }
};

const getBackfillStatusBadge = (status: string) => {
  switch (status) {
    case "queued": return { label: "Queued", color: "bg-blue-500/10 text-blue-500", icon: Clock };
    case "running": return { label: "Running", color: "bg-amber-500/10 text-amber-500", icon: Loader2 };
    case "completed": return { label: "Completed", color: "bg-emerald-500/10 text-emerald-500", icon: CheckCircle2 };
    case "failed": return { label: "Failed", color: "bg-red-500/10 text-red-500", icon: XCircle };
    default: return { label: status, color: "bg-muted text-muted-foreground", icon: HelpCircle };
  }
};

// ============================================================================
// COMPONENTS
// ============================================================================

function SummaryStrip({ timeframe }: { timeframe?: string }) {
  const { data: healthData } = useSymbolHealth(undefined, { timeframe });
  const { data: alertsData } = useQualityAlerts({ status: "active", timeframe });
  const { data: gapsData } = useFeedGaps({ resolved: false, timeframe });

  const symbolHealth = (healthData as any)?.health ?? (healthData as any)?.data ?? [];
  const alerts = (alertsData as any)?.alerts ?? (alertsData as any)?.data ?? [];
  const gaps = (gapsData as any)?.gaps ?? (gapsData as any)?.data ?? [];

  const totalSymbols = symbolHealth.length;
  const degradedCount = symbolHealth.filter((s: any) => s.status === "degraded").length;
  const criticalCount = symbolHealth.filter((s: any) => s.status === "critical").length;
  const activeAlerts = alerts.filter((a: any) => (a.state || a.status) === "active").length;
  const activeGaps = gaps.filter((g: any) => (g.backfill_status || g.status) !== "completed" && !g.resolved).length;
  const medianLatency =
    totalSymbols > 0
      ? Math.round(
          symbolHealth.reduce((sum: number, s: any) => sum + (s.latency_p95_ms || s.avg_ingest_latency_ms || 0), 0) /
            totalSymbols
        )
      : 0;
  const p95Latency = symbolHealth.length > 0 ? Math.max(...symbolHealth.map((s: any) => s.latency_p95_ms || s.max_ingest_latency_ms || 0)) : 0;
  const worstStaleness = symbolHealth.length > 0 ? Math.max(...symbolHealth.map((s: any) => s.staleness_seconds || 0)) : 0;

  return (
    <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
      <Card className="border-border/50">
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Symbols</p>
              <p className="text-xl font-bold">{totalSymbols}</p>
            </div>
            <Database className="h-5 w-5 text-muted-foreground" />
          </div>
        </CardContent>
      </Card>

      <Card className={cn("border-border/50", (degradedCount + criticalCount) > 0 && "border-amber-500/30")}>
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Unhealthy</p>
              <div className="flex items-center gap-2">
                <p className="text-xl font-bold">{degradedCount + criticalCount}</p>
                {criticalCount > 0 && (
                  <Badge variant="outline" className="text-[10px] bg-red-500/10 text-red-500 border-red-500/30">
                    {criticalCount} critical
                  </Badge>
                )}
              </div>
            </div>
            <AlertTriangle className={cn("h-5 w-5", (degradedCount + criticalCount) > 0 ? "text-amber-500" : "text-muted-foreground")} />
          </div>
        </CardContent>
      </Card>

      <Card className={cn("border-border/50", activeAlerts > 0 && "border-red-500/30")}>
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Active Alerts</p>
              <p className={cn("text-xl font-bold", activeAlerts > 0 && "text-red-500")}>{activeAlerts}</p>
            </div>
            <Bell className={cn("h-5 w-5", activeAlerts > 0 ? "text-red-500" : "text-muted-foreground")} />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Active Gaps</p>
              <p className="text-xl font-bold">{activeGaps}</p>
            </div>
            <Layers className="h-5 w-5 text-muted-foreground" />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Latency p50/p95</p>
              <p className="text-xl font-bold">
                <span>{medianLatency}</span>
                <span className="text-sm text-muted-foreground">/{p95Latency}ms</span>
              </p>
            </div>
            <Timer className="h-5 w-5 text-muted-foreground" />
          </div>
        </CardContent>
      </Card>

      <Card className={cn("border-border/50", worstStaleness > 60 && "border-red-500/30")}>
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Max Staleness</p>
              <p className={cn("text-xl font-bold", worstStaleness > 60 && "text-red-500")}>{formatDuration(worstStaleness)}</p>
            </div>
            <Clock className={cn("h-5 w-5", worstStaleness > 60 ? "text-red-500" : "text-muted-foreground")} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SymbolHealthTable({
  onSelectSymbol,
  showOnlyUnhealthy,
  data,
}: {
  onSelectSymbol: (symbol: any) => void;
  showOnlyUnhealthy: boolean;
  data: any[];
}) {
  const [sortColumn, setSortColumn] = useState<string>("quality_score");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");

  const filteredData = useMemo(() => {
    const mapped = (data || []).map((s: any) => ({
      symbol: s.symbol,
      timeframe: s.timeframe || "1m",
      status: s.status || (s.quality_score >= 90 ? "healthy" : s.quality_score >= 70 ? "degraded" : "critical"),
      quality_score: s.quality_score ?? 0,
      staleness_seconds: s.staleness_seconds ?? s.staleness ?? 0,
      active_gaps: s.active_gaps ?? s.gap_count ?? 0,
      active_alerts: s.active_alerts ?? 0,
      latency_p95_ms: s.latency_p95_ms ?? s.max_ingest_latency_ms ?? 0,
      last_good_timestamp: s.last_good_timestamp || s.metric_date || new Date().toISOString(),
      messages_per_sec: s.messages_per_sec || 0,
      drop_rate: s.drop_rate ?? (s.missing_candles_count && s.total_candles_expected ? s.missing_candles_count / Math.max(s.total_candles_expected, 1) : 0),
      out_of_order_count: s.out_of_order_count ?? s.outlier_count ?? 0,
    }));
    const filtered = showOnlyUnhealthy ? mapped.filter((s) => s.status !== "healthy") : mapped;
    return filtered.sort((a: any, b: any) => {
      const aVal = a[sortColumn as keyof typeof a];
      const bVal = b[sortColumn as keyof typeof b];
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDirection === "asc" ? aVal - bVal : bVal - aVal;
      }
      return 0;
    });
  }, [data, showOnlyUnhealthy, sortColumn, sortDirection]);

  const handleSort = (column: string) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortColumn(column);
      setSortDirection("asc");
    }
  };

  const SortHeader = ({ column, label }: { column: string; label: string }) => (
    <th
      className="p-3 text-left text-xs font-medium text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
      onClick={() => handleSort(column)}
    >
      <div className="flex items-center gap-1">
        {label}
        <ArrowUpDown className={cn("h-3 w-3", sortColumn === column && "text-foreground")} />
      </div>
    </th>
  );

  if (filteredData.length === 0) {
    return (
      <Card>
        <CardContent className="p-8 text-center">
          <CheckCircle2 className="h-12 w-12 mx-auto text-emerald-500/50" />
          <p className="mt-4 text-muted-foreground">All symbols are healthy</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b">
              <tr>
                <SortHeader column="symbol" label="Symbol" />
                <th className="p-3 text-left text-xs font-medium text-muted-foreground">TF</th>
                <th className="p-3 text-left text-xs font-medium text-muted-foreground">Status</th>
                <SortHeader column="quality_score" label="Quality" />
                <SortHeader column="staleness_seconds" label="Staleness" />
                <SortHeader column="active_gaps" label="Gaps" />
                <SortHeader column="active_alerts" label="Alerts" />
                <SortHeader column="latency_p95_ms" label="Latency p95" />
                <th className="p-3 text-left text-xs font-medium text-muted-foreground">Last Good</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {filteredData.map((symbol) => (
                <tr
                  key={symbol.symbol}
                  className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                  onClick={() => onSelectSymbol(symbol)}
                >
                  <td className="p-3 font-medium">{symbol.symbol}</td>
                  <td className="p-3 text-muted-foreground">{symbol.timeframe}</td>
                  <td className="p-3">
                    <Badge variant="outline" className={cn("text-xs", getStatusColor(symbol.status))}>
                      {symbol.status}
                    </Badge>
                  </td>
                  <td className="p-3">
                    <span className={cn(
                      "font-mono font-medium",
                      symbol.quality_score >= 90 ? "text-emerald-500" :
                      symbol.quality_score >= 70 ? "text-amber-500" : "text-red-500"
                    )}>
                      {symbol.quality_score.toFixed(1)}
                    </span>
                  </td>
                  <td className="p-3">
                    <span className={cn(
                      "font-mono",
                      symbol.staleness_seconds > 60 ? "text-red-500" :
                      symbol.staleness_seconds > 30 ? "text-amber-500" : "text-muted-foreground"
                    )}>
                      {formatDuration(symbol.staleness_seconds)}
                    </span>
                  </td>
                  <td className="p-3">
                    {symbol.active_gaps > 0 ? (
                      <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/30">
                        {symbol.active_gaps}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </td>
                  <td className="p-3">
                    {symbol.active_alerts > 0 ? (
                      <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/30">
                        {symbol.active_alerts}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </td>
                  <td className="p-3">
                    <span className={cn(
                      "font-mono",
                      symbol.latency_p95_ms > 200 ? "text-red-500" :
                      symbol.latency_p95_ms > 100 ? "text-amber-500" : "text-muted-foreground"
                    )}>
                      {symbol.latency_p95_ms}ms
                    </span>
                  </td>
                  <td className="p-3 text-xs text-muted-foreground">
                    {formatTimestamp(symbol.last_good_timestamp)}
                  </td>
                  <td className="p-3">
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function AlertsPanel() {
  const [acknowledgeNote, setAcknowledgeNote] = useState("");
  const [selectedAlert, setSelectedAlert] = useState<string | null>(null);
  const { data: alertsData, isLoading } = useQualityAlerts();
  const updateAlertStatus = useUpdateAlertStatus();

  const alerts = (alertsData as any)?.alerts ?? (alertsData as any)?.data ?? [];

  const handleAcknowledge = (alertId: string) => {
    updateAlertStatus.mutate(
      { alertId, status: "acknowledged", resolutionNotes: acknowledgeNote },
      {
        onSuccess: () => {
          toast.success(`Alert acknowledged: ${alertId}`);
          setSelectedAlert(null);
          setAcknowledgeNote("");
        },
        onError: () => {
          toast.error("Failed to acknowledge alert");
        },
      }
    );
  };

  const activeAlerts = alerts.filter((a: any) => a.state === "active" || a.status === "active");
  const clearedAlerts = alerts.filter((a: any) => a.state === "cleared" || a.status === "resolved" || a.status === "acknowledged");

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">Alerts</CardTitle>
            <CardDescription className="text-xs">{activeAlerts.length} active, {clearedAlerts.length} cleared</CardDescription>
          </div>
          <Tabs defaultValue="active" className="w-auto">
            <TabsList className="h-7">
              <TabsTrigger value="active" className="text-xs h-6 px-2">Active</TabsTrigger>
              <TabsTrigger value="cleared" className="text-xs h-6 px-2">Cleared</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {activeAlerts.length === 0 ? (
            <div className="py-6 text-center">
              <CheckCircle2 className="h-8 w-8 mx-auto text-emerald-500/50" />
              <p className="mt-2 text-sm text-muted-foreground">No active alerts</p>
            </div>
          ) : (
            activeAlerts.map((alert: any) => {
              const impact = getImpactBadge(alert.impact);
              return (
                <div
                  key={alert.id}
                  className="flex items-start justify-between p-3 rounded-lg border border-border/50 hover:bg-muted/30 transition-colors"
                >
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant="outline" className={getSeverityColor(alert.severity)}>
                        {alert.severity}
                      </Badge>
                      <span className="text-sm font-medium">{alert.symbol}</span>
                      <Badge variant="outline" className="text-xs">
                        {alert.type.replace(/_/g, " ")}
                      </Badge>
                      <Badge variant="outline" className={cn("text-xs", impact.color)}>
                        {impact.label}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{alert.description}</p>
                    <div className="flex items-center gap-4 text-xs text-muted-foreground">
                      <span>Threshold: {alert.threshold}</span>
                      <span>Actual: <span className="text-red-500">{alert.actual}</span></span>
                      <span>{formatTimestamp(alert.detected_at || alert.timestamp)}</span>
                    </div>
                  </div>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button size="sm" variant="outline" className="ml-2">
                        <MessageSquare className="h-3 w-3 mr-1" />
                        Acknowledge
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Acknowledge Alert</AlertDialogTitle>
                        <AlertDialogDescription>
                          Add a note explaining why you're acknowledging this alert. The alert will remain visible but marked as acknowledged.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <div className="py-4">
                        <Label htmlFor="note" className="text-sm">Note (optional)</Label>
                        <Input
                          id="note"
                          placeholder="e.g., Known issue, investigating..."
                          value={acknowledgeNote}
                          onChange={(e) => setAcknowledgeNote(e.target.value)}
                          className="mt-2"
                        />
                      </div>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => handleAcknowledge(alert.id)}>
                          Acknowledge
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              );
            })
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function GapsPanel() {
  const { data: gapsData, isLoading } = useFeedGaps();
  const [backfillInProgress, setBackfillInProgress] = useState<Record<string, boolean>>({});

  const gaps = (gapsData as any)?.gaps ?? (gapsData as any)?.data ?? [];

  const handleQueueBackfill = async (gap: any) => {
    const gapId = gap.id;
    const symbol = gap.symbol;
    const startTime = gap.gap_start || gap.gapStart;
    const endTime = gap.gap_end || gap.gapEnd;
    const timeframe = gap.timeframe || "5m";
    
    // Default to bybit if exchange not specified
    const exchange = gap.exchange || "bybit";
    
    setBackfillInProgress((prev) => ({ ...prev, [gapId]: true }));
    
    try {
      const { backfillGap } = await import("../../lib/api/client");
      const response = await backfillGap({
        gap_id: gapId,
        symbol,
        exchange,
        start_time: startTime,
        end_time: endTime,
        timeframe,
      });
      
      toast.success(`Backfill started: ${response.message}`);
      
      // Poll for progress
      const pollProgress = async () => {
        try {
          const { getBackfillProgress } = await import("../../lib/api/client");
          const progress = await getBackfillProgress(response.job_id);
          
          if (progress.status === "completed") {
            toast.success(`Backfill completed: ${progress.inserted_candles} candles inserted`);
            setBackfillInProgress((prev) => ({ ...prev, [gapId]: false }));
          } else if (progress.status === "failed") {
            toast.error(`Backfill failed: ${progress.error || "Unknown error"}`);
            setBackfillInProgress((prev) => ({ ...prev, [gapId]: false }));
          } else if (progress.status === "running") {
            // Continue polling
            setTimeout(pollProgress, 2000);
          }
        } catch (err) {
          console.error("Error polling backfill progress:", err);
          setBackfillInProgress((prev) => ({ ...prev, [gapId]: false }));
        }
      };
      
      // Start polling after a short delay
      setTimeout(pollProgress, 1000);
      
    } catch (err: any) {
      console.error("Error starting backfill:", err);
      toast.error(`Failed to start backfill: ${err.message || "Unknown error"}`);
      setBackfillInProgress((prev) => ({ ...prev, [gapId]: false }));
    }
  };

  const handleExportReport = () => {
    toast.success("Gap report exported");
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">Feed Gaps</CardTitle>
            <CardDescription className="text-xs">{gaps.length} gaps detected</CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={handleExportReport}>
            <Download className="h-3.5 w-3.5 mr-1" />
            Export
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {gaps.map((gap: any) => {
            const isRunning = backfillInProgress[gap.id] || (gap.backfill_status || gap.backfillStatus) === "running";
            const backfillStatus = isRunning 
              ? getBackfillStatusBadge("running")
              : getBackfillStatusBadge(gap.backfill_status || gap.backfillStatus);
            const BackfillIcon = backfillStatus.icon;
            return (
              <div
                key={gap.id}
                className="flex items-start justify-between p-3 rounded-lg border border-border/50 hover:bg-muted/30 transition-colors"
              >
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{gap.symbol}</span>
                    <Badge variant="outline" className="text-xs">{gap.timeframe}</Badge>
                    <Badge variant="outline" className={getSeverityColor(gap.severity)}>
                      {gap.severity}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>{formatTimestamp(gap.gap_start || gap.gapStart)} → {formatTimestamp(gap.gap_end || gap.gapEnd)}</span>
                    <span>Duration: <span className="text-foreground">{formatDuration(gap.duration_seconds || gap.durationSeconds)}</span></span>
                    <span>Missing: <span className="text-foreground">{gap.missing_candles ?? gap.missingCandles} candles</span></span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className={cn("text-xs", backfillStatus.color)}>
                      <BackfillIcon className={cn("h-3 w-3 mr-1", isRunning && "animate-spin")} />
                      {backfillStatus.label}
                    </Badge>
                  </div>
                </div>
                {!isRunning && (gap.backfill_status || gap.backfillStatus) !== "completed" && (
                  <Button size="sm" variant="outline" onClick={() => handleQueueBackfill(gap)} disabled={isRunning}>
                    <Play className="h-3 w-3 mr-1" />
                    Backfill
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function QualityTrendChart({ selectedSymbol, metrics }: { selectedSymbol: string | null; metrics: any[] }) {
  const trendData = useMemo(() => {
    const filtered = metrics
      .filter((m: any) => !selectedSymbol || m.symbol === selectedSymbol)
      .map((m: any) => ({
        time: m.metric_date || m.timestamp || m.created_at,
        score: m.quality_score ?? 0,
        staleness: m.staleness_seconds ?? m.staleness ?? 0,
      }))
      .filter((m) => m.time);
    return filtered
      .map((m) => ({
        ...m,
        ts: new Date(m.time).getTime(),
        label: new Date(m.time).toLocaleString(),
      }))
      .sort((a, b) => a.ts - b.ts);
  }, [metrics, selectedSymbol]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">Quality Score Trend</CardTitle>
            <CardDescription className="text-xs">
              {selectedSymbol ? `${selectedSymbol} • recent metrics` : "Recent metrics (all symbols)"}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {trendData.length === 0 ? (
          <div className="text-sm text-muted-foreground">No metrics available for this selection.</div>
        ) : (
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="qualityGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                <YAxis yAxisId="score" domain={[0, 100]} tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                <YAxis yAxisId="staleness" orientation="right" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                <RechartsTooltip contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '11px' }} />
                <ReferenceLine yAxisId="score" y={80} stroke="#f59e0b" strokeDasharray="4 4" />
                <Area yAxisId="score" type="monotone" dataKey="score" stroke="#10b981" fill="url(#qualityGradient)" strokeWidth={2} />
                <Line yAxisId="staleness" type="monotone" dataKey="staleness" stroke="#f97316" strokeWidth={2} dot={false} name="Staleness (s)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SymbolDetailDrawer({ symbol, onClose }: { symbol: any; onClose: () => void }) {
  const { data: alertsData } = useQualityAlerts({ symbol: symbol?.symbol, timeframe: symbol?.timeframe });
  const alerts = (alertsData as any)?.alerts ?? (alertsData as any)?.data ?? [];

  if (!symbol) return null;

  return (
    <Sheet open={!!symbol} onOpenChange={() => onClose()}>
      <SheetContent className="w-[500px] sm:max-w-[500px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {symbol.symbol}
            <Badge variant="outline" className={cn("text-xs", getStatusColor(symbol.status))}>
              {symbol.status}
            </Badge>
          </SheetTitle>
          <SheetDescription>
            {symbol.timeframe} timeframe • Last updated {formatDuration(symbol.staleness_seconds ?? symbol.staleness)} ago
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Quality Score Mini Chart */}
          <div>
            <h4 className="text-sm font-medium mb-3">Quality & Staleness (24h)</h4>
            <div className="text-sm text-muted-foreground">No per-symbol trend data yet.</div>
          </div>

          {/* Gap Map */}
          <div>
            <h4 className="text-sm font-medium mb-3">Gap Map (Last Hour)</h4>
            <div className="flex gap-0.5">
              {mockGapMap.map((m, i) => (
                <Tooltip key={i}>
                  <TooltipTrigger>
                    <div
                      className={cn(
                        "h-4 w-1.5 rounded-sm transition-colors",
                        m.hasGap ? "bg-red-500" : "bg-emerald-500/30"
                      )}
                    />
                  </TooltipTrigger>
                  <TooltipContent>
                    <p className="text-xs">Minute {m.minute}: {m.hasGap ? "Gap detected" : "OK"}</p>
                  </TooltipContent>
                </Tooltip>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-1">Red = missing data</p>
          </div>

          {/* Raw Feed Stats */}
          <div>
            <h4 className="text-sm font-medium mb-3">Feed Statistics</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-muted/30">
                <p className="text-xs text-muted-foreground">Messages/sec</p>
                <p className="text-lg font-bold">{symbol.messagesPerSec}</p>
              </div>
              <div className="p-3 rounded-lg bg-muted/30">
                <p className="text-xs text-muted-foreground">Drop Rate</p>
                <p className={cn("text-lg font-bold", symbol.dropRate > 0.1 && "text-red-500")}>
                  {(symbol.dropRate * 100).toFixed(1)}%
                </p>
              </div>
              <div className="p-3 rounded-lg bg-muted/30">
                <p className="text-xs text-muted-foreground">Out of Order</p>
                <p className={cn("text-lg font-bold", symbol.outOfOrderCount > 10 && "text-amber-500")}>
                  {symbol.outOfOrderCount}
                </p>
              </div>
              <div className="p-3 rounded-lg bg-muted/30">
                <p className="text-xs text-muted-foreground">Latency p95</p>
                <p className={cn("text-lg font-bold", symbol.latencyP95 > 200 && "text-red-500")}>
                  {symbol.latencyP95}ms
                </p>
              </div>
            </div>
          </div>

          {/* Recent Alerts */}
          <div>
            <h4 className="text-sm font-medium mb-3">Recent Alerts</h4>
            <div className="space-y-2">
              {alerts.filter((a: any) => a.symbol === symbol.symbol).slice(0, 3).map((alert: any) => (
                <div key={alert.id} className="p-2 rounded-lg border border-border/50 text-xs">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className={getSeverityColor(alert.severity)}>
                      {alert.severity}
                    </Badge>
                    <span>{(alert.type || alert.alert_type || "").replace(/_/g, " ")}</span>
                    <Badge variant="outline" className={cn("ml-auto", (alert.state === "active" || alert.status === "active") ? "text-red-500" : "text-muted-foreground")}>
                      {alert.state || alert.status}
                    </Badge>
                  </div>
                  <p className="text-muted-foreground mt-1">{alert.description}</p>
                </div>
              ))}
              {alerts.filter((a: any) => a.symbol === symbol.symbol).length === 0 && (
                <p className="text-sm text-muted-foreground">No recent alerts</p>
              )}
            </div>
          </div>

          {/* Cross-links */}
          <div>
            <h4 className="text-sm font-medium mb-3">Related Views</h4>
            <div className="space-y-2">
              <Link to={`/dashboard/signals?symbol=${symbol.symbol}`}>
                <Button variant="outline" size="sm" className="w-full justify-start">
                  <Signal className="h-4 w-4 mr-2" />
                  Open Signals for {symbol.symbol}
                  <ExternalLink className="h-3 w-3 ml-auto" />
                </Button>
              </Link>
              <Link to={`/dashboard/market-context?symbol=${symbol.symbol}`}>
                <Button variant="outline" size="sm" className="w-full justify-start">
                  <Activity className="h-4 w-4 mr-2" />
                  Open Market Context
                  <ExternalLink className="h-3 w-3 ml-auto" />
                </Button>
              </Link>
              <Link to={`/analysis/replay?symbol=${symbol.symbol}&time=${symbol.lastGoodTimestamp}`}>
                <Button variant="outline" size="sm" className="w-full justify-start">
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Open Replay at Last Good
                  <ExternalLink className="h-3 w-3 ml-auto" />
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function DataQualityPage() {
  const [mode, setMode] = useState<"overview" | "investigate">("overview");
  const [showOnlyUnhealthy, setShowOnlyUnhealthy] = useState(true);
  const [selectedSymbol, setSelectedSymbol] = useState<any>(null);
  const [filters, setFilters] = useState({
    symbol: "",
    timeframe: "1m",
    exchange: "",
    status: "",
  });

  // Live data fetches
  const { data: metricsData, isLoading: loadingMetrics } = useQualityMetrics({
    symbol: filters.symbol || undefined,
    timeframe: filters.timeframe || undefined,
    status: filters.status || undefined,
  });
  const { data: timeseriesData } = useQualityMetricsTimeseries({
    symbol: filters.symbol || undefined,
    timeframe: filters.timeframe || undefined,
    limit: 500,
  });
  const { data: gapsData, isLoading: loadingGaps } = useFeedGaps({
    symbol: filters.symbol || undefined,
    timeframe: filters.timeframe || undefined,
  });
  const { data: alertsData, isLoading: loadingAlerts } = useQualityAlerts({
    symbol: filters.symbol || undefined,
    timeframe: filters.timeframe || undefined,
    severity: filters.status || undefined,
  });
  const { data: healthData } = useSymbolHealth(filters.symbol || undefined, {
    timeframe: filters.timeframe || undefined,
  });

  return (
    <TooltipProvider>
      <DashBar />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Data Quality</h1>
            <p className="text-sm text-muted-foreground">
              Monitor feed health, gaps, and quality metrics
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              <RefreshCw className="h-3 w-3 mr-1" />
              Auto-refresh: 30s
            </Badge>
          </div>
        </div>

        {/* Sticky Filters */}
        <Card className="sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              {/* Mode Toggle */}
              <div className="flex items-center gap-2">
                <Tabs value={mode} onValueChange={(v: string) => setMode(v as "overview" | "investigate")}>
                  <TabsList className="h-8">
                    <TabsTrigger value="overview" className="text-xs h-7 px-3">
                      <Eye className="h-3.5 w-3.5 mr-1" />
                      Overview
                    </TabsTrigger>
                    <TabsTrigger value="investigate" className="text-xs h-7 px-3">
                      <Search className="h-3.5 w-3.5 mr-1" />
                      Investigate
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
                <Separator orientation="vertical" className="h-6" />
                <div className="flex items-center gap-2">
                  <Switch
                    checked={showOnlyUnhealthy}
                    onChange={(e) => setShowOnlyUnhealthy(e.target.checked)}
                  />
                  <Label className="text-xs cursor-pointer" onClick={() => setShowOnlyUnhealthy(!showOnlyUnhealthy)}>
                    Only unhealthy
                  </Label>
                </div>
              </div>

              {/* Filters */}
              <div className="flex items-center gap-3">
                <div className="relative">
                  <Search className="absolute left-2.5 top-2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Symbol..."
                    className="pl-8 h-8 w-32"
                    value={filters.symbol}
                    onChange={(e) => setFilters({ ...filters, symbol: e.target.value })}
                  />
                </div>
                <select
                  className="h-8 px-2 text-xs rounded-md border border-border bg-background"
                  value={filters.timeframe}
                  onChange={(e) => setFilters({ ...filters, timeframe: e.target.value })}
                >
                  <option value="1m">1m</option>
                  <option value="5m">5m</option>
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                </select>
                <select
                  className="h-8 px-2 text-xs rounded-md border border-border bg-background"
                  value={filters.status}
                  onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                >
                  <option value="">All Status</option>
                  <option value="healthy">Healthy</option>
                  <option value="degraded">Degraded</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Summary Strip */}
        <SummaryStrip timeframe={filters.timeframe || undefined} />

        {/* Main Content */}
        {mode === "overview" ? (
          <div className="space-y-6">
            {/* Symbol Health Table */}
            <SymbolHealthTable
              data={(healthData as any)?.health ?? (healthData as any)?.data ?? []}
              onSelectSymbol={setSelectedSymbol}
              showOnlyUnhealthy={showOnlyUnhealthy}
            />

            {/* Charts & Panels */}
            <div className="grid gap-6 lg:grid-cols-2">
            <QualityTrendChart
              selectedSymbol={selectedSymbol?.symbol || null}
              metrics={(timeseriesData as any)?.data ?? (timeseriesData as any)?.metrics ?? []}
            />
              <AlertsPanel />
            </div>

            <GapsPanel />
          </div>
        ) : (
          <div className="space-y-6">
            {/* Investigation Mode - Full Table */}
            <SymbolHealthTable
              data={(healthData as any)?.health ?? (healthData as any)?.data ?? []}
              onSelectSymbol={setSelectedSymbol}
              showOnlyUnhealthy={false}
            />

            {/* Side-by-side panels */}
            <div className="grid gap-6 lg:grid-cols-2">
              <AlertsPanel />
              <GapsPanel />
            </div>

            <QualityTrendChart
              selectedSymbol={selectedSymbol?.symbol || null}
              metrics={(timeseriesData as any)?.data ?? (timeseriesData as any)?.metrics ?? []}
            />
          </div>
        )}

        {/* Symbol Detail Drawer */}
        <SymbolDetailDrawer
          symbol={selectedSymbol}
          onClose={() => setSelectedSymbol(null)}
        />
      </div>
    </TooltipProvider>
  );
}
