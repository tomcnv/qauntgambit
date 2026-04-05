import { useMemo } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Clock,
  DollarSign,
  ListOrdered,
  Scale,
  Target,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { OpsMetrics } from "./types";

interface OpsKPICardsProps {
  metrics: OpsMetrics;
  onCardClick?: (cardType: string) => void;
  className?: string;
}

interface KPICardProps {
  title: string;
  value: string | number;
  subValue?: string;
  detail?: string;
  icon: React.ElementType;
  iconColor: string;
  iconBg: string;
  valueColor?: string;
  onClick?: () => void;
  badge?: { label: string; variant: "default" | "warning" | "destructive" };
  tooltip?: string;
}

function KPICard({
  title,
  value,
  subValue,
  detail,
  icon: Icon,
  iconColor,
  iconBg,
  valueColor = "text-foreground",
  onClick,
  badge,
  tooltip,
}: KPICardProps) {
  const content = (
    <Card 
      className={cn(
        "p-3 transition-all",
        onClick && "cursor-pointer hover:bg-muted/50 hover:border-primary/30"
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{title}</p>
            {badge && (
              <Badge 
                variant="outline" 
                className={cn(
                  "h-4 px-1 text-[9px]",
                  badge.variant === "warning" && "border-amber-500/50 text-amber-500 bg-amber-500/10",
                  badge.variant === "destructive" && "border-red-500/50 text-red-500 bg-red-500/10"
                )}
              >
                {badge.label}
              </Badge>
            )}
          </div>
          <p className={cn("text-lg font-bold font-mono mt-0.5", valueColor)}>
            {value}
          </p>
          {subValue && (
            <p className="text-[10px] text-muted-foreground font-mono">{subValue}</p>
          )}
          {detail && (
            <p className="text-[10px] text-muted-foreground mt-0.5 truncate">{detail}</p>
          )}
        </div>
        <div className={cn("h-8 w-8 rounded-lg flex items-center justify-center shrink-0", iconBg)}>
          <Icon className={cn("h-4 w-4", iconColor)} />
        </div>
      </div>
    </Card>
  );

  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{content}</TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs max-w-[200px]">
          {tooltip}
        </TooltipContent>
      </Tooltip>
    );
  }

  return content;
}

