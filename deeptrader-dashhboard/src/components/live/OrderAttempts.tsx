import { useState, useMemo, useCallback } from "react";
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
  Loader2,
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

// Order attempt from API
interface OrderAttempt {
  timestamp: number;
  symbol: string;
  side: string;
  size_usd: number;
  quantity: number;
  price: number;
  status: "filled" | "rejected" | "failed" | "timeout" | "pending";
  profile_id?: string;
  strategy_id?: string;
  signal_strength?: number;
  confidence?: number;
  order_id?: string;
  fill_price?: number;
  slippage_bps?: number;
  execution_time_ms?: number;
  error_code?: string;
  error_message?: string;
  rejection_stage?: string;
}

interface OrderAttemptStats {
  total_attempts: number;
  total_filled: number;
  total_rejected: number;
  total_failed: number;
  total_timeout: number;
  rejection_reasons: Record<string, number>;
  by_symbol: Record<string, { attempts: number; filled: number; rejected: number }>;
  by_profile: Record<string, { attempts: number; filled: number; rejected: number }>;
  success_rate?: number;
}

interface OrderAttemptsProps {
  attempts: OrderAttempt[];
  stats: OrderAttemptStats;
  isLoading?: boolean;
  onRefresh?: () => void;
  className?: string;
}

const STATUS_CONFIG = {
  filled: {
    icon: CheckCircle2,
    color: "text-green-500",
    bgColor: "bg-green-500/10",
    borderColor: "border-green-500/30",
    label: "Filled",
  },
  rejected: {
    icon: XCircle,
    color: "text-red-500",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
    label: "Rejected",
  },
  failed: {
    icon: AlertCircle,
    color: "text-amber-500",
    bgColor: "bg-amber-500/10",
    borderColor: "border-amber-500/30",
    label: "Failed",
  },
  timeout: {
    icon: Clock,
    color: "text-orange-500",
    bgColor: "bg-orange-500/10",
    borderColor: "border-orange-500/30",
    label: "Timeout",
  },
  pending: {
    icon: Loader2,
    color: "text-blue-500",
    bgColor: "bg-blue-500/10",
    borderColor: "border-blue-500/30",
    label: "Pending",
  },
};

