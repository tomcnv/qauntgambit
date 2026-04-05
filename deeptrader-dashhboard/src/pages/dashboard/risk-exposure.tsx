import { useState, useMemo } from "react";
import {
  format,
  parseISO,
  subDays,
  startOfMonth,
  startOfYear,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addDays,
  addMonths,
  isSameDay,
  isSameMonth,
  isWithinInterval,
} from "date-fns";
import {
  Target,
  TrendingUp,
  TrendingDown,
  Percent,
  DollarSign,
  Loader2,
  Calendar as CalendarIcon,
  X,
  ChevronLeft,
  ChevronRight,
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
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Progress } from "../../components/ui/progress";
import { cn } from "../../lib/utils";
import { TooltipProvider } from "../../components/ui/tooltip";
import { useDashboardRisk, useBotPositions, useRiskLimits, useTradeHistory } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { RunBar } from "../../components/run-bar";

// Custom range calendar component
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
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="font-medium">{format(month, "MMMM yyyy")}</span>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onMonthChange(addMonths(month, 1))}>
          <ChevronRight className="h-4 w-4" />
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

export default function RiskExposurePage() {
  const [timeRange, setTimeRange] = useState("24h");
  const [dateRange, setDateRange] = useState<{ start: string; end: string }>({ start: "", end: "" });
  const [dateRangeOpen, setDateRangeOpen] = useState(false);
  const [tempStartDate, setTempStartDate] = useState("");
  const [tempEndDate, setTempEndDate] = useState("");
  const [calendarMonth, setCalendarMonth] = useState<Date>(new Date());
  const { level: scopeLevel, exchangeAccountId } = useScopeStore();

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
      default:
        start = subDays(new Date(), 1);
    }
    
    setTimeRange(preset);
    setDateRange({
      start: format(start, "yyyy-MM-dd"),
      end: format(end, "yyyy-MM-dd"),
    });
    setDateRangeOpen(false);
  };

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

  const applyCustomDateRange = () => {
    if (tempStartDate && tempEndDate) {
      setDateRange({ start: tempStartDate, end: tempEndDate });
      setTimeRange("custom");
      setDateRangeOpen(false);
    }
  };

  const clearDateRange = () => {
    setTempStartDate("");
    setTempEndDate("");
    setDateRange({ start: "", end: "" });
    setTimeRange("24h");
    applyPreset("24h");
  };

  const toggleDateRange = () => {
    if (!dateRangeOpen) {
      setTempStartDate(dateRange.start);
      setTempEndDate(dateRange.end);
    }
    setDateRangeOpen(!dateRangeOpen);
  };

  // Fetch real data
  const { data: riskData, isLoading: loadingRisk } = useDashboardRisk({
    exchangeAccountId: scopeLevel === "exchange" ? exchangeAccountId ?? undefined : undefined,
  });
  const { data: positionsData, isLoading: loadingPositions } = useBotPositions(
    scopeLevel === "exchange" ? exchangeAccountId ?? undefined : undefined
  );
  const { data: limitsData } = useRiskLimits();
  const { data: tradeHistoryData, isLoading: loadingTrades, isFetching: fetchingTrades } = useTradeHistory({
    limit: 2000,
    startDate: dateRange.start || undefined,
    endDate: dateRange.end || undefined,
    exchangeAccountId: scopeLevel === "exchange" ? exchangeAccountId ?? undefined : undefined,
  });

  const isLoading = loadingRisk || loadingPositions || loadingTrades;

  // Extract metrics from risk data
  const metrics = riskData?.data ?? riskData ?? {};
  const leverage = metrics?.leverage ?? 1;
  const engineLimits = metrics?.limits ?? {};
  const policyLimits = limitsData?.policy ?? limitsData?.data ?? {};
  const maxLeverage = engineLimits?.max_leverage
    ?? engineLimits?.maxLeverage
    ?? policyLimits?.max_leverage
    ?? policyLimits?.maxLeverage
    ?? 10;

  // Build exposure data from positions (authoritative source for current exposure)
  const exposures = useMemo(() => {
    const colors = ["#f7931a", "#627eea", "#14f195", "#8b5cf6", "#ef4444", "#06b6d4", "#ec4899"];

    // Calculate from positions first (authoritative source)
    const positions = positionsData?.data ?? [];
    if (positions.length) {
      const grouped: Record<string, { net: number; gross: number }> = {};
      positions.forEach((p: any) => {
        const qty = parseFloat(p.quantity || p.size || 0) || 0;
        const price = parseFloat(p.mark_price || p.current_price || p.markPrice || p.entryPrice || p.entry_price || 0) || 0;
        const notional = Math.abs(qty * price);
        const side = (p.side || "").toUpperCase();
        // LONG/BUY = positive, everything else (SHORT/SELL) = negative
        const signed = (side === "LONG" || side === "BUY") ? notional : -notional;
        const symbol = p.symbol || "UNKNOWN";
        const current = grouped[symbol] || { net: 0, gross: 0 };
        current.net += signed;
        current.gross += notional;
        grouped[symbol] = current;
      });
      const totalGross = Object.values(grouped).reduce((s, v) => s + v.gross, 0) || 1;
      return Object.entries(grouped).map(([symbol, vals], idx) => ({
        symbol,
        net: vals.net,
        gross: vals.gross,
        percentage: ((vals.gross / totalGross) * 100).toFixed(1),
        color: colors[idx % colors.length],
      }));
    }

    // Fallback to API data if no positions
    const apiExposures = riskData?.data?.exposureBySymbol ?? [];
    if (apiExposures.length) {
      return apiExposures.map((row: any, idx: number) => ({
        symbol: row.symbol,
        net: row.net ?? row.netExposure ?? 0,
        gross: row.gross ?? row.grossExposure ?? row.exposure ?? 0,
        percentage: row.percentage ?? "",
        color: colors[idx % colors.length],
      }));
    }

    return [];
  }, [riskData, positionsData]);

  // Calculate totals from exposures (current positions)
  const totalGross = exposures.reduce((sum: number, s: any) => sum + (s.gross ?? s.exposure ?? 0), 0);
  const totalNet = exposures.reduce((sum: number, s: any) => sum + (s.net ?? 0), 0);

  // Period statistics from filtered trade history
  const periodStats = useMemo(() => {
    const trades = tradeHistoryData?.trades ?? [];
    const totalVolume = trades.reduce((sum: number, t: any) => {
      const size = Math.abs(parseFloat(t.size || t.quantity || 0));
      const price = parseFloat(t.exit_price || t.entry_price || t.price || 0);
      return sum + (size * price);
    }, 0);
    const totalPnl = trades.reduce((sum: number, t: any) => sum + (parseFloat(t.pnl) || 0), 0);
    const totalFees = trades.reduce((sum: number, t: any) => sum + (parseFloat(t.fees) || 0), 0);
    const tradeCount = trades.length;
    const winCount = trades.filter((t: any) => (parseFloat(t.pnl) || 0) > 0).length;
    const winRate = tradeCount > 0 ? (winCount / tradeCount) * 100 : 0;
    
    return { totalVolume, totalPnl, totalFees, tradeCount, winRate };
  }, [tradeHistoryData]);

  // Build exposure history from trade history (for the selected date range)
  // This shows trading activity/volume over time, not cumulative position exposure
  const exposureHistory = useMemo(() => {
    const trades = tradeHistoryData?.trades ?? [];
    if (!trades.length) {
      // If no trades in range, show current exposure as single point
      if (totalNet !== 0 || totalGross !== 0) {
        return [{ hour: format(new Date(), "MM-dd HH:mm"), net: totalNet, gross: totalGross }];
      }
      return [];
    }

    // Group trades by hour and show volume/exposure activity
    const hourlyData: Record<string, { net: number; gross: number; count: number }> = {};
    
    trades.forEach((t: any) => {
      const ts = t.timestamp || t.exit_time || t.entry_time;
      if (!ts) return;
      const date = new Date(ts);
      const hourKey = format(date, "MM-dd HH:00");
      
      const size = Math.abs(parseFloat(t.size || t.quantity || 0));
      const price = parseFloat(t.exit_price || t.entry_price || t.price || 0);
      const notional = size * price;
      const side = (t.side || "").toUpperCase();
      const signed = (side === "BUY" || side === "LONG") ? notional : -notional;
      
      if (!hourlyData[hourKey]) {
        hourlyData[hourKey] = { net: 0, gross: 0, count: 0 };
      }
      hourlyData[hourKey].net += signed;
      hourlyData[hourKey].gross += notional;
      hourlyData[hourKey].count += 1;
    });

    // Convert to array and sort chronologically
    return Object.entries(hourlyData)
      .map(([hour, data]) => ({ hour, ...data }))
      .sort((a, b) => a.hour.localeCompare(b.hour));
  }, [tradeHistoryData, totalNet, totalGross]);

  // Leverage history derived from exposure history using account balance
  const leverageHistory = useMemo(() => {
    const balance = metrics?.account_balance ?? metrics?.accountBalance ?? 0;
    if (!balance || !exposureHistory.length) return [];
    return exposureHistory.map((row: any) => ({
      ...row,
      leverage: balance > 0 ? Math.abs(row.gross) / balance : 0,
    }));
  }, [exposureHistory, metrics]);

  const marginData = useMemo(() => {
    if (riskData?.data?.margin) return riskData.data.margin;
    const total = metrics?.account_balance ?? metrics?.accountBalance ?? 0;
    const exposure = totalGross; // Use calculated gross exposure
    const used = exposure > 0 ? exposure / (leverage || 1) : 0;
    const available = total - used;
    const maintenanceMargin = used * 0.5; // Rough estimate
    const liquidationDistance = total > 0 ? ((total - maintenanceMargin) / total * 100) : 100;
    return {
      used,
      available,
      total,
      maintenanceMargin,
      liquidationDistance: Math.max(0, liquidationDistance).toFixed(1),
    };
  }, [riskData, metrics, leverage, totalGross]);

  return (
    <TooltipProvider>
      <RunBar />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Exposure & Leverage</h1>
            <p className="text-sm text-muted-foreground">
              Current and historical exposure analysis
            </p>
          </div>
          <div className="flex items-center gap-2 relative">
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            
            {/* Quick presets */}
            <div className="flex rounded-lg border bg-muted/50 p-1">
              {[
                { key: "today", label: "Today" },
                { key: "24h", label: "24h" },
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
              <CalendarIcon className="h-4 w-4" />
              {timeRange === "custom" && dateRange.start && dateRange.end
                ? `${dateRange.start} → ${dateRange.end}`
                : "Custom"}
            </Button>

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
                    {(dateRange.start || dateRange.end) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="w-full h-8 text-muted-foreground"
                        onClick={clearDateRange}
                      >
                        <X className="h-3 w-3 mr-1" />
                        Clear
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Current State - Real-time metrics from open positions */}
        <div className="flex items-center gap-2 mb-2">
          <h2 className="text-sm font-medium text-muted-foreground">Current State</h2>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">LIVE</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Net Exposure</span>
                <Target className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className={`text-2xl font-bold ${totalNet < 0 ? 'text-red-500' : totalNet > 0 ? 'text-emerald-500' : ''}`}>
                {totalNet < 0 ? '-' : ''}${Math.abs(totalNet).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Gross: ${totalGross.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Leverage</span>
                <Percent className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">{leverage.toFixed(1)}x</p>
              <p className="text-xs text-muted-foreground mt-1">Max allowed: {maxLeverage}x</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Margin Used</span>
                <DollarSign className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">${marginData.used.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
              <Progress 
                value={marginData.total > 0 ? (marginData.used / marginData.total) * 100 : 0} 
                className="h-1.5 mt-2" 
              />
            </CardContent>
          </Card>

          <Card className={cn(
            parseFloat(String(marginData.liquidationDistance)) > 50 
              ? "border-emerald-500/30 bg-emerald-500/5" 
              : parseFloat(String(marginData.liquidationDistance)) > 20 
                ? "border-amber-500/30 bg-amber-500/5"
                : "border-red-500/30 bg-red-500/5"
          )}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Liq. Distance</span>
                <TrendingUp className={cn(
                  "h-4 w-4",
                  parseFloat(String(marginData.liquidationDistance)) > 50 ? "text-emerald-500" : 
                  parseFloat(String(marginData.liquidationDistance)) > 20 ? "text-amber-500" : "text-red-500"
                )} />
              </div>
              <p className={cn(
                "text-2xl font-bold",
                parseFloat(String(marginData.liquidationDistance)) > 50 ? "text-emerald-500" : 
                parseFloat(String(marginData.liquidationDistance)) > 20 ? "text-amber-500" : "text-red-500"
              )}>
                {marginData.liquidationDistance}%
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {parseFloat(String(marginData.liquidationDistance)) > 50 ? "Safe zone" : 
                 parseFloat(String(marginData.liquidationDistance)) > 20 ? "Caution" : "Danger zone"}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Period Summary - affected by date filter */}
        <Card className={cn(fetchingTrades && "opacity-75 transition-opacity")}>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-medium flex items-center gap-2">
                  Period Summary
                  {fetchingTrades && (
                    <span className="inline-flex items-center gap-1.5 text-xs font-normal text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Loading...
                    </span>
                  )}
                </CardTitle>
                <CardDescription>
                  Trading activity for selected period
                  {dateRange.start && dateRange.end && (
                    <span className="ml-1 text-primary">({dateRange.start} → {dateRange.end})</span>
                  )}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {loadingTrades && !tradeHistoryData ? (
              <div className="flex items-center justify-center h-20">
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Loading trade history...</p>
                </div>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Total Trades</p>
                  <p className="text-xl font-bold">{periodStats.tradeCount}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Volume Traded</p>
                  <p className="text-xl font-bold">${periodStats.totalVolume.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Period P&L</p>
                  <p className={cn(
                    "text-xl font-bold",
                    periodStats.totalPnl > 0 ? "text-emerald-500" : periodStats.totalPnl < 0 ? "text-red-500" : ""
                  )}>
                    {periodStats.totalPnl >= 0 ? "+" : ""}${periodStats.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Total Fees</p>
                  <p className="text-xl font-bold text-muted-foreground">${periodStats.totalFees.toLocaleString(undefined, { maximumFractionDigits: 2 })}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Win Rate</p>
                  <p className={cn(
                    "text-xl font-bold",
                    periodStats.winRate >= 50 ? "text-emerald-500" : "text-amber-500"
                  )}>
                    {periodStats.winRate.toFixed(1)}%
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-6 lg:grid-cols-3">
          {/* Exposure by Symbol */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Exposure by Symbol</CardTitle>
              <CardDescription>Current allocation</CardDescription>
            </CardHeader>
            <CardContent>
              {exposures.length > 0 ? (
                <>
                  <div className="h-[200px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={exposures}
                          cx="50%"
                          cy="50%"
                          innerRadius={50}
                          outerRadius={80}
                          paddingAngle={5}
                          dataKey="gross"
                        >
                          {exposures.map((entry: any, index: number) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <RechartsTooltip
                          contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px' }}
                          formatter={(value: number) => [`$${value.toLocaleString()}`, 'Exposure']}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="space-y-2 mt-4">
                    {exposures.map((item: any) => (
                      <div key={item.symbol} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: item.color }} />
                          <span className="text-sm font-medium">{item.symbol}</span>
                        </div>
                        <div className="text-right">
                        <span className="text-sm font-mono">
                          ${ (item.gross ?? item.exposure ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 }) }
                        </span>
                        <span className="text-xs text-muted-foreground ml-2">{item.percentage ?? ""}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-muted-foreground">
                  No exposure data
                </div>
              )}
            </CardContent>
          </Card>

          {/* Trading Activity Over Time */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Trading Activity</CardTitle>
              <CardDescription>Hourly trade volume for selected period</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[280px]">
                {exposureHistory.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={exposureHistory} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                      <defs>
                        <linearGradient id="netGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                      <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} interval={3} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(v) => `$${v/1000}k`} width={50} />
                      <RechartsTooltip
                        contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                        formatter={(value: number) => [`$${value.toLocaleString()}`, '']}
                      />
                      <Area type="monotone" dataKey="net" stroke="#8b5cf6" strokeWidth={2} fill="url(#netGradient)" name="Net" />
                      <Area type="monotone" dataKey="gross" stroke="#64748b" strokeWidth={1} fill="none" strokeDasharray="4 4" name="Gross" />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted-foreground">
                    No trades in selected period
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Leverage & Margin Details */}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Volume by Hour</CardTitle>
              <CardDescription>Leverage exposure during trading activity</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[200px]">
                {leverageHistory.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={leverageHistory} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                      <defs>
                        <linearGradient id="levGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
                      <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} interval={5} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(v) => `${v}x`} width={35} domain={[0, Math.max(5, maxLeverage)]} />
                      <ReferenceLine y={maxLeverage} stroke="#ef4444" strokeDasharray="5 5" />
                      <RechartsTooltip
                        contentStyle={{ backgroundColor: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                        formatter={(value: number) => [`${value.toFixed(2)}x`, 'Leverage']}
                      />
                      <Area type="monotone" dataKey="leverage" stroke="#f59e0b" strokeWidth={2} fill="url(#levGradient)" />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-muted-foreground">
                    No trades in selected period
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Margin Status</CardTitle>
              <CardDescription>Account margin breakdown</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Total Equity</span>
                  <span className="font-mono font-medium">${marginData.total.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Used Margin</span>
                  <span className="font-mono">${marginData.used.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Available</span>
                  <span className="font-mono text-emerald-500">${marginData.available.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                </div>
                <Progress 
                  value={marginData.total > 0 ? (marginData.used / marginData.total) * 100 : 0} 
                  className="h-2 mt-2" 
                />
              </div>
              
              <div className="pt-4 border-t space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Maintenance Margin</span>
                  <span className="font-mono">${marginData.maintenanceMargin.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Liquidation Distance</span>
                  <span className={cn(
                    "font-mono",
                    parseFloat(String(marginData.liquidationDistance)) > 50 ? "text-emerald-500" : 
                    parseFloat(String(marginData.liquidationDistance)) > 20 ? "text-amber-500" : "text-red-500"
                  )}>
                    {marginData.liquidationDistance}%
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </TooltipProvider>
  );
}
