import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Filter,
  Zap,
  Shield,
  TrendingUp,
  TrendingDown,
  DollarSign,
  AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { ScrollArea } from "../ui/scroll-area";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../ui/collapsible";
import { cn } from "../../lib/utils";
import { api } from "../../lib/api/client";

interface RejectedSignal {
  timestamp: string;
  symbol: string;
  rejection_reason: string;
  rejection_stage: string;
  gates_passed: string[];
  latency_ms?: number;
  mid_price?: number;
  spread_bps?: number;
  vol_regime?: string;
  trend_direction?: string;
  data_quality_score?: number;
  trading_mode?: string;
  min_depth_usd?: number;
  min_distance_from_poc_pct?: number;
  max_spread_bps?: number;
  min_depth_per_side_usd?: number;
  rejection_detail?: Record<string, any>;
  // Loss prevention specific fields
  confidence?: number;
  confidence_threshold?: number;
  expected_profit_usd?: number;
  round_trip_fee_usd?: number;
  strategy_id?: string;
  trend?: string;
  signal_side?: string;
}

interface RejectedSignalsStats {
  total_rejections: number;
  reason_counts: Record<string, number>;
  stage_counts: Record<string, number>;
  by_symbol: Record<string, { total: number; reasons: Record<string, number> }>;
  top_reason?: string;
  top_reason_count?: number;
}

interface RejectedSignalsProps {
  rejections: RejectedSignal[];
  stats: RejectedSignalsStats;
  isLoading?: boolean;
  onRefresh?: () => void;
  className?: string;
}

// Human-readable rejection reason labels
const REJECTION_REASON_LABELS: Record<string, { label: string; description: string; color: string; icon?: typeof Shield }> = {
  no_signal: {
    label: "No Signal",
    description: "Strategy conditions not met - waiting for better entry",
    color: "text-blue-500",
  },
  vol_shock_detected: {
    label: "Vol Shock",
    description: "Volatility spike detected - pausing for safety",
    color: "text-red-500",
  },
  prediction_blocked: {
    label: "Prediction Blocked",
    description: "ML model rejected the trade opportunity",
    color: "text-amber-500",
  },
  prediction_low_confidence: {
    label: "Low Confidence",
    description: "ML prediction confidence below threshold",
    color: "text-amber-500",
    icon: AlertTriangle,
  },
  prediction_direction_blocked: {
    label: "Direction Blocked",
    description: "Predicted direction not allowed by current settings",
    color: "text-amber-500",
  },
  cooldown_active: {
    label: "Cooldown Active",
    description: "Waiting for cooldown period to expire",
    color: "text-orange-500",
  },
  position_limit: {
    label: "Position Limit",
    description: "Maximum position count reached",
    color: "text-red-500",
  },
  exposure_limit: {
    label: "Exposure Limit",
    description: "Maximum exposure limit reached",
    color: "text-red-500",
  },
  spread_too_wide: {
    label: "Spread Too Wide",
    description: "Current spread exceeds maximum threshold",
    color: "text-amber-500",
  },
  depth_insufficient: {
    label: "Low Depth",
    description: "Order book depth below minimum threshold",
    color: "text-amber-500",
  },
  data_stale: {
    label: "Stale Data",
    description: "Market data too old for reliable trading",
    color: "text-red-500",
  },
  warmup_incomplete: {
    label: "Warmup",
    description: "System still warming up, collecting data",
    color: "text-blue-500",
  },
  // Loss prevention specific reasons
  low_confidence: {
    label: "Low Confidence",
    description: "Signal confidence below minimum threshold",
    color: "text-amber-500",
    icon: AlertTriangle,
  },
  confidence_gate: {
    label: "Low Confidence",
    description: "Signal confidence below minimum threshold",
    color: "text-amber-500",
    icon: AlertTriangle,
  },
  strategy_trend_mismatch: {
    label: "Trend Mismatch",
    description: "Strategy direction conflicts with market trend",
    color: "text-orange-500",
    icon: TrendingDown,
  },
  fee_trap: {
    label: "Fee Trap",
    description: "Expected profit less than 2x fees",
    color: "text-red-500",
    icon: DollarSign,
  },
  session_mismatch: {
    label: "Session Mismatch",
    description: "Trading session not optimal for strategy",
    color: "text-blue-500",
    icon: Clock,
  },
};

