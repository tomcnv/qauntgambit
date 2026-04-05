import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import {
   Activity,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Zap,
  Clock,
  Shield,
  Target,
  ChevronRight,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Bot,
  Settings,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  ExternalLink,
  Info,
  Timer,
  Gauge,
  DollarSign,
  Percent,
  CandlestickChart,
  ListOrdered,
} from "lucide-react";
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  Tooltip as RechartsTooltip, 
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  ComposedChart,
  ReferenceLine,
  CartesianGrid,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Separator } from "../../components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { cn, formatSymbolDisplay } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { useOverviewData, useTradeProfile, useTradeHistory, useDrawdownData, useActiveConfig, useBotInstances, useHealthSnapshot } from "../../lib/api/hooks";
import { usePipelineHealth } from "../../lib/api/quant-hooks";
import { TradeInspectorDrawer } from "../../components/trade-history/TradeInspectorDrawer";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useWebSocketContext } from "../../lib/websocket/WebSocketProvider";
import { api } from "../../lib/api/client";
import { getAuthToken, getAuthUser } from "../../store/auth-store";
import { useScopeStore } from "../../store/scope-store";
import { useExchangeAccounts } from "../../lib/api/exchange-accounts-hooks";
import { ExchangeLogo } from "../../components/scope-selector";
import { WarmupStatus } from "../../components/WarmupStatus";
import { RunBar } from "../../components/run-bar";
import { useOrderAttempts } from "../../components/live/OrderAttempts";
import toast from "react-hot-toast";

// Fetch positions with optional exchange/bot filter (includes paper positions!)
const fetchPositions = (params?: { exchangeAccountId?: string; botId?: string }) => {
  const queryParams: Record<string, string> = {};
  if (params?.exchangeAccountId) {
    queryParams.exchangeAccountId = params.exchangeAccountId;
  }
  if (params?.botId) {
    queryParams.botId = params.botId;
  }
  return api.get("/dashboard/positions", { params: queryParams }).then(res => res.data);
};

// Fetch execution stats with optional exchange/bot filter  
const fetchExecutionStatsLocal = (params?: { exchangeAccountId?: string; botId?: string }) => {
  const queryParams: Record<string, string> = {};
  if (params?.exchangeAccountId) {
    queryParams.exchangeAccountId = params.exchangeAccountId;
  }
  if (params?.botId) {
    queryParams.botId = params.botId;
  }
  return api.get("/dashboard/execution", { params: queryParams }).then(res => res.data);
};

// ============================================================================
// TYPES
// ============================================================================

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
  trendValue?: string;
  icon: React.ElementType;
  tooltip?: string;
  variant?: "default" | "success" | "warning" | "danger";
  isLoading?: boolean;
}

interface AlertItem {
  id: string;
  type: "error" | "warning" | "info" | "success";
  message: string;
  timestamp: Date;
  action?: { label: string; href: string };
}

// ============================================================================
// HOOKS
// ============================================================================

const usePositionsLocal = (params?: { exchangeAccountId?: string | null; botId?: string | null }) => useQuery({
  queryKey: ["dashboard-positions", params?.exchangeAccountId, params?.botId],
  queryFn: () => fetchPositions({
    exchangeAccountId: params?.exchangeAccountId || undefined,
    botId: params?.botId || undefined,
  }),
  refetchInterval: 5000,
  staleTime: 3000,
});

const useExecutionStatsLocal = (params?: { exchangeAccountId?: string | null; botId?: string | null }) => useQuery({
  queryKey: ["dashboard-execution-local", params?.exchangeAccountId, params?.botId],
  queryFn: () => fetchExecutionStatsLocal({
    exchangeAccountId: params?.exchangeAccountId || undefined,
    botId: params?.botId || undefined,
  }),
  refetchInterval: 10000,
  staleTime: 5000,
});

// ============================================================================
// COMPONENTS
// ============================================================================

