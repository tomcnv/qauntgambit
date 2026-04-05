import { useMemo } from "react";
import {
  Shield,
  Wifi,
  WifiOff,
  Zap,
  Database,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { LiveStatus } from "./types";

interface StatusStripProps {
  status: LiveStatus;
  className?: string;
}

function StatusChip({
  label,
  status,
  icon: Icon,
  detail,
  tooltip,
}: {
  label: string;
  status: "ok" | "warning" | "error" | "neutral";
  icon: React.ElementType;
  detail?: string;
  tooltip?: string;
}) {
  const statusConfig = {
    ok: { bg: "bg-emerald-500/10", border: "border-emerald-500/30", text: "text-emerald-500", dot: "bg-emerald-500" },
    warning: { bg: "bg-amber-500/10", border: "border-amber-500/30", text: "text-amber-500", dot: "bg-amber-500" },
    error: { bg: "bg-red-500/10", border: "border-red-500/30", text: "text-red-500", dot: "bg-red-500" },
    neutral: { bg: "bg-muted", border: "border-border", text: "text-muted-foreground", dot: "bg-muted-foreground" },
  };

  const config = statusConfig[status];

  const chip = (
    <div className={cn(
      "flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-medium transition-colors",
      config.bg, config.border
    )}>
      <div className={cn("h-1.5 w-1.5 rounded-full animate-pulse", config.dot)} />
      <Icon className={cn("h-3 w-3", config.text)} />
      <span className="text-foreground">{label}</span>
      {detail && <span className={cn("font-mono", config.text)}>{detail}</span>}
    </div>
  );

  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{chip}</TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs max-w-[200px]">
          {tooltip}
        </TooltipContent>
      </Tooltip>
    );
  }

  return chip;
}

function WebSocketChips({ ws }: { ws: LiveStatus["websocket"] }) {
  return (
    <div className="flex items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border",
            ws.market 
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500" 
              : "bg-red-500/10 border-red-500/30 text-red-500"
          )}>
            {ws.market ? <Wifi className="h-2.5 w-2.5" /> : <WifiOff className="h-2.5 w-2.5" />}
            <span>MKT</span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs">
          Market data: {ws.market ? "Connected" : "Disconnected"}
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border",
            ws.orders 
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500" 
              : "bg-red-500/10 border-red-500/30 text-red-500"
          )}>
            {ws.orders ? <Wifi className="h-2.5 w-2.5" /> : <WifiOff className="h-2.5 w-2.5" />}
            <span>ORD</span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs">
          Orders feed: {ws.orders ? "Connected" : "Disconnected"}
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border",
            ws.positions 
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500" 
              : "bg-red-500/10 border-red-500/30 text-red-500"
          )}>
            {ws.positions ? <Wifi className="h-2.5 w-2.5" /> : <WifiOff className="h-2.5 w-2.5" />}
            <span>POS</span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs">
          Positions feed: {ws.positions ? "Connected" : "Disconnected"}
        </TooltipContent>
      </Tooltip>
    </div>
  );
}

