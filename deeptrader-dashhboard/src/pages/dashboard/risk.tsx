import { useState, useMemo } from "react";
import {
  Shield,
  AlertTriangle,
  Settings,
  TrendingDown,
  Target,
  Clock,
  Zap,
  CheckCircle2,
  XCircle,
  Info,
  ChevronRight,
  History,
  DollarSign,
  Percent,
  Loader2,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Separator } from "../../components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { useDrawdownData, useRiskLimits, useDashboardRisk, useTradeHistory } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { RunBar } from "../../components/run-bar";

export default function RiskPage() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  const scopedExchangeAccountId = scopeLevel !== "fleet" ? exchangeAccountId ?? null : null;
  const scopedBotId = scopeLevel === "bot" ? botId ?? null : null;

  // Fetch real data
  const { data: drawdownData, isLoading: loadingDrawdown } = useDrawdownData(720, scopedExchangeAccountId, scopedBotId); // 30 days
  const { data: riskLimitsData, isLoading: loadingLimits } = useRiskLimits();
  const { data: riskData, isLoading: loadingRisk } = useDashboardRisk({
    exchangeAccountId: scopedExchangeAccountId ?? undefined,
    botId: scopedBotId ?? undefined,
  });
  const { data: tradeHistoryData } = useTradeHistory({
    limit: 100,
    exchangeAccountId: scopedExchangeAccountId ?? undefined,
    botId: scopedBotId ?? undefined,
  });

  const isLoading = loadingDrawdown || loadingLimits || loadingRisk;

  // Extract metrics from risk data
  const metrics = riskData?.data ?? riskData ?? {};
  const currentDrawdown = metrics?.drawdown ?? metrics?.max_drawdown ?? drawdownData?.currentDrawdown ?? 0;
  const maxDrawdownToday = drawdownData?.maxDrawdown ?? currentDrawdown;
  const leverage = metrics?.leverage ?? 1;
  const exposure = metrics?.net_exposure ?? metrics?.exposure ?? 0;
  
  // Calculate daily loss from trade history
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayTrades = (tradeHistoryData?.trades ?? []).filter((t: any) => 
    new Date(t.timestamp || t.exit_time) >= todayStart
  );
  const dailyPnl = todayTrades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0);
  const dailyLoss = dailyPnl < 0 ? Math.abs(dailyPnl) : 0;

  // Risk limits from API or defaults
  const limits = riskLimitsData?.data ?? riskData?.data?.limits ?? {};
  const dailyLossLimit = limits?.daily_loss_limit ?? limits?.dailyLossLimit ?? 500;
  const maxLeverage = limits?.max_leverage ?? limits?.maxLeverage ?? 10;
  const maxDrawdownLimit = limits?.max_drawdown ?? limits?.maxDrawdown ?? 5;
  const maxPositions = limits?.max_positions ?? limits?.maxPositions ?? 5;
  const positionSizeLimit = limits?.max_position_size ?? limits?.maxPositionSize ?? 100;

  // Current position count
  const openPositions = metrics?.open_positions ?? metrics?.openPositions ?? 0;

  // Build risk limits display
  const riskLimits = useMemo(() => [
    { 
      label: "Daily Loss Limit", 
      current: dailyLoss, 
      limit: dailyLossLimit, 
      unit: "$", 
      status: dailyLoss / dailyLossLimit > 0.8 ? "warning" : "ok" 
    },
    { 
      label: "Max Leverage", 
      current: leverage, 
      limit: maxLeverage, 
      unit: "x", 
      status: leverage / maxLeverage > 0.8 ? "warning" : "ok" 
    },
    { 
      label: "Max Concurrent Positions", 
      current: openPositions, 
      limit: maxPositions, 
      unit: "", 
      status: openPositions / maxPositions > 0.8 ? "warning" : "ok" 
    },
    { 
      label: "Drawdown Limit", 
      current: currentDrawdown, 
      limit: maxDrawdownLimit, 
      unit: "%", 
      status: currentDrawdown / maxDrawdownLimit > 0.8 ? "warning" : "ok" 
    },
  ], [dailyLoss, dailyLossLimit, leverage, maxLeverage, openPositions, maxPositions, currentDrawdown, maxDrawdownLimit]);

  // Determine overall risk status
  const riskStatus = useMemo(() => {
    const hasWarning = riskLimits.some(l => l.status === "warning");
    const hasCritical = riskLimits.some(l => l.current / l.limit > 0.95);
    if (hasCritical) return { label: "Critical", color: "text-red-500", bgColor: "bg-red-500/5 border-red-500/30" };
    if (hasWarning) return { label: "Warning", color: "text-amber-500", bgColor: "bg-amber-500/5 border-amber-500/30" };
    return { label: "Healthy", color: "text-emerald-500", bgColor: "bg-emerald-500/5 border-emerald-500/30" };
  }, [riskLimits]);

  // Build drawdown chart data from API
  const drawdownChartData = useMemo(() => {
    if (drawdownData?.history && drawdownData.history.length > 0) {
      return drawdownData.history.map((point: any, idx: number) => ({
        day: idx + 1,
        drawdown: point.drawdown ?? point.value ?? 0,
      }));
    }
    // Fallback: generate from equity curve if available
    if (drawdownData?.equityCurve && drawdownData.equityCurve.length > 0) {
      let peak = drawdownData.equityCurve[0]?.equity ?? 0;
      return drawdownData.equityCurve.map((point: any, idx: number) => {
        const equity = point.equity ?? 0;
        if (equity > peak) peak = equity;
        const dd = peak > 0 ? ((peak - equity) / peak) * 100 : 0;
        return { day: idx + 1, drawdown: dd };
      });
    }
    // No data
    return [];
  }, [drawdownData]);

  const maxDrawdownChart = drawdownChartData.length > 0 
    ? Math.max(...drawdownChartData.map((d: any) => d.drawdown)) 
    : 0;
  const avgDrawdownChart = drawdownChartData.length > 0 
    ? drawdownChartData.reduce((sum: number, d: any) => sum + d.drawdown, 0) / drawdownChartData.length 
    : 0;

  // Risk events from API or empty
  const riskEvents = riskData?.data?.events ?? [];

  return (
    <TooltipProvider>
      <RunBar />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Risk Management</h1>
            <p className="text-sm text-muted-foreground">
              Monitor limits, drawdown, and risk audit log
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            <Button variant="outline" className="gap-2" onClick={() => setSettingsOpen(true)}>
              <Settings className="h-4 w-4" />
              Configure Limits
            </Button>
          </div>
        </div>

        {/* Risk Summary Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Current Drawdown</span>
                <TrendingDown className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">{currentDrawdown.toFixed(2)}%</p>
              <p className="text-xs text-muted-foreground mt-1">Max today: {maxDrawdownToday.toFixed(2)}%</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Daily Loss Used</span>
                <DollarSign className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                ${dailyLoss.toFixed(2)} 
                <span className="text-sm font-normal text-muted-foreground"> / ${dailyLossLimit}</span>
              </p>
              <Progress value={(dailyLoss / dailyLossLimit) * 100} className="h-1.5 mt-2" />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Leverage</span>
                <Percent className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                {leverage.toFixed(1)}x 
                <span className="text-sm font-normal text-muted-foreground"> / {maxLeverage}x</span>
              </p>
              <Progress value={(leverage / maxLeverage) * 100} className="h-1.5 mt-2" />
            </CardContent>
          </Card>

          <Card className={riskStatus.bgColor}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Risk Status</span>
                {riskStatus.label === "Healthy" ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                ) : riskStatus.label === "Warning" ? (
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                ) : (
                  <XCircle className="h-4 w-4 text-red-500" />
                )}
              </div>
              <p className={cn("text-2xl font-bold", riskStatus.color)}>{riskStatus.label}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {riskStatus.label === "Healthy" ? "All limits within bounds" : "Check limits above"}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="limits" className="space-y-4">
          <TabsList className="bg-muted/50">
            <TabsTrigger value="limits" className="gap-2">
              <Target className="h-4 w-4" />
              Limits
            </TabsTrigger>
            <TabsTrigger value="drawdown" className="gap-2">
              <TrendingDown className="h-4 w-4" />
              Drawdown
            </TabsTrigger>
            <TabsTrigger value="audit" className="gap-2">
              <History className="h-4 w-4" />
              Audit Log
            </TabsTrigger>
          </TabsList>

          {/* Limits Tab */}
          <TabsContent value="limits" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium">Risk Limits</CardTitle>
                <CardDescription>Current utilization of configured risk limits</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {riskLimits.map((limit, idx) => (
                    <div key={idx} className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">{limit.label}</span>
                        <span className="text-sm font-mono">
                          {typeof limit.current === 'number' ? limit.current.toFixed(2) : limit.current}{limit.unit} / {limit.limit}{limit.unit}
                        </span>
                      </div>
                      <Progress 
                        value={limit.limit > 0 ? (limit.current / limit.limit) * 100 : 0} 
                        className={cn(
                          "h-2",
                          limit.limit > 0 && (limit.current / limit.limit) > 0.8 && "[&>div]:bg-amber-500",
                          limit.limit > 0 && (limit.current / limit.limit) > 0.95 && "[&>div]:bg-red-500"
                        )}
                      />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Drawdown Tab */}
          <TabsContent value="drawdown" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base font-medium">30-Day Drawdown</CardTitle>
                    <CardDescription>Historical drawdown from peak equity</CardDescription>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <div>
                      <span className="text-muted-foreground">Max: </span>
                      <span className="font-mono font-medium">{maxDrawdownChart.toFixed(2)}%</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Avg: </span>
                      <span className="font-mono font-medium">{avgDrawdownChart.toFixed(2)}%</span>
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="h-[300px]">
                  {drawdownChartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={drawdownChartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
                        <defs>
                          <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <XAxis 
                          dataKey="day" 
                          axisLine={false}
                          tickLine={false}
                          tick={{ fontSize: 10, fill: '#64748b' }}
                        />
                        <YAxis 
                          axisLine={false}
                          tickLine={false}
                          tick={{ fontSize: 10, fill: '#64748b' }}
                          tickFormatter={(v) => `${v.toFixed(1)}%`}
                          domain={[0, Math.max(5, maxDrawdownChart * 1.2)]}
                          width={40}
                        />
                        <ReferenceLine y={maxDrawdownLimit} stroke="#ef4444" strokeDasharray="5 5" label={{ value: 'Limit', fill: '#ef4444', fontSize: 10 }} />
                        <RechartsTooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--card))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                            fontSize: '12px',
                          }}
                          formatter={(value: number) => [`${value.toFixed(2)}%`, 'Drawdown']}
                        />
                        <Area
                          type="monotone"
                          dataKey="drawdown"
                          stroke="#ef4444"
                          strokeWidth={2}
                          fill="url(#ddGradient)"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-muted-foreground">
                      No drawdown history available
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Audit Log Tab */}
          <TabsContent value="audit" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium">Risk Events</CardTitle>
                <CardDescription>Recent risk-related events and actions</CardDescription>
              </CardHeader>
              <CardContent>
                {riskEvents.length > 0 ? (
                  <div className="space-y-3">
                    {riskEvents.map((event: any, idx: number) => (
                      <div key={idx} className="flex items-start gap-3 py-3 border-b border-border/50 last:border-0">
                        <div className={cn(
                          "rounded-lg p-1.5 mt-0.5",
                          event.type === "info" && "bg-blue-500/10 text-blue-500",
                          event.type === "warning" && "bg-amber-500/10 text-amber-500",
                          event.type === "error" && "bg-red-500/10 text-red-500"
                        )}>
                          {event.type === "info" && <Info className="h-4 w-4" />}
                          {event.type === "warning" && <AlertTriangle className="h-4 w-4" />}
                          {event.type === "error" && <XCircle className="h-4 w-4" />}
                        </div>
                        <div className="flex-1">
                          <p className="text-sm">{event.message}</p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-muted-foreground">
                              {event.time || new Date(event.timestamp).toLocaleString()}
                            </span>
                            {event.symbol && (
                              <Badge variant="outline" className="text-[10px] px-1.5">
                                {event.symbol}
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-8 text-center text-muted-foreground">
                    No risk events recorded
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Settings Sheet */}
        <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
          <SheetContent className="w-full sm:max-w-md overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Risk Limits</SheetTitle>
              <SheetDescription>Configure your risk management parameters</SheetDescription>
            </SheetHeader>
            <div className="mt-6 space-y-6">
              {[
                { label: "Daily Loss Limit", value: dailyLossLimit.toString(), unit: "$" },
                { label: "Max Leverage", value: maxLeverage.toString(), unit: "x" },
                { label: "Max Concurrent Positions", value: maxPositions.toString(), unit: "" },
                { label: "Max Drawdown", value: maxDrawdownLimit.toString(), unit: "%" },
              ].map((field, idx) => (
                <div key={idx} className="space-y-2">
                  <Label>{field.label}</Label>
                  <div className="flex gap-2">
                    <Input 
                      type="number" 
                      defaultValue={field.value}
                      className="font-mono"
                    />
                    {field.unit && (
                      <div className="flex items-center px-3 border rounded-md bg-muted text-sm text-muted-foreground">
                        {field.unit}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <Separator />
              <Button className="w-full">Save Changes</Button>
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </TooltipProvider>
  );
}
