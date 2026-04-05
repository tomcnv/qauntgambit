import { useState, useMemo } from "react";
import {
  Zap,
  Clock,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Activity,
  Download,
  Loader2,
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
  CartesianGrid,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { cn } from "../../lib/utils";
import { TooltipProvider } from "../../components/ui/tooltip";
import { useExecutionStats, useTradeHistory } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { DashBar } from "../../components/DashBar";

export default function ExecutionPage() {
  const [timeRange, setTimeRange] = useState("24h");
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  
  // Fetch real execution data
  const { data: executionData, isLoading: loadingExecution } = useExecutionStats({
    exchangeAccountId: scopeLevel === 'exchange' ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel === 'bot' ? botId ?? undefined : undefined,
  });
  
  // Fetch trade history for detailed analysis
  const { data: tradeData, isLoading: loadingTrades } = useTradeHistory({
    limit: 500,
    exchangeAccountId: scopeLevel === 'exchange' ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel === 'bot' ? botId ?? undefined : undefined,
  });

  const isLoading = loadingExecution || loadingTrades;
  const trades = tradeData?.trades ?? [];
  const exec = executionData?.data ?? {};
  const quality = exec?.quality?.overall ?? exec?.quality?.recent ?? {};
  const fill = exec?.fill ?? {};

  // Extract metrics from API data
  const avgSlippage = quality?.avg_slippage_bps ?? fill?.avg_slippage_bps ?? 0;
  const avgLatency = quality?.avg_execution_time_ms ?? 0;
  const fillRate = quality?.fill_rate ?? fill?.fill_rate_pct ?? 100;
  const makerRatio = exec?.maker_ratio ?? null;
  const totalOrders = fill?.total_orders ?? trades.length ?? 0;
  const totalFills = fill?.total_fills ?? trades.length ?? 0;
  const totalRejects = fill?.total_rejects ?? 0;

  // Build hourly execution data from trades
  const hourlyExecution = useMemo(() => {
    const buckets: Record<string, { slippages: number[]; latencies: number[]; fills: number; total: number }> = {};
    
    // Initialize 24 hour buckets
    for (let i = 0; i < 24; i++) {
      const hour = `${i.toString().padStart(2, '0')}:00`;
      buckets[hour] = { slippages: [], latencies: [], fills: 0, total: 0 };
    }
    
    // Populate from trades
    trades.forEach((trade: any) => {
      const ts = trade.timestamp || trade.exit_time;
      if (!ts) return;
      const date = new Date(ts);
      const hour = `${date.getHours().toString().padStart(2, '0')}:00`;
      if (buckets[hour]) {
        if (trade.slippage_bps) buckets[hour].slippages.push(trade.slippage_bps);
        if (trade.latency_ms || trade.fill_time_ms) buckets[hour].latencies.push(trade.latency_ms || trade.fill_time_ms);
        buckets[hour].fills++;
        buckets[hour].total++;
      }
    });
    
    return Object.entries(buckets).map(([hour, data]) => ({
      hour,
      slippage: data.slippages.length > 0 ? data.slippages.reduce((a, b) => a + b, 0) / data.slippages.length : 0,
      latency: data.latencies.length > 0 ? data.latencies.reduce((a, b) => a + b, 0) / data.latencies.length : 0,
      fillRate: data.total > 0 ? (data.fills / data.total) * 100 : 100,
    }));
  }, [trades]);

  // Build slippage by symbol
  const slippageBySymbol = useMemo(() => {
    const symbolData: Record<string, { slippages: number[]; count: number }> = {};
    
    trades.forEach((trade: any) => {
      const symbol = trade.symbol || 'UNKNOWN';
      if (!symbolData[symbol]) {
        symbolData[symbol] = { slippages: [], count: 0 };
      }
      if (trade.slippage_bps) symbolData[symbol].slippages.push(trade.slippage_bps);
      symbolData[symbol].count++;
    });
    
    return Object.entries(symbolData)
      .map(([symbol, data]) => ({
        symbol,
        avgSlippage: data.slippages.length > 0 
          ? (data.slippages.reduce((a, b) => a + b, 0) / data.slippages.length).toFixed(2)
          : '0.00',
        maxSlippage: data.slippages.length > 0 
          ? Math.max(...data.slippages).toFixed(2)
          : '0.00',
        trades: data.count,
      }))
      .sort((a, b) => b.trades - a.trades)
      .slice(0, 10);
  }, [trades]);

  // Order type breakdown (based on side since we don't have order type info)
  const orderTypeBreakdown = useMemo(() => {
    const buyTrades = trades.filter((t: any) => t.side?.toLowerCase() === 'buy');
    const sellTrades = trades.filter((t: any) => t.side?.toLowerCase() === 'sell');
    
    const calcStats = (subset: any[]) => ({
      count: subset.length,
      fillRate: 100, // All trades are filled
      avgSlippage: subset.length > 0 && subset.some((t: any) => t.slippage_bps)
        ? (subset.filter((t: any) => t.slippage_bps).reduce((sum: number, t: any) => sum + t.slippage_bps, 0) / 
           subset.filter((t: any) => t.slippage_bps).length).toFixed(2)
        : '0.00',
    });
    
    return [
      { type: "BUY", ...calcStats(buyTrades) },
      { type: "SELL", ...calcStats(sellTrades) },
    ];
  }, [trades]);

  return (
    <TooltipProvider>
      <DashBar />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Execution Quality</h1>
            <p className="text-sm text-muted-foreground">
              Slippage, latency, and fill rate analysis
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            <div className="flex rounded-lg border bg-muted/50 p-1">
              {["24h", "7d", "30d"].map((range) => (
                <Button
                  key={range}
                  variant={timeRange === range ? "default" : "ghost"}
                  size="sm"
                  className="h-7 px-3 text-xs"
                  onClick={() => setTimeRange(range)}
                >
                  {range}
                </Button>
              ))}
            </div>
            <Button variant="outline" size="sm" className="gap-2">
              <Download className="h-4 w-4" />
              Export
            </Button>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Avg Slippage</span>
                <Zap className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                {typeof avgSlippage === 'number' ? avgSlippage.toFixed(2) : avgSlippage}
                <span className="text-sm font-normal text-muted-foreground"> bps</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {totalOrders} orders analyzed
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Avg Latency</span>
                <Clock className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                {typeof avgLatency === 'number' ? avgLatency.toFixed(1) : avgLatency}
                <span className="text-sm font-normal text-muted-foreground"> ms</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Round-trip time
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Fill Rate</span>
                <Activity className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                {typeof fillRate === 'number' ? fillRate.toFixed(1) : fillRate}
                <span className="text-sm font-normal text-muted-foreground">%</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {totalFills} / {totalOrders} filled
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Maker Ratio</span>
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
              </div>
              {makerRatio !== null ? (
                <p className="text-2xl font-bold">
                  {makerRatio.toFixed(0)}
                  <span className="text-sm font-normal text-muted-foreground">%</span>
                </p>
              ) : (
                <p className="text-2xl font-bold text-muted-foreground">N/A</p>
              )}
              <p className="text-xs text-muted-foreground mt-1">
                {makerRatio !== null 
                  ? (totalRejects > 0 ? `${totalRejects} rejects` : 'No rejects')
                  : 'Not available from exchange'}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Charts */}
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Slippage Over Time</CardTitle>
              <CardDescription>Hourly average slippage in basis points</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[250px]">
                {hourlyExecution.some(d => d.slippage > 0) ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={hourlyExecution} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                      <defs>
                        <linearGradient id="slippageGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                      <XAxis 
                        dataKey="hour" 
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: '#64748b' }}
                        interval={3}
                      />
                      <YAxis 
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: '#64748b' }}
                        tickFormatter={(v) => `${v.toFixed(1)}bps`}
                        width={50}
                      />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: '8px',
                          fontSize: '12px',
                        }}
                        formatter={(value: number) => [`${value.toFixed(2)} bps`, 'Slippage']}
                      />
                      <Area
                        type="monotone"
                        dataKey="slippage"
                        stroke="#f59e0b"
                        strokeWidth={2}
                        fill="url(#slippageGradient)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted-foreground">
                    No slippage data available
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Latency Distribution</CardTitle>
              <CardDescription>Round-trip order latency in milliseconds</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[250px]">
                {hourlyExecution.some(d => d.latency > 0) ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={hourlyExecution} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                      <XAxis 
                        dataKey="hour" 
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: '#64748b' }}
                        interval={3}
                      />
                      <YAxis 
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: '#64748b' }}
                        tickFormatter={(v) => `${v.toFixed(0)}ms`}
                        width={45}
                      />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: '8px',
                          fontSize: '12px',
                        }}
                        formatter={(value: number) => [`${value.toFixed(0)} ms`, 'Latency']}
                      />
                      <Line
                        type="monotone"
                        dataKey="latency"
                        stroke="#8b5cf6"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted-foreground">
                    No latency data available
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Tables */}
        <div className="grid gap-4 lg:grid-cols-2">
          {/* Slippage by Symbol */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Slippage by Symbol</CardTitle>
              <CardDescription>Average and max slippage per trading pair</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                {slippageBySymbol.length > 0 ? (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50">
                        <th className="text-left font-medium text-muted-foreground py-2">Symbol</th>
                        <th className="text-right font-medium text-muted-foreground py-2">Avg</th>
                        <th className="text-right font-medium text-muted-foreground py-2">Max</th>
                        <th className="text-right font-medium text-muted-foreground py-2">Trades</th>
                      </tr>
                    </thead>
                    <tbody>
                      {slippageBySymbol.map((row) => (
                        <tr key={row.symbol} className="border-b border-border/30 last:border-0">
                          <td className="py-3 font-medium">{row.symbol}</td>
                          <td className="py-3 text-right font-mono">{row.avgSlippage} bps</td>
                          <td className="py-3 text-right font-mono text-amber-500">{row.maxSlippage} bps</td>
                          <td className="py-3 text-right font-mono text-muted-foreground">{row.trades}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="py-8 text-center text-muted-foreground">
                    No symbol data available
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Order Types */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Order Side Analysis</CardTitle>
              <CardDescription>Fill rates and slippage by order side</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                {orderTypeBreakdown.some(r => r.count > 0) ? (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50">
                        <th className="text-left font-medium text-muted-foreground py-2">Side</th>
                        <th className="text-right font-medium text-muted-foreground py-2">Count</th>
                        <th className="text-right font-medium text-muted-foreground py-2">Fill Rate</th>
                        <th className="text-right font-medium text-muted-foreground py-2">Slippage</th>
                      </tr>
                    </thead>
                    <tbody>
                      {orderTypeBreakdown.map((row) => (
                        <tr key={row.type} className="border-b border-border/30 last:border-0">
                          <td className="py-3">
                            <Badge 
                              variant="outline" 
                              className={cn(
                                "text-xs",
                                row.type === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                              )}
                            >
                              {row.type}
                            </Badge>
                          </td>
                          <td className="py-3 text-right font-mono">{row.count}</td>
                          <td className="py-3 text-right font-mono">
                            <span className={cn(
                              row.fillRate >= 95 ? "text-emerald-500" : 
                              row.fillRate >= 80 ? "text-amber-500" : "text-red-500"
                            )}>
                              {row.fillRate}%
                            </span>
                          </td>
                          <td className="py-3 text-right font-mono">{row.avgSlippage} bps</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="py-8 text-center text-muted-foreground">
                    No trade data available
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </TooltipProvider>
  );
}
