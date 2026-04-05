import { Progress } from "./ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "./ui/tooltip";
import { useWarmupStatus, useStrategyStatus } from "../lib/api/hooks";
import { CheckCircle, Circle, Loader2, AlertTriangle, Info } from "lucide-react";
import { cn } from "../lib/utils";

interface WarmupStatusProps {
  compact?: boolean;
  showStrategy?: boolean;
}

export function WarmupStatus({ compact = false, showStrategy = true }: WarmupStatusProps) {
  const { data: warmupData, isLoading: warmupLoading } = useWarmupStatus();
  const { data: strategyData, isLoading: strategyLoading } = useStrategyStatus();
  const reasonLabels: Record<string, string> = {
    warmup: "Collecting samples",
    quality_missing: "Quality score missing",
    quality_low: "Quality score below threshold",
    data_stale: "Market data stale",
    orderbook_unsynced: "Orderbook not synced",
    trade_unsynced: "Trades not synced",
    candle_unsynced: "Candles not synced",
  };
  const formatReasons = (reasons?: string[]) =>
    (reasons || []).map((reason) => reasonLabels[reason] || reason);

  if (warmupLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading warmup status...
      </div>
    );
  }

  if (!warmupData) {
    return null;
  }

  const { symbols, overall, botStatus } = warmupData;
  const isReady = overall.ready;
  const progress = Math.round(overall.progress);

  // Compact inline version for header
  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2">
              {isReady ? (
                <Badge variant="outline" className="bg-green-500/10 text-green-600 border-green-500/30">
                  <CheckCircle className="h-3 w-3 mr-1" />
                  Data Ready
                </Badge>
              ) : (
                <Badge variant="outline" className="bg-amber-500/10 text-amber-600 border-amber-500/30">
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  Warming {progress}%
                </Badge>
              )}
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs">
            <div className="space-y-2">
              <p className="font-medium">Data Warmup Status</p>
              {Object.entries(symbols).map(([symbol, status]) => (
                <div key={symbol} className="space-y-1 text-xs">
                  <div className="flex items-center justify-between gap-4">
                    <span>{symbol.replace('-SWAP', '')}</span>
                    <span className={status.overallReady ? 'text-green-500' : 'text-amber-500'}>
                      {Math.round(status.overallProgress)}%
                    </span>
                  </div>
                  {!status.overallReady && status.reasons?.length ? (
                    <div className="text-[10px] text-muted-foreground">
                      {formatReasons(status.reasons).join(", ")}
                    </div>
                  ) : null}
                </div>
              ))}
              {!isReady && (
                <p className="text-xs text-muted-foreground mt-2">
                  Trading signals will be generated once warmup completes
                </p>
              )}
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
          <CardTitle className="text-base font-medium">Data Warmup</CardTitle>
          {isReady ? (
            <Badge variant="outline" className="bg-green-500/10 text-green-600 border-green-500/30">
              <CheckCircle className="h-3 w-3 mr-1" />
              Ready
            </Badge>
          ) : (
            <Badge variant="outline" className="bg-amber-500/10 text-amber-600 border-amber-500/30">
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              {progress}%
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Overall Progress */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Overall Progress</span>
            <span className="font-medium">{progress}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>

        {/* Per-Symbol Status */}
        <div className="space-y-3">
          {Object.entries(symbols).map(([symbol, status]) => (
            <div key={symbol} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{symbol.replace('-SWAP', '')}</span>
                {status.overallReady ? (
                  <CheckCircle className="h-4 w-4 text-green-500" />
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {Math.round(status.overallProgress)}%
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="flex items-center gap-1.5">
                  {status.amt.ready ? (
                    <CheckCircle className="h-3 w-3 text-green-500" />
                  ) : (
                    <Circle className="h-3 w-3 text-muted-foreground" />
                  )}
                  <span className="text-muted-foreground">AMT</span>
                  <span>{Math.round(status.amt.progress)}%</span>
                </div>
                <div className="flex items-center gap-1.5">
                  {status.htf.ready ? (
                    <CheckCircle className="h-3 w-3 text-green-500" />
                  ) : (
                    <Circle className="h-3 w-3 text-muted-foreground" />
                  )}
                  <span className="text-muted-foreground">HTF</span>
                  <span>{Math.round(status.htf.progress)}%</span>
                </div>
              </div>
              {!status.overallReady && status.reasons?.length ? (
                <div className="text-[11px] text-muted-foreground">
                  <span className="font-medium text-foreground">Reasons:</span>{" "}
                  {formatReasons(status.reasons).join(", ")}
                </div>
              ) : null}
            </div>
          ))}
        </div>

        {/* Bot Status */}
        <div className="pt-2 border-t space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Heartbeat</span>
            {botStatus.heartbeatAlive ? (
              <span className="text-green-500 flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                Active
              </span>
            ) : (
              <span className="text-amber-500 flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                Inactive
              </span>
            )}
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Services</span>
            {botStatus.servicesHealthy ? (
              <span className="text-green-500">Healthy</span>
            ) : (
              <span className="text-amber-500">Degraded</span>
            )}
          </div>
        </div>

        {/* Strategy Status */}
        {showStrategy && strategyData && (
          <div className="pt-2 border-t space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{strategyData.strategy.name}</span>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <Info className="h-4 w-4 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent side="left" className="max-w-xs">
                    <p className="text-xs">{strategyData.strategy.description}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            
            {/* Required Conditions */}
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Required Conditions:</p>
              <div className="grid grid-cols-1 gap-1">
                {strategyData.conditions.required.slice(0, 3).map((condition, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs">
                    <Circle className="h-2 w-2 text-muted-foreground" />
                    <span>{condition.name}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Factor Weights */}
            <div className="flex gap-2 flex-wrap">
              {Object.entries(strategyData.conditions.weights).map(([factor, weight]) => (
                <Badge key={factor} variant="outline" className="text-xs">
                  {factor.toUpperCase()} {weight}%
                </Badge>
              ))}
            </div>

            {/* Signals Generated */}
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Signals Generated</span>
              <span className={cn(
                "font-medium",
                strategyData.signalsGenerated > 0 ? "text-green-500" : "text-muted-foreground"
              )}>
                {strategyData.signalsGenerated}
              </span>
            </div>
          </div>
        )}

        {/* Info Message */}
        {!isReady && (
          <p className="text-xs text-muted-foreground pt-2 border-t">
            Trading signals will be generated once all data is warmed up and market conditions meet strategy criteria.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default WarmupStatus;

