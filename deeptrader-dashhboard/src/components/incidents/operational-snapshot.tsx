import { useMemo } from "react";
import {
  Siren,
  AlertTriangle,
  XCircle,
  PauseCircle,
  Target,
  TrendingDown,
  Activity,
  Database,
} from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { cn } from "../../lib/utils";
import { useIncidentSnapshot, useDashboardRisk, useRiskLimits } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";

interface SnapshotTileProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  variant?: "default" | "critical" | "warning" | "success" | "info";
  onClick?: () => void;
  isActive?: boolean;
}

function SnapshotTile({
  title,
  value,
  subtitle,
  icon,
  variant = "default",
  onClick,
  isActive,
}: SnapshotTileProps) {
  // Cleaner styling - no confusing colored borders, just subtle backgrounds
  const variantStyles = {
    default: "border-border/50 hover:border-border",
    critical: "border-border/50 hover:border-red-500/50",
    warning: "border-border/50 hover:border-amber-500/50",
    success: "border-border/50 hover:border-emerald-500/50",
    info: "border-border/50 hover:border-blue-500/50",
  };

  const iconStyles = {
    default: "text-muted-foreground",
    critical: "text-red-500",
    warning: "text-amber-500",
    success: "text-emerald-500",
    info: "text-blue-500",
  };

  const valueStyles = {
    default: "text-foreground",
    critical: "text-red-400",
    warning: "text-amber-400",
    success: "text-emerald-400",
    info: "text-foreground",
  };

  return (
    <Card
      className={cn(
        "cursor-pointer transition-all duration-200 hover:bg-muted/30",
        variantStyles[variant]
      )}
      onClick={onClick}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            {title}
          </span>
          <div className={cn("h-5 w-5", iconStyles[variant])}>{icon}</div>
        </div>
        <p className={cn("text-2xl font-bold", valueStyles[variant])}>{value}</p>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );
}

interface OperationalSnapshotProps {
  onFilterChange?: (filter: { severity?: string; type?: string }) => void;
  activeFilter?: { severity?: string; type?: string };
}

