import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Shield,
  TrendingDown,
  AlertTriangle,
  DollarSign,
  BarChart3,
  RefreshCw,
  Clock,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { Progress } from "../ui/progress";
import { cn } from "../../lib/utils";
import { fetchLossPreventionMetrics } from "../../lib/api/client";

interface LossPreventionMetrics {
  total_signals_rejected: number;
  rejection_breakdown: Record<string, number>;
  estimated_losses_avoided_usd: number;
  average_loss_per_trade_usd: number;
  low_confidence_count: number;
  strategy_trend_mismatch_count: number;
  fee_trap_count: number;
  session_mismatch_count: number;
  window_start: number;
  window_end: number;
}

interface LossPreventionPanelProps {
  botId?: string;
  tenantId?: string;
  windowHours?: number;
  className?: string;
}

// Human-readable labels for rejection reasons
const REJECTION_REASON_LABELS: Record<string, { label: string; description: string; color: string; icon: typeof Shield }> = {
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
    description: "Signal rejected by loss prevention filter",
    color: "text-muted-foreground",
    icon: Shield,
  };
}

function formatCurrency(value: number): string {
  if (Math.abs(value) >= 1000) {
    return `$${(value / 1000).toFixed(1)}k`;
  }
  return `$${value.toFixed(2)}`;
}

/**
 * Hook to fetch loss prevention metrics from the API
 */
export function useLossPreventionMetrics(
  botId?: string,
  tenantId?: string,
  options?: { refetchInterval?: number; windowHours?: number }
) {
  return useQuery({
    queryKey: ["loss-prevention-metrics", botId, tenantId, options?.windowHours],
    queryFn: async () => {
      const response = await fetchLossPreventionMetrics({
        botId,
        tenantId,
        windowHours: options?.windowHours ?? 24,
      });
      return response.data;
    },
    enabled: !!botId,
    refetchInterval: options?.refetchInterval ?? 10000,
    staleTime: 5000,
  });
}

function RejectionBreakdownBar({ breakdown, total }: { breakdown: Record<string, number>; total: number }) {
  const sortedReasons = useMemo(() => {
    return Object.entries(breakdown)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 4);
  }, [breakdown]);

  if (total === 0) {
    return (
      <div className="text-center py-4 text-muted-foreground text-sm">
        <Shield className="h-6 w-6 mx-auto mb-1 opacity-50" />
        <p>No signals rejected</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {sortedReasons.map(([reason, count]) => {
        const info = getReasonInfo(reason);
        const percentage = total > 0 ? (count / total) * 100 : 0;
        const Icon = info.icon;

        return (
          <Tooltip key={reason}>
            <TooltipTrigger asChild>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5">
                    <Icon className={cn("h-3 w-3", info.color)} />
                    <span className={info.color}>{info.label}</span>
                  </div>
                  <span className="font-mono text-muted-foreground">
                    {count} ({percentage.toFixed(0)}%)
                  </span>
                </div>
                <Progress value={percentage} className="h-1.5" />
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>{info.description}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {count} signals rejected
              </p>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

export function LossPreventionPanel({
  botId,
  tenantId,
  windowHours = 24,
  className,
}: LossPreventionPanelProps) {
  const { data: metrics, isLoading, refetch } = useLossPreventionMetrics(
    botId,
    tenantId,
    { windowHours }
  );

  const totalRejected = metrics?.total_signals_rejected ?? 0;
  const estimatedSaved = metrics?.estimated_losses_avoided_usd ?? 0;
  const breakdown = metrics?.rejection_breakdown ?? {};

  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Shield className="h-4 w-4 text-green-500" />
            Loss Prevention
            <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-500 border-green-500/30">
              Active
            </Badge>
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0"
            onClick={() => refetch()}
            disabled={isLoading}
          >
            <RefreshCw className={cn("h-3 w-3", isLoading && "animate-spin")} />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Key Metrics Row */}
        <div className="grid grid-cols-2 gap-4">
          {/* Total Rejected */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="p-3 rounded-lg bg-muted/50 border border-border">
                <div className="flex items-center gap-2 mb-1">
                  <BarChart3 className="h-4 w-4 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">Signals Rejected</span>
                </div>
                <div className="text-2xl font-bold font-mono">
                  {totalRejected.toLocaleString()}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  Last {windowHours}h
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>Total signals blocked by loss prevention filters</p>
              <p className="text-xs text-muted-foreground mt-1">
                These trades would likely have resulted in losses
              </p>
            </TooltipContent>
          </Tooltip>

          {/* Estimated Losses Avoided */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="p-3 rounded-lg bg-green-500/10 border border-green-500/30">
                <div className="flex items-center gap-2 mb-1">
                  <DollarSign className="h-4 w-4 text-green-500" />
                  <span className="text-xs text-green-600 dark:text-green-400">Losses Avoided</span>
                </div>
                <div className="text-2xl font-bold font-mono text-green-600 dark:text-green-400">
                  {formatCurrency(estimatedSaved)}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  Est. @ ${metrics?.average_loss_per_trade_usd?.toFixed(2) ?? "15.00"}/trade
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>Estimated losses avoided by rejecting low-quality signals</p>
              <p className="text-xs text-muted-foreground mt-1">
                Calculated as: rejected signals × avg loss per trade
              </p>
            </TooltipContent>
          </Tooltip>
        </div>

        {/* Rejection Reasons Breakdown */}
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">
            Rejection Reasons
          </p>
          <RejectionBreakdownBar breakdown={breakdown} total={totalRejected} />
        </div>

        {/* Quick Stats */}
        {totalRejected > 0 && (
          <div className="flex flex-wrap gap-2 pt-2 border-t border-border">
            {metrics?.low_confidence_count ? (
              <Badge variant="outline" className="text-[9px] text-amber-500 border-amber-500/30">
                <AlertTriangle className="h-2.5 w-2.5 mr-1" />
                Low Conf: {metrics.low_confidence_count}
              </Badge>
            ) : null}
            {metrics?.strategy_trend_mismatch_count ? (
              <Badge variant="outline" className="text-[9px] text-orange-500 border-orange-500/30">
                <TrendingDown className="h-2.5 w-2.5 mr-1" />
                Trend: {metrics.strategy_trend_mismatch_count}
              </Badge>
            ) : null}
            {metrics?.fee_trap_count ? (
              <Badge variant="outline" className="text-[9px] text-red-500 border-red-500/30">
                <DollarSign className="h-2.5 w-2.5 mr-1" />
                Fee Trap: {metrics.fee_trap_count}
              </Badge>
            ) : null}
            {metrics?.session_mismatch_count ? (
              <Badge variant="outline" className="text-[9px] text-blue-500 border-blue-500/30">
                <Clock className="h-2.5 w-2.5 mr-1" />
                Session: {metrics.session_mismatch_count}
              </Badge>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default LossPreventionPanel;
