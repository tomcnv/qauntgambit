/**
 * TradingStatusPanel - Compact Trading Activity Overview
 */

import { useMemo } from "react";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { TradingStatus, RejectionReason } from "./types";

interface TradingStatusPanelProps {
  status: TradingStatus;
  className?: string;
}

// Live indicator dot
function LiveDot({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
    </span>
  );
}

export function TradingStatusPanel({ status, className }: TradingStatusPanelProps) {
  const totalEvaluated = status.approvedCount + status.rejectedCount;
  
  const formatNumber = (n: number) => {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toString();
  };

  const passRateStatus = useMemo(() => {
    if (status.passRate > 1) return 'success';
    if (status.passRate > 0.1) return 'warning';
    return 'error';
  }, [status.passRate]);

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Trading Activity</CardTitle>
            <LiveDot active={status.decisionsPerSecond > 0} />
          </div>
          <div className="flex items-center gap-2">
            {status.blockedSymbolCount > 0 && (
              <Badge variant="outline" className="text-[10px]">
                {status.blockedSymbolCount}/{status.totalSymbolCount} blocked
              </Badge>
            )}
            <span className={cn(
              "text-xs",
              status.isTrading ? "text-emerald-500" : "text-muted-foreground"
            )}>
              {status.statusSummary}
            </span>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="pt-0">
        <div className="flex items-start gap-6">
          {/* Metrics Row */}
          <div className="flex gap-6 shrink-0">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="cursor-default">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Trades</p>
                  <p className={cn(
                    "text-xl font-bold tabular-nums",
                    status.tradesToday > 0 && "text-emerald-500"
                  )}>{status.tradesToday}</p>
                </div>
              </TooltipTrigger>
              <TooltipContent>Executed trades today</TooltipContent>
            </Tooltip>
            
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="cursor-default">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Dec/sec</p>
                  <p className="text-xl font-bold tabular-nums">
                    {status.decisionsPerSecond > 0 ? status.decisionsPerSecond.toFixed(0) : '—'}
                  </p>
                </div>
              </TooltipTrigger>
              <TooltipContent>Decision evaluations per second</TooltipContent>
            </Tooltip>
            
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="cursor-default">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Evaluated</p>
                  <p className="text-xl font-bold tabular-nums">
                    {totalEvaluated > 0 ? formatNumber(totalEvaluated) : '—'}
                  </p>
                </div>
              </TooltipTrigger>
              <TooltipContent>{totalEvaluated.toLocaleString()} total decisions</TooltipContent>
            </Tooltip>
            
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="cursor-default">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Pass Rate</p>
                  <p className={cn(
                    "text-xl font-bold tabular-nums",
                    passRateStatus === 'success' && "text-emerald-500",
                    passRateStatus === 'warning' && "text-amber-500",
                    passRateStatus === 'error' && "text-red-500",
                  )}>
                    {status.passRate < 1 ? `${status.passRate.toFixed(2)}%` : `${status.passRate.toFixed(1)}%`}
                  </p>
                </div>
              </TooltipTrigger>
              <TooltipContent>{status.approvedCount.toLocaleString()} approved / {status.rejectedCount.toLocaleString()} rejected</TooltipContent>
            </Tooltip>
          </div>
          
          {/* Divider */}
          <div className="w-px self-stretch bg-border" />
          
          {/* Rejections */}
          <div className="flex-1 min-w-0">
            {status.topRejectionReasons.length > 0 ? (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Top Rejections</p>
                  <p className="text-[10px] text-muted-foreground">Last 15m</p>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {status.topRejectionReasons.slice(0, 4).map((reason, idx) => {
                    const parts = reason.reason.split(':');
                    const category = parts[0]?.trim() || reason.reason;
                    return (
                      <Tooltip key={idx}>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-2 cursor-default">
                            <span className="text-xs text-muted-foreground truncate max-w-[140px]">{category}</span>
                            <span className={cn(
                              "text-xs font-bold tabular-nums",
                              reason.percentage > 50 && "text-red-500",
                              reason.percentage > 20 && reason.percentage <= 50 && "text-amber-500",
                              reason.percentage <= 20 && "text-muted-foreground",
                            )}>
                              {reason.percentage.toFixed(1)}%
                            </span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" className="max-w-[250px]">
                          <p className="font-medium">{reason.reason}</p>
                          <p className="text-xs text-muted-foreground">{reason.count.toLocaleString()} occurrences</p>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
                  {status.topRejectionReasons.length > 4 && (
                    <span className="text-[10px] text-muted-foreground">
                      +{status.topRejectionReasons.length - 4} more
                    </span>
                  )}
                </div>
              </div>
            ) : status.rejectedCount === 0 && status.approvedCount > 0 ? (
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                <span className="text-sm text-muted-foreground">All decisions passing</span>
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">Awaiting activity...</span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
