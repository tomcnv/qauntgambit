import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  Settings,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Clock,
  Target,
  Shield,
  Zap,
  RefreshCw,
  Pause,
  Play,
  Square,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  BarChart3,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Separator } from "../../components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import {
  useOverviewData,
  useTradeProfile,
  useBotPositions,
  usePendingOrders,
  useTradingOpsData,
} from "../../lib/api/hooks";
import { useWebSocketContext } from "../../lib/websocket/WebSocketProvider";
import { useScopeStore } from "../../store/scope-store";

export default function ActiveBotPage() {
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  const scopedExchangeAccountId = scopeLevel !== "fleet" ? exchangeAccountId || undefined : undefined;
  const scopedBotId = scopeLevel === "bot" ? botId || undefined : undefined;
  const { data: overviewData } = useOverviewData({
    exchangeAccountId: scopeLevel !== "fleet" ? exchangeAccountId || null : null,
    botId: scopeLevel === "bot" ? botId || null : null,
  });
  const { data: opsData } = useTradingOpsData({
    exchangeAccountId: scopedExchangeAccountId,
    botId: scopedBotId,
  });
  const { data: tradeProfile } = useTradeProfile();
  const { data: positionsResp } = useBotPositions({
    exchangeAccountId: scopedExchangeAccountId,
    botId: scopedBotId,
  });
  const { data: pendingOrdersResp } = usePendingOrders({
    exchangeAccountId: scopedExchangeAccountId ?? null,
    botId: scopedBotId ?? null,
  });
  const { isConnected: wsConnected } = useWebSocketContext();

  const botStatus = overviewData?.botStatus as any;
  const fastScalper = overviewData?.fastScalper as any;
  const tradingInfo = botStatus?.trading as any;
  const metrics = tradingInfo?.metrics ?? opsData?.trading?.metrics ?? fastScalper?.metrics ?? {};
  
  const isTradingActive = tradingInfo?.isActive ?? false;
  const platformStatus = botStatus?.platform?.status ?? fastScalper?.status ?? "offline";

  const rawPositions = Array.isArray(positionsResp?.positions)
    ? positionsResp.positions
    : Array.isArray((positionsResp as any)?.data)
      ? (positionsResp as any).data
      : [];

  const positions = rawPositions.map((p: any) => ({
        symbol: p.symbol || p.ticker || "UNKNOWN",
        side: (p.side || p.direction || "").toString().toUpperCase(),
        size: Number(p.size || p.qty || 0),
        entryPrice: Number(p.entry_price || p.entryPrice || p.avg_entry_price || p.price || 0),
        currentPrice: Number(p.mark_price || p.current_price || p.last || p.price || 0),
        pnl: Number(p.unrealized_pnl || p.pnl || 0),
        margin: Number(p.margin || p.margin_used || 0),
      }));

  const pendingOrders = Array.isArray(pendingOrdersResp?.orders) ? pendingOrdersResp.orders : [];

  const strategies = Array.isArray(opsData?.trading?.strategies)
    ? opsData.trading.strategies
    : Array.isArray(fastScalper?.strategies)
      ? fastScalper.strategies
      : [];

  const exposureData = positions.map((p) => ({
    name: p.symbol,
    value: Math.abs(p.size * p.currentPrice),
    color: "#22c55e",
  }));
  const totalPnl = positions.reduce((acc, p) => acc + (p.pnl || 0), 0);
  const netExposure = positions.reduce((acc, p) => acc + Math.abs(p.size * p.currentPrice), 0);

  return (
    <TooltipProvider>
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Active Bot Details</h1>
            <p className="text-sm text-muted-foreground">
              Deep dive into current trading engine telemetry and configuration
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link to="/bot-management">
              <Button variant="outline" size="sm" className="gap-2">
                <Settings className="h-4 w-4" />
                Configure
              </Button>
            </Link>
          </div>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="positions" className="space-y-4">
          <TabsList className="bg-muted/50">
            <TabsTrigger value="positions" className="gap-2">
              <Target className="h-4 w-4" />
              Positions
            </TabsTrigger>
            <TabsTrigger value="strategies" className="gap-2">
              <Layers className="h-4 w-4" />
              Strategies
            </TabsTrigger>
            <TabsTrigger value="exposure" className="gap-2">
              <BarChart3 className="h-4 w-4" />
              Exposure
            </TabsTrigger>
            <TabsTrigger value="orders" className="gap-2">
              <Activity className="h-4 w-4" />
              Open Orders
            </TabsTrigger>
          </TabsList>

          {/* Positions Tab */}
          <TabsContent value="positions" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base font-medium">Open Positions</CardTitle>
                    <CardDescription>Currently held positions across all symbols</CardDescription>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <div>
                      <span className="text-muted-foreground">Net Exposure: </span>
                      <span className="font-mono font-medium">
                        ${netExposure.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Total PnL: </span>
                      <span
                        className={cn(
                          "font-mono font-medium",
                          totalPnl >= 0 ? "text-emerald-500" : "text-red-500"
                        )}
                      >
                        {totalPnl >= 0 ? "+" : ""}
                        ${totalPnl.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50">
                        <th className="text-left font-medium text-muted-foreground py-3 pr-4">Symbol</th>
                        <th className="text-left font-medium text-muted-foreground py-3 pr-4">Side</th>
                        <th className="text-right font-medium text-muted-foreground py-3 pr-4">Size</th>
                        <th className="text-right font-medium text-muted-foreground py-3 pr-4">Entry</th>
                        <th className="text-right font-medium text-muted-foreground py-3 pr-4">Current</th>
                        <th className="text-right font-medium text-muted-foreground py-3 pr-4">PnL</th>
                        <th className="text-right font-medium text-muted-foreground py-3 pr-4">Margin</th>
                        <th className="text-right font-medium text-muted-foreground py-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map((pos) => (
                        <tr key={pos.symbol} className="border-b border-border/30 last:border-0 hover:bg-muted/30">
                          <td className="py-3 pr-4">
                            <span className="font-medium">{pos.symbol}</span>
                          </td>
                          <td className="py-3 pr-4">
                            <Badge 
                              variant="outline" 
                              className={cn(
                                "text-xs",
                                pos.side === "LONG" 
                                  ? "border-emerald-500/50 text-emerald-500" 
                                  : "border-red-500/50 text-red-500"
                              )}
                            >
                              {pos.side}
                            </Badge>
                          </td>
                          <td className="py-3 pr-4 text-right font-mono">{pos.size}</td>
                          <td className="py-3 pr-4 text-right font-mono">${pos.entryPrice.toLocaleString()}</td>
                          <td className="py-3 pr-4 text-right font-mono">${pos.currentPrice.toLocaleString()}</td>
                          <td className={cn(
                            "py-3 pr-4 text-right font-mono font-medium",
                            pos.pnl >= 0 ? "text-emerald-500" : "text-red-500"
                          )}>
                            {pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
                          </td>
                          <td className="py-3 pr-4 text-right font-mono text-muted-foreground">
                            ${pos.margin.toFixed(2)}
                          </td>
                          <td className="py-3 text-right">
                            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-red-500">
                              Close
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Strategies Tab */}
          <TabsContent value="strategies" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-3">
              {strategies.map((strat: { id?: string; name: string; status: string; pnl?: number; trades?: number; winRate?: number; avgSlippage?: number }) => (
                <Card key={strat.name} className={cn(
                  "relative overflow-hidden",
                  strat.status === "paused" && "opacity-60"
                )}>
                  <CardContent className="p-5">
                    <div className="flex items-start justify-between mb-4">
                      <div>
                        <h3 className="font-medium">{strat.name}</h3>
                        <p className="text-xs text-muted-foreground">{strat.trades} trades today</p>
                      </div>
                      <Badge 
                        variant="outline" 
                        className={cn(
                          "text-xs",
                          strat.status === "active" 
                            ? "border-emerald-500/50 text-emerald-500" 
                            : "border-amber-500/50 text-amber-500"
                        )}
                      >
                        {strat.status.toUpperCase()}
                      </Badge>
                    </div>

                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-sm text-muted-foreground">PnL</span>
                        <span className={cn(
                          "font-mono font-medium",
                          (strat.pnl ?? 0) >= 0 ? "text-emerald-500" : "text-red-500"
                        )}>
                          {(strat.pnl ?? 0) >= 0 ? "+" : ""}${(strat.pnl ?? 0).toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-sm text-muted-foreground">Win Rate</span>
                        <span className="font-mono">{strat.winRate}%</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-sm text-muted-foreground">Avg Slippage</span>
                        <span className="font-mono">{strat.avgSlippage ?? 0}bps</span>
                      </div>
                    </div>

                    <Separator className="my-4" />

                    <div className="flex gap-2">
                      {strat.status === "active" ? (
                        <Button variant="outline" size="sm" className="flex-1 gap-1">
                          <Pause className="h-3 w-3" />
                          Pause
                        </Button>
                      ) : (
                        <Button variant="outline" size="sm" className="flex-1 gap-1">
                          <Play className="h-3 w-3" />
                          Resume
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" className="gap-1">
                        <Settings className="h-3 w-3" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* Exposure Tab */}
          <TabsContent value="exposure" className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base font-medium">Exposure by Symbol</CardTitle>
                  <CardDescription>Net exposure distribution</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[300px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={exposureData}
                          cx="50%"
                          cy="50%"
                          innerRadius={60}
                          outerRadius={100}
                          paddingAngle={5}
                          dataKey="value"
                        >
                          {exposureData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <RechartsTooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--card))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                          }}
                          formatter={(value: number) => [`${value}%`, 'Exposure']}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex justify-center gap-6 mt-4">
                    {exposureData.map((item) => (
                      <div key={item.name} className="flex items-center gap-2">
                        <span 
                          className="h-3 w-3 rounded-full" 
                          style={{ backgroundColor: item.color }}
                        />
                        <span className="text-sm">{item.name}</span>
                        <span className="text-sm text-muted-foreground">{item.value}%</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base font-medium">Risk Metrics</CardTitle>
                  <CardDescription>Current risk exposure and limits</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Margin Used</span>
                      <span className="font-mono">$2,898.30 / $10,000</span>
                    </div>
                    <Progress value={29} className="h-2" />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Daily Loss Limit</span>
                      <span className="font-mono">$42.50 / $500</span>
                    </div>
                    <Progress value={8.5} className="h-2" />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Max Positions</span>
                      <span className="font-mono">3 / 5</span>
                    </div>
                    <Progress value={60} className="h-2" />
                  </div>

                  <Separator />

                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-muted-foreground">Leverage</p>
                      <p className="text-lg font-mono font-medium">2.9x</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Liq. Distance</p>
                      <p className="text-lg font-mono font-medium text-emerald-500">34.2%</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* Open Orders Tab */}
          <TabsContent value="orders" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base font-medium">Open Orders</CardTitle>
                    <CardDescription>Pending limit and stop orders</CardDescription>
                  </div>
                  <Button variant="outline" size="sm" className="gap-2 text-red-500">
                    <XCircle className="h-4 w-4" />
                    Cancel All
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <CheckCircle2 className="h-10 w-10 mb-3 opacity-50" />
                  <p className="text-sm font-medium">No open orders</p>
                  <p className="text-xs">All orders have been filled or cancelled</p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </TooltipProvider>
  );
}