function KPICard({ 
  title, 
  value, 
  subtitle, 
  trend, 
  trendValue, 
  icon: Icon, 
  tooltip,
  variant = "default",
  isLoading = false,
}: KPICardProps) {
  const variantStyles = {
    default: "border-border",
    success: "border-emerald-500/30 bg-emerald-500/5",
    warning: "border-amber-500/30 bg-amber-500/5",
    danger: "border-red-500/30 bg-red-500/5",
  };

  const iconStyles = {
    default: "bg-muted text-muted-foreground",
    success: "bg-emerald-500/10 text-emerald-500",
    warning: "bg-amber-500/10 text-amber-500",
    danger: "bg-red-500/10 text-red-500",
  };

  return (
    <Card className={cn("relative overflow-hidden", variantStyles[variant])}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">{title}</span>
              {tooltip && (
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger>
                      <Info className="h-3.5 w-3.5 text-muted-foreground/50" />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">{tooltip}</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )}
            </div>
            <div className="flex items-baseline gap-2">
              {isLoading ? (
                <div className="h-8 w-24 bg-muted animate-pulse rounded" />
              ) : (
                <span className="text-2xl font-bold tracking-tight">{value}</span>
              )}
              {trend && trendValue && !isLoading && (
                <span className={cn(
                  "flex items-center text-xs font-medium",
                  trend === "up" && "text-emerald-500",
                  trend === "down" && "text-red-500",
                  trend === "neutral" && "text-muted-foreground"
                )}>
                  {trend === "up" && <ArrowUpRight className="h-3 w-3" />}
                  {trend === "down" && <ArrowDownRight className="h-3 w-3" />}
                  {trend === "neutral" && <Minus className="h-3 w-3" />}
                  {trendValue}
                </span>
              )}
            </div>
            {subtitle && !isLoading && (
              <p className="text-xs text-muted-foreground">{subtitle}</p>
            )}
          </div>
          <div className={cn("rounded-xl p-2.5", iconStyles[variant])}>
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function AlertFeed({ alerts }: { alerts: AlertItem[] }) {
  const iconMap = { error: XCircle, warning: AlertTriangle, info: Info, success: CheckCircle2 };
  const colorMap = {
    error: "text-red-500 bg-red-500/10",
    warning: "text-amber-500 bg-amber-500/10",
    info: "text-blue-500 bg-blue-500/10",
    success: "text-emerald-500 bg-emerald-500/10",
  };

  if (alerts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
        <CheckCircle2 className="h-8 w-8 mb-2 opacity-50" />
        <p className="text-sm">No active alerts</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {alerts.map((alert) => {
        const Icon = iconMap[alert.type];
        return (
          <div key={alert.id} className="flex items-start gap-3 rounded-lg border bg-card/50 p-3 transition-colors hover:bg-card">
            <div className={cn("rounded-lg p-1.5", colorMap[alert.type])}>
              <Icon className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium leading-tight">{alert.message}</p>
              <p className="text-xs text-muted-foreground mt-1">{alert.timestamp.toLocaleTimeString()}</p>
            </div>
            {alert.action && (
              <Link to={alert.action.href}>
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">
                  {alert.action.label}
                  <ChevronRight className="h-3 w-3 ml-1" />
                </Button>
              </Link>
            )}
          </div>
        );
      })}
    </div>
  );
}

function PreflightChecklist({ checks }: { checks: { label: string; status: "pass" | "fail" | "warn" | "pending"; detail?: string }[] }) {
  const statusIcon = {
    pass: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    fail: <XCircle className="h-4 w-4 text-red-500" />,
    warn: <AlertTriangle className="h-4 w-4 text-amber-500" />,
    pending: <RefreshCw className="h-4 w-4 text-muted-foreground animate-spin" />,
  };

  return (
    <div className="space-y-2">
      {checks.map((check, idx) => (
        <div key={idx} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
          <div className="flex items-center gap-2">
            {statusIcon[check.status]}
            <span className="text-sm">{check.label}</span>
          </div>
          {check.detail && <span className="text-xs text-muted-foreground">{check.detail}</span>}
        </div>
      ))}
    </div>
  );
}

// Memoized chart config to prevent recharts infinite loop
const CHART_MARGIN = { top: 5, right: 5, left: 5, bottom: 5 };
const CHART_TICK_STYLE = { fontSize: 10, fill: '#64748b' };
const TOOLTIP_STYLE = { backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' };

function EquityChart({ data, isLoading }: { data: { time: string; value: number }[]; isLoading?: boolean }) {
  if (isLoading) {
    return (
      <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
        <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
        Loading equity data...
      </div>
    );
  }
  
  if (!data || data.length === 0) {
    return (
      <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
        No trading data for this period
      </div>
    );
  }

  const minValue = Math.min(...data.map(d => d.value));
  const maxValue = Math.max(...data.map(d => d.value));
  const isPositive = data[data.length - 1]?.value >= data[0]?.value;

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={data} margin={CHART_MARGIN}>
        <defs>
          <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={isPositive ? "#10b981" : "#ef4444"} stopOpacity={0.3} />
            <stop offset="95%" stopColor={isPositive ? "#10b981" : "#ef4444"} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="time" axisLine={false} tickLine={false} tick={CHART_TICK_STYLE} interval="preserveStartEnd" />
        <YAxis 
          domain={[minValue * 0.999, maxValue * 1.001]} 
          axisLine={false} tickLine={false} 
          tick={CHART_TICK_STYLE} 
          tickFormatter={(v) => `$${v.toFixed(0)}`} 
          width={50} 
        />
        <RechartsTooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number) => [`$${value.toFixed(2)}`, 'Equity']}
        />
        <Area type="monotone" dataKey="value" stroke={isPositive ? "#10b981" : "#ef4444"} strokeWidth={2} fill="url(#equityGradient)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function ExecutionChart({ data }: { data: { time: string; slippage: number; latency: number }[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
        No execution data yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <ComposedChart data={data} margin={CHART_MARGIN}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
        <XAxis dataKey="time" axisLine={false} tickLine={false} tick={CHART_TICK_STYLE} interval="preserveStartEnd" />
        <YAxis yAxisId="left" axisLine={false} tickLine={false} tick={CHART_TICK_STYLE} tickFormatter={(v) => `${v}bps`} width={45} />
        <YAxis yAxisId="right" orientation="right" axisLine={false} tickLine={false} tick={CHART_TICK_STYLE} tickFormatter={(v) => `${v}ms`} width={40} />
        <RechartsTooltip contentStyle={TOOLTIP_STYLE} />
        <Bar yAxisId="left" dataKey="slippage" fill="#f59e0b" opacity={0.8} radius={[2, 2, 0, 0]} name="Slippage (bps)" isAnimationActive={false} />
        <Line yAxisId="right" type="monotone" dataKey="latency" stroke="#8b5cf6" strokeWidth={2} dot={false} name="Latency (ms)" isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ============================================================================
// OPS COMPONENTS - Mission Control
// ============================================================================

// Decision Funnel - "Why am I not trading?"
function DecisionFunnel({ 
  eventsIngested = 0,
  signalsGenerated = 0, 
  signalsRejected = 0,
  ordersPlaced = 0,
  fills = 0,
  topRejectReasons = [] as { reason: string; count: number }[],
  decisionsPerSec = 0,
  bladeSignals = {} as Record<string, string>,
  botRunning = false,
  marketDataHealthy = false,
}: {
  eventsIngested?: number;
  signalsGenerated?: number;
  signalsRejected?: number;
  ordersPlaced?: number;
  fills?: number;
  topRejectReasons?: { reason: string; count: number }[];
  decisionsPerSec?: number;
  bladeSignals?: Record<string, string>;
  botRunning?: boolean;
  marketDataHealthy?: boolean;
}) {
  const funnelSteps = [
    { label: "Events", value: eventsIngested, color: "bg-blue-500" },
    { label: "Signals", value: signalsGenerated, color: "bg-violet-500" },
    { label: "Orders", value: ordersPlaced, color: "bg-amber-500" },
    { label: "Fills", value: fills, color: "bg-emerald-500" },
  ];

  // Determine status explanation
  const getStatusExplanation = () => {
    if (!botRunning && eventsIngested === 0) return { text: "Bot stopped", status: "neutral" };
    if (fills > 0) return { text: "Trading normally", status: "success" };
    if (ordersPlaced > 0) return { text: "Orders pending fill", status: "info" };
    if (signalsRejected > 0 && signalsGenerated === 0) return { text: "Signals rejected by risk gates", status: "warning" };
    if (signalsGenerated === 0 && eventsIngested > 0) return { text: "No signals met threshold", status: "info" };
    if (botRunning && marketDataHealthy && eventsIngested === 0) return { text: "Live, awaiting decisions", status: "info" };
    if (eventsIngested === 0) return { text: "Waiting for market data", status: "warning" };
    return { text: "System idle", status: "neutral" };
  };

  const status = getStatusExplanation();
  const statusColors = {
    success: "text-emerald-500",
    warning: "text-amber-500", 
    info: "text-blue-500",
    neutral: "text-muted-foreground",
  };

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Decision Funnel</CardTitle>
          <Badge variant="outline" className="text-[10px] font-mono">
            {decisionsPerSec.toFixed(0)}/s
          </Badge>
        </div>
        <p className={cn("text-xs font-medium", statusColors[status.status as keyof typeof statusColors])}>
          {status.text}
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Funnel visualization */}
        <div className="flex items-center gap-1">
          {funnelSteps.map((step, idx) => (
            <div key={step.label} className="flex-1">
              <div className="flex items-center gap-1">
                <div className={cn("h-6 rounded-sm flex items-center justify-center text-[10px] font-mono text-white", step.color)} 
                     style={{ width: `${Math.max(20, 100 - idx * 20)}%` }}>
                  {step.value.toLocaleString()}
                </div>
                {idx < funnelSteps.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
              </div>
              <p className="text-[10px] text-muted-foreground mt-0.5">{step.label}</p>
            </div>
          ))}
        </div>

        {/* Gate status */}
        <div className="flex flex-wrap gap-1.5 pt-1 border-t">
          {Object.entries(bladeSignals).map(([name, signal]) => (
            <Badge 
              key={name} 
              variant="outline" 
              className={cn(
                "text-[9px] px-1.5",
                signal === 'allow' && "border-emerald-500/50 text-emerald-500",
                signal === 'throttle' && "border-amber-500/50 text-amber-500",
                signal === 'block' && "border-red-500/50 text-red-500",
              )}
            >
              {name}: {signal}
            </Badge>
          ))}
        </div>

        {/* Top rejection reasons */}
        {topRejectReasons.length > 0 && (
          <div className="space-y-1 pt-1 border-t">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Top Rejections</p>
            {topRejectReasons.slice(0, 2).map((r, idx) => (
              <div key={idx} className="flex justify-between text-xs">
                <span className="text-muted-foreground truncate">{r.reason}</span>
                <span className="font-mono text-amber-500">{r.count}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Risk Headroom - Visual limits usage
function RiskHeadroom({
  dailyPnl = 0,
  dailyPnlLimit = 200,
  exposure = 0,
  exposureLimit = 5000,
  positions = 0,
  maxPositions = 4,
  leverage = 0,
  maxLeverage = 10,
}: {
  dailyPnl?: number;
  dailyPnlLimit?: number;
  exposure?: number;
  exposureLimit?: number;
  positions?: number;
  maxPositions?: number;
  leverage?: number;
  maxLeverage?: number;
}) {
  const dailyLossUsed = Math.max(0, -dailyPnl);
  const metrics = [
    { 
      label: "Daily Loss Used", 
      used: dailyLossUsed, 
      limit: dailyPnlLimit, 
      pct: dailyPnlLimit > 0 ? Math.min(100, (dailyLossUsed / dailyPnlLimit) * 100) : 0,
      format: (v: number) => `$${v.toFixed(0)}`,
      isLoss: dailyLossUsed > 0,
    },
    { 
      label: "Exposure", 
      used: exposure, 
      limit: exposureLimit, 
      pct: Math.min(100, (exposure / exposureLimit) * 100),
      format: (v: number) => `$${(v/1000).toFixed(1)}k`,
    },
    { 
      label: "Positions", 
      used: positions, 
      limit: maxPositions, 
      pct: Math.min(100, (positions / maxPositions) * 100),
      format: (v: number) => v.toString(),
    },
    { 
      label: "Leverage", 
      used: leverage, 
      limit: maxLeverage, 
      pct: Math.min(100, (leverage / maxLeverage) * 100),
      format: (v: number) => `${v.toFixed(1)}x`,
    },
  ];

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Risk Headroom</CardTitle>
          <Link to="/risk/limits">
            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]">
              Limits <ChevronRight className="h-3 w-3 ml-0.5" />
            </Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {metrics.map((m) => {
          const isNearLimit = m.pct >= 80;
          const isAtLimit = m.pct >= 95;
          return (
            <div key={m.label} className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">{m.label}</span>
                <span className={cn(
                  "font-mono",
                  isAtLimit && "text-red-500",
                  isNearLimit && !isAtLimit && "text-amber-500",
                  m.isLoss && "text-red-400"
                )}>
                  {m.format(m.used)} / {m.format(m.limit)}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div 
                  className={cn(
                    "h-full rounded-full transition-all",
                    isAtLimit && "bg-red-500",
                    isNearLimit && !isAtLimit && "bg-amber-500",
                    !isNearLimit && "bg-emerald-500"
                  )}
                  style={{ width: `${m.pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// Orders & Rejections Panel
function OrdersRejectionsPanel({
  openOrders = 0,
  cancelRate = 0,
  rejectRate = 0,
  topRejectCodes = [] as { code: string; count: number }[],
  replaceRate = 0,
}: {
  openOrders?: number;
  cancelRate?: number;
  rejectRate?: number;
  topRejectCodes?: { code: string; count: number }[];
  replaceRate?: number;
}) {
  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Orders & Rejections</CardTitle>
          <Link to="/orders">
            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]">
              Details <ChevronRight className="h-3 w-3 ml-0.5" />
            </Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="text-center p-2 rounded-lg bg-muted/50">
            <p className="text-lg font-bold font-mono">{openOrders}</p>
            <p className="text-[10px] text-muted-foreground">Open Orders</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-muted/50">
            <p className={cn("text-lg font-bold font-mono", rejectRate > 5 && "text-amber-500")}>
              {rejectRate.toFixed(1)}%
            </p>
            <p className="text-[10px] text-muted-foreground">Reject Rate</p>
          </div>
        </div>
        <div className="flex justify-between text-xs pt-2 border-t">
          <span className="text-muted-foreground">Cancel Rate</span>
          <span className="font-mono">{cancelRate.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Replace Rate</span>
          <span className="font-mono">{replaceRate.toFixed(1)}%</span>
        </div>
        {topRejectCodes.length > 0 && (
          <div className="pt-2 border-t space-y-1">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Top Reject Codes</p>
            {topRejectCodes.slice(0, 2).map((r, idx) => (
              <div key={idx} className="flex justify-between text-xs">
                <code className="text-[10px] bg-muted px-1 rounded">{r.code}</code>
                <span className="font-mono text-red-400">{r.count}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Top Symbols Mini-Table
function TopSymbolsTable({
  symbols = [] as {
    symbol: string;
    status: string;
    signals: number;
    exposure: number;
    pnl: number;
    slippage: number;
  }[],
  onSymbolClick,
}: {
  symbols?: {
    symbol: string;
    status: string;
    signals: number;
    exposure: number;
    pnl: number;
    slippage: number;
  }[];
  onSymbolClick?: (symbol: string) => void;
}) {
  const getStatusBadge = (status: string) => {
    const s = status.toLowerCase();
    if (s === 'trading' || s === 'active') return "bg-emerald-500/10 text-emerald-500 border-emerald-500/30";
    if (s === 'blocked' || s === 'error') return "bg-red-500/10 text-red-500 border-red-500/30";
    return "bg-muted text-muted-foreground border-border";
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Top Symbols</CardTitle>
          <Link to="/live">
            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]">
              View All <ChevronRight className="h-3 w-3 ml-0.5" />
            </Button>
          </Link>
        </div>
        <CardDescription className="text-xs">By exposure & activity</CardDescription>
      </CardHeader>
      <CardContent>
        {symbols.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No active symbols</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b">
                  <th className="text-left font-medium text-muted-foreground py-1.5 pr-2">Symbol</th>
                  <th className="text-center font-medium text-muted-foreground py-1.5 px-2">Status</th>
                  <th className="text-right font-medium text-muted-foreground py-1.5 px-2">Signals</th>
                  <th className="text-right font-medium text-muted-foreground py-1.5 px-2">Exposure</th>
                  <th className="text-right font-medium text-muted-foreground py-1.5 px-2">P&L</th>
                  <th className="text-right font-medium text-muted-foreground py-1.5 pl-2">Slip</th>
                </tr>
              </thead>
              <tbody>
                {symbols.slice(0, 5).map((s) => {
                  const exposure = s.exposure ?? 0;
                  const pnl = s.pnl ?? 0;
                  const slippage = s.slippage ?? 0;
                  const signals = s.signals ?? 0;
                  return (
                    <tr 
                      key={s.symbol} 
                      className="border-b border-border/30 last:border-0 hover:bg-muted/30 cursor-pointer transition-colors"
                      onClick={() => onSymbolClick?.(s.symbol)}
                    >
                      <td className="py-1.5 pr-2 font-medium">{formatSymbolDisplay(s.symbol)}</td>
                      <td className="py-1.5 px-2 text-center">
                        <Badge variant="outline" className={cn("text-[9px] px-1", getStatusBadge(s.status))}>
                          {s.status}
                        </Badge>
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono">{signals}</td>
                      <td className="py-1.5 px-2 text-right font-mono">${exposure.toFixed(0)}</td>
                      <td className={cn("py-1.5 px-2 text-right font-mono", pnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                        {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                      </td>
                      <td className="py-1.5 pl-2 text-right font-mono text-muted-foreground">{slippage.toFixed(1)}bp</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Latency Percentiles Display
function LatencyPercentiles({
  signalToOrder = { p50: null, p95: null, p99: null },
  orderToAck = { p50: null, p95: null, p99: null },
  ackToFill = { p50: null, p95: null, p99: null },
}: {
  signalToOrder?: { p50: number | null; p95: number | null; p99: number | null };
  orderToAck?: { p50: number | null; p95: number | null; p99: number | null };
  ackToFill?: { p50: number | null; p95: number | null; p99: number | null };
}) {
  const formatLatency = (val: number | null | undefined) => {
    if (val === null || val === undefined) return "N/A";
    return `${val.toFixed(0)}ms`;
  };
  
  const metrics = [
    { label: "Signal → Order", desc: "Time from signal generation to order submission", ...signalToOrder },
    { label: "Order → Ack", desc: "Time from order submission to exchange acknowledgment", ...orderToAck },
    { label: "Ack → Fill", desc: "Time from acknowledgment to order fill", ...ackToFill },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">Latency Percentiles</CardTitle>
            <CardDescription className="text-xs">End-to-end execution timing</CardDescription>
          </div>
          <Tooltip>
            <TooltipTrigger>
              <Info className="h-4 w-4 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent side="left" className="max-w-xs">
              <p className="text-xs">
                <strong>p50</strong>: Median (50% of orders)<br/>
                <strong>p95</strong>: 95th percentile<br/>
                <strong>p99</strong>: 99th percentile (worst case)
              </p>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Header row */}
        <div className="grid grid-cols-4 gap-2 text-[10px] text-muted-foreground border-b pb-2">
          <div className="font-medium">Stage</div>
          <div className="text-right">p50</div>
          <div className="text-right">p95</div>
          <div className="text-right font-semibold">p99</div>
        </div>
        {/* Data rows */}
        {metrics.map((m) => (
          <Tooltip key={m.label}>
            <TooltipTrigger asChild>
              <div className="grid grid-cols-4 gap-2 text-xs hover:bg-muted/30 rounded px-1 py-1 -mx-1 cursor-help transition-colors">
                <div className="text-muted-foreground truncate">{m.label}</div>
                <div className={cn("text-right font-mono", m.p50 === null && "text-muted-foreground")}>{formatLatency(m.p50)}</div>
                <div className={cn("text-right font-mono", m.p95 === null ? "text-muted-foreground" : (m.p95 ?? 0) > 50 && "text-amber-500")}>
                  {formatLatency(m.p95)}
                </div>
                <div className={cn("text-right font-mono font-semibold", m.p99 === null ? "text-muted-foreground" : (m.p99 ?? 0) > 100 ? "text-red-500" : (m.p99 ?? 0) > 50 && "text-amber-500")}>
                  {formatLatency(m.p99)}
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="left">
              <p className="text-xs">{m.desc}</p>
            </TooltipContent>
          </Tooltip>
        ))}
        {/* Total latency */}
        {(() => {
          const hasData = signalToOrder.p50 !== null || orderToAck.p50 !== null || ackToFill.p50 !== null;
          const totalP50 = hasData ? (signalToOrder.p50 ?? 0) + (orderToAck.p50 ?? 0) + (ackToFill.p50 ?? 0) : null;
          const totalP95 = hasData ? (signalToOrder.p95 ?? 0) + (orderToAck.p95 ?? 0) + (ackToFill.p95 ?? 0) : null;
          const totalP99 = hasData ? (signalToOrder.p99 ?? 0) + (orderToAck.p99 ?? 0) + (ackToFill.p99 ?? 0) : null;
          return (
            <div className="grid grid-cols-4 gap-2 text-xs border-t pt-2 mt-2">
              <div className="font-medium">Total</div>
              <div className={cn("text-right font-mono font-medium", totalP50 === null && "text-muted-foreground")}>
                {formatLatency(totalP50)}
              </div>
              <div className={cn("text-right font-mono font-medium", totalP95 === null && "text-muted-foreground")}>
                {formatLatency(totalP95)}
              </div>
              <div className={cn("text-right font-mono font-bold", totalP99 === null && "text-muted-foreground")}>
                {formatLatency(totalP99)}
              </div>
            </div>
          );
        })()}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function Overview() {
  // Selected trade for detail view
  const [selectedTrade, setSelectedTrade] = useState<any>(null);
  const [slippageRollup, setSlippageRollup] = useState<{
    symbol?: string;
    side?: string;
    window_sec?: number;
    latest_realized_slippage_bps?: number;
    avg_realized_slippage_bps_symbol_side?: number;
    sample_count_symbol_side?: number;
    avg_realized_slippage_bps_overall?: number;
    sample_count_overall?: number;
  } | null>(null);
  
  // Scope management
  const queryClient = useQueryClient();
  const { level: scopeLevel, exchangeAccountId, exchangeAccountName, botId, botName } = useScopeStore();
  const authUser = getAuthUser();
  const authToken = getAuthToken();
  const tenantId = useMemo(() => {
    if (authUser?.id) return authUser.id;
    if (!authToken || authToken.split(".").length !== 3) return undefined;
    try {
      const payload = JSON.parse(atob(authToken.split(".")[1]));
      return payload?.tenant_id || payload?.tenantId || payload?.user_id || payload?.userId || payload?.sub;
    } catch {
      return undefined;
    }
  }, [authToken, authUser?.id]);
  const { data: exchangeAccounts = [] } = useExchangeAccounts();
  const { data: botInstancesData } = useBotInstances();
  const bots = (botInstancesData as any)?.bots || [];
  
  // Helper to parse exchange from name like "Test Account (BINANCE)"
  const getExchangeFromName = (name: string | null): string | null => {
    if (!name) return null;
    const match = name.match(/\(([^)]+)\)$/);
    return match ? match[1].toLowerCase() : null;
  };
  const getAccountLabel = (name: string | null): string => {
    if (!name) return 'Exchange';
    return name.replace(/\s*\([^)]+\)$/, '');
  };
  
  const exchange = getExchangeFromName(exchangeAccountName);
  const accountLabel = getAccountLabel(exchangeAccountName);
  
  // Resolve bot/exchange based on scope selection
  const botForExchange = bots.find((bot: any) =>
    bot.exchangeConfigs?.some((config: any) => config.exchange_account_id === exchangeAccountId)
  );

  const scopedBotId =
    scopeLevel === "bot" ? botId :
    scopeLevel === "exchange" ? botForExchange?.id :
    null;

  const scopedBot = scopedBotId
    ? bots.find((b: any) => b.id === scopedBotId) || null
    : null;

  const scopedExchangeId =
    scopeLevel === "fleet" ? null :
    scopeLevel === "exchange" ? exchangeAccountId :
    scopeLevel === "bot" ? scopedBot?.exchangeConfigs?.[0]?.exchange_account_id || exchangeAccountId || null :
    null;

  // Find selected exchange account
  const selectedAccount = (exchangeAccounts as any[]).find((acc: any) => acc.id === scopedExchangeId);

  // Get the specific config for this exchange to access version
  const configForExchange = scopedBot?.exchangeConfigs?.find(
    (config: any) => config.exchange_account_id === scopedExchangeId
  );
  const configVersion = configForExchange?.config_version;
  
  // Data hooks - pass scope params for filtering (including paper trading support)
  const { data: overviewData, isLoading: overviewLoading } = useOverviewData({
    exchangeAccountId: scopedExchangeId,
    botId: scopedBotId,
  });
  const { data: healthData } = useHealthSnapshot({
    botId: scopedBotId || undefined,
    tenantId: tenantId || null,
  });
  const { data: pipelineHealth } = usePipelineHealth(5000);
  const { data: tradeProfile } = useTradeProfile();
  
  // Build trade history params with scope filtering
  const tradeHistoryParams = useMemo(() => {
    const today = new Date();
    const todayStr = today.toLocaleDateString("en-CA");
    const params: any = {
      limit: 5000, // Pull full day's trades to avoid undercounting
      startDate: todayStr,
      endDate: todayStr,
    };
    if (scopedExchangeId) {
      params.exchangeAccountId = scopedExchangeId;
    }
    if (scopedBotId) {
      params.botId = scopedBotId;
    }
    return params;
  }, [scopedExchangeId, scopedBotId]);
  
  const { data: tradeHistoryData, isLoading: tradesLoading } = useTradeHistory(tradeHistoryParams);
  
  // Pass exchange scope to all data hooks (hard-wired to scoped IDs)
  const { data: drawdownData, isLoading: drawdownLoading } = useDrawdownData(24, scopedExchangeId || null, scopedBotId || null);
  const { data: positionsData, isLoading: positionsLoading } = usePositionsLocal({
    exchangeAccountId: scopedExchangeId || null,
    botId: scopedBotId || null,
  });
  const { data: executionData } = useExecutionStatsLocal({
    exchangeAccountId: scopedExchangeId || null,
    botId: scopedBotId || null,
  });
  const orderAttemptsData = useOrderAttempts(scopeLevel === "bot" ? scopedBotId || undefined : undefined, { refetchInterval: 10000 });
  const { data: slippageRollupData } = useQuery({
    queryKey: ["execution-slippage-rollup", scopedBotId],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (scopedBotId) params.botId = scopedBotId;
      const res = await api.get("/dashboard/execution-slippage-rollup", { params });
      return res.data;
    },
    refetchInterval: 15000,
    staleTime: 5000,
  });
  const { data: activeConfigData } = useActiveConfig();
  const { isConnected: wsConnected, lastMessage } = useWebSocketContext();
  const slippageAutotuneMutation = useMutation({
    mutationFn: async (apply: boolean) => {
      const params: Record<string, string | boolean> = { apply };
      if (scopedBotId) params.botId = scopedBotId;
      const res = await api.post("/dashboard/execution-slippage-autotune", null, { params });
      return res.data?.data ?? res.data;
    },
    onSuccess: (data: any) => {
      if (data?.applied) {
        toast.success(`Slippage tuned to ${Number(data.recommended_bps).toFixed(2)}bps`);
        queryClient.invalidateQueries({ queryKey: ["active-config"] });
      } else if (data?.reason === "insufficient_samples") {
        toast("Auto-tune skipped: not enough samples yet", { icon: "⏳" });
      } else if (data?.reason === "already_aligned") {
        toast("Auto-tune: already aligned", { icon: "✅" });
      } else {
        toast("Auto-tune preview refreshed", { icon: "📊" });
      }
      queryClient.invalidateQueries({ queryKey: ["execution-slippage-rollup"] });
    },
    onError: (err: any) => {
      toast.error(err?.message || "Failed to run slippage auto-tune");
    },
  });

  useEffect(() => {
    // Scope changed: clear in-memory rollup until new scope snapshot/WS arrives.
    setSlippageRollup(null);
  }, [scopedBotId, scopedExchangeId]);

  const rollupSeed = useMemo(() => {
    const raw = (slippageRollupData as any)?.data;
    const latest = raw?.latest_symbol_side;
    const overall = raw?.overall;
    if (latest && typeof latest === "object") {
      return latest as any;
    }
    if (overall && typeof overall === "object") {
      return {
        window_sec: overall.window_sec,
        avg_realized_slippage_bps_symbol_side: overall.avg_realized_slippage_bps_overall,
        sample_count_symbol_side: overall.sample_count_overall,
        avg_realized_slippage_bps_overall: overall.avg_realized_slippage_bps_overall,
        sample_count_overall: overall.sample_count_overall,
      };
    }
    return null;
  }, [slippageRollupData]);

  useEffect(() => {
    if (!lastMessage || lastMessage.event !== "bot:execution_slippage_rollup") {
      return;
    }
    const payload = (lastMessage.data ?? {}) as Record<string, unknown>;
    const toFinite = (value: unknown): number | undefined => {
      const n = Number(value);
      return Number.isFinite(n) ? n : undefined;
    };
    setSlippageRollup({
      symbol: typeof payload.symbol === "string" ? payload.symbol : undefined,
      side: typeof payload.side === "string" ? payload.side : undefined,
      window_sec: toFinite(payload.window_sec),
      latest_realized_slippage_bps: toFinite(payload.latest_realized_slippage_bps),
      avg_realized_slippage_bps_symbol_side: toFinite(payload.avg_realized_slippage_bps_symbol_side),
      sample_count_symbol_side: toFinite(payload.sample_count_symbol_side),
      avg_realized_slippage_bps_overall: toFinite(payload.avg_realized_slippage_bps_overall),
      sample_count_overall: toFinite(payload.sample_count_overall),
    });
  }, [lastMessage]);

  // Extract data
  const botStatus = overviewData?.botStatus as any;
  const fastScalper = overviewData?.fastScalper as any;
  const liveStatus = (overviewData?.liveStatus ?? (healthData as any)?.liveStatus) as any;
  const positionGuardian = liveStatus?.position_guardian ?? liveStatus?.health?.position_guardian ?? null;
  const executionReadiness = liveStatus?.health?.execution_readiness ?? liveStatus?.execution_readiness ?? null;
  const tradingActivity = liveStatus?.health?.trading_activity ?? liveStatus?.trading_activity ?? null;
  const dominantExecutionFailure = useMemo(() => {
    const attempts = orderAttemptsData?.data?.attempts ?? [];
    if (!Array.isArray(attempts) || attempts.length === 0) return null;
    const grouped = new Map<string, { symbol?: string; reason: string; count: number }>();
    for (const attempt of attempts) {
      if (!attempt || !["failed", "rejected", "timeout"].includes(attempt.status)) continue;
      const reason = String(attempt.error_code || attempt.error_message || attempt.rejection_stage || attempt.status || "execution_failed");
      const key = `${attempt.symbol || "unknown"}::${reason}`;
      const current = grouped.get(key) || { symbol: attempt.symbol, reason, count: 0 };
      current.count += 1;
      grouped.set(key, current);
    }
    return Array.from(grouped.values()).sort((a, b) => b.count - a.count)[0] || null;
  }, [orderAttemptsData?.data?.attempts]);
  const tradingInfo = botStatus?.trading as any;
  const scopedMetrics = overviewData?.scopedMetrics as any;
  // Prefer scoped metrics whenever a bot is scoped so the view changes with selection
  const metrics = scopedBotId
    ? (scopedMetrics || tradingInfo?.metrics || fastScalper?.metrics || {})
    : (scopedMetrics?._source ? scopedMetrics : (tradingInfo?.metrics ?? fastScalper?.metrics ?? {}));
  const alerts = overviewData?.alerts as any;
  const isPaperAccount = selectedAccount?.environment === 'paper' || scopedMetrics?._isPaper;
  
  const isTradingActive = tradingInfo?.isActive ?? false;
  const platformStatus = botStatus?.platform?.status ?? fastScalper?.status ?? "offline";
  const liveHeartbeatStatus = String(
    liveStatus?.heartbeat?.status ??
    (healthData as any)?.status ??
    liveStatus?.health?.status ??
    ""
  ).toLowerCase();
  const runtimeHeartbeatActive =
    liveHeartbeatStatus === "ok" ||
    liveHeartbeatStatus === "running" ||
    Boolean((healthData as any)?.botStatus?.heartbeatAlive) ||
    String(liveStatus?.health?.services?.python_engine?.status ?? "").toLowerCase() === "running";
  const environment = tradingInfo?.mode ?? "paper";
  
  // Check if we have a verified exchange account (not the old trade_profiles system)
  const hasVerifiedCredential = selectedAccount?.status === 'verified' || 
    (exchangeAccounts as any[]).some((acc: any) => acc.status === 'verified');
  const lastHeartbeat = botStatus?.platform?.lastHeartbeat ?? fastScalper?.lastHeartbeat;

  // KPI values - use filtered trade data when at exchange/bot scope
  const trades = tradeHistoryData?.trades ?? [];
  const totalTradeCount = tradeHistoryData?.totalCount ?? trades.length;
  
  const resolveTradePnl = useCallback((trade: any) => {
    const toNum = (value: any) => {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    };
    const netRaw = trade?.net_pnl ?? trade?.netPnl;
    const grossRaw = trade?.gross_pnl ?? trade?.grossPnl;
    const feesRaw = trade?.total_fees_usd ?? trade?.totalFees ?? trade?.fees ?? trade?.fee;
    const fees = toNum(feesRaw);
    const net = netRaw != null ? toNum(netRaw) : (grossRaw != null ? toNum(grossRaw) - fees : toNum(trade?.pnl));
    const gross = grossRaw != null ? toNum(grossRaw) : (netRaw != null ? net + fees : toNum(trade?.pnl) + fees);
    return { net, gross, fees };
  }, []);
  
  // Legacy fallback: calculate realized P&L from filtered trades (today only)
  // Primary source should be backend metrics to avoid timezone/day-boundary drift.
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayTrades = trades.filter((t: any) => new Date(t.timestamp || t.closedAt) >= todayStart);
  const dailyAgg = todayTrades.reduce((acc: { net: number; gross: number; fees: number }, t: any) => {
    const { net, gross, fees } = resolveTradePnl(t);
    acc.net += net;
    acc.gross += gross;
    acc.fees += fees;
    return acc;
  }, { net: 0, gross: 0, fees: 0 });
  
  // Trade stats from API
  const tradeStats = tradeHistoryData?.stats ?? {};
  
  // Prefer backend metrics when they are populated, but do not let a stale zeroed metrics
  // payload hide scoped trade-history PnL that the user can already see elsewhere.
  const metricDailyPnlRaw = Number(metrics?.daily_pnl ?? metrics?.dailyPnl);
  const tradeHistoryPnlRaw = Number(tradeStats?.totalPnl ?? tradeStats?.totalPnL ?? tradeStats?.netPnl);
  const metricDailyFeesRaw = Number(metrics?.daily_fees ?? tradeStats?.totalFees);
  const hasMetricDailyPnl = Number.isFinite(metricDailyPnlRaw);
  const hasTradeHistoryPnl = Number.isFinite(tradeHistoryPnlRaw);
  const hasMetricDailyFees = Number.isFinite(metricDailyFeesRaw);
  const preferTradeHistoryPnl =
    hasTradeHistoryPnl &&
    (
      !hasMetricDailyPnl ||
      (
        Math.abs(metricDailyPnlRaw) < 0.01 &&
        Math.abs(tradeHistoryPnlRaw) >= 0.01
      )
    );
  const dailyPnl = preferTradeHistoryPnl
    ? tradeHistoryPnlRaw
    : (hasMetricDailyPnl ? metricDailyPnlRaw : dailyAgg.net);
  const dailyFees = hasMetricDailyFees
    ? Math.abs(metricDailyFeesRaw)
    : Math.abs(Number(tradeStats?.totalFees ?? dailyAgg.fees));
  const dailyPnlGross = hasMetricDailyPnl ? (dailyPnl + dailyFees) : dailyAgg.gross;
  const positions = positionsData?.data ?? positionsData?.positions ?? [];
  const calculatedUnrealizedPnl = positions.reduce((sum: number, pos: any) => {
    const unrealized = Number(pos.unrealizedPnl ?? pos.unrealized_pnl ?? pos.pnl ?? 0);
    return sum + (Number.isFinite(unrealized) ? unrealized : 0);
  }, 0);
  const unrealizedPnl =
    (positions.length > 0 ? calculatedUnrealizedPnl : null)
    ?? metrics?.unrealized_pnl
    ?? metrics?.unrealizedPnl
    ?? liveStatus?.risk?.unrealized_pnl
    ?? 0;
  const totalPnl = dailyPnl + unrealizedPnl;
  const drawdown = metrics?.drawdown ?? metrics?.max_drawdown ?? metrics?.maxDrawdown ?? liveStatus?.risk?.drawdown ?? 0;
  const rollingDrawdown = metrics?.rolling_drawdown ?? liveStatus?.risk?.rolling_drawdown ?? drawdown;
  
  // Calculate net exposure from actual positions (authoritative source)
  const calculatedNetExposure = useMemo(() => {
    if (!positions.length) return 0;
    return positions.reduce((sum: number, p: any) => {
      const qty = parseFloat(p.quantity || p.size || 0) || 0;
      const price = parseFloat(p.mark_price || p.current_price || p.markPrice || p.entry_price || p.entryPrice || 0) || 0;
      const notional = Math.abs(qty * price);
      const side = (p.side || '').toUpperCase();
      // LONG/BUY = positive, everything else (SHORT/SELL) = negative
      const signed = (side === 'LONG' || side === 'BUY') ? notional : -notional;
      return sum + signed;
    }, 0);
  }, [positions]);
  const exposure = positions.length > 0 ? calculatedNetExposure : (metrics?.net_exposure ?? metrics?.netExposure ?? metrics?.exposure ?? liveStatus?.risk?.net_exposure ?? 0);
  const leverage = metrics?.leverage ?? liveStatus?.risk?.leverage ?? 1;
  // Get slippage/latency from execution data or metrics
  const slippage = executionData?.data?.quality?.overall?.avg_slippage_bps 
    ?? executionData?.data?.quality?.recent?.avg_slippage_bps
    ?? executionData?.data?.fill?.avg_slippage_bps
    ?? metrics?.avg_slippage ?? metrics?.avgSlippage ?? metrics?.slippageBps ?? 0;
  const latency = executionData?.data?.quality?.overall?.avg_execution_time_ms 
    ?? executionData?.data?.quality?.recent?.avg_execution_time_ms
    ?? metrics?.avg_latency ?? metrics?.avgLatency ?? metrics?.latencyMs ?? 0;
  // Decision rejection rate from live-status (risk management rejections) 
  // NOT exchange order rejections - this shows how many signals are being blocked
  const rejectRate = liveStatus?.rejectRate?.last5m 
    ?? executionData?.data?.quality?.overall?.rejection_rate 
    ?? metrics?.reject_rate ?? metrics?.rejectRate ?? 0;
  // Use TODAY's trade count (filtered), not total historical count
  const tradesToday = tradeHistoryData?.totalCount ?? todayTrades.length;
  const winRate = metrics?.win_rate ?? metrics?.winRate ?? 0;
  // Execution quality stats - try multiple paths to find data
  const fillRate = executionData?.data?.quality?.recent?.fill_rate 
    ?? executionData?.data?.fill?.fill_rate_pct 
    ?? executionData?.data?.fillRate 
    ?? metrics?.fillRate 
    ?? 0;
  const makerRatio = executionData?.data?.quality?.makerRatio 
    ?? executionData?.data?.makerRatio 
    ?? metrics?.makerRatio 
    ?? null; // Show N/A if not available
  const effectiveRollup = slippageRollup || rollupSeed;
  const rollupWindowMin = Math.max(1, Math.round((effectiveRollup?.window_sec ?? 3600) / 60));
  const rollupAvgSymbolSide = effectiveRollup?.avg_realized_slippage_bps_symbol_side;
  const rollupLatest = effectiveRollup?.latest_realized_slippage_bps;
  const rollupSampleCount = Math.max(0, Math.floor(effectiveRollup?.sample_count_symbol_side ?? 0));
  const rollupOverall = effectiveRollup?.avg_realized_slippage_bps_overall;
  const rollupOverallCount = Math.max(0, Math.floor(effectiveRollup?.sample_count_overall ?? 0));
  const hasRollup = Number.isFinite(rollupAvgSymbolSide) && rollupSampleCount > 0;
  const activeConfig = (activeConfigData as any)?.active || activeConfigData || {};
  const configuredSymbolSlippageBps = (() => {
    const symbol = (effectiveRollup?.symbol || "").toUpperCase();
    const symbols = ((activeConfigData as any)?.symbols || []) as any[];
    if (!symbol || !Array.isArray(symbols)) return null;
    const matched = symbols.find((s) => String(s?.symbol || "").toUpperCase() === symbol);
    const value = Number(matched?.max_slippage_bps ?? matched?.maxSlippageBps);
    return Number.isFinite(value) && value > 0 ? value : null;
  })();
  const configuredEvSlippageBps = (() => {
    const candidates = [
      configuredSymbolSlippageBps,
      Number(activeConfig?.max_slippage_bps),
      Number(activeConfig?.maxSlippageBps),
      Number(activeConfig?.execution_config?.max_slippage_bps),
      Number(activeConfig?.executionConfig?.max_slippage_bps),
      Number(activeConfig?.profile_overrides?.slippage_bps),
      Number(activeConfig?.profile_overrides?.cost_model?.slippage_bps),
      Number((activeConfigData as any)?.max_slippage_bps),
    ];
    const firstValid = candidates.find((n) => Number.isFinite(n) && n > 0);
    return firstValid ?? null;
  })();
  const slippageBand =
    hasRollup && configuredEvSlippageBps
      ? Number(rollupAvgSymbolSide) <= configuredEvSlippageBps
        ? "good"
        : Number(rollupAvgSymbolSide) <= configuredEvSlippageBps * 1.25
          ? "warn"
          : "bad"
      : null;
  const rollupRows = useMemo(() => {
    const rows = ((slippageRollupData as any)?.data?.symbol_sides || []) as any[];
    return rows
      .map((row) => ({
        symbol: String(row?.symbol || ""),
        side: String(row?.side || "").toUpperCase(),
        avg: Number(row?.avg_realized_slippage_bps_symbol_side || 0),
        count: Math.max(0, Math.floor(Number(row?.sample_count_symbol_side || 0))),
        latest: Number(row?.latest_realized_slippage_bps || 0),
      }))
      .filter((row) => row.symbol && Number.isFinite(row.avg));
  }, [slippageRollupData]);

  // ============================================================================
  // OPS PANEL DATA - Decision Funnel, Risk Headroom, Orders & Rejections
  // ============================================================================
  
  // Bot running state
  const botRunning =
    runtimeHeartbeatActive ||
    isTradingActive ||
    platformStatus === 'running' ||
    platformStatus === 'warming';
  const marketDataHealthy =
    String(liveStatus?.quality?.status || "").toLowerCase() === "ok" ||
    Number(liveStatus?.quality?.quality_score ?? 0) > 0.8 ||
    (
      Number(liveStatus?.quality?.orderbook_age_sec ?? 999) <= 1 &&
      String(liveStatus?.quality?.orderbook_sync_state || "").toLowerCase() === "synced"
    ) ||
    String(
      pipelineHealth?.layers?.find((layer: any) => String(layer?.name || "").toLowerCase() === "ingest")?.status || ""
    ).toLowerCase() === "healthy";
  
  // Orchestrator stats - prefer liveStatus (from /api/dashboard/live-status), fallback to fastScalper/botStatus
  const rawOrchestratorStats = liveStatus?.orchestratorStats ?? fastScalper?.orchestratorStats ?? fastScalper?.orchestrator_stats ?? botStatus?.orchestrator_stats;
  const orchestratorStats = useMemo(() => {
    // If we have raw orchestrator stats from liveStatus or fastScalper
    if (rawOrchestratorStats) {
      return {
        events_ingested: rawOrchestratorStats.eventsIngested ?? rawOrchestratorStats.events_ingested ?? rawOrchestratorStats.execution_count ?? 0,
        signals_generated: rawOrchestratorStats.signalsGenerated ?? rawOrchestratorStats.signals_generated ?? ((rawOrchestratorStats.execution_count ?? 0) - (rawOrchestratorStats.rejection_count ?? 0)),
        signals_rejected: rawOrchestratorStats.signalsRejected ?? rawOrchestratorStats.signals_rejected ?? rawOrchestratorStats.rejection_count ?? 0,
        orders_placed: rawOrchestratorStats.ordersPlaced ?? rawOrchestratorStats.orders_placed ?? rawOrchestratorStats.completion_count ?? tradesToday,
        fills: rawOrchestratorStats.fills ?? tradesToday,
        decisions_per_sec: rawOrchestratorStats.decisionsPerSec ?? rawOrchestratorStats.decisions_per_sec ?? (rawOrchestratorStats.avg_latency_ms ? 1000 / rawOrchestratorStats.avg_latency_ms : 0),
      };
    }
    // Fallback: use execution data and trade count
    const execFill = executionData?.data?.fill ?? executionData?.data?.quality?.overall ?? {};
    const execQuality = executionData?.data?.quality?.recent ?? {};
    // Calculate decisions per second from average latency or estimate from trade count
    const avgLatencyMs = execQuality?.avg_execution_time_ms ?? executionData?.data?.fill?.avg_slippage_bps ?? 0;
    const estimatedDps = avgLatencyMs > 0 ? Math.min(1000 / avgLatencyMs, 100) : 0;
    
    return {
      events_ingested: fastScalper?.websocket?.messagesReceived ?? execFill?.total_orders ?? tradesToday,
      signals_generated: execFill?.total_orders ?? tradesToday,
      signals_rejected: execFill?.total_rejected ?? 0,
      orders_placed: execFill?.total_orders ?? tradesToday,
      fills: execFill?.total_filled ?? tradesToday,
      decisions_per_sec: estimatedDps,
    };
  }, [rawOrchestratorStats, tradesToday, fastScalper?.websocket?.messagesReceived, executionData?.data, liveStatus?.orchestratorStats]);
  
  // Get decisions per second from fastScalper metrics or orchestratorStats
  const decisionsPerSec = useMemo(() => {
    // Try multiple sources for decisions per second
    return liveStatus?.orchestratorStats?.decisionsPerSec
      ?? fastScalper?.metrics?.decisionsPerSec 
      ?? fastScalper?.metrics?.decisions_per_sec
      ?? orchestratorStats?.decisions_per_sec
      ?? (executionData?.data?.quality?.recent?.avg_execution_time_ms 
          ? Math.min(1000 / executionData.data.quality.recent.avg_execution_time_ms, 100) 
          : 0);
  }, [liveStatus?.orchestratorStats, fastScalper?.metrics, orchestratorStats?.decisions_per_sec, executionData?.data?.quality?.recent?.avg_execution_time_ms]);
  
  // Blade signals from liveStatus or bot metrics
  const bladeSignals: Record<string, string> = useMemo(() => {
    // Prefer liveStatus.bladeSignals
    const signals = liveStatus?.bladeSignals ?? fastScalper?.blade_signals ?? botStatus?.blade_signals ?? {};
    // Normalize to simple string values
    return Object.entries(signals).reduce((acc, [key, val]) => {
      if (typeof val === 'object' && val !== null) {
        acc[key] = (val as any).signal ?? (val as any).status ?? 'allow';
      } else {
        acc[key] = String(val);
      }
      return acc;
    }, {} as Record<string, string>);
  }, [liveStatus?.bladeSignals, fastScalper?.blade_signals, botStatus?.blade_signals]);
  
  // Check if signals are blocked
  const signalsBlocked = Object.values(bladeSignals).some(s => s === 'block' || s === 'EMERGENCY');
  
  // Top rejection reasons - prefer liveStatus
  const topRejectReasons: { reason: string; count: number }[] = useMemo(() => {
    const reasons = liveStatus?.topRejectReasons ?? fastScalper?.rejection_reasons ?? botStatus?.rejection_reasons ?? [];
    if (Array.isArray(reasons)) return reasons.slice(0, 3);
    // Convert object to array
    return Object.entries(reasons).map(([reason, count]) => ({ reason, count: count as number })).slice(0, 3);
  }, [liveStatus?.topRejectReasons, fastScalper?.rejection_reasons, botStatus?.rejection_reasons]);
  
  // Risk limits from activeConfig or defaults
  const riskLimits = activeConfigData?.risk_config ?? activeConfigData?.riskConfig ?? {
    daily_loss_limit: 200,
    max_exposure: 5000,
    max_positions: 4,
    max_leverage: 10,
  };
  const dailyLossLimitUsd = (() => {
    const explicitUsd = Number(riskLimits?.maxDailyLossUsd ?? riskLimits?.max_daily_loss_usd);
    if (Number.isFinite(explicitUsd) && explicitUsd > 0) return explicitUsd;
    const pct = Number(riskLimits?.maxDailyLossPct ?? riskLimits?.max_daily_loss_pct);
    const equity = Number(
      metrics?.equity ??
      metrics?.account_equity ??
      metrics?.accountBalance ??
      metrics?.account_balance ??
      0
    );
    if (Number.isFinite(pct) && pct > 0 && Number.isFinite(equity) && equity > 0) {
      return (pct / 100) * equity;
    }
    const legacy = Number(riskLimits?.daily_loss_limit);
    return Number.isFinite(legacy) && legacy > 0 ? legacy : 200;
  })();
  
  // Top reject codes - prefer liveStatus.topRejectReasons (decision rejections)
  const topRejectCodes: { code: string; count: number }[] = useMemo(() => {
    // Prefer decision rejection reasons from live-status
    const liveReasons = liveStatus?.topRejectReasons;
    if (Array.isArray(liveReasons) && liveReasons.length > 0) {
      return liveReasons.slice(0, 3).map((r: any) => ({ 
        code: r.reason || r.code || 'unknown', 
        count: r.count || 0 
      }));
    }
    // Fallback to execution data (order rejections)
    const codes = executionData?.data?.reject_codes ?? executionData?.data?.rejectCodes ?? [];
    if (Array.isArray(codes)) return codes.slice(0, 3);
    return Object.entries(codes).map(([code, count]) => ({ code, count: count as number })).slice(0, 3);
  }, [liveStatus?.topRejectReasons, executionData?.data?.reject_codes, executionData?.data?.rejectCodes]);
  
  // Top symbols by exposure or activity
  const topSymbols = useMemo(() => {
    const symbolMap = new Map<string, {
      symbol: string;
      status: string;
      signals: number;
      exposure: number;
      pnl: number;
      slippage: number;
      _slippages?: number[];
    }>();

    const apiTopSymbols = liveStatus?.topSymbols;
    const hasLocalData = positions.length > 0 || trades.length > 0;
    if (!hasLocalData && apiTopSymbols && Array.isArray(apiTopSymbols) && apiTopSymbols.length > 0) {
      return apiTopSymbols.map((sym: any) => ({
        symbol: sym.symbol,
        status: sym.netExposure !== 0 ? 'Trading' : 'Idle',
        signals: sym.signals || 0,
        exposure: Math.abs(sym.netExposure || sym.longExposure || sym.shortExposure || 0),
        pnl: sym.pnl || 0,
        slippage: sym.slippage || 0,
      }));
    }

    // Use today's trades (same local-day window used for net P&L) to keep numbers consistent.
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todaysTrades = trades.filter((t: any) => new Date(t.timestamp || t.closedAt) >= todayStart);

    // Seed with API exposure/signals if present (we will overwrite P&L with local net P&L).
    if (apiTopSymbols && Array.isArray(apiTopSymbols)) {
      apiTopSymbols.forEach((sym: any) => {
        symbolMap.set(sym.symbol, {
          symbol: sym.symbol,
          status: (sym.netExposure ?? 0) !== 0 ? 'Trading' : 'Idle',
          signals: sym.signals || 0,
          exposure: Math.abs(sym.netExposure || sym.longExposure || sym.shortExposure || 0),
          pnl: 0,
          slippage: sym.slippage || 0,
        });
      });
    }

    // Add positions for exposure + unrealized P&L
    positions.forEach((pos: any) => {
      const symbol = pos.symbol;
      const qty = parseFloat(pos.quantity || pos.size || 0) || 0;
      const price = parseFloat(pos.mark_price || pos.current_price || pos.markPrice || pos.entry_price || pos.entryPrice || 0) || 0;
      const notional = Math.abs(qty * price);
      const unrealized = parseFloat(pos.unrealizedPnl || pos.unrealized_pnl || pos.pnl || 0) || 0;
      const existing = symbolMap.get(symbol);
      if (existing) {
        existing.exposure = Math.max(existing.exposure, notional);
        existing.status = 'Trading';
        existing.pnl += unrealized;
      } else {
        symbolMap.set(symbol, {
          symbol,
          status: 'Trading',
          signals: 0,
          exposure: notional,
          pnl: unrealized,
          slippage: 0,
        });
      }
    });

    // Add today's realized P&L and slippage from trades (net of fees)
    todaysTrades.forEach((trade: any) => {
      const symbol = trade.symbol;
      const netPnl = resolveTradePnl(trade).net;
      const slip = trade.slippage_bps ?? trade.slippage;
      if (!symbolMap.has(symbol)) {
        symbolMap.set(symbol, {
          symbol,
          status: 'Idle',
          signals: 0,
          exposure: 0,
          pnl: 0,
          slippage: 0,
          _slippages: [],
        });
      }
      const entry = symbolMap.get(symbol)!;
      entry.pnl += netPnl || 0;
      entry.signals += 1;
      if (slip !== undefined && slip !== null) {
        if (!entry._slippages) entry._slippages = [];
        entry._slippages.push(Number(slip));
      }
    });

    const results = Array.from(symbolMap.values()).map((entry) => {
      if (entry._slippages && entry._slippages.length > 0) {
        const avgSlip = entry._slippages.reduce((a, b) => a + b, 0) / entry._slippages.length;
        entry.slippage = avgSlip;
      }
      delete entry._slippages;
      return entry;
    });

    // Convert to array and sort by exposure then signals
    return results
      .sort((a, b) => b.exposure - a.exposure || b.signals - a.signals)
      .slice(0, 5);
  }, [positions, trades, liveStatus?.topSymbols, resolveTradePnl]);
  
  // Latency percentiles from execution data or fallback to simple values
  const latencyPercentiles = useMemo(() => {
    const execQuality = executionData?.data?.quality?.overall ?? executionData?.data?.quality?.recent ?? {};
    return {
      signalToOrder: {
        p50: execQuality.signal_to_order_p50 ?? null,
        p95: execQuality.signal_to_order_p95 ?? null,
        p99: execQuality.signal_to_order_p99 ?? null,
      },
      orderToAck: {
        p50: execQuality.order_to_ack_p50 ?? null,
        p95: execQuality.order_to_ack_p95 ?? null,
        p99: execQuality.order_to_ack_p99 ?? null,
      },
      ackToFill: {
        p50: execQuality.ack_to_fill_p50 ?? null,
        p95: execQuality.ack_to_fill_p95 ?? null,
        p99: execQuality.ack_to_fill_p99 ?? null,
      },
    };
  }, [executionData?.data?.quality, latency]);

  // Build equity chart data from drawdown endpoint
  const equityChartData = useMemo(() => {
    if (!drawdownData?.drawdown || drawdownData.drawdown.length === 0) return [];
    return drawdownData.drawdown.map((point: any) => ({
      time: new Date(point.time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
      value: point.equity,
    }));
  }, [drawdownData]);

  // Build execution chart data (simplified - from metrics if available)
  const executionChartData = useMemo(() => {
    // If we have hourly execution data from backend, use it
    // Otherwise, create simple data points from current metrics
    if (!trades.length) return [];
    
    // Group trades by hour and calculate avg slippage/latency
    const hourlyMap = new Map<string, { slippages: number[], latencies: number[] }>();
    trades.forEach((trade: any) => {
      const hour = new Date(trade.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
      if (!hourlyMap.has(hour)) hourlyMap.set(hour, { slippages: [], latencies: [] });
      const entry = hourlyMap.get(hour)!;
      // Use slippage_bps and latency_ms from trade data
      const tradeSlippage = trade.slippage_bps ?? trade.slippage ?? 0;
      const tradeLatency = trade.latency_ms ?? trade.fill_time_ms ?? trade.latency ?? 0;
      if (tradeSlippage > 0) entry.slippages.push(tradeSlippage);
      if (tradeLatency > 0) entry.latencies.push(tradeLatency);
    });

    return Array.from(hourlyMap.entries()).map(([time, data]) => ({
      time,
      slippage: data.slippages.length ? data.slippages.reduce((a, b) => a + b, 0) / data.slippages.length : slippage,
      latency: data.latencies.length ? data.latencies.reduce((a, b) => a + b, 0) / data.latencies.length : latency,
    }));
  }, [trades, slippage, latency]);

  // Build alerts from real data
  const alertItems: AlertItem[] = useMemo(() => {
    const items: AlertItem[] = [];
    if (!hasVerifiedCredential) {
      items.push({ id: "no-creds", type: "warning", message: "No exchange credentials configured", timestamp: new Date(), action: { label: "Configure", href: "/bot-management" } });
    }
    if (!wsConnected) {
      items.push({ id: "ws-disconnected", type: "error", message: "WebSocket disconnected - real-time data unavailable", timestamp: new Date() });
    }
    if (drawdown > 2) {
      items.push({ id: "high-dd", type: "warning", message: `High drawdown: ${drawdown.toFixed(2)}%`, timestamp: new Date(), action: { label: "View Risk", href: "/risk" } });
    }
    if (positionGuardian?.status === "misconfigured") {
      items.push({
        id: "guard-misconfigured",
        type: "error",
        message: `Position guard misconfigured: ${positionGuardian?.reason || "invalid_guard_policy"}`,
        timestamp: new Date(),
        action: { label: "System Health", href: "/dashboard/settings/system-health" },
      });
    }
    if (executionReadiness?.exchange_credentials_configured === false) {
      items.push({
        id: "exchange-credentials-missing",
        type: "error",
        message: "Exchange credentials missing",
        timestamp: new Date(),
        action: { label: "Bot Management", href: "/bot-management" },
      });
    }
    if (executionReadiness?.config_drift_active) {
      items.push({
        id: "config-drift-active",
        type: "warning",
        message: "Runtime config drift detected",
        timestamp: new Date(),
        action: { label: "Runtime Config", href: "/dashboard/runtime-config" },
      });
    }
    if (executionReadiness?.execution_ready === false && executionReadiness?.execution_block_reason) {
      items.push({
        id: "execution-readiness-blocked",
        type: executionReadiness?.trading_paused ? "warning" : "error",
        message: `Execution blocked: ${executionReadiness.execution_block_reason}`,
        timestamp: new Date(),
        action: { label: "System Health", href: "/dashboard/settings/system-health" },
      });
    }
    if (tradingActivity?.top_rejected_symbol) {
      items.push({
        id: "top-rejected-symbol",
        type: "warning",
        message: `Top blocked symbol: ${tradingActivity.top_rejected_symbol} · ${tradingActivity.top_rejected_symbol_reason || "rejection_only"}`,
        timestamp: new Date(),
        action: { label: "Trading Ops", href: "/dashboard/trading-ops" },
      });
    }
    if (dominantExecutionFailure?.symbol) {
      items.push({
        id: "top-execution-failure",
        type: "warning",
        message: `Execution failures: ${dominantExecutionFailure.symbol} · ${dominantExecutionFailure.reason}`,
        timestamp: new Date(),
        action: { label: "Live Trading", href: "/dashboard/live-trading" },
      });
    }
    // Add alerts from backend
    if (alerts?.items) {
      alerts.items.slice(0, 3).forEach((alert: any, idx: number) => {
        items.push({
          id: `backend-${idx}`,
          type: alert.severity === 'critical' ? 'error' : alert.severity === 'warning' ? 'warning' : 'info',
          message: alert.message,
          timestamp: new Date(alert.timestamp || Date.now()),
        });
      });
    }
    return items;
  }, [hasVerifiedCredential, wsConnected, drawdown, alerts, positionGuardian, executionReadiness, tradingActivity, dominantExecutionFailure]);

  // Preflight checks
  const preflightChecks = useMemo(() => [
    { label: "API Keys", status: hasVerifiedCredential ? "pass" : "fail" as const, detail: hasVerifiedCredential ? "Verified" : "Not configured" },
    { label: "WebSocket", status: wsConnected ? "pass" : "fail" as const, detail: wsConnected ? "Connected" : "Disconnected" },
    { label: "Risk Limits", status: drawdown < 5 ? "pass" : "warn" as const, detail: drawdown < 5 ? "Within bounds" : `DD: ${drawdown.toFixed(1)}%` },
    { label: "Market Data", status: wsConnected ? "pass" : "warn" as const, detail: wsConnected ? "Live" : "Stale" },
  ], [hasVerifiedCredential, wsConnected, drawdown]);

  const formatHeartbeat = () => {
    if (!lastHeartbeat) return "No heartbeat";
    const diff = Date.now() - new Date(lastHeartbeat).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    return new Date(lastHeartbeat).toLocaleTimeString();
  };

  return (
    <TooltipProvider>
      {/* Sticky Run Bar - Controls and status for the active exchange/bot */}
      <RunBar />
      
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* ================================================================== */}
        {/* SECTION 1: OVERVIEW DASHBOARD */}
        {/* ================================================================== */}
        
        <section className="space-y-4">
          {/* Page title with subheader */}
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
            <p className="text-sm text-muted-foreground">Performance metrics, risk status, and trading activity at a glance</p>
          </div>

          {/* Fleet Overview: Exchange Accounts Summary */}
          {scopeLevel === 'fleet' && exchangeAccounts.length > 0 && (
            <Card className="border-primary/20">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base font-medium">Exchange Accounts</CardTitle>
                  <Link to="/exchange-accounts">
                    <Button variant="ghost" size="sm" className="text-xs">
                      Manage <ChevronRight className="h-3 w-3 ml-1" />
                    </Button>
                  </Link>
                </div>
                <CardDescription>Risk pools and connected venues</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                  {exchangeAccounts.slice(0, 6).map((account: any) => (
                    <div 
                      key={account.id} 
                      className="flex items-center gap-3 p-3 rounded-lg border bg-card hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => useScopeStore.getState().setExchangeScope(account.id, `${account.label} (${account.venue.toUpperCase()})`)}
                    >
                      <div className={cn(
                        "h-10 w-10 rounded-lg flex items-center justify-center",
                        account.status === 'verified' ? "bg-emerald-500/10" : "bg-muted"
                      )}>
                        <Activity className={cn(
                          "h-5 w-5",
                          account.status === 'verified' ? "text-emerald-500" : "text-muted-foreground"
                        )} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium truncate">{account.label}</p>
                          <Badge variant="outline" className="text-[10px] px-1">
                            {account.venue?.toUpperCase()}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{account.environment?.toUpperCase()}</span>
                          {account.running_bot_count > 0 && (
                            <span className="text-emerald-500">{account.running_bot_count} bot(s) running</span>
                          )}
                        </div>
                      </div>
                      {account.kill_switch_enabled && (
                        <Badge variant="destructive" className="text-[10px]">KILLED</Badge>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Bot List for Fleet scope */}
          {scopeLevel === 'fleet' && bots.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base font-medium">Bot Fleet</CardTitle>
                  <Link to="/bot-management">
                    <Button variant="ghost" size="sm" className="text-xs">
                      Manage <ChevronRight className="h-3 w-3 ml-1" />
                    </Button>
                  </Link>
                </div>
                <CardDescription>{bots.length} bot(s) configured</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {bots.slice(0, 5).map((bot: any) => (
                    <div 
                      key={bot.id}
                      className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => {
                        const exchangeConfig = bot.exchangeConfigs?.[0];
                        if (exchangeConfig?.exchange_account_id) {
                          useScopeStore.getState().setBotScope(
                            exchangeConfig.exchange_account_id,
                            exchangeConfig.exchange || 'Exchange',
                            bot.id,
                            bot.name
                          );
                        }
                      }}
                    >
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          "h-8 w-8 rounded-lg flex items-center justify-center",
                          bot.status === 'running' ? "bg-emerald-500/10" : "bg-muted"
                        )}>
                          <Bot className={cn(
                            "h-4 w-4",
                            bot.status === 'running' ? "text-emerald-500" : "text-muted-foreground"
                          )} />
                        </div>
                        <div>
                          <p className="text-sm font-medium">{bot.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {bot.exchangeConfigs?.[0]?.exchange?.toUpperCase() || "No config"} · {bot.environment || "paper"}
                          </p>
                        </div>
                      </div>
                      <Badge variant={bot.status === 'running' ? 'default' : 'secondary'} className="text-xs">
                        {bot.status || 'idle'}
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* KPI Cards */}
          <div className="grid gap-4 grid-cols-2 lg:grid-cols-5">
            <KPICard
              title="Net PnL"
              value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`}
              subtitle={`Today Realized Gross: $${dailyPnlGross.toFixed(2)} · Fees: -$${dailyFees.toFixed(2)} · Live Unreal: $${unrealizedPnl.toFixed(2)}`}
              trend={totalPnl >= 0 ? "up" : "down"}
              trendValue={tradesToday > 0 ? `${tradesToday} trades` : undefined}
              icon={DollarSign}
              variant={totalPnl >= 0 ? "success" : "danger"}
              tooltip="Current net PnL: today's realized PnL after fees plus current unrealized PnL on open positions"
              isLoading={overviewLoading}
            />
            <KPICard
              title="Current Drawdown"
              value={`${drawdown.toFixed(2)}%`}
              subtitle={`Rolling: ${rollingDrawdown.toFixed(2)}%`}
              trend={drawdown > 2 ? "down" : drawdown > 1 ? "neutral" : "up"}
              icon={TrendingDown}
              variant={drawdown > 3 ? "danger" : drawdown > 1.5 ? "warning" : "default"}
              tooltip="Current drawdown from peak equity, not today's realized session PnL"
              isLoading={overviewLoading}
            />
            <KPICard
              title="Net Exposure"
              value={`${exposure < 0 ? '-' : ''}$${Math.abs(exposure).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              subtitle={`${leverage.toFixed(1)}x leverage · ${positions.length} positions`}
              trend={exposure < 0 ? "down" : exposure > 0 ? "up" : "neutral"}
              icon={Target}
              variant={leverage > 5 ? "warning" : "default"}
              tooltip="Net directional exposure (negative = short, positive = long)"
              isLoading={overviewLoading || positionsLoading}
            />
            <KPICard
              title="Execution Quality"
              value={`${slippage.toFixed(1)}bps`}
              subtitle={`${latency.toFixed(0)}ms roundtrip · ${(100 - rejectRate).toFixed(0)}% fill rate`}
              trend={slippage < 2 ? "up" : slippage > 5 ? "down" : "neutral"}
              icon={Zap}
              variant={rejectRate > 50 ? "warning" : slippage > 5 ? "warning" : "default"}
              tooltip="Slippage: price impact vs expected. Roundtrip: exchange order latency. Fill rate: orders that completed successfully (pre-flight failures like min notional reduce this)."
              isLoading={overviewLoading}
            />
            <KPICard
              title="Realized Slippage"
              value={hasRollup ? `${Number(rollupAvgSymbolSide).toFixed(2)}bps` : "—"}
              trend={
                !hasRollup
                  ? "neutral"
                  : slippageBand === "good"
                    ? "up"
                    : slippageBand === "bad"
                      ? "down"
                      : "neutral"
              }
              trendValue={
                configuredEvSlippageBps
                  ? `Target ${configuredEvSlippageBps.toFixed(2)}bps`
                  : rollupOverallCount > 0 && Number.isFinite(rollupOverall)
                    ? `Overall ${Number(rollupOverall).toFixed(2)}bps`
                    : undefined
              }
              subtitle={hasRollup
                ? `${rollupSampleCount} closes / ${rollupWindowMin}m · latest ${(rollupLatest ?? 0).toFixed(2)}bps${configuredEvSlippageBps ? ` · vs target ${((Number(rollupAvgSymbolSide) - configuredEvSlippageBps) >= 0 ? "+" : "")}${(Number(rollupAvgSymbolSide) - configuredEvSlippageBps).toFixed(2)}bps` : ""}`
                : `Waiting for closed trades (${rollupWindowMin}m window)`
              }
              icon={BarChart3}
              variant={
                !hasRollup
                  ? "default"
                  : slippageBand === "good"
                    ? "success"
                    : slippageBand === "bad"
                      ? "danger"
                      : "warning"
              }
              tooltip="Rolling realized slippage from closed positions (entry+exit), used to tune EV cost assumptions."
              isLoading={false}
            />
          </div>

          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-medium">Realized Slippage Offenders</CardTitle>
                  <CardDescription>Highest rolling slippage by symbol/side (closed positions)</CardDescription>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => slippageAutotuneMutation.mutate(true)}
                  disabled={slippageAutotuneMutation.isPending}
                >
                  {slippageAutotuneMutation.isPending ? "Tuning..." : "Auto-tune now"}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {rollupRows.length === 0 ? (
                <p className="text-sm text-muted-foreground">No closed-trade slippage rollup yet.</p>
              ) : (
                <div className="space-y-2">
                  {rollupRows.slice(0, 6).map((row) => {
                    const rowBand = configuredEvSlippageBps
                      ? row.avg <= configuredEvSlippageBps
                        ? "text-emerald-500"
                        : row.avg <= configuredEvSlippageBps * 1.25
                          ? "text-amber-500"
                          : "text-red-500"
                      : "text-foreground";
                    return (
                      <div key={`${row.symbol}:${row.side}`} className="grid grid-cols-5 gap-2 rounded border px-2 py-1 text-xs">
                        <div className="font-medium">{formatSymbolDisplay(row.symbol)}</div>
                        <div className="text-muted-foreground">{row.side}</div>
                        <div className={cn("text-right font-mono", rowBand)}>{row.avg.toFixed(2)}bps</div>
                        <div className="text-right text-muted-foreground">{row.count} closes</div>
                        <div className="text-right text-muted-foreground">latest {row.latest.toFixed(2)}</div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ================================================================== */}
          {/* OPS ROW - Decision Funnel, Risk Headroom, Orders & Rejections */}
          {/* ================================================================== */}
          <div className="grid gap-4 lg:grid-cols-3">
            <DecisionFunnel
              eventsIngested={orchestratorStats?.events_ingested || 0}
              signalsGenerated={orchestratorStats?.signals_generated || 0}
              signalsRejected={orchestratorStats?.signals_rejected || 0}
              ordersPlaced={orchestratorStats?.orders_placed || tradesToday || 0}
              fills={orchestratorStats?.fills || tradesToday || 0}
              decisionsPerSec={decisionsPerSec}
              status={botRunning ? (signalsBlocked ? "signals_blocked" : "healthy") : "idle"}
              bladeSignals={bladeSignals}
              topRejectReasons={topRejectReasons}
              botRunning={botRunning}
              marketDataHealthy={marketDataHealthy}
            />
            
            <RiskHeadroom 
              dailyPnl={dailyPnl}
              dailyPnlLimit={dailyLossLimitUsd}
              exposure={Math.abs(exposure)}
              exposureLimit={riskLimits?.max_exposure || 5000}
              positions={positions.length}
              maxPositions={riskLimits?.max_positions || 4}
              leverage={leverage}
              maxLeverage={riskLimits?.max_leverage || 10}
            />
            
            <OrdersRejectionsPanel 
              openOrders={liveStatus?.pendingOrders?.count ?? executionData?.data?.open_orders ?? 0}
              cancelRate={executionData?.data?.cancel_rate || 0}
              rejectRate={rejectRate}
              replaceRate={executionData?.data?.replace_rate || 0}
              topRejectCodes={topRejectCodes}
            />
          </div>

          {/* Top Symbols & Latency Percentiles Row */}
          <div className="grid gap-4 lg:grid-cols-2">
            <TopSymbolsTable 
              symbols={topSymbols}
              onSymbolClick={(symbol) => console.log('Navigate to', symbol)}
            />
            <LatencyPercentiles 
              signalToOrder={latencyPercentiles.signalToOrder}
              orderToAck={latencyPercentiles.orderToAck}
              ackToFill={latencyPercentiles.ackToFill}
            />
          </div>
        </section>

        {/* ================================================================== */}
        {/* SECTION 2: CHARTS */}
        {/* ================================================================== */}
        
        <section className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-medium">Equity Curve</CardTitle>
                  <CardDescription>24-hour performance</CardDescription>
                </div>
                <Badge variant="outline" className="font-mono text-xs">24H</Badge>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <EquityChart data={equityChartData} isLoading={drawdownLoading} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-medium">Execution Quality</CardTitle>
                  <CardDescription>Slippage & latency</CardDescription>
                </div>
                <div className="flex gap-3 text-xs">
                  <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-500" />Slippage</span>
                  <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-violet-500" />Latency</span>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <ExecutionChart data={executionChartData} />
            </CardContent>
          </Card>
        </section>

        {/* ================================================================== */}
        {/* ALERTS BANNER - Only show when there are active alerts */}
        {/* ================================================================== */}
        {alertItems.length > 0 && (
          <Card className="border-amber-500/50 bg-amber-500/5">
            <CardHeader className="pb-2 pt-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                  <CardTitle className="text-sm font-medium text-amber-500">Active Alerts</CardTitle>
                  <Badge variant="outline" className="text-[10px] border-amber-500/50 text-amber-500">{alertItems.length}</Badge>
                </div>
                <Link to="/alerts">
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] text-amber-500 hover:text-amber-400">
                    View All <ChevronRight className="h-3 w-3 ml-0.5" />
                  </Button>
                </Link>
              </div>
            </CardHeader>
            <CardContent className="pb-3">
              <div className="flex flex-wrap gap-2">
                {alertItems.slice(0, 4).map((alert, i) => (
                  <Badge key={i} variant="outline" className="text-[10px] border-amber-500/30 text-amber-600 bg-amber-500/10">
                    {alert.title || alert.message || 'Alert'}
                  </Badge>
                ))}
                {alertItems.length > 4 && (
                  <Badge variant="outline" className="text-[10px] border-muted text-muted-foreground">
                    +{alertItems.length - 4} more
                  </Badge>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ================================================================== */}
        {/* SECTION 3: POSITIONS & EXECUTION STATS */}
        {/* ================================================================== */}
        
        <section className="grid gap-4 lg:grid-cols-3">
          {/* Positions - 2/3 width */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <CardTitle className="text-base font-medium">Positions</CardTitle>
                  <Badge variant="outline" className="text-xs font-mono">{positions.length} open</Badge>
                  <span className={cn("text-sm font-mono", exposure >= 0 ? "text-emerald-500" : "text-red-500")}>
                    {exposure < 0 ? '-' : ''}${Math.abs(exposure).toLocaleString(undefined, { maximumFractionDigits: 0 })} exposure
                  </span>
                </div>
                <Link to="/active-bot">
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">Details <ChevronRight className="h-3 w-3 ml-1" /></Button>
                </Link>
              </div>
            </CardHeader>
            <CardContent>
              {positions.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No open positions</p>
                  <p className="text-xs mt-1">Positions will appear here when you have active trades</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-xs text-muted-foreground">
                        <th className="text-left font-medium py-2 pr-4">Symbol</th>
                        <th className="text-right font-medium py-2 px-4">Size</th>
                        <th className="text-right font-medium py-2 px-4">Entry</th>
                        <th className="text-right font-medium py-2 px-4">Mark</th>
                        <th className="text-right font-medium py-2 px-4">Value</th>
                        <th className="text-right font-medium py-2 px-4">P&L (Gross / Net Est)</th>
                        <th className="text-right font-medium py-2 pl-4">%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((pos: any) => {
                        const pnl = pos.unrealizedPnl ?? pos.unrealized_pnl ?? pos.pnl ?? 0;
                        const estimatedNetPnl =
                          pos.estimatedNetUnrealizedAfterFees ??
                          pos.estimated_net_unrealized_after_fees ??
                          pnl;
                        const pnlPct = pos.unrealizedPnlPct ?? pos.unrealized_pnl_pct ?? 0;
                        const entryPrice = pos.entryPrice ?? pos.entry_price ?? 0;
                        const markPrice = pos.markPrice ?? pos.mark_price ?? pos.reference_price ?? 0;
                        const qty = pos.size ?? pos.quantity ?? 0;
                        const marketValue = pos.marketValue ?? pos.market_value ?? (markPrice * Math.abs(qty));
                        const side = (pos.side || '').toLowerCase();
                        const isLong = side === 'long' || side === 'buy';
                        return (
                          <tr key={pos.symbol} className="border-b border-border/50 hover:bg-muted/30">
                            <td className="py-2.5 pr-4">
                              <div className="flex items-center gap-2">
                                <Badge variant="outline" className={cn("text-[10px] px-1.5 w-12 justify-center", isLong ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500")}>
                                  {isLong ? 'LONG' : 'SHORT'}
                                </Badge>
                                <span className="font-medium">{formatSymbolDisplay(pos.symbol)}</span>
                              </div>
                            </td>
                            <td className="text-right py-2.5 px-4 font-mono text-xs">
                              {qty.toFixed(4)}
                            </td>
                            <td className="text-right py-2.5 px-4 font-mono text-xs text-muted-foreground">
                              ${entryPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td className="text-right py-2.5 px-4 font-mono text-xs">
                              ${markPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </td>
                            <td className="text-right py-2.5 px-4 font-mono text-xs">
                              ${marketValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                            </td>
                            <td className={cn("text-right py-2.5 px-4 font-mono text-xs font-medium", pnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                              <div>{pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</div>
                              <div className={cn("text-[10px]", estimatedNetPnl >= 0 ? "text-emerald-400/90" : "text-red-400/90")}>
                                {estimatedNetPnl >= 0 ? '+' : ''}${Number(estimatedNetPnl).toFixed(2)}
                              </div>
                            </td>
                            <td className={cn("text-right py-2.5 pl-4 font-mono text-xs", pnlPct >= 0 ? "text-emerald-500/80" : "text-red-500/80")}>
                              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                    {positions.length > 0 && (
                      <tfoot>
                        <tr className="font-medium">
                          <td className="py-2.5 pr-4 text-muted-foreground">Total</td>
                          <td className="text-right py-2.5 px-4"></td>
                          <td className="text-right py-2.5 px-4"></td>
                          <td className="text-right py-2.5 px-4"></td>
                          <td className="text-right py-2.5 px-4 font-mono text-xs">
                            ${positions.reduce((sum: number, p: any) => sum + (p.marketValue ?? p.market_value ?? 0), 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                          </td>
                          <td className={cn("text-right py-2.5 px-4 font-mono text-xs", unrealizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                            {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(2)}
                          </td>
                          <td className="text-right py-2.5 pl-4"></td>
                        </tr>
                      </tfoot>
                    )}
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Execution Stats - 1/3 width */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-medium">Execution Stats</CardTitle>
                <Link to="/execution">
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">Report <ChevronRight className="h-3 w-3 ml-1" /></Button>
                </Link>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Fill Rate</span>
                  <span className="font-mono">{fillRate.toFixed(1)}%</span>
                </div>
                <Progress value={fillRate} className="h-1.5" />
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Maker Ratio</span>
                  <span className="font-mono">{makerRatio !== null ? `${makerRatio.toFixed(0)}%` : 'N/A'}</span>
                </div>
                {makerRatio !== null && (
                  <div className="flex h-1.5 rounded-full overflow-hidden bg-muted">
                    <div className="bg-emerald-500" style={{ width: `${makerRatio}%` }} />
                    <div className="bg-amber-500" style={{ width: `${100 - makerRatio}%` }} />
                  </div>
                )}
              </div>
              <Separator />
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Trades Today</span>
                  <span className="font-mono">{tradesToday}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Win Rate</span>
                  <span className={cn("font-mono", winRate >= 50 ? "text-emerald-500" : "text-red-500")}>{winRate.toFixed(1)}%</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        {/* ================================================================== */}
        {/* SECTION 4: PRE-FLIGHT & RECENT TRADES */}
        {/* ================================================================== */}
        
        <section className="grid gap-4 lg:grid-cols-2">
          {/* Pre-flight Checklist */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-medium">Pre-flight Checklist</CardTitle>
                <Badge variant="outline" className={cn("text-xs", preflightChecks.every(c => c.status === "pass") ? "border-emerald-500/50 text-emerald-500" : "border-amber-500/50 text-amber-500")}>
                  {preflightChecks.filter(c => c.status === "pass").length}/{preflightChecks.length} passed
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <PreflightChecklist checks={preflightChecks} />
            </CardContent>
          </Card>

          {/* Recent Trades */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-medium">Recent Trades</CardTitle>
                <Link to="/history">
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">View All <ChevronRight className="h-3 w-3 ml-1" /></Button>
                </Link>
              </div>
            </CardHeader>
            <CardContent>
              {tradesLoading ? (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  Loading trades...
                </div>
              ) : trades.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <Activity className="h-8 w-8 mb-2 opacity-50" />
                  <p className="text-sm">No trades yet</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50">
                        <th className="text-left font-medium text-muted-foreground py-2 pr-4">Time</th>
                        <th className="text-left font-medium text-muted-foreground py-2 pr-4">Symbol</th>
                        <th className="text-left font-medium text-muted-foreground py-2 pr-4">Type</th>
                        <th className="text-right font-medium text-muted-foreground py-2">PnL / Fee</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.slice(0, 5).map((trade: any, idx: number) => {
                        const { net: netPnl, fees } = resolveTradePnl(trade);
                        const pnl = trade.pnl || 0;
                        const isEntry = pnl === 0 && fees > 0;
                        const isExit = pnl !== 0;
                        
                        return (
                          <tr 
                            key={trade.id || idx} 
                            className="border-b border-border/30 last:border-0 cursor-pointer hover:bg-muted/30 transition-colors"
                            onClick={() => setSelectedTrade(trade)}
                          >
                            <td className="py-2.5 pr-4 font-mono text-xs text-muted-foreground">
                              {new Date(trade.timestamp).toLocaleTimeString()}
                            </td>
                            <td className="py-2.5 pr-4 font-medium">{trade.symbol}</td>
                            <td className="py-2.5 pr-4">
                              {isEntry ? (
                                <Badge variant="outline" className={cn("text-[10px] px-1.5", trade.side === "BUY" || trade.side === "buy" ? "border-blue-500/50 text-blue-500" : "border-orange-500/50 text-orange-500")}>
                                  {trade.side === "BUY" || trade.side === "buy" ? "OPEN LONG" : "OPEN SHORT"}
                                </Badge>
                              ) : (
                                <Badge variant="outline" className={cn("text-[10px] px-1.5", netPnl >= 0 ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500")}>
                                  {trade.side === "SELL" || trade.side === "sell" ? "CLOSE LONG" : "CLOSE SHORT"}
                                </Badge>
                              )}
                            </td>
                            <td className="py-2.5 text-right font-mono font-medium">
                              {isEntry ? (
                                <span className="text-muted-foreground text-xs">
                                  fee: ${fees.toFixed(2)}
                                </span>
                              ) : (
                                <span className={netPnl >= 0 ? "text-emerald-500" : "text-red-500"}>
                                  {netPnl >= 0 ? "+" : ""}${netPnl.toFixed(2)}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      </div>
      
      {/* Unified Trade Detail Drawer */}
      <TradeInspectorDrawer
        open={!!selectedTrade}
        onOpenChange={(open) => !open && setSelectedTrade(null)}
        trade={selectedTrade ? {
          id: selectedTrade.id,
          symbol: selectedTrade.symbol,
          side: selectedTrade.side,
          timestamp: selectedTrade.timestamp,
          quantity: selectedTrade.size,
          entryPrice: selectedTrade.entry_price,
          exitPrice: selectedTrade.exit_price,
          entryTime: selectedTrade.entry_time,
          pnl: selectedTrade.pnl,
          fees: selectedTrade.fees,
          strategy: selectedTrade.strategy || selectedTrade.strategy_id,
          latency: selectedTrade.latency_ms,
          slippage: selectedTrade.slippage_bps,
          exitReason: selectedTrade.exitReason,
        } : null}
      />
    </TooltipProvider>
  );
}
