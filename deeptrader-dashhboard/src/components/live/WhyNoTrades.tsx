import { useMemo } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Filter,
  Shield,
  TrendingDown,
  XCircle,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Progress } from "../ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { RejectFunnel, GateStats } from "./types";

interface WhyNoTradesProps {
  funnel: RejectFunnel & { isLive?: boolean };
  gates: GateStats[];
  decisionsPerSec: number;
  lastTradeAgo?: number; // seconds
  isPaper?: boolean; // Paper trading mode
  isBotRunning?: boolean; // Is the bot actively running
  className?: string;
}

function FunnelStep({
  label,
  count,
  prevCount,
  icon: Icon,
  color,
}: {
  label: string;
  count: number;
  prevCount?: number;
  icon: React.ElementType;
  color: string;
}) {
  const dropRate = prevCount && prevCount > 0 ? ((prevCount - count) / prevCount * 100) : 0;
  const hasSignificantDrop = dropRate > 30;

  return (
    <div className="flex items-center gap-2">
      <div className={cn("flex items-center gap-1.5 px-2 py-1 rounded-md bg-muted/50 min-w-[100px]")}>
        <Icon className={cn("h-3 w-3", color)} />
        <span className="text-[10px] text-muted-foreground">{label}</span>
        <span className="text-xs font-mono font-medium ml-auto">{count.toLocaleString()}</span>
      </div>
      {prevCount !== undefined && (
        <div className="flex items-center gap-1">
          <ArrowRight className="h-3 w-3 text-muted-foreground" />
          {hasSignificantDrop && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge 
                  variant="outline" 
                  className="text-[9px] px-1 h-4 bg-amber-500/10 text-amber-500 border-amber-500/30"
                >
                  -{dropRate.toFixed(0)}%
                </Badge>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                {prevCount - count} dropped at this stage
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      )}
    </div>
  );
}

function GateIndicator({ gate }: { gate: GateStats }) {
  const utilizationPct = gate.threshold > 0 ? (gate.current / gate.threshold) * 100 : 0;
  const isBlocking = gate.blocking;
  const isClose = utilizationPct > 70;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={cn(
          "flex items-center gap-2 px-2 py-1.5 rounded-md border",
          isBlocking 
            ? "bg-red-500/10 border-red-500/30" 
            : isClose 
              ? "bg-amber-500/10 border-amber-500/30"
              : "bg-muted/30 border-border"
        )}>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-medium truncate">{gate.name}</span>
              {isBlocking && <XCircle className="h-3 w-3 text-red-500 shrink-0" />}
            </div>
            <div className="flex items-center gap-1 mt-0.5">
              <Progress 
                value={Math.min(100, utilizationPct)} 
                className={cn(
                  "h-1 flex-1",
                  isBlocking ? "[&>div]:bg-red-500" : isClose ? "[&>div]:bg-amber-500" : ""
                )}
              />
              <span className="text-[9px] font-mono text-muted-foreground shrink-0">
                {gate.current.toFixed(2)}/{gate.threshold}{gate.unit}
              </span>
            </div>
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" className="text-xs">
        <p className="font-medium">{gate.name}</p>
        <p>Current: {gate.current.toFixed(4)} {gate.unit}</p>
        <p>Threshold: {gate.threshold} {gate.unit}</p>
        <p>Status: {isBlocking ? "BLOCKING" : isClose ? "Near limit" : "OK"}</p>
      </TooltipContent>
    </Tooltip>
  );
}

