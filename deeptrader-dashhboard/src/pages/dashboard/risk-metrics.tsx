import { useMemo, useState, useCallback } from "react";
import {
  BarChart3,
  RefreshCw,
  ShieldAlert,
  Shield,
  Zap,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Clock,
  Play,
  Settings2,
  ChevronRight,
  Bookmark,
  ExternalLink,
  Info,
  CheckCircle2,
  XCircle,
  Activity,
  Target,
  Layers,
} from "lucide-react";
import {
  LineChart as RechartsLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  ComposedChart,
  ReferenceLine,
  Cell,
  PieChart,
  Pie,
  Area,
  AreaChart,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { TooltipProvider, Tooltip, TooltipContent, TooltipTrigger } from "../../components/ui/tooltip";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Progress } from "../../components/ui/progress";
import { Separator } from "../../components/ui/separator";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../components/ui/collapsible";
import {
  useVaRCalculations,
  useScenarioResults,
  useComponentVaR,
  useScenarioFactors,
  useScenarioDetailWithFactors,
  useCorrelations,
  useRiskLimits,
  useTradeHistory,
  useDashboardRisk,
  useBotPositions,
  useRunHistoricalVaR,
  useRunMonteCarloVaR,
  useRunScenarioTest,
  useVaRSnapshot,
  useVaRDataStatus,
  useForceVaRSnapshot,
} from "../../lib/api/hooks";
import type {
  VaRCalculation,
  ScenarioTest,
  ComponentVaR,
  ScenarioFactorImpact,
  CorrelationRecord,
} from "../../lib/api/types";
import { RunBar } from "../../components/run-bar";
import { cn } from "../../lib/utils";
import { useScopeStore } from "../../store/scope-store";
import { format, subDays, startOfDay, parseISO } from "date-fns";
import toast from "react-hot-toast";

// ═══════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════

const formatCurrency = (v?: number | null) =>
  v === undefined || v === null ? "—" : `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const formatPercent = (v?: number | null, decimals = 1) =>
  v === undefined || v === null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}%`;

// Freshness badge colors and labels
const FRESHNESS_CONFIG: Record<string, { label: string; color: string; bgColor: string }> = {
  fresh: { label: "Fresh", color: "text-emerald-500", bgColor: "bg-emerald-500/10" },
  recent: { label: "Recent", color: "text-blue-500", bgColor: "bg-blue-500/10" },
  aging: { label: "Aging", color: "text-amber-500", bgColor: "bg-amber-500/10" },
  stale: { label: "Stale", color: "text-red-500", bgColor: "bg-red-500/10" },
};

function FreshnessBadge({ freshness, timestamp }: { freshness: string; timestamp?: string }) {
  const config = FRESHNESS_CONFIG[freshness] || FRESHNESS_CONFIG.stale;
  const timeAgo = timestamp ? formatTimeAgo(new Date(timestamp)) : "";
  
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className={cn("text-[10px] gap-1", config.color, config.bgColor)}>
          <span className="w-1.5 h-1.5 rounded-full bg-current" />
          {config.label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs">{timeAgo || "No timestamp"}</p>
      </TooltipContent>
    </Tooltip>
  );
}

function SourceBadge({ source }: { source: "auto" | "manual" }) {
  return (
    <Badge 
      variant="outline" 
      className={cn(
        "text-[10px]",
        source === "auto" ? "text-blue-500 bg-blue-500/10" : "text-purple-500 bg-purple-500/10"
      )}
    >
      {source === "auto" ? "Auto" : "Manual"}
    </Badge>
  );
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return format(date, "MMM d");
}

const formatNumber = (v?: number | null, decimals = 0) =>
  v === undefined || v === null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: decimals });

// Safe date formatter that handles invalid dates
const safeFormatDate = (dateInput: string | Date | null | undefined, formatStr: string): string | null => {
  if (!dateInput) return null;
  const date = typeof dateInput === "string" ? new Date(dateInput) : dateInput;
  if (isNaN(date.getTime())) return null;
  return format(date, formatStr);
};

