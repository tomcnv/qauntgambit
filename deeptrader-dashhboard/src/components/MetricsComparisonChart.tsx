/**
 * MetricsComparisonChart Component
 * 
 * Displays side-by-side comparison of live vs backtest metrics including:
 * - Return metrics (total_return_pct, annualized_return_pct)
 * - Risk metrics (sharpe_ratio, sortino_ratio, max_drawdown_pct)
 * - Trade metrics (total_trades, win_rate, profit_factor)
 * - Execution metrics (avg_slippage_bps, avg_latency_ms)
 * - Highlights significant differences (>10%)
 * - Shows divergence attribution factors
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 9.3, 9.4, 9.6**
 */

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { ScrollArea } from "./ui/scroll-area";
import { Separator } from "./ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "./ui/tooltip";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { useQuery } from "@tanstack/react-query";
import { 
  CheckCircle, 
  XCircle, 
  AlertTriangle, 
  Loader2, 
  TrendingUp,
  TrendingDown,
  BarChart3,
  Activity,
  Clock,
  ChevronDown,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Scale,
  Target,
  Zap,
  Percent,
  DollarSign,
  Timer
} from "lucide-react";
import { cn } from "../lib/utils";
import { useState } from "react";
import { botApiBaseUrl } from "../lib/quantgambit-url";

// ============================================================================
// Types
// ============================================================================

export interface UnifiedMetrics {
  // Return metrics
  total_return_pct: number;
  annualized_return_pct: number;
  
  // Risk metrics
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_duration_sec: number;
  
  // Trade metrics
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  profit_factor: number;
  avg_trade_pnl: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  
  // Execution metrics
  avg_slippage_bps: number;
  avg_latency_ms: number;
  partial_fill_rate: number;
}

export interface MetricDifference {
  live: number;
  backtest: number;
  diff_pct: number;
  significant: boolean;
}

export interface MetricsComparisonResponse {
  live_metrics: UnifiedMetrics;
  backtest_metrics: UnifiedMetrics;
  significant_differences: Record<string, MetricDifference>;
  divergence_factors: string[];
  overall_similarity: number;
  comparison_timestamp: string;
  has_significant_differences: boolean;
  backtest_run_id?: string | null;
  live_period_hours?: number | null;
}

export interface BacktestRunOption {
  run_id: string;
  name: string;
  created_at: string;
  status: string;
}

// ============================================================================
// API Functions
// ============================================================================

function getBotApiBaseUrl(): string {
  return botApiBaseUrl();
}

