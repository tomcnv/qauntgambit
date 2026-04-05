import { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ListOrdered,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Filter,
  TrendingUp,
  TrendingDown,
  Zap,
  Target,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Checkbox } from "../../components/ui/checkbox";
import { cn, formatQuantity } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { useOverviewData, usePendingOrders, useExecutionStats, useCancelOrder, useReplaceOrder, useTradeHistory } from "../../lib/api/hooks";
import toast from "react-hot-toast";
import { useScopeStore } from "../../store/scope-store";
import { TradeInspectorDrawer } from "../../components/trade-history/TradeInspectorDrawer";
import { RunBar } from "../../components/run-bar";

export default function OrdersPage() {
  // Scope management
  const { level: scopeLevel, exchangeAccountId, exchangeAccountName, botId, botName } = useScopeStore();
  
  // Parse exchange from name like "Test Account (BINANCE)"
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

  const { data: overviewData } = useOverviewData({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId : null,
    botId: scopeLevel === 'bot' ? botId : null,
  });
  const queryClient = useQueryClient();
  // Pass scope params to APIs
  const { data: pendingOrdersData, isLoading: loadingOrders } = usePendingOrders({
    exchangeAccountId: exchangeAccountId || undefined,
    botId: botId || undefined,
  });
  const { data: tradeHistoryData, isLoading: loadingHistory } = useTradeHistory({ 
    limit: 50, 
    includeAll: true,
    showEntries: true,
    status: "filled,closed",
    exchangeAccountId: exchangeAccountId || undefined,
    botId: botId || undefined 
  });
  const { data: executionStats } = useExecutionStats({ 
    exchangeAccountId: exchangeAccountId || undefined, 
    botId: botId || undefined 
  });
  const cancelOrderMutation = useCancelOrder();
  const replaceOrderMutation = useReplaceOrder();
  const [replaceDraft, setReplaceDraft] = useState<any | null>(null);
  const [replacePrice, setReplacePrice] = useState<string>("");
  const [replaceSize, setReplaceSize] = useState<string>("");
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<any | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState({
    symbols: [] as string[],
    side: "",
    status: "",
  });
  
  // Check if we're viewing a filled trade (not pending order)
  const isViewingFilledTrade = selectedOrder && !selectedOrder.isPending;
  
  const metrics = (overviewData?.fastScalper as any)?.metrics ?? {};
  const execData = executionStats?.data ?? executionStats ?? {};

  // Try multiple data paths for execution stats
  // Prefer quality.overall (actual order tracking) over fill (often empty)
  const fillRate = metrics?.fillRate 
    ?? execData?.quality?.overall?.fill_rate 
    ?? execData?.quality?.recent?.fill_rate
    ?? (execData?.fill?.fill_rate_pct > 0 ? execData.fill.fill_rate_pct : 0);
  const cancelRate = metrics?.cancelRate 
    ?? (execData?.fill?.total_cancels && execData?.fill?.total_orders 
        ? (execData.fill.total_cancels / execData.fill.total_orders * 100) 
        : 0);
  const rejectRate = metrics?.rejectRate 
    ?? execData?.quality?.overall?.rejection_rate 
    ?? (execData?.fill?.total_rejects && execData?.fill?.total_orders 
        ? (execData.fill.total_rejects / execData.fill.total_orders * 100) 
        : 0);
  const avgLatency = metrics?.avgLatency 
    ?? execData?.quality?.overall?.avg_execution_time_ms 
    ?? execData?.quality?.recent?.avg_execution_time_ms 
    ?? 0;
  const makerRatio = metrics?.makerRatio ?? execData?.maker_ratio ?? null;

  const handleCancel = (order: any) => {
    setCancelingId(order.id);
    cancelOrderMutation.mutate(
      { orderId: order.id, symbol: order.symbol },
      {
        onSuccess: () => toast.success("Cancel sent"),
        onError: (err: any) => toast.error(err?.message || "Cancel failed"),
        onSettled: () => setCancelingId(null),
      }
    );
  };

  const openReplace = (order: any) => {
    setReplaceDraft(order);
    setReplacePrice(order.price ? String(order.price) : "");
    setReplaceSize(order.size ? String(order.size) : "");
  };

  const submitReplace = () => {
    if (!replaceDraft) return;
    if (!replacePrice && !replaceSize) {
      toast.error("Enter a new price or size");
      return;
    }
    setReplacingId(replaceDraft.id);
    replaceOrderMutation.mutate(
      {
        orderId: replaceDraft.id,
        symbol: replaceDraft.symbol,
        newPrice: replacePrice ? Number(replacePrice) : undefined,
        newSize: replaceSize ? Number(replaceSize) : undefined,
      },
      {
        onSuccess: () => {
          toast.success("Replace sent");
          setReplaceDraft(null);
        },
        onError: (err: any) => toast.error(err?.message || "Replace failed"),
        onSettled: () => setReplacingId(null),
      }
    );
  };

  // Combine pending orders with recent filled orders from trade history
  const scopedPendingOrders = (pendingOrdersData?.orders ?? []).filter((o: any) => {
    if (scopeLevel !== "fleet" && exchangeAccountId) {
      return o.exchange_account_id === exchangeAccountId || !o.exchange_account_id;
    }
    if (scopeLevel === "bot" && botId) {
      return o.bot_id === botId || !o.bot_id;
    }
    return true;
  });

  const pendingOrders = scopedPendingOrders.map((o: any, idx: number) => ({
    id: o.id || o.order_id || `pending-${idx}`,
    time: o.timestamp
      ? new Date(o.timestamp).toLocaleTimeString(undefined, { hour12: false })
      : o.time || "",
    timestamp: o.timestamp || Date.now(),
    symbol: o.symbol,
    side: o.side?.toUpperCase(),
    type: o.type || o.order_type || "LIMIT",
    size: o.size || o.qty || o.quantity,
    price: o.price,
    status: o.status || "NEW",
    fillTime: o.fill_time_ms ? `${o.fill_time_ms}ms` : o.fillTime || "-",
    slippage: o.slippage_bps ?? o.slippage ?? 0,
    isPending: true,
    exchange_account_id: o.exchange_account_id,
    bot_id: o.bot_id,
  }));

  const filledOrders = (tradeHistoryData?.trades ?? []).slice(0, 50).map((t: any, idx: number) => ({
    id: t.id || `filled-${idx}`,
    time: t.formattedTimestamp
      ? new Date(t.formattedTimestamp).toLocaleTimeString(undefined, { hour12: false })
      : t.timestamp
      ? new Date(t.timestamp).toLocaleTimeString(undefined, { hour12: false })
      : "",
    timestamp: t.timestamp || 0,
    symbol: t.symbol,
    side: t.side?.toUpperCase(),
    type: "MARKET",
    size: t.size || t.quantity,
    price: t.exit_price || t.entry_price || t.price,
    status: "FILLED",
    fillTime: t.fill_time_ms ? `${t.fill_time_ms.toFixed(0)}ms` : t.latency_ms ? `${t.latency_ms.toFixed(0)}ms` : "-",
    slippage: t.slippage_bps ?? 0,
    isPending: false,
    pnl: t.pnl,
    fees: t.fees,
    exchange_account_id: t.exchange_account_id,
    bot_id: t.bot_id,
    // Include full trade data for detail view
    entry_price: t.entry_price,
    exit_price: t.exit_price,
    entry_time: t.entry_time,
    strategy: t.strategy || t.strategy_id,
    profile: t.profile || t.profile_id,
    exitReason: t.exitReason || t.reason,
    holdingDuration: t.holdingDuration,
    pnlPercent: t.pnlPercent,
    latency_ms: t.latency_ms,
    slippage_bps: t.slippage_bps,
  }));

  // Build symbol options from data
  const availableSymbols = useMemo(() => {
    const set = new Set<string>();
    [...pendingOrders, ...filledOrders].forEach((o) => {
      if (o.symbol) set.add(o.symbol.toUpperCase());
    });
    return Array.from(set).sort();
  }, [pendingOrders, filledOrders]);

  // Apply UI filters (symbols/side/status)
  const filteredOrders = [...pendingOrders, ...filledOrders].filter((o) => {
    const sym = o.symbol?.toUpperCase();
    if (filters.symbols.length > 0 && (!sym || !filters.symbols.includes(sym))) return false;
    if (filters.side && o.side !== filters.side) return false;
    if (filters.status && o.status !== filters.status) return false;
    return true;
  });

  // Combine and sort by timestamp (most recent first)
  const orders = filteredOrders
    .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
    .slice(0, 100);

  const execHistoryData = executionStats?.data ?? executionStats ?? {};
  const latencyData = (execHistoryData?.latency_history || []).map((row: any) => ({
    hour: row.bucket || row.hour || "",
    p50: row.p50 || row.p50_ms || 0,
    p95: row.p95 || row.p95_ms || 0,
    p99: row.p99 || row.p99_ms || 0,
  }));

  const fillRateData = (execHistoryData?.fill_rate_history || []).map((row: any) => ({
    hour: row.bucket || row.hour || "",
    filled: row.filled ?? 0,
    partial: row.partial ?? 0,
    cancelled: row.cancelled ?? 0,
    rejected: row.rejected ?? 0,
  }));

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["pending-orders"] });
    queryClient.invalidateQueries({ queryKey: ["trade-history"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-execution"] });
    queryClient.invalidateQueries({ queryKey: ["overview"] });
  };

  return (
    <TooltipProvider>
      {/* Sticky Run Bar */}
      <RunBar />
      
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Orders & Fills</h1>
            <p className="text-sm text-muted-foreground">
              Real-time order flow, fill rates, and execution latency
            </p>
          </div>
          <div className="flex items-center gap-2 relative">
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              aria-label="Filters"
              onClick={() => setFiltersOpen((o) => !o)}
            >
              <Filter className="h-4 w-4" />
            </Button>
            {filtersOpen && (
              <div className="absolute right-0 top-12 w-80 rounded-lg border bg-background shadow-xl z-50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">Filters</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2"
                    onClick={() => setFilters({ symbols: [], side: "", status: "" })}
                  >
                    Clear
                  </Button>
                </div>
                <div className="space-y-2">
                  <Label>Symbols</Label>
                  <div className="grid grid-cols-2 gap-2 max-h-40 overflow-auto pr-1">
                    {availableSymbols.length === 0 && (
                      <p className="text-xs text-muted-foreground col-span-2">No symbols yet</p>
                    )}
                    {availableSymbols.map((sym) => (
                      <label key={sym} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={filters.symbols.includes(sym)}
                          onCheckedChange={() =>
                            setFilters((f) => {
                              const exists = f.symbols.includes(sym);
                              const symbols = exists ? f.symbols.filter((s) => s !== sym) : [...f.symbols, sym];
                              return { ...f, symbols };
                            })
                          }
                        />
                        <span className="font-mono">{sym}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Side</Label>
                  <Select
                    value={filters.side}
                    onValueChange={(v) => setFilters((f) => ({ ...f, side: v ? v.toUpperCase() : "" }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="All" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">All</SelectItem>
                      <SelectItem value="BUY">Buy</SelectItem>
                      <SelectItem value="SELL">Sell</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Status</Label>
                  <Select
                    value={filters.status}
                    onValueChange={(v) => setFilters((f) => ({ ...f, status: v }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="All" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">All</SelectItem>
                      <SelectItem value="NEW">Open</SelectItem>
                      <SelectItem value="PENDING_CANCEL">Pending Cancel</SelectItem>
                      <SelectItem value="FILLED">Filled</SelectItem>
                      <SelectItem value="CANCELED">Canceled</SelectItem>
                      <SelectItem value="REJECTED">Rejected</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}
            <Button variant="outline" size="sm" className="gap-2" onClick={handleRefresh}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Fill Rate</span>
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              </div>
              <p className="text-2xl font-bold">{fillRate.toFixed(1)}%</p>
              <Progress value={fillRate} className="h-1.5 mt-2" />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Cancel Rate</span>
                <XCircle className="h-4 w-4 text-amber-500" />
              </div>
              <p className="text-2xl font-bold">{cancelRate.toFixed(1)}%</p>
              <Progress value={cancelRate} className="h-1.5 mt-2 [&>div]:bg-amber-500" />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Reject Rate</span>
                <AlertTriangle className="h-4 w-4 text-red-500" />
              </div>
              <p className="text-2xl font-bold">{rejectRate.toFixed(1)}%</p>
              <Progress value={rejectRate * 10} className="h-1.5 mt-2 [&>div]:bg-red-500" />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Avg Latency</span>
                <Clock className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">{typeof avgLatency === 'number' ? avgLatency.toFixed(1) : avgLatency}<span className="text-sm font-normal text-muted-foreground">ms</span></p>
              <p className="text-xs text-muted-foreground mt-1">Round-trip time</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Maker Ratio</span>
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
              </div>
              {makerRatio !== null ? (
                <>
                  <p className="text-2xl font-bold">{makerRatio}%</p>
                  <div className="flex h-1.5 rounded-full overflow-hidden bg-muted mt-2">
                    <div className="bg-emerald-500" style={{ width: `${makerRatio}%` }} />
                    <div className="bg-amber-500" style={{ width: `${100 - makerRatio}%` }} />
                  </div>
                </>
              ) : (
                <>
                  <p className="text-2xl font-bold text-muted-foreground">N/A</p>
                  <p className="text-xs text-muted-foreground mt-1">Not available from exchange</p>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Charts */}
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Latency Distribution</CardTitle>
              <CardDescription>P50, P95, P99 latency over 24 hours</CardDescription>
            </CardHeader>
            <CardContent>
              {latencyData.length === 0 ? (
                <div className="h-[250px] flex items-center justify-center text-muted-foreground text-sm">
                  <div className="text-center">
                    <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No latency data yet</p>
                    <p className="text-xs mt-1">Charts will populate as orders are filled</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="h-[250px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={latencyData} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                        <defs>
                          <linearGradient id="p50Gradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                        <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} interval="preserveStartEnd" />
                        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(v) => `${v}ms`} width={50} />
                        <RechartsTooltip
                          contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                          formatter={(value: any) => [`${value}ms`, '']}
                        />
                        <Area type="monotone" dataKey="p50" stroke="#10b981" strokeWidth={2} fill="url(#p50Gradient)" name="P50" />
                        <Area type="monotone" dataKey="p95" stroke="#f59e0b" strokeWidth={1.5} fill="none" name="P95" />
                        <Area type="monotone" dataKey="p99" stroke="#ef4444" strokeWidth={1} fill="none" name="P99" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex justify-center gap-6 mt-2">
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-emerald-500" />P50</span>
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-amber-500" />P95</span>
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-red-500" />P99</span>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Fill Rate Breakdown</CardTitle>
              <CardDescription>Order outcomes over time</CardDescription>
            </CardHeader>
            <CardContent>
              {fillRateData.length === 0 ? (
                <div className="h-[250px] flex items-center justify-center text-muted-foreground text-sm">
                  <div className="text-center">
                    <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No fill data yet</p>
                    <p className="text-xs mt-1">Charts will populate as orders are placed</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="h-[250px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={fillRateData} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                        <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} interval="preserveStartEnd" />
                        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} width={40} />
                        <RechartsTooltip
                          contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                        />
                        <Bar dataKey="filled" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} name="Filled" />
                        <Bar dataKey="partial" stackId="a" fill="#3b82f6" name="Partial" />
                        <Bar dataKey="cancelled" stackId="a" fill="#f59e0b" name="Cancelled" />
                        <Bar dataKey="rejected" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} name="Rejected" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex justify-center gap-6 mt-2">
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-emerald-500" />Filled</span>
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-blue-500" />Partial</span>
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-amber-500" />Cancelled</span>
                    <span className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full bg-red-500" />Rejected</span>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Order Table */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-medium">Recent Orders</CardTitle>
                <CardDescription>Pending and recently filled orders · Click any order for details</CardDescription>
              </div>
              <Badge variant="outline" className="text-xs">
                {pendingOrders.length} pending, {filledOrders.length} filled
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Time</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Side</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-4">Size</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-4">Price</th>
                    <th className="text-center font-medium text-muted-foreground py-2 pr-4">Status</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-4">Fill Time</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-4">Slippage</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-4">P&L</th>
                    <th className="text-center font-medium text-muted-foreground py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(orders.length ? orders : []).map((order) => (
                    <tr 
                      key={order.id} 
                      className="border-b border-border/30 last:border-0 hover:bg-muted/30 cursor-pointer"
                      onClick={() => setSelectedOrder(order)}
                    >
                      <td className="py-2.5 pr-4 font-mono text-xs text-muted-foreground">{order.time}</td>
                      <td className="py-2.5 pr-4 font-medium">{order.symbol}</td>
                      <td className="py-2.5 pr-4">
                        <Badge variant="outline" className={cn(
                          "text-[10px] px-1.5",
                          order.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                        )}>
                          {order.side}
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-4 text-right font-mono">{formatQuantity(order.size)}</td>
                      <td className="py-2.5 pr-4 text-right font-mono">
                        {order.price ? `$${order.price.toLocaleString()}` : "MKT"}
                      </td>
                      <td className="py-2.5 pr-4 text-center">
                        <Badge className={cn(
                          "text-[10px] px-1.5",
                          order.status === "FILLED" && "bg-emerald-500/10 text-emerald-500 border-emerald-500/30",
                          order.status === "NEW" && "bg-blue-500/10 text-blue-500 border-blue-500/30",
                          order.status === "PARTIAL" && "bg-blue-500/10 text-blue-500 border-blue-500/30",
                          order.status === "CANCELLED" && "bg-amber-500/10 text-amber-500 border-amber-500/30",
                          order.status === "REJECTED" && "bg-red-500/10 text-red-500 border-red-500/30"
                        )}>
                          {order.status}
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-4 text-right font-mono text-muted-foreground">{order.fillTime}</td>
                      <td className={cn(
                        "py-2.5 pr-4 text-right font-mono",
                        order.slippage > 2 ? "text-amber-500" : "text-muted-foreground"
                      )}>
                        {order.slippage > 0 ? `${order.slippage.toFixed(1)}bps` : "-"}
                      </td>
                      <td className="py-2.5 pr-4 text-right font-mono">
                        {!order.isPending && order.pnl !== undefined && order.pnl !== null ? (
                          <span className={order.pnl >= 0 ? "text-emerald-500" : "text-red-500"}>
                            {order.pnl >= 0 ? "+" : ""}${order.pnl?.toFixed(2)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2.5 text-center">
                        {order.isPending ? (
                          <div className="flex gap-1 justify-center">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              onClick={(e) => { e.stopPropagation(); handleCancel(order); }}
                              disabled={cancelingId === order.id}
                            >
                              {cancelingId === order.id ? "..." : "Cancel"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              onClick={(e) => { e.stopPropagation(); openReplace(order); }}
                              disabled={replacingId === order.id}
                            >
                              {replacingId === order.id ? "..." : "Edit"}
                            </Button>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!orders.length && !loadingOrders && (
                    <tr>
                      <td colSpan={10} className="py-8 text-center text-muted-foreground">No orders found</td>
                    </tr>
                  )}
                  {loadingOrders && (
                    <tr>
                      <td colSpan={10} className="py-8 text-center text-muted-foreground">Loading orders…</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
        
        {/* Unified Trade Detail Drawer (for filled orders/trades) */}
        {isViewingFilledTrade && (
          <TradeInspectorDrawer
            open={!!selectedOrder && !selectedOrder.isPending}
            onOpenChange={(open) => !open && setSelectedOrder(null)}
            trade={selectedOrder ? {
              id: selectedOrder.id,
              symbol: selectedOrder.symbol,
              side: selectedOrder.side,
              timestamp: selectedOrder.timestamp,
              quantity: selectedOrder.size,
              entryPrice: selectedOrder.entry_price || selectedOrder.price,
              exitPrice: selectedOrder.exit_price || selectedOrder.price,
              entryTime: selectedOrder.entry_time,
              pnl: selectedOrder.pnl,
              fees: selectedOrder.fees,
              strategy: selectedOrder.strategy,
              profile: selectedOrder.profile,
              latency: selectedOrder.latency_ms,
              slippage: selectedOrder.slippage_bps || selectedOrder.slippage,
              exitReason: selectedOrder.exitReason || selectedOrder.reason,
              holdTimeSeconds: selectedOrder.holdingDuration ? selectedOrder.holdingDuration / 1000 : undefined,
              pnlPercent: selectedOrder.pnlPercent,
            } : null}
          />
        )}
        
        {/* Pending Order Detail Sheet */}
        <Sheet open={!!selectedOrder && selectedOrder.isPending} onOpenChange={() => setSelectedOrder(null)}>
          <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
            {selectedOrder && selectedOrder.isPending && (
              <>
                <SheetHeader>
                  <SheetTitle className="flex items-center gap-3">
                    <span className="text-xl">{selectedOrder.symbol}</span>
                    <Badge 
                      variant="outline" 
                      className={cn(
                        "text-xs uppercase",
                        selectedOrder.side === "BUY"
                          ? "border-emerald-500/50 text-emerald-500" 
                          : "border-red-500/50 text-red-500"
                      )}
                    >
                      {selectedOrder.side}
                    </Badge>
                    <Badge variant="outline" className="text-xs">{selectedOrder.status}</Badge>
                  </SheetTitle>
                  <SheetDescription>
                    {selectedOrder.time || selectedOrder.formattedTimestamp || "—"}
                  </SheetDescription>
                </SheetHeader>
                
                <div className="mt-6 space-y-6">
                  {/* Order Details Grid (for pending orders) */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="rounded-lg border border-border bg-muted/50 p-4">
                      <p className="text-xs text-muted-foreground">Type</p>
                      {(() => {
                        const orderType = (selectedOrder.type || '').toUpperCase();
                        const isProtection = ['STOP', 'TAKE_PROFIT', 'TRAILING'].some(t => orderType.includes(t));
                        return isProtection ? (
                          <div className="mt-1 flex items-center gap-2">
                            <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/50">
                              {selectedOrder.type}
                            </Badge>
                            <span className="text-xs text-amber-400/70">Protection</span>
                          </div>
                        ) : (
                          <p className="mt-1 text-lg font-semibold">{selectedOrder.type}</p>
                        );
                      })()}
                    </div>
                    <div className="rounded-lg border border-border bg-muted/50 p-4">
                      <p className="text-xs text-muted-foreground">Size</p>
                      <p className="mt-1 text-lg font-semibold">
                        {formatQuantity(selectedOrder.size)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/50 p-4">
                      <p className="text-xs text-muted-foreground">Price</p>
                      <p className="mt-1 text-lg font-semibold">
                        {selectedOrder.price ? `$${selectedOrder.price.toLocaleString()}` : "Market"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/50 p-4">
                      <p className="text-xs text-muted-foreground">Status</p>
                      <p className="mt-1 text-lg font-semibold">{selectedOrder.status}</p>
                    </div>
                  </div>
                </div>
              </>
            )}
          </SheetContent>
        </Sheet>
      </div>
    </TooltipProvider>
  );
}


