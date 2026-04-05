import { useState } from "react";
import { RunBar } from "../../components/run-bar";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { useBacktests, useBacktestDetail, useDatasets, useCreateBacktest, useStrategies } from "../../lib/api/hooks";
import { BacktestRun, BacktestTrade } from "../../lib/api/types";
import { cn, formatQuantity } from "../../lib/utils";
import {
  Loader2,
  Play,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Calendar,
  DollarSign,
  Target,
  AlertCircle,
  CheckCircle2,
  Clock,
  XCircle,
  Database,
  FlaskConical,
} from "lucide-react";
import toast from "react-hot-toast";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";

const getStatusColor = (status: string) => {
  switch (status) {
    case "completed":
      return "bg-emerald-500/20 text-emerald-300 border-emerald-400/30";
    case "running":
      return "bg-blue-500/20 text-blue-300 border-blue-400/30";
    case "pending":
      return "bg-amber-500/20 text-amber-300 border-amber-400/30";
    case "failed":
      return "bg-rose-500/20 text-rose-300 border-rose-400/30";
    case "cancelled":
      return "bg-gray-500/20 text-gray-300 border-gray-400/30";
    default:
      return "bg-gray-500/20 text-gray-300 border-gray-400/30";
  }
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4" />;
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin" />;
    case "pending":
      return <Clock className="h-4 w-4" />;
    case "failed":
      return <XCircle className="h-4 w-4" />;
    case "cancelled":
      return <XCircle className="h-4 w-4" />;
    default:
      return <AlertCircle className="h-4 w-4" />;
  }
};

const formatDate = (dateString: string) => {
  return new Date(dateString).toLocaleString();
};

const formatCurrency = (value: number) => {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
};

const formatPercent = (value: number) => {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
};