export const fetchMetricsComparison = async (
  backtestRunId: string,
  livePeriodHours: number = 24
): Promise<MetricsComparisonResponse> => {
  const params = new URLSearchParams({
    backtest_run_id: backtestRunId,
    live_period_hours: livePeriodHours.toString(),
  });
  
  const response = await fetch(`${getBotApiBaseUrl()}/metrics/compare?${params}`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to fetch metrics comparison: ${response.statusText}`);
  }
  
  return response.json();
};

export const fetchBacktestRuns = async (): Promise<{ backtests: BacktestRunOption[] }> => {
  const response = await fetch(`${API_BASE_URL}/research/backtests?status=completed&limit=20`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    throw new Error(`Failed to fetch backtest runs: ${response.statusText}`);
  }
  
  const data = await response.json();
  return {
    backtests: (data.backtests || []).map((bt: any) => ({
      run_id: bt.run_id || bt.id,
      name: bt.name || `Backtest ${bt.run_id?.slice(0, 8) || bt.id?.slice(0, 8)}`,
      created_at: bt.created_at,
      status: bt.status,
    })),
  };
};

// ============================================================================
// Custom Hooks
// ============================================================================

export const useMetricsComparison = (backtestRunId: string | null, livePeriodHours: number = 24) =>
  useQuery<MetricsComparisonResponse>({
    queryKey: ["metrics-comparison", backtestRunId, livePeriodHours],
    queryFn: () => fetchMetricsComparison(backtestRunId!, livePeriodHours),
    enabled: !!backtestRunId,
    staleTime: 60000, // 1 minute
    refetchInterval: false,
  });

export const useBacktestRuns = () =>
  useQuery<{ backtests: BacktestRunOption[] }>({
    queryKey: ["backtest-runs-for-comparison"],
    queryFn: fetchBacktestRuns,
    staleTime: 30000, // 30 seconds
  });

// ============================================================================
// Helper Functions
// ============================================================================

const formatTimestamp = (timestamp: string): string => {
  const date = new Date(timestamp);
  return date.toLocaleString([], { 
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit', 
    minute: '2-digit',
  });
};

const formatPercent = (value: number, decimals: number = 1): string => {
  return `${value.toFixed(decimals)}%`;
};

const formatNumber = (value: number, decimals: number = 2): string => {
  if (value === Infinity || value === 999.99) return "∞";
  return value.toFixed(decimals);
};

const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(0)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
};

const getDiffColor = (diffPct: number, significant: boolean): string => {
  if (!significant) return "text-muted-foreground";
  if (diffPct > 0) return "text-green-500";
  if (diffPct < 0) return "text-red-500";
  return "text-muted-foreground";
};

const getDiffBgColor = (significant: boolean): string => {
  if (significant) return "bg-amber-500/10 border-amber-500/30";
  return "bg-muted/50";
};

const getDiffIcon = (diffPct: number, significant: boolean) => {
  if (!significant) return <Minus className="h-3 w-3 text-muted-foreground" />;
  if (diffPct > 0) return <ArrowUpRight className="h-3 w-3 text-green-500" />;
  if (diffPct < 0) return <ArrowDownRight className="h-3 w-3 text-red-500" />;
  return <Minus className="h-3 w-3 text-muted-foreground" />;
};

// Metric display configuration
interface MetricConfig {
  key: keyof UnifiedMetrics;
  label: string;
  format: (value: number) => string;
  icon: React.ReactNode;
  lowerIsBetter?: boolean;
  description: string;
}

const RETURN_METRICS: MetricConfig[] = [
  {
    key: "total_return_pct",
    label: "Total Return",
    format: (v) => formatPercent(v),
    icon: <TrendingUp className="h-4 w-4" />,
    description: "Total return as percentage",
  },
  {
    key: "annualized_return_pct",
    label: "Annualized Return",
    format: (v) => formatPercent(v),
    icon: <TrendingUp className="h-4 w-4" />,
    description: "Annualized return as percentage",
  },
];

const RISK_METRICS: MetricConfig[] = [
  {
    key: "sharpe_ratio",
    label: "Sharpe Ratio",
    format: (v) => formatNumber(v),
    icon: <Scale className="h-4 w-4" />,
    description: "Risk-adjusted return (higher is better)",
  },
  {
    key: "sortino_ratio",
    label: "Sortino Ratio",
    format: (v) => formatNumber(v),
    icon: <Scale className="h-4 w-4" />,
    description: "Downside risk-adjusted return (higher is better)",
  },
  {
    key: "max_drawdown_pct",
    label: "Max Drawdown",
    format: (v) => formatPercent(v),
    icon: <TrendingDown className="h-4 w-4" />,
    lowerIsBetter: true,
    description: "Maximum peak-to-trough decline (lower is better)",
  },
];

const TRADE_METRICS: MetricConfig[] = [
  {
    key: "total_trades",
    label: "Total Trades",
    format: (v) => v.toLocaleString(),
    icon: <Activity className="h-4 w-4" />,
    description: "Total number of completed trades",
  },
  {
    key: "win_rate",
    label: "Win Rate",
    format: (v) => formatPercent(v * 100),
    icon: <Target className="h-4 w-4" />,
    description: "Ratio of winning trades to total",
  },
  {
    key: "profit_factor",
    label: "Profit Factor",
    format: (v) => formatNumber(v),
    icon: <DollarSign className="h-4 w-4" />,
    description: "Gross profit / gross loss ratio",
  },
];

const EXECUTION_METRICS: MetricConfig[] = [
  {
    key: "avg_slippage_bps",
    label: "Avg Slippage",
    format: (v) => `${formatNumber(v)} bps`,
    icon: <Zap className="h-4 w-4" />,
    lowerIsBetter: true,
    description: "Average slippage in basis points",
  },
  {
    key: "avg_latency_ms",
    label: "Avg Latency",
    format: (v) => `${formatNumber(v, 1)} ms`,
    icon: <Timer className="h-4 w-4" />,
    lowerIsBetter: true,
    description: "Average execution latency",
  },
];

// Parse divergence factor for display
const parseDivergenceFactor = (factor: string): { type: string; value: string; direction: string } => {
  // Format: "slippage_diff:+1.5bps (backtest higher)"
  const match = factor.match(/^(\w+):([^(]+)\s*\((.+)\)$/);
  if (match) {
    return {
      type: match[1].replace(/_/g, " "),
      value: match[2].trim(),
      direction: match[3],
    };
  }
  // Fallback for simpler formats
  const simpleMatch = factor.match(/^(\w+):(.+)$/);
  if (simpleMatch) {
    return {
      type: simpleMatch[1].replace(/_/g, " "),
      value: simpleMatch[2],
      direction: "",
    };
  }
  return { type: factor, value: "", direction: "" };
};

const getDivergenceIcon = (type: string) => {
  if (type.includes("slippage")) return <Zap className="h-3 w-3" />;
  if (type.includes("latency")) return <Timer className="h-3 w-3" />;
  if (type.includes("win_rate")) return <Target className="h-3 w-3" />;
  if (type.includes("profit")) return <DollarSign className="h-3 w-3" />;
  if (type.includes("drawdown")) return <TrendingDown className="h-3 w-3" />;
  if (type.includes("sharpe")) return <Scale className="h-3 w-3" />;
  if (type.includes("partial")) return <Percent className="h-3 w-3" />;
  return <AlertTriangle className="h-3 w-3" />;
};

// ============================================================================
// Sub-Components
// ============================================================================

interface SimilarityIndicatorProps {
  similarity: number;
  hasSignificantDifferences: boolean;
}

function SimilarityIndicator({ similarity, hasSignificantDifferences }: SimilarityIndicatorProps) {
  const similarityPercent = similarity * 100;
  const isHighSimilarity = similarityPercent >= 90;
  const isMediumSimilarity = similarityPercent >= 70 && similarityPercent < 90;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Overall Similarity</span>
        <span className={cn(
          "text-2xl font-bold",
          isHighSimilarity 
            ? "text-green-500"
            : isMediumSimilarity
            ? "text-amber-500"
            : "text-red-500"
        )}>
          {formatPercent(similarityPercent)}
        </span>
      </div>
      <Progress 
        value={similarityPercent} 
        className={cn(
          "h-3",
          isHighSimilarity 
            ? "[&>div]:bg-green-500"
            : isMediumSimilarity
            ? "[&>div]:bg-amber-500"
            : "[&>div]:bg-red-500"
        )}
      />
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
        {hasSignificantDifferences ? (
          <>
            <AlertTriangle className="h-3 w-3 text-amber-500" />
            <span>Significant differences detected</span>
          </>
        ) : (
          <>
            <CheckCircle className="h-3 w-3 text-green-500" />
            <span>Metrics are well aligned</span>
          </>
        )}
      </div>
    </div>
  );
}

interface MetricRowProps {
  config: MetricConfig;
  liveValue: number;
  backtestValue: number;
  difference?: MetricDifference;
}

function MetricRow({ config, liveValue, backtestValue, difference }: MetricRowProps) {
  const isSignificant = difference?.significant ?? false;
  const diffPct = difference?.diff_pct ?? 0;
  
  // For metrics where lower is better, invert the color logic
  const effectiveDiffPct = config.lowerIsBetter ? -diffPct : diffPct;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn(
            "grid grid-cols-4 gap-4 p-3 rounded-lg border transition-colors",
            isSignificant ? getDiffBgColor(true) : "hover:bg-muted/30"
          )}>
            {/* Metric Name */}
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">{config.icon}</span>
              <span className="text-sm font-medium">{config.label}</span>
            </div>
            
            {/* Live Value */}
            <div className="text-right">
              <Badge variant="outline" className="bg-blue-500/10 text-blue-600 border-blue-500/30">
                {config.format(liveValue)}
              </Badge>
            </div>
            
            {/* Backtest Value */}
            <div className="text-right">
              <Badge variant="outline" className="bg-purple-500/10 text-purple-600 border-purple-500/30">
                {config.format(backtestValue)}
              </Badge>
            </div>
            
            {/* Difference */}
            <div className="flex items-center justify-end gap-1">
              {getDiffIcon(effectiveDiffPct, isSignificant)}
              <span className={cn(
                "text-sm font-medium",
                getDiffColor(effectiveDiffPct, isSignificant)
              )}>
                {diffPct !== 0 ? `${diffPct > 0 ? '+' : ''}${formatPercent(diffPct)}` : '—'}
              </span>
              {isSignificant && (
                <AlertTriangle className="h-3 w-3 text-amber-500 ml-1" />
              )}
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent side="left" className="max-w-xs">
          <div className="space-y-1">
            <p className="font-medium">{config.label}</p>
            <p className="text-xs text-muted-foreground">{config.description}</p>
            {isSignificant && (
              <p className="text-xs text-amber-500">
                Difference exceeds 10% threshold
              </p>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

interface MetricsSectionProps {
  title: string;
  icon: React.ReactNode;
  metrics: MetricConfig[];
  liveMetrics: UnifiedMetrics;
  backtestMetrics: UnifiedMetrics;
  significantDifferences: Record<string, MetricDifference>;
}

function MetricsSection({ 
  title, 
  icon, 
  metrics, 
  liveMetrics, 
  backtestMetrics, 
  significantDifferences 
}: MetricsSectionProps) {
  const sectionHasSignificant = metrics.some(m => significantDifferences[m.key]?.significant);

  return (
    <Collapsible defaultOpen>
      <CollapsibleTrigger className="flex items-center justify-between w-full py-2 hover:bg-muted/50 rounded px-2 -mx-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          {icon}
          {title}
          {sectionHasSignificant && (
            <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-600 border-amber-500/30">
              Differences
            </Badge>
          )}
        </div>
        <ChevronDown className="h-4 w-4 text-muted-foreground" />
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-3 space-y-2">
        {/* Header Row */}
        <div className="grid grid-cols-4 gap-4 px-3 text-xs text-muted-foreground">
          <div>Metric</div>
          <div className="text-right">Live</div>
          <div className="text-right">Backtest</div>
          <div className="text-right">Diff</div>
        </div>
        {/* Metric Rows */}
        {metrics.map((config) => (
          <MetricRow
            key={config.key}
            config={config}
            liveValue={liveMetrics[config.key] as number}
            backtestValue={backtestMetrics[config.key] as number}
            difference={significantDifferences[config.key]}
          />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

interface DivergenceFactorsProps {
  factors: string[];
}

function DivergenceFactors({ factors }: DivergenceFactorsProps) {
  if (factors.length === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-4">
        No significant divergence factors identified
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {factors.map((factor, index) => {
        const parsed = parseDivergenceFactor(factor);
        return (
          <div 
            key={index}
            className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 border"
          >
            <div className="flex-shrink-0 mt-0.5 text-muted-foreground">
              {getDivergenceIcon(parsed.type)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium capitalize">{parsed.type}</span>
                {parsed.value && (
                  <Badge variant="outline" className="text-[10px]">
                    {parsed.value}
                  </Badge>
                )}
              </div>
              {parsed.direction && (
                <p className="text-xs text-muted-foreground mt-0.5">
                  {parsed.direction}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface BacktestSelectorProps {
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  runs: BacktestRunOption[];
  isLoading: boolean;
}

function BacktestSelector({ selectedRunId, onSelect, runs, isLoading }: BacktestSelectorProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading backtests...
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        No completed backtests available
      </div>
    );
  }

  return (
    <Select value={selectedRunId || ""} onValueChange={onSelect}>
      <SelectTrigger className="w-[280px]">
        <SelectValue placeholder="Select a backtest run" />
      </SelectTrigger>
      <SelectContent>
        {runs.map((run) => (
          <SelectItem key={run.run_id} value={run.run_id}>
            <div className="flex flex-col">
              <span>{run.name}</span>
              <span className="text-xs text-muted-foreground">
                {formatTimestamp(run.created_at)}
              </span>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// ============================================================================
// Main Component
// ============================================================================

interface MetricsComparisonChartProps {
  /** Pre-selected backtest run ID (optional) */
  backtestRunId?: string | null;
  /** Pre-loaded comparison data (optional, will fetch if not provided) */
  comparison?: MetricsComparisonResponse | null;
  /** Whether to show in compact mode */
  compact?: boolean;
  /** Live period in hours for comparison (default: 24) */
  livePeriodHours?: number;
}

export function MetricsComparisonChart({ 
  backtestRunId: initialRunId,
  comparison: preloadedComparison,
  compact = false,
  livePeriodHours = 24,
}: MetricsComparisonChartProps) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId || null);
  
  const { data: runsData, isLoading: runsLoading } = useBacktestRuns();
  const { 
    data: fetchedComparison, 
    isLoading: comparisonLoading, 
    error: comparisonError,
  } = useMetricsComparison(
    preloadedComparison ? null : selectedRunId,
    livePeriodHours
  );

  const comparison = preloadedComparison || fetchedComparison;
  const runs = runsData?.backtests || [];

  // Loading state for comparison
  if (comparisonLoading && !comparison) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading metrics comparison...</span>
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (comparisonError && !comparison) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <span className="ml-2 text-muted-foreground">
            {comparisonError instanceof Error ? comparisonError.message : 'Failed to load metrics comparison'}
          </span>
        </CardContent>
      </Card>
    );
  }

  // No comparison data state (need to select a backtest)
  if (!comparison) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Live vs Backtest Metrics
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">Compare with:</span>
            <BacktestSelector
              selectedRunId={selectedRunId}
              onSelect={setSelectedRunId}
              runs={runs}
              isLoading={runsLoading}
            />
          </div>
          <div className="text-center py-8">
            <BarChart3 className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              Select a backtest run to compare metrics
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Comparison will show live trading metrics vs backtest results
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const similarityPercent = comparison.overall_similarity * 100;
  const isHighSimilarity = similarityPercent >= 90;
  const isMediumSimilarity = similarityPercent >= 70 && similarityPercent < 90;

  // Compact version for header/sidebar
  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2 cursor-pointer">
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
              <Badge 
                variant="outline" 
                className={cn(
                  isHighSimilarity 
                    ? "bg-green-500/10 text-green-600 border-green-500/30"
                    : isMediumSimilarity
                    ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                    : "bg-red-500/10 text-red-600 border-red-500/30"
                )}
              >
                {formatPercent(similarityPercent)} Similar
              </Badge>
              {comparison.has_significant_differences && (
                <AlertTriangle className="h-3 w-3 text-amber-500" />
              )}
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs">
            <div className="space-y-2">
              <p className="font-medium">Live vs Backtest Comparison</p>
              <div className="text-xs space-y-1">
                <div className="flex justify-between gap-4">
                  <span>Overall Similarity:</span>
                  <span className="font-medium">{formatPercent(similarityPercent)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span>Significant Differences:</span>
                  <span className="font-medium">
                    {Object.keys(comparison.significant_differences).length}
                  </span>
                </div>
                <div className="flex justify-between gap-4">
                  <span>Divergence Factors:</span>
                  <span className="font-medium">{comparison.divergence_factors.length}</span>
                </div>
              </div>
            </div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // Full card version
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            Live vs Backtest Metrics
          </CardTitle>
          <Badge 
            variant="outline" 
            className={cn(
              isHighSimilarity 
                ? "bg-green-500/10 text-green-600 border-green-500/30"
                : isMediumSimilarity
                ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                : "bg-red-500/10 text-red-600 border-red-500/30"
            )}
          >
            <Activity className="h-3 w-3 mr-1" />
            {formatPercent(similarityPercent)} Similar
          </Badge>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            <span>Compared: {formatTimestamp(comparison.comparison_timestamp)}</span>
          </div>
          {comparison.live_period_hours && (
            <>
              <span>•</span>
              <span>Live: {comparison.live_period_hours}h</span>
            </>
          )}
          {comparison.backtest_run_id && (
            <>
              <span>•</span>
              <span>Backtest: {comparison.backtest_run_id.slice(0, 8)}...</span>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Backtest Selector */}
        {!preloadedComparison && (
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">Compare with:</span>
            <BacktestSelector
              selectedRunId={selectedRunId}
              onSelect={setSelectedRunId}
              runs={runs}
              isLoading={runsLoading}
            />
          </div>
        )}

        {/* Overall Similarity */}
        <SimilarityIndicator
          similarity={comparison.overall_similarity}
          hasSignificantDifferences={comparison.has_significant_differences}
        />

        {/* Summary Stats */}
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1 p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Activity className="h-3 w-3 text-blue-500" />
              Live Return
            </div>
            <p className={cn(
              "text-lg font-semibold",
              comparison.live_metrics.total_return_pct >= 0 ? "text-green-500" : "text-red-500"
            )}>
              {formatPercent(comparison.live_metrics.total_return_pct)}
            </p>
          </div>
          <div className="space-y-1 p-3 rounded-lg bg-purple-500/5 border border-purple-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <BarChart3 className="h-3 w-3 text-purple-500" />
              Backtest Return
            </div>
            <p className={cn(
              "text-lg font-semibold",
              comparison.backtest_metrics.total_return_pct >= 0 ? "text-green-500" : "text-red-500"
            )}>
              {formatPercent(comparison.backtest_metrics.total_return_pct)}
            </p>
          </div>
          <div className="space-y-1 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <AlertTriangle className="h-3 w-3 text-amber-500" />
              Differences
            </div>
            <p className="text-lg font-semibold text-amber-500">
              {Object.keys(comparison.significant_differences).length}
            </p>
          </div>
        </div>

        <Separator />

        {/* Metrics Sections */}
        <ScrollArea className="h-[400px] pr-4">
          <div className="space-y-6">
            {/* Return Metrics */}
            <MetricsSection
              title="Return Metrics"
              icon={<TrendingUp className="h-4 w-4" />}
              metrics={RETURN_METRICS}
              liveMetrics={comparison.live_metrics}
              backtestMetrics={comparison.backtest_metrics}
              significantDifferences={comparison.significant_differences}
            />

            <Separator />

            {/* Risk Metrics */}
            <MetricsSection
              title="Risk Metrics"
              icon={<Scale className="h-4 w-4" />}
              metrics={RISK_METRICS}
              liveMetrics={comparison.live_metrics}
              backtestMetrics={comparison.backtest_metrics}
              significantDifferences={comparison.significant_differences}
            />

            <Separator />

            {/* Trade Metrics */}
            <MetricsSection
              title="Trade Metrics"
              icon={<Target className="h-4 w-4" />}
              metrics={TRADE_METRICS}
              liveMetrics={comparison.live_metrics}
              backtestMetrics={comparison.backtest_metrics}
              significantDifferences={comparison.significant_differences}
            />

            <Separator />

            {/* Execution Metrics */}
            <MetricsSection
              title="Execution Metrics"
              icon={<Zap className="h-4 w-4" />}
              metrics={EXECUTION_METRICS}
              liveMetrics={comparison.live_metrics}
              backtestMetrics={comparison.backtest_metrics}
              significantDifferences={comparison.significant_differences}
            />
          </div>
        </ScrollArea>

        <Separator />

        {/* Divergence Attribution Factors */}
        <Collapsible defaultOpen={comparison.divergence_factors.length > 0}>
          <CollapsibleTrigger className="flex items-center justify-between w-full py-2 hover:bg-muted/50 rounded px-2 -mx-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <AlertTriangle className="h-4 w-4" />
              Divergence Attribution
              {comparison.divergence_factors.length > 0 && (
                <Badge variant="outline" className="text-[10px] ml-2">
                  {comparison.divergence_factors.length} factors
                </Badge>
              )}
            </div>
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-3">
            <DivergenceFactors factors={comparison.divergence_factors} />
          </CollapsibleContent>
        </Collapsible>

        {/* Warning for low similarity */}
        {comparison.overall_similarity < 0.70 && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <XCircle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-red-600">Low Similarity Detected</p>
              <p className="text-xs text-muted-foreground mt-1">
                Live and backtest metrics differ significantly ({formatPercent(similarityPercent)} similarity). 
                Review divergence factors and consider recalibrating the backtest model.
              </p>
            </div>
          </div>
        )}

        {/* Warning for significant differences */}
        {comparison.has_significant_differences && comparison.overall_similarity >= 0.70 && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-amber-600">Significant Differences Found</p>
              <p className="text-xs text-muted-foreground mt-1">
                {Object.keys(comparison.significant_differences).length} metric(s) differ by more than 10%. 
                Review the highlighted metrics and divergence factors above.
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default MetricsComparisonChart;
