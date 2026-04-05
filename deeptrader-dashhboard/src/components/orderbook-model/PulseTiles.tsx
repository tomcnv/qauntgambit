/**
 * PulseTiles - 4 KPI cards showing real-time model health
 * 
 * 1. Rolling Accuracy (last 50) + sparkline
 * 2. Coverage (validated / made %)
 * 3. Freshness (p95 prediction age)
 * 4. Usage Rate (eligible % + blocked count)
 */

import { Card, CardContent } from "../ui/card";
import { cn } from "../../lib/utils";
import { TrendingUp, TrendingDown, Minus, Activity, Clock, Filter, Target } from "lucide-react";
import type { ModelPulse, AccuracyPoint } from "../../types/orderbookModel";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
} from "recharts";

interface PulseTilesProps {
  pulse: ModelPulse | undefined;
  accuracySeries: AccuracyPoint[] | undefined;
  isLoading?: boolean;
}

function MiniSparkline({ data }: { data: { value: number }[] }) {
  if (!data || data.length < 2) return null;
  
  return (
    <ResponsiveContainer width="100%" height={24}>
      <AreaChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="sparklineGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
            <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke="hsl(var(--primary))"
          strokeWidth={1.5}
          fill="url(#sparklineGradient)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function KPITile({
  title,
  value,
  unit,
  subtitle,
  trend,
  icon: Icon,
  sparklineData,
  className,
}: {
  title: string;
  value: string | number;
  unit?: string;
  subtitle?: string;
  trend?: "up" | "down" | "flat";
  icon: React.ElementType;
  sparklineData?: { value: number }[];
  className?: string;
}) {
  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-emerald-500" : trend === "down" ? "text-red-500" : "text-muted-foreground";

  return (
    <Card className={cn("relative overflow-hidden", className)}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Icon className="h-4 w-4" />
            <span className="text-xs font-medium">{title}</span>
          </div>
          {trend && <TrendIcon className={cn("h-3.5 w-3.5", trendColor)} />}
        </div>
        
        <div className="mt-2 flex items-baseline gap-1">
          <span className="text-2xl font-bold tracking-tight">{value}</span>
          {unit && <span className="text-sm text-muted-foreground">{unit}</span>}
        </div>
        
        {subtitle && (
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        )}
        
        {sparklineData && sparklineData.length > 0 && (
          <div className="mt-2">
            <MiniSparkline data={sparklineData} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function PulseTiles({ pulse, accuracySeries, isLoading }: PulseTilesProps) {
  // Convert accuracy series to sparkline data
  const accuracySparkline = accuracySeries?.map((p) => ({
    value: p.rolling_accuracy_pct,
  })) ?? [];

  // Determine trends based on data
  const getAccuracyTrend = () => {
    if (!accuracySeries || accuracySeries.length < 2) return "flat";
    const recent = accuracySeries.slice(-5);
    const first = recent[0]?.rolling_accuracy_pct ?? 50;
    const last = recent[recent.length - 1]?.rolling_accuracy_pct ?? 50;
    if (last > first + 2) return "up";
    if (last < first - 2) return "down";
    return "flat";
  };

  // Calculate coverage percentage
  const coverage = pulse && pulse.predictions_made > 0
    ? ((pulse.predictions_validated / pulse.predictions_made) * 100).toFixed(1)
    : "0.0";

  // Format freshness
  const freshness = pulse?.freshness?.p95_prediction_age_ms ?? 0;
  const freshnessStr = freshness < 1000 
    ? `${freshness.toFixed(0)}ms` 
    : `${(freshness / 1000).toFixed(1)}s`;

  // Calculate usage rate
  const usageRate = pulse?.usage?.eligible_rate_pct ?? 0;
  const blockedCount = pulse?.usage?.blocked_by_model_count ?? 0;

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardContent className="p-4">
              <div className="h-4 w-20 bg-muted rounded mb-3" />
              <div className="h-8 w-16 bg-muted rounded mb-2" />
              <div className="h-3 w-24 bg-muted rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {/* Rolling Accuracy */}
      <KPITile
        title="Rolling Accuracy"
        value={pulse?.rolling_accuracy_pct?.toFixed(1) ?? "—"}
        unit="%"
        subtitle={`Last 50 predictions • ${pulse?.predictions_validated ?? 0} validated`}
        trend={getAccuracyTrend()}
        icon={Target}
        sparklineData={accuracySparkline}
      />

      {/* Coverage */}
      <KPITile
        title="Coverage"
        value={coverage}
        unit="%"
        subtitle={`${pulse?.predictions_validated ?? 0} of ${pulse?.predictions_made ?? 0} validated`}
        trend={parseFloat(coverage) > 90 ? "up" : parseFloat(coverage) < 70 ? "down" : "flat"}
        icon={Activity}
      />

      {/* Freshness */}
      <KPITile
        title="Freshness (p95)"
        value={freshnessStr}
        subtitle={`${pulse?.pending_predictions ?? 0} pending • ${pulse?.validation_errors ?? 0} errors`}
        trend={freshness < 1000 ? "up" : freshness > 2000 ? "down" : "flat"}
        icon={Clock}
      />

      {/* Usage Rate */}
      <KPITile
        title="Usage Rate"
        value={usageRate.toFixed(0)}
        unit="%"
        subtitle={`${blockedCount} blocked by model`}
        trend={usageRate > 80 ? "up" : usageRate < 50 ? "down" : "flat"}
        icon={Filter}
      />
    </div>
  );
}