const BacktestCard = ({ backtest, onView }: { backtest: BacktestRun; onView: (id: string) => void }) => {
  return (
    <Card className="border-white/5 bg-black/40 hover:bg-black/60 transition-colors cursor-pointer" onClick={() => onView(backtest.id)}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">{backtest.strategy_id}</CardTitle>
            <p className="text-sm text-muted-foreground mt-1">{backtest.symbol} • {backtest.exchange}</p>
          </div>
          <Badge className={cn("rounded-full px-3 py-1 text-xs flex items-center gap-1", getStatusColor(backtest.status))}>
            {getStatusIcon(backtest.status)}
            {backtest.status.toUpperCase()}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">Period</p>
            <p className="text-white">{formatDate(backtest.start_date).split(",")[0]}</p>
            <p className="text-white">to {formatDate(backtest.end_date).split(",")[0]}</p>
          </div>
          {backtest.status === "completed" && backtest.total_return_percent !== undefined && (
            <>
              <div>
                <p className="text-muted-foreground">Return</p>
                <p className={cn("text-lg font-semibold", backtest.total_return_percent >= 0 ? "text-emerald-400" : "text-rose-400")}>
                  {formatPercent(backtest.total_return_percent)}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Sharpe Ratio</p>
                <p className="text-white">{backtest.sharpe_ratio?.toFixed(2) || "N/A"}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Max Drawdown</p>
                <p className="text-rose-400">{formatPercent(backtest.max_drawdown_percent || 0)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Win Rate</p>
                <p className="text-white">{(backtest.win_rate || 0) * 100}%</p>
              </div>
              <div>
                <p className="text-muted-foreground">Total Trades</p>
                <p className="text-white">{backtest.total_trades || 0}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Profit Factor</p>
                <p className="text-white">{backtest.profit_factor?.toFixed(2) || "N/A"}</p>
              </div>
            </>
          )}
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
          <span>Created: {formatDate(backtest.created_at)}</span>
          {backtest.completed_at && <span>Completed: {formatDate(backtest.completed_at)}</span>}
        </div>
      </CardContent>
    </Card>
  );
};

const BacktestDetailView = ({ backtestId, onBack }: { backtestId: string; onBack: () => void }) => {
  const { data, isLoading } = useBacktestDetail(backtestId);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!data) {
    return (
      <Card className="border-white/5 bg-black/40">
        <CardContent className="py-12 text-center">
          <p className="text-muted-foreground">Backtest not found</p>
          <Button onClick={onBack} className="mt-4" variant="outline">
            Back to List
          </Button>
        </CardContent>
      </Card>
    );
  }

  const { backtest, trades, equityCurve } = data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Button onClick={onBack} variant="outline" className="mb-4">
            ← Back to Backtests
          </Button>
          <h2 className="text-2xl font-semibold">{backtest.strategy_id}</h2>
          <p className="text-muted-foreground">{backtest.symbol} • {backtest.exchange}</p>
        </div>
        <Badge className={cn("rounded-full px-3 py-1 text-xs flex items-center gap-1", getStatusColor(backtest.status))}>
          {getStatusIcon(backtest.status)}
          {backtest.status.toUpperCase()}
        </Badge>
      </div>

      {/* Performance Metrics */}
      {backtest.status === "completed" && (
        <div className="grid gap-4 md:grid-cols-4">
          <Card className="border-white/5 bg-black/40">
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Return</p>
              <p className={cn("mt-2 text-3xl font-semibold", backtest.total_return_percent && backtest.total_return_percent >= 0 ? "text-emerald-400" : "text-rose-400")}>
                {backtest.total_return_percent !== undefined ? formatPercent(backtest.total_return_percent) : "N/A"}
              </p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/40">
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Sharpe Ratio</p>
              <p className="mt-2 text-3xl font-semibold">{backtest.sharpe_ratio?.toFixed(2) || "N/A"}</p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/40">
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Max Drawdown</p>
              <p className="mt-2 text-3xl font-semibold text-rose-400">
                {backtest.max_drawdown_percent !== undefined ? formatPercent(backtest.max_drawdown_percent) : "N/A"}
              </p>
            </CardContent>
          </Card>
          <Card className="border-white/5 bg-black/40">
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Win Rate</p>
              <p className="mt-2 text-3xl font-semibold">{backtest.win_rate ? (backtest.win_rate * 100).toFixed(1) + "%" : "N/A"}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Equity Curve */}
      {equityCurve.length > 0 && (
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle>Equity Curve</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={equityCurve}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                <XAxis
                  dataKey="time"
                  tick={{ fill: "#9ca3af" }}
                  tickFormatter={(value) => new Date(value).toLocaleDateString()}
                />
                <YAxis tick={{ fill: "#9ca3af" }} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: "8px" }}
                  labelFormatter={(value) => new Date(value).toLocaleString()}
                  formatter={(value: number) => formatCurrency(value)}
                />
                <Legend />
                <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} name="Equity" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Trades Table */}
      {trades.length > 0 && (
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle>Recent Trades ({trades.length} total)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10">
                    <th className="text-left py-2 text-muted-foreground">Time</th>
                    <th className="text-left py-2 text-muted-foreground">Side</th>
                    <th className="text-right py-2 text-muted-foreground">Entry</th>
                    <th className="text-right py-2 text-muted-foreground">Exit</th>
                    <th className="text-right py-2 text-muted-foreground">Size</th>
                    <th className="text-right py-2 text-muted-foreground">PnL</th>
                    <th className="text-right py-2 text-muted-foreground">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 50).map((trade) => (
                    <tr key={trade.id} className="border-b border-white/5">
                      <td className="py-2">{formatDate(trade.entry_time)}</td>
                      <td className="py-2">
                        <Badge variant={trade.side === "buy" ? "default" : "outline"} className="text-xs">
                          {trade.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="text-right py-2">{formatCurrency(trade.entry_price)}</td>
                      <td className="text-right py-2">{trade.exit_price ? formatCurrency(trade.exit_price) : "-"}</td>
                      <td className="text-right py-2">{formatQuantity(trade.size)}</td>
                      <td className={cn("text-right py-2 font-semibold", trade.pnl && trade.pnl >= 0 ? "text-emerald-400" : "text-rose-400")}>
                        {trade.pnl !== undefined ? formatCurrency(trade.pnl) : "-"}
                      </td>
                      <td className="text-right py-2">{trade.duration_seconds ? `${trade.duration_seconds}s` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const CreateBacktestForm = ({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) => {
  const { data: strategies } = useStrategies();
  const { data: datasets } = useDatasets();
  const createBacktest = useCreateBacktest();

  const [formData, setFormData] = useState({
    strategy_id: "",
    symbol: "",
    exchange: "okx",
    start_date: "",
    end_date: "",
    initial_capital: 10000,
    commission_per_trade: 0.001,
    slippage_model: "fixed",
    slippage_bps: 5.0,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createBacktest.mutateAsync(formData);
      toast.success("Backtest created successfully");
      onSuccess();
      onClose();
    } catch (error: any) {
      toast.error(error.response?.data?.message || "Failed to create backtest");
    }
  };

  return (
    <Card className="border-white/5 bg-black/40">
      <CardHeader>
        <CardTitle>Create New Backtest</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="strategy_id">Strategy</Label>
            <Select
              id="strategy_id"
              value={formData.strategy_id}
              onChange={(e) => setFormData({ ...formData, strategy_id: e.target.value })}
              options={[
                { value: "", label: "Select strategy" },
                ...(strategies?.strategies.map((s) => ({ value: s.id, label: s.name })) || []),
              ]}
            />
          </div>
          <div>
            <Label htmlFor="symbol">Symbol</Label>
            <Select
              id="symbol"
              value={formData.symbol}
              onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}
              options={[
                { value: "", label: "Select symbol" },
                ...(datasets?.datasets.map((d) => ({ value: d.symbol, label: d.symbol })) || []),
              ]}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="start_date">Start Date</Label>
              <Input
                id="start_date"
                type="datetime-local"
                value={formData.start_date}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                required
              />
            </div>
            <div>
              <Label htmlFor="end_date">End Date</Label>
              <Input
                id="end_date"
                type="datetime-local"
                value={formData.end_date}
                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="initial_capital">Initial Capital</Label>
              <Input
                id="initial_capital"
                type="number"
                value={formData.initial_capital}
                onChange={(e) => setFormData({ ...formData, initial_capital: parseFloat(e.target.value) })}
                required
              />
            </div>
            <div>
              <Label htmlFor="commission_per_trade">Commission per Trade</Label>
              <Input
                id="commission_per_trade"
                type="number"
                step="0.0001"
                value={formData.commission_per_trade}
                onChange={(e) => setFormData({ ...formData, commission_per_trade: parseFloat(e.target.value) })}
                required
              />
            </div>
          </div>
          <div className="flex gap-4">
            <Button type="submit" disabled={createBacktest.isPending}>
              {createBacktest.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Create Backtest
                </>
              )}
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};

export default function ResearchPage() {
  const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [filterStatus, setFilterStatus] = useState<string>("");
  const { data, isLoading } = useBacktests({ status: filterStatus || undefined });

  if (selectedBacktestId) {
    return <BacktestDetailView backtestId={selectedBacktestId} onBack={() => setSelectedBacktestId(null)} />;
  }

  return (
    <>
      <RunBar variant="minimal" />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Quant Research Platform</h1>
          <p className="text-sm text-muted-foreground">Backtest strategies and analyze performance</p>
        </div>
        <div className="flex gap-3">
          <Button onClick={() => setShowCreateForm(!showCreateForm)}>
            <FlaskConical className="mr-2 h-4 w-4" />
            New Backtest
          </Button>
        </div>
      </div>

      {showCreateForm && (
        <CreateBacktestForm
          onClose={() => setShowCreateForm(false)}
          onSuccess={() => {
            setShowCreateForm(false);
          }}
        />
      )}

      {/* Filters */}
      <div className="flex gap-4">
        <Select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          options={[
            { value: "", label: "All Statuses" },
            { value: "pending", label: "Pending" },
            { value: "running", label: "Running" },
            { value: "completed", label: "Completed" },
            { value: "failed", label: "Failed" },
          ]}
        />
      </div>

      {/* Backtests List */}
      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : data?.backtests.length === 0 ? (
        <Card className="border-white/5 bg-black/40">
          <CardContent className="py-12 text-center">
            <Database className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <p className="text-muted-foreground">No backtests found</p>
            <p className="mt-2 text-sm text-muted-foreground">Create your first backtest to get started</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {data?.backtests.map((backtest) => (
            <BacktestCard key={backtest.id} backtest={backtest} onView={setSelectedBacktestId} />
          ))}
        </div>
      )}
      </div>
    </>
  );
}
