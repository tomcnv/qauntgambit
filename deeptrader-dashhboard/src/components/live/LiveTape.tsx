import { useState, useMemo } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronRight,
  Clock,
  ExternalLink,
  Filter,
  Radio,
  RotateCcw,
  Search,
  Shield,
  XCircle,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Input } from "../ui/input";
import { Checkbox } from "../ui/checkbox";
import { Label } from "../ui/label";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn, formatQuantity, formatSymbolDisplay } from "../../lib/utils";
import { Anomaly, FillRow, OrderRow, PositionRow, LiveTapeFilters } from "./types";

interface TopSymbolData {
  symbol: string;
  count?: number;
  signals?: number;
  pnl: number;
  avgSlip?: number;
  slippage?: number;
}

interface LatencyData {
  p50?: number | null;
  p95?: number | null;
  p99?: number | null;
  avg?: number | null;
}

interface LiveTapeProps {
  fills: any[];
  orders: any[];
  cancels: any[];
  rejects: any[];
  positions: any[];
  anomalies?: Anomaly[];
  onRowClick: (type: string, item: any) => void;
  onCancel: (order: any) => void;
  onReplace: (order: any) => void;
  cancelingId: string | null;
  replacingId: string | null;
  orderErrors: Record<string, string>;
  onOpenReplay?: (fill: { symbol?: string; timestamp?: string | number; id?: string; decisionId?: string }) => void;
  className?: string;
  // API-provided data (more accurate than calculated from fills)
  apiTopSymbols?: TopSymbolData[];
  apiLatency?: LatencyData;
}

// Time filter options
const TIME_FILTERS = [
  { value: "5m", label: "5m", seconds: 300 },
  { value: "15m", label: "15m", seconds: 900 },
  { value: "1h", label: "1h", seconds: 3600 },
  { value: "24h", label: "24h", seconds: 86400 },
  { value: "all", label: "All", seconds: Infinity },
] as const;

