import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { DashBar } from "../../components/DashBar";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bot,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  Filter,
  FlaskConical,
  GitBranch,
  GitCompare,
  HelpCircle,
  Info,
  Layers,
  LineChart,
  Loader2,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Shield,
  Sparkles,
  Tag,
  Target,
  TrendingDown,
  TrendingUp,
  Upload,
  XCircle,
  Zap,
} from "lucide-react";
import {
  LineChart as RechartsLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
  Area,
  AreaChart,
  ComposedChart,
  Bar,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Progress } from "../../components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Separator } from "../../components/ui/separator";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../../components/ui/accordion";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Checkbox } from "../../components/ui/checkbox";
import { Switch } from "../../components/ui/switch";
import { Alert, AlertDescription, AlertTitle } from "../../components/ui/alert";
import toast from "react-hot-toast";
import {
  useBacktests,
  useBacktestDetail,
  useDatasets,
  useCreateBacktest,
  useRerunBacktest,
  usePromoteBacktestConfig,
  useDeleteBacktest,
  useWfoRuns,
  useCreateWfoRun,
  useWfoRun,
  useResearchStrategies,
  useBacktestPreflight,
} from "../../lib/api/hooks";
import { fetchWarmStartState, WarmStartResponse } from "../../lib/api/client";

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const formatDate = (d: string) => new Date(d).toLocaleDateString();
const formatDateTime = (d: string) => new Date(d).toLocaleString();
const formatPct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const formatCurrency = (v: number) => `$${v.toLocaleString()}`;

const getStatusConfig = (status: string) => {
  switch (status) {
    case "completed": return { color: "text-emerald-500", bg: "bg-emerald-500/10", icon: CheckCircle2 };
    case "running": return { color: "text-blue-500", bg: "bg-blue-500/10", icon: Loader2 };
    case "pending": return { color: "text-amber-500", bg: "bg-amber-500/10", icon: Clock };
    case "failed": return { color: "text-red-500", bg: "bg-red-500/10", icon: XCircle };
    default: return { color: "text-muted-foreground", bg: "bg-muted/10", icon: HelpCircle };
  }
};

// ============================================================================
// LIVE STATE CARD - Requirements 4.8
// ============================================================================

/**
 * LiveStateCard displays the current live trading state when warm start is available.
 * This component fetches and displays:
 * - Current live positions (symbol, size, entry price, unrealized PnL)
 * - Current account state (equity, margin, balance)
 * - Loading and error states with retry option
 * 
 * Validates: Requirements 4.8
 */
