import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  BookOpen,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Columns,
  Copy,
  Database,
  Download,
  ExternalLink,
  Eye,
  FastForward,
  FileJson,
  FileText,
  Filter,
  Flag,
  Gauge,
  GitCompare,
  Hash,
  HelpCircle,
  Info,
  Layers,
  LineChart,
  ListOrdered,
  Loader2,
  Maximize2,
  MessageSquare,
  Minus,
  Pause,
  Pin,
  Play,
  Plus,
  RefreshCw,
  Rewind,
  Save,
  Search,
  Settings,
  Shield,
  Signal,
  SkipBack,
  SkipForward,
  StepBack,
  StepForward,
  Tag,
  Target,
  Timer,
  TrendingDown,
  TrendingUp,
  X,
  XCircle,
  Zap,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  LineChart as RechartsLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
  ComposedChart,
  Bar,
  ReferenceLine,
  ReferenceArea,
  Scatter,
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
import { Slider } from "../../components/ui/slider";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Checkbox } from "../../components/ui/checkbox";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../components/ui/dropdown-menu";
import toast from "react-hot-toast";
import { format, subDays, subHours, subMinutes, addMinutes, parseISO, formatDistanceToNow } from "date-fns";

// API Hooks
import {
  useReplayEvents,
  useReplaySnapshot,
  useCompareReplaySessions,
  useSessionIntegrity,
  useIntegrityByTimeRange,
  useFeatureDictionary,
  useReplayAnnotations,
  useCreateReplayAnnotation,
  useDeleteReplayAnnotation,
  useOutcomeSummary,
} from "../../lib/api/hooks";
import { fetchReplaySessions, createReplaySession, ReplayEvent } from "../../lib/api/client";
import { useScopeStore } from "../../store/scope-store";
import { useQuery } from "@tanstack/react-query";
import { DashBar } from "../../components/DashBar";
import { 
  ReplayPriceChart, 
  ReplayChartLegend, 
  ReplayChartControls,
  ChartType,
  ChartOverlays,
} from "../../components/replay/ReplayPriceChart";

// ============================================================================
// TYPES
// ============================================================================

interface DecisionTrace {
  timestamp: number;
  symbol: string;
  outcome: "approved" | "rejected";
  gateResults?: {
    data: { passed: boolean; reason?: string };
    risk: { passed: boolean; reason?: string; limitBreached?: string };
    microstructure: { passed: boolean; reason?: string; spread?: number; depth?: number };
  };
  featureContributions?: Array<{ name: string; value: number; zScore: number }>;
  executionMetrics?: {
    expectedPrice?: number;
    submittedPrice?: number;
    fillPrice?: number;
    slippageBps?: number;
    fillTimeMs?: number;
  };
  stages: Array<{
    name: string;
    passed: boolean;
    reason?: string;
    latencyMs: number;
  }>;
  finalDecision?: {
    action: string;
    side: string;
    size: number;
    price: number;
    confidence?: number;
  };
}

interface SessionInfo {
  id: string;
  symbol: string;
  startTime: string;
  endTime: string;
  sessionName?: string;
  configVersion?: number;
  botId?: string;
}

