import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { useTCAAnalysis, useCapacityCurve, useProfileSpecs } from "../../lib/api/hooks";
import { TCAAnalysisItem, CapacityCurvePoint } from "../../lib/api/types";
import { cn } from "../../lib/utils";
import { useScopeStore } from "../../store/scope-store";
import {
  DollarSign,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Loader2,
  Filter,
} from "lucide-react";
import { BarChart3 } from "lucide-react";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";

const formatUsd = (value?: number | string | null) => {
  if (value === undefined || value === null) return "—";
  const numValue = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(numValue)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(numValue);
};

const formatBps = (value?: number | string | null) => {
  if (value === undefined || value === null) return "—";
  const numValue = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(numValue)) return "—";
  return `${numValue >= 0 ? "+" : ""}${numValue.toFixed(2)} bps`;
};

const formatPercent = (value?: number | string | null) => {
  if (value === undefined || value === null) return "—";
  const numValue = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(numValue)) return "—";
  return `${numValue >= 0 ? "+" : ""}${numValue.toFixed(2)}%`;
};

const TCATable = ({ data }: { data: TCAAnalysisItem[] }) => {
  if (data.length === 0) {
    return (
      <div className="rounded-2xl border border-white/5 bg-white/5 p-8 text-center">
        <p className="text-sm text-muted-foreground">No trade cost data available</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-white/10">
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Symbol
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Trades
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Volume
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Avg Slippage
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Avg Fees
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Total Cost
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.3em] text-muted-foreground">
              Cost Drag
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((item, idx) => (
            <tr
              key={`${item.symbol}-${item.profile_id || "none"}-${idx}`}
              className="border-b border-white/5 hover:bg-white/5"
            >
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-white">{item.symbol}</span>
                  {item.profile_id && (
                    <Badge variant="outline" className="text-xs">
                      {item.profile_id.slice(0, 8)}
                    </Badge>
                  )}
                </div>
              </td>
              <td className="px-4 py-3 text-right text-white">{item.total_trades}</td>
              <td className="px-4 py-3 text-right text-white">{formatUsd(item.total_volume)}</td>
              <td className={cn("px-4 py-3 text-right", (Number(item.avg_slippage_bps) || 0) > 5 ? "text-amber-400" : "text-white")}>
                {formatBps(item.avg_slippage_bps)}
              </td>
              <td className="px-4 py-3 text-right text-white">{formatUsd(item.avg_fees)}</td>
              <td className="px-4 py-3 text-right text-white">{formatUsd(item.total_cost)}</td>
              <td className={cn("px-4 py-3 text-right", (Number(item.avg_cost_pct) || 0) > 1 ? "text-red-400" : "text-white")}>
                {formatPercent(item.avg_cost_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const CapacityCurveChart = ({ curve }: { curve: CapacityCurvePoint[] }) => {
  if (curve.length === 0) {
    return (
      <div className="rounded-2xl border border-white/5 bg-white/5 p-8 text-center">
        <p className="text-sm text-muted-foreground">No capacity data available</p>
      </div>
    );
  }

  const chartData = curve.map((point) => ({
    bucket: point.notionalBucket,
    slippage: point.avgSlippageBps,
    fees: point.avgFees,
    trades: point.tradeCount,
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
        <XAxis dataKey="bucket" stroke="rgba(255,255,255,0.5)" fontSize={12} />
        <YAxis stroke="rgba(255,255,255,0.5)" fontSize={12} />
        <Tooltip
          contentStyle={{
            backgroundColor: "rgba(0,0,0,0.9)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: "8px",
          }}
        />
        <Legend />
        <Bar dataKey="slippage" fill="#f59e0b" name="Avg Slippage (bps)" />
        <Bar dataKey="fees" fill="#3b82f6" name="Avg Fees (USD)" />
      </BarChart>
    </ResponsiveContainer>
  );
};

export default function TCAPage() {
  const [filters, setFilters] = useState<{
    symbol?: string;
    profileId?: string;
    startDate?: string;
    endDate?: string;
    periodType?: "daily" | "weekly" | "monthly";
  }>({
    periodType: "daily",
  });

  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);

  const { botId } = useScopeStore();
  
  const { data: tcaData, isLoading: tcaLoading } = useTCAAnalysis(filters);
  const { data: capacityData, isLoading: capacityLoading } = useCapacityCurve(
    selectedProfileId,
    filters.startDate,
    filters.endDate
  );
  const { data: profilesData } = useProfileSpecs(botId);

  const analysis = tcaData?.data || [];
  const capacityCurve = capacityData?.curve || [];

  // Calculate summary metrics
  const summary = useMemo(() => {
    if (analysis.length === 0) return null;

    const totalTrades = analysis.reduce((sum, item) => sum + (Number(item.total_trades) || 0), 0);
    const totalVolume = analysis.reduce((sum, item) => sum + (Number(item.total_volume) || 0), 0);
    const totalCost = analysis.reduce((sum, item) => sum + (Number(item.total_cost) || 0), 0);
    const avgSlippage = analysis.reduce((sum, item) => sum + (Number(item.avg_slippage_bps) || 0), 0) / analysis.length;
    const avgCostDrag = analysis.reduce((sum, item) => sum + (Number(item.avg_cost_pct) || 0), 0) / analysis.length;

    return {
      totalTrades,
      totalVolume,
      totalCost,
      avgSlippage,
      avgCostDrag,
    };
  }, [analysis]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Trade Cost & Capacity</h1>
        <p className="text-sm text-muted-foreground">
          Analyze slippage, fees, and capacity limits to prove scalability
        </p>
      </div>

      {/* Filters */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <Label htmlFor="symbol">Symbol</Label>
              <Input
                id="symbol"
                placeholder="e.g., BTC-USDT-SWAP"
                value={filters.symbol || ""}
                onChange={(e) => setFilters({ ...filters, symbol: e.target.value || undefined })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="profile">Profile</Label>
              <Select
                id="profile"
                options={[
                  { value: "", label: "All Profiles" },
                  ...(profilesData?.specs?.map((p) => ({ value: p.id, label: p.name })) || []),
                ]}
                value={filters.profileId || ""}
                onChange={(e) => {
                  const profileId = e.target.value || undefined;
                  setFilters({ ...filters, profileId });
                  setSelectedProfileId(profileId || null);
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="period">Period Type</Label>
              <Select
                id="period"
                options={[
                  { value: "daily", label: "Daily" },
                  { value: "weekly", label: "Weekly" },
                  { value: "monthly", label: "Monthly" },
                ]}
                value={filters.periodType || "daily"}
                onChange={(e) => setFilters({ ...filters, periodType: e.target.value as any })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="startDate">Start Date</Label>
              <Input
                id="startDate"
                type="date"
                value={filters.startDate || ""}
                onChange={(e) => setFilters({ ...filters, startDate: e.target.value || undefined })}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary Metrics */}
      {summary && (
        <div className="grid gap-4 md:grid-cols-5">
          <Card className="border-white/5 bg-black/30">
            <CardContent className="p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Trades</p>
              <p className="mt-2 text-2xl font-semibold text-white">{summary.totalTrades}</p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/30">
            <CardContent className="p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Volume</p>
              <p className="mt-2 text-2xl font-semibold text-white">{formatUsd(summary.totalVolume)}</p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/30">
            <CardContent className="p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Cost</p>
              <p className="mt-2 text-2xl font-semibold text-white">{formatUsd(summary.totalCost)}</p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/30">
            <CardContent className="p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Avg Slippage</p>
              <p className={cn("mt-2 text-2xl font-semibold", (Number(summary.avgSlippage) || 0) > 5 ? "text-amber-400" : "text-white")}>
                {formatBps(summary.avgSlippage)}
              </p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/30">
            <CardContent className="p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Avg Cost Drag</p>
              <p className={cn("mt-2 text-2xl font-semibold", (Number(summary.avgCostDrag) || 0) > 1 ? "text-red-400" : "text-white")}>
                {formatPercent(summary.avgCostDrag)}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* TCA Analysis Table */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Cost Breakdown</CardTitle>
          <p className="mt-2 text-sm text-muted-foreground">
            Real-time trade cost data from live trading activity
          </p>
        </CardHeader>
        <CardContent>
          {tcaLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <p className="ml-3 text-sm text-muted-foreground">Loading trade cost data...</p>
            </div>
          ) : analysis.length === 0 ? (
            <div className="rounded-2xl border border-white/5 bg-white/5 p-8 text-center">
              <AlertCircle className="mx-auto h-12 w-12 text-muted-foreground" />
              <p className="mt-4 text-sm font-semibold text-white">No Trade Cost Data Available</p>
              <p className="mt-2 text-sm text-muted-foreground">
                TCA data is collected automatically when trades are executed.
                <br />
                Start trading to see cost analysis here.
              </p>
            </div>
          ) : (
            <TCATable data={analysis} />
          )}
        </CardContent>
      </Card>

      {/* Capacity Curves */}
      {selectedProfileId && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Capacity Curve: {profilesData?.specs?.find((p) => p.id === selectedProfileId)?.name || selectedProfileId}
            </CardTitle>
            <p className="mt-2 text-sm text-muted-foreground">
              Real-time performance vs notional size - helps identify capacity limits
            </p>
          </CardHeader>
          <CardContent>
            {capacityLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                <p className="ml-3 text-sm text-muted-foreground">Loading capacity data...</p>
              </div>
            ) : capacityCurve.length === 0 ? (
              <div className="rounded-2xl border border-white/5 bg-white/5 p-8 text-center">
                <AlertCircle className="mx-auto h-12 w-12 text-muted-foreground" />
                <p className="mt-4 text-sm font-semibold text-white">No Capacity Data</p>
                <p className="mt-2 text-sm text-muted-foreground">
                  No trades recorded for this profile yet. Execute trades to see capacity analysis.
                </p>
              </div>
            ) : (
              <CapacityCurveChart curve={capacityCurve} />
            )}
          </CardContent>
        </Card>
      )}

      {!selectedProfileId && (
        <Card className="border-white/5 bg-black/30">
          <CardContent className="p-8 text-center">
            <AlertCircle className="mx-auto h-12 w-12 text-muted-foreground" />
            <p className="mt-4 text-sm text-muted-foreground">
              Select a profile above to view capacity curve
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