function getReasonInfo(reason: string) {
  return REJECTION_REASON_LABELS[reason] || {
    label: reason.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    description: "Signal rejected at this stage",
    color: "text-muted-foreground",
  };
}

function formatTimeAgo(timestamp: string): string {
  const now = Date.now();
  const time = new Date(timestamp).getTime();
  const diff = (now - time) / 1000;

  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/**
 * Format the rejection description based on the reason and details
 * Requirements: 1.5, 4.7
 */
function formatRejectionDescription(rejection: RejectedSignal): string {
  const reason = rejection.rejection_reason;
  const detail = rejection.rejection_detail || {};
  
  // Low confidence rejection - show confidence value and threshold (Requirement 1.5)
  if (reason === "low_confidence" || reason === "confidence_gate") {
    const confidence = rejection.confidence ?? detail.confidence;
    const threshold = rejection.confidence_threshold ?? detail.threshold;
    if (confidence != null && threshold != null) {
      return `Confidence ${(confidence * 100).toFixed(1)}% < threshold ${(threshold * 100).toFixed(0)}%`;
    }
  }
  
  // Fee trap rejection - show "Fee trap: edge $X < fees $Y" (Requirement 4.7)
  if (reason === "fee_trap") {
    const expectedProfit = rejection.expected_profit_usd ?? detail.expected_profit_usd;
    const fees = rejection.round_trip_fee_usd ?? detail.round_trip_fee_usd;
    if (expectedProfit != null && fees != null) {
      return `Fee trap: edge $${expectedProfit.toFixed(2)} < fees $${fees.toFixed(2)}`;
    }
  }
  
  // Strategy-trend mismatch - show strategy, trend, and signal direction
  if (reason === "strategy_trend_mismatch") {
    const strategy = rejection.strategy_id ?? detail.strategy_id;
    const trend = rejection.trend ?? detail.trend;
    const side = rejection.signal_side ?? detail.signal_side;
    if (strategy && trend && side) {
      return `${strategy}: ${side} signal in ${trend} trend`;
    }
  }
  
  // Session mismatch - show session info
  if (reason === "session_mismatch") {
    const session = detail.session;
    if (session) {
      return `Trading paused during ${session} session`;
    }
  }
  
  // Default to the standard description
  return getReasonInfo(reason).description;
}

function RejectionRow({ rejection }: { rejection: RejectedSignal }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const reasonInfo = getReasonInfo(rejection.rejection_reason);
  const description = formatRejectionDescription(rejection);
  const Icon = reasonInfo.icon || XCircle;

  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <CollapsibleTrigger asChild>
        <div
          className={cn(
            "flex items-center gap-2 p-2 rounded-md cursor-pointer transition-colors",
            "hover:bg-muted/50 bg-muted/20 border border-border"
          )}
        >
          <Icon className={cn("h-4 w-4 shrink-0", reasonInfo.color)} />

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant="outline" className="text-[10px] font-mono">
                {rejection.symbol.replace("-SWAP", "")}
              </Badge>
              <Badge
                variant="outline"
                className={cn("text-[10px]", reasonInfo.color)}
              >
                {reasonInfo.label}
              </Badge>
              {rejection.vol_regime && (
                <Badge variant="outline" className="text-[9px]">
                  {rejection.vol_regime}
                </Badge>
              )}
              {rejection.trading_mode && rejection.trading_mode !== "NORMAL" && (
                <Badge variant="outline" className="text-[9px] bg-amber-500/10 text-amber-500">
                  {rejection.trading_mode}
                </Badge>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground mt-0.5 truncate">
              {description}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[10px] text-muted-foreground">
              {formatTimeAgo(rejection.timestamp)}
            </span>
            {isExpanded ? (
              <ChevronUp className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            )}
          </div>
        </div>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="mt-1 p-3 bg-muted/30 rounded-md text-xs space-y-3">
          {/* Loss Prevention Details - show for specific rejection types */}
          {(rejection.rejection_reason === "low_confidence" || rejection.rejection_reason === "confidence_gate") && (
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
                Confidence Details
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Confidence:</span>
                  <span className={cn(
                    "font-mono",
                    (rejection.confidence ?? rejection.rejection_detail?.confidence ?? 0) < 0.5 
                      ? "text-red-500" 
                      : "text-amber-500"
                  )}>
                    {((rejection.confidence ?? rejection.rejection_detail?.confidence ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Threshold:</span>
                  <span className="font-mono">
                    {((rejection.confidence_threshold ?? rejection.rejection_detail?.threshold ?? 0.5) * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Fee Trap Details */}
          {rejection.rejection_reason === "fee_trap" && (
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
                Fee Analysis
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Expected Edge:</span>
                  <span className="font-mono text-red-500">
                    ${(rejection.expected_profit_usd ?? rejection.rejection_detail?.expected_profit_usd ?? 0).toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Round-trip Fees:</span>
                  <span className="font-mono">
                    ${(rejection.round_trip_fee_usd ?? rejection.rejection_detail?.round_trip_fee_usd ?? 0).toFixed(2)}
                  </span>
                </div>
                {rejection.rejection_detail?.ratio != null && (
                  <div className="flex justify-between col-span-2">
                    <span className="text-muted-foreground">Edge/Fee Ratio:</span>
                    <span className={cn(
                      "font-mono",
                      rejection.rejection_detail.ratio < 2 ? "text-red-500" : "text-green-500"
                    )}>
                      {rejection.rejection_detail.ratio.toFixed(2)}x (need 2x)
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Strategy-Trend Mismatch Details */}
          {rejection.rejection_reason === "strategy_trend_mismatch" && (
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
                Strategy-Trend Analysis
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Strategy:</span>
                  <span className="font-mono">
                    {rejection.strategy_id ?? rejection.rejection_detail?.strategy_id ?? "unknown"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Signal Side:</span>
                  <span className={cn(
                    "font-mono",
                    (rejection.signal_side ?? rejection.rejection_detail?.signal_side) === "long" 
                      ? "text-green-500" 
                      : "text-red-500"
                  )}>
                    {(rejection.signal_side ?? rejection.rejection_detail?.signal_side ?? "unknown").toUpperCase()}
                  </span>
                </div>
                <div className="flex justify-between col-span-2">
                  <span className="text-muted-foreground">Market Trend:</span>
                  <span className={cn(
                    "font-mono",
                    (rejection.trend ?? rejection.rejection_detail?.trend) === "up" 
                      ? "text-green-500" 
                      : (rejection.trend ?? rejection.rejection_detail?.trend) === "down"
                        ? "text-red-500"
                        : "text-muted-foreground"
                  )}>
                    {(rejection.trend ?? rejection.rejection_detail?.trend ?? "unknown").toUpperCase()}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Market Snapshot */}
          <div>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
              Market Snapshot
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1">
              {rejection.mid_price && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Price:</span>
                  <span className="font-mono">${rejection.mid_price.toLocaleString()}</span>
                </div>
              )}
              {rejection.spread_bps != null && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Spread:</span>
                  <span className="font-mono">{Math.abs(rejection.spread_bps).toFixed(2)} bps</span>
                </div>
              )}
              {rejection.min_depth_usd && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Depth:</span>
                  <span className="font-mono">${(rejection.min_depth_usd / 1000).toFixed(0)}k</span>
                </div>
              )}
              {rejection.data_quality_score != null && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Quality:</span>
                  <span className={cn(
                    "font-mono",
                    rejection.data_quality_score >= 0.9 ? "text-green-500" : "text-amber-500"
                  )}>
                    {(rejection.data_quality_score * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Strategy Thresholds */}
          {(rejection.min_distance_from_poc_pct || rejection.max_spread_bps || rejection.min_depth_per_side_usd) && (
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
                Strategy Thresholds
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1">
                {rejection.min_distance_from_poc_pct && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Min POC Dist:</span>
                    <span className="font-mono">{(rejection.min_distance_from_poc_pct * 100).toFixed(2)}%</span>
                  </div>
                )}
                {rejection.max_spread_bps && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Max Spread:</span>
                    <span className="font-mono">{rejection.max_spread_bps.toFixed(2)} bps</span>
                  </div>
                )}
                {rejection.min_depth_per_side_usd && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Min Depth:</span>
                    <span className="font-mono">${(rejection.min_depth_per_side_usd / 1000).toFixed(0)}k</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Gates Passed */}
          {rejection.gates_passed && rejection.gates_passed.length > 0 && (
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
                Gates Passed ({rejection.gates_passed.length})
              </p>
              <div className="flex flex-wrap gap-1">
                {rejection.gates_passed.map((gate) => (
                  <Badge key={gate} variant="outline" className="text-[9px] bg-green-500/10 text-green-500 border-green-500/30">
                    <CheckCircle2 className="h-2 w-2 mr-1" />
                    {gate.replace(/_/g, " ")}
                  </Badge>
                ))}
                <Badge variant="outline" className="text-[9px] bg-red-500/10 text-red-500 border-red-500/30">
                  <XCircle className="h-2 w-2 mr-1" />
                  {rejection.rejection_stage?.replace(/_/g, " ") || "unknown"}
                </Badge>
              </div>
            </div>
          )}

          {/* Latency */}
          {rejection.latency_ms != null && (
            <div className="pt-2 border-t border-border">
              <span className="text-muted-foreground">Decision latency:</span>{" "}
              <span className="font-mono">{rejection.latency_ms.toFixed(2)}ms</span>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}


function StatsBar({ stats }: { stats: RejectedSignalsStats }) {
  const topReasons = Object.entries(stats.reason_counts || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-muted/50">
            <span className="text-muted-foreground">Total:</span>
            <span className="font-mono font-medium">{stats.total_rejections}</span>
          </div>
        </TooltipTrigger>
        <TooltipContent>Total rejected signals</TooltipContent>
      </Tooltip>

      {topReasons.map(([reason, count]) => {
        const info = getReasonInfo(reason);
        const Icon = info.icon || XCircle;
        const percentage = stats.total_rejections > 0 
          ? ((count / stats.total_rejections) * 100).toFixed(0) 
          : "0";
        return (
          <Tooltip key={reason}>
            <TooltipTrigger asChild>
              <Badge variant="outline" className={cn("text-[10px]", info.color)}>
                <Icon className="h-2.5 w-2.5 mr-1" />
                {info.label}: {count} ({percentage}%)
              </Badge>
            </TooltipTrigger>
            <TooltipContent>
              <p>{info.description}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {count} of {stats.total_rejections} rejections ({percentage}%)
              </p>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

/**
 * Hook to fetch rejected signals from the API
 */
export function useRejectedSignals(botId: string | undefined, options?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["rejected-signals", botId],
    queryFn: async () => {
      if (!botId) return { rejections: [], stats: {} };
      const response = await api.get(`/dashboard/rejected-signals?botId=${botId}&limit=50`);
      return response.data?.data || { rejections: [], stats: {} };
    },
    enabled: !!botId,
    refetchInterval: options?.refetchInterval ?? 5000,
    staleTime: 2000,
  });
}

export function RejectedSignals({
  rejections,
  stats,
  isLoading,
  onRefresh,
  className,
}: RejectedSignalsProps) {
  const [filter, setFilter] = useState<string>("all");

  const filteredRejections = useMemo(() => {
    if (filter === "all") return rejections;
    return rejections.filter((r) => r.rejection_reason === filter);
  }, [rejections, filter]);

  const filterOptions = useMemo(() => {
    const reasons = Object.keys(stats.reason_counts || {});
    return ["all", ...reasons];
  }, [stats.reason_counts]);

  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Zap className="h-4 w-4 text-muted-foreground" />
            Rejected Signals
            <Badge variant="outline" className="text-[10px]">
              {stats.total_rejections || 0}
            </Badge>
          </CardTitle>
          <div className="flex items-center gap-1">
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="h-6 text-xs px-2 rounded-md border bg-background"
            >
              {filterOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === "all" ? "All Reasons" : getReasonInfo(opt).label}
                </option>
              ))}
            </select>
            {onRefresh && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={onRefresh}
                disabled={isLoading}
              >
                <RefreshCw className={cn("h-3 w-3", isLoading && "animate-spin")} />
              </Button>
            )}
          </div>
        </div>
        <StatsBar stats={stats} />
      </CardHeader>

      <CardContent className="pt-2">
        {filteredRejections.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">
            <Shield className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No rejected signals</p>
            <p className="text-xs mt-1">All signals are passing through</p>
          </div>
        ) : (
          <ScrollArea className="h-[300px] pr-2">
            <div className="space-y-1">
              {filteredRejections.map((rejection, idx) => (
                <RejectionRow key={`${rejection.timestamp}-${idx}`} rejection={rejection} />
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

export default RejectedSignals;