export function StatusStrip({ status, className }: StatusStripProps) {
  const orderStatus = useMemo(() => {
    if (status.lastOrder.status === "none") return "neutral";
    if (status.lastOrder.status === "rejected") return "error";
    if (status.lastOrder.status === "canceled") return "warning";
    return "ok";
  }, [status.lastOrder.status]);

  const riskStatus = useMemo(() => {
    if (status.riskState.status === "paused") return "error";
    if (status.riskState.status === "throttled") return "warning";
    return "ok";
  }, [status.riskState.status]);

  const dataStatus = useMemo(() => {
    if (status.dataQuality.score < 50) return "error";
    if (status.dataQuality.score < 80) return "warning";
    return "ok";
  }, [status.dataQuality.score]);

  return (
    <div className={cn(
      "flex items-center gap-2 flex-wrap py-2 px-3 rounded-lg bg-card border",
      className
    )}>
      {/* WebSocket connections */}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-muted-foreground">WS:</span>
        <WebSocketChips ws={status.websocket} />
      </div>

      <div className="h-4 w-px bg-border mx-1" />

      {/* Last Order */}
      <StatusChip
        label="Order"
        status={orderStatus}
        icon={Zap}
        detail={status.lastOrder.status === "none" ? "—" : `${status.lastOrder.latencyMs || 0}ms`}
        tooltip={status.lastOrder.status === "none" 
          ? "No orders yet" 
          : `${status.lastOrder.status} (${status.lastOrder.latencyMs}ms)${status.lastOrder.symbol ? ` - ${status.lastOrder.symbol}` : ""}`
        }
      />

      <div className="h-4 w-px bg-border mx-1" />

      {/* Risk State */}
      <StatusChip
        label="Risk"
        status={riskStatus}
        icon={Shield}
        detail={status.riskState.status === "ok" ? "OK" : status.riskState.status}
        tooltip={
          status.riskState.status === "ok" 
            ? "All risk checks passing" 
            : `${status.riskState.status}${status.riskState.guardrail ? `: ${status.riskState.guardrail}` : ""}${status.riskState.pausedBy ? ` (by ${status.riskState.pausedBy})` : ""}`
        }
      />

      {/* Data Quality */}
      <StatusChip
        label="Data"
        status={dataStatus}
        icon={Database}
        detail={`${status.dataQuality.score}%`}
        tooltip={
          status.dataQuality.gapCount > 0 
            ? `${status.dataQuality.gapCount} gaps${status.dataQuality.staleSymbols.length > 0 ? `, stale: ${status.dataQuality.staleSymbols.slice(0, 3).join(", ")}` : ""}`
            : "All data feeds healthy"
        }
      />
    </div>
  );
}

// Hook to derive status from various data sources
export function useLiveStatus(
  wsConnected: boolean,
  overviewData: any,
  executionData: any,
  activeBotData: any,
): LiveStatus {
  return useMemo(() => {
    const metrics = overviewData?.fastScalper?.metrics || {};
    const orchestratorStats = overviewData?.fastScalper?.orchestratorStats || {};
    const lastTrade = executionData?.recentTrades?.[0];
    const lastOrder = executionData?.recentOrders?.[0];
    
    // Calculate heartbeat age
    const lastTickTime = metrics.last_tick_time || orchestratorStats.last_tick_time;
    const ageSeconds = lastTickTime 
      ? Math.floor((Date.now() - new Date(lastTickTime).getTime()) / 1000)
      : 999;

    return {
      heartbeat: {
        status: ageSeconds < 5 ? "ok" : ageSeconds < 30 ? "stale" : "dead",
        lastTickMs: lastTickTime ? new Date(lastTickTime).getTime() : 0,
        ageSeconds,
      },
      websocket: {
        market: wsConnected,
        orders: wsConnected, // Could be separate in future
        positions: wsConnected,
      },
      lastDecision: {
        status: orchestratorStats.last_decision_approved === false 
          ? "rejected" 
          : orchestratorStats.last_decision_approved === true 
            ? "approved" 
            : "none",
        reason: orchestratorStats.last_rejection_reason,
        timestamp: orchestratorStats.last_decision_time,
        symbol: orchestratorStats.last_decision_symbol,
      },
      lastOrder: {
        status: lastOrder?.status === "FILLED" 
          ? "filled" 
          : lastOrder?.status === "CANCELED" 
            ? "canceled"
            : lastOrder?.status === "REJECTED"
              ? "rejected"
              : lastOrder?.status === "NEW" || lastOrder?.status === "PENDING"
                ? "submitted"
                : "none",
        latencyMs: lastTrade?.latency || lastOrder?.latency || 0,
        timestamp: lastOrder?.timestamp,
        symbol: lastOrder?.symbol,
      },
      riskState: {
        status: activeBotData?.state === "paused" 
          ? "paused" 
          : metrics.throttled 
            ? "throttled" 
            : "ok",
        guardrail: metrics.throttle_reason || activeBotData?.pause_reason,
        pausedBy: activeBotData?.paused_by,
      },
      dataQuality: {
        score: metrics.data_quality_score ?? 100,
        gapCount: metrics.data_gaps ?? 0,
        staleSymbols: metrics.stale_symbols ?? [],
      },
    };
  }, [wsConnected, overviewData, executionData, activeBotData]);
}



