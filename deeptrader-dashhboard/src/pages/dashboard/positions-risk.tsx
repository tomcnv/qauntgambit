import { useState, useMemo, useEffect, useRef } from "react";
import { usePriceStore } from "../../store/price-store";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock,
  DollarSign,
  ExternalLink,
  Filter,
  Gauge,
  History,
  Info,
  Layers,
  Percent,
  RefreshCw,
  Scale,
  Search,
  Shield,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
  XCircle,
  Zap,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Separator } from "../../components/ui/separator";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../../components/ui/alert-dialog";
import { useOverviewData, useBotPositions, useActiveConfig, useTradeProfile, useBotInstances, useTradingSnapshot } from "../../lib/api/hooks";
import { closeAllPositions } from "../../lib/api/client";
import { Link, useLocation } from "react-router-dom";
import toast from "react-hot-toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useScopeStore } from "../../store/scope-store";
import { RunBar } from "../../components/run-bar";

// ============================================================================
// TYPES
// ============================================================================

type PositionRow = {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT" | "BUY" | "SELL";
  qty: number;
  notional: number;
  entryPrice: number;
  markPrice: number;
  unrealizedPnl: number;
  estimatedNetUnrealizedPnl: number;
  unrealizedPnlPercent: number;
  realizedToday: number;
  leverage: number | null;
  marginUsed: number;
  liqPrice: number;
  liqDistance: number;
  fundingPnl: number;
  nextFunding: string;
  strategy: string;
  status: string[];
  stopLoss: number | null;
  takeProfit: number | null;
  guardStatus: string | null;
  ageSec: number | null;
  predictionConfidence: number | null;
  botName: string | null;
  botId: string | null;
};

// ============================================================================
// COMPONENTS
// ============================================================================

function StickyHeader({
  botName,
  exchange,
  marketType,
  lastUpdated,
  isLivePricing = false,
  filters,
  onFilterChange,
  onFlattenAll,
}: {
  botName: string;
  exchange: string;
  marketType: string;
  lastUpdated: number;
  isLivePricing?: boolean;
  filters: {
    symbol: string;
    strategy: string;
    nonZeroOnly: boolean;
    futuresOnly: boolean;
    atRiskOnly: boolean;
  };
  onFilterChange: (key: string, value: any) => void;
  onFlattenAll: () => void;
}) {
  return (
    <div className="sticky top-0 z-40 bg-card/95 backdrop-blur-sm border-b">
      <div className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Left: Bot info */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" />
            <span className="font-medium text-sm">{botName}</span>
          </div>
          <Separator orientation="vertical" className="h-5 hidden sm:block" />
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">{exchange}</Badge>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">{marketType}</Badge>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            <span>Updated {lastUpdated}s ago</span>
          </div>
          {isLivePricing && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-emerald-500/50 text-emerald-500 animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1 inline-block" />
              LIVE
            </Badge>
          )}
        </div>

        {/* Right: Filters + Flatten */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Symbol..."
              value={filters.symbol}
              onChange={(e) => onFilterChange("symbol", e.target.value)}
              className="h-7 w-[100px] pl-8 text-xs"
            />
          </div>
          <Button
            variant={filters.nonZeroOnly ? "default" : "outline"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => onFilterChange("nonZeroOnly", !filters.nonZeroOnly)}
          >
            Non-zero
          </Button>
          <Button
            variant={filters.atRiskOnly ? "default" : "outline"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => onFilterChange("atRiskOnly", !filters.atRiskOnly)}
          >
            <AlertTriangle className="h-3.5 w-3.5 mr-1" />
            At-risk
          </Button>

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" className="h-7 text-xs border-red-500/30 text-red-500 hover:bg-red-500/10">
                <Target className="h-3.5 w-3.5 mr-1" />
                Flatten All
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="sm:max-w-md">
              <AlertDialogHeader>
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/10">
                  <Target className="h-7 w-7 text-red-500" />
                </div>
                <AlertDialogTitle className="text-center">Flatten All Positions</AlertDialogTitle>
                <AlertDialogDescription className="text-center">
                  This will close all open positions at market price. This action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter className="sm:justify-center gap-2">
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction className="bg-red-500 hover:bg-red-600" onClick={onFlattenAll}>
                  Confirm Flatten
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>
    </div>
  );
}