export function WhyNoTrades({
  funnel,
  gates,
  decisionsPerSec,
  lastTradeAgo,
  isPaper,
  isBotRunning,
  className,
}: WhyNoTradesProps) {
  const blockingGates = gates.filter(g => g.blocking);
  const hasBlockingGates = blockingGates.length > 0;
  const isFunnelLive = funnel.isLive ?? false;

  const statusMessage = useMemo(() => {
    // Check if bot is running first
    if (!isBotRunning && !isFunnelLive) {
      // Bot is not running
      if (isPaper && funnel.filled > 0) {
        return {
          text: `Bot stopped - ${funnel.filled} paper trades made`,
          color: "text-muted-foreground",
          icon: Clock,
        };
      }
      if (funnel.filled > 0) {
        return {
          text: `Bot stopped - last activity: ${lastTradeAgo ? formatTimeAgo(lastTradeAgo) : 'unknown'}`,
          color: "text-muted-foreground",
          icon: Clock,
        };
      }
      return {
        text: isPaper ? "Paper bot not running - start to begin trading" : "Bot not running",
        color: "text-muted-foreground",
        icon: Clock,
      };
    }
    
    // Paper trading mode - different status logic
    if (isPaper) {
      if (funnel.filled > 0) {
        return {
          text: "Paper trading active",
          color: "text-blue-500",
          icon: CheckCircle2,
        };
      }
      return {
        text: "Paper mode - awaiting signals",
        color: "text-blue-500",
        icon: Clock,
      };
    }
    
    if (hasBlockingGates) {
      return {
        text: `Blocked by: ${blockingGates.map(g => g.name).join(", ")}`,
        color: "text-red-500",
        icon: XCircle,
      };
    }
    if (funnel.evaluated === 0) {
      return {
        text: "No signals being evaluated",
        color: "text-muted-foreground",
        icon: Clock,
      };
    }
    if (funnel.approved === 0 && funnel.evaluated > 0) {
      return {
        text: "Signals being filtered (working as designed)",
        color: "text-amber-500",
        icon: Filter,
      };
    }
    if (funnel.filled > 0) {
      return {
        text: "Trading normally",
        color: "text-emerald-500",
        icon: CheckCircle2,
      };
    }
    return {
      text: "Waiting for opportunities",
      color: "text-blue-500",
      icon: Clock,
    };
  }, [funnel, hasBlockingGates, blockingGates, isPaper, isBotRunning, isFunnelLive, lastTradeAgo]);

  function formatTimeAgo(seconds: number): string {
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  }

  const StatusIcon = statusMessage.icon;

  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">Why No Trades?</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px] h-5 font-mono">
              {decisionsPerSec.toFixed(1)}/s
            </Badge>
            {lastTradeAgo !== undefined && (
              <Badge variant="outline" className="text-[10px] h-5">
                Last: {formatTimeAgo(lastTradeAgo)}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Status message */}
        <div className={cn("flex items-center gap-2 px-3 py-2 rounded-md bg-muted/30", statusMessage.color)}>
          <StatusIcon className="h-4 w-4" />
          <span className="text-sm font-medium">{statusMessage.text}</span>
        </div>

        {/* Decision funnel */}
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">Decision Funnel (last 15m)</p>
          <div className="flex flex-wrap items-center gap-1">
            <FunnelStep 
              label="Evaluated" 
              count={funnel.evaluated} 
              icon={Zap}
              color="text-blue-500"
            />
            <FunnelStep 
              label="Gated" 
              count={funnel.gated} 
              prevCount={funnel.evaluated}
              icon={Shield}
              color="text-violet-500"
            />
            <FunnelStep 
              label="Approved" 
              count={funnel.approved} 
              prevCount={funnel.gated}
              icon={CheckCircle2}
              color="text-emerald-500"
            />
            <FunnelStep 
              label="Ordered" 
              count={funnel.ordered} 
              prevCount={funnel.approved}
              icon={TrendingDown}
              color="text-amber-500"
            />
            <FunnelStep 
              label="Filled" 
              count={funnel.filled} 
              prevCount={funnel.ordered}
              icon={CheckCircle2}
              color="text-emerald-500"
            />
          </div>
        </div>

        {/* Gate status */}
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2">
            Gate Status
            {hasBlockingGates && (
              <span className="text-red-500 ml-2">({blockingGates.length} blocking)</span>
            )}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {gates.map((gate) => (
              <GateIndicator key={gate.name} gate={gate} />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function formatTimeAgo(seconds: number): string {
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

// Hook to derive funnel and gates from overview data
export function useWhyNoTrades(overviewData: any, executionData: any): {
  funnel: RejectFunnel;
  gates: GateStats[];
  decisionsPerSec: number;
  lastTradeAgo?: number;
} {
  return useMemo(() => {
    const orchestratorStats = overviewData?.fastScalper?.orchestratorStats || {};
    const metrics = overviewData?.fastScalper?.metrics || {};
    const execution = executionData || {};

    // Build funnel from orchestrator stats
    // Use actual fill count as authoritative source, then work backwards
    // Each earlier step must be >= later step
    const actualFillCount = execution.fillsCount || 0;
    const filled = Math.max(orchestratorStats.fills || 0, actualFillCount);
    const ordered = Math.max(orchestratorStats.orders_placed || execution.ordersPlaced || 0, filled);
    const approved = Math.max(orchestratorStats.signals_approved || orchestratorStats.completion_count || 0, ordered);
    const gated = Math.max(orchestratorStats.signals_gated || 0, approved);
    const evaluated = Math.max(orchestratorStats.signals_evaluated || orchestratorStats.execution_count || 0, gated);
    
    const funnel: RejectFunnel = {
      evaluated,
      gated,
      approved,
      ordered,
      filled,
    };

    // Build gates from metrics
    const gates: GateStats[] = [];
    
    // Spread gate
    if (metrics.current_spread !== undefined || metrics.spread_threshold !== undefined) {
      gates.push({
        name: "Spread",
        blocking: (metrics.current_spread || 0) > (metrics.spread_threshold || Infinity),
        current: metrics.current_spread || 0,
        threshold: metrics.spread_threshold || 0.1,
        unit: "%",
      });
    }

    // Depth gate
    if (metrics.current_depth !== undefined || metrics.depth_threshold !== undefined) {
      gates.push({
        name: "Depth",
        blocking: (metrics.current_depth || Infinity) < (metrics.depth_threshold || 0),
        current: metrics.current_depth || 0,
        threshold: metrics.depth_threshold || 1000,
        unit: "$",
      });
    }

    // Volatility gate
    if (metrics.current_volatility !== undefined || metrics.volatility_threshold !== undefined) {
      gates.push({
        name: "Volatility",
        blocking: (metrics.current_volatility || 0) > (metrics.volatility_threshold || Infinity),
        current: metrics.current_volatility || 0,
        threshold: metrics.volatility_threshold || 5,
        unit: "%",
      });
    }

    // Risk exposure gate
    if (metrics.exposure_utilization !== undefined) {
      gates.push({
        name: "Exposure",
        blocking: (metrics.exposure_utilization || 0) >= 100,
        current: metrics.exposure_utilization || 0,
        threshold: 100,
        unit: "%",
      });
    }

    // Position limit gate
    if (metrics.position_count !== undefined || metrics.max_positions !== undefined) {
      gates.push({
        name: "Positions",
        blocking: (metrics.position_count || 0) >= (metrics.max_positions || Infinity),
        current: metrics.position_count || 0,
        threshold: metrics.max_positions || 10,
        unit: "",
      });
    }

    // Cooldown gate
    if (metrics.cooldown_active !== undefined) {
      gates.push({
        name: "Cooldown",
        blocking: metrics.cooldown_active === true,
        current: metrics.cooldown_remaining || 0,
        threshold: metrics.cooldown_seconds || 60,
        unit: "s",
      });
    }

    // Default gates if none found
    if (gates.length === 0) {
      gates.push(
        { name: "Spread", blocking: false, current: 0.02, threshold: 0.1, unit: "%" },
        { name: "Depth", blocking: false, current: 5000, threshold: 1000, unit: "$" },
        { name: "Volatility", blocking: false, current: 1.5, threshold: 5, unit: "%" },
        { name: "Exposure", blocking: false, current: 30, threshold: 100, unit: "%" },
        { name: "Cooldown", blocking: false, current: 0, threshold: 60, unit: "s" },
      );
    }

    // Decisions per second
    const decisionsPerSec = metrics.decisions_per_sec || 
      orchestratorStats.decisions_per_sec || 
      (orchestratorStats.execution_count && orchestratorStats.uptime_seconds 
        ? orchestratorStats.execution_count / orchestratorStats.uptime_seconds 
        : 0);

    // Last trade timestamp
    const lastTradeTime = execution.lastTradeTime || orchestratorStats.last_fill_time;
    const lastTradeAgo = lastTradeTime 
      ? Math.floor((Date.now() - new Date(lastTradeTime).getTime()) / 1000)
      : undefined;

    return { funnel, gates, decisionsPerSec, lastTradeAgo };
  }, [overviewData, executionData]);
}



