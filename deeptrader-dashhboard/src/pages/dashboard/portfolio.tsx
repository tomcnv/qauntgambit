import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  useStrategyPortfolio,
  useStrategyCorrelations,
  usePortfolioSummary,
} from "../../lib/api/hooks";
import { cn } from "../../lib/utils";
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  PieChart,
  Loader2,
  Activity,
  DollarSign,
  Target,
  AlertTriangle,
} from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  Cell,
  PieChart as RechartsPieChart,
  Pie,
} from "recharts";

const formatUsd = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};

const formatPercent = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
};

const formatNumber = (value: number | null | undefined, decimals = 2) => {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(decimals);
};

const COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

export default function PortfolioPage() {
  const [filters, setFilters] = useState({
    strategyName: "",
    startDate: "",
    endDate: "",
  });

  const { data: strategiesData, isLoading: strategiesLoading } = useStrategyPortfolio({
    strategyName: filters.strategyName || undefined,
    startDate: filters.startDate || undefined,
    endDate: filters.endDate || undefined,
    limit: 100,
  });

  const { data: correlationsData, isLoading: correlationsLoading } = useStrategyCorrelations({
    limit: 50,
  });

  const { data: summaryData, isLoading: summaryLoading } = usePortfolioSummary({
    limit: 30,
  });

  const strategies = strategiesData?.data || [];
  const correlations = correlationsData?.data || [];
  const summary = summaryData?.data || [];

  // Get latest summary
  const latestSummary = summary.length > 0 ? summary[0] : null;

  // Prepare strategy performance chart
  const strategyPerformanceChart = useMemo(() => {
    const latestStrategies = strategies
      .filter((s) => s.calculation_date === strategies[0]?.calculation_date)
      .slice(0, 10);
    
    return latestStrategies.map((s) => ({
      name: s.strategy_name,
      pnl: Number(s.total_pnl),
      return: Number(s.daily_return || 0) * 100,
      sharpe: Number(s.sharpe_ratio || 0),
    }));
  }, [strategies]);

  // Prepare correlation matrix data
  const correlationMatrix = useMemo(() => {
    const latestDate = correlations[0]?.calculation_date;
    if (!latestDate) return [];

    const latestCorrs = correlations.filter((c) => c.calculation_date === latestDate);
    const strategyNames = Array.from(
      new Set([
        ...latestCorrs.map((c) => c.strategy_a),
        ...latestCorrs.map((c) => c.strategy_b),
      ])
    ).sort();

    return strategyNames.map((nameA) => ({
      strategy: nameA,
      ...strategyNames.reduce((acc, nameB) => {
        if (nameA === nameB) {
          acc[nameB] = 1.0;
        } else {
          const corr = latestCorrs.find(
            (c) =>
              (c.strategy_a === nameA && c.strategy_b === nameB) ||
              (c.strategy_a === nameB && c.strategy_b === nameA)
          );
          acc[nameB] = corr ? Number(corr.correlation_coefficient || 0) : 0;
        }
        return acc;
      }, {} as Record<string, number>),
    }));
  }, [correlations]);

  // Prepare portfolio equity curve
  const portfolioEquityChart = useMemo(() => {
    return summary
      .slice(0, 30)
      .reverse()
      .map((s) => ({
        date: new Date(s.calculation_date).toLocaleDateString(),
        pnl: Number(s.total_portfolio_pnl),
        return: Number(s.portfolio_daily_return || 0) * 100,
      }));
  }, [summary]);

  // Risk budget allocation
  const riskBudgetData = useMemo(() => {
    const latestStrategies = strategies
      .filter((s) => s.calculation_date === strategies[0]?.calculation_date)
      .filter((s) => s.risk_budget_pct && Number(s.risk_budget_pct) > 0);
    
    return latestStrategies.map((s) => ({
      name: s.strategy_name,
      value: Number(s.risk_budget_pct || 0),
    }));
  }, [strategies]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Strategy Portfolio & Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Multi-strategy performance, correlations, and portfolio-level metrics
        </p>
      </div>

      {/* Filters */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="strategyName">Strategy Name</Label>
              <Input
                id="strategyName"
                placeholder="Filter by strategy"
                value={filters.strategyName}
                onChange={(e) => setFilters({ ...filters, strategyName: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="startDate">Start Date</Label>
              <Input
                id="startDate"
                type="date"
                value={filters.startDate}
                onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="endDate">End Date</Label>
              <Input
                id="endDate"
                type="date"
                value={filters.endDate}
                onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Portfolio Summary Cards */}
      {latestSummary && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card className="border-white/5 bg-black/30">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs uppercase tracking-[0.4em] text-muted-foreground">
                Total PnL
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <DollarSign className="h-4 w-4 text-muted-foreground" />
                <p className={cn(
                  "text-2xl font-bold",
                  Number(latestSummary.total_portfolio_pnl) >= 0 ? "text-emerald-400" : "text-red-400"
                )}>
                  {formatUsd(Number(latestSummary.total_portfolio_pnl))}
                </p>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatUsd(Number(latestSummary.total_realized_pnl))} realized
              </p>
            </CardContent>
          </Card>

          <Card className="border-white/5 bg-black/30">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs uppercase tracking-[0.4em] text-muted-foreground">
                Daily Return
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                {Number(latestSummary.portfolio_daily_return || 0) >= 0 ? (
                  <TrendingUp className="h-4 w-4 text-emerald-400" />
                ) : (
                  <TrendingDown className="h-4 w-4 text-red-400" />
                )}
                <p className={cn(
                  "text-2xl font-bold",
                  Number(latestSummary.portfolio_daily_return || 0) >= 0 ? "text-emerald-400" : "text-red-400"
                )}>
                  {formatPercent(Number(latestSummary.portfolio_daily_return))}
                </p>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                YTD: {formatPercent(Number(latestSummary.portfolio_ytd_return))}
              </p>
            </CardContent>
          </Card>

          <Card className="border-white/5 bg-black/30">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs uppercase tracking-[0.4em] text-muted-foreground">
                Sharpe Ratio
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
                <p className="text-2xl font-bold text-white">
                  {formatNumber(Number(latestSummary.portfolio_sharpe_ratio))}
                </p>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Max DD: {formatPercent(Number(latestSummary.portfolio_max_drawdown))}
              </p>
            </CardContent>
          </Card>

          <Card className="border-white/5 bg-black/30">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs uppercase tracking-[0.4em] text-muted-foreground">
                Risk Budget
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <Target className="h-4 w-4 text-muted-foreground" />
                <p className="text-2xl font-bold text-white">
                  {formatPercent(Number(latestSummary.risk_budget_utilization_pct))}
                </p>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {latestSummary.active_strategies_count} active strategies
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Portfolio Equity Curve */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Portfolio Equity Curve
            </CardTitle>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : portfolioEquityChart.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">No portfolio data available</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={portfolioEquityChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                  <XAxis dataKey="date" stroke="rgba(255,255,255,0.5)" />
                  <YAxis stroke="rgba(255,255,255,0.5)" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "rgba(0,0,0,0.9)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      borderRadius: "8px",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="pnl"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={{ fill: "#10b981", r: 3 }}
                    name="Total PnL"
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Risk Budget Allocation */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Risk Budget Allocation
            </CardTitle>
          </CardHeader>
          <CardContent>
            {strategiesLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : riskBudgetData.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">No risk budget data available</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <RechartsPieChart>
                  <Pie
                    data={riskBudgetData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent = 0 }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {riskBudgetData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </RechartsPieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Strategy Performance */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Strategy Performance
          </CardTitle>
        </CardHeader>
        <CardContent>
          {strategiesLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : strategies.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-sm text-muted-foreground">No strategy data available</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-white/10">
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Strategy
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Total PnL
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Daily Return
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Sharpe
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Win Rate
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Trades
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Risk Budget
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {strategies
                    .filter((s) => s.calculation_date === strategies[0]?.calculation_date)
                    .slice(0, 20)
                    .map((strategy) => (
                      <tr key={strategy.id} className="border-b border-white/5 hover:bg-white/5">
                        <td className="px-4 py-3 font-semibold text-white">{strategy.strategy_name}</td>
                        <td className={cn(
                          "px-4 py-3 text-right",
                          Number(strategy.total_pnl) >= 0 ? "text-emerald-400" : "text-red-400"
                        )}>
                          {formatUsd(Number(strategy.total_pnl))}
                        </td>
                        <td className={cn(
                          "px-4 py-3 text-right",
                          Number(strategy.daily_return || 0) >= 0 ? "text-emerald-400" : "text-red-400"
                        )}>
                          {formatPercent(Number(strategy.daily_return))}
                        </td>
                        <td className="px-4 py-3 text-right text-white">
                          {formatNumber(Number(strategy.sharpe_ratio))}
                        </td>
                        <td className="px-4 py-3 text-right text-white">
                          {formatPercent(Number(strategy.win_rate))}
                        </td>
                        <td className="px-4 py-3 text-right text-white">{strategy.total_trades}</td>
                        <td className="px-4 py-3 text-right text-white">
                          {formatPercent(Number(strategy.risk_budget_pct))}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Correlation Matrix */}
      {correlationMatrix.length > 0 && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Strategy Correlation Matrix
            </CardTitle>
          </CardHeader>
          <CardContent>
            {correlationsLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                        Strategy
                      </th>
                      {correlationMatrix[0] &&
                        Object.keys(correlationMatrix[0])
                          .filter((key) => key !== "strategy")
                          .map((key) => (
                            <th
                              key={key}
                              className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground"
                            >
                              {key}
                            </th>
                          ))}
                    </tr>
                  </thead>
                  <tbody>
                    {correlationMatrix.map((row, idx) => (
                      <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                        <td className="px-4 py-3 font-semibold text-white">{row.strategy}</td>
                        {Object.keys(row)
                          .filter((key) => key !== "strategy")
                          .map((key) => {
                            const value = (row as Record<string, number | string>)[key];
                            const numVal = typeof value === "number" ? value : Number(value);
                            const colorIntensity = Math.abs(numVal);
                            return (
                              <td
                                key={key}
                                className={cn(
                                  "px-4 py-3 text-center text-sm",
                                  numVal >= 0.7
                                    ? "bg-emerald-500/20 text-emerald-300"
                                    : numVal >= 0.3
                                    ? "bg-yellow-500/20 text-yellow-300"
                                    : numVal <= -0.3
                                    ? "bg-red-500/20 text-red-300"
                                    : "text-muted-foreground"
                                )}
                              >
                                {Number.isFinite(numVal) ? numVal.toFixed(2) : "—"}
                              </td>
                            );
                          })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}