function RiskSummaryStrip({
  totalGross,
  totalNet,
  totalMarginUsed,
  totalMargin,
  largestPercent,
  atRiskCount,
  positionsCount,
}: {
  totalGross: number;
  totalNet: number;
  totalMarginUsed: number;
  totalMargin: number;
  largestPercent: number;
  atRiskCount: number;
  positionsCount: number;
}) {
  const marginPercent = totalMargin > 0 ? (totalMarginUsed / totalMargin) * 100 : 0;
  const availableMargin = Math.max(totalMargin - totalMarginUsed, 0);
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
      <Card>
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">Net Exposure</span>
            <Scale className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <p className={cn("text-lg font-bold", totalNet >= 0 ? "text-emerald-500" : "text-red-500")}>
            ${Math.abs(totalNet).toLocaleString()}
          </p>
          <p className="text-[10px] text-muted-foreground">{totalNet >= 0 ? "Net Long" : "Net Short"}</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">Gross Exposure</span>
            <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <p className="text-lg font-bold">${totalGross.toLocaleString()}</p>
          <p className="text-[10px] text-muted-foreground">{positionsCount} positions</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">Margin Used</span>
            <Gauge className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <p className="text-lg font-bold">{marginPercent.toFixed(0)}%</p>
          <Progress value={marginPercent} className="h-1 mt-1" />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">Available</span>
            <DollarSign className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <p className="text-lg font-bold text-emerald-500">${availableMargin.toLocaleString()}</p>
          <p className="text-[10px] text-muted-foreground">Buffer remaining</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">Largest Position</span>
            <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <p className="text-lg font-bold">{largestPercent.toFixed(0)}%</p>
          <p className="text-[10px] text-muted-foreground">of total exposure</p>
        </CardContent>
      </Card>

      <Card className={atRiskCount > 0 ? "border-amber-500/30 bg-amber-500/5" : ""}>
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">At-Risk</span>
            <ShieldAlert className={cn("h-3.5 w-3.5", atRiskCount > 0 ? "text-amber-500" : "text-muted-foreground")} />
          </div>
          <p className={cn("text-lg font-bold", atRiskCount > 0 ? "text-amber-500" : "")}>
            {atRiskCount}
          </p>
          <p className="text-[10px] text-muted-foreground">{"< 10% liq distance"}</p>
        </CardContent>
      </Card>
    </div>
  );
}