function LiveStateCard() {
  const [isExpanded, setIsExpanded] = useState(false);
  
  // Fetch warm start state - Requirements 4.8
  const { 
    data: warmStartState, 
    isLoading, 
    error,
    refetch,
  } = useQuery<WarmStartResponse>({
    queryKey: ["warm-start-state-display"],
    queryFn: fetchWarmStartState,
    staleTime: 30000, // 30 seconds
    refetchInterval: 60000, // Refresh every minute
    retry: 1, // Only retry once on failure
  });

  // Loading state
  if (isLoading) {
    return (
      <Card className="border-blue-500/30 bg-blue-500/5">
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
            <div>
              <p className="text-sm font-medium">Loading Live State</p>
              <p className="text-xs text-muted-foreground">Fetching current positions and account state...</p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Error state with retry
  if (error) {
    return (
      <Card className="border-red-500/30 bg-red-500/5">
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-red-500" />
              <div>
                <p className="text-sm font-medium text-red-600">Failed to Load Live State</p>
                <p className="text-xs text-muted-foreground">
                  {error instanceof Error ? error.message : "Unable to fetch current live state"}
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // No data state
  if (!warmStartState) {
    return (
      <Card className="border-muted">
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <Activity className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">No Live State Available</p>
              <p className="text-xs text-muted-foreground">Live trading state is not currently available.</p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Calculate total unrealized PnL from positions
  const totalUnrealizedPnl = warmStartState.positions.reduce((sum, pos) => {
    // If unrealized_pnl is available, use it; otherwise estimate from position data
    if (pos.unrealized_pnl !== undefined) {
      return sum + pos.unrealized_pnl;
    }
    return sum;
  }, 0);

  return (
    <Card className={cn(
      "transition-all",
      warmStartState.is_stale 
        ? "border-amber-500/30 bg-amber-500/5" 
        : "border-emerald-500/30 bg-emerald-500/5"
    )}>
      <CardContent className="p-4 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn(
              "rounded-full p-2",
              warmStartState.is_stale ? "bg-amber-500/10" : "bg-emerald-500/10"
            )}>
              <Activity className={cn(
                "h-5 w-5",
                warmStartState.is_stale ? "text-amber-500" : "text-emerald-500"
              )} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">Live Trading State</p>
                <Badge variant="outline" className={cn(
                  "text-[10px]",
                  warmStartState.is_stale 
                    ? "text-amber-500 border-amber-500/30" 
                    : "text-emerald-500 border-emerald-500/30"
                )}>
                  <Clock className="h-3 w-3 mr-1" />
                  {warmStartState.age_seconds < 60 
                    ? `${Math.floor(warmStartState.age_seconds)}s ago`
                    : `${Math.floor(warmStartState.age_seconds / 60)}m ago`
                  }
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {warmStartState.positions.length} open position{warmStartState.positions.length !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button 
              variant="ghost" 
              size="sm" 
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        {/* Staleness Warning */}
        {warmStartState.is_stale && (
          <Alert className="border-amber-500/50 bg-amber-500/10 py-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <AlertDescription className="text-xs text-amber-600">
              Live state is {Math.floor(warmStartState.age_seconds / 60)} minutes old. Click refresh to update.
            </AlertDescription>
          </Alert>
        )}

        {/* Validation Errors */}
        {!warmStartState.is_valid && warmStartState.validation_errors.length > 0 && (
          <Alert variant="destructive" className="py-2">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="text-xs">
              {warmStartState.validation_errors.join(", ")}
            </AlertDescription>
          </Alert>
        )}

        {/* Account State Summary */}
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-lg border bg-background p-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Equity</p>
            <p className="text-lg font-bold text-emerald-500">
              ${warmStartState.account_state.equity?.toLocaleString() || "0"}
            </p>
          </div>
          <div className="rounded-lg border bg-background p-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Balance</p>
            <p className="text-lg font-bold">
              ${warmStartState.account_state.balance?.toLocaleString() || "0"}
            </p>
          </div>
          <div className="rounded-lg border bg-background p-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Margin</p>
            <p className="text-lg font-bold">
              ${warmStartState.account_state.margin?.toLocaleString() || "0"}
            </p>
          </div>
          <div className="rounded-lg border bg-background p-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Available</p>
            <p className="text-lg font-bold">
              ${warmStartState.account_state.available_balance?.toLocaleString() || "0"}
            </p>
          </div>
        </div>

        {/* Expanded Positions View */}
        {isExpanded && warmStartState.positions.length > 0 && (
          <div className="space-y-3 pt-2 border-t">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Current Live Positions
              </p>
              {totalUnrealizedPnl !== 0 && (
                <Badge variant="outline" className={cn(
                  "text-xs",
                  totalUnrealizedPnl >= 0 
                    ? "text-emerald-500 border-emerald-500/30" 
                    : "text-red-500 border-red-500/30"
                )}>
                  Total uPnL: {totalUnrealizedPnl >= 0 ? '+' : ''}${totalUnrealizedPnl.toFixed(2)}
                </Badge>
              )}
            </div>
            
            <div className="rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/30">
                    <th className="text-left p-2 font-medium text-xs">Symbol</th>
                    <th className="text-center p-2 font-medium text-xs">Side</th>
                    <th className="text-right p-2 font-medium text-xs">Size</th>
                    <th className="text-right p-2 font-medium text-xs">Entry Price</th>
                    <th className="text-right p-2 font-medium text-xs">Stop Loss</th>
                    <th className="text-right p-2 font-medium text-xs">Take Profit</th>
                    <th className="text-right p-2 font-medium text-xs">uPnL</th>
                  </tr>
                </thead>
                <tbody>
                  {warmStartState.positions.map((pos, idx) => (
                    <tr key={idx} className="border-b border-border/30 last:border-0">
                      <td className="p-2 font-medium">{pos.symbol}</td>
                      <td className="p-2 text-center">
                        <Badge 
                          variant="outline" 
                          className={cn(
                            "text-[10px] px-1.5",
                            pos.side === "long" || pos.side === "buy"
                              ? "text-emerald-500 border-emerald-500/30 bg-emerald-500/10"
                              : "text-red-500 border-red-500/30 bg-red-500/10"
                          )}
                        >
                          {pos.side?.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="p-2 text-right font-mono">{pos.size}</td>
                      <td className="p-2 text-right font-mono">${pos.entry_price?.toLocaleString()}</td>
                      <td className="p-2 text-right font-mono text-red-500">
                        {pos.stop_loss ? `$${pos.stop_loss.toLocaleString()}` : '—'}
                      </td>
                      <td className="p-2 text-right font-mono text-emerald-500">
                        {pos.take_profit ? `$${pos.take_profit.toLocaleString()}` : '—'}
                      </td>
                      <td className={cn(
                        "p-2 text-right font-mono",
                        (pos.unrealized_pnl ?? 0) >= 0 ? "text-emerald-500" : "text-red-500"
                      )}>
                        {pos.unrealized_pnl !== undefined 
                          ? `${pos.unrealized_pnl >= 0 ? '+' : ''}$${pos.unrealized_pnl.toFixed(2)}`
                          : '—'
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Snapshot Time */}
            <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1">
              <span>Snapshot Time</span>
              <span>{new Date(warmStartState.snapshot_time).toLocaleString()}</span>
            </div>
          </div>
        )}

        {/* Collapsed Positions Preview */}
        {!isExpanded && warmStartState.positions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {warmStartState.positions.slice(0, 5).map((pos, idx) => (
              <Badge 
                key={idx}
                variant="outline" 
                className="text-xs"
              >
                <span className={cn(
                  "mr-1",
                  pos.side === "long" || pos.side === "buy" ? "text-emerald-500" : "text-red-500"
                )}>
                  {pos.side === "long" || pos.side === "buy" ? "▲" : "▼"}
                </span>
                {pos.symbol} {pos.size}
              </Badge>
            ))}
            {warmStartState.positions.length > 5 && (
              <Badge variant="outline" className="text-xs text-muted-foreground">
                +{warmStartState.positions.length - 5} more
              </Badge>
            )}
          </div>
        )}

        {/* No Positions State */}
        {warmStartState.positions.length === 0 && (
          <div className="text-center py-2">
            <p className="text-xs text-muted-foreground">No open positions</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// RUNS TAB
// ============================================================================

function RunsTab({
  onSelectRun,
  selectedForCompare,
  onToggleCompare,
}: {
  onSelectRun: (run: any) => void;
  selectedForCompare: string[];
  onToggleCompare: (id: string) => void;
}) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [symbolFilter, setSymbolFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  
  // Fetch real backtest data from API
  const { data: backtestsData, isLoading, error, refetch } = useBacktests({ status: statusFilter || undefined });
  
  // Transform API data (no fallback to mocks)
  const runs = useMemo(() => {
    if (!backtestsData?.backtests) return [];
    return backtestsData.backtests.map((bt: any) => ({
      id: bt.id,
      name: bt.name || `Run ${bt.id}`,
      strategy: bt.strategy_id || bt.profile_id || "unknown",
      symbol: bt.symbol,
      exchange: bt.exchange || "okx",
      timeframe: bt.timeframe || "5m",
      startDate: bt.start_date,
      endDate: bt.end_date,
      status: bt.status,
      createdAt: bt.created_at,
      completedAt: bt.completed_at,
      initialCapital: bt.initial_capital || 10000,
      metrics: bt.results ? {
        returnPct: bt.results.return_pct ?? bt.results.total_return_pct ?? 0,
        maxDdPct: bt.results.max_drawdown_pct ?? 0,
        sharpe: bt.results.sharpe_ratio ?? 0,
        profitFactor: bt.results.profit_factor ?? 0,
        winRate: bt.results.win_rate ?? 0,
        totalTrades: bt.results.total_trades ?? 0,
        tradesPerDay: bt.results.trades_per_day ?? 0,
        expectancy: bt.results.expectancy ?? 0,
        feeDragPct: bt.results.fee_drag_pct ?? 0,
        slippageDragPct: bt.results.slippage_drag_pct ?? 0,
        realizedPnl: bt.results.realized_pnl ?? 0,
        totalFees: bt.results.total_fees ?? 0,
        grossProfit: bt.results.gross_profit ?? 0,
        grossLoss: bt.results.gross_loss ?? 0,
        avgWin: bt.results.avg_win ?? 0,
        avgLoss: bt.results.avg_loss ?? 0,
        largestWin: bt.results.largest_win ?? 0,
        largestLoss: bt.results.largest_loss ?? 0,
        winningTrades: bt.results.winning_trades ?? 0,
        losingTrades: bt.results.losing_trades ?? 0,
      } : null,
      realism: { fees: true, slippage: "fixed", slippageBps: bt.slippage_bps || 5 },
      tags: bt.tags || [],
    }));
  }, [backtestsData]);

  const filteredRuns = useMemo(() => {
    return runs.filter((run: any) => {
      if (statusFilter && run.status !== statusFilter) return false;
      if (symbolFilter && run.symbol !== symbolFilter) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        if (!run.name?.toLowerCase().includes(q) && !run.strategy.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [runs, statusFilter, symbolFilter, searchQuery]);

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 space-y-4">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Loading backtest runs...</p>
      </div>
    );
  }

  // Error state with retry button
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 space-y-4">
        <div className="rounded-full bg-red-500/10 p-3">
          <AlertCircle className="h-8 w-8 text-red-500" />
        </div>
        <div className="text-center space-y-1">
          <p className="text-sm font-medium">Failed to load backtest runs</p>
          <p className="text-xs text-muted-foreground">
            {error instanceof Error ? error.message : "An unexpected error occurred"}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 mr-1.5" />
          Retry
        </Button>
      </div>
    );
  }

  // Empty state
  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 space-y-4">
        <div className="rounded-full bg-muted p-3">
          <FlaskConical className="h-8 w-8 text-muted-foreground" />
        </div>
        <div className="text-center space-y-1">
          <p className="text-sm font-medium">No backtest runs found</p>
          <p className="text-xs text-muted-foreground">
            Create your first backtest to get started.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Live State Card - Requirements 4.8 */}
      <LiveStateCard />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search runs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 h-9"
          />
        </div>

        <select
          className="h-9 px-3 text-sm rounded-md border border-border bg-background"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All Statuses</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="pending">Pending</option>
          <option value="failed">Failed</option>
        </select>

        <select
          className="h-9 px-3 text-sm rounded-md border border-border bg-background"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
        >
          <option value="">All Symbols</option>
          {[...new Set(runs.map((r: any) => r.symbol))].map((s) => (
            <option key={String(s)} value={String(s)}>{String(s)}</option>
          ))}
        </select>

        {selectedForCompare.length > 0 && (
          <Badge variant="outline" className="ml-auto">
            {selectedForCompare.length} selected for compare
          </Badge>
        )}
      </div>

      {/* Filtered empty state */}
      {filteredRuns.length === 0 && runs.length > 0 && (
        <div className="flex flex-col items-center justify-center py-12 space-y-3">
          <Search className="h-6 w-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No runs match your filters</p>
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => {
              setStatusFilter("");
              setSymbolFilter("");
              setSearchQuery("");
            }}
          >
            Clear filters
          </Button>
        </div>
      )}

      {/* Runs Table */}
      {filteredRuns.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/30">
                    <th className="w-10 p-3"></th>
                    <th className="text-left p-3 font-medium">Run</th>
                    <th className="text-left p-3 font-medium">Strategy</th>
                    <th className="text-left p-3 font-medium">Symbol</th>
                    <th className="text-left p-3 font-medium">Period</th>
                    <th className="text-center p-3 font-medium">Status</th>
                    <th className="text-right p-3 font-medium">PnL</th>
                    <th className="text-right p-3 font-medium">Return</th>
                    <th className="text-right p-3 font-medium">Max DD</th>
                    <th className="text-right p-3 font-medium">Sharpe</th>
                    <th className="text-right p-3 font-medium">PF</th>
                    <th className="text-right p-3 font-medium">Trades</th>
                    <th className="text-center p-3 font-medium">Realism</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRuns.map((run) => {
                    const status = getStatusConfig(run.status);
                    const StatusIcon = status.icon;
                    return (
                      <tr
                        key={run.id}
                        className="border-b border-border/30 hover:bg-muted/20 cursor-pointer transition-colors"
                        onClick={() => onSelectRun(run)}
                      >
                        <td className="p-3" onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={selectedForCompare.includes(run.id)}
                            onChange={() => onToggleCompare(run.id)}
                            disabled={run.status !== "completed"}
                          />
                        </td>
                        <td className="p-3">
                          <div>
                            <p className="font-medium">{run.name || `Run ${run.id.slice(-4)}`}</p>
                            <p className="text-xs text-muted-foreground">{formatDateTime(run.createdAt)}</p>
                          </div>
                        </td>
                        <td className="p-3">
                          <Badge variant="outline" className="text-xs">{run.strategy}</Badge>
                        </td>
                        <td className="p-3 font-mono text-xs">{run.symbol}</td>
                        <td className="p-3 text-xs text-muted-foreground">
                          {formatDate(run.startDate)} – {formatDate(run.endDate)}
                        </td>
                        <td className="p-3 text-center">
                          <Badge variant="outline" className={cn("text-xs", status.color, status.bg)}>
                            <StatusIcon className={cn("h-3 w-3 mr-1", run.status === "running" && "animate-spin")} />
                            {run.status}
                          </Badge>
                        </td>
                        {run.metrics ? (
                          <>
                            <td className={cn("p-3 text-right font-mono", run.metrics.realizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                              ${run.metrics.realizedPnl >= 0 ? "+" : ""}{run.metrics.realizedPnl.toFixed(0)}
                            </td>
                            <td className={cn("p-3 text-right font-mono", run.metrics.returnPct >= 0 ? "text-emerald-500" : "text-red-500")}>
                              {formatPct(run.metrics.returnPct)}
                            </td>
                            <td className="p-3 text-right font-mono text-red-500">{formatPct(run.metrics.maxDdPct)}</td>
                            <td className="p-3 text-right font-mono">{run.metrics.sharpe.toFixed(2)}</td>
                            <td className="p-3 text-right font-mono">{run.metrics.profitFactor.toFixed(2)}</td>
                            <td className="p-3 text-right font-mono">{run.metrics.totalTrades}</td>
                          </>
                        ) : (
                          <>
                            <td className="p-3 text-right text-muted-foreground">—</td>
                            <td className="p-3 text-right text-muted-foreground">—</td>
                            <td className="p-3 text-right text-muted-foreground">—</td>
                            <td className="p-3 text-right text-muted-foreground">—</td>
                            <td className="p-3 text-right text-muted-foreground">—</td>
                            <td className="p-3 text-right text-muted-foreground">—</td>
                          </>
                        )}
                        <td className="p-3 text-center">
                          <div className="flex items-center justify-center gap-1">
                            {run.realism.fees && (
                              <Tooltip>
                                <TooltipTrigger>
                                  <Badge variant="outline" className="text-[10px] px-1 py-0">F</Badge>
                                </TooltipTrigger>
                                <TooltipContent>Fees enabled</TooltipContent>
                              </Tooltip>
                            )}
                            {run.realism.slippage !== "none" && (
                              <Tooltip>
                                <TooltipTrigger>
                                  <Badge variant="outline" className="text-[10px] px-1 py-0">S</Badge>
                                </TooltipTrigger>
                                <TooltipContent>Slippage: {run.realism.slippage} ({run.realism.slippageBps}bps)</TooltipContent>
                              </Tooltip>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ============================================================================
// RUN DETAIL DRAWER
// ============================================================================

function RunDetailDrawer({
  run,
  onClose,
  onClone,
  onAddToCompare,
  onRerun,
  onPromote,
  onDelete,
}: {
  run: any | null;
  onClose: () => void;
  onClone: (run: any) => void;
  onAddToCompare: (id: string) => void;
  onRerun: (id: string, forceRun?: boolean) => void;
  onPromote: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [activeTab, setActiveTab] = useState("overview");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  // Fetch real equity curve and trades from API - Requirements 4.3, 4.4
  const { data: detail, isLoading: detailLoading, error: detailError, refetch: refetchDetail } = useBacktestDetail(run?.id || "");

  if (!run) return null;

  const m = run.metrics;
  // Use real equity curve and trades from API (no fallback to mock data)
  const equityCurve = detail?.equityCurve || [];
  const trades = detail?.trades || [];
  
  // Get error message from run or detail
  const errorMessage = run.error || run.error_message || detail?.backtest?.error_message || null;

  return (
    <Sheet open={!!run} onOpenChange={onClose}>
      <SheetContent className="w-full sm:max-w-4xl overflow-y-auto" side="right">
        <SheetHeader>
          <div className="flex items-center justify-between">
            <div>
              <SheetTitle>{run.name || `Run ${run.id.slice(-4)}`}</SheetTitle>
              <SheetDescription>
                {run.strategy} • {run.symbol} • {run.timeframe}
              </SheetDescription>
            </div>
            <Badge variant="outline" className={cn("text-xs", getStatusConfig(run.status).color)}>
              {run.status}
            </Badge>
          </div>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Error Message for Failed Backtests */}
          {run.status === "failed" && errorMessage && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-red-500 mb-1">Backtest Failed</h4>
                  <p className="text-sm text-red-400">{errorMessage}</p>
                </div>
              </div>
            </div>
          )}

          {/* No-Trade Warning Banner - Feature: backtest-diagnostics, Requirements 5.1, 5.2, 5.3, 5.4 */}
          {run.status === "completed" && (m?.totalTrades === 0 || m?.totalTrades === undefined) && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-amber-600 mb-1">
                    No Trades Generated
                  </h4>
                  <p className="text-sm text-amber-700">
                    {detail?.execution_diagnostics?.summary || 
                     "This backtest completed without generating any trades."}
                  </p>
                  {detail?.execution_diagnostics?.suggestions && detail.execution_diagnostics.suggestions.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs font-medium text-amber-600 mb-1">Suggestions:</p>
                      <ul className="text-xs text-muted-foreground space-y-1">
                        {detail.execution_diagnostics.suggestions.map((s: string, i: number) => (
                          <li key={i}>• {s}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {detail?.execution_diagnostics && (
                    <Button 
                      variant="outline" 
                      size="sm" 
                      className="mt-3 text-amber-600 border-amber-500/50 hover:bg-amber-500/10"
                      onClick={() => setActiveTab("diagnostics")}
                    >
                      <BarChart3 className="h-4 w-4 mr-1.5" />
                      View Diagnostics
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => onRerun(run.id)} disabled={run.status === "running"}>
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Rerun
            </Button>
            {run.status === "failed" && (
              <Button 
                variant="outline" 
                size="sm" 
                onClick={() => onRerun(run.id, true)}
                className="text-amber-600 border-amber-500/50 hover:bg-amber-500/10"
              >
                <Zap className="h-4 w-4 mr-1.5" />
                Rerun with Force
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => onClone(run)}>
              <Copy className="h-4 w-4 mr-1.5" />
              Clone
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPromote(run.id)}
              disabled={!["completed", "degraded"].includes(run.status)}
            >
              <Upload className="h-4 w-4 mr-1.5" />
              Promote Config
            </Button>
            <Button variant="outline" size="sm" onClick={() => onAddToCompare(run.id)} disabled={run.status !== "completed"}>
              <GitCompare className="h-4 w-4 mr-1.5" />
              Add to Compare
            </Button>
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4 mr-1.5" />
              Export
            </Button>
            {showDeleteConfirm ? (
              <div className="flex items-center gap-2 ml-auto">
                <span className="text-xs text-muted-foreground">Delete this run?</span>
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="text-red-500 border-red-500 hover:bg-red-50"
                  onClick={() => { onDelete(run.id); setShowDeleteConfirm(false); }}
                  disabled={run.status === "running"}
                >
                  Confirm
                </Button>
                <Button variant="outline" size="sm" onClick={() => setShowDeleteConfirm(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button 
                variant="outline" 
                size="sm" 
                className="ml-auto text-red-500 hover:text-red-600 hover:bg-red-50"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={run.status === "running"}
              >
                <XCircle className="h-4 w-4 mr-1.5" />
                Delete
              </Button>
            )}
          </div>

          {/* KPI Strip */}
          {m && (
            <div className="grid grid-cols-4 gap-3">
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Realized PnL</p>
                <p className={cn("text-lg font-bold", m.realizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                  ${m.realizedPnl >= 0 ? "+" : ""}{(m.realizedPnl || 0).toFixed(0)}
                </p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Return</p>
                <p className={cn("text-lg font-bold", m.returnPct >= 0 ? "text-emerald-500" : "text-red-500")}>
                  {formatPct(m.returnPct)}
                </p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Max DD</p>
                <p className="text-lg font-bold text-red-500">{formatPct(m.maxDdPct)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Sharpe</p>
                <p className="text-lg font-bold">{(m.sharpe || 0).toFixed(2)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Profit Factor</p>
                <p className="text-lg font-bold">{(m.profitFactor || 0).toFixed(2)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Win Rate</p>
                <p className="text-lg font-bold">{(m.winRate || 0).toFixed(1)}%</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Trades/Day</p>
                <p className="text-lg font-bold">{(m.tradesPerDay || 0).toFixed(1)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Total Trades</p>
                <p className="text-lg font-bold">{m.totalTrades || 0}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Fee Drag</p>
                <p className="text-lg font-bold text-amber-500">{(m.feeDragPct || 0).toFixed(2)}%</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Slippage Drag</p>
                <p className="text-lg font-bold text-amber-500">{(m.slippageDragPct || 0).toFixed(2)}%</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Avg Win</p>
                <p className="text-lg font-bold text-emerald-500">${(m.avgWin || 0).toFixed(0)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-[11px] text-muted-foreground">Avg Loss</p>
                <p className="text-lg font-bold text-red-500">${Math.abs(m.avgLoss || 0).toFixed(0)}</p>
              </div>
            </div>
          )}

          {/* Tabs */}
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="w-full">
              <TabsTrigger value="overview" className="flex-1">Overview</TabsTrigger>
              <TabsTrigger value="trades" className="flex-1">Trades</TabsTrigger>
              <TabsTrigger value="costs" className="flex-1">Costs</TabsTrigger>
              <TabsTrigger value="diagnostics" className="flex-1">Diagnostics</TabsTrigger>
              <TabsTrigger value="notes" className="flex-1">Notes</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="space-y-4 mt-4">
              {/* Equity Curve - Requirements 4.3: Fetch real equity curve data from API */}
              <div className="rounded-lg border p-4">
                <h4 className="text-sm font-medium mb-3">Equity Curve</h4>
                <div className="h-[200px]">
                  {/* Loading state for equity curve */}
                  {detailLoading && (
                    <div className="flex flex-col items-center justify-center h-full space-y-2">
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                      <p className="text-xs text-muted-foreground">Loading equity curve...</p>
                    </div>
                  )}
                  {/* Error state for equity curve */}
                  {!detailLoading && detailError && (
                    <div className="flex flex-col items-center justify-center h-full space-y-2">
                      <AlertCircle className="h-6 w-6 text-red-500" />
                      <p className="text-xs text-muted-foreground">Failed to load equity curve</p>
                      <Button variant="ghost" size="sm" onClick={() => refetchDetail()}>
                        <RefreshCw className="h-3 w-3 mr-1" />
                        Retry
                      </Button>
                    </div>
                  )}
                  {/* Empty state for equity curve */}
                  {!detailLoading && !detailError && equityCurve.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-full space-y-2">
                      <LineChart className="h-6 w-6 text-muted-foreground" />
                      <p className="text-xs text-muted-foreground">No equity curve data available</p>
                    </div>
                  )}
                  {/* Equity curve chart */}
                  {!detailLoading && !detailError && equityCurve.length > 0 && (
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart
                        data={equityCurve.map((p: any) => ({
                          date: new Date(p.time || p.timestamp).toLocaleString(),
                          equity: p.value || p.equity,
                          drawdown: p.drawdown || 0,
                        }))}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} tickFormatter={(v) => v.slice(-2)} />
                        <YAxis yAxisId="equity" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                        <YAxis yAxisId="dd" orientation="right" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} />
                        <RechartsTooltip contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '11px' }} />
                        <Area yAxisId="dd" type="monotone" dataKey="drawdown" fill="hsl(var(--destructive) / 0.2)" stroke="hsl(var(--destructive))" name="Drawdown %" />
                        <Line yAxisId="equity" type="monotone" dataKey="equity" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} name="Equity" />
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              {/* Config Details */}
              <div className="rounded-lg border p-4">
                <h4 className="text-sm font-medium mb-3">Configuration</h4>
                <div className="grid grid-cols-2 gap-y-2 text-sm">
                  <div className="text-muted-foreground">Period</div>
                  <div>{formatDate(run.startDate)} – {formatDate(run.endDate)}</div>
                  <div className="text-muted-foreground">Initial Capital</div>
                  <div>{formatCurrency(run.initialCapital)}</div>
                  <div className="text-muted-foreground">Timeframe</div>
                  <div>{run.timeframe}</div>
                  <div className="text-muted-foreground">Fees</div>
                  <div>{run.realism.fees ? "Enabled" : "Disabled"}</div>
                  <div className="text-muted-foreground">Slippage</div>
                  <div>{run.realism.slippage} ({run.realism.slippageBps}bps)</div>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="trades" className="mt-4">
              {/* Trades Table - Requirements 4.4: Fetch real trade data from API */}
              {/* Loading state for trades */}
              {detailLoading && (
                <div className="flex flex-col items-center justify-center py-12 space-y-2">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Loading trades...</p>
                </div>
              )}
              {/* Error state for trades */}
              {!detailLoading && detailError && (
                <div className="flex flex-col items-center justify-center py-12 space-y-3">
                  <AlertCircle className="h-6 w-6 text-red-500" />
                  <p className="text-sm text-muted-foreground">Failed to load trades</p>
                  <Button variant="outline" size="sm" onClick={() => refetchDetail()}>
                    <RefreshCw className="h-4 w-4 mr-1.5" />
                    Retry
                  </Button>
                </div>
              )}
              {/* Empty state for trades */}
              {!detailLoading && !detailError && trades.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 space-y-2">
                  <Activity className="h-6 w-6 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">No trades recorded</p>
                </div>
              )}
              {/* Trades table */}
              {!detailLoading && !detailError && trades.length > 0 && (
                <div className="rounded-lg border overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-muted/30 border-b">
                        <th className="text-left p-2 font-medium">Time</th>
                        <th className="text-left p-2 font-medium">Strategy</th>
                        <th className="text-left p-2 font-medium">Side</th>
                        <th className="text-right p-2 font-medium">Entry</th>
                        <th className="text-right p-2 font-medium">Exit</th>
                        <th className="text-right p-2 font-medium">Size</th>
                        <th className="text-right p-2 font-medium">PnL</th>
                        <th className="text-left p-2 font-medium">Exit Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.slice(0, 100).map((t: any, idx: number) => {
                        const pnlRatio = Number(t.pnl || t.realized_pnl || 0);
                        const initialCapital = Number(detail?.backtest?.config?.initial_capital || 10000);
                        const pnlUsd = pnlRatio * initialCapital; // Convert ratio to USD
                        const side = (t.side || t.direction || "").toString().toLowerCase();
                        const strategyName = (t.strategy_id || "").replace(/_/g, " ").replace(/scalp/gi, "").trim() || "N/A";
                        const exitReason = (t.reason || "").replace(/_/g, " ") || "-";
                        return (
                          <tr key={t.id || idx} className="border-b border-border/30">
                            <td className="p-2 font-mono text-[10px]">
                              {t.entry_time || t.entryTime
                                ? formatDateTime(t.entry_time || t.entryTime)
                                : t.timestamp
                                ? formatDateTime(t.timestamp)
                                : ""}
                            </td>
                            <td className="p-2 text-[10px] text-muted-foreground">{strategyName}</td>
                            <td className="p-2">
                              <Badge variant="outline" className={cn("text-[10px]", side === "buy" || side === "long" ? "text-emerald-500" : "text-red-500")}>
                                {side || "NA"}
                              </Badge>
                            </td>
                            <td className="p-2 text-right font-mono text-[10px]">{Number(t.entry_price || t.entry || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-[10px]">{Number(t.exit_price || t.exit || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-[10px]">{Number(t.size || t.quantity || 0).toFixed(3)}</td>
                            <td className={cn("p-2 text-right font-mono font-medium text-[11px]", pnlUsd >= 0 ? "text-emerald-500" : "text-red-500")}>
                              ${pnlUsd >= 0 ? "+" : ""}
                              {Math.abs(pnlUsd).toFixed(2)}
                            </td>
                            <td className="p-2 text-[10px] text-muted-foreground">{exitReason}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </TabsContent>

            <TabsContent value="costs" className="mt-4">
              <div className="space-y-4">
                <div className="rounded-lg border p-4">
                  <h4 className="text-sm font-medium mb-3">Cost Breakdown</h4>
                  <div className="space-y-4">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-muted-foreground">Total Fees</span>
                        <span className="font-mono font-medium">${(m?.totalFees || 0).toFixed(2)}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
                        <span>Fee Drag</span>
                        <span>{(m?.feeDragPct || 0).toFixed(2)}% of capital</span>
                      </div>
                      <Progress value={Math.min((m?.feeDragPct || 0) * 20, 100)} className="h-2" />
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-muted-foreground">Estimated Slippage</span>
                        <span className="font-mono font-medium">${((m?.slippageDragPct || 0) * (run.initialCapital || 10000) / 100).toFixed(2)}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
                        <span>Slippage Drag</span>
                        <span>{(m?.slippageDragPct || 0).toFixed(2)}% of capital</span>
                      </div>
                      <Progress value={Math.min((m?.slippageDragPct || 0) * 20, 100)} className="h-2" />
                    </div>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">Total Cost Impact</span>
                      <span className="font-mono font-medium text-amber-500">
                        ${((m?.totalFees || 0) + ((m?.slippageDragPct || 0) * (run.initialCapital || 10000) / 100)).toFixed(2)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>As % of capital</span>
                      <span>{((m?.feeDragPct || 0) + (m?.slippageDragPct || 0)).toFixed(2)}%</span>
                    </div>
                  </div>
                </div>
                
                <div className="rounded-lg border p-4">
                  <h4 className="text-sm font-medium mb-3">Trade Statistics</h4>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-muted-foreground">Winning Trades</p>
                      <p className="font-mono font-medium text-emerald-500">{m?.winningTrades || 0}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Losing Trades</p>
                      <p className="font-mono font-medium text-red-500">{m?.losingTrades || 0}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Gross Profit</p>
                      <p className="font-mono font-medium text-emerald-500">${(m?.grossProfit || 0).toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Gross Loss</p>
                      <p className="font-mono font-medium text-red-500">${(m?.grossLoss || 0).toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Largest Win</p>
                      <p className="font-mono font-medium text-emerald-500">${(m?.largestWin || 0).toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Largest Loss</p>
                      <p className="font-mono font-medium text-red-500">${Math.abs(m?.largestLoss || 0).toFixed(2)}</p>
                    </div>
                  </div>
                </div>
              </div>
            </TabsContent>

            {/* Diagnostics Tab - Feature: backtest-diagnostics, Requirements 3.1, 3.2, 3.3 */}
            <TabsContent value="diagnostics" className="space-y-4 mt-4">
              {detail?.execution_diagnostics ? (
                <>
                  {/* Processing Summary */}
                  <div className="rounded-lg border p-4">
                    <h4 className="text-sm font-medium mb-3">Processing Summary</h4>
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <p className="text-xs text-muted-foreground">Total Snapshots</p>
                        <p className="text-lg font-bold">{(detail.execution_diagnostics.total_snapshots || 0).toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Processed</p>
                        <p className="text-lg font-bold text-emerald-500">
                          {(detail.execution_diagnostics.snapshots_processed || 0).toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Skipped</p>
                        <p className="text-lg font-bold text-amber-500">
                          {(detail.execution_diagnostics.snapshots_skipped || 0).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Rejection Breakdown */}
                  <div className="rounded-lg border p-4">
                    <h4 className="text-sm font-medium mb-3">Safety Filter Rejections</h4>
                    <div className="space-y-3">
                      {detail.execution_diagnostics.rejection_breakdown && Object.entries(detail.execution_diagnostics.rejection_breakdown).map(([reason, count]) => {
                        const total = detail.execution_diagnostics?.global_gate_rejections || 1;
                        const percentage = total > 0 ? ((count as number) / total) * 100 : 0;
                        const formatReason = (r: string) => r.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                        return (
                          <div key={reason} className="space-y-1">
                            <div className="flex items-center justify-between text-sm">
                              <span className="text-muted-foreground">{formatReason(reason)}</span>
                              <span className="font-mono">{(count as number).toLocaleString()} ({percentage.toFixed(1)}%)</span>
                            </div>
                            <Progress value={percentage} className="h-2" />
                          </div>
                        );
                      })}
                      <div className="pt-2 border-t">
                        <div className="flex items-center justify-between text-sm font-medium">
                          <span>Total Rejections</span>
                          <span className="font-mono text-red-500">{(detail.execution_diagnostics.global_gate_rejections || 0).toLocaleString()}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Signal Pipeline */}
                  <div className="rounded-lg border p-4">
                    <h4 className="text-sm font-medium mb-3">Signal Pipeline</h4>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 text-center p-3 rounded-lg bg-muted/30">
                        <p className="text-xs text-muted-foreground">Profiles Selected</p>
                        <p className="text-lg font-bold">{detail.execution_diagnostics.profiles_selected || 0}</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <div className="flex-1 text-center p-3 rounded-lg bg-muted/30">
                        <p className="text-xs text-muted-foreground">Signals Generated</p>
                        <p className="text-lg font-bold">{detail.execution_diagnostics.signals_generated || 0}</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <div className="flex-1 text-center p-3 rounded-lg bg-amber-500/10">
                        <p className="text-xs text-muted-foreground">Cooldown Blocked</p>
                        <p className="text-lg font-bold text-amber-500">{detail.execution_diagnostics.cooldown_rejections || 0}</p>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <div className="flex-1 text-center p-3 rounded-lg bg-emerald-500/10">
                        <p className="text-xs text-muted-foreground">Trades Executed</p>
                        <p className="text-lg font-bold text-emerald-500">{m?.totalTrades || 0}</p>
                      </div>
                    </div>
                  </div>

                  {/* Summary & Suggestions */}
                  {detail.execution_diagnostics.summary && (
                    <div className="rounded-lg border p-4">
                      <h4 className="text-sm font-medium mb-2">Analysis Summary</h4>
                      <p className="text-sm text-muted-foreground mb-3">{detail.execution_diagnostics.summary}</p>
                      {detail.execution_diagnostics.primary_issue && (
                        <div className="flex items-center gap-2 mb-3">
                          <Badge variant="outline" className="text-xs">
                            Primary Issue: {detail.execution_diagnostics.primary_issue.split('_').join(' ')}
                          </Badge>
                        </div>
                      )}
                      {detail.execution_diagnostics.suggestions && detail.execution_diagnostics.suggestions.length > 0 && (
                        <div>
                          <p className="text-xs font-medium mb-2">Suggestions:</p>
                          <ul className="text-sm text-muted-foreground space-y-1">
                            {detail.execution_diagnostics.suggestions.map((s: string, i: number) => (
                              <li key={i} className="flex items-start gap-2">
                                <span className="text-emerald-500">•</span>
                                <span>{s}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <div className="rounded-lg border p-8 text-center">
                  <BarChart3 className="h-12 w-12 mx-auto text-muted-foreground/50 mb-3" />
                  <p className="text-sm text-muted-foreground">
                    Diagnostics not available for this backtest.
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Diagnostics are collected for backtests run after this feature was enabled.
                  </p>
                </div>
              )}
            </TabsContent>

            <TabsContent value="notes" className="mt-4">
              <div className="space-y-4">
                <div>
                  <Label>Tags</Label>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {(run.tags || []).map((tag: string) => (
                      <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                    ))}
                    <Button variant="ghost" size="sm" className="h-6 px-2 text-xs">
                      <Plus className="h-3 w-3 mr-1" /> Add
                    </Button>
                  </div>
                </div>
                <div>
                  <Label>Notes</Label>
                  <textarea className="w-full mt-2 p-2 rounded-md border border-border bg-background text-sm min-h-[100px]" placeholder="Add notes about this run..." />
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ============================================================================
// NEW BACKTEST TAB
// ============================================================================

function NewBacktestTab({ onSubmit }: { onSubmit: () => void }) {
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState({
    strategy: "",
    symbol: "",
    exchange: "okx",
    startDate: "",
    endDate: "",
    initialCapital: 10000,
    makerFeeBps: 2,
    takerFeeBps: 5.5,
    slippageModel: "fixed",
    slippageBps: 5,
    runName: "",
    forceRun: false,
    // Warm start configuration - Feature: trading-pipeline-integration, Requirements: 3.1, 3.6
    warmStartEnabled: false,
    // Execution scenario configuration - Feature: trading-pipeline-integration, Requirements: 5.5
    executionScenario: "realistic" as "optimistic" | "realistic" | "pessimistic" | "custom",
    customExecutionConfig: {
      baseLatencyMs: 50.0,
      latencyStdMs: 20.0,
      baseSlippageBps: 2.0,
      depthSlippageFactor: 0.3,
      partialFillProbSmall: 0.10,
      partialFillProbMedium: 0.25,
      partialFillProbLarge: 0.50,
    },
    // Profile parameter overrides for experiments
    profileOverrides: {} as Record<string, number | boolean | string>,
  });
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  // Custom execution scenario modal state - Feature: trading-pipeline-integration, Requirements: 5.5
  const [customScenarioModalOpen, setCustomScenarioModalOpen] = useState(false);

  // Execution scenario presets - Feature: trading-pipeline-integration, Requirements: 5.5
  const executionScenarioPresets = {
    optimistic: {
      baseLatencyMs: 10.0,
      latencyStdMs: 5.0,
      baseSlippageBps: 0.5,
      depthSlippageFactor: 0.1,
      partialFillProbSmall: 0.05,
      partialFillProbMedium: 0.15,
      partialFillProbLarge: 0.30,
    },
    realistic: {
      baseLatencyMs: 50.0,
      latencyStdMs: 20.0,
      baseSlippageBps: 2.0,
      depthSlippageFactor: 0.3,
      partialFillProbSmall: 0.10,
      partialFillProbMedium: 0.25,
      partialFillProbLarge: 0.50,
    },
    pessimistic: {
      baseLatencyMs: 150.0,
      latencyStdMs: 50.0,
      baseSlippageBps: 5.0,
      depthSlippageFactor: 0.5,
      partialFillProbSmall: 0.20,
      partialFillProbMedium: 0.40,
      partialFillProbLarge: 0.70,
    },
  };

  // Get current execution scenario parameters for preview
  const currentExecutionParams = formData.executionScenario === "custom" 
    ? formData.customExecutionConfig 
    : executionScenarioPresets[formData.executionScenario as keyof typeof executionScenarioPresets];

  // Warm start state query - Feature: trading-pipeline-integration, Requirements: 3.1, 3.6
  const { 
    data: warmStartState, 
    isLoading: warmStartLoading, 
    error: warmStartError,
    refetch: refetchWarmStart,
  } = useQuery<WarmStartResponse>({
    queryKey: ["warm-start-state"],
    queryFn: fetchWarmStartState,
    enabled: formData.warmStartEnabled,
    staleTime: 30000, // 30 seconds
    refetchInterval: formData.warmStartEnabled ? 60000 : false, // Refresh every minute when enabled
  });

  // Fetch real datasets and strategies from API
  const { data: datasetsData, isLoading: datasetsLoading } = useDatasets();
  const { data: strategiesData, isLoading: strategiesLoading } = useResearchStrategies();
  const createBacktest = useCreateBacktest();
  
  // Transform datasets from API
  const datasets = useMemo(() => {
    if (datasetsData?.datasets && datasetsData.datasets.length > 0) {
      return datasetsData.datasets.map((ds: any) => ({
        symbol: ds.symbol,
        exchange: ds.exchange || "okx",
        earliestDate: ds.earliest_date || ds.earliestDate,
        latestDate: ds.latest_date || ds.latestDate,
        candleCount: ds.candle_count || ds.candleCount || 0,
      }));
    }
    return [];
  }, [datasetsData]);

  // Transform strategies from API
  const strategies = useMemo(() => {
    if ((strategiesData as any)?.strategies && (strategiesData as any).strategies.length > 0) {
      return (strategiesData as any).strategies.map((s: any) => ({
        id: s.id,
        name: s.name,
        description: s.description,
      }));
    }
    return [];
  }, [strategiesData]);

  // Get selected dataset info for date validation
  const selectedDataset = useMemo(() => {
    return datasets.find((d: any) => d.symbol === formData.symbol);
  }, [datasets, formData.symbol]);

  // Auto-populate dates when symbol changes
  const handleSymbolChange = (symbol: string) => {
    const dataset = datasets.find((d: any) => d.symbol === symbol);
    if (dataset) {
      // Format ISO timestamps for datetime-local input (YYYY-MM-DDTHH:MM)
      // The API returns full ISO timestamps like "2026-01-17T07:38:17.968508+00:00"
      // datetime-local needs "2026-01-17T07:38"
      const earliest = dataset.earliestDate ? dataset.earliestDate.slice(0, 16) : "";
      const latest = dataset.latestDate ? dataset.latestDate.slice(0, 16) : "";
      setFormData({ 
        ...formData, 
        symbol,
        startDate: earliest,
        endDate: latest,
      });
    } else {
      setFormData({ ...formData, symbol, startDate: "", endDate: "" });
    }
  };

  // Calculate date range info
  const dateRangeInfo = useMemo(() => {
    if (!formData.startDate || !formData.endDate) return null;
    const start = new Date(formData.startDate);
    const end = new Date(formData.endDate);
    const diffMs = end.getTime() - start.getTime();
    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
    return { days, hours, minutes, totalMinutes: Math.floor(diffMs / (1000 * 60)) };
  }, [formData.startDate, formData.endDate]);

  const handleSubmit = async () => {
    try {
      if (!formData.forceRun && preflight && !preflight.ok) {
        toast.error("Backtest blocked: no source data in selected range");
        return;
      }
      // Append :00Z to convert datetime-local format to UTC ISO format
      // datetime-local gives us "2026-01-17T07:38", we need "2026-01-17T07:38:00Z"
      const startDateUTC = formData.startDate ? `${formData.startDate}:00Z` : "";
      const endDateUTC = formData.endDate ? `${formData.endDate}:00Z` : "";
      
      // Build execution scenario config - Feature: trading-pipeline-integration, Requirements: 5.5
      const executionScenarioConfig = formData.executionScenario === "custom" 
        ? {
            scenario: "custom",
            base_latency_ms: formData.customExecutionConfig.baseLatencyMs,
            latency_std_ms: formData.customExecutionConfig.latencyStdMs,
            base_slippage_bps: formData.customExecutionConfig.baseSlippageBps,
            depth_slippage_factor: formData.customExecutionConfig.depthSlippageFactor,
            partial_fill_prob_small: formData.customExecutionConfig.partialFillProbSmall,
            partial_fill_prob_medium: formData.customExecutionConfig.partialFillProbMedium,
            partial_fill_prob_large: formData.customExecutionConfig.partialFillProbLarge,
          }
        : { scenario: formData.executionScenario };
      
      // Parse strategy/profile selection
      const isProfile = formData.strategy.startsWith('profile:');
      const strategyOrProfileId = isProfile ? formData.strategy.substring(8) : formData.strategy;
      
      await createBacktest.mutateAsync({
        strategy_id: isProfile ? undefined : strategyOrProfileId,
        profile_id: isProfile ? strategyOrProfileId : undefined,
        symbol: formData.symbol,
        start_date: startDateUTC,
        end_date: endDateUTC,
        initial_capital: formData.initialCapital,
        force_run: formData.forceRun,
        config: {
          maker_fee_bps: formData.makerFeeBps,
          taker_fee_bps: formData.takerFeeBps,
          slippage_model: formData.slippageModel,
          slippage_bps: formData.slippageBps,
          // Warm start configuration - Feature: trading-pipeline-integration, Requirements: 3.1
          warm_start: formData.warmStartEnabled,
          // Execution scenario configuration - Feature: trading-pipeline-integration, Requirements: 5.5
          execution_scenario: executionScenarioConfig,
          // Profile parameter overrides for experiments
          profile_overrides: Object.keys(formData.profileOverrides).length > 0 ? formData.profileOverrides : undefined,
        },
      });
      toast.success("Backtest queued successfully");
      onSubmit();
    } catch (error: any) {
      toast.error(error?.message || "Failed to create backtest");
    }
  };

  const isStep1Valid = formData.strategy && formData.symbol && formData.startDate && formData.endDate;

  const preflightStartDateUTC = formData.startDate ? `${formData.startDate}:00Z` : "";
  const preflightEndDateUTC = formData.endDate ? `${formData.endDate}:00Z` : "";
  const {
    data: preflight,
    isLoading: preflightLoading,
    isError: preflightError,
    error: preflightErrorObj,
    refetch: refetchPreflight,
  } = useBacktestPreflight({
    symbol: formData.symbol || undefined,
    start_date: preflightStartDateUTC || undefined,
    end_date: preflightEndDateUTC || undefined,
    require_decision_events: true,
  });

  // Format date for display - handles both date-only and full ISO timestamps
  const formatDateDisplay = (dateStr: string) => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    // If the timestamp includes time info, show it
    if (dateStr.includes('T')) {
      return date.toLocaleString("en-US", { 
        month: "short", 
        day: "numeric", 
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      });
    }
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Progress */}
      <div className="flex items-center gap-2">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center gap-2">
            <div className={cn(
              "h-8 w-8 rounded-full flex items-center justify-center text-sm font-medium border-2",
              step >= s ? "bg-primary text-primary-foreground border-primary" : "border-muted text-muted-foreground"
            )}>
              {s}
            </div>
            {s < 3 && <div className={cn("w-12 h-0.5", step > s ? "bg-primary" : "bg-muted")} />}
          </div>
        ))}
      </div>

      {/* Step 1: What to test */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">What to Test</CardTitle>
            <CardDescription>Select the strategy, symbol, and time period</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Profile (Recommended) or Strategy</Label>
                <select
                  className="w-full mt-1.5 h-9 px-3 rounded-md border border-border bg-background"
                  value={formData.strategy}
                  onChange={(e) => setFormData({ ...formData, strategy: e.target.value })}
                  disabled={strategiesLoading}
                >
                  <option value="">{strategiesLoading ? "Loading..." : "Select profile or strategy"}</option>
                  
                  {/* PROFILES - Recommended */}
                  <optgroup label="📋 Profiles (Recommended - Tests Full Bot Logic)">
                    <option value="profile:all">🤖 All Profiles (Auto-Select by Market)</option>
                    <option value="profile:poc_magnet_profile">POC Magnet Scalp</option>
                    <option value="profile:spread_capture_profile">Spread Capture Scalp</option>
                    <option value="profile:liquidity_fade_profile">Liquidity Fade Scalp</option>
                    <option value="profile:value_area_rejection_profile">Value Area Rejection</option>
                    <option value="profile:vwap_reversion_profile">VWAP Reversion</option>
                    <option value="profile:trend_pullback_profile">Trend Pullback</option>
                    <option value="profile:high_vol_breakout_profile">High Vol Breakout</option>
                    <option value="profile:asia_range_profile">Asia Range Scalp</option>
                    <option value="profile:europe_open_profile">Europe Open</option>
                    <option value="profile:us_open_profile">US Open</option>
                  </optgroup>
                  
                  {/* STRATEGIES - Legacy */}
                  <optgroup label="⚠️ Individual Strategies (Legacy - Tests Single Strategy Only)">
                    <option value="all">All Strategies (No Profile Routing)</option>
                  </optgroup>
                  
                  {/* Scalping Strategies */}
                  <optgroup label="Scalping">
                    {strategies.filter((s: any) => 
                      ["amt_value_area_rejection_scalp", "poc_magnet_scalp", "breakout_scalp", "asia_range_scalp"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Mean Reversion Strategies */}
                  <optgroup label="Mean Reversion">
                    {strategies.filter((s: any) => 
                      ["mean_reversion_fade", "vwap_reversion"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Breakout Strategies */}
                  <optgroup label="Breakout">
                    {strategies.filter((s: any) => 
                      ["opening_range_breakout", "high_vol_breakout", "vol_expansion"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Trend Following Strategies */}
                  <optgroup label="Trend Following">
                    {strategies.filter((s: any) => 
                      ["trend_pullback"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Session-Based Strategies */}
                  <optgroup label="Session-Based">
                    {strategies.filter((s: any) => 
                      ["europe_open_vol", "us_open_momentum", "overnight_thin"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Volatility Strategies */}
                  <optgroup label="Volatility">
                    {strategies.filter((s: any) => 
                      ["low_vol_grind", "chop_zone_avoid"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Order Flow Strategies */}
                  <optgroup label="Order Flow">
                    {strategies.filter((s: any) => 
                      ["liquidity_hunt", "order_flow_imbalance", "spread_compression", "volume_profile_cluster"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Risk Management Strategies */}
                  <optgroup label="Risk Management">
                    {strategies.filter((s: any) => 
                      ["drawdown_recovery", "max_profit_protection"].includes(s.id)
                    ).map((s: any) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </optgroup>
                  {/* Other strategies not in categories */}
                  {strategies.filter((s: any) => 
                    !["amt_value_area_rejection_scalp", "poc_magnet_scalp", "breakout_scalp", "asia_range_scalp",
                      "mean_reversion_fade", "vwap_reversion",
                      "opening_range_breakout", "high_vol_breakout", "vol_expansion",
                      "trend_pullback",
                      "europe_open_vol", "us_open_momentum", "overnight_thin",
                      "low_vol_grind", "chop_zone_avoid",
                      "liquidity_hunt", "order_flow_imbalance", "spread_compression", "volume_profile_cluster",
                      "drawdown_recovery", "max_profit_protection"].includes(s.id)
                  ).length > 0 && (
                    <optgroup label="Other">
                      {strategies.filter((s: any) => 
                        !["amt_value_area_rejection_scalp", "poc_magnet_scalp", "breakout_scalp", "asia_range_scalp",
                          "mean_reversion_fade", "vwap_reversion",
                          "opening_range_breakout", "high_vol_breakout", "vol_expansion",
                          "trend_pullback",
                          "europe_open_vol", "us_open_momentum", "overnight_thin",
                          "low_vol_grind", "chop_zone_avoid",
                          "liquidity_hunt", "order_flow_imbalance", "spread_compression", "volume_profile_cluster",
                          "drawdown_recovery", "max_profit_protection"].includes(s.id)
                      ).map((s: any) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
                {/* Auto-Select Info Tooltip */}
                {formData.strategy === "all" && (
                  <div className="flex items-start gap-2 mt-2 p-3 rounded-lg bg-blue-500/10 border border-blue-500/30">
                    <Info className="h-4 w-4 text-blue-500 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-blue-600">Auto-Select Mode</p>
                      <p className="text-xs text-muted-foreground">
                        The engine will automatically choose the best strategy based on current 
                        market conditions (trend, volatility, session, value area position).
                      </p>
                    </div>
                  </div>
                )}
                {/* Strategy Description */}
                {formData.strategy && formData.strategy !== "all" && strategies.find((s: any) => s.id === formData.strategy)?.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {strategies.find((s: any) => s.id === formData.strategy)?.description}
                  </p>
                )}
              </div>
              <div>
                <Label>Symbol</Label>
                <select
                  className="w-full mt-1.5 h-9 px-3 rounded-md border border-border bg-background"
                  value={formData.symbol}
                  onChange={(e) => handleSymbolChange(e.target.value)}
                  disabled={datasetsLoading}
                >
                  <option value="">{datasetsLoading ? "Loading datasets..." : "Select symbol"}</option>
                  {datasets.map((d: any) => (
                    <option key={d.symbol} value={d.symbol}>{d.symbol} ({d.exchange})</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Data Availability Info */}
            {selectedDataset && (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-emerald-500" />
                    <span className="text-sm font-medium">Data Available</span>
                  </div>
                  <Badge variant="outline" className="text-xs text-emerald-600 border-emerald-500/30">
                    {selectedDataset.candleCount?.toLocaleString()} candles
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {formatDateDisplay(selectedDataset.earliestDate)} → {formatDateDisplay(selectedDataset.latestDate)}
                </p>
              </div>
            )}

            {/* Date Range Selection */}
            <div>
              <Label className="mb-1.5 block">Backtest Period</Label>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Start Date/Time</Label>
                  <div className="relative mt-1">
                    <Input
                      type="datetime-local"
                      value={formData.startDate ? formData.startDate.slice(0, 16) : ""}
                      onChange={(e) => setFormData({ ...formData, startDate: e.target.value })}
                      min={selectedDataset?.earliestDate?.slice(0, 16)}
                      max={formData.endDate?.slice(0, 16) || selectedDataset?.latestDate?.slice(0, 16)}
                      disabled={!formData.symbol}
                      className="pr-8"
                    />
                    <Calendar className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                  </div>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">End Date/Time</Label>
                  <div className="relative mt-1">
                    <Input
                      type="datetime-local"
                      value={formData.endDate ? formData.endDate.slice(0, 16) : ""}
                      onChange={(e) => setFormData({ ...formData, endDate: e.target.value })}
                      min={formData.startDate?.slice(0, 16) || selectedDataset?.earliestDate?.slice(0, 16)}
                      max={selectedDataset?.latestDate?.slice(0, 16)}
                      disabled={!formData.symbol}
                      className="pr-8"
                    />
                    <Calendar className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                  </div>
                </div>
              </div>
              {dateRangeInfo && (
                <p className="text-xs text-muted-foreground mt-2">
                  Selected period: <span className="font-medium">
                    {dateRangeInfo.days > 0 
                      ? `${dateRangeInfo.days} day${dateRangeInfo.days !== 1 ? 's' : ''}${dateRangeInfo.hours > 0 ? ` ${dateRangeInfo.hours}h` : ''}`
                      : dateRangeInfo.hours > 0 
                        ? `${dateRangeInfo.hours}h ${dateRangeInfo.minutes}m`
                        : `${dateRangeInfo.minutes} minutes`
                    }
                  </span>
                </p>
              )}
              {!formData.symbol && (
                <p className="text-xs text-muted-foreground mt-2">
                  Select a symbol to enable date selection
                </p>
              )}
            </div>

            {datasets.length === 0 && !datasetsLoading && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium">No datasets available</p>
                    <p className="text-xs text-muted-foreground">
                      Historical data needs to be collected before running backtests. Check the Datasets tab for more info.
                    </p>
                  </div>
                </div>
              </div>
            )}
            {strategies.length === 0 && !strategiesLoading && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium">No strategies available</p>
                    <p className="text-xs text-muted-foreground">
                      Strategies need to be configured before running backtests.
                    </p>
                  </div>
                </div>
              </div>
            )}
            <div className="flex justify-end">
              <Button onClick={() => setStep(2)} disabled={!isStep1Valid}>
                Next <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Capital & Costs */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Capital & Costs</CardTitle>
            <CardDescription>Configure starting capital and realistic trading costs</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Initial Capital */}
            <div>
              <Label>Initial Capital (USDT)</Label>
              <Input
                type="number"
                className="mt-1.5"
                value={formData.initialCapital}
                onChange={(e) => setFormData({ ...formData, initialCapital: parseFloat(e.target.value) || 0 })}
                min={100}
                step={100}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Starting equity for the backtest simulation
              </p>
            </div>

            {/* Trading Fees */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">Trading Fees</Label>
                <Badge variant="outline" className="text-xs">
                  {selectedDataset?.exchange || "Exchange"} rates
                </Badge>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Maker Fee (bps)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.makerFeeBps || 2}
                    onChange={(e) => setFormData({ ...formData, makerFeeBps: parseFloat(e.target.value) || 0 })}
                    min={0}
                    max={100}
                    step={0.5}
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Taker Fee (bps)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.takerFeeBps || 5.5}
                    onChange={(e) => setFormData({ ...formData, takerFeeBps: parseFloat(e.target.value) || 0 })}
                    min={0}
                    max={100}
                    step={0.5}
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Bybit: Maker 2bps, Taker 5.5bps • Binance: Maker 2bps, Taker 4bps
              </p>
            </div>

            {/* Slippage */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">Slippage Model</Label>
                <select
                  className="h-8 px-2 text-xs rounded-md border border-border bg-background"
                  value={formData.slippageModel}
                  onChange={(e) => setFormData({ ...formData, slippageModel: e.target.value })}
                >
                  <option value="none">None (Optimistic)</option>
                  <option value="fixed">Fixed</option>
                  <option value="realistic">Realistic (Variable)</option>
                </select>
              </div>
              {formData.slippageModel !== "none" && (
                <div>
                  <Label className="text-xs text-muted-foreground">
                    {formData.slippageModel === "fixed" ? "Fixed Slippage (bps)" : "Average Slippage (bps)"}
                  </Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.slippageBps}
                    onChange={(e) => setFormData({ ...formData, slippageBps: parseFloat(e.target.value) || 0 })}
                    min={0}
                    max={50}
                    step={1}
                  />
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                {formData.slippageModel === "none" && "No slippage - fills at exact price (unrealistic)"}
                {formData.slippageModel === "fixed" && "Constant slippage applied to every trade"}
                {formData.slippageModel === "realistic" && "Variable slippage based on order size and volatility"}
              </p>
            </div>

            {/* Cost Summary */}
            <div className="rounded-lg bg-muted/30 p-3">
              <p className="text-xs font-medium mb-1">Estimated Cost per Round Trip</p>
              <p className="text-sm">
                ~{((formData.makerFeeBps || 2) + (formData.takerFeeBps || 5.5) + (formData.slippageModel !== "none" ? formData.slippageBps : 0)).toFixed(1)} bps
                <span className="text-muted-foreground ml-1">
                  ({(((formData.makerFeeBps || 2) + (formData.takerFeeBps || 5.5) + (formData.slippageModel !== "none" ? formData.slippageBps : 0)) / 100).toFixed(3)}%)
                </span>
              </p>
            </div>

            {/* Execution Scenario Configuration - Feature: trading-pipeline-integration, Requirements: 5.5 */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {formData.executionScenario === "optimistic" && <Zap className="h-4 w-4 text-emerald-500" />}
                  {formData.executionScenario === "realistic" && <Target className="h-4 w-4 text-blue-500" />}
                  {formData.executionScenario === "pessimistic" && <Shield className="h-4 w-4 text-amber-500" />}
                  {formData.executionScenario === "custom" && <Settings className="h-4 w-4 text-purple-500" />}
                  <Label className="text-sm font-medium">Execution Scenario</Label>
                </div>
                <select
                  className="h-8 px-2 text-xs rounded-md border border-border bg-background"
                  value={formData.executionScenario}
                  onChange={(e) => {
                    const newScenario = e.target.value as "optimistic" | "realistic" | "pessimistic" | "custom";
                    setFormData({ ...formData, executionScenario: newScenario });
                    if (newScenario === "custom") {
                      setCustomScenarioModalOpen(true);
                    }
                  }}
                >
                  <option value="optimistic">⚡ Optimistic</option>
                  <option value="realistic">🎯 Realistic</option>
                  <option value="pessimistic">🛡️ Pessimistic</option>
                  <option value="custom">⚙️ Custom</option>
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                {formData.executionScenario === "optimistic" && "Best-case execution: low latency, minimal slippage, rare partial fills"}
                {formData.executionScenario === "realistic" && "Typical market conditions: moderate latency, normal slippage, occasional partial fills"}
                {formData.executionScenario === "pessimistic" && "Worst-case execution: high latency, significant slippage, frequent partial fills"}
                {formData.executionScenario === "custom" && "Custom execution parameters configured manually"}
              </p>

              {/* Scenario Parameter Preview */}
              <div className="rounded-lg bg-muted/30 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">Scenario Parameters</span>
                  {formData.executionScenario === "custom" && (
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      className="h-6 px-2 text-xs text-purple-500 hover:text-purple-600"
                      onClick={() => setCustomScenarioModalOpen(true)}
                    >
                      <Settings className="h-3 w-3 mr-1" />
                      Configure
                    </Button>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Base Latency</span>
                    <span className="font-mono">{currentExecutionParams.baseLatencyMs}ms</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Latency Std Dev</span>
                    <span className="font-mono">±{currentExecutionParams.latencyStdMs}ms</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Base Slippage</span>
                    <span className="font-mono">{currentExecutionParams.baseSlippageBps}bps</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Depth Factor</span>
                    <span className="font-mono">{currentExecutionParams.depthSlippageFactor}</span>
                  </div>
                  <div className="flex justify-between col-span-2 pt-1 border-t border-border/50">
                    <span className="text-muted-foreground">Partial Fill Probability</span>
                    <span className="font-mono">
                      S:{(currentExecutionParams.partialFillProbSmall * 100).toFixed(0)}% / 
                      M:{(currentExecutionParams.partialFillProbMedium * 100).toFixed(0)}% / 
                      L:{(currentExecutionParams.partialFillProbLarge * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Preflight Data Check */}
            {formData.symbol && formData.startDate && formData.endDate && (
              <div
                className={cn(
                  "rounded-lg border p-3",
                  preflight?.ok
                    ? "border-emerald-500/30 bg-emerald-500/5"
                    : "border-amber-500/30 bg-amber-500/5",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {preflightLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    ) : preflight?.ok ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                    )}
                    <span className="text-sm font-medium">Backtest Preflight</span>
                  </div>
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => refetchPreflight()}>
                    <RefreshCw className="h-3 w-3 mr-1" />
                    Refresh
                  </Button>
                </div>

                {preflightLoading && (
                  <p className="text-xs text-muted-foreground mt-1.5">Checking source data availability...</p>
                )}

                {preflightError && (
                  <p className="text-xs text-red-500 mt-1.5">
                    Preflight check failed: {preflightErrorObj instanceof Error ? preflightErrorObj.message : "Unknown error"}
                  </p>
                )}

                {!preflightLoading && !preflightError && preflight && (
                  <div className="mt-2 space-y-1.5 text-xs">
                    <p className={cn(preflight.ok ? "text-emerald-600" : "text-amber-600")}>
                      {preflight.ok
                        ? "Data coverage looks valid for this range."
                        : "No usable source data in this range. Adjust date window or run backfill."}
                    </p>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded border border-border/60 bg-background/70 px-2 py-1.5">
                        <p className="text-muted-foreground">Decision events</p>
                        <p className="font-semibold">{preflight.decision_events_count.toLocaleString()}</p>
                      </div>
                      <div className="rounded border border-border/60 bg-background/70 px-2 py-1.5">
                        <p className="text-muted-foreground">Market candles</p>
                        <p className="font-semibold">{preflight.market_candles_count.toLocaleString()}</p>
                      </div>
                    </div>
                    <p className="text-muted-foreground">
                      Decision range:{" "}
                      {preflight.decision_events_range?.start
                        ? `${formatDateDisplay(preflight.decision_events_range.start)} → ${formatDateDisplay(preflight.decision_events_range.end || "")}`
                        : "No data"}
                    </p>
                    <p className="text-muted-foreground">
                      Candle range:{" "}
                      {preflight.market_candles_range?.start
                        ? `${formatDateDisplay(preflight.market_candles_range.start)} → ${formatDateDisplay(preflight.market_candles_range.end || "")}`
                        : "No data"}
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Warm Start Configuration - Feature: trading-pipeline-integration, Requirements: 3.1, 3.6 */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-amber-500" />
                  <Label className="text-sm font-medium">Start from Live State</Label>
                </div>
                <Switch
                  checked={formData.warmStartEnabled}
                  onCheckedChange={(checked) => setFormData({ ...formData, warmStartEnabled: checked })}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Initialize the backtest with current live positions, account state, and recent history.
                This allows testing strategy changes from your current market position.
              </p>

              {/* Warm Start State Preview */}
              {formData.warmStartEnabled && (
                <div className="space-y-3 pt-2">
                  {warmStartLoading && (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading live state...
                    </div>
                  )}

                  {warmStartError && (
                    <Alert variant="destructive">
                      <AlertCircle className="h-4 w-4" />
                      <AlertTitle>Failed to load live state</AlertTitle>
                      <AlertDescription className="text-xs">
                        Unable to fetch current live state. The backtest will start from scratch.
                      </AlertDescription>
                    </Alert>
                  )}

                  {warmStartState && (
                    <>
                      {/* Staleness Warning - Requirements: 3.6 */}
                      {warmStartState.is_stale && (
                        <Alert className="border-amber-500/50 bg-amber-500/10">
                          <AlertTriangle className="h-4 w-4 text-amber-500" />
                          <AlertTitle className="text-amber-600">Stale State Warning</AlertTitle>
                          <AlertDescription className="text-xs text-muted-foreground">
                            The live state snapshot is {Math.floor(warmStartState.age_seconds / 60)} minutes old.
                            Consider refreshing before running the backtest.
                            <Button 
                              variant="ghost" 
                              size="sm" 
                              className="h-auto p-0 ml-2 text-amber-600 hover:text-amber-700"
                              onClick={() => refetchWarmStart()}
                            >
                              <RefreshCw className="h-3 w-3 mr-1" />
                              Refresh
                            </Button>
                          </AlertDescription>
                        </Alert>
                      )}

                      {/* Validation Errors */}
                      {!warmStartState.is_valid && warmStartState.validation_errors.length > 0 && (
                        <Alert variant="destructive">
                          <AlertCircle className="h-4 w-4" />
                          <AlertTitle>State Validation Failed</AlertTitle>
                          <AlertDescription className="text-xs">
                            {warmStartState.validation_errors.join(", ")}
                          </AlertDescription>
                        </Alert>
                      )}

                      {/* State Preview */}
                      <div className="rounded-lg bg-muted/30 p-3 space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium">Live State Preview</span>
                          <Badge variant="outline" className={cn(
                            "text-[10px]",
                            warmStartState.is_stale 
                              ? "text-amber-500 border-amber-500/30" 
                              : "text-emerald-500 border-emerald-500/30"
                          )}>
                            <Clock className="h-3 w-3 mr-1" />
                            {Math.floor(warmStartState.age_seconds)}s ago
                          </Badge>
                        </div>

                        {/* Account State */}
                        <div className="grid grid-cols-2 gap-3">
                          <div className="rounded-lg border bg-background p-2">
                            <p className="text-[10px] text-muted-foreground">Account Equity</p>
                            <p className="text-sm font-bold text-emerald-500">
                              ${warmStartState.account_state.equity?.toLocaleString() || "0"}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-background p-2">
                            <p className="text-[10px] text-muted-foreground">Open Positions</p>
                            <p className="text-sm font-bold">
                              {warmStartState.positions.length}
                            </p>
                          </div>
                        </div>

                        {/* Positions Preview */}
                        {warmStartState.positions.length > 0 && (
                          <div className="space-y-2">
                            <p className="text-[10px] font-medium text-muted-foreground">Current Positions</p>
                            <div className="space-y-1.5">
                              {warmStartState.positions.slice(0, 3).map((pos, idx) => (
                                <div 
                                  key={idx} 
                                  className="flex items-center justify-between text-xs rounded-lg border bg-background px-2 py-1.5"
                                >
                                  <div className="flex items-center gap-2">
                                    <Badge 
                                      variant="outline" 
                                      className={cn(
                                        "text-[9px] px-1",
                                        pos.side === "long" || pos.side === "buy"
                                          ? "text-emerald-500 border-emerald-500/30"
                                          : "text-red-500 border-red-500/30"
                                      )}
                                    >
                                      {pos.side?.toUpperCase()}
                                    </Badge>
                                    <span className="font-medium">{pos.symbol}</span>
                                  </div>
                                  <div className="text-right">
                                    <span className="text-muted-foreground">Size: </span>
                                    <span className="font-mono">{pos.size}</span>
                                    <span className="text-muted-foreground ml-2">@ </span>
                                    <span className="font-mono">${pos.entry_price?.toLocaleString()}</span>
                                  </div>
                                </div>
                              ))}
                              {warmStartState.positions.length > 3 && (
                                <p className="text-[10px] text-muted-foreground text-center">
                                  +{warmStartState.positions.length - 3} more positions
                                </p>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Snapshot Time */}
                        <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t">
                          <span>Snapshot Time</span>
                          <span>{new Date(warmStartState.snapshot_time).toLocaleString()}</span>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Profile Parameter Overrides */}
            <Accordion type="single" collapsible className="border rounded-lg">
              <AccordionItem value="overrides" className="border-none">
                <AccordionTrigger className="px-4 py-3 hover:no-underline">
                  <div className="flex items-center gap-2">
                    <FlaskConical className="h-4 w-4 text-purple-500" />
                    <span className="text-sm font-medium">Advanced: Override Profile Parameters</span>
                    {Object.keys(formData.profileOverrides).length > 0 && (
                      <Badge variant="secondary" className="ml-2 text-xs">
                        {Object.keys(formData.profileOverrides).length} override{Object.keys(formData.profileOverrides).length !== 1 ? 's' : ''}
                      </Badge>
                    )}
                  </div>
                </AccordionTrigger>
                <AccordionContent className="px-4 pb-4 space-y-3">
                  <p className="text-xs text-muted-foreground">
                    Test "what if" scenarios by overriding profile risk parameters without editing code.
                    Common overrides: risk_per_trade_pct, max_leverage, stop_loss_pct, take_profit_pct
                  </p>
                  
                  {/* Quick Presets */}
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs h-7"
                      onClick={() => setFormData({ ...formData, profileOverrides: { risk_per_trade_pct: 0.02, max_leverage: 3.0 } })}
                    >
                      Aggressive (2% risk, 3x leverage)
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs h-7"
                      onClick={() => setFormData({ ...formData, profileOverrides: { risk_per_trade_pct: 0.005, max_leverage: 1.0 } })}
                    >
                      Conservative (0.5% risk, 1x leverage)
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs h-7"
                      onClick={() => setFormData({ ...formData, profileOverrides: {} })}
                    >
                      Clear All
                    </Button>
                  </div>

                  {/* Override Inputs */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-xs">risk_per_trade_pct</Label>
                      <Input
                        type="number"
                        step="0.001"
                        placeholder="e.g. 0.015 (1.5%)"
                        className="h-8 text-xs mt-1"
                        value={formData.profileOverrides.risk_per_trade_pct || ''}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          const newOverrides = { ...formData.profileOverrides };
                          if (isNaN(val) || e.target.value === '') {
                            delete newOverrides.risk_per_trade_pct;
                          } else {
                            newOverrides.risk_per_trade_pct = val;
                          }
                          setFormData({ ...formData, profileOverrides: newOverrides });
                        }}
                      />
                    </div>
                    <div>
                      <Label className="text-xs">max_leverage</Label>
                      <Input
                        type="number"
                        step="0.1"
                        placeholder="e.g. 2.0"
                        className="h-8 text-xs mt-1"
                        value={formData.profileOverrides.max_leverage || ''}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          const newOverrides = { ...formData.profileOverrides };
                          if (isNaN(val) || e.target.value === '') {
                            delete newOverrides.max_leverage;
                          } else {
                            newOverrides.max_leverage = val;
                          }
                          setFormData({ ...formData, profileOverrides: newOverrides });
                        }}
                      />
                    </div>
                    <div>
                      <Label className="text-xs">stop_loss_pct</Label>
                      <Input
                        type="number"
                        step="0.001"
                        placeholder="e.g. 0.01 (1%)"
                        className="h-8 text-xs mt-1"
                        value={formData.profileOverrides.stop_loss_pct || ''}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          const newOverrides = { ...formData.profileOverrides };
                          if (isNaN(val) || e.target.value === '') {
                            delete newOverrides.stop_loss_pct;
                          } else {
                            newOverrides.stop_loss_pct = val;
                          }
                          setFormData({ ...formData, profileOverrides: newOverrides });
                        }}
                      />
                    </div>
                    <div>
                      <Label className="text-xs">take_profit_pct</Label>
                      <Input
                        type="number"
                        step="0.001"
                        placeholder="e.g. 0.015 (1.5%)"
                        className="h-8 text-xs mt-1"
                        value={formData.profileOverrides.take_profit_pct || ''}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          const newOverrides = { ...formData.profileOverrides };
                          if (isNaN(val) || e.target.value === '') {
                            delete newOverrides.take_profit_pct;
                          } else {
                            newOverrides.take_profit_pct = val;
                          }
                          setFormData({ ...formData, profileOverrides: newOverrides });
                        }}
                      />
                    </div>
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>

            <div className="flex justify-between pt-2">
              <Button variant="outline" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button onClick={() => setStep(3)}>
                Next <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: Review & Run */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Review & Run</CardTitle>
            <CardDescription>Confirm your backtest configuration</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label>Run Name (optional)</Label>
              <Input
                className="mt-1.5"
                placeholder="Auto-generated if empty"
                value={formData.runName}
                onChange={(e) => setFormData({ ...formData, runName: e.target.value })}
              />
            </div>

            {/* Force Run Option */}
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
              <div className="flex items-start gap-3">
                <Checkbox
                  id="forceRun"
                  checked={formData.forceRun}
                  onCheckedChange={(checked) => setFormData({ ...formData, forceRun: checked === true })}
                />
                <div className="flex-1">
                  <Label htmlFor="forceRun" className="text-sm font-medium cursor-pointer">
                    Force Run (bypass data validation)
                  </Label>
                  <p className="text-xs text-muted-foreground mt-1">
                    Enable this to run the backtest even if data quality checks fail (e.g., gaps in data, incomplete coverage). 
                    Results may be less reliable.
                  </p>
                </div>
                <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
              </div>
            </div>

            <div className="rounded-lg border p-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Strategy</span>
                <span className="font-medium">
                  {formData.strategy === "all" 
                    ? "🤖 All Strategies (Auto-Select)" 
                    : (strategies.find((s: any) => s.id === formData.strategy)?.name || formData.strategy)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Symbol</span>
                <span className="font-medium">{formData.symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Period</span>
                <span className="font-medium">{formatDateDisplay(formData.startDate)} – {formatDateDisplay(formData.endDate)}</span>
              </div>
              {dateRangeInfo && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Duration</span>
                  <span className="font-medium">
                    {dateRangeInfo.days > 0 
                      ? `${dateRangeInfo.days} day${dateRangeInfo.days !== 1 ? 's' : ''}${dateRangeInfo.hours > 0 ? ` ${dateRangeInfo.hours}h` : ''}`
                      : dateRangeInfo.hours > 0 
                        ? `${dateRangeInfo.hours}h ${dateRangeInfo.minutes}m`
                        : `${dateRangeInfo.minutes} minutes`
                    }
                  </span>
                </div>
              )}
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Initial Capital</span>
                <span className="font-medium">{formData.initialCapital.toLocaleString()} USDT</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Maker Fee</span>
                <span className="font-medium">{formData.makerFeeBps} bps</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Taker Fee</span>
                <span className="font-medium">{formData.takerFeeBps} bps</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Slippage</span>
                <span className="font-medium">
                  {formData.slippageModel === "none" ? "None" : `${formData.slippageModel} (${formData.slippageBps} bps)`}
                </span>
              </div>
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Est. Round Trip Cost</span>
                <span className="font-medium text-amber-600">
                  ~{((formData.makerFeeBps || 0) + (formData.takerFeeBps || 0) + (formData.slippageModel !== "none" ? formData.slippageBps : 0)).toFixed(1)} bps
                </span>
              </div>
              {/* Execution Scenario Summary - Feature: trading-pipeline-integration, Requirements: 5.5 */}
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Execution Scenario</span>
                <span className={cn(
                  "font-medium flex items-center gap-1",
                  formData.executionScenario === "optimistic" && "text-emerald-500",
                  formData.executionScenario === "realistic" && "text-blue-500",
                  formData.executionScenario === "pessimistic" && "text-amber-500",
                  formData.executionScenario === "custom" && "text-purple-500"
                )}>
                  {formData.executionScenario === "optimistic" && <Zap className="h-3 w-3" />}
                  {formData.executionScenario === "realistic" && <Target className="h-3 w-3" />}
                  {formData.executionScenario === "pessimistic" && <Shield className="h-3 w-3" />}
                  {formData.executionScenario === "custom" && <Settings className="h-3 w-3" />}
                  {formData.executionScenario.charAt(0).toUpperCase() + formData.executionScenario.slice(1)}
                </span>
              </div>
              <div className="text-xs text-muted-foreground bg-muted/30 rounded-lg px-2 py-1.5">
                <div className="flex justify-between">
                  <span>Latency: {currentExecutionParams.baseLatencyMs}±{currentExecutionParams.latencyStdMs}ms</span>
                  <span>Slippage: {currentExecutionParams.baseSlippageBps}bps</span>
                </div>
              </div>
              {/* Warm Start Summary - Feature: trading-pipeline-integration, Requirements: 3.1 */}
              <Separator />
              <div className="flex justify-between">
                <span className="text-muted-foreground">Warm Start</span>
                <span className={cn(
                  "font-medium flex items-center gap-1",
                  formData.warmStartEnabled ? "text-emerald-500" : "text-muted-foreground"
                )}>
                  {formData.warmStartEnabled ? (
                    <>
                      <Zap className="h-3 w-3" />
                      Enabled
                      {warmStartState && (
                        <span className="text-xs text-muted-foreground ml-1">
                          ({warmStartState.positions.length} positions)
                        </span>
                      )}
                    </>
                  ) : (
                    "Disabled (Cold Start)"
                  )}
                </span>
              </div>
              {formData.warmStartEnabled && warmStartState?.is_stale && (
                <div className="flex items-center gap-2 text-xs text-amber-500 bg-amber-500/10 rounded-lg px-2 py-1.5">
                  <AlertTriangle className="h-3 w-3" />
                  <span>Warning: Live state is {Math.floor(warmStartState.age_seconds / 60)} minutes old</span>
                </div>
              )}
            </div>

            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep(2)}>
                Back
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={createBacktest.isPending || (!formData.forceRun && Boolean(preflight) && !preflight.ok)}
              >
                {createBacktest.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                    Submitting...
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-1.5" />
                    {!formData.forceRun && preflight && !preflight.ok ? "Blocked: No Data" : "Run Backtest"}
                  </>
                )}
              </Button>
            </div>
            {!formData.forceRun && preflight && !preflight.ok && (
              <p className="text-xs text-amber-600">
                Backtest submission is blocked by preflight. Enable Force Run to bypass.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Custom Execution Scenario Modal - Feature: trading-pipeline-integration, Requirements: 5.5 */}
      <Dialog open={customScenarioModalOpen} onOpenChange={setCustomScenarioModalOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5 text-purple-500" />
              Custom Execution Scenario
            </DialogTitle>
            <DialogDescription>
              Configure custom execution simulation parameters for more precise backtesting.
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            {/* Latency Configuration */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <Label className="text-sm font-medium">Latency Simulation</Label>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Base Latency (ms)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.customExecutionConfig.baseLatencyMs}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        baseLatencyMs: parseFloat(e.target.value) || 0,
                      },
                    })}
                    min={1}
                    max={500}
                    step={5}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    Average order-to-fill time
                  </p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Latency Std Dev (ms)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.customExecutionConfig.latencyStdMs}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        latencyStdMs: parseFloat(e.target.value) || 0,
                      },
                    })}
                    min={0}
                    max={200}
                    step={5}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    Latency variation
                  </p>
                </div>
              </div>
            </div>

            {/* Slippage Configuration */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center gap-2">
                <TrendingDown className="h-4 w-4 text-muted-foreground" />
                <Label className="text-sm font-medium">Slippage Model</Label>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Base Slippage (bps)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.customExecutionConfig.baseSlippageBps}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        baseSlippageBps: parseFloat(e.target.value) || 0,
                      },
                    })}
                    min={0}
                    max={20}
                    step={0.5}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    Minimum slippage per trade
                  </p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Depth Slippage Factor</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={formData.customExecutionConfig.depthSlippageFactor}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        depthSlippageFactor: parseFloat(e.target.value) || 0,
                      },
                    })}
                    min={0}
                    max={2}
                    step={0.1}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    Additional slippage per 10% of depth
                  </p>
                </div>
              </div>
            </div>

            {/* Partial Fill Configuration */}
            <div className="rounded-lg border p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-muted-foreground" />
                <Label className="text-sm font-medium">Partial Fill Probability</Label>
              </div>
              <p className="text-xs text-muted-foreground">
                Probability of partial fills based on order size relative to available liquidity
              </p>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="text-xs text-muted-foreground">Small Orders (&lt;1%)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={(formData.customExecutionConfig.partialFillProbSmall * 100).toFixed(0)}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        partialFillProbSmall: (parseFloat(e.target.value) || 0) / 100,
                      },
                    })}
                    min={0}
                    max={100}
                    step={1}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5 text-center">%</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Medium (1-5%)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={(formData.customExecutionConfig.partialFillProbMedium * 100).toFixed(0)}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        partialFillProbMedium: (parseFloat(e.target.value) || 0) / 100,
                      },
                    })}
                    min={0}
                    max={100}
                    step={1}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5 text-center">%</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Large (&gt;5%)</Label>
                  <Input
                    type="number"
                    className="mt-1"
                    value={(formData.customExecutionConfig.partialFillProbLarge * 100).toFixed(0)}
                    onChange={(e) => setFormData({
                      ...formData,
                      customExecutionConfig: {
                        ...formData.customExecutionConfig,
                        partialFillProbLarge: (parseFloat(e.target.value) || 0) / 100,
                      },
                    })}
                    min={0}
                    max={100}
                    step={1}
                  />
                  <p className="text-[10px] text-muted-foreground mt-0.5 text-center">%</p>
                </div>
              </div>
            </div>

            {/* Preset Quick Apply */}
            <div className="rounded-lg bg-muted/30 p-3">
              <p className="text-xs font-medium mb-2">Quick Apply Preset</p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 text-xs"
                  onClick={() => setFormData({
                    ...formData,
                    customExecutionConfig: executionScenarioPresets.optimistic,
                  })}
                >
                  <Zap className="h-3 w-3 mr-1 text-emerald-500" />
                  Optimistic
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 text-xs"
                  onClick={() => setFormData({
                    ...formData,
                    customExecutionConfig: executionScenarioPresets.realistic,
                  })}
                >
                  <Target className="h-3 w-3 mr-1 text-blue-500" />
                  Realistic
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 text-xs"
                  onClick={() => setFormData({
                    ...formData,
                    customExecutionConfig: executionScenarioPresets.pessimistic,
                  })}
                >
                  <Shield className="h-3 w-3 mr-1 text-amber-500" />
                  Pessimistic
                </Button>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCustomScenarioModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => setCustomScenarioModalOpen(false)}>
              <CheckCircle2 className="h-4 w-4 mr-1.5" />
              Apply Configuration
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ============================================================================
// COMPARE TAB
// ============================================================================

function CompareTab({
  selectedIds,
  onClearSelection,
}: {
  selectedIds: string[];
  onClearSelection: () => void;
}) {
  const { data: backtestsData } = useBacktests({});
  const selectedRuns = useMemo(() => {
    const runs =
      backtestsData?.backtests?.map((bt: any) => ({
        id: bt.id,
        name: bt.name || `Run ${bt.id}`,
        metrics: bt.results || null,
      })) || [];
    return runs.filter((r: any) => selectedIds.includes(r.id) && r.metrics);
  }, [backtestsData, selectedIds]);

  if (selectedRuns.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <GitCompare className="h-12 w-12 mb-4 opacity-30" />
        <p className="text-lg font-medium">Select runs to compare</p>
        <p className="text-sm">Go to the Runs tab and check 2–5 completed runs</p>
      </div>
    );
  }

  const metrics = ["returnPct", "maxDdPct", "sharpe", "profitFactor", "winRate", "tradesPerDay", "expectancy", "feeDragPct", "slippageDragPct"];
  const metricLabels: Record<string, string> = {
    returnPct: "Return %",
    maxDdPct: "Max DD %",
    sharpe: "Sharpe",
    profitFactor: "Profit Factor",
    winRate: "Win Rate %",
    tradesPerDay: "Trades/Day",
    expectancy: "Expectancy",
    feeDragPct: "Fee Drag %",
    slippageDragPct: "Slippage Drag %",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Comparing {selectedRuns.length} Runs</h3>
        <Button variant="outline" size="sm" onClick={onClearSelection}>
          Clear Selection
        </Button>
      </div>

      {/* Metric Delta Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Metric Comparison</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left p-2 font-medium">Metric</th>
                  {selectedRuns.map((run) => (
                    <th key={run.id} className="text-right p-2 font-medium">{run.name || run.id.slice(-4)}</th>
                  ))}
                  <th className="text-right p-2 font-medium">Δ (Best - Worst)</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((metric) => {
                  const values = selectedRuns.map((r) => r.metrics?.[metric as keyof typeof r.metrics] || 0);
                  const max = Math.max(...values);
                  const min = Math.min(...values);
                  const delta = max - min;
                  return (
                    <tr key={metric} className="border-b border-border/30">
                      <td className="p-2 text-muted-foreground">{metricLabels[metric]}</td>
                      {selectedRuns.map((run, i) => {
                        const val = run.metrics?.[metric as keyof typeof run.metrics] || 0;
                        const isBest = val === max && max !== min;
                        const isWorst = val === min && max !== min;
                        return (
                          <td key={run.id} className={cn(
                            "p-2 text-right font-mono",
                            isBest && "text-emerald-500 font-medium",
                            isWorst && "text-red-500"
                          )}>
                            {typeof val === "number" ? val.toFixed(2) : val}
                          </td>
                        );
                      })}
                      <td className="p-2 text-right font-mono text-muted-foreground">{delta.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* What Changed */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">What Changed Between Runs</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">
            Detailed config diff not available yet; add /research/backtests/compare or include config fields in backtest_runs to populate this view.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================================
// WALK-FORWARD TAB
// ============================================================================

function WalkForwardTab() {
  const [showSetup, setShowSetup] = useState(false);
  const [wfoConfig, setWfoConfig] = useState({
    profileId: "",
    symbol: "",
    exchange: "okx",
    timeframe: "5m",
    inSampleDays: 30,
    outSampleDays: 7,
    totalPeriods: 4,
    anchored: false,
    objective: "sharpe_ratio",
    paramSpaces: [] as { name: string; min: number; max: number; step: number }[],
  });

  const [newParam, setNewParam] = useState({ name: "", min: 0, max: 1, step: 0.1 });
  
  // Fetch datasets and strategies
  const { data: datasetsData } = useDatasets();
  const { data: strategiesData } = useResearchStrategies();
  const { data: wfoRunsData, isLoading } = useWfoRuns();
  const createWfoRun = useCreateWfoRun();
  
  const datasets = useMemo(() => {
    if (datasetsData?.datasets && datasetsData.datasets.length > 0) {
      return datasetsData.datasets.map((ds: any) => ({
        symbol: ds.symbol,
        exchange: ds.exchange || "okx",
      }));
    }
    return [];
  }, [datasetsData]);

  const strategies = useMemo(() => {
    if ((strategiesData as any)?.strategies) {
      return (strategiesData as any).strategies;
    }
    return [];
  }, [strategiesData]);

  const addParamSpace = () => {
    if (newParam.name) {
      setWfoConfig({
        ...wfoConfig,
        paramSpaces: [...wfoConfig.paramSpaces, { ...newParam }],
      });
      setNewParam({ name: "", min: 0, max: 1, step: 0.1 });
    }
  };

  const handleRunWfo = () => {
    if (!wfoConfig.profileId || !wfoConfig.symbol) {
      toast.error("Profile and symbol are required");
      return;
    }
    const payload = {
      profile_id: wfoConfig.profileId,
      symbol: wfoConfig.symbol,
      exchange: wfoConfig.exchange,
      timeframe: wfoConfig.timeframe,
      inSampleDays: wfoConfig.inSampleDays,
      outSampleDays: wfoConfig.outSampleDays,
      totalPeriods: wfoConfig.totalPeriods,
      anchored: wfoConfig.anchored,
      objective: wfoConfig.objective,
      paramSpaces: wfoConfig.paramSpaces,
    };
    createWfoRun.mutate(payload, {
      onSuccess: () => {
        toast.success("Walk-forward run submitted");
        setShowSetup(false);
      },
      onError: (err: any) => toast.error(err?.message || "Failed to submit WFO"),
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium">Walk-Forward Optimization</h3>
          <p className="text-sm text-muted-foreground">Optimize parameters while preventing overfitting</p>
        </div>
        <Button onClick={() => setShowSetup(true)}>
          <Plus className="h-4 w-4 mr-1.5" />
          New WFO
        </Button>
      </div>

      {/* Setup Form */}
      {showSetup && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">WFO Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Profile</Label>
                <select
                  className="w-full mt-1.5 h-9 px-3 rounded-md border border-border bg-background"
                  value={wfoConfig.profileId}
                  onChange={(e) => setWfoConfig({ ...wfoConfig, profileId: e.target.value })}
                >
                  <option value="">Select profile</option>
                  {strategies.map((s: any) => (
                    <option key={s.id} value={s.id}>{s.name || s.id}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label>Symbol</Label>
                <select
                  className="w-full mt-1.5 h-9 px-3 rounded-md border border-border bg-background"
                  value={wfoConfig.symbol}
                  onChange={(e) => setWfoConfig({ ...wfoConfig, symbol: e.target.value })}
                >
                  <option value="">Select symbol</option>
                  {datasets.map((d: any) => (
                    <option key={d.symbol} value={d.symbol}>{d.symbol}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-4 gap-4">
              <div>
                <Label>IS Days</Label>
                <Input
                  type="number"
                  className="mt-1.5"
                  value={wfoConfig.inSampleDays}
                  onChange={(e) => setWfoConfig({ ...wfoConfig, inSampleDays: parseInt(e.target.value) })}
                />
              </div>
              <div>
                <Label>OOS Days</Label>
                <Input
                  type="number"
                  className="mt-1.5"
                  value={wfoConfig.outSampleDays}
                  onChange={(e) => setWfoConfig({ ...wfoConfig, outSampleDays: parseInt(e.target.value) })}
                />
              </div>
              <div>
                <Label>Periods</Label>
                <Input
                  type="number"
                  className="mt-1.5"
                  value={wfoConfig.totalPeriods}
                  onChange={(e) => setWfoConfig({ ...wfoConfig, totalPeriods: parseInt(e.target.value) })}
                />
              </div>
              <div>
                <Label>Window Type</Label>
                <select
                  className="w-full mt-1.5 h-9 px-3 rounded-md border border-border bg-background"
                  value={wfoConfig.anchored ? "anchored" : "rolling"}
                  onChange={(e) => setWfoConfig({ ...wfoConfig, anchored: e.target.value === "anchored" })}
                >
                  <option value="rolling">Rolling</option>
                  <option value="anchored">Anchored</option>
                </select>
              </div>
            </div>

            <div>
              <Label>Objective</Label>
              <select
                className="w-full mt-1.5 h-9 px-3 rounded-md border border-border bg-background"
                value={wfoConfig.objective}
                onChange={(e) => setWfoConfig({ ...wfoConfig, objective: e.target.value })}
              >
                <option value="sharpe_ratio">Sharpe Ratio</option>
                <option value="total_pnl">Total PnL</option>
                <option value="win_rate">Win Rate</option>
                <option value="profit_factor">Profit Factor</option>
              </select>
            </div>

            {/* Parameter Spaces */}
            <div>
              <Label>Parameter Spaces</Label>
              <div className="mt-2 space-y-2">
                {wfoConfig.paramSpaces.map((p, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm bg-muted/30 rounded-lg px-3 py-2">
                    <span className="font-medium">{p.name}</span>
                    <span className="text-muted-foreground">min: {p.min}, max: {p.max}, step: {p.step}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0 ml-auto"
                      onClick={() => setWfoConfig({
                        ...wfoConfig,
                        paramSpaces: wfoConfig.paramSpaces.filter((_, j) => j !== i),
                      })}
                    >
                      <XCircle className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <Input
                      placeholder="Parameter name"
                      value={newParam.name}
                      onChange={(e) => setNewParam({ ...newParam, name: e.target.value })}
                    />
                  </div>
                  <div className="w-20">
                    <Input
                      type="number"
                      step="0.01"
                      placeholder="Min"
                      value={newParam.min}
                      onChange={(e) => setNewParam({ ...newParam, min: parseFloat(e.target.value) })}
                    />
                  </div>
                  <div className="w-20">
                    <Input
                      type="number"
                      step="0.01"
                      placeholder="Max"
                      value={newParam.max}
                      onChange={(e) => setNewParam({ ...newParam, max: parseFloat(e.target.value) })}
                    />
                  </div>
                  <div className="w-20">
                    <Input
                      type="number"
                      step="0.01"
                      placeholder="Step"
                      value={newParam.step}
                      onChange={(e) => setNewParam({ ...newParam, step: parseFloat(e.target.value) })}
                    />
                  </div>
                  <Button variant="outline" size="sm" onClick={addParamSpace}>
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowSetup(false)}>Cancel</Button>
              <Button onClick={handleRunWfo} disabled={!wfoConfig.profileId || !wfoConfig.symbol}>
                <Play className="h-4 w-4 mr-1.5" />
                Run WFO
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Walk-Forward Results</CardTitle>
          <CardDescription>Recent runs (Redis-backed)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <div className="text-sm text-muted-foreground">Loading runs…</div>
          ) : (wfoRunsData?.runs || []).length === 0 ? (
            <div className="text-sm text-muted-foreground">No WFO runs yet. Create one above.</div>
          ) : (
            <div className="space-y-3">
              {(wfoRunsData?.runs || []).map((run: any) => (
                <Card key={run.id} className="border-border/50">
                  <CardContent className="p-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium">{run.profile_id} • {run.symbol}</p>
                        <p className="text-xs text-muted-foreground">
                          {run.inSampleDays}d IS / {run.outSampleDays}d OOS • {run.totalPeriods} periods • {run.timeframe}
                        </p>
                      </div>
                      <Badge variant="outline" className="text-xs">{run.status}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground flex flex-wrap gap-2">
                      <span>Objective: {run.objective}</span>
                      <span>Anchored: {run.anchored ? "Yes" : "No"}</span>
                      <span>Created: {run.created_at}</span>
                    </div>
                    {run.results && (
                      <div className="text-xs space-y-1">
                        <div className="flex gap-4">
                          <span>IS PnL: {run.results.is_pnl}</span>
                          <span>OOS PnL: {run.results.oos_pnl}</span>
                          <span>Degradation: {run.results.degradation}</span>
                        </div>
                        <div className="flex gap-4">
                          <span>IS Sharpe: {run.results.is_sharpe}</span>
                          <span>OOS Sharpe: {run.results.oos_sharpe}</span>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================================
// DATASETS TAB
// ============================================================================

function DatasetsTab() {
  // Fetch real dataset data
  const { data: datasetsData, isLoading } = useDatasets();
  
  // Transform API data - no mock fallback
  const datasets = useMemo(() => {
    if (datasetsData?.datasets && datasetsData.datasets.length > 0) {
      return datasetsData.datasets.map((ds: any) => ({
        symbol: ds.symbol,
        exchange: ds.exchange || "okx",
        earliestDate: ds.earliest_date || ds.start_date,
        latestDate: ds.latest_date || ds.end_date,
        candleCount: ds.candle_count || 0,
        gaps: ds.gap_count || 0,
        gapDays: ds.gap_days || [],
      }));
    }
    return [];
  }, [datasetsData]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Available Datasets</h3>
        <Badge variant="outline" className="text-xs">
          {datasets.length} symbols
        </Badge>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="text-left p-3 font-medium">Symbol</th>
                  <th className="text-left p-3 font-medium">Exchange</th>
                  <th className="text-left p-3 font-medium">Coverage</th>
                  <th className="text-right p-3 font-medium">Candles</th>
                  <th className="text-center p-3 font-medium">Gaps</th>
                  <th className="text-center p-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((d: any) => {
                  const days = Math.ceil((new Date(d.latestDate).getTime() - new Date(d.earliestDate).getTime()) / (1000 * 60 * 60 * 24));
                  const exceedsLimit = d.candleCount > 5000 * 30; // 30 days at 5m
                  return (
                    <tr key={d.symbol} className="border-b border-border/30">
                      <td className="p-3 font-medium">{d.symbol}</td>
                      <td className="p-3 text-muted-foreground">{d.exchange}</td>
                      <td className="p-3">
                        <div>
                          <p className="text-xs">{d.earliestDate} – {d.latestDate}</p>
                          <p className="text-xs text-muted-foreground">{days} days</p>
                        </div>
                      </td>
                      <td className="p-3 text-right font-mono">{d.candleCount.toLocaleString()}</td>
                      <td className="p-3 text-center">
                        {d.gaps > 0 ? (
                          <Tooltip>
                            <TooltipTrigger>
                              <Badge variant="outline" className="text-xs text-amber-500 border-amber-500/30">
                                {d.gaps} gaps
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p className="text-xs">Missing: {d.gapDays.join(", ")}</p>
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <Badge variant="outline" className="text-xs text-emerald-500 border-emerald-500/30">Clean</Badge>
                        )}
                      </td>
                      <td className="p-3 text-center">
                        {exceedsLimit ? (
                          <Tooltip>
                            <TooltipTrigger>
                              <Badge variant="outline" className="text-xs text-amber-500 border-amber-500/30">
                                <AlertTriangle className="h-3 w-3 mr-1" />
                                Large
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p className="text-xs">May exceed 5000 candle limit for single run</p>
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <Badge variant="outline" className="text-xs text-emerald-500 border-emerald-500/30">
                            <CheckCircle2 className="h-3 w-3 mr-1" />
                            Ready
                          </Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card className="border-amber-500/30 bg-amber-500/5">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5" />
            <div>
              <p className="font-medium text-sm">Data Limits</p>
              <p className="text-xs text-muted-foreground mt-1">
                Backtest runs are limited to 5,000 candles per symbol. For longer periods, use a larger timeframe (e.g., 15m instead of 5m)
                or split into multiple runs.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function BacktestingPage() {
  const [activeTab, setActiveTab] = useState("runs");
  const [selectedRun, setSelectedRun] = useState<any | null>(null);
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);
  
  const rerunBacktest = useRerunBacktest();
  const promoteBacktest = usePromoteBacktestConfig();
  const deleteBacktest = useDeleteBacktest();

  const handleToggleCompare = (id: string) => {
    setSelectedForCompare((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : prev.length < 5 ? [...prev, id] : prev
    );
  };

  const handleClone = (run: any) => {
    setSelectedRun(null);
    setActiveTab("new");
    toast.success("Configuration loaded from run");
  };

  const handleRerun = (id: string, forceRun?: boolean) => {
    rerunBacktest.mutate({ id, force_run: forceRun }, {
      onSuccess: (data) => {
        const message = forceRun 
          ? `Backtest force rerun queued (${data.run_id.slice(0, 8)})` 
          : `Backtest rerun queued (${data.run_id.slice(0, 8)})`;
        toast.success(message);
        setSelectedRun(null);
      },
      onError: (error: any) => {
        toast.error(error?.message || "Failed to rerun backtest");
      },
    });
  };

  const handleDelete = (id: string) => {
    deleteBacktest.mutate(id, {
      onSuccess: () => {
        toast.success("Backtest deleted");
        setSelectedRun(null);
      },
      onError: (error: any) => {
        toast.error(error?.message || "Failed to delete backtest");
      },
    });
  };

  const handlePromote = (id: string) => {
    promoteBacktest.mutate(
      {
        id,
        notes: `Promoted from backtest ${id}`,
        activate: false,
        status: "draft",
      },
      {
        onSuccess: (data) => {
          toast.success(`Config promoted v${data.version_number}`);
        },
        onError: (error: any) => {
          toast.error(error?.message || "Failed to promote backtest config");
        },
      },
    );
  };

  return (
    <TooltipProvider>
      <DashBar />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Backtesting</h1>
            <p className="text-sm text-muted-foreground">
              Test strategies against historical data with realistic execution costs
            </p>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="runs" className="gap-1.5">
              <BarChart3 className="h-4 w-4" />
              Runs
            </TabsTrigger>
            <TabsTrigger value="new" className="gap-1.5">
              <Plus className="h-4 w-4" />
              New Backtest
            </TabsTrigger>
            <TabsTrigger value="compare" className="gap-1.5">
              <GitCompare className="h-4 w-4" />
              Compare
              {selectedForCompare.length > 0 && (
                <Badge variant="outline" className="ml-1 text-[10px] px-1">{selectedForCompare.length}</Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="datasets" className="gap-1.5">
              <Database className="h-4 w-4" />
              Datasets
            </TabsTrigger>
            <TabsTrigger value="wfo" className="gap-1.5">
              <RefreshCw className="h-4 w-4" />
              Walk-Forward
            </TabsTrigger>
          </TabsList>

          <TabsContent value="runs" className="mt-4">
            <RunsTab
              onSelectRun={setSelectedRun}
              selectedForCompare={selectedForCompare}
              onToggleCompare={handleToggleCompare}
            />
          </TabsContent>

          <TabsContent value="new" className="mt-4">
            <NewBacktestTab onSubmit={() => setActiveTab("runs")} />
          </TabsContent>

          <TabsContent value="compare" className="mt-4">
            <CompareTab
              selectedIds={selectedForCompare}
              onClearSelection={() => setSelectedForCompare([])}
            />
          </TabsContent>

          <TabsContent value="wfo" className="mt-4">
            <WalkForwardTab />
          </TabsContent>

          <TabsContent value="datasets" className="mt-4">
            <DatasetsTab />
          </TabsContent>
        </Tabs>

        {/* Run Detail Drawer */}
        <RunDetailDrawer
          run={selectedRun}
          onClose={() => setSelectedRun(null)}
          onClone={handleClone}
          onAddToCompare={(id) => {
            handleToggleCompare(id);
            toast.success("Added to compare");
          }}
          onRerun={handleRerun}
          onPromote={handlePromote}
          onDelete={handleDelete}
        />
      </div>
    </TooltipProvider>
  );
}
