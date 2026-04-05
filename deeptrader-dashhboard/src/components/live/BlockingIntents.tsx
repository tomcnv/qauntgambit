import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, Lock, RefreshCcw, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { useScopeStore } from "../../store/scope-store";
import { apiFetch } from "../../lib/api/client";

interface BlockingIntent {
  symbol: string;
  side: string;
  size: number;
  status: string;
  lastError: string | null;
  stopLoss: number | null;
  takeProfit: number | null;
  clientOrderId: string | null;
  createdAt: string | null;
  submittedAt: string | null;
  ageSeconds: number | null;
}

interface BlockingIntentsResponse {
  blocking: BlockingIntent[];
  blockingCount: number;
  recentFailures: BlockingIntent[];
  recentFailureCount: number;
  stats: Record<string, number>;
  failureReasons: Record<string, number>;
  hasBlockingIntents: boolean;
}

interface BlockingIntentsProps {
  botId?: string;
  tenantId?: string;
  className?: string;
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "unknown";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

function IntentRow({ intent }: { intent: BlockingIntent }) {
  const isOld = (intent.ageSeconds ?? 0) > 300; // More than 5 minutes old
  
  return (
    <div className={cn(
      "flex items-center justify-between p-2 rounded-md",
      isOld ? "bg-red-500/10 border border-red-500/30" : "bg-amber-500/10 border border-amber-500/30"
    )}>
      <div className="flex items-center gap-2">
        {isOld ? (
          <XCircle className="h-4 w-4 text-red-500" />
        ) : (
          <Clock className="h-4 w-4 text-amber-500" />
        )}
        <span className="font-mono text-sm">{intent.symbol}</span>
        <Badge variant="outline" className={cn(
          "text-[10px] h-5",
          intent.side === "long" || intent.side === "buy" ? "text-green-500" : "text-red-500"
        )}>
          {intent.side}
        </Badge>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground font-mono">
          {intent.size.toFixed(4)}
        </span>
        <Badge variant="outline" className="text-[10px] h-5">
          {intent.status}
        </Badge>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="text-xs text-muted-foreground">
              {formatAge(intent.ageSeconds)} ago
            </span>
          </TooltipTrigger>
          <TooltipContent>
            {intent.lastError && <p className="text-red-400">Error: {intent.lastError}</p>}
            <p>Created: {intent.createdAt || "unknown"}</p>
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}

export function BlockingIntents({ className, botId: botIdOverride, tenantId: tenantIdOverride }: BlockingIntentsProps) {
  const { botId: scopedBotId, tenantId: scopedTenantId } = useScopeStore();
  const botId = botIdOverride || scopedBotId;
  const tenantId = tenantIdOverride || scopedTenantId;
  
  const { data, isLoading, refetch, isRefetching } = useQuery<BlockingIntentsResponse>({
    queryKey: ["blocking-intents", botId],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("botId", botId!);
      if (tenantId) {
        params.set("tenant_id", tenantId);
      }
      const response = await apiFetch(`/dashboard/blocking-intents?${params.toString()}`);
      return response.json();
    },
    enabled: !!botId,
    refetchInterval: 10000, // Refresh every 10s
  });

  if (!botId) return null;
  if (isLoading) return null;

  const hasBlocking = data?.hasBlockingIntents ?? false;
  const totalFailed = data?.stats?.failed ?? 0;
  const totalFilled = data?.stats?.filled ?? 0;
  
  // Top failure reasons
  const topReasons = Object.entries(data?.failureReasons ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);

  // Don't show if nothing interesting
  if (!hasBlocking && totalFailed === 0) return null;

  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-amber-500" />
            <CardTitle className="text-sm font-medium">Order Intents</CardTitle>
            {hasBlocking && (
              <Badge variant="destructive" className="text-[10px] h-5">
                {data?.blockingCount} Blocking
              </Badge>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => refetch()}
            disabled={isRefetching}
          >
            <RefreshCcw className={cn("h-3 w-3", isRefetching && "animate-spin")} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Blocking intents warning */}
        {hasBlocking && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-red-500">
              <AlertTriangle className="h-4 w-4" />
              <span className="text-sm font-medium">
                {data?.blockingCount} intent(s) blocking new trades
              </span>
            </div>
            <div className="space-y-1">
              {data?.blocking.map((intent, i) => (
                <IntentRow key={i} intent={intent} />
              ))}
            </div>
          </div>
        )}

        {/* Stats summary */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground">Filled:</span>
            <span className="font-mono text-green-500">{totalFilled}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-muted-foreground">Failed:</span>
            <span className="font-mono text-red-500">{totalFailed}</span>
          </div>
          {totalFilled + totalFailed > 0 && (
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground">Success Rate:</span>
              <span className="font-mono">
                {((totalFilled / (totalFilled + totalFailed)) * 100).toFixed(1)}%
              </span>
            </div>
          )}
        </div>

        {/* Top failure reasons */}
        {topReasons.length > 0 && (
          <div>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
              Top Failure Reasons
            </p>
            <div className="space-y-1">
              {topReasons.map(([reason, count]) => (
                <div key={reason} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground truncate max-w-[200px]" title={reason}>
                    {reason}
                  </span>
                  <span className="font-mono text-red-400">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent failures preview */}
        {!hasBlocking && (data?.recentFailures?.length ?? 0) > 0 && (
          <div>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">
              Recent Failures (last hour)
            </p>
            <div className="space-y-1">
              {data?.recentFailures.slice(0, 3).map((intent, i) => (
                <IntentRow key={i} intent={intent} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