function PositionsTable({
  positions,
  onPositionClick,
  showBotColumn = false,
}: {
  positions: PositionRow[];
  onPositionClick: (position: PositionRow) => void;
  showBotColumn?: boolean;
}) {
  const [sortKey, setSortKey] = useState<string>("notional");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sortedPositions = [...positions].sort((a, b) => {
    const aVal = a[sortKey as keyof typeof a] as number;
    const bVal = b[sortKey as keyof typeof b] as number;
    return sortDir === "asc" ? aVal - bVal : bVal - aVal;
  });

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const SortHeader = ({ label, sortKeyName, align = "left" }: { label: string; sortKeyName: string; align?: "left" | "right" }) => (
    <th
      className={cn(
        "font-medium text-muted-foreground py-2 pr-3 cursor-pointer hover:text-foreground transition-colors",
        align === "right" ? "text-right" : "text-left"
      )}
      onClick={() => handleSort(sortKeyName)}
    >
      <div className={cn("flex items-center gap-1", align === "right" && "justify-end")}>
        {label}
        {sortKey === sortKeyName && (
          <span className="text-[10px]">{sortDir === "asc" ? "↑" : "↓"}</span>
        )}
      </div>
    </th>
  );

  const formatAge = (ageSec: number | null) => {
    if (!ageSec || ageSec <= 0) {
      return "—";
    }
    if (ageSec < 60) {
      return `${Math.floor(ageSec)}s`;
    }
    if (ageSec < 3600) {
      return `${Math.floor(ageSec / 60)}m`;
    }
    return `${(ageSec / 3600).toFixed(1)}h`;
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Positions</CardTitle>
          <Badge variant="outline" className="text-xs">{positions.length} active</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b">
                {showBotColumn && <th className="text-left font-medium text-muted-foreground py-2 pr-3">Bot</th>}
                <SortHeader label="Symbol" sortKeyName="symbol" align="left" />
                <th className="text-left font-medium text-muted-foreground py-2 pr-3">Side</th>
                <SortHeader label="Qty" sortKeyName="qty" align="right" />
                <SortHeader label="Notional" sortKeyName="notional" align="right" />
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">Entry</th>
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">Mark</th>
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">SL</th>
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">TP</th>
                <th className="text-left font-medium text-muted-foreground py-2 pr-3">Guard</th>
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">Age</th>
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">Pred</th>
                <SortHeader label="P&L (Gross / Net Est)" sortKeyName="unrealizedPnl" align="right" />
                <th className="text-right font-medium text-muted-foreground py-2 pr-3">Lev</th>
                <SortHeader label="Liq %" sortKeyName="liqDistance" align="right" />
                <th className="text-left font-medium text-muted-foreground py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {sortedPositions.map((pos) => (
                <tr
                  key={pos.id}
                  className={cn(
                    "border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors",
                    pos.liqDistance < 10 && pos.liqDistance < 900 && "bg-amber-500/5"
                  )}
                  onClick={() => onPositionClick(pos)}
                >
                  {showBotColumn && (
                    <td className="py-2.5 pr-3 text-left">
                      <span className="font-medium">{pos.botName || "Alpha Bot"}</span>
                    </td>
                  )}
                  <td className="py-2.5 pr-3 font-medium">{pos.symbol}</td>
                  <td className="py-2.5 pr-3">
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px] px-1.5",
                        pos.side === "LONG" || pos.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                      )}
                    >
                      {pos.side}
                    </Badge>
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono">{pos.qty < 1 ? pos.qty.toPrecision(4) : pos.qty.toFixed(2)}</td>
                  <td className="py-2.5 pr-3 text-right font-mono">${pos.notional.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                  <td className="py-2.5 pr-3 text-right font-mono text-muted-foreground">${pos.entryPrice.toLocaleString()}</td>
                  <td className="py-2.5 pr-3 text-right font-mono">${pos.markPrice.toLocaleString()}</td>
                  <td className="py-2.5 pr-3 text-right font-mono text-red-400">
                    {pos.stopLoss ? `$${pos.stopLoss.toLocaleString()}` : "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono text-emerald-400">
                    {pos.takeProfit ? `$${pos.takeProfit.toLocaleString()}` : "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-left">
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[9px] px-1.5 py-0",
                        pos.guardStatus === "protected"
                          ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/30"
                          : "bg-muted/30 text-muted-foreground border-muted"
                      )}
                    >
                      {pos.guardStatus || "unknown"}
                    </Badge>
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono text-muted-foreground">
                    {formatAge(pos.ageSec)}
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono">
                    {pos.predictionConfidence !== null && pos.predictionConfidence !== undefined
                      ? `${(pos.predictionConfidence * 100).toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className={cn("py-2.5 pr-3 text-right font-mono whitespace-nowrap", pos.unrealizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                    <div>
                      {pos.unrealizedPnl >= 0 ? "+" : ""}${pos.unrealizedPnl.toFixed(2)} <span className="text-[10px] opacity-70">({pos.unrealizedPnlPercent >= 0 ? "+" : ""}{pos.unrealizedPnlPercent.toFixed(2)}%)</span>
                    </div>
                    <div className={cn("text-[10px]", pos.estimatedNetUnrealizedPnl >= 0 ? "text-emerald-400/90" : "text-red-400/90")}>
                      {pos.estimatedNetUnrealizedPnl >= 0 ? "+" : ""}${pos.estimatedNetUnrealizedPnl.toFixed(2)}
                    </div>
                  </td>
                  <td className="py-2.5 pr-3 text-right font-mono">{pos.leverage !== null ? `${pos.leverage}x` : 'N/A'}</td>
                  <td className={cn("py-2.5 pr-3 text-right font-mono", pos.liqDistance < 10 && pos.liqDistance < 900 && "text-amber-500 font-semibold")}>
                    {pos.liqDistance >= 900 ? "—" : `${pos.liqDistance.toFixed(1)}%`}
                  </td>
                  <td className="py-2.5 text-left">
                    <div className="flex gap-1">
                      {pos.liqDistance < 10 && pos.liqDistance < 900 ? (
                        <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-amber-500/10 text-amber-500 border-amber-500/30">At Risk</Badge>
                      ) : pos.status.includes("hedged") ? (
                        <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-blue-500/10 text-blue-500 border-blue-500/30">Hedged</Badge>
                      ) : (
                        <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-emerald-500/10 text-emerald-500 border-emerald-500/30">Active</Badge>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function ExposureBreakdown({
  bySymbol,
  byStrategy,
}: {
  bySymbol: Array<{ symbol: string; net: number; gross: number; percentage: number; color: string }>;
  byStrategy: Array<{ strategy: string; net: number; gross: number; percentage: number; color: string }>;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* By Symbol */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Exposure by Symbol</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4">
            <div className="h-[140px] w-[140px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={bySymbol}
                    cx="50%"
                    cy="50%"
                    innerRadius={35}
                    outerRadius={55}
                    paddingAngle={3}
                    dataKey="gross"
                  >
                    {bySymbol.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-1 space-y-2">
              {bySymbol.map((item) => (
                <div key={item.symbol} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="font-medium">{item.symbol}</span>
                  </div>
                  <div className="text-right">
                    <span className={cn("font-mono", item.net >= 0 ? "text-emerald-500" : "text-red-500")}>
                      {item.net >= 0 ? "+" : "-"}${Math.abs(item.net).toFixed(2)}
                    </span>
                    <span className="text-muted-foreground ml-2">{item.percentage.toFixed(1)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          {bySymbol[0]?.percentage > 35 && (
            <div className="flex items-center gap-2 mt-3 p-2 rounded-lg bg-amber-500/10 text-amber-500 text-xs">
              <AlertTriangle className="h-3.5 w-3.5" />
              <span>Concentration warning: Top symbol &gt; 35%</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* By Strategy */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Exposure by Strategy</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4">
            <div className="h-[140px] w-[140px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={byStrategy}
                    cx="50%"
                    cy="50%"
                    innerRadius={35}
                    outerRadius={55}
                    paddingAngle={3}
                    dataKey="gross"
                  >
                    {byStrategy.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-1 space-y-2">
              {byStrategy.map((item) => (
                <div key={item.strategy} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="font-medium">{item.strategy}</span>
                  </div>
                  <div className="text-right">
                    <span className={cn("font-mono", item.net >= 0 ? "text-emerald-500" : "text-red-500")}>
                      {item.net >= 0 ? "+" : "-"}${Math.abs(item.net).toFixed(2)}
                    </span>
                    <span className="text-muted-foreground ml-2">{item.percentage.toFixed(1)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function MarginLiquidationPanel({ positions, marginBuffer }: { positions: PositionRow[]; marginBuffer: number }) {
  const closestToLiq = [...positions]
    .filter(p => p.liqDistance < 15)
    .sort((a, b) => a.liqDistance - b.liqDistance)
    .slice(0, 3);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium">Margin & Liquidation</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Account Mode */}
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Account Mode</span>
          <div className="flex gap-2">
            <Badge variant="outline" className="text-[10px]">Cross Margin</Badge>
            <Badge variant="outline" className="text-[10px]">Max 10x</Badge>
          </div>
        </div>

        {/* Margin Buffer Gauge */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Margin Buffer</span>
            <span className={cn("font-mono", marginBuffer < 20 ? "text-amber-500" : "text-emerald-500")}>
              {marginBuffer.toFixed(1)}%
            </span>
          </div>
          <Progress
            value={marginBuffer}
            className={cn("h-2", marginBuffer < 20 && "[&>div]:bg-amber-500")}
          />
        </div>

        {/* Closest to Liquidation */}
        <div className="space-y-2">
          <span className="text-xs text-muted-foreground">Closest to Liquidation</span>
          {closestToLiq.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-emerald-500">
              <CheckCircle2 className="h-3.5 w-3.5" />
              <span>All positions safe</span>
            </div>
          ) : (
            <div className="space-y-1.5">
              {closestToLiq.map((pos) => (
                <div
                  key={pos.id}
                  className={cn(
                    "flex items-center justify-between p-2 rounded-lg text-xs",
                    pos.liqDistance < 10 ? "bg-amber-500/10" : "bg-muted/30"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px] px-1",
                        pos.side === "LONG" || pos.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                      )}
                    >
                      {pos.side}
                    </Badge>
                    <span className="font-medium">{pos.symbol}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground">Liq: ${pos.liqPrice.toLocaleString()}</span>
                    <span className={cn("font-mono font-semibold", pos.liqDistance < 10 ? "text-amber-500" : "")}>
                      {pos.liqDistance.toFixed(1)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Warnings */}
        {closestToLiq.some(p => p.liqDistance < 10) && (
          <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 text-amber-500 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Liquidation Risk</p>
              <p className="text-[11px] opacity-80">
                {closestToLiq.filter(p => p.liqDistance < 10).length} position(s) within 10% of liquidation price
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PositionDrawer({
  position,
  onClose,
}: {
  position: PositionRow | null;
  onClose: () => void;
}) {
  if (!position) return null;

  const positionTimeline: Array<{ time: string; size: number; avgEntry: number }> = [];
  const recentFills: Array<{ time: string; side: string; qty: number; price: number }> = [];

  return (
    <Sheet open={!!position} onOpenChange={onClose}>
      <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                position.side === "LONG" || position.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
              )}
            >
              {position.side}
            </Badge>
            <SheetTitle>{position.symbol}</SheetTitle>
          </div>
          <SheetDescription>Position details and history</SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Key Metrics */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground mb-1">Notional</p>
              <p className="text-lg font-bold">${position.notional.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground mb-1">Unrealized PnL</p>
              <p className={cn("text-lg font-bold", position.unrealizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                {position.unrealizedPnl >= 0 ? "+" : ""}${position.unrealizedPnl.toFixed(2)}
              </p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground mb-1">Leverage</p>
              <p className="text-lg font-bold">{position.leverage !== null ? `${position.leverage}x` : 'N/A'}</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground mb-1">Liq Distance</p>
              <p className={cn("text-lg font-bold", position.liqDistance < 10 ? "text-amber-500" : "")}>
                {position.liqDistance.toFixed(1)}%
              </p>
            </div>
          </div>

          {/* Position Timeline */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Position Timeline</h3>
            {positionTimeline.length === 0 ? (
              <p className="text-xs text-muted-foreground">No timeline data available</p>
            ) : (
            <div className="h-[120px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={positionTimeline} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="sizeGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} width={35} />
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                  />
                  <Area type="stepAfter" dataKey="size" stroke="#8b5cf6" strokeWidth={2} fill="url(#sizeGradient)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            )}
          </div>

          {/* Recent Fills */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Recent Fills</h3>
            {recentFills.length === 0 ? (
              <p className="text-xs text-muted-foreground">No fills available</p>
            ) : (
            <div className="space-y-1.5">
                {recentFills.map((fill, idx) => (
                <div key={idx} className="flex items-center justify-between py-1.5 border-b border-border/30 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-muted-foreground">{fill.time}</span>
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-[10px] px-1",
                        fill.side === "BUY" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                      )}
                    >
                      {fill.side}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3">
                    <span>{fill.qty}</span>
                    <span className="font-mono">${fill.price.toLocaleString()}</span>
                  </div>
                </div>
              ))}
            </div>
            )}
          </div>

          {/* PnL Breakdown */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium">PnL Breakdown</h3>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between py-1 border-b border-border/30">
                <span className="text-muted-foreground">Price Move</span>
                <span className={cn("font-mono", position.unrealizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                  {position.unrealizedPnl >= 0 ? "+" : ""}${position.unrealizedPnl.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-border/30">
                <span className="text-muted-foreground">Funding</span>
                <span className={cn("font-mono", position.fundingPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                  {position.fundingPnl >= 0 ? "+" : ""}${position.fundingPnl.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between py-1 font-medium">
                <span>Net Unrealized</span>
                <span className={cn("font-mono", position.unrealizedPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                  {position.unrealizedPnl >= 0 ? "+" : ""}${position.unrealizedPnl.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="space-y-2 pt-4 border-t">
            <div className="grid grid-cols-2 gap-2">
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" size="sm" className="w-full">Reduce 50%</Button>
                </AlertDialogTrigger>
                <AlertDialogContent className="sm:max-w-md">
                  <AlertDialogHeader>
                    <AlertDialogTitle>Reduce Position by 50%</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will close {(position.qty / 2).toFixed(4)} {position.symbol} at market price.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={() => toast.success("Position reduced")}>Confirm</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" size="sm" className="w-full border-red-500/30 text-red-500 hover:bg-red-500/10">
                    Close Position
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent className="sm:max-w-md">
                  <AlertDialogHeader>
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/10">
                      <XCircle className="h-7 w-7 text-red-500" />
                    </div>
                    <AlertDialogTitle className="text-center">Close Entire Position</AlertDialogTitle>
                    <AlertDialogDescription className="text-center">
                      This will close your entire {position.symbol} {position.side.toLowerCase()} position ({position.qty < 1 ? position.qty.toPrecision(4) : position.qty.toFixed(2)}) at market price.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter className="sm:justify-center gap-2">
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction className="bg-red-500 hover:bg-red-600" onClick={() => toast.success("Position closed")}>
                      Close Position
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>

          {/* Cross-page Links */}
          <div className="space-y-2">
            <Link to={`/dashboard/live?symbol=${position.symbol}`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
                <ExternalLink className="h-4 w-4 mr-2" />
                View orders/fills for {position.symbol}
              </Button>
            </Link>
            <Link to={`/dashboard/execution?symbol=${position.symbol}`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
                <ExternalLink className="h-4 w-4 mr-2" />
                View execution quality
              </Button>
            </Link>
            <Link to="/replay">
              <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
                <History className="h-4 w-4 mr-2" />
                Open in Replay
              </Button>
            </Link>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function PositionsRiskPage() {
  const location = useLocation();
  const isBotScopeRoute = location.pathname.startsWith("/bots/");
  
  // Scope management
  const { level: scopeLevel, exchangeAccountId, exchangeAccountName, botId, botName } = useScopeStore();
  const { data: botInstancesData } = useBotInstances();
  const bots = (botInstancesData as any)?.bots || [];
  const botForExchange = bots.find((bot: any) =>
    bot.exchangeConfigs?.some((config: any) => config.exchange_account_id === exchangeAccountId)
  );
  const scopedBotId = botId || botForExchange?.id || null;
  
  const { data: activeConfigData } = useActiveConfig();
  const { data: overviewData } = useOverviewData({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId : null,
    botId: scopeLevel !== 'fleet' ? scopedBotId : null,
  });
  // Use bot positions from Redis (filtered by bot or exchange account when scoped)
  const { data: positionsData, isLoading: loadingPositions } = useBotPositions({
    exchangeAccountId: scopeLevel === 'exchange' ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel !== 'fleet' ? scopedBotId ?? undefined : undefined,
  });
  const { data: tradingSnapshot } = useTradingSnapshot({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel !== 'fleet' ? scopedBotId ?? undefined : undefined,
  });
  
  // Scope-aware title
  const getScopeTitle = () => {
    switch (scopeLevel) {
      case 'exchange': return `${exchangeAccountName || 'Exchange'} Positions`;
      case 'bot': return `${botName || 'Bot'} Positions`;
      default: return 'Fleet Positions';
    }
  };
  const [selectedPosition, setSelectedPosition] = useState<PositionRow | null>(null);
  const [filters, setFilters] = useState({
    symbol: "",
    side: "",
    status: "",
    strategy: "",
    nonZeroOnly: true,
    futuresOnly: false,
    atRiskOnly: false,
  });

  // Real-time prices from WebSocket for display only.
  // Do not use these to recompute PnL; backend position payload is authoritative.
  const livePrices = usePriceStore((s) => s.prices);
  const priceLastUpdate = usePriceStore((s) => s.lastUpdate);
  
  // Helper to get live price for a symbol
  const getLivePrice = (symbol: string): number | undefined => {
    // Normalize symbol: "BTC-USDT-SWAP" -> "BTCUSDT", "BTCUSDT" -> "BTCUSDT"
    const normalized = symbol
      .replace(/-/g, '')
      .replace('SWAP', '')
      .replace('/USDT', 'USDT')
      .toUpperCase();
    return livePrices.get(normalized)?.price;
  };

  const positions: PositionRow[] = useMemo(() => {
    // Support both old format (positions array) and new format (data array from Redis)
    const posArray =
      positionsData?.data ||
      positionsData?.positions ||
      tradingSnapshot?.positions ||
      [];
    if (posArray.length > 0) {
      return posArray.map((p: any, i: number) => {
        const rawQty = parseFloat(p.quantity || p.size || 0);
        const qty = Math.abs(rawQty);
        const sideRaw = String(p.side || "").toUpperCase();
        const sideSign = sideRaw === "SHORT" || sideRaw === "SELL" ? -1 : sideRaw === "LONG" || sideRaw === "BUY" ? 1 : rawQty < 0 ? -1 : 1;
        const side: PositionRow["side"] = sideRaw === "BUY" || sideRaw === "SELL" ? sideRaw : sideSign >= 0 ? "LONG" : "SHORT";
        const storedPrice = parseFloat(
          p.reference_price || p.mark_price || p.markPrice || p.current_price || p.entryPrice || p.entry_price || 0
        );
        const symbolKey = p.symbol || `SYM-${i}`;
        
        // Use live price for near-real-time valuation when available.
        const livePrice = getLivePrice(symbolKey);
        const mark = livePrice ?? storedPrice;
        
        const notional = Math.abs(qty * mark);
        const entry = parseFloat(p.entry_price || p.entryPrice || 0);
        
        // For live screen accuracy, value PnL from displayed mark when possible.
        const serverUnrealized = parseFloat(String(p.unrealizedPnl ?? p.unrealized_pnl ?? p.pnl ?? Number.NaN));
        const markBasedUnrealized = entry && mark && qty ? (mark - entry) * qty * sideSign : Number.NaN;
        const unrealized = Number.isFinite(markBasedUnrealized)
          ? markBasedUnrealized
          : (Number.isFinite(serverUnrealized) ? serverUnrealized : 0);
        const serverFeeEstimate = parseFloat(String(p.estimatedRoundTripFeeUsd ?? p.estimated_round_trip_fee_usd ?? Number.NaN));
        const estimatedRoundTripFee = Number.isFinite(serverFeeEstimate) ? serverFeeEstimate : Math.abs(notional) * 0.0012;
        const estimatedNetUnrealizedBase = unrealized - estimatedRoundTripFee;
        const estimatedNetUnrealized = parseFloat(String(estimatedNetUnrealizedBase));
        
        const unrealizedPct = entry && qty ? (unrealized / (Math.abs(qty) * entry)) * 100 : 0;
        // Leverage comes from exchange position data
        // If not provided, show "N/A" instead of assuming 10x
        const leverage = p.leverage ? parseFloat(p.leverage) : null;
        // Calculate margin used: notional / leverage (for cross margin)
        // If leverage is null, we can't calculate margin
        const marginUsed = parseFloat(p.margin || 0) || (leverage ? notional / leverage : 0);
        const liqPrice = parseFloat(p.liquidation_price || p.liquidationPrice || 0);
        const liqDistance = liqPrice
          ? Math.abs((mark - liqPrice) / (mark || 1)) * 100
          : 999;
        const openedAt = parseFloat(p.opened_at || p.openedAt || 0);
        const ageSec = Number.isFinite(p.age_sec) ? p.age_sec : (openedAt ? Date.now() / 1000 - openedAt : null);
          const predictionConfidence = p.prediction_confidence ?? p.predictionConfidence ?? p.prediction?.confidence ?? null;
        return {
          id: p.id ? String(p.id) : String(i),
          symbol: symbolKey.replace(/-USDT-SWAP$/, "USDT"),
          side,
          qty,
          notional,
          entryPrice: entry,
          markPrice: mark,
          unrealizedPnl: unrealized,
          estimatedNetUnrealizedPnl: Number.isFinite(estimatedNetUnrealized) ? estimatedNetUnrealized : unrealized,
          unrealizedPnlPercent: unrealizedPct,
          realizedToday: parseFloat(p.realizedToday || 0),
          leverage,
          marginUsed,
          liqPrice,
          liqDistance: Number.isFinite(liqDistance) ? liqDistance : 999,
          fundingPnl: parseFloat(p.fundingPnl || 0),
          nextFunding: p.nextFundingTime || "N/A",
          strategy: p.strategy || p.strategy_id || p.profile_id || "unknown",
          status: Array.isArray(p.status) ? p.status : [],
          stopLoss: p.stop_loss ?? p.stopLoss ?? null,
          takeProfit: p.take_profit ?? p.takeProfit ?? null,
          guardStatus: p.guard_status ?? p.guardStatus ?? null,
          ageSec: ageSec ? Math.max(0, ageSec) : null,
          predictionConfidence: predictionConfidence !== null ? Number(predictionConfidence) : null,
          botName: p.bot_name ?? p.botName ?? null,
          botId: p.bot_id ?? p.botId ?? null,
        };
      });
    }
    return [];
  }, [positionsData, tradingSnapshot, livePrices, priceLastUpdate]);

  // Get exchange balance from overview data for margin calculations
  const exchangeBalance = overviewData?.scopedMetrics?.data?.current_equity 
    || overviewData?.scopedMetrics?.data?.exchange_balance 
    || 0;

  const totals = useMemo(() => {
    const totalGross = positions.reduce((sum, p) => sum + p.notional, 0);
    const totalNet = positions.reduce((sum, p) => sum + ((p.side === "LONG" || p.side === "BUY") ? p.notional : -p.notional), 0);
    const totalMarginUsed = positions.reduce((sum, p) => sum + p.marginUsed, 0);
    // Total margin is the exchange balance (available capital for trading)
    const totalMargin = exchangeBalance || totalMarginUsed * 2; // fallback if no balance
    const largest = positions.length ? Math.max(...positions.map((p) => p.notional)) : 0;
    const largestPercent = totalGross > 0 ? (largest / totalGross) * 100 : 0;
    const atRiskCount = positions.filter((p) => p.liqDistance < 10).length;
    const availableMargin = Math.max(totalMargin - totalMarginUsed, 0);
    const marginBuffer = totalMargin > 0 ? (availableMargin / totalMargin) * 100 : 100;
    return { totalGross, totalNet, totalMarginUsed, totalMargin, availableMargin, largestPercent, atRiskCount, marginBuffer };
  }, [positions, exchangeBalance]);

  const exposureBySymbol = useMemo(() => {
    const map = new Map<string, { symbol: string; net: number; gross: number }>();
    positions.forEach((p) => {
      const existing = map.get(p.symbol) || { symbol: p.symbol, net: 0, gross: 0 };
      const signed = (p.side === "LONG" || p.side === "BUY") ? p.notional : -p.notional;
      existing.net += signed;
      existing.gross += Math.abs(p.notional);
      map.set(p.symbol, existing);
    });
    const totalGross = Array.from(map.values()).reduce((sum, v) => sum + v.gross, 0) || 1;
    const palette = ["#8b5cf6", "#06b6d4", "#f59e0b", "#10b981", "#f97316", "#0ea5e9"];
    return Array.from(map.values()).map((v, idx) => ({
      ...v,
      percentage: (v.gross / totalGross) * 100,
      color: palette[idx % palette.length],
    }));
  }, [positions]);

  const exposureByStrategyCalc = useMemo(() => {
    const map = new Map<string, { strategy: string; net: number; gross: number }>();
    positions.forEach((p) => {
      const key = p.strategy || "unknown";
      const existing = map.get(key) || { strategy: key, net: 0, gross: 0 };
      const signed = (p.side === "LONG" || p.side === "BUY") ? p.notional : -p.notional;
      existing.net += signed;
      existing.gross += Math.abs(p.notional);
      map.set(key, existing);
    });
    const totalGross = Array.from(map.values()).reduce((sum, v) => sum + v.gross, 0) || 1;
    const palette = ["#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#6366f1", "#f97316"];
    return Array.from(map.values()).map((v, idx) => ({
      ...v,
      percentage: (v.gross / totalGross) * 100,
      color: palette[idx % palette.length],
    }));
  }, [positions]);

  // Debounced chart data - only updates every 10 seconds to prevent chart jitter
  const [debouncedBySymbol, setDebouncedBySymbol] = useState(exposureBySymbol);
  const [debouncedByStrategy, setDebouncedByStrategy] = useState(exposureByStrategyCalc);
  const lastChartUpdate = useRef(Date.now());

  useEffect(() => {
    const now = Date.now();
    // Update immediately on first render or if 10 seconds have passed
    if (now - lastChartUpdate.current >= 10000 || debouncedBySymbol.length === 0) {
      setDebouncedBySymbol(exposureBySymbol);
      setDebouncedByStrategy(exposureByStrategyCalc);
      lastChartUpdate.current = now;
    } else {
      // Schedule an update after the remaining time
      const timeUntilUpdate = 10000 - (now - lastChartUpdate.current);
      const timer = setTimeout(() => {
        setDebouncedBySymbol(exposureBySymbol);
        setDebouncedByStrategy(exposureByStrategyCalc);
        lastChartUpdate.current = Date.now();
      }, timeUntilUpdate);
      return () => clearTimeout(timer);
    }
  }, [exposureBySymbol, exposureByStrategyCalc]);

  const handleFilterChange = (key: string, value: any) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const queryClient = useQueryClient();
  
  const flattenAllMutation = useMutation({
    mutationFn: (options?: { botId?: string; exchangeAccountId?: string }) => closeAllPositions(options),
    onSuccess: (data) => {
      const paperMsg = data.paperClosed ? ` (${data.paperClosed} paper)` : '';
      const exchangeMsg = data.exchangeClosed ? ` (${data.exchangeClosed} exchange)` : '';
      toast.success(`Closed ${data.count} position(s)${paperMsg}${exchangeMsg}`);
      // Invalidate positions queries to refresh the data
      queryClient.invalidateQueries({ queryKey: ["exchange-positions"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      queryClient.invalidateQueries({ queryKey: ["bot-positions"] });
      queryClient.invalidateQueries({ queryKey: ["paper-positions"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to close positions");
    },
  });

  const handleFlattenAll = () => {
    // Pass botId and/or exchangeAccountId to close paper positions too
    flattenAllMutation.mutate({ 
      botId: botId || undefined, 
      exchangeAccountId: exchangeAccountId || undefined 
    });
  };

  const filteredPositions = positions.filter((pos: any) => {
    if (filters.symbol && !pos.symbol.toLowerCase().includes(filters.symbol.toLowerCase())) return false;
    if (filters.side && pos.side !== filters.side) return false;
    if (filters.status && !pos.status?.includes(filters.status)) return false;
    if (filters.nonZeroOnly && Math.abs(pos.qty) === 0) return false;
    if (filters.atRiskOnly && pos.liqDistance >= 10) return false;
    return true;
  });

  return (
    <TooltipProvider>
      {/* Sticky Run Bar */}
      <RunBar />
      
      {/* Main Content */}
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Page Header with Filters */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">Positions</h1>
              {priceLastUpdate > 0 && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 border-emerald-500/50 text-emerald-500">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1 inline-block animate-pulse" />
                  LIVE
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground">
              Open positions, exposure, and risk metrics {priceLastUpdate > 0 && "• Prices updating in real-time"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Input
              placeholder="Filter by symbol..."
              value={filters.symbol}
              onChange={(e) => handleFilterChange("symbol", e.target.value)}
              className="w-40 h-8 text-sm"
            />
            <Select value={filters.side} onValueChange={(v) => handleFilterChange("side", v)}>
              <SelectTrigger className="w-28 h-8">
                <SelectValue placeholder="Side" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All Sides</SelectItem>
                <SelectItem value="LONG">Long</SelectItem>
                <SelectItem value="SHORT">Short</SelectItem>
                <SelectItem value="BUY">Buy</SelectItem>
                <SelectItem value="SELL">Sell</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filters.status} onValueChange={(v) => handleFilterChange("status", v)}>
              <SelectTrigger className="w-32 h-8">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All Status</SelectItem>
                <SelectItem value="hedged">Hedged</SelectItem>
                <SelectItem value="active">Active</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant={filters.atRiskOnly ? "default" : "outline"}
              size="sm"
              onClick={() => handleFilterChange("atRiskOnly", !filters.atRiskOnly)}
              className="gap-1"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              At Risk
            </Button>
            <Button
              variant={filters.nonZeroOnly ? "default" : "outline"}
              size="sm"
              onClick={() => handleFilterChange("nonZeroOnly", !filters.nonZeroOnly)}
              className="gap-1"
            >
              Non-zero
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setFilters({ symbol: "", side: "", status: "", strategy: "", nonZeroOnly: true, futuresOnly: false, atRiskOnly: false })}>
              Clear
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={positions.length === 0 || flattenAllMutation.isPending}
                >
                  <Target className="h-3.5 w-3.5 mr-1" />
                  {flattenAllMutation.isPending ? "Flattening..." : "Flatten All"}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent className="sm:max-w-md">
                <AlertDialogHeader>
                  <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/10">
                    <Target className="h-7 w-7 text-red-500" />
                  </div>
                  <AlertDialogTitle className="text-center">Flatten All Positions</AlertDialogTitle>
                  <AlertDialogDescription className="text-center">
                    This will close all {positions.length} open position(s) at market price. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter className="sm:justify-center gap-2">
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction className="bg-red-500 hover:bg-red-600" onClick={handleFlattenAll}>
                    Confirm Flatten
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>

        {/* Risk Summary Strip */}
        <RiskSummaryStrip
          totalGross={totals.totalGross}
          totalNet={totals.totalNet}
          totalMarginUsed={totals.totalMarginUsed}
          totalMargin={totals.totalMargin}
          largestPercent={totals.largestPercent}
          atRiskCount={totals.atRiskCount}
          positionsCount={positions.length}
        />

        {/* Main Positions Table */}
        <PositionsTable
          positions={filteredPositions}
          onPositionClick={setSelectedPosition}
          showBotColumn={scopeLevel !== 'bot'}
        />

        {/* Exposure + Margin Panels */}
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ExposureBreakdown bySymbol={debouncedBySymbol} byStrategy={debouncedByStrategy} />
          </div>
          <MarginLiquidationPanel positions={positions} marginBuffer={totals.marginBuffer} />
        </div>
      </div>

      {/* Position Detail Drawer */}
      <PositionDrawer position={selectedPosition} onClose={() => setSelectedPosition(null)} />
    </TooltipProvider>
  );
}