export function OperationalSnapshot({
  onFilterChange,
  activeFilter,
}: OperationalSnapshotProps) {
  const { level, exchangeAccountId, botId } = useScopeStore();

  const { data: snapshotData, isLoading } = useIncidentSnapshot({
    exchangeAccountId: level === "exchange" ? exchangeAccountId ?? undefined : undefined,
    botId: level === "bot" ? botId ?? undefined : undefined,
  });

  const { data: riskData } = useDashboardRisk({
    exchangeAccountId: level === "exchange" ? exchangeAccountId ?? undefined : undefined,
  });

  const { data: limitsData } = useRiskLimits();

  const snapshot = snapshotData?.snapshot;
  const risk = riskData?.data ?? riskData;
  const policy = limitsData?.policy;
  const engineLimits = risk?.limits ?? {};
  const engineExposure = risk?.exposure ?? {};
  const accountEquity = risk?.account_equity ?? risk?.accountEquity ?? 0;

  // Calculate exposure vs limit
  const exposureData = useMemo(() => {
    const currentExposure = engineExposure?.total_usd ?? risk?.net_exposure ?? 0;
    const engineLimitUsd = engineLimits?.max_total_exposure_pct && accountEquity
      ? (engineLimits.max_total_exposure_pct / 100) * accountEquity
      : null;
    const exposureLimit = engineLimitUsd ?? policy?.max_position_size ?? policy?.max_exposure_usd ?? 50000;
    const percentage = exposureLimit > 0 ? Math.abs(currentExposure) / exposureLimit : 0;
    return {
      current: currentExposure,
      limit: exposureLimit,
      percentage: Math.min(percentage * 100, 100),
      isNearLimit: percentage >= 0.8,
    };
  }, [risk, policy, engineExposure, engineLimits, accountEquity]);

  // Calculate drawdown vs limit
  const drawdownData = useMemo(() => {
    const currentDrawdown = risk?.drawdown ?? risk?.peak_drawdown ?? 0;
    const drawdownLimit = policy?.max_drawdown_pct ?? 10;
    const percentage = drawdownLimit > 0 ? Math.abs(currentDrawdown) / drawdownLimit : 0;
    return {
      current: currentDrawdown,
      limit: drawdownLimit,
      percentage: Math.min(percentage * 100, 100),
      isNearLimit: percentage >= 0.8,
    };
  }, [risk, policy]);

  // Determine severity variant based on active incidents
  const activeVariant = useMemo(() => {
    if (!snapshot?.activeIncidents) return "success";
    if (snapshot.activeIncidents.critical > 0) return "critical";
    if (snapshot.activeIncidents.high > 0) return "warning";
    if (snapshot.activeIncidents.total > 0) return "info";
    return "success";
  }, [snapshot]);

  const tiles = [
    {
      id: "active",
      title: "Active Incidents",
      value: snapshot?.activeIncidents?.total ?? 0,
      subtitle: snapshot?.activeIncidents
        ? `${snapshot.activeIncidents.critical} critical, ${snapshot.activeIncidents.high} high`
        : "No active incidents",
      icon: <Siren className="h-5 w-5" />,
      variant: activeVariant as "default" | "critical" | "warning" | "success" | "info",
      filter: {},
    },
    {
      id: "pauses",
      title: "Auto-Pauses (24h)",
      value: snapshot?.autoPauses24h ?? 0,
      subtitle: "Trading interruptions",
      icon: <PauseCircle className="h-5 w-5" />,
      variant: (snapshot?.autoPauses24h ?? 0) > 0 ? "warning" : "default",
      filter: { causedPause: true },
    },
    {
      id: "breaches",
      title: "Breaches (24h)",
      value: snapshot?.breaches24h ?? 0,
      subtitle: "Limit violations",
      icon: <XCircle className="h-5 w-5" />,
      variant: (snapshot?.breaches24h ?? 0) > 0 ? "critical" : "default",
      filter: { type: "breach" },
    },
    {
      id: "exposure",
      title: "Net Exposure",
      value: `$${Math.abs(exposureData.current).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      subtitle: `of $${exposureData.limit.toLocaleString()} limit`,
      icon: <Target className="h-5 w-5" />,
      variant: exposureData.isNearLimit ? "warning" : "default",
      filter: {},
    },
    {
      id: "drawdown",
      title: "Drawdown",
      value: `${Math.abs(drawdownData.current).toFixed(2)}%`,
      subtitle: `of ${drawdownData.limit}% limit`,
      icon: <TrendingDown className="h-5 w-5" />,
      variant: drawdownData.isNearLimit ? "warning" : "default",
      filter: {},
    },
    {
      id: "impact",
      title: "PnL Impact (24h)",
      value: `$${Math.abs(snapshot?.pnlImpact24h ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      subtitle: (snapshot?.pnlImpact24h ?? 0) < 0 ? "Loss from incidents" : "No impact",
      icon: <Activity className="h-5 w-5" />,
      variant: (snapshot?.pnlImpact24h ?? 0) < 0 ? "critical" : "success",
      filter: {},
    },
  ];

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardContent className="p-4">
              <div className="h-4 w-20 bg-muted rounded mb-2" />
              <div className="h-8 w-16 bg-muted rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {tiles.map((tile) => (
        <SnapshotTile
          key={tile.id}
          title={tile.title}
          value={tile.value}
          subtitle={tile.subtitle}
          icon={tile.icon}
          variant={tile.variant as "default" | "critical" | "warning" | "success" | "info"}
          onClick={() => onFilterChange?.(tile.filter)}
          isActive={Boolean(
            (activeFilter?.severity && (tile.filter as any)?.severity === activeFilter.severity) ||
            (activeFilter?.type && (tile.filter as any)?.type === activeFilter.type)
          )}
        />
      ))}
    </div>
  );
}

export default OperationalSnapshot;