interface IntegrityInfo {
  score: string;
  snapshotCoverage: string;
  dataGaps: number;
  datasetHash: string;
  configVersion: number | null;
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const formatTime = (ts: number) => format(new Date(ts), "HH:mm:ss");
const formatDateTime = (ts: number | string) => format(new Date(ts), "MMM d, HH:mm:ss");
const formatPrice = (price: number) => `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const formatPnL = (pnl: number) => {
  const formatted = `$${Math.abs(pnl).toFixed(2)}`;
  return pnl >= 0 ? `+${formatted}` : `-${formatted}`;
};

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

// Header Summary Component - Shows scope, integrity, outcomes at a glance
function ReplayHeaderSummary({
  session,
  integrity,
  outcomes,
  compareMode,
  onToggleCompare,
}: {
  session: SessionInfo | null;
  integrity: IntegrityInfo | null;
  outcomes: { trades: number; pnl: number; rejects: number; avgLatency: string; avgSlippage: string } | null;
  compareMode: boolean;
  onToggleCompare: () => void;
}) {
  return (
    <div className="bg-card/50 border rounded-lg p-3 mb-4">
      <div className="flex items-center justify-between gap-6">
        {/* Scope Info */}
        <div className="flex items-center gap-4">
          <div>
            <span className="text-xs text-muted-foreground">Symbol</span>
            <p className="font-medium">{session?.symbol || "—"}</p>
            </div>
          <Separator orientation="vertical" className="h-8" />
          <div>
            <span className="text-xs text-muted-foreground">Config</span>
            <p className="font-medium">v{integrity?.configVersion || "—"}</p>
            </div>
            <Separator orientation="vertical" className="h-8" />
          <div>
            <span className="text-xs text-muted-foreground">Time Range</span>
            <p className="font-medium text-sm">
              {session ? `${formatDateTime(session.startTime)} → ${formatDateTime(session.endTime)}` : "—"}
            </p>
          </div>
            </div>

        {/* Data Integrity */}
        <div className="flex items-center gap-4">
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Feed Quality</span>
            <p className={cn(
              "font-medium",
              parseFloat(integrity?.score || "0") >= 90 ? "text-green-500" : 
              parseFloat(integrity?.score || "0") >= 70 ? "text-yellow-500" : "text-red-500"
            )}>
              {integrity?.score || "—"}%
            </p>
            </div>
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Coverage</span>
            <p className="font-medium">{integrity?.snapshotCoverage || "—"}%</p>
          </div>
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Gaps</span>
            <p className={cn("font-medium", (integrity?.dataGaps || 0) > 0 ? "text-yellow-500" : "")}>
              {integrity?.dataGaps ?? "—"}
            </p>
            </div>
          </div>

        {/* Outcome Summary */}
        <div className="flex items-center gap-4">
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Trades</span>
            <p className="font-medium">{outcomes?.trades ?? "—"}</p>
          </div>
          <div className="text-center">
            <span className="text-xs text-muted-foreground">PnL</span>
            <p className={cn("font-medium", (outcomes?.pnl || 0) >= 0 ? "text-green-500" : "text-red-500")}>
              {outcomes ? formatPnL(outcomes.pnl) : "—"}
            </p>
        </div>
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Rejects</span>
            <p className="font-medium">{outcomes?.rejects ?? "—"}</p>
          </div>
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Avg Latency</span>
            <p className="font-medium">{outcomes?.avgLatency || "—"}ms</p>
          </div>
          <div className="text-center">
            <span className="text-xs text-muted-foreground">Avg Slip</span>
            <p className="font-medium">{outcomes?.avgSlippage || "—"}bps</p>
          </div>
        </div>

        {/* Reproducibility Hash */}
          <div className="flex items-center gap-2">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
            <Button
                  variant="ghost"
              size="sm"
                  className="text-xs font-mono"
                  onClick={async () => {
                    const hashToCopy = integrity?.datasetHash || "";
                    if (!hashToCopy) {
                      toast.error("No hash available to copy");
                      return;
                    }
                    try {
                      await navigator.clipboard.writeText(hashToCopy);
                      toast.success("Hash copied to clipboard");
                    } catch (err) {
                      // Fallback for older browsers or non-secure contexts
                      const textArea = document.createElement("textarea");
                      textArea.value = hashToCopy;
                      textArea.style.position = "fixed";
                      textArea.style.left = "-999999px";
                      document.body.appendChild(textArea);
                      textArea.select();
                      try {
                        document.execCommand("copy");
                        toast.success("Hash copied to clipboard");
                      } catch (e) {
                        toast.error("Failed to copy hash");
                      }
                      document.body.removeChild(textArea);
                    }
                  }}
                >
                  <Hash className="h-3 w-3 mr-1" />
                  {integrity?.datasetHash?.slice(0, 8) || "--------"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Reproducibility hash - click to copy</p>
                <p className="font-mono text-xs">{integrity?.datasetHash}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          
          <Separator orientation="vertical" className="h-8" />
          
                <Button
            variant={compareMode ? "default" : "outline"}
                  size="sm"
            onClick={onToggleCompare}
                >
            <GitCompare className="h-4 w-4 mr-1" />
            Compare
                </Button>
            </div>
          </div>
          </div>
  );
}

// Event Filter Chips with counts
function EventFilterChips({
  events,
  filters,
  onToggleFilter,
}: {
  events: ReplayEvent[];
  filters: Set<string>;
  onToggleFilter: (type: string) => void;
}) {
  const counts = useMemo(() => {
    const c: Record<string, number> = { decision: 0, trade: 0, rejection: 0, alert: 0, snapshot: 0 };
    events.forEach(e => {
      if (c[e.type] !== undefined) c[e.type]++;
    });
    return c;
  }, [events]);

  const chipConfig = [
    { type: "decision", label: "Decisions", color: "bg-blue-500" },
    { type: "trade", label: "Trades", color: "bg-green-500" },
    { type: "rejection", label: "Rejects", color: "bg-red-500" },
    { type: "alert", label: "Alerts", color: "bg-yellow-500" },
    { type: "snapshot", label: "Snapshots", color: "bg-purple-500" },
  ];

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {chipConfig.map(({ type, label, color }) => (
        <button
          key={type}
          onClick={() => onToggleFilter(type)}
          className={cn(
            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all",
            filters.has(type)
              ? "bg-muted text-muted-foreground opacity-50"
              : "bg-muted/50 text-foreground hover:bg-muted"
          )}
        >
          <span className={cn("w-2 h-2 rounded-full", color)} />
          {label} ({counts[type]})
        </button>
      ))}
          </div>
  );
}

// Anomaly Lanes - Sparklines for latency, slippage, etc.
function AnomalyLanes({
  events,
  onJumpTo,
}: {
  events: ReplayEvent[];
  onJumpTo: (ts: number) => void;
}) {
  // Extract metrics from events
  const metrics = useMemo(() => {
    const latency: { ts: number; value: number }[] = [];
    const slippage: { ts: number; value: number }[] = [];
    const rejectRate: { ts: number; value: number }[] = [];

    let recentRejects = 0;
    let recentDecisions = 0;

    events.forEach(e => {
      if (e.type === "decision" || e.type === "rejection") {
        if (e.data?.latencyMs) {
          latency.push({ ts: e.timestamp, value: e.data.latencyMs });
        }
        if (e.type === "rejection") recentRejects++;
        recentDecisions++;
        
        if (recentDecisions >= 10) {
          rejectRate.push({ ts: e.timestamp, value: (recentRejects / recentDecisions) * 100 });
          recentRejects = Math.floor(recentRejects * 0.5);
          recentDecisions = Math.floor(recentDecisions * 0.5);
        }
      }
      if (e.type === "trade" && e.data?.slippage) {
        slippage.push({ ts: e.timestamp, value: Math.abs(e.data.slippage) });
      }
    });

    return { latency, slippage, rejectRate };
  }, [events]);

  const renderSparkline = (data: { ts: number; value: number }[], label: string, threshold: number) => {
    if (data.length === 0) return null;
    const maxVal = Math.max(...data.map(d => d.value), threshold);

  return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-16">{label}</span>
        <div className="flex-1 h-4 bg-muted/30 rounded relative overflow-hidden">
          {data.map((d, i) => {
            const height = (d.value / maxVal) * 100;
            const isAnomaly = d.value > threshold;
              return (
                    <div
                key={i}
                      className={cn(
                  "absolute bottom-0 w-0.5 cursor-pointer transition-all hover:bg-primary",
                  isAnomaly ? "bg-red-500" : "bg-muted-foreground/50"
                )}
                style={{
                  left: `${(i / data.length) * 100}%`,
                  height: `${height}%`,
                }}
                onClick={() => onJumpTo(d.ts)}
                title={`${typeof d.value === 'number' ? d.value.toFixed(1) : d.value} at ${formatTime(d.ts)}`}
              />
              );
            })}
          {/* Threshold line */}
          <div
            className="absolute w-full h-px bg-yellow-500/50"
            style={{ bottom: `${(threshold / maxVal) * 100}%` }}
          />
            </div>
          </div>
    );
  };

  return (
    <div className="bg-muted/20 rounded-lg p-2 space-y-1.5">
      {renderSparkline(metrics.latency, "Latency", 50)}
      {renderSparkline(metrics.slippage, "Slippage", 5)}
      {renderSparkline(metrics.rejectRate, "Reject %", 50)}
          </div>
  );
}

// Context Panel - Shows trade details or decision context
function ContextPanel({
  currentEvent,
  nearestDecision,
  snapshot,
  featureDictionary,
  position,
  onNavigate,
}: {
  currentEvent: ReplayEvent | null;
  nearestDecision: DecisionTrace | null;
  snapshot: any;
  featureDictionary: Record<string, any[]>;
  position: any;
  onNavigate: (direction: "prev" | "next") => void;
}) {
  const [activeTab, setActiveTab] = useState("decision");

  // Show snapshot details if current event is a snapshot
  if (currentEvent?.type === "snapshot") {
    const data = currentEvent.data as Record<string, unknown> | undefined;
    const marketData = data?.marketData as Record<string, unknown> | undefined;
    const gateStates = data?.gateStates as Record<string, unknown> | undefined;
    
    return (
      <Card className="h-full rounded-none border-0 border-l overflow-auto">
        <CardHeader className="py-3 px-4 sticky top-0 bg-card z-10 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm">Market Snapshot</CardTitle>
              <Badge variant="outline" className="text-xs">
                {String(data?.snapshotType || "snapshot")}
              </Badge>
            </div>
            <div className="flex gap-1">
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("prev")}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("next")}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          {/* Price Summary */}
          <div className="p-4 bg-muted/30 rounded-lg text-center">
            <div className="text-2xl font-bold font-mono">
              {marketData?.price ? formatPrice(marketData.price as number) : "—"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              Current Price
            </div>
          </div>

          {/* Market Data */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Market Data</h4>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Spread</span>
                <span className="font-mono">
                  {typeof marketData?.spread === 'number' ? `${marketData.spread.toFixed(2)} bps` : "—"}
                </span>
              </div>
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Volume</span>
                <span className="font-mono">
                  {typeof marketData?.volume === 'number' ? marketData.volume.toLocaleString() : "—"}
                </span>
              </div>
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Bid</span>
                <span className="font-mono">
                  {typeof marketData?.bid === 'number' ? formatPrice(marketData.bid) : "—"}
                </span>
              </div>
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Ask</span>
                <span className="font-mono">
                  {typeof marketData?.ask === 'number' ? formatPrice(marketData.ask) : "—"}
                </span>
              </div>
            </div>
          </div>

          {/* System Status */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">System Status</h4>
            <div className="space-y-2">
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Regime</span>
                <Badge variant="outline" className="text-xs">
                  {String(data?.regimeLabel || "unknown")}
                </Badge>
              </div>
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Data Quality</span>
                <span className={cn(
                  "font-mono text-sm",
                  (data?.dataQualityScore as number) >= 90 ? "text-green-500" :
                  (data?.dataQualityScore as number) >= 70 ? "text-yellow-500" : "text-red-500"
                )}>
                  {data?.dataQualityScore !== undefined ? `${data.dataQualityScore}%` : "—"}
                </span>
              </div>
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Latency</span>
                <span className="font-mono text-sm">
                  {data?.latencyMs !== undefined ? `${data.latencyMs}ms` : "—"}
                </span>
              </div>
            </div>
          </div>

          {/* Gate States */}
          {gateStates && Object.keys(gateStates).length > 0 && (
            <div className="space-y-3">
              <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Gate States</h4>
              <div className="space-y-1">
                {Object.entries(gateStates).map(([gate, state]) => (
                  <div key={gate} className="flex justify-between items-center p-2 bg-muted/30 rounded text-xs">
                    <span className="text-muted-foreground">{gate}</span>
                    <Badge 
                      variant={state ? "default" : "outline"}
                      className="text-[10px]"
                    >
                      {state ? "OPEN" : "CLOSED"}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Details */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Details</h4>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Symbol</span>
                <span className="font-mono">{currentEvent.symbol}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Time</span>
                <span className="font-mono">{formatDateTime(currentEvent.timestamp)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Event ID</span>
                <span className="font-mono truncate max-w-[180px] text-[10px]">{currentEvent.id}</span>
              </div>
            </div>
          </div>

          {/* Raw Data (collapsible) */}
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              View Raw Data
            </summary>
            <pre className="mt-2 p-2 bg-muted/30 rounded overflow-x-auto text-[10px]">
              {JSON.stringify(data, null, 2)}
            </pre>
          </details>
        </CardContent>
      </Card>
    );
  }

  // Show alert details if current event is an alert
  if (currentEvent?.type === "alert") {
    const data = currentEvent.data as Record<string, unknown> | undefined;
    
    return (
      <Card className="h-full rounded-none border-0 border-l overflow-auto">
        <CardHeader className="py-3 px-4 sticky top-0 bg-card z-10 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm">Alert</CardTitle>
              <Badge variant="warning" className="text-xs">
                {String(data?.severity || "info")}
              </Badge>
            </div>
            <div className="flex gap-1">
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("prev")}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("next")}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          {/* Alert Title */}
          <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="h-5 w-5 text-yellow-500" />
              <span className="font-medium">{String(data?.title || "Alert")}</span>
            </div>
            {data?.message && (
              <p className="text-sm text-muted-foreground">{String(data.message)}</p>
            )}
          </div>

          {/* Alert Details */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Details</h4>
            <div className="space-y-2">
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Type</span>
                <Badge variant="outline" className="text-xs">
                  {String(data?.incidentType || data?.type || "unknown")}
                </Badge>
              </div>
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Severity</span>
                <Badge 
                  variant={
                    data?.severity === "critical" ? "destructive" :
                    data?.severity === "warning" ? "warning" : "outline"
                  }
                  className="text-xs"
                >
                  {String(data?.severity || "info")}
                </Badge>
              </div>
            </div>
          </div>

          {/* Time Info */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Timing</h4>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Symbol</span>
                <span className="font-mono">{currentEvent.symbol}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Time</span>
                <span className="font-mono">{formatDateTime(currentEvent.timestamp)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Event ID</span>
                <span className="font-mono truncate max-w-[180px] text-[10px]">{currentEvent.id}</span>
              </div>
            </div>
          </div>

          {/* Raw Data (collapsible) */}
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              View Raw Data
            </summary>
            <pre className="mt-2 p-2 bg-muted/30 rounded overflow-x-auto text-[10px]">
              {JSON.stringify(data, null, 2)}
            </pre>
          </details>
        </CardContent>
      </Card>
    );
  }

  // Show trade details if current event is a trade
  if (currentEvent?.type === "trade") {
    const trade = currentEvent.data;
    const isBuy = trade?.side === "buy" || trade?.side === "long";
    const pnl = typeof trade?.pnl === 'number' ? trade.pnl : null;
    const pnlPercent = (trade?.price && trade?.size && pnl !== null) 
      ? (pnl / (trade.price * trade.size) * 100) 
      : null;
    
    return (
      <Card className="h-full rounded-none border-0 border-l overflow-auto">
        <CardHeader className="py-3 px-4 sticky top-0 bg-card z-10 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm">Trade Details</CardTitle>
              <Badge variant={isBuy ? "default" : "destructive"} className="text-xs">
                {trade?.side?.toUpperCase()}
              </Badge>
              {trade?.source && (
                <Badge variant="outline" className="text-[10px]">
                  {trade.source}
                </Badge>
              )}
            </div>
            <div className="flex gap-1">
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("prev")}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("next")}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          {/* P&L Summary - Prominent */}
          <div className={cn(
            "p-4 rounded-lg text-center",
            pnl !== undefined && pnl !== null 
              ? pnl >= 0 ? "bg-green-500/10 border border-green-500/20" : "bg-red-500/10 border border-red-500/20"
              : "bg-muted/30"
          )}>
            <div className="text-2xl font-bold font-mono">
              <span className={pnl !== undefined && pnl !== null ? (pnl >= 0 ? "text-green-500" : "text-red-500") : ""}>
                {pnl !== undefined && pnl !== null ? `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}` : "—"}
              </span>
            </div>
            {pnlPercent !== null && pnlPercent !== undefined && !isNaN(pnlPercent) && (
              <div className="text-xs text-muted-foreground mt-1">
                {pnlPercent >= 0 ? "+" : ""}{pnlPercent.toFixed(2)}% return
              </div>
            )}
          </div>

          {/* Trade Summary */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Position</h4>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Side</span>
                <span className={cn("font-medium", isBuy ? "text-green-500" : "text-red-500")}>
                  {trade?.side?.toUpperCase()}
                </span>
              </div>
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Size</span>
                <span className="font-mono">
                  {typeof trade?.size === 'number' 
                    ? trade.size < 0.001 ? trade.size.toPrecision(4) : trade.size.toFixed(4)
                    : trade?.size}
                </span>
              </div>
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Entry Price</span>
                <span className="font-mono">{formatPrice(trade?.price || 0)}</span>
              </div>
              <div className="p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground text-xs block">Exit Price</span>
                <span className="font-mono">
                  {trade?.exitPrice ? formatPrice(trade.exitPrice) : "—"}
                </span>
              </div>
            </div>
          </div>

          {/* Execution Quality */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Execution Quality</h4>
            <div className="space-y-2">
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Slippage</span>
                <span className={cn(
                  "font-mono text-sm",
                  typeof trade?.slippage === 'number' && trade.slippage > 5 ? "text-yellow-500" : 
                  typeof trade?.slippage === 'number' && trade.slippage > 10 ? "text-red-500" : ""
                )}>
                  {typeof trade?.slippage === 'number' ? `${trade.slippage.toFixed(2)} bps` : "—"}
                </span>
              </div>
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Fees</span>
                <span className="font-mono text-sm">
                  {typeof trade?.fee === 'number' ? `$${trade.fee.toFixed(4)}` : "—"}
                </span>
              </div>
              <div className="flex justify-between items-center p-2 bg-muted/30 rounded">
                <span className="text-xs text-muted-foreground">Strategy</span>
                <span className="text-sm">
                  {trade?.strategy || "default"}
                </span>
              </div>
            </div>
          </div>

          {/* Symbol & Time */}
          <div className="space-y-3">
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Details</h4>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Symbol</span>
                <span className="font-mono">{currentEvent.symbol}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Time</span>
                <span className="font-mono">{formatDateTime(currentEvent.timestamp)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Event ID</span>
                <span className="font-mono truncate max-w-[180px] text-[10px]">{currentEvent.id}</span>
              </div>
            </div>
          </div>

          {/* Raw Data (collapsible) */}
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              View Raw Data
            </summary>
            <pre className="mt-2 p-2 bg-muted/30 rounded overflow-x-auto text-[10px]">
              {JSON.stringify(trade, null, 2)}
            </pre>
          </details>
        </CardContent>
      </Card>
    );
  }

  // If no current event, show "why no decision" state
  if (!currentEvent && !nearestDecision) {
  return (
    <Card className="h-full rounded-none border-0 border-l">
        <CardHeader className="py-3 px-4">
        <div className="flex items-center justify-between">
            <CardTitle className="text-sm">Context</CardTitle>
            <div className="flex gap-1">
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("prev")}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("next")}>
                <ChevronRight className="h-4 w-4" />
              </Button>
          </div>
        </div>
      </CardHeader>
        <CardContent className="p-4">
          <div className="text-center py-8 space-y-4">
            <HelpCircle className="h-12 w-12 mx-auto text-muted-foreground/50" />
            <div>
              <h3 className="font-medium">No Decision at This Time</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Possible reasons:
              </p>
              <ul className="text-xs text-muted-foreground mt-2 space-y-1">
                <li>• Outside evaluation cadence</li>
                <li>• Strategy in warmup period</li>
                <li>• Data quality degraded</li>
                <li>• Post-trade cooldown active</li>
              </ul>
            </div>
            <div className="flex justify-center gap-2">
              <Button variant="outline" size="sm" onClick={() => onNavigate("prev")}>
                <ChevronLeft className="h-3 w-3 mr-1" />
                Previous Decision
              </Button>
              <Button variant="outline" size="sm" onClick={() => onNavigate("next")}>
                Next Decision
                <ChevronRight className="h-3 w-3 ml-1" />
              </Button>
        </div>

            {/* Current Market Snapshot */}
            {snapshot && (
              <div className="mt-4 p-3 bg-muted/30 text-left">
                <h4 className="text-xs font-medium mb-2">Current Market Snapshot</h4>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-muted-foreground">Price:</span>{" "}
                    {formatPrice(snapshot.marketSnapshot?.price || 0)}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Spread:</span>{" "}
                    {typeof snapshot.marketSnapshot?.spread === 'number' ? snapshot.marketSnapshot.spread.toFixed(2) : "—"}bps
                  </div>
                  <div>
                    <span className="text-muted-foreground">Quality:</span>{" "}
                    {snapshot.marketSnapshot?.dataQualityScore || "—"}%
                  </div>
                  <div>
                    <span className="text-muted-foreground">Regime:</span>{" "}
                    {snapshot.marketSnapshot?.regimeLabel || "unknown"}
                  </div>
                </div>
          </div>
        )}
          </div>
      </CardContent>
    </Card>
  );
}

  const decision = nearestDecision;
  const isApproved = decision?.outcome === "approved";

  return (
    <Card className="h-full flex flex-col rounded-none border-0 border-l">
      <CardHeader className="py-3 px-4 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">Context</CardTitle>
            {decision && (
              <Badge variant={isApproved ? "default" : "destructive"} className="text-xs">
                {isApproved ? "Approved" : "Rejected"}
              </Badge>
            )}
          </div>
          <div className="flex gap-1">
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("prev")}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onNavigate("next")}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col">
        <TabsList className="mx-4 mb-2 grid grid-cols-5 h-8">
            <TabsTrigger value="decision" className="text-xs">Decision</TabsTrigger>
          <TabsTrigger value="gates" className="text-xs">Gates</TabsTrigger>
            <TabsTrigger value="features" className="text-xs">Features</TabsTrigger>
            <TabsTrigger value="orders" className="text-xs">Orders</TabsTrigger>
            <TabsTrigger value="position" className="text-xs">Position</TabsTrigger>
          </TabsList>

        <ScrollArea className="flex-1 px-4 pb-4">
          {/* Decision Tab */}
          <TabsContent value="decision" className="mt-0 space-y-3">
            {decision?.finalDecision && (
              <div className="p-3 bg-muted/30 rounded-lg">
                <h4 className="text-xs font-medium mb-2">Action</h4>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-muted-foreground">Side:</span>{" "}
                    <span className={decision.finalDecision.side === "buy" ? "text-green-500" : "text-red-500"}>
                      {decision.finalDecision.side?.toUpperCase()}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Size:</span> {decision.finalDecision.size}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Price:</span> {formatPrice(decision.finalDecision.price)}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Confidence:</span>{" "}
                    {typeof decision.finalDecision.confidence === 'number' ? (decision.finalDecision.confidence * 100).toFixed(0) : "—"}%
                  </div>
                </div>
              </div>
            )}

                  {/* Stage Pipeline */}
            <div>
              <h4 className="text-xs font-medium mb-2">Pipeline Stages</h4>
              <div className="space-y-1.5">
                {(decision?.stages || []).map((stage, i) => (
                  <div
                    key={i}
                        className={cn(
                      "flex items-center justify-between p-2 rounded text-xs",
                      stage.passed ? "bg-green-500/10" : "bg-red-500/10"
                        )}
                      >
                          <div className="flex items-center gap-2">
                            {stage.passed ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                            ) : (
                        <XCircle className="h-3.5 w-3.5 text-red-500" />
                            )}
                      <span>{stage.name}</span>
                          </div>
                    <div className="flex items-center gap-2 text-muted-foreground">
                      {stage.reason && <span>{stage.reason}</span>}
                      <span>{stage.latencyMs}ms</span>
                          </div>
                        </div>
                ))}
              </div>
            </div>
          </TabsContent>

          {/* Gates Tab */}
          <TabsContent value="gates" className="mt-0 space-y-3">
            {decision?.gateResults ? (
              <>
                {/* Data Gate */}
                <div className={cn(
                  "p-3 rounded-lg",
                  decision.gateResults.data?.passed ? "bg-green-500/10" : "bg-red-500/10"
                )}>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-medium flex items-center gap-1.5">
                      <Database className="h-3.5 w-3.5" />
                      Data Gate
                    </h4>
                    <Badge variant={decision.gateResults.data?.passed ? "default" : "destructive"} className="text-xs">
                      {decision.gateResults.data?.passed ? "PASS" : "FAIL"}
                    </Badge>
                          </div>
                  {decision.gateResults.data?.reason && (
                    <p className="text-xs text-muted-foreground">{decision.gateResults.data.reason}</p>
                        )}
                      </div>

                {/* Risk Gate */}
                <div className={cn(
                  "p-3 rounded-lg",
                  decision.gateResults.risk?.passed ? "bg-green-500/10" : "bg-red-500/10"
                )}>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-medium flex items-center gap-1.5">
                      <Shield className="h-3.5 w-3.5" />
                      Risk Gate
                    </h4>
                    <Badge variant={decision.gateResults.risk?.passed ? "default" : "destructive"} className="text-xs">
                      {decision.gateResults.risk?.passed ? "PASS" : "FAIL"}
                    </Badge>
                  </div>
                  {decision.gateResults.risk?.reason && (
                    <p className="text-xs text-muted-foreground">{decision.gateResults.risk.reason}</p>
                  )}
                  {decision.gateResults.risk?.limitBreached && (
                    <p className="text-xs text-red-500 mt-1">Limit: {decision.gateResults.risk.limitBreached}</p>
                  )}
                  </div>

                {/* Microstructure Gate */}
                <div className={cn(
                  "p-3 rounded-lg",
                  decision.gateResults.microstructure?.passed ? "bg-green-500/10" : "bg-red-500/10"
                )}>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-medium flex items-center gap-1.5">
                      <Activity className="h-3.5 w-3.5" />
                      Microstructure Gate
                    </h4>
                    <Badge variant={decision.gateResults.microstructure?.passed ? "default" : "destructive"} className="text-xs">
                      {decision.gateResults.microstructure?.passed ? "PASS" : "FAIL"}
                    </Badge>
                        </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                        <div>
                      <span className="text-muted-foreground">Spread:</span>{" "}
                      {typeof decision.gateResults.microstructure?.spread === 'number' ? decision.gateResults.microstructure.spread.toFixed(2) : "—"}bps
                        </div>
                        <div>
                      <span className="text-muted-foreground">Depth:</span>{" "}
                      {typeof decision.gateResults.microstructure?.depth === 'number' ? decision.gateResults.microstructure.depth.toFixed(0) : "—"}
                        </div>
                        </div>
                      </div>
              </>
            ) : (
              <div className="text-center py-8 text-muted-foreground text-sm">
                No gate data available for this decision
                </div>
              )}
            </TabsContent>

            {/* Features Tab */}
          <TabsContent value="features" className="mt-0 space-y-3">
                  <div>
              <h4 className="text-xs font-medium mb-2">Top Contributing Features</h4>
              {(decision?.featureContributions || []).length > 0 ? (
                <div className="space-y-1.5">
                  {decision?.featureContributions?.slice(0, 10).map((f, i) => {
                    const featureInfo = Object.values(featureDictionary).flat().find(
                      (fd: any) => fd.name === f.name
                    );
                    return (
                      <TooltipProvider key={i}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div className="flex items-center justify-between p-2 bg-muted/30 rounded text-xs cursor-help">
                              <span className="font-medium">{f.name}</span>
                              <div className="flex items-center gap-3">
                                <span>{typeof f.value === 'number' ? f.value.toFixed(4) : f.value}</span>
                                <Badge
                                  variant={typeof f.zScore === 'number' && Math.abs(f.zScore) > 2 ? "destructive" : "secondary"}
                                  className="text-xs"
                                >
                                  z: {typeof f.zScore === 'number' ? f.zScore.toFixed(2) : f.zScore}
                                </Badge>
                          </div>
                          </div>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p className="font-medium">{featureInfo?.displayName || f.name}</p>
                            <p className="text-xs">{featureInfo?.description || "No description available"}</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-4 text-muted-foreground text-sm">
                  No feature data available
                </div>
              )}
            </div>
            </TabsContent>

            {/* Orders Tab */}
          <TabsContent value="orders" className="mt-0 space-y-3">
            {decision?.executionMetrics ? (
              <div className="space-y-3">
                <div className="p-3 bg-muted/30 rounded-lg">
                  <h4 className="text-xs font-medium mb-2">Execution Metrics</h4>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Expected Price:</span>
                      <span>{formatPrice(decision.executionMetrics.expectedPrice || 0)}</span>
                      </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Submitted Price:</span>
                      <span>{formatPrice(decision.executionMetrics.submittedPrice || 0)}</span>
                        </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Fill Price:</span>
                      <span>{formatPrice(decision.executionMetrics.fillPrice || 0)}</span>
                        </div>
                    <Separator className="my-2" />
                    <div className="flex justify-between font-medium">
                      <span>Slippage:</span>
                      <span className={cn(
                        typeof decision.executionMetrics.slippageBps === 'number' && decision.executionMetrics.slippageBps > 2 ? "text-red-500" : "text-green-500"
                      )}>
                        {typeof decision.executionMetrics.slippageBps === 'number' ? decision.executionMetrics.slippageBps.toFixed(2) : "0"}bps
                          </span>
                        </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Fill Time:</span>
                      <span>{decision.executionMetrics.fillTimeMs || "—"}ms</span>
                      </div>
                    </div>
                </div>
                </div>
              ) : (
              <div className="text-center py-8 text-muted-foreground text-sm">
                No order/execution data available
                </div>
              )}
            </TabsContent>

            {/* Position Tab */}
          <TabsContent value="position" className="mt-0 space-y-3">
            {position ? (
              <div className="p-3 bg-muted/30 rounded-lg">
                <h4 className="text-xs font-medium mb-2">Current Position</h4>
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Side:</span>
                    <span className={position.side === "long" ? "text-green-500" : "text-red-500"}>
                      {position.side?.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Size:</span>
                    <span>{position.size}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Entry Price:</span>
                    <span>{formatPrice(position.entryPrice)}</span>
                  </div>
                  <Separator className="my-2" />
                  <div className="flex justify-between font-medium">
                    <span>Unrealized PnL:</span>
                    <span className={position.unrealizedPnl >= 0 ? "text-green-500" : "text-red-500"}>
                      {formatPnL(position.unrealizedPnl)}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground text-sm">
                No position at this time
              </div>
            )}
            </TabsContent>
          </ScrollArea>
        </Tabs>

        {/* Related Views - Collapsible */}
        <div className="flex-shrink-0 p-3 border-t">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-muted-foreground">Quick Links</span>
          </div>
          <div className="flex gap-1.5 flex-wrap">
            <Link to="/dashboard/risk/incidents">
              <Button variant="ghost" size="sm" className="h-7 text-xs">
                <AlertTriangle className="h-3 w-3 mr-1" />
                Incidents
              </Button>
            </Link>
            <Link to="/dashboard/execution">
              <Button variant="ghost" size="sm" className="h-7 text-xs">
                <Activity className="h-3 w-3 mr-1" />
                Execution
              </Button>
            </Link>
            <Link to="/dashboard/history">
              <Button variant="ghost" size="sm" className="h-7 text-xs">
                <BarChart3 className="h-3 w-3 mr-1" />
                History
              </Button>
            </Link>
          </div>
        </div>
    </Card>
  );
}

// Compare Mode Panel
function CompareModePanel({
  isOpen,
  sessions,
  currentSessionId,
  compareSessionId,
  onSelectCompareSession,
  compareResults,
  isComparing,
  onRunCompare,
}: {
  isOpen: boolean;
  sessions: any[];
  currentSessionId: string | null;
  compareSessionId: string | null;
  onSelectCompareSession: (id: string) => void;
  compareResults: any | null;
  isComparing: boolean;
  onRunCompare: () => void;
}) {
  if (!isOpen) return null;

  return (
    <div className="absolute top-0 right-0 w-80 bg-card border rounded-lg shadow-lg p-4 z-10 m-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium flex items-center gap-2">
          <GitCompare className="h-4 w-4" />
          Compare Sessions
        </h3>
      </div>

      <div className="space-y-3">
        <div>
          <Label className="text-xs">Compare with:</Label>
          <Select value={compareSessionId || ""} onValueChange={onSelectCompareSession}>
            <SelectTrigger className="mt-1">
              <SelectValue placeholder="Select session..." />
            </SelectTrigger>
            <SelectContent>
              {sessions.filter(s => s.id !== currentSessionId).map(s => (
                <SelectItem key={s.id} value={s.id}>
                  {s.session_name || format(new Date(s.created_at), "MMM d HH:mm")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button
          onClick={onRunCompare}
          disabled={!compareSessionId || isComparing}
          className="w-full"
        >
          {isComparing ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Comparing...
            </>
          ) : (
            <>
              <GitCompare className="h-4 w-4 mr-2" />
              Run Comparison
            </>
          )}
        </Button>

        {/* Compare Results Summary */}
        {compareResults && (
          <div className="mt-4 p-3 bg-muted/30 rounded-lg space-y-2">
            <h4 className="text-xs font-medium">Comparison Results</h4>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">Trade Count Δ:</span>
                <span className={cn(
                  "ml-1 font-medium",
                  compareResults.summary?.diff?.tradeCountDelta > 0 ? "text-green-500" : 
                  compareResults.summary?.diff?.tradeCountDelta < 0 ? "text-red-500" : ""
                )}>
                  {compareResults.summary?.diff?.tradeCountDelta > 0 ? "+" : ""}
                  {compareResults.summary?.diff?.tradeCountDelta || 0}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">PnL Δ:</span>
                <span className={cn(
                  "ml-1 font-medium",
                  compareResults.summary?.diff?.pnlDelta > 0 ? "text-green-500" : 
                  compareResults.summary?.diff?.pnlDelta < 0 ? "text-red-500" : ""
                )}>
                  {formatPnL(compareResults.summary?.diff?.pnlDelta || 0)}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Added Events:</span>
                <span className="ml-1 font-medium text-green-500">
                  +{compareResults.addedEvents?.length || 0}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Removed Events:</span>
                <span className="ml-1 font-medium text-red-500">
                  -{compareResults.removedEvents?.length || 0}
                </span>
              </div>
            </div>
            {(compareResults.changedDecisions?.length || 0) > 0 && (
              <div className="mt-2 pt-2 border-t">
                <span className="text-xs text-yellow-500">
                  ⚠️ {compareResults.changedDecisions.length} decision outcomes changed
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Regime/Signal Panel (below price chart)
function RegimeSignalPanel({
  events,
  currentTime,
}: {
  events: ReplayEvent[];
  currentTime: number;
}) {
  // Extract regime and signal data from snapshots
  const regimeData = useMemo(() => {
    return events
      .filter(e => e.type === "snapshot" && e.data?.regimeLabel)
      .map(e => ({
        time: e.timestamp,
        regime: e.data.regimeLabel || "unknown",
        dataQuality: e.data.dataQualityScore || 100,
      }));
  }, [events]);

  const currentRegime = useMemo(() => {
    const snapshots = events.filter(e => e.type === "snapshot").sort((a, b) => a.timestamp - b.timestamp);
    for (let i = snapshots.length - 1; i >= 0; i--) {
      if (snapshots[i].timestamp <= currentTime) {
        return snapshots[i].data?.regimeLabel || "unknown";
      }
    }
    return "unknown";
  }, [events, currentTime]);

  const regimeColors: Record<string, string> = {
    trend: "bg-blue-500",
    "mean-revert": "bg-purple-500",
    flat: "bg-gray-500",
    volatile: "bg-orange-500",
    unknown: "bg-gray-400",
  };

  return (
    <div className="h-16 border-t bg-muted/10 px-4 py-2">
      <div className="flex items-center justify-between h-full">
        <div className="flex items-center gap-4">
          <div>
            <span className="text-xs text-muted-foreground">Current Regime</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={cn("w-2 h-2 rounded-full", regimeColors[currentRegime] || regimeColors.unknown)} />
              <span className="text-sm font-medium capitalize">{currentRegime}</span>
            </div>
          </div>
        </div>

        {/* Mini regime timeline */}
        <div className="flex-1 h-4 mx-4 bg-muted/30 rounded overflow-hidden flex">
          {regimeData.slice(0, 50).map((d, i) => (
            <div
              key={i}
              className={cn(
                "flex-1 transition-opacity",
                d.time <= currentTime ? "opacity-100" : "opacity-30",
                regimeColors[d.regime] || regimeColors.unknown
              )}
              title={`${d.regime} at ${formatTime(d.time)}`}
            />
          ))}
        </div>

        <div className="text-right">
          <span className="text-xs text-muted-foreground">Gate States</span>
          <div className="flex items-center gap-1 mt-0.5">
            <Badge variant="outline" className="text-xs px-1.5 py-0">
              <CheckCircle2 className="h-2.5 w-2.5 mr-0.5 text-green-500" />
              Risk
            </Badge>
            <Badge variant="outline" className="text-xs px-1.5 py-0">
              <CheckCircle2 className="h-2.5 w-2.5 mr-0.5 text-green-500" />
              Data
            </Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

// Post-Mortem Panel
function PostMortemPanel({
  isOpen,
  onClose,
  session,
  outcomes,
  annotations,
  onCreateAnnotation,
}: {
  isOpen: boolean;
  onClose: () => void;
  session: SessionInfo | null;
  outcomes: any;
  annotations: any[];
  onCreateAnnotation: (data: { title: string; content: string; tags: string[] }) => void;
}) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");

  const handleAddTag = () => {
    if (tagInput.trim() && !tags.includes(tagInput.trim())) {
      setTags([...tags, tagInput.trim()]);
      setTagInput("");
    }
  };

  const handleSubmit = () => {
    if (title.trim() || content.trim()) {
      onCreateAnnotation({ title, content, tags });
      setTitle("");
      setContent("");
      setTags([]);
      // Toast is shown by handleCreateAnnotation
    }
  };

  return (
    <Sheet open={isOpen} onOpenChange={onClose}>
      <SheetContent className="w-[500px] sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Post-Mortem Analysis</SheetTitle>
          <SheetDescription>
            Document findings and create annotations for this replay session
          </SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Summary Section */}
          <div>
            <h3 className="text-sm font-medium mb-3">Session Summary</h3>
            <div className="p-3 bg-muted/30 rounded-lg space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Symbol:</span>
                <span>{session?.symbol || "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Time Range:</span>
                <span className="text-xs">
                  {session ? `${formatDateTime(session.startTime)} → ${formatDateTime(session.endTime)}` : "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total Trades:</span>
                <span>{outcomes?.trades ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Net PnL:</span>
                <span className={cn((outcomes?.pnl || 0) >= 0 ? "text-green-500" : "text-red-500")}>
                  {outcomes ? formatPnL(outcomes.pnl) : "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Rejection Rate:</span>
                <span>
                  {outcomes ? `${((outcomes.rejects / (outcomes.rejects + outcomes.trades || 1)) * 100).toFixed(1)}%` : "—"}
                </span>
              </div>
            </div>
          </div>

          {/* Add Annotation */}
          <div>
            <h3 className="text-sm font-medium mb-3">Add Annotation</h3>
            <div className="space-y-3">
              <div>
                <Label className="text-xs">Title</Label>
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Brief summary..."
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Notes</Label>
                <Textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="Detailed observations, root cause analysis..."
                  className="mt-1 min-h-[100px]"
                />
              </div>
              <div>
                <Label className="text-xs">Tags</Label>
                <div className="flex gap-2 mt-1">
                  <Input
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    placeholder="Add tag..."
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddTag())}
                  />
                  <Button variant="outline" onClick={handleAddTag}>Add</Button>
                </div>
                {tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {tags.map((tag, i) => (
                      <Badge key={i} variant="secondary" className="text-xs">
                  {tag}
                        <button
                          className="ml-1 hover:text-destructive"
                          onClick={() => setTags(tags.filter((_, j) => j !== i))}
                        >
                          <X className="h-2.5 w-2.5" />
                        </button>
                </Badge>
              ))}
                  </div>
                )}
              </div>
              <Button onClick={handleSubmit} className="w-full">
                <Pin className="h-4 w-4 mr-2" />
                Save Annotation
              </Button>
            </div>
          </div>

          {/* Existing Annotations */}
          <div>
            <h3 className="text-sm font-medium mb-3">
              Previous Annotations {annotations.length > 0 ? `(${annotations.length})` : ""}
            </h3>
            {annotations.length > 0 ? (
              <ScrollArea className="h-[200px]">
                <div className="space-y-2">
                  {annotations.map((ann: any) => (
                    <div key={ann.id} className="p-2 bg-muted/30 rounded-lg text-xs">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium">{ann.title || "Untitled"}</span>
                        <span className="text-muted-foreground">
                          {formatDistanceToNow(new Date(ann.created_at), { addSuffix: true })}
                        </span>
                      </div>
                      <p className="text-muted-foreground">{ann.content}</p>
                      {ann.tags?.length > 0 && (
                        <div className="flex gap-1 mt-1">
                          {ann.tags.map((t: string, i: number) => (
                            <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <div className="p-4 bg-muted/30 rounded-lg text-center text-sm text-muted-foreground">
                No annotations yet. Add one above to document your findings.
              </div>
            )}
          </div>

          {/* Export Options */}
          <div>
            <h3 className="text-sm font-medium mb-3">Export</h3>
            <div className="grid grid-cols-3 gap-2">
              <Button variant="outline" size="sm">
                <FileText className="h-3.5 w-3.5 mr-1" />
                CSV
            </Button>
              <Button variant="outline" size="sm">
                <FileJson className="h-3.5 w-3.5 mr-1" />
                JSON
              </Button>
              <Button variant="outline" size="sm">
                <Download className="h-3.5 w-3.5 mr-1" />
                Bundle
            </Button>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function ReplayStudioPage() {
  const { exchangeAccountId, botId } = useScopeStore();
  const [searchParams] = useSearchParams();

  // Read URL parameters for deep-linking from trade replay buttons
  const urlSymbol = searchParams.get("symbol");
  const urlTime = searchParams.get("time");
  const urlTradeId = searchParams.get("tradeId");

  // Session State - initialize from URL params if provided
  const [selectedSymbol, setSelectedSymbol] = useState(() => {
    if (urlSymbol) return urlSymbol;
    return "BTC-USDT-SWAP";
  });
  const [startTime, setStartTime] = useState(() => {
    if (urlTime) {
      // Center the time window around the trade: 30 mins before to 30 mins after
      const tradeTime = new Date(urlTime);
      return subMinutes(tradeTime, 30).toISOString();
    }
    return subHours(new Date(), 4).toISOString();
  });
  const [endTime, setEndTime] = useState(() => {
    if (urlTime) {
      // Center the time window around the trade: 30 mins before to 30 mins after
      const tradeTime = new Date(urlTime);
      return addMinutes(tradeTime, 30).toISOString();
    }
    return new Date().toISOString();
  });
  const [sessionId, setSessionId] = useState<string | null>(null);
  
  // Track if we should auto-select a trade from URL - track both ID and time
  const [pendingTradeId, setPendingTradeId] = useState<string | null>(urlTradeId);
  const [pendingTradeTime, setPendingTradeTime] = useState<string | null>(urlTime);
  const [hasInitializedFromUrl, setHasInitializedFromUrl] = useState(false);
  // Track if we should center the chart on the current time (after initial load from URL)
  const [shouldCenterChart, setShouldCenterChart] = useState(false);
  
  // Ref to track if we've already processed URL params (prevents infinite loops)
  const urlParamsProcessedRef = useRef(false);
  
  // Effect to handle URL parameter changes (e.g., navigating from trade history)
  // Only runs once on mount or when URL actually changes
  useEffect(() => {
    // Skip if we've already processed these params
    if (urlParamsProcessedRef.current) return;
    
    if (urlSymbol || urlTime || urlTradeId) {
      urlParamsProcessedRef.current = true;
      
      // Update symbol if provided
      if (urlSymbol) {
        setSelectedSymbol(urlSymbol);
      }
      
      // Update time range if provided
      if (urlTime) {
        const tradeTime = new Date(urlTime);
        setStartTime(subMinutes(tradeTime, 30).toISOString());
        setEndTime(addMinutes(tradeTime, 30).toISOString());
        setPendingTradeTime(urlTime);
      }
      
      // Set pending trade ID for auto-selection
      if (urlTradeId) {
        setPendingTradeId(urlTradeId);
      }
      
      setHasInitializedFromUrl(true);
    }
  }, [urlSymbol, urlTime, urlTradeId]);

  // Playback State
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [currentTime, setCurrentTime] = useState<number>(Date.now());
  const [zoomLevel, setZoomLevel] = useState(1);

  // Filter State
  const [eventFilters, setEventFilters] = useState<Set<string>>(new Set());
  const [showOnlyGateFailures, setShowOnlyGateFailures] = useState(false);
  const [showOnlySlippageOutliers, setShowOnlySlippageOutliers] = useState(false);

  // Compare Mode
  const [compareMode, setCompareMode] = useState(false);
  const [compareSessionId, setCompareSessionId] = useState<string | null>(null);
  const [compareResults, setCompareResults] = useState<any>(null);
  const [showRegimePanel, setShowRegimePanel] = useState(true);

  // UI State
  const [postMortemOpen, setPostMortemOpen] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [timePreset, setTimePreset] = useState("4h");
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  
  // Chart configuration state
  const [chartType, setChartType] = useState<ChartType>("candles");
  const [chartOverlays, setChartOverlays] = useState<ChartOverlays>({
    trades: true,
    decisions: true,
    rejections: false,
    activity: true,
  });

  // Refs
  const timelineRef = useRef<HTMLDivElement>(null);
  const eventListRef = useRef<HTMLDivElement>(null);
  const eventRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());

  // API Queries
  const { data: eventsData, isLoading: loadingEvents, refetch: refetchEvents } = useReplayEvents(
    selectedSymbol,
    startTime,
    endTime,
    { includeDetails: true, limit: 1000 },
    true
  );

  const { data: snapshotData } = useReplaySnapshot(
    selectedSymbol,
    new Date(currentTime).toISOString(),
    true
  );

  // Use time-range based integrity (no session ID required)
  const { data: integrityData } = useIntegrityByTimeRange(
    selectedSymbol,
    startTime,
    endTime,
    true
  );

  const { data: summaryData } = useOutcomeSummary(
    selectedSymbol,
    startTime,
    endTime,
    true
  );

  const { data: featureDictData } = useFeatureDictionary();

  const { data: annotationsData, refetch: refetchAnnotations } = useReplayAnnotations(
    sessionId || "",
    !!sessionId
  );

  const { data: sessionsData } = useQuery({
    queryKey: ["replay-sessions", selectedSymbol],
    queryFn: () => fetchReplaySessions({ symbol: selectedSymbol, limit: 50 }),
  });

  const createAnnotationMutation = useCreateReplayAnnotation();
  const compareSessionsMutation = useCompareReplaySessions();

  // Derived State
  const events = useMemo(() => {
    let evts = eventsData?.events || [];

    // Apply type filters
    if (eventFilters.size > 0) {
      evts = evts.filter(e => !eventFilters.has(e.type));
    }

    // Apply gate failure filter
    if (showOnlyGateFailures) {
      evts = evts.filter(e => 
        e.type === "rejection" || 
        (e.data?.gateResults && Object.values(e.data.gateResults).some((g: any) => !g.passed))
      );
    }

    // Apply slippage filter
    if (showOnlySlippageOutliers) {
      evts = evts.filter(e => 
        e.type === "trade" && Math.abs(e.data?.slippage || 0) > 5
      );
    }

    return evts;
  }, [eventsData, eventFilters, showOnlyGateFailures, showOnlySlippageOutliers]);

  const currentEvent = useMemo(() => {
    if (!events.length) return null;
    
    // If an event is explicitly selected, use that
    if (selectedEventId) {
      const selected = events.find(e => e.id === selectedEventId);
      if (selected) return selected;
    }
    
    // Otherwise find event closest to current time
    let closest = events[0];
    let minDiff = Math.abs(events[0].timestamp - currentTime);
    for (const e of events) {
      const diff = Math.abs(e.timestamp - currentTime);
      if (diff < minDiff) {
        minDiff = diff;
        closest = e;
      }
    }
    return closest;
  }, [events, currentTime, selectedEventId]);

  const nearestDecision = useMemo((): DecisionTrace | null => {
    const decisionEvents = events.filter(e => e.type === "decision" || e.type === "rejection");
    if (!decisionEvents.length) return null;

    let closest = decisionEvents[0];
    let minDiff = Math.abs(decisionEvents[0].timestamp - currentTime);
    for (const e of decisionEvents) {
      const diff = Math.abs(e.timestamp - currentTime);
      if (diff < minDiff) {
        minDiff = diff;
        closest = e;
      }
    }

    return {
      timestamp: closest.timestamp,
      symbol: closest.symbol,
      outcome: closest.type === "decision" ? "approved" : "rejected",
      gateResults: closest.data?.gateResults,
      featureContributions: closest.data?.featureContributions,
      executionMetrics: closest.data?.executionMetrics,
      stages: closest.data?.stageResults ? Object.entries(closest.data.stageResults).map(([name, result]: [string, any]) => ({
        name,
        passed: result.passed ?? true,
        reason: result.reason,
        latencyMs: result.latencyMs || 0,
      })) : [],
      finalDecision: closest.data?.outcome === "approved" ? {
        action: "trade",
        side: closest.data.side,
        size: closest.data.size,
        price: closest.data.price,
        confidence: closest.data.confidence,
      } : undefined,
    };
  }, [events, currentTime]);

  const sessionInfo: SessionInfo | null = useMemo(() => ({
    id: sessionId || "temp",
    symbol: selectedSymbol,
    startTime,
    endTime,
    configVersion: integrityData?.data?.reproducibility?.configVersion || undefined,
    botId: integrityData?.data?.reproducibility?.botId || botId || undefined,
  }), [sessionId, selectedSymbol, startTime, endTime, integrityData, botId]);

  const integrityInfo: IntegrityInfo | null = useMemo(() => {
    if (!integrityData?.data) {
      return { score: "—", snapshotCoverage: "—", dataGaps: 0, datasetHash: "", configVersion: null };
    }
    return {
      score: integrityData.data.integrity.score,
      snapshotCoverage: integrityData.data.integrity.snapshotCoverage,
      dataGaps: integrityData.data.integrity.dataGaps,
      datasetHash: integrityData.data.reproducibility.datasetHash,
      configVersion: integrityData.data.reproducibility.configVersion,
    };
  }, [integrityData]);

  const outcomesInfo = useMemo(() => {
    // First try to use the summary API data
    if (summaryData?.data && summaryData.data.trades.count > 0) {
      return {
        trades: summaryData.data.trades.count,
        pnl: summaryData.data.trades.totalPnl,
        rejects: summaryData.data.decisions.rejected,
        avgLatency: summaryData.data.decisions.avgLatencyMs,
        avgSlippage: summaryData.data.trades.avgSlippageBps,
      };
    }
    
    // Fallback: Calculate from events data (more reliable since it's already working)
    const tradeEvents = events.filter(e => e.type === "trade");
    const rejectionEvents = events.filter(e => e.type === "rejection");
    
    if (tradeEvents.length === 0 && rejectionEvents.length === 0) {
      return null;
    }
    
    const totalPnl = tradeEvents.reduce((sum, e) => sum + (e.data?.pnl || 0), 0);
    const totalSlippage = tradeEvents.reduce((sum, e) => sum + (e.data?.slippage || 0), 0);
    const avgSlippage = tradeEvents.length > 0 ? (totalSlippage / tradeEvents.length).toFixed(2) : "0";
    
    return {
      trades: tradeEvents.length,
      pnl: totalPnl,
      rejects: rejectionEvents.length,
      avgLatency: summaryData?.data?.decisions?.avgLatencyMs || "0",
      avgSlippage: avgSlippage,
    };
  }, [summaryData, events]);

  // Note: Chart data extraction is now handled by ReplayPriceChart component

  // Playback Effect
  useEffect(() => {
    if (!isPlaying || !events.length) return;

    const interval = setInterval(() => {
      setCurrentTime(prev => {
        const next = prev + 1000 * playbackSpeed;
        const endTs = new Date(endTime).getTime();
        if (next >= endTs) {
            setIsPlaying(false);
          return endTs;
          }
          return next;
      });
    }, 100);

    return () => clearInterval(interval);
  }, [isPlaying, playbackSpeed, endTime, events.length]);

  // Set initial current time when events load and handle URL-based trade selection
  useEffect(() => {
    if (events.length > 0) {
      // If we have a pending trade from URL params, find and select it
      if (pendingTradeId || pendingTradeTime) {
        let targetEvent: typeof events[0] | null = null;
        
        // First, try to find by trade ID
        if (pendingTradeId) {
          targetEvent = events.find(e => 
            e.type === "trade" && (
              e.id === pendingTradeId || 
              e.data?.tradeId === pendingTradeId ||
              e.data?.id === pendingTradeId
            )
          ) || null;
        }
        
        // If not found by ID but we have a time, find the closest trade to that time
        if (!targetEvent && pendingTradeTime) {
          const targetTimestamp = new Date(pendingTradeTime).getTime();
          const tradeEvents = events.filter(e => e.type === "trade");
          
          if (tradeEvents.length > 0) {
            // Find the trade closest to the target time
            let closestTrade = tradeEvents[0];
            let closestDiff = Math.abs(tradeEvents[0].timestamp - targetTimestamp);
            
            for (const trade of tradeEvents) {
              const diff = Math.abs(trade.timestamp - targetTimestamp);
              if (diff < closestDiff) {
                closestDiff = diff;
                closestTrade = trade;
              }
            }
            
            // Only use if within 5 minutes of target time
            if (closestDiff < 5 * 60 * 1000) {
              targetEvent = closestTrade;
            }
          }
          
          // If still no trade found, find any event closest to the time
          if (!targetEvent) {
            let closestEvent = events[0];
            let closestDiff = Math.abs(events[0].timestamp - targetTimestamp);
            
            for (const event of events) {
              const diff = Math.abs(event.timestamp - targetTimestamp);
              if (diff < closestDiff) {
                closestDiff = diff;
                closestEvent = event;
              }
            }
            targetEvent = closestEvent;
          }
        }
        
        if (targetEvent) {
          console.log("Replay Studio: Auto-selecting event from URL", targetEvent.id, targetEvent.type);
          setCurrentTime(targetEvent.timestamp);
          setSelectedEventId(targetEvent.id);
          
          // Center the chart on this event
          setShouldCenterChart(true);
          // Reset after a short delay so it doesn't keep centering
          setTimeout(() => setShouldCenterChart(false), 500);
          
          // Scroll to the event in the list after a short delay to ensure DOM is ready
          setTimeout(() => {
            const element = eventRefsMap.current.get(targetEvent!.id);
            if (element) {
              element.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          }, 200);
        } else if (pendingTradeTime) {
          // No event found, just set the time and center chart
          setCurrentTime(new Date(pendingTradeTime).getTime());
          setShouldCenterChart(true);
          setTimeout(() => setShouldCenterChart(false), 500);
        } else {
          setCurrentTime(events[0].timestamp);
        }
        
        // Clear pending state so we don't re-trigger
        setPendingTradeId(null);
        setPendingTradeTime(null);
      } else if (!hasInitializedFromUrl) {
        // Default behavior when no URL params
        setCurrentTime(events[0].timestamp);
      }
    }
  }, [events.length, pendingTradeId, pendingTradeTime, hasInitializedFromUrl]);

  // Handlers
  const handleToggleFilter = (type: string) => {
    setEventFilters(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
    } else {
        next.add(type);
      }
      return next;
    });
  };

  const handleJumpToEvent = useCallback((ts: number) => {
    setCurrentTime(ts);
    setIsPlaying(false);
    
    // Find the closest event to the timestamp and scroll to it
    if (events.length > 0) {
      let closestEvent = events[0];
      let closestDiff = Math.abs(events[0].timestamp - ts);
      
      for (const event of events) {
        const diff = Math.abs(event.timestamp - ts);
        if (diff < closestDiff) {
          closestDiff = diff;
          closestEvent = event;
        }
      }
      
      // Scroll to the event
      const eventEl = eventRefsMap.current.get(closestEvent.id);
      if (eventEl) {
        eventEl.scrollIntoView({ behavior: "smooth", block: "center" });
        setSelectedEventId(closestEvent.id);
      }
    }
  }, [events]);

  const handleNavigateEvent = useCallback((direction: "prev" | "next") => {
    if (!events.length) return;
    
    // Find current index based on selectedEventId or currentTime
    let currentIdx = -1;
    if (selectedEventId) {
      currentIdx = events.findIndex(e => e.id === selectedEventId);
    }
    if (currentIdx === -1) {
      // Find by timestamp
      currentIdx = events.findIndex(e => e.timestamp >= currentTime);
      if (currentIdx === -1) currentIdx = events.length - 1;
    }

    let targetIdx: number;
    if (direction === "prev") {
      targetIdx = currentIdx <= 0 ? events.length - 1 : currentIdx - 1;
    } else {
      targetIdx = currentIdx >= events.length - 1 ? 0 : currentIdx + 1;
    }

    const targetEvent = events[targetIdx];
    setCurrentTime(targetEvent.timestamp);
    setSelectedEventId(targetEvent.id);
    
    // Scroll to event
    const eventEl = eventRefsMap.current.get(targetEvent.id);
    if (eventEl) {
      eventEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [events, selectedEventId, currentTime]);
  
  // Keep old function for playback controls (decision-only navigation)
  const handleNavigateDecision = (direction: "prev" | "next") => {
    const decisionEvents = events.filter(e => e.type === "decision" || e.type === "rejection" || e.type === "trade");
    if (!decisionEvents.length) return;

    const currentIdx = decisionEvents.findIndex(e => e.timestamp >= currentTime);
    let targetIdx: number;

    if (direction === "prev") {
      targetIdx = currentIdx <= 0 ? decisionEvents.length - 1 : currentIdx - 1;
    } else {
      targetIdx = currentIdx >= decisionEvents.length - 1 ? 0 : currentIdx + 1;
    }

    const targetEvent = decisionEvents[targetIdx];
    setCurrentTime(targetEvent.timestamp);
    setSelectedEventId(targetEvent.id);
  };

  const [loadSessionOpen, setLoadSessionOpen] = useState(false);

  const handleLoadSession = (session: any) => {
    // Load the selected session
    setSessionId(session.id);
    setSelectedSymbol(session.symbol);
    setStartTime(session.start_time);
    setEndTime(session.end_time);
    setLoadSessionOpen(false);
    toast.success(`Session "${session.session_name || 'Unnamed'}" loaded`);
    refetchEvents();
  };

  const handleSaveSession = async () => {
    try {
      // Create a new session if one doesn't exist
      if (!sessionId) {
        const sessionName = `Replay ${selectedSymbol} ${format(new Date(), "MMM d HH:mm")}`;
        const result = await createReplaySession({
          symbol: selectedSymbol,
          startTime,
          endTime,
          sessionName,
        });
        if (result.success && result.data) {
          setSessionId(result.data.id);
          toast.success(`Session saved as "${sessionName}"`);
        } else {
          toast.error("Failed to save session");
        }
      } else {
        toast.success("Session already saved");
      }
    } catch (error: any) {
      console.error("Save session error:", error);
      toast.error(`Failed to save session: ${error?.message || 'Unknown error'}`);
    }
  };

  const handleCreateAnnotation = async (data: { title: string; content: string; tags: string[] }) => {
    let currentSessionId = sessionId;
    
    // Auto-create a session if one doesn't exist
    if (!currentSessionId) {
      try {
        console.log("[PostMortem] Creating session for annotation...");
        const result = await createReplaySession({
          symbol: selectedSymbol,
          startTime,
          endTime,
          sessionName: `Replay ${format(new Date(), "MMM d HH:mm")}`,
        });
        console.log("[PostMortem] Session creation result:", result);
        if (result.success && result.data) {
          currentSessionId = result.data.id;
          setSessionId(currentSessionId);
          toast.success("Session created");
        } else {
          toast.error("Failed to create session for annotation");
          return;
        }
      } catch (error: any) {
        console.error("[PostMortem] Session creation error:", error);
        toast.error(`Failed to create session: ${error?.message || 'Unknown error'}`);
        return;
      }
    }
    
    try {
      console.log("[PostMortem] Saving annotation to session:", currentSessionId);
      await createAnnotationMutation.mutateAsync({
        sessionId: currentSessionId,
        timestamp: new Date(currentTime).toISOString(),
        title: data.title,
        content: data.content,
        tags: data.tags,
      });
      console.log("[PostMortem] Annotation saved, refetching...");
      // Small delay to ensure the query key update is processed
      setTimeout(() => refetchAnnotations(), 100);
      toast.success("Annotation saved!");
    } catch (error: any) {
      console.error("[PostMortem] Annotation save error:", error);
      toast.error(`Failed to save annotation: ${error?.message || 'Unknown error'}`);
    }
  };

  const handleRunCompare = async () => {
    if (!compareSessionId) return;
    try {
      const result = await compareSessionsMutation.mutateAsync({
        baselineSessionId: sessionId || undefined,
        compareSessionId,
        symbol: selectedSymbol,
        timeRange: { start: startTime, end: endTime },
      });
      setCompareResults(result.data);
      toast.success("Comparison complete");
    } catch (error) {
      toast.error("Comparison failed");
    }
  };

  // Progress through timeline
  const timelineProgress = useMemo(() => {
    const start = new Date(startTime).getTime();
    const end = new Date(endTime).getTime();
    const total = end - start;
    if (total <= 0) return 0;
    return ((currentTime - start) / total) * 100;
  }, [currentTime, startTime, endTime]);

  return (
    <TooltipProvider>
      <div className="flex flex-col h-full max-h-screen overflow-hidden">
        {/* Run Bar */}
        <DashBar />

        {/* Header Controls - Sticky */}
        <div className="flex-shrink-0 p-4 border-b bg-card/95 backdrop-blur-sm sticky top-0 z-20">
          <div className="flex items-center justify-between gap-4 mb-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold">Replay Studio</h1>
              <Badge variant="outline" className="text-xs">Forensic Mode</Badge>
          </div>

            <div className="flex items-center gap-3">
              {/* Symbol Selector */}
              <Select value={selectedSymbol} onValueChange={setSelectedSymbol}>
                <SelectTrigger className="w-[160px] h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="BTC-USDT-SWAP">BTC-USDT-SWAP</SelectItem>
                  <SelectItem value="ETH-USDT-SWAP">ETH-USDT-SWAP</SelectItem>
                  <SelectItem value="SOL-USDT-SWAP">SOL-USDT-SWAP</SelectItem>
                  <SelectItem value="BTCUSDT">BTCUSDT (Spot)</SelectItem>
                  <SelectItem value="ETHUSDT">ETHUSDT (Spot)</SelectItem>
                  <SelectItem value="SOLUSDT">SOLUSDT (Spot)</SelectItem>
                </SelectContent>
              </Select>

              <Separator orientation="vertical" className="h-6" />

              {/* Quick Time Presets - Segmented Control Style */}
              <div className="flex rounded-lg border bg-muted/50 p-1">
                {[
                  { key: "1h", label: "1h", hours: 1 },
                  { key: "4h", label: "4h", hours: 4 },
                  { key: "12h", label: "12h", hours: 12 },
                  { key: "24h", label: "24h", hours: 24 },
                  { key: "3d", label: "3d", hours: 72 },
                  { key: "7d", label: "7d", hours: 168 },
                ].map(({ key, label, hours }) => (
                  <Button
                    key={key}
                    variant={timePreset === key ? "default" : "ghost"}
                    size="sm"
                    className="h-7 px-2.5 text-xs"
                    onClick={() => {
                      setTimePreset(key);
                      setStartTime(subHours(new Date(), hours).toISOString());
                      setEndTime(new Date().toISOString());
                    }}
                  >
                    {label}
                  </Button>
                ))}
              </div>

              {/* Custom Date Range Button */}
              <div className="relative">
                <Button
                  variant={timePreset === "custom" ? "default" : "outline"}
                  size="sm"
                  className="gap-2 h-9"
                  onClick={() => setDatePickerOpen(!datePickerOpen)}
                >
                  <Calendar className="h-4 w-4" />
                  {timePreset === "custom" 
                    ? `${format(new Date(startTime), "MMM d, HH:mm")} → ${format(new Date(endTime), "MMM d, HH:mm")}`
                    : "Custom"}
                </Button>

                {/* Custom Date Range Popover */}
                {datePickerOpen && (
                  <div className="absolute right-0 top-11 w-[360px] rounded-lg border bg-card shadow-xl z-50 p-4">
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-medium">Custom Time Range</p>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          onClick={() => setDatePickerOpen(false)}
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <Label className="text-xs text-muted-foreground">Start</Label>
                          <Input
                            type="datetime-local"
                            value={startTime.slice(0, 16)}
                            onChange={(e) => {
                              setStartTime(new Date(e.target.value).toISOString());
                              setTimePreset("custom");
                            }}
                            className="h-9 text-sm"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs text-muted-foreground">End</Label>
                          <Input
                            type="datetime-local"
                            value={endTime.slice(0, 16)}
                            onChange={(e) => {
                              setEndTime(new Date(e.target.value).toISOString());
                              setTimePreset("custom");
                            }}
                            className="h-9 text-sm"
                          />
                        </div>
                      </div>

                      <div className="border-t pt-3">
                        <p className="text-xs text-muted-foreground mb-2">Quick Select</p>
                        <div className="grid grid-cols-3 gap-1.5">
                          {[
                            { label: "Last 1h", hours: 1 },
                            { label: "Last 4h", hours: 4 },
                            { label: "Last 12h", hours: 12 },
                            { label: "Last 24h", hours: 24 },
                            { label: "Last 3d", hours: 72 },
                            { label: "Last 7d", hours: 168 },
                          ].map(({ label, hours }) => (
                            <Button
                              key={label}
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => {
                                setStartTime(subHours(new Date(), hours).toISOString());
                                setEndTime(new Date().toISOString());
                                setTimePreset("custom");
                              }}
                            >
                              {label}
                            </Button>
                          ))}
                        </div>
                      </div>

                      <div className="flex gap-2 pt-2">
                        <Button
                          size="sm"
                          className="flex-1"
                          onClick={() => {
                            setDatePickerOpen(false);
                            refetchEvents();
                          }}
                        >
                          Apply
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setDatePickerOpen(false)}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <Separator orientation="vertical" className="h-6" />

              {/* Load Session Dropdown */}
              <DropdownMenu open={loadSessionOpen} onOpenChange={setLoadSessionOpen}>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <RefreshCw className="h-4 w-4 mr-1" />
                    Load
                    <ChevronDown className="h-3 w-3 ml-1" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-72">
                  <DropdownMenuLabel>Recent Sessions</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {sessionsData?.data && sessionsData.data.length > 0 ? (
                    <ScrollArea className="h-[200px]">
                      {sessionsData.data.slice(0, 10).map((session: any) => (
                        <DropdownMenuItem
                          key={session.id}
                          onClick={() => handleLoadSession(session)}
                          className="flex flex-col items-start py-2"
                        >
                          <span className="font-medium text-sm">
                            {session.session_name || `Session ${session.id.slice(0, 8)}`}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {session.symbol} • {format(new Date(session.start_time), "MMM d, HH:mm")} - {format(new Date(session.end_time), "HH:mm")}
                          </span>
                        </DropdownMenuItem>
                      ))}
                    </ScrollArea>
                  ) : (
                    <div className="p-4 text-center text-sm text-muted-foreground">
                      No saved sessions yet
                    </div>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>

              <Button variant="outline" size="sm" onClick={handleSaveSession}>
                <Save className="h-4 w-4 mr-1" />
                Save
              </Button>
              <Button variant="outline" size="sm" onClick={() => setPostMortemOpen(true)} className="relative">
                <BookOpen className="h-4 w-4 mr-1" />
                Post-Mortem
                {(annotationsData?.data?.length || 0) > 0 && (
                  <Badge variant="default" className="absolute -top-1.5 -right-1.5 h-4 min-w-4 px-1 text-[10px]">
                    {annotationsData?.data?.length}
                  </Badge>
                )}
              </Button>
            </div>
        </div>

          {/* Header Summary */}
          <ReplayHeaderSummary
            session={sessionInfo}
            integrity={integrityInfo}
            outcomes={outcomesInfo}
            compareMode={compareMode}
            onToggleCompare={() => setCompareMode(!compareMode)}
          />
        </div>

        {/* Main Content Area */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left: Chart + Timeline */}
          <div className="flex-1 flex flex-col overflow-hidden border-r">
            {/* Chart Controls + Legend */}
            <div className="flex-shrink-0 p-2 border-b flex items-center justify-between gap-4">
              <div className="flex items-center gap-4 flex-1 min-w-0">
                <AnomalyLanes events={events} onJumpTo={handleJumpToEvent} />
                <ReplayChartLegend 
                  className="flex-shrink-0 hidden lg:flex" 
                  tradeCount={events.filter(e => e.type === "trade").length}
                  chartType={chartType}
                />
              </div>
              <ReplayChartControls
                chartType={chartType}
                onChartTypeChange={setChartType}
                overlays={chartOverlays}
                onOverlaysChange={setChartOverlays}
                suggestedChartType={
                  // Smart suggestions based on timeframe
                  timePreset === "24h" || timePreset === "3d" || timePreset === "7d" 
                    ? "line" 
                    : playbackSpeed >= 4 
                      ? "line" 
                      : undefined
                }
                className="flex-shrink-0"
              />
            </div>

            {/* Price Chart - Fixed height to give more room to event list */}
            <div className="flex-shrink-0 h-[240px] p-3 relative border-b">
              {/* Compare Mode Panel Overlay */}
              <CompareModePanel
                isOpen={compareMode}
                sessions={sessionsData?.data || []}
                currentSessionId={sessionId}
                compareSessionId={compareSessionId}
                onSelectCompareSession={setCompareSessionId}
                compareResults={compareResults}
                isComparing={compareSessionsMutation.isPending}
                onRunCompare={handleRunCompare}
              />

              {loadingEvents ? (
                <div className="h-full flex items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : events.length === 0 ? (
                <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
                  No data available for this time range
                </div>
              ) : (
                <ReplayPriceChart
                  events={events}
                  currentTime={currentTime}
                  onTimeClick={handleJumpToEvent}
                  height={210}
                  className="h-full"
                  symbol={selectedSymbol}
                  startTime={startTime}
                  endTime={endTime}
                  chartType={chartType}
                  onChartTypeChange={setChartType}
                  overlays={chartOverlays}
                  onOverlaysChange={setChartOverlays}
                  timeRangeMinutes={
                    timePreset === "1h" ? 60 :
                    timePreset === "4h" ? 240 :
                    timePreset === "12h" ? 720 :
                    timePreset === "24h" ? 1440 :
                    timePreset === "3d" ? 4320 :
                    timePreset === "7d" ? 10080 : 240
                  }
                  playbackSpeed={playbackSpeed}
                  centerOnCurrentTime={shouldCenterChart}
                />
              )}
            </div>

            {/* Regime/Signal Panel */}
            {showRegimePanel && (
              <RegimeSignalPanel events={events} currentTime={currentTime} />
            )}

            {/* Playback Controls + Timeline Scrubber - Sticky */}
            <div className="flex-shrink-0 p-4 border-t bg-card/95 backdrop-blur-sm sticky bottom-0 z-10">
              {/* Playback Controls */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setCurrentTime(new Date(startTime).getTime())}
                  >
                    <SkipBack className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleNavigateDecision("prev")}
                  >
                    <StepBack className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="default"
                    size="icon"
                    onClick={() => setIsPlaying(!isPlaying)}
                  >
                    {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleNavigateDecision("next")}
                  >
                    <StepForward className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setCurrentTime(new Date(endTime).getTime())}
                  >
                    <SkipForward className="h-4 w-4" />
                  </Button>
                </div>

                <div className="flex items-center gap-4">
                  <span className="text-sm font-mono">{formatDateTime(currentTime)}</span>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Speed:</span>
                    <Select
                      value={playbackSpeed.toString()}
                      onValueChange={(v) => setPlaybackSpeed(parseFloat(v))}
                    >
                      <SelectTrigger className="w-[70px] h-7 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="0.5">0.5x</SelectItem>
                        <SelectItem value="1">1x</SelectItem>
                        <SelectItem value="2">2x</SelectItem>
                        <SelectItem value="5">5x</SelectItem>
                        <SelectItem value="10">10x</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => setZoomLevel(Math.max(0.5, zoomLevel - 0.5))}
                    >
                      <ZoomOut className="h-3 w-3" />
                    </Button>
                    <span className="text-xs w-8 text-center">{zoomLevel}x</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => setZoomLevel(Math.min(10, zoomLevel + 0.5))}
                    >
                      <ZoomIn className="h-3 w-3" />
                    </Button>
                  </div>

                  <Separator orientation="vertical" className="h-6" />

                  {/* Chart overlay toggles */}
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant={showRegimePanel ? "secondary" : "ghost"}
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => setShowRegimePanel(!showRegimePanel)}
                        >
                          <Layers className="h-3.5 w-3.5" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Toggle Regime/Signal Panel</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>

        {/* Timeline Scrubber */}
              <div className="relative">
                <Progress value={timelineProgress} className="h-2" />
                {/* Event markers on timeline */}
                <div className="absolute inset-0 pointer-events-none">
                  {events.slice(0, 200).map((e) => {
                    const start = new Date(startTime).getTime();
                    const end = new Date(endTime).getTime();
                    const pos = ((e.timestamp - start) / (end - start)) * 100;
                    if (pos < 0 || pos > 100) return null;
                    return (
                      <div
                        key={e.id}
                        className={cn(
                          "absolute top-0 w-0.5 h-2 pointer-events-auto cursor-pointer",
                          e.type === "trade" ? "bg-green-500" :
                          e.type === "decision" ? "bg-blue-500" :
                          e.type === "rejection" ? "bg-red-500" :
                          e.type === "alert" ? "bg-yellow-500" :
                          "bg-purple-500/50"
                        )}
                        style={{ left: `${pos}%` }}
                        onClick={() => handleJumpToEvent(e.timestamp)}
                      />
                    );
                  })}
                </div>
              </div>

              {/* Filter Chips */}
              <div className="mt-3 flex items-center justify-between">
                <EventFilterChips
                  events={eventsData?.events || []}
                  filters={eventFilters}
                  onToggleFilter={handleToggleFilter}
                />
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-xs">
                    <Checkbox
                      checked={showOnlyGateFailures}
                      onCheckedChange={(c) => setShowOnlyGateFailures(!!c)}
                    />
                    Gate Failures Only
                  </label>
                  <label className="flex items-center gap-2 text-xs">
                    <Checkbox
                      checked={showOnlySlippageOutliers}
                      onCheckedChange={(c) => setShowOnlySlippageOutliers(!!c)}
                    />
                    Slippage &gt;5bps
                  </label>
                </div>
          </div>
        </div>

            {/* Event List - Expandable to fill remaining space */}
            <div className="flex-1 min-h-0 border-t">
              <ScrollArea className="h-full">
                {/* Table header */}
                <div className="sticky top-0 z-10 bg-card border-b px-2 py-1.5 grid grid-cols-[60px_70px_1fr_80px] gap-2 text-xs font-medium text-muted-foreground">
                  <span>Time</span>
                  <span>Type</span>
                  <span>Details</span>
                  <span className="text-right">Price</span>
                </div>
                <div className="p-1">
                  {events.slice(0, 200).map((event) => {
                    const isSelected = event.id === selectedEventId;
                    // Only show "current" indicator during playback when no event is explicitly selected
                    const isCurrentPlayback = !selectedEventId && Math.abs(event.timestamp - currentTime) < 1000;
                    
                    // Extract price from various event types
                    let eventPrice = 0;
                    if (event.type === "trade") {
                      eventPrice = event.data?.price || 0;
                    } else if (event.type === "snapshot") {
                      eventPrice = event.data?.marketData?.price || event.data?.price || 0;
                    } else if (event.type === "decision" || event.type === "rejection") {
                      eventPrice = event.data?.marketContext?.price || 0;
                    }
                    
                    return (
                      <div
                        key={event.id}
                        ref={(el) => {
                          if (el) {
                            eventRefsMap.current.set(event.id, el);
                          } else {
                            eventRefsMap.current.delete(event.id);
                          }
                        }}
                        className={cn(
                          "grid grid-cols-[60px_70px_1fr_80px] gap-2 items-center px-2 py-1.5 rounded cursor-pointer transition-colors text-xs",
                          // Selected event takes priority (user clicked)
                          isSelected ? "bg-primary/10 ring-1 ring-primary" :
                          // During playback, highlight the current event
                          isCurrentPlayback ? "bg-muted ring-1 ring-muted-foreground/30" : 
                          "hover:bg-muted/50"
                        )}
                        onClick={() => {
                          setSelectedEventId(event.id);
                          handleJumpToEvent(event.timestamp);
                        }}
                      >
                        {/* Time */}
                        <span className="font-mono text-muted-foreground">
                          {formatTime(event.timestamp)}
                        </span>
                        
                        {/* Type Badge */}
                        <Badge
                          variant={
                            event.type === "trade" ? "default" :
                            event.type === "rejection" ? "destructive" :
                            event.type === "decision" ? "outline" :
                            "secondary"
                          }
                          className="text-[10px] h-5 justify-center"
                        >
                          {event.type}
                        </Badge>
                        
                        {/* Details */}
                        <span className="truncate">
                          {event.type === "trade" && (
                            <span className="flex items-center gap-2">
                              <span className={cn(
                                "font-medium min-w-[36px]",
                                event.data?.side === "buy" || event.data?.side === "long" ? "text-green-500" : "text-red-500"
                              )}>
                                {event.data?.side?.toUpperCase()}
                              </span>
                              <span className="text-foreground font-mono">
                                {typeof event.data?.size === 'number' 
                                  ? event.data.size < 0.01 
                                    ? event.data.size.toFixed(6)
                                    : event.data.size < 1 
                                      ? event.data.size.toFixed(4)
                                      : event.data.size.toFixed(2)
                                  : event.data?.size}
                              </span>
                              {typeof event.data?.pnl === 'number' && (
                                <span className={cn(
                                  "font-medium",
                                  event.data.pnl >= 0 ? "text-green-500" : "text-red-500"
                                )}>
                                  {event.data.pnl >= 0 ? "+" : ""}{event.data.pnl.toFixed(2)}
                                </span>
                              )}
                              {typeof event.data?.slippage === 'number' && (
                                <span className="text-muted-foreground">
                                  {event.data.slippage.toFixed(1)}bp
                                </span>
                              )}
                              {event.data?.source && (
                                <Badge variant="outline" className="text-[9px] h-4 px-1">
                                  {event.data.source}
                                </Badge>
                              )}
                            </span>
                          )}
                          {(event.type === "decision" || event.type === "rejection") && (
                            <span className="flex items-center gap-1.5">
                              <span className={event.type === "decision" ? "text-green-500 font-medium" : "text-red-500 font-medium"}>
                                {event.data?.outcome?.toUpperCase() || event.type.toUpperCase()}
                              </span>
                              <span className="text-muted-foreground truncate">
                                {event.data?.reason || "—"}
                              </span>
                            </span>
                          )}
                          {event.type === "alert" && (
                            <span className="text-yellow-500 truncate">{event.data?.message}</span>
                          )}
                          {event.type === "snapshot" && (
                            <span className="text-muted-foreground">Market snapshot</span>
                          )}
                        </span>
                        
                        {/* Price */}
                        <span className="text-right font-mono tabular-nums">
                          {eventPrice > 0 ? formatPrice(eventPrice) : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
            </div>
          </div>

          {/* Right: Context Panel */}
          <div className="w-[400px] flex-shrink-0 overflow-hidden">
            <ContextPanel
              currentEvent={currentEvent}
              nearestDecision={nearestDecision}
              snapshot={snapshotData?.data}
              featureDictionary={featureDictData?.data || {}}
              position={snapshotData?.data?.currentPosition}
              onNavigate={handleNavigateEvent}
            />
          </div>
        </div>

        {/* Post-Mortem Panel */}
        <PostMortemPanel
          isOpen={postMortemOpen}
          onClose={() => setPostMortemOpen(false)}
          session={sessionInfo}
          outcomes={outcomesInfo}
          annotations={annotationsData?.data || []}
          onCreateAnnotation={handleCreateAnnotation}
        />
      </div>
    </TooltipProvider>
  );
}