// Summary rail component
function SummaryRail({
  fills,
  rejects,
  className,
  apiTopSymbols,
  apiLatency,
}: {
  fills: any[];
  rejects: any[];
  className?: string;
  apiTopSymbols?: TopSymbolData[];
  apiLatency?: LatencyData;
}) {
  // Top symbols - prefer API data if available (has accurate PnL)
  const topSymbols = useMemo(() => {
    // Use API-provided topSymbols if available (more accurate)
    if (apiTopSymbols && apiTopSymbols.length > 0) {
      return apiTopSymbols.slice(0, 3).map(s => ({
        symbol: s.symbol,
        count: s.count ?? s.signals ?? 0,
        pnl: s.pnl ?? 0,
        avgSlip: s.avgSlip ?? s.slippage ?? 0,
      }));
    }
    
    // Fallback: calculate from fills
    const bySymbol = new Map<string, { count: number; pnl: number; slip: number[] }>();
    fills.forEach(f => {
      const sym = f.symbol || "?";
      const existing = bySymbol.get(sym) || { count: 0, pnl: 0, slip: [] };
      existing.count++;
      existing.pnl += f.pnl || 0;
      if (f.slippage) existing.slip.push(f.slippage);
      bySymbol.set(sym, existing);
    });
    return Array.from(bySymbol.entries())
      .map(([sym, data]) => ({
        symbol: sym,
        count: data.count,
        pnl: data.pnl,
        avgSlip: data.slip.length > 0 ? data.slip.reduce((a, b) => a + b, 0) / data.slip.length : 0,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 3);
  }, [fills, apiTopSymbols]);

  // Top reject reasons
  const topRejectReasons = useMemo(() => {
    const byReason = new Map<string, number>();
    rejects.forEach(r => {
      const reason = r.reason || r.rejection_reason || "Unknown";
      byReason.set(reason, (byReason.get(reason) || 0) + 1);
    });
    return Array.from(byReason.entries())
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 3);
  }, [rejects]);

  // Latency stats - prefer API data if available
  const latencyStats = useMemo(() => {
    // Use API-provided latency if available
    if (apiLatency && (apiLatency.p95 || apiLatency.avg)) {
      return {
        p95: apiLatency.p95 ?? apiLatency.avg ?? 0,
        max: apiLatency.p99 ?? apiLatency.p95 ?? 0,
        lastSpike: null,
      };
    }
    
    // Fallback: calculate from fills
    const latencies = fills.map(f => f.latency || f.latency_ms || 0).filter(l => l > 0).sort((a, b) => a - b);
    if (latencies.length === 0) return null;
    const p95 = latencies[Math.floor(latencies.length * 0.95)] || 0;
    const maxLatency = Math.max(...latencies);
    const lastSpike = fills.find(f => (f.latency || f.latency_ms || 0) > p95 * 1.5);
    return { p95, max: maxLatency, lastSpike: lastSpike?.time };
  }, [fills, apiLatency]);

  return (
    <div className={cn("flex gap-4 text-[10px] py-2 px-3 bg-muted/30 rounded-md", className)}>
      {/* Top symbols */}
      <div className="space-y-1">
        <span className="text-muted-foreground uppercase tracking-wide">Top Symbols</span>
        {topSymbols.length === 0 ? (
          <p className="text-muted-foreground">No data</p>
        ) : (
          topSymbols.map(s => (
            <div key={s.symbol} className="flex items-center gap-2">
              <span className="font-mono font-medium">{formatSymbolDisplay(s.symbol)}</span>
              <span className="text-muted-foreground">{s.count}</span>
              <span className={cn("font-mono", s.pnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                {s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(2)}
              </span>
              <span className="text-muted-foreground">{s.avgSlip.toFixed(1)}bp</span>
            </div>
          ))
        )}
      </div>

      <div className="w-px bg-border" />

      {/* Top reject reasons */}
      <div className="space-y-1">
        <span className="text-muted-foreground uppercase tracking-wide">Top Rejects</span>
        {topRejectReasons.length === 0 ? (
          <p className="text-muted-foreground">No rejects</p>
        ) : (
          topRejectReasons.map(r => (
            <div key={r.reason} className="flex items-center gap-2">
              <span className="font-mono truncate max-w-[120px]">{r.reason}</span>
              <Badge variant="outline" className="h-4 px-1 text-[9px]">{r.count}</Badge>
            </div>
          ))
        )}
      </div>

      <div className="w-px bg-border" />

      {/* Latency stats */}
      <div className="space-y-1">
        <span className="text-muted-foreground uppercase tracking-wide">Latency</span>
        {!latencyStats ? (
          <p className="text-muted-foreground">No data</p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">p95:</span>
              <span className="font-mono">{latencyStats.p95.toFixed(0)}ms</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Max:</span>
              <span className={cn("font-mono", latencyStats.max > 100 ? "text-amber-500" : "")}>
                {latencyStats.max.toFixed(0)}ms
              </span>
            </div>
            {latencyStats.lastSpike && (
              <div className="flex items-center gap-1 text-amber-500">
                <AlertTriangle className="h-2.5 w-2.5" />
                <span>Spike: {latencyStats.lastSpike}</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function LiveTape({
  fills,
  orders,
  cancels,
  rejects,
  positions,
  anomalies = [],
  onRowClick,
  onCancel,
  onReplace,
  cancelingId,
  replacingId,
  orderErrors,
  onOpenReplay,
  className,
  apiTopSymbols,
  apiLatency,
}: LiveTapeProps) {
  const [activeTab, setActiveTab] = useState("positions");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<LiveTapeFilters>({
    timeRange: "24h",
    symbols: [],
    strategies: [],
    anomaliesOnly: false,
    hideReconciled: false,
  });

  // Available filter options
  const availableSymbols = useMemo(() => {
    const set = new Set<string>();
    [...fills, ...orders, ...cancels, ...rejects, ...positions].forEach((f: any) => {
      if (f?.symbol) set.add(String(f.symbol).toUpperCase());
    });
    return Array.from(set).sort();
  }, [fills, orders, cancels, rejects, positions]);

  const availableStrategies = useMemo(() => {
    const set = new Set<string>();
    fills.forEach((f: any) => {
      if (f?.strategy) set.add(f.strategy);
    });
    return Array.from(set).sort();
  }, [fills]);

  // Time filtering
  const timeFilterSeconds = TIME_FILTERS.find(t => t.value === filters.timeRange)?.seconds || Infinity;
  const now = Date.now();

  const isWithinTimeRange = (item: any) => {
    if (timeFilterSeconds === Infinity) return true;
    const timestamp = item.timestamp || (item.time ? new Date(item.time).getTime() : 0);
    if (!timestamp) return true;
    const age = (now - timestamp) / 1000;
    return age <= timeFilterSeconds;
  };

  // Apply all filters
  const applyFilters = (item: any, isFill = false) => {
    // Time filter
    if (!isWithinTimeRange(item)) return false;
    
    // Symbol filter
    const sym = item.symbol?.toUpperCase();
    if (filters.symbols.length > 0 && (!sym || !filters.symbols.includes(sym))) return false;
    
    // Strategy filter
    if (filters.strategies.length > 0 && (!item.strategy || !filters.strategies.includes(item.strategy))) {
      return false;
    }
    
    // Anomalies only
    if (filters.anomaliesOnly && isFill) {
      if (!((item.slippage || 0) > 2 || (item.latency || 0) > 50)) return false;
    }
    
    // Hide reconciled
    if (filters.hideReconciled && item.reconciled) return false;
    
    return true;
  };

  const filteredFills = fills.filter((f) => applyFilters(f, true));
  
  // Helper to identify protection orders (SL/TP/trailing stop)
  const isProtectionOrder = (order: any) => {
    const orderType = (order.type || order.order_type || '').toUpperCase();
    return ['STOP', 'TAKE_PROFIT', 'TRAILING'].some(t => orderType.includes(t));
  };
  
  // Split orders into trading orders and protection orders
  const allFilteredOrders = orders.filter((o) => applyFilters(o));
  const filteredOrders = allFilteredOrders.filter(o => !isProtectionOrder(o));
  const filteredProtectionOrders = allFilteredOrders.filter(o => isProtectionOrder(o));
  
  const filteredCancels = cancels.filter((c) => applyFilters(c));
  const filteredRejects = rejects.filter((r) => applyFilters(r));
  const filteredPositions = positions.filter((p) => applyFilters(p));
  const filteredAnomalies = anomalies.filter(a => {
    if (!isWithinTimeRange(a)) return false;
    if (filters.symbols.length > 0 && a.symbol && !filters.symbols.includes(a.symbol.toUpperCase())) {
      return false;
    }
    return true;
  });

  // Detect anomalies from fills
  const detectedAnomalies = useMemo(() => {
    const results: Anomaly[] = [];
    
    // Helper to get valid timestamp
    const getTimestamp = (fill: any): string => {
      // Try timestamp first (numeric ms)
      if (fill.timestamp && typeof fill.timestamp === 'number' && fill.timestamp > 0) {
        return new Date(fill.timestamp).toISOString();
      }
      // Try time string
      if (fill.time && typeof fill.time === 'string') {
        // If it's already an ISO string, use it
        if (fill.time.includes('T') || fill.time.includes('-')) {
          return fill.time;
        }
        // If it's just a time like "10:23:45", use today's date
        return new Date().toISOString().split('T')[0] + 'T' + fill.time;
      }
      // Fallback to now
      return new Date().toISOString();
    };
    
    filteredFills.forEach(f => {
      const ts = getTimestamp(f);
      
      // Latency spike
      if ((f.latency || 0) > 100) {
        results.push({
          id: `lat-${f.id}`,
          type: "latency_spike",
          timestamp: ts,
          symbol: f.symbol,
          severity: f.latency > 200 ? "critical" : "warning",
          message: `High latency: ${f.latency}ms`,
          value: f.latency,
          threshold: 100,
        });
      }
      
      // Slippage outlier
      if (Math.abs(f.slippage || 0) > 3) {
        results.push({
          id: `slip-${f.id}`,
          type: "slippage_outlier",
          timestamp: ts,
          symbol: f.symbol,
          severity: Math.abs(f.slippage) > 5 ? "critical" : "warning",
          message: `High slippage: ${f.slippage?.toFixed(2)}bp`,
          value: f.slippage,
          threshold: 3,
        });
      }
    });
    
    return [...results, ...filteredAnomalies].sort((a, b) => 
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );
  }, [filteredFills, filteredAnomalies]);

  const hasActiveFilters = filters.symbols.length > 0 || 
    filters.strategies.length > 0 || 
    filters.anomaliesOnly || 
    filters.hideReconciled ||
    filters.timeRange !== "24h";

  return (
    <Card className={cn("relative", className)}>
      <CardHeader className="pb-2 sticky top-0 bg-card z-20 border-b">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-emerald-500 animate-pulse" />
            <CardTitle className="text-sm font-medium">Live Tape</CardTitle>
            <Badge variant="outline" className="text-[10px] h-5">
              <RotateCcw className="h-2.5 w-2.5 mr-1 animate-spin" />
              Auto-refresh
            </Badge>
          </div>
          
          {/* Time filter chips */}
          <div className="flex items-center gap-1">
            {TIME_FILTERS.map(t => (
              <Button
                key={t.value}
                variant={filters.timeRange === t.value ? "default" : "ghost"}
                size="sm"
                className="h-6 px-2 text-[10px]"
                onClick={() => setFilters(f => ({ ...f, timeRange: t.value as any }))}
              >
                {t.label}
              </Button>
            ))}
            
            <div className="w-px h-4 bg-border mx-1" />
            
            {/* Quick filter chips */}
            <Button
              variant={filters.anomaliesOnly ? "default" : "ghost"}
              size="sm"
              className={cn(
                "h-6 px-2 text-[10px] gap-1",
                filters.anomaliesOnly && "bg-amber-500 hover:bg-amber-600"
              )}
              onClick={() => setFilters(f => ({ ...f, anomaliesOnly: !f.anomaliesOnly }))}
            >
              <AlertTriangle className="h-2.5 w-2.5" />
              Anomalies
            </Button>
            
            <Button
              variant="ghost"
              size="icon"
              className={cn("h-6 w-6", hasActiveFilters && "text-primary")}
              onClick={() => setFiltersOpen(o => !o)}
              aria-label="Filters"
            >
              <Filter className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Expanded filters */}
        {filtersOpen && (
          <div className="mt-3 p-3 rounded-lg border bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium">Filters</p>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[10px]"
                onClick={() => setFilters({
                  timeRange: "24h",
                  symbols: [],
                  strategies: [],
                  anomaliesOnly: false,
                  hideReconciled: false,
                })}
              >
                Clear All
              </Button>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              {/* Symbols */}
              <div className="space-y-1.5">
                <Label className="text-[10px]">Symbols</Label>
                <div className="flex flex-wrap gap-1 max-h-20 overflow-auto">
                  {availableSymbols.map(sym => (
                    <Badge
                      key={sym}
                      variant={filters.symbols.includes(sym) ? "default" : "outline"}
                      className="text-[10px] cursor-pointer"
                      onClick={() => setFilters(f => ({
                        ...f,
                        symbols: f.symbols.includes(sym)
                          ? f.symbols.filter(s => s !== sym)
                          : [...f.symbols, sym]
                      }))}
                    >
                      {sym.replace(/-USDT.*/, "")}
                    </Badge>
                  ))}
                </div>
              </div>
              
              {/* Strategies */}
              <div className="space-y-1.5">
                <Label className="text-[10px]">Strategies</Label>
                <div className="flex flex-wrap gap-1 max-h-20 overflow-auto">
                  {availableStrategies.map(strat => (
                    <Badge
                      key={strat}
                      variant={filters.strategies.includes(strat) ? "default" : "outline"}
                      className="text-[10px] cursor-pointer"
                      onClick={() => setFilters(f => ({
                        ...f,
                        strategies: f.strategies.includes(strat)
                          ? f.strategies.filter(s => s !== strat)
                          : [...f.strategies, strat]
                      }))}
                    >
                      {strat}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-[10px]">
                <Checkbox
                  checked={filters.hideReconciled}
                  onCheckedChange={(checked) => setFilters(f => ({ ...f, hideReconciled: !!checked }))}
                />
                Hide reconciled trades
              </label>
            </div>
          </div>
        )}
      </CardHeader>

      <CardContent className="pt-2">
        {/* Summary Rail */}
        <SummaryRail 
          fills={filteredFills} 
          rejects={filteredRejects} 
          className="mb-3"
          apiTopSymbols={apiTopSymbols}
          apiLatency={apiLatency}
        />

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-3 sticky top-[60px] bg-card z-10">
            <TabsTrigger value="positions" className="text-xs gap-1.5">
              Positions
              {filteredPositions.length > 0 && (
                <Badge className="h-4 px-1 text-[10px] bg-blue-500">{filteredPositions.length}</Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="fills" className="text-xs gap-1.5">
              Fills
              <Badge variant="outline" className="h-4 px-1 text-[10px]">
                {filteredFills.length >= 500 ? '500+' : filteredFills.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="orders" className="text-xs gap-1.5">
              Orders
              <Badge variant="outline" className="h-4 px-1 text-[10px]">{filteredOrders.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="protection" className="text-xs gap-1.5">
              <Shield className="h-3 w-3" />
              Protection
              {(filteredProtectionOrders.length > 0 || filteredPositions.some((p: any) => p.stop_loss || p.stopLoss || p.take_profit || p.takeProfit)) && (
                <Badge className="h-4 px-1 text-[10px] bg-amber-500">
                  {filteredProtectionOrders.length + filteredPositions.filter((p: any) => p.stop_loss || p.stopLoss || p.take_profit || p.takeProfit).length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="cancels" className="text-xs gap-1.5">
              Cancels
              <Badge variant="outline" className="h-4 px-1 text-[10px]">{filteredCancels.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="rejects" className="text-xs gap-1.5">
              Rejects
              {filteredRejects.length > 0 && (
                <Badge className="h-4 px-1 text-[10px] bg-red-500">{filteredRejects.length}</Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="anomalies" className="text-xs gap-1.5">
              Anomalies
              {detectedAnomalies.length > 0 && (
                <Badge className="h-4 px-1 text-[10px] bg-amber-500">{detectedAnomalies.length}</Badge>
              )}
            </TabsTrigger>
          </TabsList>

          {/* Positions Tab */}
          <TabsContent value="positions" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Side</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Size</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Entry</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Mark</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Unreal P&L (Net Est)</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">SL</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">TP</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Guard</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Age</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Pred</th>
                    <th className="text-right font-medium text-muted-foreground py-2">Lev</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPositions.length === 0 ? (
                    <tr>
                      <td colSpan={12} className="py-8 text-center text-muted-foreground">
                        No open positions
                      </td>
                    </tr>
                  ) : (
                    filteredPositions.map((pos: any, idx: number) => {
                      const pnl = parseFloat(pos.unrealizedPnl || pos.unrealized_pnl || pos.pnl || 0);
                      const estimatedNetPnl = parseFloat(
                        pos.estimatedNetUnrealizedAfterFees ?? pos.estimated_net_unrealized_after_fees ?? pnl
                      );
                      const side = (pos.side || '').toUpperCase();
                      const ageSec = pos.age_sec ?? pos.ageSec ?? (pos.opened_at || pos.openedAt ? Date.now() / 1000 - (pos.opened_at || pos.openedAt) : null);
                      const predictionConfidence = pos.prediction_confidence ?? pos.predictionConfidence ?? pos.prediction?.confidence ?? null;
                      const guardStatus = pos.guard_status || pos.guardStatus || null;
                      const formatAge = (value: number | null) => {
                        if (!value || value <= 0) return "—";
                        if (value < 60) return `${Math.floor(value)}s`;
                        if (value < 3600) return `${Math.floor(value / 60)}m`;
                        return `${(value / 3600).toFixed(1)}h`;
                      };
                      return (
                        <tr 
                          key={pos.id || idx} 
                          className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                          onClick={() => onRowClick("position", pos)}
                        >
                          <td className="py-2 pr-2 font-medium">{pos.symbol}</td>
                          <td className="py-2 pr-2">
                            <Badge variant="outline" className={cn(
                              "text-[10px] px-1",
                              side === "LONG" || side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                            )}>
                              {side === "BUY" ? "LONG" : side === "SELL" ? "SHORT" : side}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2 text-right font-mono">{formatQuantity(pos.quantity || pos.size || 0)}</td>
                          <td className="py-2 pr-2 text-right font-mono">${(pos.entryPrice || pos.entry_price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                          <td className="py-2 pr-2 text-right font-mono">${(pos.markPrice || pos.mark_price || pos.current_price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                          <td className={cn("py-2 pr-2 text-right font-mono", pnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                            <div>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}</div>
                            <div className={cn("text-[10px]", estimatedNetPnl >= 0 ? "text-emerald-400/90" : "text-red-400/90")}>
                              {estimatedNetPnl >= 0 ? "+" : ""}{estimatedNetPnl.toFixed(2)}
                            </div>
                          </td>
                          <td className="py-2 pr-2 text-right font-mono text-red-400">
                            {pos.stopLoss || pos.stop_loss ? `$${parseFloat(pos.stopLoss || pos.stop_loss).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"}
                          </td>
                          <td className="py-2 pr-2 text-right font-mono text-emerald-400">
                            {pos.takeProfit || pos.take_profit ? `$${parseFloat(pos.takeProfit || pos.take_profit).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"}
                          </td>
                          <td className="py-2 pr-2 text-left">
                            <Badge
                              variant="outline"
                              className={cn(
                                "text-[10px] px-1",
                                guardStatus === "protected"
                                  ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/30"
                                  : "bg-muted/30 text-muted-foreground border-muted"
                              )}
                            >
                              {guardStatus || "unknown"}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2 text-right font-mono text-muted-foreground">
                            {formatAge(ageSec)}
                          </td>
                          <td className="py-2 pr-2 text-right font-mono">
                            {predictionConfidence !== null && predictionConfidence !== undefined
                              ? `${(predictionConfidence * 100).toFixed(0)}%`
                              : "—"}
                          </td>
                          <td className="py-2 text-right font-mono">{pos.leverage || 1}x</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* Fills Tab - Enhanced */}
          <TabsContent value="fills" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Time</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Side</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Type</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Qty</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Price</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">P&L</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Fee</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Strategy</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Latency</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Slip</th>
                    <th className="text-center font-medium text-muted-foreground py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredFills.length === 0 ? (
                    <tr>
                      <td colSpan={12} className="py-8 text-center text-muted-foreground">
                        No fills in selected time range
                      </td>
                    </tr>
                  ) : (
                    filteredFills.map((fill: any) => {
                      const isAnomaly = (fill.slippage || 0) > 2 || (fill.latency || 0) > 50;
                      return (
                        <tr 
                          key={fill.id} 
                          className={cn(
                            "border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors",
                            isAnomaly && "bg-amber-500/5"
                          )}
                          onClick={() => onRowClick("fill", fill)}
                        >
                          <td className="py-2 pr-2 font-mono text-muted-foreground text-[10px]">{fill.time}</td>
                          <td className="py-2 pr-2 font-medium">{fill.symbol}</td>
                          <td className="py-2 pr-2">
                            <Badge variant="outline" className={cn(
                              "text-[10px] px-1",
                              fill.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                            )}>
                              {fill.side}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2">
                            <Badge variant="outline" className="text-[10px] px-1">
                              {fill.orderType || fill.order_type || "taker"}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2 text-right font-mono">{formatQuantity(fill.quantity || fill.qty || 0)}</td>
                          <td className="py-2 pr-2 text-right font-mono">${(fill.price || fill.entryPrice || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                          <td className={cn(
                            "py-2 pr-2 text-right font-mono",
                            (fill.pnl || 0) >= 0 ? "text-emerald-500" : "text-red-500"
                          )}>
                            {fill.pnl !== undefined ? `${fill.pnl >= 0 ? "+" : ""}$${fill.pnl.toFixed(2)}` : "—"}
                          </td>
                          <td className="py-2 pr-2 text-right font-mono text-muted-foreground">
                            {fill.fee !== undefined ? `-$${Math.abs(fill.fee).toFixed(4)}` : "—"}
                          </td>
                          <td className="py-2 pr-2 text-[10px] text-muted-foreground truncate max-w-[80px]">
                            {fill.strategy || "—"}
                          </td>
                          <td className={cn(
                            "py-2 pr-2 text-right font-mono",
                            (fill.latency || 0) > 50 ? "text-amber-500" : "text-muted-foreground"
                          )}>
                            {fill.latency ? `${fill.latency}ms` : "—"}
                          </td>
                          <td className={cn(
                            "py-2 pr-2 text-right font-mono",
                            Math.abs(fill.slippage || 0) > 2 ? "text-amber-500" : "text-muted-foreground"
                          )}>
                            {fill.slippage !== undefined ? `${fill.slippage.toFixed(2)}bp` : "—"}
                          </td>
                          <td className="py-2 text-center">
                            {onOpenReplay && (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-5 w-5"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onOpenReplay({
                                        symbol: fill.symbol,
                                        timestamp: fill.timestamp || fill.time,
                                        id: fill.id,
                                        decisionId: fill.decisionId,
                                      });
                                    }}
                                  >
                                    <ExternalLink className="h-3 w-3" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Open in Replay</TooltipContent>
                              </Tooltip>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* Orders Tab */}
          <TabsContent value="orders" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Time</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Side</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Type</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Qty</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Price</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Status</th>
                    <th className="text-center font-medium text-muted-foreground py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOrders.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-muted-foreground">
                        No pending orders
                      </td>
                    </tr>
                  ) : (
                    filteredOrders.map((order: any) => (
                      <tr 
                        key={order.id} 
                        className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                        onClick={() => onRowClick("order", order)}
                      >
                        <td className="py-2 pr-2 font-mono text-muted-foreground text-[10px]">{order.time}</td>
                        <td className="py-2 pr-2 font-medium">{order.symbol}</td>
                        <td className="py-2 pr-2">
                          <Badge variant="outline" className={cn(
                            "text-[10px] px-1",
                            order.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                          )}>
                            {order.side}
                          </Badge>
                        </td>
                        <td className="py-2 pr-2 text-[10px]">{order.type}</td>
                        <td className="py-2 pr-2 text-right font-mono">{formatQuantity(order.quantity || order.qty || 0)}</td>
                        <td className="py-2 pr-2 text-right font-mono">${(order.price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                        <td className="py-2 pr-2">
                          <Badge variant="outline" className="text-[10px] px-1">
                            {order.status}
                          </Badge>
                        </td>
                        <td className="py-2 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[10px]"
                              onClick={(e) => {
                                e.stopPropagation();
                                onReplace(order);
                              }}
                              disabled={!!replacingId}
                            >
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[10px] text-red-500 hover:text-red-600"
                              onClick={(e) => {
                                e.stopPropagation();
                                onCancel(order);
                              }}
                              disabled={!!cancelingId}
                            >
                              Cancel
                            </Button>
                          </div>
                          {orderErrors[order.id] && (
                            <p className="text-[9px] text-red-500 mt-0.5">{orderErrors[order.id]}</p>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* Protection Orders Tab (SL/TP) */}
          <TabsContent value="protection" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              {/* Show position-attached SL/TP (most exchanges use this) */}
              {filteredPositions.some((p: any) => p.stop_loss || p.stopLoss || p.take_profit || p.takeProfit) && (
                <div className="mb-4">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1">
                    <Shield className="h-3 w-3" />
                    Position-Attached SL/TP
                  </div>
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-card z-10">
                      <tr className="border-b">
                        <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                        <th className="text-left font-medium text-muted-foreground py-2 pr-2">Position</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-2">Entry</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-2">Stop Loss</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-2">Take Profit</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-2">Risk</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-2">Reward</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPositions.filter((p: any) => p.stop_loss || p.stopLoss || p.take_profit || p.takeProfit).map((pos: any) => {
                        const sl = parseFloat(pos.stopLoss || pos.stop_loss || 0);
                        const tp = parseFloat(pos.takeProfit || pos.take_profit || 0);
                        const entry = parseFloat(pos.entryPrice || pos.entry_price || 0);
                        const side = (pos.side || '').toUpperCase();
                        const isLong = side === 'LONG' || side === 'BUY';
                        
                        // Calculate risk/reward percentages
                        const riskPct = entry > 0 && sl > 0 ? Math.abs((sl - entry) / entry * 100) : 0;
                        const rewardPct = entry > 0 && tp > 0 ? Math.abs((tp - entry) / entry * 100) : 0;
                        const rr = riskPct > 0 ? (rewardPct / riskPct) : 0;
                        
                        return (
                          <tr 
                            key={`pos-protection-${pos.symbol}`} 
                            className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                            onClick={() => onRowClick("position", pos)}
                          >
                            <td className="py-2 pr-2 font-medium">{pos.symbol}</td>
                            <td className="py-2 pr-2">
                              <Badge variant="outline" className={cn(
                                "text-[10px] px-1.5",
                                isLong ? "border-emerald-500/50 text-emerald-500 bg-emerald-500/10" : "border-red-500/50 text-red-500 bg-red-500/10"
                              )}>
                                {side}
                              </Badge>
                            </td>
                            <td className="py-2 pr-2 text-right font-mono">
                              ${entry.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </td>
                            <td className="py-2 pr-2 text-right font-mono">
                              {sl > 0 ? (
                                <span className="text-red-400">${sl.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="py-2 pr-2 text-right font-mono">
                              {tp > 0 ? (
                                <span className="text-emerald-400">${tp.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="py-2 pr-2 text-right font-mono text-red-400">
                              {riskPct > 0 ? `-${riskPct.toFixed(2)}%` : '—'}
                            </td>
                            <td className="py-2 pr-2 text-right font-mono">
                              {rewardPct > 0 ? (
                                <span className="text-emerald-400">+{rewardPct.toFixed(2)}%</span>
                              ) : '—'}
                              {rr > 0 && (
                                <span className="text-muted-foreground ml-1 text-[9px]">({rr.toFixed(1)}R)</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              
              {/* Separate conditional orders (if any) */}
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Type</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Side</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Trigger</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Qty</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Status</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Created</th>
                    <th className="text-center font-medium text-muted-foreground py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredProtectionOrders.length === 0 && !filteredPositions.some((p: any) => p.stop_loss || p.stopLoss || p.take_profit || p.takeProfit) ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-muted-foreground">
                        No protection (SL/TP not set on positions)
                      </td>
                    </tr>
                  ) : filteredProtectionOrders.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-4 text-center text-muted-foreground text-[10px]">
                        No separate conditional orders — SL/TP attached to positions above
                      </td>
                    </tr>
                  ) : (
                    filteredProtectionOrders.map((order: any) => {
                      const orderType = (order.type || '').toUpperCase();
                      const isStopLoss = orderType.includes('STOP') && !orderType.includes('TAKE');
                      const isTakeProfit = orderType.includes('TAKE_PROFIT') || orderType.includes('TAKEPROFIT');
                      return (
                        <tr 
                          key={order.id} 
                          className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                          onClick={() => onRowClick("order", order)}
                        >
                          <td className="py-2 pr-2 font-medium">{order.symbol}</td>
                          <td className="py-2 pr-2">
                            <Badge 
                              variant="outline" 
                              className={cn(
                                "text-[10px] px-1.5",
                                isStopLoss && "border-red-500/50 text-red-400 bg-red-500/10",
                                isTakeProfit && "border-emerald-500/50 text-emerald-400 bg-emerald-500/10",
                                !isStopLoss && !isTakeProfit && "border-amber-500/50 text-amber-400 bg-amber-500/10"
                              )}
                            >
                              {isStopLoss ? "SL" : isTakeProfit ? "TP" : order.type}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2">
                            <Badge variant="outline" className={cn(
                              "text-[10px] px-1",
                              order.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                            )}>
                              {order.side}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2 text-right font-mono">
                            ${(order.price || order.stopPrice || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                          </td>
                          <td className="py-2 pr-2 text-right font-mono">{formatQuantity(order.quantity || order.qty || 0)}</td>
                          <td className="py-2 pr-2">
                            <Badge variant="outline" className="text-[10px] px-1 border-blue-500/50 text-blue-400">
                              {order.status || "ACTIVE"}
                            </Badge>
                          </td>
                          <td className="py-2 pr-2 font-mono text-muted-foreground text-[10px]">{order.time}</td>
                          <td className="py-2 text-center">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[10px] text-red-500 hover:text-red-600"
                              onClick={(e) => {
                                e.stopPropagation();
                                onCancel(order);
                              }}
                              disabled={!!cancelingId}
                            >
                              Cancel
                            </Button>
                            {orderErrors[order.id] && (
                              <p className="text-[9px] text-red-500 mt-0.5">{orderErrors[order.id]}</p>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* Cancels Tab */}
          <TabsContent value="cancels" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Time</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Side</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Qty</th>
                    <th className="text-right font-medium text-muted-foreground py-2 pr-2">Price</th>
                    <th className="text-left font-medium text-muted-foreground py-2">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCancels.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-muted-foreground">
                        No canceled orders
                      </td>
                    </tr>
                  ) : (
                    filteredCancels.map((cancel: any) => (
                      <tr 
                        key={cancel.id} 
                        className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                        onClick={() => onRowClick("cancel", cancel)}
                      >
                        <td className="py-2 pr-2 font-mono text-muted-foreground text-[10px]">{cancel.time}</td>
                        <td className="py-2 pr-2 font-medium">{cancel.symbol}</td>
                        <td className="py-2 pr-2">
                          <Badge variant="outline" className={cn(
                            "text-[10px] px-1",
                            cancel.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                          )}>
                            {cancel.side}
                          </Badge>
                        </td>
                        <td className="py-2 pr-2 text-right font-mono">{formatQuantity(cancel.quantity || 0)}</td>
                        <td className="py-2 pr-2 text-right font-mono">${(cancel.price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                        <td className="py-2 text-muted-foreground truncate max-w-[150px]">{cancel.reason || "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* Rejects Tab */}
          <TabsContent value="rejects" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Time</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Side</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Stage</th>
                    <th className="text-left font-medium text-muted-foreground py-2">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRejects.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-muted-foreground">
                        No rejected signals
                      </td>
                    </tr>
                  ) : (
                    filteredRejects.map((reject: any) => (
                      <tr 
                        key={reject.id} 
                        className="border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors"
                        onClick={() => onRowClick("reject", reject)}
                      >
                        <td className="py-2 pr-2 font-mono text-muted-foreground text-[10px]">{reject.time}</td>
                        <td className="py-2 pr-2 font-medium">{reject.symbol}</td>
                        <td className="py-2 pr-2">
                          <Badge variant="outline" className={cn(
                            "text-[10px] px-1",
                            reject.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                          )}>
                            {reject.side}
                          </Badge>
                        </td>
                        <td className="py-2 pr-2">
                          <Badge variant="outline" className="text-[10px] px-1 bg-red-500/10 text-red-500 border-red-500/30">
                            {reject.stage || reject.rejection_stage || "gate"}
                          </Badge>
                        </td>
                        <td className="py-2 text-muted-foreground">{reject.reason || reject.rejection_reason || "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>

          {/* Anomalies Tab */}
          <TabsContent value="anomalies" className="mt-0">
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Time</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Type</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Symbol</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Severity</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-2">Message</th>
                    <th className="text-right font-medium text-muted-foreground py-2">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {detectedAnomalies.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-muted-foreground">
                        No anomalies detected
                      </td>
                    </tr>
                  ) : (
                    detectedAnomalies.map((anomaly) => (
                      <tr 
                        key={anomaly.id} 
                        className={cn(
                          "border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors",
                          anomaly.severity === "critical" ? "bg-red-500/5" : "bg-amber-500/5"
                        )}
                      >
                        <td className="py-2 pr-2 font-mono text-muted-foreground text-[10px]">
                          {(() => {
                            const d = new Date(anomaly.timestamp);
                            return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString();
                          })()}
                        </td>
                        <td className="py-2 pr-2">
                          <Badge variant="outline" className="text-[10px] px-1">
                            {anomaly.type.replace(/_/g, " ")}
                          </Badge>
                        </td>
                        <td className="py-2 pr-2 font-medium">{anomaly.symbol || "—"}</td>
                        <td className="py-2 pr-2">
                          <Badge 
                            variant="outline" 
                            className={cn(
                              "text-[10px] px-1",
                              anomaly.severity === "critical" 
                                ? "bg-red-500/10 text-red-500 border-red-500/30"
                                : "bg-amber-500/10 text-amber-500 border-amber-500/30"
                            )}
                          >
                            {anomaly.severity}
                          </Badge>
                        </td>
                        <td className="py-2 pr-2 text-muted-foreground">{anomaly.message}</td>
                        <td className="py-2 text-right font-mono">
                          {anomaly.value !== undefined && anomaly.threshold !== undefined && (
                            <span className={anomaly.value > anomaly.threshold ? "text-red-500" : ""}>
                              {anomaly.value.toFixed(1)} / {anomaly.threshold}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