function formatTimeAgo(timestamp: number): string {
  const now = Date.now() / 1000;
  const diff = now - timestamp;
  
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function AttemptRow({ attempt }: { attempt: OrderAttempt }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const config = STATUS_CONFIG[attempt.status] || STATUS_CONFIG.failed;
  const Icon = config.icon;
  
  const isFailed = attempt.status === "rejected" || attempt.status === "failed";
  
  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <CollapsibleTrigger asChild>
        <div
          className={cn(
            "flex items-center gap-2 p-2 rounded-md cursor-pointer transition-colors",
            "hover:bg-muted/50",
            config.bgColor,
            config.borderColor,
            "border"
          )}
        >
          <Icon className={cn("h-4 w-4 shrink-0", config.color, attempt.status === "pending" && "animate-spin")} />
          
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-[10px] font-mono">
                {attempt.symbol.replace("-SWAP", "")}
              </Badge>
              <Badge 
                variant="outline" 
                className={cn(
                  "text-[10px]",
                  attempt.side.toLowerCase() === "buy" 
                    ? "bg-green-500/10 text-green-500 border-green-500/30"
                    : "bg-red-500/10 text-red-500 border-red-500/30"
                )}
              >
                {attempt.side.toUpperCase()}
              </Badge>
              <span className="text-xs font-mono text-muted-foreground">
                ${attempt.size_usd?.toFixed(2) || "0.00"}
              </span>
              {attempt.profile_id && (
                <Badge variant="secondary" className="text-[9px] truncate max-w-[100px]">
                  {attempt.profile_id.replace(/_/g, " ")}
                </Badge>
              )}
            </div>
            
            {isFailed && attempt.error_message && (
              <p className="text-[10px] text-red-400 mt-0.5 truncate">
                {attempt.error_code}: {attempt.error_message.slice(0, 60)}...
              </p>
            )}
          </div>
          
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[10px] text-muted-foreground">
              {formatTimeAgo(attempt.timestamp)}
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
        <div className="mt-1 p-3 bg-muted/30 rounded-md text-xs space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Price:</span>
              <span className="font-mono">${attempt.price?.toLocaleString() || "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Quantity:</span>
              <span className="font-mono">{attempt.quantity?.toFixed(6) || "N/A"}</span>
            </div>
            {attempt.fill_price && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Fill Price:</span>
                <span className="font-mono">${attempt.fill_price?.toLocaleString()}</span>
              </div>
            )}
            {attempt.slippage_bps != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Slippage:</span>
                <span className={cn(
                  "font-mono",
                  attempt.slippage_bps > 5 ? "text-amber-500" : "text-green-500"
                )}>
                  {Number(attempt.slippage_bps).toFixed(2)} bps
                </span>
              </div>
            )}
            {attempt.execution_time_ms != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Exec Time:</span>
                <span className="font-mono">{Number(attempt.execution_time_ms).toFixed(0)}ms</span>
              </div>
            )}
            {attempt.confidence != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Confidence:</span>
                <span className="font-mono">{(Number(attempt.confidence) * 100).toFixed(1)}%</span>
              </div>
            )}
          </div>
          
          {isFailed && (
            <div className="pt-2 border-t border-border">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-3 w-3 text-red-500 mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium text-red-400">
                    {attempt.error_code || "Unknown Error"}
                  </p>
                  <p className="text-muted-foreground mt-0.5">
                    {attempt.error_message}
                  </p>
                  {attempt.rejection_stage && (
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Stage: {attempt.rejection_stage}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
          
          {attempt.order_id && (
            <div className="pt-2 border-t border-border">
              <span className="text-muted-foreground">Order ID:</span>{" "}
              <span className="font-mono text-[10px]">{attempt.order_id}</span>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function StatsBar({ stats }: { stats: OrderAttemptStats }) {
  const successRate = stats.total_attempts > 0
    ? ((stats.total_filled / stats.total_attempts) * 100).toFixed(1)
    : "0.0";
    
  const topRejectionReason = Object.entries(stats.rejection_reasons || {})
    .sort(([, a], [, b]) => b - a)[0];
  
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-muted/50">
            <span className="text-muted-foreground">Total:</span>
            <span className="font-mono font-medium">{stats.total_attempts}</span>
          </div>
        </TooltipTrigger>
        <TooltipContent>Total order attempts</TooltipContent>
      </Tooltip>
      
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-green-500/10">
            <CheckCircle2 className="h-3 w-3 text-green-500" />
            <span className="font-mono font-medium text-green-500">{stats.total_filled}</span>
          </div>
        </TooltipTrigger>
        <TooltipContent>Successfully filled orders</TooltipContent>
      </Tooltip>
      
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-red-500/10">
            <XCircle className="h-3 w-3 text-red-500" />
            <span className="font-mono font-medium text-red-500">
              {stats.total_rejected + stats.total_failed}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent>Rejected + failed orders</TooltipContent>
      </Tooltip>
      
      <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-muted/50">
        <span className="text-muted-foreground">Rate:</span>
        <span className={cn(
          "font-mono font-medium",
          parseFloat(successRate) > 50 ? "text-green-500" : "text-amber-500"
        )}>
          {successRate}%
        </span>
      </div>
      
      {topRejectionReason && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" className="text-[10px] text-red-400">
              Top: {topRejectionReason[0]} ({topRejectionReason[1]})
            </Badge>
          </TooltipTrigger>
          <TooltipContent>Most common rejection reason</TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

/**
 * Hook to fetch order attempts from the API
 */
export function useOrderAttempts(botId: string | undefined, options?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["order-attempts", botId],
    queryFn: async () => {
      if (!botId) return { attempts: [], stats: {} };
      const response = await api.get(`/dashboard/order-attempts?botId=${botId}&limit=100`);
      return response.data?.data || { attempts: [], stats: {} };
    },
    enabled: !!botId,
    refetchInterval: options?.refetchInterval ?? 5000, // Refresh every 5 seconds
    staleTime: 2000,
  });
}

export function OrderAttempts({
  attempts,
  stats,
  isLoading,
  onRefresh,
  className,
}: OrderAttemptsProps) {
  const [filter, setFilter] = useState<"all" | "failed">("all");
  
  const filteredAttempts = useMemo(() => {
    if (filter === "failed") {
      return attempts.filter(
        (a) => a.status === "rejected" || a.status === "failed" || a.status === "timeout"
      );
    }
    return attempts;
  }, [attempts, filter]);
  
  const hasFailures = attempts.some(
    (a) => a.status === "rejected" || a.status === "failed"
  );
  
  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            Order Attempts
            {hasFailures && (
              <Badge variant="destructive" className="text-[10px]">
                {stats.total_rejected + stats.total_failed} Failed
              </Badge>
            )}
          </CardTitle>
          <div className="flex items-center gap-1">
            <Button
              variant={filter === "all" ? "secondary" : "ghost"}
              size="sm"
              className="h-6 text-xs px-2"
              onClick={() => setFilter("all")}
            >
              All
            </Button>
            <Button
              variant={filter === "failed" ? "destructive" : "ghost"}
              size="sm"
              className="h-6 text-xs px-2"
              onClick={() => setFilter("failed")}
            >
              <Filter className="h-3 w-3 mr-1" />
              Failed
            </Button>
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
        {filteredAttempts.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">
            {filter === "failed" ? (
              <>
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-500/50" />
                <p>No failed orders</p>
              </>
            ) : (
              <>
                <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>No order attempts yet</p>
                <p className="text-xs mt-1">Waiting for trading signals...</p>
              </>
            )}
          </div>
        ) : (
          <ScrollArea className="h-[400px] pr-2">
            <div className="space-y-1">
              {filteredAttempts.map((attempt, idx) => (
                <AttemptRow key={`${attempt.timestamp}-${idx}`} attempt={attempt} />
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

export default OrderAttempts;