export function OpsKPICards({ metrics, onCardClick, className }: OpsKPICardsProps) {
  const exposureStatus = useMemo(() => {
    const pct = metrics.exposure.currentPct;
    if (pct > 80) return { variant: "destructive" as const, label: "HIGH" };
    if (pct > 60) return { variant: "warning" as const, label: "MED" };
    return null;
  }, [metrics.exposure.currentPct]);

  const pendingStatus = useMemo(() => {
    if (metrics.pendingOrders.oldestAgeSeconds > 60) return { variant: "warning" as const, label: "STALE" };
    if (metrics.pendingOrders.count > 10) return { variant: "warning" as const, label: "MANY" };
    return null;
  }, [metrics.pendingOrders]);

  const rejectStatus = useMemo(() => {
    // Only show warning if we have actual rejection data (topReason exists or topReasonCount > 0)
    const hasRejectionData = metrics.rejectRate.topReason || metrics.rejectRate.topReasonCount > 0;
    if (!hasRejectionData && metrics.rejectRate.last5m > 50) {
      // High rate but no actual rejection data - likely bad data, don't show warning
      return null;
    }
    if (metrics.rejectRate.last5m > 50) return { variant: "destructive" as const, label: "HIGH" };
    if (metrics.rejectRate.last5m > 20) return { variant: "warning" as const, label: "ELEVATED" };
    return null;
  }, [metrics.rejectRate]);

  const slippageStatus = useMemo(() => {
    if (metrics.slippage.p95 > 5) return { variant: "destructive" as const, label: "HIGH" };
    if (metrics.slippage.p95 > 2) return { variant: "warning" as const, label: "ELEVATED" };
    return null;
  }, [metrics.slippage.p95]);

  return (
    <div className={cn("grid gap-2 grid-cols-2 lg:grid-cols-5", className)}>
      {/* Exposure */}
      <KPICard
        title="Exposure"
        value={`$${Math.abs(metrics.exposure.net).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        subValue={`Gross: $${metrics.exposure.gross.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        detail={`${metrics.exposure.currentPct.toFixed(0)}% of ${metrics.exposure.maxAllowedPct}% max`}
        icon={Scale}
        iconColor="text-blue-500"
        iconBg="bg-blue-500/10"
        valueColor={metrics.exposure.net >= 0 ? "text-emerald-500" : "text-red-500"}
        onClick={() => onCardClick?.("exposure")}
        badge={exposureStatus || undefined}
        tooltip="Net and gross exposure. Click to filter positions."
      />

      {/* Pending Orders */}
      <KPICard
        title="Pending"
        value={metrics.pendingOrders.count}
        subValue={metrics.pendingOrders.count > 0 
          ? `Oldest: ${formatAge(metrics.pendingOrders.oldestAgeSeconds)}`
          : "No pending orders"
        }
        icon={ListOrdered}
        iconColor="text-violet-500"
        iconBg="bg-violet-500/10"
        onClick={() => onCardClick?.("pending")}
        badge={pendingStatus || undefined}
        tooltip="Pending orders count and age. Click to view orders tab."
      />

      {/* Reject Rate */}
      <KPICard
        title="Reject Rate"
        value={(() => {
          // Show "0%" if no rejection data but high rate (likely bad data)
          const hasRejectionData = metrics.rejectRate.topReason || metrics.rejectRate.topReasonCount > 0;
          if (!hasRejectionData && metrics.rejectRate.last5m > 50) return "0%";
          return `${metrics.rejectRate.last5m.toFixed(1)}%`;
        })()}
        subValue={(() => {
          const hasRejectionData = metrics.rejectRate.topReason || metrics.rejectRate.topReasonCount > 0;
          if (!hasRejectionData && metrics.rejectRate.last1h > 50) return "1h: 0%";
          return `1h: ${metrics.rejectRate.last1h.toFixed(1)}%`;
        })()}
        detail={metrics.rejectRate.topReason 
          ? `Top: ${metrics.rejectRate.topReason} (${metrics.rejectRate.topReasonCount})`
          : "No rejects"
        }
        icon={XCircle}
        iconColor="text-red-500"
        iconBg="bg-red-500/10"
        onClick={() => onCardClick?.("rejects")}
        badge={rejectStatus || undefined}
        tooltip="Signal rejection rate. Click to view rejects tab."
      />

      {/* Slippage */}
      <KPICard
        title="Slippage"
        value={`${metrics.slippage.p50.toFixed(2)}bp`}
        subValue={`p95: ${metrics.slippage.p95.toFixed(2)}bp`}
        detail={`Avg: ${metrics.slippage.avg.toFixed(2)}bp`}
        icon={Target}
        iconColor="text-amber-500"
        iconBg="bg-amber-500/10"
        onClick={() => onCardClick?.("slippage")}
        badge={slippageStatus || undefined}
        tooltip="Slippage percentiles (basis points). Click to view fills."
      />

      {/* Today's P&L */}
      <KPICard
        title="Today's P&L"
        value={`${metrics.pnl.net >= 0 ? "+" : ""}$${metrics.pnl.net.toFixed(2)}`}
        subValue={`Real: $${metrics.pnl.realized.toFixed(2)} · Unreal: $${metrics.pnl.unrealized.toFixed(2)}`}
        detail={`Fees: -$${Math.abs(metrics.pnl.fees).toFixed(2)} · ${metrics.pnl.tradesCount} trades today`}
        icon={metrics.pnl.net >= 0 ? TrendingUp : TrendingDown}
        iconColor={metrics.pnl.net >= 0 ? "text-emerald-500" : "text-red-500"}
        iconBg={metrics.pnl.net >= 0 ? "bg-emerald-500/10" : "bg-red-500/10"}
        valueColor={metrics.pnl.net >= 0 ? "text-emerald-500" : "text-red-500"}
        onClick={() => onCardClick?.("pnl")}
        tooltip="Today's P&L: realized + unrealized - fees (resets at midnight)"
      />
    </div>
  );
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

// Hook to derive ops metrics from various data sources
export function useOpsMetrics(
  overviewData: any,
  executionData: any,
  pendingOrders: any[],
  positions: any[],
  fills: any[],
): OpsMetrics {
  return useMemo(() => {
    const metrics = overviewData?.fastScalper?.metrics || {};
    const scopedMetrics = overviewData?.scopedMetrics || {};
    
    // Calculate exposure
    const totalLong = positions
      .filter(p => p.side === "LONG" || p.side === "BUY")
      .reduce((sum, p) => sum + Math.abs(p.quantity * (p.markPrice || p.entryPrice || 0)), 0);
    const totalShort = positions
      .filter(p => p.side === "SHORT" || p.side === "SELL")
      .reduce((sum, p) => sum + Math.abs(p.quantity * (p.markPrice || p.entryPrice || 0)), 0);
    const netExposure = totalLong - totalShort;
    const grossExposure = totalLong + totalShort;
    const maxExposure = scopedMetrics.max_exposure || metrics.max_exposure || 10000;
    
    // Calculate pending orders age (excluding SL/TP protection orders which are expected to be old)
    const now = Date.now();
    const protectionOrderTypes = ['STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT', 'stop_loss', 'take_profit', 'trailing_stop', 'stop_limit'];
    const tradingOrders = pendingOrders.filter(o => {
      const orderType = (o.type || o.order_type || '').toUpperCase();
      return !protectionOrderTypes.some(t => orderType.includes(t.toUpperCase()));
    });
    const ordersWithAge = tradingOrders.map(o => ({
      ...o,
      age: o.timestamp ? (now - new Date(o.timestamp).getTime()) / 1000 : 0
    }));
    const oldestAge = Math.max(0, ...ordersWithAge.map(o => o.age));

    // Calculate reject rate
    const recentFills = fills.filter(f => {
      const age = f.timestamp ? (now - new Date(f.timestamp).getTime()) / 1000 : 9999;
      return age < 3600; // Last hour
    });
    const fills5m = recentFills.filter(f => {
      const age = f.timestamp ? (now - new Date(f.timestamp).getTime()) / 1000 : 9999;
      return age < 300;
    });
    
    // From execution data
    const rejectRate5m = executionData?.rejectRate5m ?? (scopedMetrics.reject_rate_5m || 0);
    const rejectRate1h = executionData?.rejectRate1h ?? (scopedMetrics.reject_rate_1h || 0);
    const topRejectReason = executionData?.topRejectReason || scopedMetrics.top_reject_reason || "";
    const topRejectCount = executionData?.topRejectCount || scopedMetrics.top_reject_count || 0;

    // Calculate slippage percentiles
    const slippages = fills
      .map(f => f.slippage || 0)
      .filter(s => s !== 0)
      .sort((a, b) => a - b);
    
    const p50 = slippages.length > 0 ? slippages[Math.floor(slippages.length * 0.5)] : 0;
    const p95 = slippages.length > 0 ? slippages[Math.floor(slippages.length * 0.95)] : 0;
    const avgSlippage = slippages.length > 0 
      ? slippages.reduce((a, b) => a + b, 0) / slippages.length 
      : 0;

    // Calculate P&L from TODAY's fills only (consistent with overview page)
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayFills = fills.filter(f => new Date(f.timestamp || f.time) >= todayStart);
    
    const realizedPnl = todayFills.reduce((sum, f) => sum + (f.pnl || 0), 0);
    const unrealizedPnl = positions.reduce((sum, p) => sum + (p.unrealizedPnl || p.unrealized_pnl || 0), 0);
    const totalFees = todayFills.reduce((sum, f) => sum + (f.fee || 0), 0);
    const todayTradesCount = todayFills.length;

    return {
      exposure: {
        net: netExposure,
        gross: grossExposure,
        maxAllowedPct: 100,
        currentPct: maxExposure > 0 ? (grossExposure / maxExposure) * 100 : 0,
      },
      pendingOrders: {
        count: pendingOrders.length,
        oldestAgeSeconds: Math.floor(oldestAge),
      },
      rejectRate: {
        last5m: rejectRate5m,
        last1h: rejectRate1h,
        topReason: topRejectReason,
        topReasonCount: topRejectCount,
      },
      slippage: {
        p50,
        p95,
        avg: avgSlippage,
      },
      pnl: {
        realized: realizedPnl,
        unrealized: unrealizedPnl,
        fees: totalFees,
        net: realizedPnl + unrealizedPnl - totalFees,
        tradesCount: todayTradesCount, // Today's trade count
      },
    };
  }, [overviewData, executionData, pendingOrders, positions, fills]);
}



