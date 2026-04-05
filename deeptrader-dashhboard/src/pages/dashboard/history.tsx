import { useState, useMemo, useEffect } from "react";
import {
  format,
  addMonths,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addDays,
  isSameMonth,
  isSameDay,
  isWithinInterval,
  parseISO,
  subDays,
  startOfYear,
} from "date-fns";
import {
  History,
  Download,
  Search,
  Filter,
  Calendar,
  TrendingUp,
  TrendingDown,
  ChevronLeft,
  ChevronRight,
  ArrowUpRight,
  ArrowDownRight,
  X,
  Clock,
  Target,
  Loader2,
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
  Cell,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Checkbox } from "../../components/ui/checkbox";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { cn, formatQuantity } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { useTradeHistory } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { TradeInspectorDrawer } from "../../components/trade-history/TradeInspectorDrawer";
import { RunBar } from "../../components/run-bar";


// Simple themed range calendar
function RangeCalendar({
  month,
  startDate,
  endDate,
  onMonthChange,
  onSelectDate,
}: {
  month: Date;
  startDate: string;
  endDate: string;
  onMonthChange: (next: Date) => void;
  onSelectDate: (date: string) => void;
}) {
  const monthStart = startOfMonth(month);
  const monthEnd = endOfMonth(month);
  const startDateObj = startDate ? parseISO(startDate) : null;
  const endDateObj = endDate ? parseISO(endDate) : null;

  const weeks: Date[][] = [];
  let current = startOfWeek(monthStart, { weekStartsOn: 1 });
  const end = endOfWeek(monthEnd, { weekStartsOn: 1 });

  while (current <= end) {
    const week: Date[] = [];
    for (let i = 0; i < 7; i++) {
      week.push(current);
      current = addDays(current, 1);
    }
    weeks.push(week);
  }

  const isInRange = (day: Date) => {
    if (startDateObj && endDateObj) {
      return isWithinInterval(day, { start: startDateObj, end: endDateObj });
    }
    return false;
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onMonthChange(addMonths(month, -1))}>
          ←
        </Button>
        <span className="font-medium">{format(month, "MMMM yyyy")}</span>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onMonthChange(addMonths(month, 1))}>
          →
        </Button>
      </div>
      <div className="grid grid-cols-7 text-[11px] text-muted-foreground">
        {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => (
          <div key={d} className="text-center py-1">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1 text-xs">
        {weeks.flat().map((day, idx) => {
          const iso = format(day, "yyyy-MM-dd");
          const selectedStart = startDateObj && isSameDay(day, startDateObj);
          const selectedEnd = endDateObj && isSameDay(day, endDateObj);
          const inRange = isInRange(day);
          const muted = !isSameMonth(day, month);
          return (
            <button
              key={idx}
              className={cn(
                "h-8 rounded-md border text-center transition-colors",
                muted ? "text-muted-foreground/60 border-transparent" : "border-border/60",
                inRange && "bg-primary/10 border-primary/40",
                (selectedStart || selectedEnd) && "bg-primary/20 border-primary text-primary font-semibold"
              )}
              onClick={() => onSelectDate(iso)}
            >
              {format(day, "d")}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function HistoryPage() {
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

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [dateRangeOpen, setDateRangeOpen] = useState(false);
  const [tempStartDate, setTempStartDate] = useState("");
  const [tempEndDate, setTempEndDate] = useState("");
  const [calendarMonth, setCalendarMonth] = useState(new Date());
  const [timeRange, setTimeRange] = useState("all");
  const [filters, setFilters] = useState({
    symbols: [] as string[],
    side: "",
    outcome: "",
    text: "",
    startDate: "",
    endDate: "",
  });

  // Date range presets
  const applyPreset = (preset: string) => {
    const today = new Date();
    let start: Date;
    let end = today;
    
    switch (preset) {
      case "today":
        start = new Date(today.setHours(0, 0, 0, 0));
        end = new Date();
        break;
      case "24h":
        start = subDays(new Date(), 1);
        break;
      case "7d":
        start = subDays(new Date(), 7);
        break;
      case "30d":
        start = subDays(new Date(), 30);
        break;
      case "mtd":
        start = startOfMonth(new Date());
        break;
      case "ytd":
        start = startOfYear(new Date());
        break;
      case "all":
        setTimeRange("all");
        setFilters((f) => ({ ...f, startDate: "", endDate: "" }));
        setDateRangeOpen(false);
        return;
      default:
        start = subDays(new Date(), 7);
    }
    
    setTimeRange(preset);
    setFilters((f) => ({
      ...f,
      startDate: format(start, "yyyy-MM-dd"),
      endDate: format(end, "yyyy-MM-dd"),
    }));
    setDateRangeOpen(false);
  };

  const applyCustomDateRange = () => {
    if (tempStartDate && tempEndDate) {
      setFilters((f) => ({
        ...f,
        startDate: tempStartDate,
        endDate: tempEndDate,
      }));
      setTimeRange("custom");
      setDateRangeOpen(false);
    }
  };
  const { data: historyData, isLoading } = useTradeHistory({
    // Pass exchangeAccountId for both 'exchange' and 'bot' scope levels
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel === 'bot' ? botId ?? undefined : undefined,
    startDate: filters.startDate || undefined,
    endDate: filters.endDate || undefined,
  });
  const [page, setPage] = useState(1);
  const [selectedTrade, setSelectedTrade] = useState<any>(null);

  const trades = historyData?.trades || [];
  const rawStats = historyData?.stats;
  const stats = useMemo(() => ({
    totalPnl: rawStats?.totalPnl ?? (rawStats as any)?.totalPnL ?? 0,
    totalPnL: (rawStats as any)?.totalPnL ?? rawStats?.totalPnl ?? 0,
    totalTrades: rawStats?.totalTrades ?? 0,
    winRate: rawStats?.winRate ?? 0,
    avgWin: rawStats?.avgWin ?? 0,
    avgLoss: rawStats?.avgLoss ?? 0,
    profitFactor: rawStats?.profitFactor ?? 0,
    sharpe: rawStats?.sharpe ?? 0,
    maxWin: rawStats?.maxWin ?? rawStats?.largestWin ?? 0,
    maxLoss: rawStats?.maxLoss ?? rawStats?.largestLoss ?? 0,
    largestWin: rawStats?.largestWin ?? rawStats?.maxWin ?? 0,
    largestLoss: rawStats?.largestLoss ?? rawStats?.maxLoss ?? 0,
    pnlHistory: rawStats?.pnlHistory ?? [],
  }), [rawStats]);
  
  const availableSymbols = useMemo(() => {
    const set = new Set<string>();
    trades.forEach((t: any) => {
      if (t.symbol) set.add(t.symbol.toUpperCase());
    });
    return Array.from(set).sort();
  }, [trades]);

  // Filter trades by UI filters
  const filteredTrades = useMemo(() => {
    return trades.filter((t: any) => {
      const sym = t.symbol?.toUpperCase();
      if (filters.symbols.length > 0 && (!sym || !filters.symbols.includes(sym))) return false;
      if (filters.side && t.side?.toUpperCase() !== filters.side) return false;
      if (filters.outcome) {
        const isWin = (t.pnl ?? 0) > 0;
        if (filters.outcome === "win" && !isWin) return false;
        if (filters.outcome === "loss" && isWin) return false;
      }
      if (filters.startDate || filters.endDate) {
        const ts = new Date(t.timestamp || t.exit_time || t.created_at || t.entry_time).getTime();
        if (filters.startDate && ts < new Date(filters.startDate).getTime()) return false;
        if (filters.endDate && ts > new Date(filters.endDate).getTime()) return false;
      }
      if (filters.text) {
        const q = filters.text.toLowerCase();
        const hay = `${t.symbol || ""} ${t.side || ""} ${t.strategy || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [trades, filters]);
  
  // Derived stats from filtered trades (used when filters are active)
  const derivedStats = useMemo(() => {
    if (!filteredTrades.length) return null;
    const totalTrades = filteredTrades.length;
    const pnlValues = filteredTrades.map((t: any) => t.pnl ?? 0);
    const totalPnL = pnlValues.reduce((s, v) => s + v, 0);
    const wins = pnlValues.filter((v) => v > 0);
    const losses = pnlValues.filter((v) => v <= 0);
    const winRate = totalTrades ? (wins.length / totalTrades) * 100 : 0;
    const avgWin = wins.length ? wins.reduce((s, v) => s + v, 0) / wins.length : 0;
    const avgLoss = losses.length ? losses.reduce((s, v) => s + v, 0) / losses.length : 0;
    const profitFactor = losses.reduce((s, v) => s + Math.abs(v), 0) > 0
      ? (wins.reduce((s, v) => s + v, 0)) / (losses.reduce((s, v) => s + Math.abs(v), 0))
      : wins.length ? 999 : 0;
    const maxWin = wins.length ? Math.max(...wins) : 0;
    const maxLoss = losses.length ? Math.min(...losses) : 0;
    return {
      totalPnL,
      totalTrades,
      winRate,
      avgWin,
      avgLoss,
      profitFactor,
      sharpe: stats.sharpe ?? 0,
      maxWin,
      maxLoss,
      largestWin: maxWin,
      largestLoss: maxLoss,
    };
  }, [filteredTrades, stats.sharpe]);

  // Derived daily PnL from filtered trades if filters active
  const dailyPnL = useMemo(() => {
    if (!filteredTrades.length) return historyData?.stats?.pnlHistory || [];
    const map = new Map<string, { date: string; pnl: number; fees: number; netPnl: number; totalTrades: number; winningTrades: number; losingTrades: number; winRate: number }>();
    filteredTrades.forEach((t: any) => {
      const date = new Date(t.timestamp || t.exit_time || t.created_at || t.entry_time).toISOString().split("T")[0];
      if (!map.has(date)) {
        map.set(date, { date, pnl: 0, fees: 0, netPnl: 0, totalTrades: 0, winningTrades: 0, losingTrades: 0, winRate: 0 });
      }
      const day = map.get(date)!;
      const pnl = t.pnl ?? 0;
      const fees = t.fees ?? 0;
      day.pnl += pnl;
      day.fees += fees;
      day.netPnl += pnl - fees;
      day.totalTrades += 1;
      if (pnl > 0) day.winningTrades += 1;
      if (pnl < 0) day.losingTrades += 1;
    });
    return Array.from(map.values()).map((d) => ({
      ...d,
      winRate: d.totalTrades ? (d.winningTrades / d.totalTrades) * 100 : 0,
    })).sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
  }, [filteredTrades, historyData?.stats?.pnlHistory]);

  const displayStats = derivedStats || stats;
  const pagedTrades = filteredTrades.slice((page - 1) * 20, (page - 1) * 20 + 20);
  const totalPages = Math.max(1, Math.ceil((filteredTrades.length || 1) / 20));

  // Reset pagination when filters change
  useEffect(() => {
    setPage(1);
  }, [filters]);

  // Sync temp date selectors when filters change
  useEffect(() => {
    setTempStartDate(filters.startDate);
    setTempEndDate(filters.endDate);
    if (filters.startDate) {
      setCalendarMonth(parseISO(filters.startDate));
    }
  }, [filters.startDate, filters.endDate]);

  const handleSelectDate = (iso: string) => {
    if (!tempStartDate || (tempStartDate && tempEndDate)) {
      // Start new selection
      setTempStartDate(iso);
      setTempEndDate("");
    } else {
      // Complete the range
      const start = parseISO(tempStartDate);
      const selected = parseISO(iso);
      if (selected < start) {
        setTempEndDate(tempStartDate);
        setTempStartDate(iso);
      } else {
        setTempEndDate(iso);
      }
    }
  };

  const toggleFilters = () => {
    setFiltersOpen((o) => {
      if (!o) setDateRangeOpen(false);
      return !o;
    });
  };

  const toggleDateRange = () => {
    setDateRangeOpen((o) => {
      if (!o) setFiltersOpen(false);
      return !o;
    });
  };

  const clearAllFilters = () => {
    setFilters({
      symbols: [],
      side: "",
      outcome: "",
      text: "",
      startDate: "",
      endDate: "",
    });
    setTempStartDate("");
    setTempEndDate("");
    setTimeRange("all");
    setFiltersOpen(false);
    setDateRangeOpen(false);
  };

  return (
    <TooltipProvider>
      {/* Sticky Run Bar */}
      <RunBar />
      
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Trade History</h1>
            <p className="text-sm text-muted-foreground">
              Historical trades and PnL reports • Click any trade for details
            </p>
          </div>
        <div className="flex items-center gap-2 relative">
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          
          {/* Filters button */}
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9"
            aria-label="Filters"
            onClick={toggleFilters}
          >
            <Filter className="h-4 w-4" />
          </Button>

          {/* Quick presets */}
          <div className="flex rounded-lg border bg-muted/50 p-1">
            {[
              { key: "all", label: "All" },
              { key: "today", label: "Today" },
              { key: "7d", label: "7d" },
              { key: "30d", label: "30d" },
              { key: "mtd", label: "MTD" },
              { key: "ytd", label: "YTD" },
            ].map(({ key, label }) => (
              <Button
                key={key}
                variant={timeRange === key ? "default" : "ghost"}
                size="sm"
                className="h-7 px-2.5 text-xs"
                onClick={() => applyPreset(key)}
              >
                {label}
              </Button>
            ))}
          </div>

          {/* Custom date range button */}
          <Button
            variant={timeRange === "custom" ? "default" : "outline"}
            size="sm"
            className="gap-2 h-9"
            onClick={toggleDateRange}
          >
            <Calendar className="h-4 w-4" />
            {timeRange === "custom" && filters.startDate && filters.endDate
              ? `${filters.startDate} → ${filters.endDate}`
              : "Custom"}
          </Button>

          {/* Clear all */}
          {(filters.symbols.length > 0 || filters.side || filters.outcome || filters.text || timeRange !== "all") && (
            <Button
              variant="ghost"
              size="sm"
              className="h-9 px-3 text-muted-foreground"
              onClick={clearAllFilters}
            >
              <X className="h-3 w-3 mr-1" />
              Clear
            </Button>
          )}

          {/* Date range picker panel */}
          {dateRangeOpen && (
            <div className="absolute right-0 top-12 w-[420px] rounded-lg border bg-background shadow-xl z-50 p-4 flex">
              <div className="flex-1 space-y-3">
                <p className="text-sm font-medium">Select Date Range</p>
                <div className="flex gap-2 text-xs mb-2">
                  <div className="flex-1 px-2 py-1 rounded border bg-muted/50">
                    <span className="text-muted-foreground">From:</span>{" "}
                    <span className="font-medium">{tempStartDate || "—"}</span>
                  </div>
                  <div className="flex-1 px-2 py-1 rounded border bg-muted/50">
                    <span className="text-muted-foreground">To:</span>{" "}
                    <span className="font-medium">{tempEndDate || "—"}</span>
                  </div>
                </div>
                <RangeCalendar
                  month={calendarMonth}
                  startDate={tempStartDate}
                  endDate={tempEndDate}
                  onMonthChange={setCalendarMonth}
                  onSelectDate={handleSelectDate}
                />
              </div>
              <div className="w-36 space-y-2 border-l pl-4 ml-4">
                <p className="text-xs text-muted-foreground font-medium mb-3">Quick Select</p>
                {[
                  { key: "today", label: "Today" },
                  { key: "24h", label: "Last 24 hours" },
                  { key: "7d", label: "Last 7 days" },
                  { key: "30d", label: "Last 30 days" },
                  { key: "mtd", label: "Month to date" },
                  { key: "ytd", label: "Year to date" },
                ].map(({ key, label }) => (
                  <Button
                    key={key}
                    variant="ghost"
                    size="sm"
                    className="w-full justify-start h-7 text-xs"
                    onClick={() => applyPreset(key)}
                  >
                    {label}
                  </Button>
                ))}
                <div className="border-t pt-3 mt-3 space-y-2">
                  <Button
                    size="sm"
                    className="w-full h-8"
                    onClick={applyCustomDateRange}
                    disabled={!tempStartDate || !tempEndDate}
                  >
                    Apply
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full h-8"
                    onClick={() => setDateRangeOpen(false)}
                  >
                    Cancel
                  </Button>
                  {(filters.startDate || filters.endDate) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="w-full h-8 text-muted-foreground"
                      onClick={() => {
                        setTempStartDate("");
                        setTempEndDate("");
                        applyPreset("all");
                      }}
                    >
                      <X className="h-3 w-3 mr-1" />
                      Clear
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}
          {filtersOpen && (
            <div className="absolute right-0 top-12 w-80 rounded-lg border bg-background shadow-xl z-50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">Filters</p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2"
                  onClick={() => setFilters((f) => ({ ...f, symbols: [], side: "", outcome: "", text: "" }))}
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
                <Label>Outcome</Label>
                <Select
                  value={filters.outcome}
                  onValueChange={(v) => setFilters((f) => ({ ...f, outcome: v }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="All" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">All</SelectItem>
                    <SelectItem value="win">Winners (P&L &gt; 0)</SelectItem>
                    <SelectItem value="loss">Losers (P&L ≤ 0)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="history-filter-text">Search</Label>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    id="history-filter-text"
                    placeholder="Symbol, side, strategy"
                    value={filters.text}
                    onChange={(e) => setFilters((f) => ({ ...f, text: e.target.value }))}
                    className="h-8 pl-8 text-sm"
                  />
                </div>
              </div>
            </div>
          )}
          <Button variant="outline" size="sm" className="gap-2">
            <Download className="h-4 w-4" />
            Export CSV
          </Button>
        </div>
        </div>

        {/* Stats Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className={cn(
            (displayStats.totalPnL ?? 0) >= 0 
              ? "border-emerald-500/30 bg-emerald-500/5" 
              : "border-red-500/30 bg-red-500/5"
          )}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Month PnL</span>
                {(displayStats.totalPnL ?? 0) >= 0 
                  ? <ArrowUpRight className="h-4 w-4 text-emerald-500" />
                  : <ArrowDownRight className="h-4 w-4 text-red-500" />
                }
              </div>
              <p className={cn(
                "text-2xl font-bold",
                (displayStats.totalPnL ?? 0) >= 0 ? "text-emerald-500" : "text-red-500"
              )}>
                {(displayStats.totalPnL ?? 0) >= 0 ? "+" : ""}${(displayStats.totalPnL ?? 0).toFixed(2)}
              </p>
              <p className="text-xs text-muted-foreground mt-1">{displayStats.totalTrades} trades</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Win Rate</span>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">{(displayStats.winRate ?? 0).toFixed(1)}%</p>
              <p className="text-xs text-muted-foreground mt-1">
                Avg win: ${(displayStats.avgWin ?? 0).toFixed(2)} / loss: ${Math.abs(displayStats.avgLoss ?? 0).toFixed(2)}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Profit Factor</span>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">{(displayStats.profitFactor ?? 0).toFixed(2)}</p>
              <p className="text-xs text-muted-foreground mt-1">Sharpe: {(displayStats.sharpe ?? 0).toFixed(2)}</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Best / Worst</span>
                <History className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-lg font-bold text-emerald-500">+${(displayStats.maxWin ?? displayStats.largestWin ?? 0).toFixed(2)}</span>
                <span className="text-muted-foreground">/</span>
                <span className="text-lg font-bold text-red-500">${(displayStats.maxLoss ?? displayStats.largestLoss ?? 0).toFixed(2)}</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="trades" className="space-y-4">
          <TabsList className="bg-muted/50">
            <TabsTrigger value="trades" className="gap-2">
              <History className="h-4 w-4" />
              Trades
            </TabsTrigger>
            <TabsTrigger value="daily" className="gap-2">
              <Calendar className="h-4 w-4" />
              Daily PnL
            </TabsTrigger>
          </TabsList>

          {/* Trades Tab */}
          <TabsContent value="trades" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <CardTitle className="text-base font-medium">Trade Log</CardTitle>
                    <CardDescription>All executed trades • Click row for details</CardDescription>
                  </div>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search trades..."
                      value={filters.text}
                      onChange={(e) => setFilters((f) => ({ ...f, text: e.target.value }))}
                      className="pl-9 w-full sm:w-[250px]"
                    />
                  </div>
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
                        <th className="text-right font-medium text-muted-foreground py-2 pr-4">Entry</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-4">Exit</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-4">PnL</th>
                        <th className="text-right font-medium text-muted-foreground py-2 pr-4">Fees</th>
                        <th className="text-left font-medium text-muted-foreground py-2">Strategy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedTrades.map((trade: any, idx: number) => {
                        const netPnl = (trade.pnl ?? 0) - (trade.fees ?? 0);
                        return (
                          <tr 
                            key={trade.id || idx} 
                            className="border-b border-border/30 last:border-0 hover:bg-muted/30 cursor-pointer transition-colors"
                            onClick={() => setSelectedTrade(trade)}
                          >
                            <td className="py-3 pr-4 font-mono text-xs text-muted-foreground whitespace-nowrap">
                              {trade.timestamp ? new Date(trade.timestamp).toLocaleString() : trade.time}
                            </td>
                            <td className="py-3 pr-4 font-medium">{trade.symbol}</td>
                            <td className="py-3 pr-4">
                              <Badge 
                                variant="outline" 
                                className={cn(
                                  "text-xs",
                                  (trade.side || "").toLowerCase() === "buy" || (trade.side || "").toLowerCase() === "long"
                                    ? "border-emerald-500/50 text-emerald-500" 
                                    : "border-red-500/50 text-red-500"
                                )}
                              >
                                {(trade.side || "").toUpperCase()}
                              </Badge>
                            </td>
                            <td className="py-3 pr-4 text-right font-mono">{formatQuantity(trade.size ?? trade.quantity)}</td>
                            <td className="py-3 pr-4 text-right font-mono">${(trade.entry_price ?? 0).toLocaleString()}</td>
                            <td className="py-3 pr-4 text-right font-mono">${(trade.exit_price ?? 0).toLocaleString()}</td>
                            <td className={cn(
                              "py-3 pr-4 text-right font-mono font-medium",
                              netPnl >= 0 ? "text-emerald-500" : "text-red-500"
                            )}>
                              {netPnl >= 0 ? "+" : ""}${netPnl.toFixed(2)}
                            </td>
                            <td className="py-3 pr-4 text-right font-mono text-yellow-400">
                              -${(trade.fees ?? 0).toFixed(2)}
                            </td>
                            <td className="py-3 text-xs text-muted-foreground">
                              {trade.strategy || trade.strategy_id || trade.profile || trade.profile_id || "—"}
                            </td>
                          </tr>
                        );
                      })}
                      {!filteredTrades.length && !isLoading && (
                        <tr>
                          <td colSpan={9} className="py-8 text-center text-muted-foreground">No trades found.</td>
                        </tr>
                      )}
                      {isLoading && (
                        <tr>
                          <td colSpan={9} className="py-8 text-center">
                            <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t">
                  <p className="text-sm text-muted-foreground">
                    Showing {(page - 1) * 20 + 1}-{Math.min(page * 20, filteredTrades.length)} of {filteredTrades.length} trades
                  </p>
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="icon" className="h-8 w-8" disabled={page === 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="px-3 text-sm text-muted-foreground">
                      {page} / {totalPages}
                    </span>
                    <Button variant="outline" size="icon" className="h-8 w-8" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Daily PnL Tab */}
          <TabsContent value="daily" className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium">Daily P&L</CardTitle>
                <CardDescription>Net performance by day (after fees)</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-[300px]">
                  {dailyPnL.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dailyPnL} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                        <XAxis 
                          dataKey="date" 
                          axisLine={false}
                          tickLine={false}
                          tick={{ fontSize: 10, fill: '#64748b' }}
                          tickFormatter={(date) => {
                            const d = new Date(date);
                            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                          }}
                        />
                        <YAxis 
                          axisLine={false}
                          tickLine={false}
                          tick={{ fontSize: 10, fill: '#64748b' }}
                          tickFormatter={(v) => `$${v}`}
                          width={50}
                        />
                        <RechartsTooltip
                          contentStyle={{
                            backgroundColor: 'hsl(var(--card))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: '8px',
                            fontSize: '12px',
                            padding: '12px',
                          }}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length) return null;
                            const data = payload[0].payload;
                            const netPnl = data.netPnl ?? data.pnl ?? 0;
                            const grossPnl = data.pnl ?? 0;
                            const fees = data.fees ?? 0;
                            return (
                              <div className="bg-card border rounded-lg p-3 shadow-lg space-y-2">
                                <p className="font-medium text-sm">{new Date(data.date).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</p>
                                <div className="space-y-1 text-xs">
                                  <div className="flex justify-between gap-4">
                                    <span className="text-muted-foreground">Gross P&L</span>
                                    <span className={cn("font-mono", grossPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                                      {grossPnl >= 0 ? "+" : ""}${grossPnl.toFixed(2)}
                                    </span>
                                  </div>
                                  <div className="flex justify-between gap-4">
                                    <span className="text-muted-foreground">Fees</span>
                                    <span className="font-mono text-amber-500">-${fees.toFixed(2)}</span>
                                  </div>
                                  <div className="flex justify-between gap-4 pt-1 border-t">
                                    <span className="font-medium">Net P&L</span>
                                    <span className={cn("font-mono font-bold", netPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
                                      {netPnl >= 0 ? "+" : ""}${netPnl.toFixed(2)}
                                    </span>
                                  </div>
                                  <div className="flex justify-between gap-4 pt-1 border-t text-muted-foreground">
                                    <span>{data.trades} trades</span>
                                    <span>{data.wins}W / {data.losses}L ({data.winRate}%)</span>
                                  </div>
                                </div>
                              </div>
                            );
                          }}
                        />
                        <Bar 
                          dataKey="netPnl" 
                          radius={[4, 4, 0, 0]}
                          fill="#10b981"
                        >
                          {dailyPnL.map((entry, index) => (
                            <Cell 
                              key={`cell-${index}`} 
                              fill={(entry.netPnl ?? entry.pnl ?? 0) >= 0 ? '#10b981' : '#ef4444'} 
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-muted-foreground">
                      No daily P&L data available
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
        
        {/* Trade Detail Sheet */}
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
            entryPrice: selectedTrade.entry_price || selectedTrade.entryPrice,
            exitPrice: selectedTrade.exit_price || selectedTrade.exitPrice,
            entryTime: selectedTrade.entry_time || selectedTrade.entryTime,
            pnl: selectedTrade.pnl,
            fees: selectedTrade.fees,
            strategy: selectedTrade.strategy || selectedTrade.strategy_id,
            profile: selectedTrade.profile || selectedTrade.profile_id,
            latency: selectedTrade.latency_ms,
            slippage: selectedTrade.slippage_bps,
            exitReason: selectedTrade.exitReason || selectedTrade.exit_reason,
            pnlPercent: selectedTrade.pnlPercent,
          } : null}
        />
      </div>
    </TooltipProvider>
  );
}