// Mini sparkline component
function Sparkline({ data, color = "#ef4444", width = 80, height = 24 }: { data: number[]; color?: string; width?: number; height?: number }) {
  if (!data.length) return null;
  
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        points={points}
      />
      {/* Last point dot */}
      <circle
        cx={(data.length - 1) / (data.length - 1) * width}
        cy={height - ((data[data.length - 1] - min) / range) * height}
        r="2"
        fill={color}
      />
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════
// EMPTY STATE WITH DIAGNOSTICS
// ═══════════════════════════════════════════════════════════════

interface DiagnosticItem {
  label: string;
  status: "ok" | "warning" | "error" | "pending";
  detail?: string;
}

function EmptyStateWithDiagnostics({
  title,
  description,
  icon: Icon,
  diagnostics,
  ctaLabel,
  ctaAction,
  secondaryCta,
}: {
  title: string;
  description: string;
  icon: React.ElementType;
  diagnostics: DiagnosticItem[];
  ctaLabel?: string;
  ctaAction?: () => void;
  secondaryCta?: { label: string; action: () => void };
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
      <div className="h-16 w-16 rounded-full bg-muted/50 flex items-center justify-center mb-4">
        <Icon className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-semibold mb-1">{title}</h3>
      <p className="text-sm text-muted-foreground max-w-md mb-6">{description}</p>

      {/* Diagnostic Checklist */}
      <div className="w-full max-w-sm bg-muted/30 rounded-lg p-4 mb-6">
        <p className="text-xs font-medium text-muted-foreground mb-3 text-left">Diagnostic Checklist</p>
        <div className="space-y-2">
          {diagnostics.map((item, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              {item.status === "ok" ? (
                <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
              ) : item.status === "warning" ? (
                <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
              ) : item.status === "error" ? (
                <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
              ) : (
                <Clock className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              )}
              <span className="text-left flex-1">
                {item.label}
                {item.detail && (
                  <span className="text-muted-foreground ml-1">({item.detail})</span>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* CTAs */}
      <div className="flex items-center gap-3">
        {ctaLabel && ctaAction && (
          <Button onClick={ctaAction}>
            <Play className="h-4 w-4 mr-2" />
            {ctaLabel}
          </Button>
        )}
        {secondaryCta && (
          <Button variant="outline" onClick={secondaryCta.action}>
            {secondaryCta.label}
          </Button>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// KPI CARDS (TAB 1 - ROW 1)
// ═══════════════════════════════════════════════════════════════

interface KPICardProps {
  title: string;
  value: string;
  subtitle?: string;
  context?: string;
  icon: React.ReactNode;
  iconBg: string;
  sparklineData?: number[];
  trend?: "up" | "down" | "neutral";
  badge?: { text: string; variant: "default" | "destructive" | "secondary" | "outline" };
  onClick?: () => void;
}

function KPICard({ title, value, subtitle, context, icon, iconBg, sparklineData, trend, badge, onClick }: KPICardProps) {
  return (
    <Card className={cn("transition-all duration-200", onClick && "cursor-pointer hover:border-primary/50")}>
      <CardContent className="p-4" onClick={onClick}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <p className="text-xs text-muted-foreground font-medium">{title}</p>
              {badge && (
                <Badge variant={badge.variant} className="text-[9px] px-1.5 py-0">
                  {badge.text}
                </Badge>
              )}
            </div>
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold tracking-tight">{value}</p>
              {trend && (
                <span className={cn("text-xs", trend === "up" ? "text-green-500" : trend === "down" ? "text-red-500" : "text-muted-foreground")}>
                  {trend === "up" ? <TrendingUp className="h-3 w-3 inline" /> : trend === "down" ? <TrendingDown className="h-3 w-3 inline" /> : null}
                </span>
              )}
            </div>
            {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
            {context && <p className="text-[10px] text-muted-foreground/70 mt-1 truncate">{context}</p>}
            {sparklineData && sparklineData.length > 1 && (
              <div className="mt-2">
                <Sparkline data={sparklineData} color={iconBg.includes("red") ? "#ef4444" : iconBg.includes("amber") ? "#f59e0b" : iconBg.includes("green") ? "#22c55e" : "#3b82f6"} />
              </div>
            )}
          </div>
          <div className={cn("h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0", iconBg)}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function SummaryCards({
  calculations,
  scenarios,
  riskData,
  riskPolicy,
  equity,
  onViewScenario,
  snapshotData,
  dataStatus,
  onForceSnapshot,
  isForceSnapshotPending,
}: {
  calculations: VaRCalculation[];
  scenarios: ScenarioTest[];
  riskData: any;
  riskPolicy: any;
  equity: number;
  onViewScenario?: (id: string) => void;
  snapshotData?: any;
  dataStatus?: any;
  onForceSnapshot?: () => void;
  isForceSnapshotPending?: boolean;
}) {
  // Use auto snapshot data if available, otherwise fall back to all calculations
  const autoCalcs = snapshotData?.latestAuto || [];
  const freshness = snapshotData?.freshness || "stale";
  const hasSufficientData = dataStatus?.sufficient ?? (snapshotData?.dataStatus?.sufficient ?? false);
  const tradeDays = dataStatus?.tradeDays ?? snapshotData?.dataStatus?.tradeDays ?? 0;
  const requiredDays = dataStatus?.minRequired ?? snapshotData?.minDataDays ?? 30;
  
  // Get latest VaR by confidence level - prioritize auto calcs
  const var95 = useMemo(() => {
    // First try auto calcs
    const auto95 = autoCalcs.find((c: any) => c.confidence_level === 0.95 || c.confidence === 0.95);
    if (auto95) return { ...auto95, source: "auto" };
    // Fall back to all calculations
    const filtered = calculations.filter((c) => c.confidence_level === 0.95);
    const manual = filtered.sort((a, b) => new Date(b.calculated_at).getTime() - new Date(a.calculated_at).getTime())[0];
    return manual ? { ...manual, source: "manual" } : undefined;
  }, [calculations, autoCalcs]);

  const var99 = useMemo(() => {
    // First try auto calcs
    const auto99 = autoCalcs.find((c: any) => c.confidence_level === 0.99 || c.confidence === 0.99);
    if (auto99) return { ...auto99, source: "auto" };
    // Fall back to all calculations
    const filtered = calculations.filter((c) => c.confidence_level === 0.99);
    const manual = filtered.sort((a, b) => new Date(b.calculated_at).getTime() - new Date(a.calculated_at).getTime())[0];
    return manual ? { ...manual, source: "manual" } : undefined;
  }, [calculations, autoCalcs]);

  // Sparkline data - last 14 VaR calculations
  const var95Sparkline = useMemo(() => {
    return calculations
      .filter((c) => c.confidence_level === 0.95 && c.calculated_at && !isNaN(new Date(c.calculated_at).getTime()))
      .sort((a, b) => new Date(a.calculated_at).getTime() - new Date(b.calculated_at).getTime())
      .slice(-14)
      .map((c) => c.var_value);
  }, [calculations]);

  const var99Sparkline = useMemo(() => {
    return calculations
      .filter((c) => c.confidence_level === 0.99 && c.calculated_at && !isNaN(new Date(c.calculated_at).getTime()))
      .sort((a, b) => new Date(a.calculated_at).getTime() - new Date(b.calculated_at).getTime())
      .slice(-14)
      .map((c) => c.var_value);
  }, [calculations]);

  // Worst scenario in last 30 days
  const worstScenario = useMemo(() => {
    const thirtyDaysAgo = subDays(new Date(), 30);
    return scenarios
      .filter((s) => s.created_at && !isNaN(new Date(s.created_at).getTime()) && new Date(s.created_at) >= thirtyDaysAgo)
      .sort((a, b) => (a.portfolio_pnl ?? 0) - (b.portfolio_pnl ?? 0))[0];
  }, [scenarios]);

  // Risk headroom calculations - use riskPolicy for limits
  // Prefer USD limit if set (> 0), otherwise calculate from percentage
  const dailyLossUsdRaw = riskPolicy?.max_daily_loss_usd;
  const dailyLossPctRaw = riskPolicy?.max_daily_loss_pct;
  const dailyLossUsd = typeof dailyLossUsdRaw === "number" ? dailyLossUsdRaw : parseFloat(dailyLossUsdRaw || "0") || 0;
  const dailyLossPct = typeof dailyLossPctRaw === "number" ? dailyLossPctRaw : parseFloat(dailyLossPctRaw || "0") || 0;
  const hasUsdLimit = dailyLossUsd > 0;
  const dailyLossLimit = hasUsdLimit 
    ? dailyLossUsd 
    : (dailyLossPct > 0 && equity > 0 ? equity * (dailyLossPct / 100) : null);
  const dailyLossUsed = riskData?.daily_loss ?? 0;
  const dailyLossRemaining = dailyLossLimit !== null ? dailyLossLimit - Math.abs(dailyLossUsed) : null;
  

  // VaR breach count (compare realized PnL vs VaR threshold)
  const breachCount = useMemo(() => {
    // Simplified - would need trade history with daily P&L to calculate properly
    return 0;
  }, []);

  const expectedBreaches = calculations.length > 0 ? Math.round((1 - 0.95) * 30) : 0; // 5% chance over 30 days

  return (
    <div className="space-y-4">
      {/* Risk Snapshot Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">Risk Snapshot</h3>
          {(var95 || var99) && <FreshnessBadge freshness={freshness} timestamp={var95?.calculated_at || var95?.calculation_timestamp} />}
          {var95?.source && <SourceBadge source={var95.source as "auto" | "manual"} />}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {!hasSufficientData && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="text-amber-500 bg-amber-500/10 gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {tradeDays}/{requiredDays} days
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-xs">Need {requiredDays - tradeDays} more days of trading data for auto VaR</p>
              </TooltipContent>
            </Tooltip>
          )}
          {hasSufficientData && onForceSnapshot && (
            <Button 
              variant="ghost" 
              size="sm" 
              className="h-6 text-xs"
              onClick={onForceSnapshot}
              disabled={isForceSnapshotPending}
            >
              {isForceSnapshotPending ? (
                <><RefreshCw className="h-3 w-3 mr-1 animate-spin" /> Running...</>
              ) : (
                <><RefreshCw className="h-3 w-3 mr-1" /> Refresh</>
              )}
            </Button>
          )}
        </div>
      </div>
      
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {/* VaR 95% */}
      <KPICard
        title="VaR 95% (1d)"
        value={formatCurrency(var95?.var_value)}
        subtitle={equity > 0 && var95?.var_value ? `${((var95.var_value / equity) * 100).toFixed(2)}% of equity` : undefined}
        context={var95?.calculated_at && !isNaN(new Date(var95.calculated_at).getTime()) 
          ? `${var95.method?.replace("_", " ") || "historical"} · ${format(new Date(var95.calculated_at), "MMM d, HH:mm")}` 
          : var95?.calculation_timestamp && !isNaN(new Date(var95.calculation_timestamp).getTime())
          ? `${var95.method?.replace("_", " ") || "historical"} · ${format(new Date(var95.calculation_timestamp), "MMM d, HH:mm")}`
          : "No calculations yet"}
        icon={<ShieldAlert className="h-5 w-5 text-red-500" />}
        iconBg="bg-red-500/10"
        sparklineData={var95Sparkline}
      />

      {/* VaR 99% */}
      <KPICard
        title="VaR 99% (1d)"
        value={formatCurrency(var99?.var_value)}
        subtitle={equity > 0 && var99?.var_value ? `${((var99.var_value / equity) * 100).toFixed(2)}% of equity` : undefined}
        context={var99?.calculated_at && !isNaN(new Date(var99.calculated_at).getTime()) 
          ? `${var99.method?.replace("_", " ") || "historical"} · ${format(new Date(var99.calculated_at), "MMM d, HH:mm")}` 
          : var99?.calculation_timestamp && !isNaN(new Date(var99.calculation_timestamp).getTime())
          ? `${var99.method?.replace("_", " ") || "historical"} · ${format(new Date(var99.calculation_timestamp), "MMM d, HH:mm")}`
          : "No calculations yet"}
        icon={<Shield className="h-5 w-5 text-red-600" />}
        iconBg="bg-red-600/10"
        sparklineData={var99Sparkline}
      />

      {/* Expected Shortfall */}
      <KPICard
        title="Expected Shortfall (95%)"
        value={formatCurrency(var95?.expected_shortfall)}
        subtitle={equity > 0 && var95?.expected_shortfall ? `${((var95.expected_shortfall / equity) * 100).toFixed(2)}% of equity` : undefined}
        context="Avg loss beyond VaR"
        icon={<AlertTriangle className="h-5 w-5 text-amber-500" />}
        iconBg="bg-amber-500/10"
      />

      {/* Worst Stress Loss */}
      <KPICard
        title="Worst Stress Loss (30d)"
        value={formatCurrency(worstScenario?.portfolio_pnl)}
        subtitle={worstScenario?.scenario_name || "No scenarios run"}
        context={worstScenario?.created_at && !isNaN(new Date(worstScenario.created_at).getTime()) ? format(new Date(worstScenario.created_at), "MMM d, yyyy") : undefined}
        icon={<Zap className="h-5 w-5 text-orange-500" />}
        iconBg="bg-orange-500/10"
        onClick={worstScenario ? () => onViewScenario?.(worstScenario.id) : undefined}
        badge={worstScenario ? { text: "View", variant: "outline" } : undefined}
      />

      {/* Risk Headroom */}
      <KPICard
        title="Daily Loss Remaining"
        value={dailyLossRemaining !== null ? formatCurrency(dailyLossRemaining) : "—"}
        subtitle={dailyLossLimit !== null 
          ? `of ${formatCurrency(dailyLossLimit)} limit${hasUsdLimit ? "" : ` (${Number(dailyLossPct || 0).toFixed(2)}%)`}` 
          : "No limit set"}
        context={dailyLossRemaining !== null && dailyLossLimit ? `${((dailyLossRemaining / dailyLossLimit) * 100).toFixed(0)}% headroom` : undefined}
        icon={<Target className="h-5 w-5 text-blue-500" />}
        iconBg="bg-blue-500/10"
        trend={dailyLossRemaining !== null && dailyLossLimit && dailyLossRemaining / dailyLossLimit > 0.5 ? "up" : dailyLossRemaining !== null && dailyLossLimit && dailyLossRemaining / dailyLossLimit < 0.2 ? "down" : "neutral"}
      />

      {/* VaR Breach Count */}
      <KPICard
        title="VaR Breaches (30d)"
        value={`${breachCount}`}
        subtitle={`Expected: ${expectedBreaches}`}
        context={breachCount <= expectedBreaches ? "Within expected range" : "Exceeds expected"}
        icon={breachCount <= expectedBreaches ? <CheckCircle2 className="h-5 w-5 text-green-500" /> : <XCircle className="h-5 w-5 text-red-500" />}
        iconBg={breachCount <= expectedBreaches ? "bg-green-500/10" : "bg-red-500/10"}
        badge={breachCount > expectedBreaches ? { text: "Review", variant: "destructive" } : { text: "OK", variant: "secondary" }}
      />
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// VAR TREND VS REALIZED PNL CHART (TAB 1 - LEFT PANEL)
// ═══════════════════════════════════════════════════════════════

function VaRTrendChart({
  calculations,
  dailyPnL,
}: {
  calculations: VaRCalculation[];
  dailyPnL: Array<{ date: string; pnl: number }>;
}) {
  const chartData = useMemo(() => {
    // Get last 30 days
    const days = Array.from({ length: 30 }, (_, i) => {
      const date = subDays(new Date(), 29 - i);
      return format(date, "yyyy-MM-dd");
    });

    return days.map((date) => {
      const dayVaR = calculations
        .filter((c) => {
          if (!c.calculated_at) return false;
          const calcDate = new Date(c.calculated_at);
          if (isNaN(calcDate.getTime())) return false;
          return format(calcDate, "yyyy-MM-dd") === date && c.confidence_level === 0.95;
        })
        .sort((a, b) => new Date(b.calculated_at).getTime() - new Date(a.calculated_at).getTime())[0];

      const dayPnL = dailyPnL.find((d) => d.date === date);

      const isBreach = dayPnL && dayVaR && Math.abs(dayPnL.pnl) > dayVaR.var_value;

      return {
        date: format(new Date(date), "MMM d"),
        var95: dayVaR?.var_value || null,
        pnl: dayPnL?.pnl || 0,
        isBreach,
      };
    });
  }, [calculations, dailyPnL]);

  return (
    <Card className="col-span-1">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">VaR Trend vs Realized P&L</CardTitle>
            <CardDescription className="text-xs">Last 30 days · Red bars indicate VaR breaches</CardDescription>
          </div>
          <Badge variant="outline" className="text-[10px]">95% VaR</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `$${Math.abs(v / 1000).toFixed(0)}k`}
              />
              <RechartsTooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "11px",
                }}
                formatter={(value: number, name: string) => [
                  formatCurrency(value),
                  name === "var95" ? "VaR 95%" : "Realized P&L",
                ]}
              />
              <Bar dataKey="pnl" name="P&L">
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.isBreach ? "#dc2626" : entry.pnl >= 0 ? "#22c55e" : "#6b7280"}
                  />
                ))}
              </Bar>
              <Line
                type="stepAfter"
                dataKey="var95"
                stroke="#ef4444"
                strokeWidth={2}
                dot={false}
                name="VaR"
                strokeDasharray="4 4"
              />
              <ReferenceLine y={0} stroke="hsl(var(--border))" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════
// CURRENT EXPOSURE SNAPSHOT (TAB 1 - RIGHT PANEL)
// ═══════════════════════════════════════════════════════════════

function ExposureSnapshot({
  positions,
  riskData,
  equity,
}: {
  positions: any[];
  riskData: any;
  equity: number;
}) {
  const exposureBySymbol = useMemo(() => {
    const bySymbol: Record<string, { net: number; gross: number }> = {};
    positions.forEach((p) => {
      const notional = Math.abs((p.size || p.quantity || 0) * (p.current_price || p.entry_price || 0));
      const signed = (p.side === "LONG" || p.side === "BUY") ? notional : -notional;
      if (!bySymbol[p.symbol]) {
        bySymbol[p.symbol] = { net: 0, gross: 0 };
      }
      bySymbol[p.symbol].net += signed;
      bySymbol[p.symbol].gross += notional;
    });
    return Object.entries(bySymbol)
      .map(([symbol, { net, gross }]) => ({ symbol, net, gross }))
      .sort((a, b) => b.gross - a.gross)
      .slice(0, 5);
  }, [positions]);

  const totalGross = exposureBySymbol.reduce((sum, e) => sum + e.gross, 0);
  const totalNet = exposureBySymbol.reduce((sum, e) => sum + e.net, 0);

  const maxExposure = riskData?.policy?.max_total_exposure_pct ? equity * (riskData.policy.max_total_exposure_pct / 100) : equity;
  const exposurePct = maxExposure > 0 ? (totalGross / maxExposure) * 100 : 0;

  const leverage = equity > 0 ? totalGross / equity : 0;
  const maxLeverage = riskData?.policy?.max_leverage || 10;

  // Find biggest position
  const biggestPosition = positions.reduce((max, p) => {
    const notional = Math.abs((p.size || p.quantity || 0) * (p.current_price || p.entry_price || 0));
    return notional > (max?.notional || 0) ? { symbol: p.symbol, notional, side: p.side } : max;
  }, null as { symbol: string; notional: number; side: string } | null);

  return (
    <Card className="col-span-1">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Current Exposure Snapshot</CardTitle>
        <CardDescription className="text-xs">Live position risk distribution</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Top metrics */}
        <div className="grid grid-cols-2 gap-3">
          <div className="p-2 rounded-lg bg-muted/50">
            <p className="text-[10px] text-muted-foreground">Net Exposure</p>
            <p className={cn("text-lg font-bold", totalNet >= 0 ? "text-green-500" : "text-red-500")}>
              {formatCurrency(totalNet)}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-muted/50">
            <p className="text-[10px] text-muted-foreground">Gross Exposure</p>
            <p className="text-lg font-bold">{formatCurrency(totalGross)}</p>
          </div>
        </div>

        {/* Leverage / Margin Usage */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-muted-foreground">Leverage</span>
            <span className="font-medium">{leverage.toFixed(2)}x / {maxLeverage}x</span>
          </div>
          <Progress value={(leverage / maxLeverage) * 100} className="h-1.5" />
        </div>

        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-muted-foreground">Exposure Usage</span>
            <span className="font-medium">{exposurePct.toFixed(1)}%</span>
          </div>
          <Progress value={Math.min(exposurePct, 100)} className="h-1.5" />
        </div>

        {/* Exposure by symbol */}
        <div>
          <p className="text-xs font-medium mb-2">Top 5 by Gross Exposure</p>
          <div className="space-y-1.5">
            {exposureBySymbol.length === 0 ? (
              <p className="text-xs text-muted-foreground">No open positions</p>
            ) : (
              exposureBySymbol.map((e) => (
                <div key={e.symbol} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[9px] px-1.5">{e.symbol}</Badge>
                    <span className={cn("text-[10px]", e.net >= 0 ? "text-green-500" : "text-red-500")}>
                      {e.net >= 0 ? "+" : ""}{formatCurrency(e.net)}
                    </span>
                  </div>
                  <span className="font-mono text-muted-foreground">{formatCurrency(e.gross)}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Biggest position */}
        {biggestPosition && (
          <div className="pt-2 border-t">
            <p className="text-[10px] text-muted-foreground mb-1">Largest Position Contribution</p>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge variant="outline">{biggestPosition.symbol}</Badge>
                <Badge variant={biggestPosition.side === "LONG" || biggestPosition.side === "BUY" ? "default" : "destructive"} className="text-[9px]">
                  {biggestPosition.side}
                </Badge>
              </div>
              <span className="font-mono text-sm">{formatCurrency(biggestPosition.notional)}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════
// RISK EVENTS FEED (TAB 1 - ROW 3)
// ═══════════════════════════════════════════════════════════════

function RiskEventsFeed({ calculations, scenarios }: { calculations: VaRCalculation[]; scenarios: ScenarioTest[] }) {
  // Generate pseudo-events from calculations and scenarios
  const events = useMemo(() => {
    const eventList: Array<{
      id: string;
      type: "var_computed" | "scenario_run" | "var_change" | "breach";
      message: string;
      timestamp: Date;
      severity: "info" | "warning" | "critical";
    }> = [];

    // Add VaR computations
    calculations.slice(0, 5).forEach((c) => {
      if (!c.calculated_at) return;
      const timestamp = new Date(c.calculated_at);
      if (isNaN(timestamp.getTime())) return;
      eventList.push({
        id: `var-${c.id}`,
        type: "var_computed",
        message: `VaR ${(c.confidence_level * 100).toFixed(0)}% calculated: ${formatCurrency(c.var_value)}`,
        timestamp,
        severity: "info",
      });
    });

    // Add scenario runs
    scenarios.slice(0, 5).forEach((s) => {
      if (!s.created_at) return;
      const timestamp = new Date(s.created_at);
      if (isNaN(timestamp.getTime())) return;
      const isSerious = s.portfolio_pnl && Math.abs(s.portfolio_pnl) > 10000;
      eventList.push({
        id: `scenario-${s.id}`,
        type: "scenario_run",
        message: `Scenario "${s.scenario_name}": ${formatCurrency(s.portfolio_pnl)} impact`,
        timestamp,
        severity: isSerious ? "warning" : "info",
      });
    });

    // Sort by timestamp
    return eventList.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime()).slice(0, 8);
  }, [calculations, scenarios]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">What Changed?</CardTitle>
          <Badge variant="outline" className="text-[10px]">
            <Activity className="h-3 w-3 mr-1" />
            Recent Events
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-xs text-muted-foreground">No recent risk events</p>
        ) : (
          <div className="space-y-2">
            {events.map((event) => (
              <div
                key={event.id}
                className={cn(
                  "flex items-start gap-2 p-2 rounded-lg text-xs",
                  event.severity === "critical" && "bg-red-500/10",
                  event.severity === "warning" && "bg-amber-500/10",
                  event.severity === "info" && "bg-muted/50"
                )}
              >
                <div
                  className={cn(
                    "w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0",
                    event.severity === "critical" && "bg-red-500",
                    event.severity === "warning" && "bg-amber-500",
                    event.severity === "info" && "bg-blue-500"
                  )}
                />
                <div className="flex-1 min-w-0">
                  <p className="truncate">{event.message}</p>
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {format(event.timestamp, "MMM d, HH:mm")}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════
// VAR CONFIGURATION PANEL (TAB 2 - LEFT)
// ═══════════════════════════════════════════════════════════════

interface VaRConfig {
  method: "historical" | "monte_carlo";
  confidenceLevel: number;
  horizon: number;
  lookback: number;
  symbol?: string;
}

function VaRConfigPanel({
  config,
  onConfigChange,
  onRunVaR,
  isRunning,
  symbols,
}: {
  config: VaRConfig;
  onConfigChange: (config: VaRConfig) => void;
  onRunVaR: () => void;
  isRunning: boolean;
  symbols: string[];
}) {
  const presets = [
    { name: "Daily VaR (95%, 1d, 252d)", method: "historical" as const, confidenceLevel: 0.95, horizon: 1, lookback: 252 },
    { name: "Daily VaR (99%, 1d, 252d)", method: "historical" as const, confidenceLevel: 0.99, horizon: 1, lookback: 252 },
    { name: "Monte Carlo (95%, 1d)", method: "monte_carlo" as const, confidenceLevel: 0.95, horizon: 1, lookback: 90 },
    { name: "Short-term (95%, 5d, 90d)", method: "historical" as const, confidenceLevel: 0.95, horizon: 5, lookback: 90 },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          VaR Configuration
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Presets */}
        <div>
          <Label className="text-xs text-muted-foreground mb-2 block">Quick Presets</Label>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((preset, i) => (
              <Button
                key={i}
                variant="outline"
                size="sm"
                className="text-[10px] h-6 px-2"
                onClick={() =>
                  onConfigChange({
                    ...config,
                    method: preset.method,
                    confidenceLevel: preset.confidenceLevel,
                    horizon: preset.horizon,
                    lookback: preset.lookback,
                  })
                }
              >
                <Bookmark className="h-2.5 w-2.5 mr-1" />
                {preset.name.split(" (")[0]}
              </Button>
            ))}
          </div>
        </div>

        <Separator />

        {/* Method */}
        <div>
          <Label className="text-xs mb-1.5 block">Method</Label>
          <Select
            value={config.method}
            onValueChange={(v: "historical" | "monte_carlo") => onConfigChange({ ...config, method: v })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="historical">Historical Simulation</SelectItem>
              <SelectItem value="monte_carlo">Monte Carlo</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Confidence */}
        <div>
          <Label className="text-xs mb-1.5 block">Confidence Level</Label>
          <div className="flex gap-1.5">
            {[0.95, 0.99].map((level) => (
              <Button
                key={level}
                variant={config.confidenceLevel === level ? "default" : "outline"}
                size="sm"
                className="flex-1 h-7 text-xs"
                onClick={() => onConfigChange({ ...config, confidenceLevel: level })}
              >
                {(level * 100).toFixed(0)}%
              </Button>
            ))}
          </div>
        </div>

        {/* Horizon */}
        <div>
          <Label className="text-xs mb-1.5 block">Time Horizon</Label>
          <div className="flex gap-1.5">
            {[1, 2, 5, 10].map((days) => (
              <Button
                key={days}
                variant={config.horizon === days ? "default" : "outline"}
                size="sm"
                className="flex-1 h-7 text-xs"
                onClick={() => onConfigChange({ ...config, horizon: days })}
              >
                {days}d
              </Button>
            ))}
          </div>
        </div>

        {/* Lookback */}
        <div>
          <Label className="text-xs mb-1.5 block">Lookback Period</Label>
          <Select
            value={String(config.lookback)}
            onValueChange={(v) => onConfigChange({ ...config, lookback: parseInt(v) })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="30">30 days</SelectItem>
              <SelectItem value="90">90 days</SelectItem>
              <SelectItem value="180">180 days</SelectItem>
              <SelectItem value="252">252 days (1 year)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Symbol filter */}
        <div>
          <Label className="text-xs mb-1.5 block">Symbol Filter (optional)</Label>
          <Select
            value={config.symbol || "all"}
            onValueChange={(v) => onConfigChange({ ...config, symbol: v === "all" ? undefined : v })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="All symbols" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Symbols</SelectItem>
              {symbols.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Separator />

        {/* Run Button */}
        <Button className="w-full" onClick={onRunVaR} disabled={isRunning}>
          {isRunning ? (
            <>
              <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
              Computing...
            </>
          ) : (
            <>
              <Play className="h-4 w-4 mr-2" />
              Run VaR Calculation
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════
// VAR RESULTS PANEL (TAB 2 - RIGHT)
// ═══════════════════════════════════════════════════════════════

function VaRResultsPanel({
  calculations,
  riskPolicy,
  tradeCount,
  onRunVaR,
}: {
  calculations: VaRCalculation[];
  riskPolicy: any;
  tradeCount?: number;
  onRunVaR?: () => void;
}) {
  const latestCalc = calculations[0];

  // P&L distribution for histogram (mock - would need real distribution data)
  const distributionData = useMemo(() => {
    // Generate mock distribution based on VaR value
    if (!latestCalc) return [];
    const varVal = latestCalc.var_value;
    const bins = 20;
    return Array.from({ length: bins }, (_, i) => {
      const x = -varVal * 2 + (i / bins) * varVal * 4;
      const y = Math.exp(-Math.pow((x + varVal * 0.2) / (varVal * 0.5), 2) / 2);
      return { x: Math.round(x), y: Math.round(y * 100) };
    });
  }, [latestCalc]);

  // Would breach policy?
  const dailyLossLimitPct = riskPolicy?.max_daily_loss_pct || 5;
  const wouldBreach = latestCalc && (latestCalc.var_value / 100) > dailyLossLimitPct; // Simplified

  // Diagnostics for empty state
  const diagnostics: DiagnosticItem[] = [
    {
      label: "Trade history available",
      status: (tradeCount ?? 0) >= 30 ? "ok" : (tradeCount ?? 0) > 0 ? "warning" : "error",
      detail: tradeCount !== undefined ? `${tradeCount} trades` : "checking...",
    },
    {
      label: "Minimum observations (30+)",
      status: (tradeCount ?? 0) >= 30 ? "ok" : "error",
      detail: (tradeCount ?? 0) >= 30 ? "met" : `need ${30 - (tradeCount ?? 0)} more`,
    },
    {
      label: "Risk policy configured",
      status: riskPolicy ? "ok" : "warning",
      detail: riskPolicy ? "active" : "using defaults",
    },
  ];

  return (
    <div className="space-y-4">
      {/* Top Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Latest Calculation</CardTitle>
        </CardHeader>
        <CardContent>
          {!latestCalc ? (
            <EmptyStateWithDiagnostics
              title="No VaR Calculations Yet"
              description="Run your first VaR calculation to quantify potential losses at a given confidence level."
              icon={ShieldAlert}
              diagnostics={diagnostics}
              ctaLabel="Run VaR Calculation"
              ctaAction={onRunVaR}
            />
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-red-500/10 text-center">
                  <p className="text-[10px] text-muted-foreground">VaR</p>
                  <p className="text-xl font-bold text-red-500">{formatCurrency(latestCalc.var_value)}</p>
                </div>
                <div className="p-3 rounded-lg bg-amber-500/10 text-center">
                  <p className="text-[10px] text-muted-foreground">ES</p>
                  <p className="text-xl font-bold text-amber-500">{formatCurrency(latestCalc.expected_shortfall)}</p>
                </div>
                <div className="p-3 rounded-lg bg-muted/50 text-center">
                  <p className="text-[10px] text-muted-foreground">Sample Size</p>
                  <p className="text-xl font-bold">{latestCalc.metadata?.sample_size || "—"}</p>
                </div>
              </div>

              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Method</span>
                <span className="font-medium capitalize">{latestCalc.method?.replace("_", " ")}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Confidence</span>
                <span className="font-medium">{(latestCalc.confidence_level * 100).toFixed(0)}%</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Horizon</span>
                <span className="font-medium">{latestCalc.time_horizon_days}d</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Computed</span>
                <span className="font-medium">{safeFormatDate(latestCalc.calculated_at, "MMM d, HH:mm") || "—"}</span>
              </div>

              {/* Policy check */}
              <div className={cn("p-2 rounded-lg text-xs flex items-center gap-2", wouldBreach ? "bg-red-500/10" : "bg-green-500/10")}>
                {wouldBreach ? (
                  <>
                    <XCircle className="h-4 w-4 text-red-500" />
                    <span className="text-red-500">Would breach daily loss limit ({dailyLossLimitPct}%)</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                    <span className="text-green-500">Within policy limits</span>
                  </>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* P&L Distribution Histogram */}
      {distributionData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">P&L Distribution</CardTitle>
            <CardDescription className="text-xs">VaR threshold shown as vertical line</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[180px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={distributionData} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis
                    dataKey="x"
                    tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                  />
                  <YAxis hide />
                  <Bar dataKey="y" fill="hsl(var(--primary))" radius={[2, 2, 0, 0]} />
                  {latestCalc && (
                    <ReferenceLine
                      x={-Math.round(latestCalc.var_value)}
                      stroke="#ef4444"
                      strokeWidth={2}
                      strokeDasharray="4 4"
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* History Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Calculation History</CardTitle>
        </CardHeader>
        <CardContent>
          {calculations.length === 0 ? (
            <p className="text-xs text-muted-foreground">No calculations yet</p>
          ) : (
            <div className="overflow-x-auto max-h-[200px]">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b">
                    <th className="p-2 text-left font-medium">Time</th>
                    <th className="p-2 text-left font-medium">Method</th>
                    <th className="p-2 text-right font-medium">Conf</th>
                    <th className="p-2 text-right font-medium">VaR</th>
                    <th className="p-2 text-right font-medium">ES</th>
                  </tr>
                </thead>
                <tbody>
                  {calculations.slice(0, 10).map((calc) => (
                    <tr key={calc.id} className="border-b last:border-0">
                      <td className="p-2 text-muted-foreground">
                        {safeFormatDate(calc.calculated_at, "MMM d, HH:mm") || "—"}
                      </td>
                      <td className="p-2 capitalize">{calc.method?.replace("_", " ")}</td>
                      <td className="p-2 text-right">{(calc.confidence_level * 100).toFixed(0)}%</td>
                      <td className="p-2 text-right font-mono text-red-500">{formatCurrency(calc.var_value)}</td>
                      <td className="p-2 text-right font-mono text-amber-500">{formatCurrency(calc.expected_shortfall)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// SCENARIO BUILDER (TAB 3 - LEFT)
// ═══════════════════════════════════════════════════════════════

interface ScenarioConfig {
  name: string;
  type: "price" | "volatility" | "liquidity" | "correlation";
  shockMagnitude: number;
  shockUnits: "pct" | "bps" | "abs";
  applyTo: "all" | "selected";
  selectedSymbols: string[];
}

function ScenarioBuilder({
  config,
  onConfigChange,
  onRunScenario,
  isRunning,
  symbols,
}: {
  config: ScenarioConfig;
  onConfigChange: (config: ScenarioConfig) => void;
  onRunScenario: () => void;
  isRunning: boolean;
  symbols: string[];
}) {
  const presets = [
    { name: "-10% Market Crash", type: "price" as const, shockMagnitude: -0.10, shockUnits: "pct" as const },
    { name: "-20% Flash Crash", type: "price" as const, shockMagnitude: -0.20, shockUnits: "pct" as const },
    { name: "2x Volatility Spike", type: "volatility" as const, shockMagnitude: 2.0, shockUnits: "pct" as const },
    { name: "-5% Correction", type: "price" as const, shockMagnitude: -0.05, shockUnits: "pct" as const },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Zap className="h-4 w-4" />
          Scenario Builder
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Presets */}
        <div>
          <Label className="text-xs text-muted-foreground mb-2 block">Quick Presets</Label>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((preset, i) => (
              <Button
                key={i}
                variant="outline"
                size="sm"
                className="text-[10px] h-6 px-2"
                onClick={() =>
                  onConfigChange({
                    ...config,
                    name: preset.name,
                    type: preset.type,
                    shockMagnitude: preset.shockMagnitude,
                    shockUnits: preset.shockUnits,
                  })
                }
              >
                {preset.name}
              </Button>
            ))}
          </div>
        </div>

        <Separator />

        {/* Scenario Name */}
        <div>
          <Label className="text-xs mb-1.5 block">Scenario Name</Label>
          <Input
            className="h-8 text-xs"
            value={config.name}
            onChange={(e) => onConfigChange({ ...config, name: e.target.value })}
            placeholder="Enter scenario name"
          />
        </div>

        {/* Shock Type */}
        <div>
          <Label className="text-xs mb-1.5 block">Shock Type</Label>
          <Select
            value={config.type}
            onValueChange={(v: "price" | "volatility" | "liquidity" | "correlation") =>
              onConfigChange({ ...config, type: v })
            }
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="price">Price Shock</SelectItem>
              <SelectItem value="volatility">Volatility Shock</SelectItem>
              <SelectItem value="liquidity">Liquidity Shock</SelectItem>
              <SelectItem value="correlation">Correlation Breakdown</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Shock Magnitude */}
        <div>
          <Label className="text-xs mb-1.5 block">Shock Magnitude</Label>
          <div className="flex gap-2">
            <Input
              type="number"
              step="0.01"
              className="h-8 text-xs flex-1"
              value={config.shockMagnitude * 100}
              onChange={(e) =>
                onConfigChange({ ...config, shockMagnitude: parseFloat(e.target.value) / 100 || 0 })
              }
            />
            <Select
              value={config.shockUnits}
              onValueChange={(v: "pct" | "bps" | "abs") => onConfigChange({ ...config, shockUnits: v })}
            >
              <SelectTrigger className="h-8 text-xs w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="pct">%</SelectItem>
                <SelectItem value="bps">bps</SelectItem>
                <SelectItem value="abs">$</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Apply To */}
        <div>
          <Label className="text-xs mb-1.5 block">Apply To</Label>
          <Select
            value={config.applyTo}
            onValueChange={(v: "all" | "selected") => onConfigChange({ ...config, applyTo: v })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Positions</SelectItem>
              <SelectItem value="selected">Selected Symbols</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {config.applyTo === "selected" && (
          <div>
            <Label className="text-xs mb-1.5 block">Select Symbols</Label>
            <div className="flex flex-wrap gap-1.5 p-2 rounded-lg border max-h-24 overflow-auto">
              {symbols.length === 0 ? (
                <p className="text-xs text-muted-foreground">No symbols available</p>
              ) : (
                symbols.map((s) => (
                  <Button
                    key={s}
                    variant={config.selectedSymbols.includes(s) ? "default" : "outline"}
                    size="sm"
                    className="text-[10px] h-5 px-2"
                    onClick={() => {
                      const selected = config.selectedSymbols.includes(s)
                        ? config.selectedSymbols.filter((x) => x !== s)
                        : [...config.selectedSymbols, s];
                      onConfigChange({ ...config, selectedSymbols: selected });
                    }}
                  >
                    {s}
                  </Button>
                ))
              )}
            </div>
          </div>
        )}

        <Separator />

        {/* Run Button */}
        <Button className="w-full" onClick={onRunScenario} disabled={isRunning || !config.name}>
          {isRunning ? (
            <>
              <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
              Running...
            </>
          ) : (
            <>
              <Play className="h-4 w-4 mr-2" />
              Run Scenario
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════
// SCENARIO RESULTS (TAB 3 - RIGHT)
// ═══════════════════════════════════════════════════════════════

function ScenarioResultsPanel({
  scenarios,
  selectedScenario,
  factors,
  positions,
  currentPositions,
  onSelectScenario,
}: {
  scenarios: ScenarioTest[];
  selectedScenario: ScenarioTest | null;
  factors: ScenarioFactorImpact[];
  positions: any[];
  currentPositions: any[];
  onSelectScenario: (id: string) => void;
}) {
  // Waterfall chart data from factors
  const waterfallData = useMemo(() => {
    if (!factors.length) return [];
    return factors.map((f) => ({
      name: f.name,
      impact: f.impact,
      cumulative: f.cumulative,
      fill: f.impact < 0 ? "#ef4444" : "#22c55e",
    }));
  }, [factors]);

  return (
    <div className="space-y-4">
      {/* Top Summary */}
      {selectedScenario && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">{selectedScenario.scenario_name}</CardTitle>
              <Badge variant="outline" className="text-[10px]">
                {safeFormatDate(selectedScenario.created_at, "MMM d, HH:mm") || "—"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div className="p-3 rounded-lg bg-red-500/10 text-center">
                <p className="text-[10px] text-muted-foreground">Portfolio P&L</p>
                <p className="text-xl font-bold text-red-500">{formatCurrency(selectedScenario.portfolio_pnl)}</p>
              </div>
              <div className="p-3 rounded-lg bg-amber-500/10 text-center">
                <p className="text-[10px] text-muted-foreground">Max Drawdown</p>
                <p className="text-xl font-bold text-amber-500">{formatCurrency(selectedScenario.max_drawdown)}</p>
              </div>
              <div className="p-3 rounded-lg bg-muted/50 text-center">
                <p className="text-[10px] text-muted-foreground">Positions</p>
                <p className="text-xl font-bold">{selectedScenario.affected_positions}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Waterfall Chart */}
      {waterfallData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Impact Breakdown</CardTitle>
            <CardDescription className="text-xs">Contribution by factor</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={waterfallData} layout="vertical" margin={{ top: 5, right: 20, left: 60, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => formatCurrency(v)}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                    tickLine={false}
                    axisLine={false}
                    width={55}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "8px",
                      fontSize: "11px",
                    }}
                    formatter={(value: number) => [formatCurrency(value), "Impact"]}
                  />
                  <Bar dataKey="impact" radius={[0, 4, 4, 0]}>
                    {waterfallData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Position Impacts Table */}
      {positions.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Position Impacts</CardTitle>
            <CardDescription className="text-xs">Top 10 affected positions</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto max-h-[180px]">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b">
                    <th className="p-2 text-left font-medium">Symbol</th>
                    <th className="p-2 text-left font-medium">Side</th>
                    <th className="p-2 text-right font-medium">Size</th>
                    <th className="p-2 text-right font-medium">P&L Impact</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.slice(0, 10).map((p, idx) => (
                    <tr key={`${p.symbol}-${idx}`} className="border-b last:border-0">
                      <td className="p-2">
                        <Badge variant="outline" className="text-[9px]">{p.symbol}</Badge>
                      </td>
                      <td className="p-2">{p.side || "—"}</td>
                      <td className="p-2 text-right font-mono">{formatNumber(p.size, 4)}</td>
                      <td className="p-2 text-right font-mono text-red-500">{formatCurrency(p.pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Scenario History */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Scenario History</CardTitle>
        </CardHeader>
        <CardContent>
          {scenarios.length === 0 ? (
            <EmptyStateWithDiagnostics
              title="No Scenarios Run Yet"
              description="Run stress tests to understand how your portfolio would perform under adverse market conditions."
              icon={Zap}
              diagnostics={[
                {
                  label: "Open positions",
                  status: currentPositions.length > 0 ? "ok" : "warning",
                  detail: currentPositions.length > 0 ? `${currentPositions.length} positions` : "none",
                },
                {
                  label: "Scenario configuration",
                  status: "pending",
                  detail: "ready to configure",
                },
              ]}
              ctaLabel="Configure Scenario"
            />
          ) : (
            <div className="space-y-2 max-h-[200px] overflow-auto">
              {scenarios.map((s) => (
                <div
                  key={s.id}
                  className={cn(
                    "p-2 rounded-lg border cursor-pointer transition-colors",
                    selectedScenario?.id === s.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                  )}
                  onClick={() => onSelectScenario(s.id)}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-medium">{s.scenario_name}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {safeFormatDate(s.created_at, "MMM d, HH:mm") || "—"} · {s.affected_positions} positions
                      </p>
                    </div>
                    <div className="text-right">
                      <p className={cn("text-sm font-mono", (s.portfolio_pnl ?? 0) < 0 ? "text-red-500" : "text-green-500")}>
                        {formatCurrency(s.portfolio_pnl)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════

export default function RiskMetricsPage() {
  const { selectedExchangeAccountId, selectedBotId } = useScopeStore();
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);

  // VaR configuration state
  const [varConfig, setVarConfig] = useState<VaRConfig>({
    method: "historical",
    confidenceLevel: 0.95,
    horizon: 1,
    lookback: 252,
  });

  // Scenario configuration state
  const [scenarioConfig, setScenarioConfig] = useState<ScenarioConfig>({
    name: "",
    type: "price",
    shockMagnitude: -0.10,
    shockUnits: "pct",
    applyTo: "all",
    selectedSymbols: [],
  });

  // Data hooks
  const { data: varData, isLoading: loadingVar } = useVaRCalculations({ limit: 200 });
  const { data: scenariosData, isLoading: loadingScenarios } = useScenarioResults({ limit: 50 });
  const { data: componentVarData } = useComponentVaR();
  const { data: selectedScenarioDetail, isLoading: loadingScenarioDetail } = useScenarioDetailWithFactors(selectedScenarioId || undefined);
  const { data: riskLimitsData } = useRiskLimits();
  const { data: tradeHistoryData } = useTradeHistory({ limit: 500, exchangeAccountId: selectedExchangeAccountId || undefined, botId: selectedBotId || undefined });
  const { data: riskData } = useDashboardRisk({ exchangeAccountId: selectedExchangeAccountId || undefined, botId: selectedBotId || undefined });
  const { data: positionsData } = useBotPositions({
    exchangeAccountId: selectedExchangeAccountId || undefined,
    botId: selectedBotId || undefined,
  });
  
  // VaR Snapshot hooks (auto-generated snapshots)
  const { data: snapshotData, isLoading: loadingSnapshot } = useVaRSnapshot();
  const { data: dataStatusData } = useVaRDataStatus({ exchangeAccountId: selectedExchangeAccountId || undefined, botId: selectedBotId || undefined });

  // Mutations
  const runHistoricalVaR = useRunHistoricalVaR();
  const runMonteCarloVaR = useRunMonteCarloVaR();
  const runScenarioTest = useRunScenarioTest();
  const forceSnapshot = useForceVaRSnapshot();

  const calculations = varData?.data || [];
  const scenarios = scenariosData?.data || [];
  const positions = positionsData?.data || [];
  const factors = selectedScenarioDetail?.factors || [];
  const scenarioPositions = selectedScenarioDetail?.positions || [];

  // Equity from risk data or positions
  const equity = riskData?.account_balance || 100000;

  // Daily P&L from trade history
  const dailyPnL = useMemo(() => {
    if (!tradeHistoryData?.trades) return [];
    const byDay: Record<string, number> = {};
    tradeHistoryData.trades.forEach((t: any) => {
      const dateStr = t.exit_time || t.created_at;
      if (!dateStr) return; // Skip if no date
      const dateObj = new Date(dateStr);
      if (isNaN(dateObj.getTime())) return; // Skip if invalid date
      const date = format(dateObj, "yyyy-MM-dd");
      byDay[date] = (byDay[date] || 0) + (t.pnl || 0);
    });
    return Object.entries(byDay).map(([date, pnl]) => ({ date, pnl }));
  }, [tradeHistoryData]);

  // Get unique symbols from positions and trades
  const availableSymbols = useMemo(() => {
    const symbolSet = new Set<string>();
    positions.forEach((p) => symbolSet.add(p.symbol));
    tradeHistoryData?.trades?.forEach((t: any) => symbolSet.add(t.symbol));
    return Array.from(symbolSet).sort();
  }, [positions, tradeHistoryData]);

  // Selected scenario
  const selectedScenario = useMemo(() => {
    return scenarios.find((s) => s.id === selectedScenarioId) || null;
  }, [scenarios, selectedScenarioId]);

  // Handlers
  const handleRunVaR = useCallback(async () => {
    try {
      const params = {
        confidenceLevel: varConfig.confidenceLevel,
        timeHorizonDays: varConfig.horizon,
        lookbackDays: varConfig.lookback,
        symbol: varConfig.symbol,
      };

      if (varConfig.method === "historical") {
        await runHistoricalVaR.mutateAsync(params);
      } else {
        await runMonteCarloVaR.mutateAsync({ ...params, numSimulations: 10000 });
      }
      toast.success("VaR calculation completed");
    } catch (error: any) {
      toast.error(error.message || "Failed to run VaR calculation");
    }
  }, [varConfig, runHistoricalVaR, runMonteCarloVaR]);

  const handleRunScenario = useCallback(async () => {
    try {
      await runScenarioTest.mutateAsync({
        scenarioName: scenarioConfig.name,
        scenarioType: scenarioConfig.type === "price" ? "price_shock" : 
                      scenarioConfig.type === "volatility" ? "volatility_shock" :
                      scenarioConfig.type === "liquidity" ? "liquidity_shock" : "correlation_breakdown",
        shockParams: {
          shockValue: scenarioConfig.shockMagnitude,
          shockUnits: scenarioConfig.shockUnits,
          symbols: scenarioConfig.applyTo === "selected" ? scenarioConfig.selectedSymbols : undefined,
        },
      });
      toast.success("Scenario test completed");
    } catch (error: any) {
      toast.error(error.message || "Failed to run scenario test");
    }
  }, [scenarioConfig, runScenarioTest]);

  const handleViewScenario = useCallback((id: string) => {
    setSelectedScenarioId(id);
    setActiveTab("stress");
  }, []);

  return (
    <TooltipProvider>
      <RunBar variant="full" />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">VaR & Stress Tests</h1>
            <p className="text-sm text-muted-foreground">Value at Risk, Expected Shortfall, and scenario analysis</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              <Clock className="h-3 w-3 mr-1" />
              {calculations.length > 0
                ? `Last: ${safeFormatDate(calculations[0]?.calculated_at, "MMM d, HH:mm") || "Unknown"}`
                : "No calculations"}
            </Badge>
            <Badge variant="outline" className="text-xs">
              <RefreshCw className="h-3 w-3 mr-1" />
              Auto-refresh
            </Badge>
          </div>
        </div>

        {/* Insufficient Data Alert */}
        {dataStatusData && !dataStatusData.sufficient && (
          <div className="flex items-center gap-3 p-4 rounded-lg border border-amber-500/30 bg-amber-500/5">
            <div className="h-10 w-10 rounded-full bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-amber-500">Insufficient Trading Data</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                VaR calculations require at least {dataStatusData.minRequired} days of trading history. 
                You currently have <span className="font-medium text-foreground">{dataStatusData.tradeDays} days</span> ({dataStatusData.totalTrades} trades).
                Keep trading to unlock automatic risk metrics.
              </p>
            </div>
            <Badge variant="outline" className="text-amber-500 bg-amber-500/10 flex-shrink-0">
              {dataStatusData.tradeDays}/{dataStatusData.minRequired} days
            </Badge>
          </div>
        )}

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
          <TabsList className="inline-flex">
            <TabsTrigger value="overview" className="gap-1.5">
              <BarChart3 className="h-4 w-4" />
              Overview
            </TabsTrigger>
            <TabsTrigger value="var" className="gap-1.5">
              <ShieldAlert className="h-4 w-4" />
              VaR
            </TabsTrigger>
            <TabsTrigger value="stress" className="gap-1.5">
              <Zap className="h-4 w-4" />
              Stress Tests
            </TabsTrigger>
          </TabsList>

          {/* TAB 1: OVERVIEW */}
          <TabsContent value="overview" className="space-y-6">
            {/* KPI Cards */}
            <SummaryCards
              calculations={calculations}
              scenarios={scenarios}
              riskData={riskData}
              riskPolicy={riskLimitsData?.policy}
              equity={equity}
              onViewScenario={handleViewScenario}
              snapshotData={snapshotData}
              dataStatus={dataStatusData}
              onForceSnapshot={() => forceSnapshot.mutate({})}
              isForceSnapshotPending={forceSnapshot.isPending}
            />

            {/* Two Big Panels */}
            <div className="grid gap-4 lg:grid-cols-2">
              <VaRTrendChart calculations={calculations} dailyPnL={dailyPnL} />
              <ExposureSnapshot positions={positions} riskData={riskData} equity={equity} />
            </div>

            {/* Risk Events Feed */}
            <RiskEventsFeed calculations={calculations} scenarios={scenarios} />
          </TabsContent>

          {/* TAB 2: VAR */}
          <TabsContent value="var" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-1">
                <VaRConfigPanel
                  config={varConfig}
                  onConfigChange={setVarConfig}
                  onRunVaR={handleRunVaR}
                  isRunning={runHistoricalVaR.isPending || runMonteCarloVaR.isPending}
                  symbols={availableSymbols}
                />
              </div>
              <div className="lg:col-span-2">
                <VaRResultsPanel
                  calculations={calculations}
                  riskPolicy={riskLimitsData?.policy}
                  tradeCount={tradeHistoryData?.trades?.length}
                  onRunVaR={handleRunVaR}
                />
              </div>
            </div>
          </TabsContent>

          {/* TAB 3: STRESS TESTS */}
          <TabsContent value="stress" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-1">
                <ScenarioBuilder
                  config={scenarioConfig}
                  onConfigChange={setScenarioConfig}
                  onRunScenario={handleRunScenario}
                  isRunning={runScenarioTest.isPending}
                  symbols={availableSymbols}
                />
              </div>
              <div className="lg:col-span-2">
                <ScenarioResultsPanel
                  scenarios={scenarios}
                  selectedScenario={selectedScenario}
                  factors={factors}
                  positions={scenarioPositions}
                  currentPositions={positions}
                  onSelectScenario={setSelectedScenarioId}
                />
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </TooltipProvider>
  );
}
