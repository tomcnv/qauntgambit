import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { useTradingOpsData } from "../../lib/api/hooks";
import { FastScalperRejectionRecord, RecentTrade, TradingPosition } from "../../lib/api/types";
import { cn, formatQuantity } from "../../lib/utils";
import { SystemStatus } from "../../components/dashboard/system-status";
import { useScopeStore } from "../../store/scope-store";
import { useBotInstances } from "../../lib/api/hooks";

const formatUsd = (value?: number) =>
  value === undefined || Number.isNaN(value)
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);

const formatLabel = (label: string) => label.replace(/_/g, " ");


const formatStatValue = (value: unknown) => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    const digits = Math.abs(value) >= 100 ? 0 : 2;
    return value.toFixed(digits);
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
};

const ExecutionStatsCard = ({ title, stats }: { title: string; stats?: Record<string, unknown> }) => (
  <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
    <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">{title}</p>
    {stats && Object.keys(stats).length > 0 ? (
      <div className="mt-2 grid grid-cols-2 gap-3">
        {Object.entries(stats).map(([label, value]) => (
          <div key={label}>
            <p className="text-[10px] uppercase tracking-[0.3em]">{formatLabel(label)}</p>
            <p className="text-white">{formatStatValue(value)}</p>
          </div>
        ))}
      </div>
    ) : (
      <p>No data reported.</p>
    )}
  </div>
);

const QualityStatsCard = ({ quality }: { quality?: Record<string, any> }) => {
  if (!quality || Object.keys(quality).length === 0) {
    return (
      <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Quality Monitor</p>
        <p>No quality stats available.</p>
      </div>
    );
  }

  const score = quality.score ?? quality.quality_score;
  const recent = quality.recent ?? {};
  const overall = quality.overall ?? {};
  const remainingEntries = Object.entries(quality).filter(
    ([key]) => !["score", "quality_score", "recent", "overall"].includes(key)
  );

  return (
    <div className="rounded-2xl border border-white/5 bg-white/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Quality Monitor</p>
        {score !== undefined && (
          <Badge variant={score >= 0.5 ? "success" : "warning"}>{score.toFixed(2)}</Badge>
        )}
      </div>
      {Object.keys(recent).length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Recent</p>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(recent).map(([label, value]) => (
              <div key={`recent-${label}`}>
                <p className="text-[10px] uppercase tracking-[0.3em]">{formatLabel(label)}</p>
                <p className="text-white">{formatStatValue(value)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {Object.keys(overall).length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Overall</p>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(overall).map(([label, value]) => (
              <div key={`overall-${label}`}>
                <p className="text-[10px] uppercase tracking-[0.3em]">{formatLabel(label)}</p>
                <p className="text-white">{formatStatValue(value)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {remainingEntries.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {remainingEntries.map(([label, value]) => (
            <div key={`misc-${label}`}>
              <p className="text-[10px] uppercase tracking-[0.3em]">{formatLabel(label)}</p>
              <p className="text-white">{formatStatValue(value)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const RejectionList = ({ records }: { records: FastScalperRejectionRecord[] }) => (
  <div className="space-y-3 text-sm text-muted-foreground">
    {records.length === 0 ? (
      <p>No rejection events recorded.</p>
    ) : (
      records.slice(0, 8).map((record, idx) => (
        <div key={`${record.timestamp}-${idx}`} className="rounded-2xl border border-white/5 bg-white/5 px-4 py-3">
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em]">
            <span>{record.reason}</span>
            <Badge variant="outline">{record.symbol ?? "n/a"}</Badge>
          </div>
          <p className="mt-1 text-base font-semibold text-white">
            {record.profile ? `Profile: ${record.profile}` : "Profile unknown"}
          </p>
          <p className="text-xs text-muted-foreground">{new Date(record.timestamp).toLocaleTimeString()}</p>
        </div>
      ))
    )}
  </div>
);

const PositionsTable = ({ positions }: { positions: TradingPosition[] }) => {
  if (!positions.length) {
    return <p className="text-sm text-muted-foreground">No open positions.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-white/5 bg-white/5">
      <table className="min-w-full divide-y divide-white/5 text-sm">
        <thead className="bg-white/5 text-xs uppercase tracking-[0.3em] text-muted-foreground">
          <tr>
            <th className="px-4 py-3 text-left">Symbol</th>
            <th className="px-4 py-3 text-left">Side</th>
            <th className="px-4 py-3 text-right">Size</th>
            <th className="px-4 py-3 text-right">Entry</th>
            <th className="px-4 py-3 text-right">Mark</th>
            <th className="px-4 py-3 text-right">PnL</th>
            <th className="px-4 py-3 text-right">Stop / TP</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {positions.map((position) => {
            const pnl = position.pnl ?? 0;
            const pnlClass = pnl >= 0 ? "text-emerald-400" : "text-rose-400";
            return (
              <tr key={`${position.symbol}-${position.entry_price}`} className="text-foreground">
                <td className="px-4 py-3 font-semibold">{position.symbol}</td>
                <td className="px-4 py-3">
                  <Badge variant={position.side === "buy" ? "success" : "warning"} className="uppercase">
                    {position.side}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">{position.size?.toPrecision(3)}</td>
                <td className="px-4 py-3 text-right">{position.entry_price?.toFixed(2)}</td>
                <td className="px-4 py-3 text-right">{position.current_price?.toFixed(2)}</td>
                <td className={cn("px-4 py-3 text-right font-semibold", pnlClass)}>{pnl.toFixed(2)}</td>
                <td className="px-4 py-3 text-right">
                  {position.stop_loss ? position.stop_loss.toFixed(2) : "—"} /{" "}
                  {position.take_profit ? position.take_profit.toFixed(2) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const RecentTradesList = ({ trades }: { trades: RecentTrade[] }) => {
  if (!trades.length) {
    return <p className="text-sm text-muted-foreground">No completed trades recorded in this session.</p>;
  }

  return (
    <div className="space-y-3">
      {trades.slice(0, 8).map((trade, idx) => {
        const pnlClass = trade.pnl >= 0 ? "text-emerald-400" : "text-rose-400";
        const timestampMs = trade.timestamp > 1e12 ? trade.timestamp : trade.timestamp * 1000;
        const timestamp = new Date(timestampMs);
        return (
          <div key={`${trade.symbol}-${trade.timestamp}-${idx}`} className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">{trade.symbol}</p>
                <p className="text-xs text-muted-foreground">{timestamp.toLocaleString()}</p>
              </div>
              <Badge variant={trade.side === "long" ? "success" : "warning"}>{trade.side}</Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-4 text-xs text-muted-foreground sm:grid-cols-4">
              <div>
                <p className="uppercase tracking-[0.3em]">Entry</p>
                <p className="text-white">{trade.entry_price?.toFixed(2)}</p>
              </div>
              <div>
                <p className="uppercase tracking-[0.3em]">Exit</p>
                <p className="text-white">{trade.exit_price?.toFixed(2)}</p>
              </div>
              <div>
                <p className="uppercase tracking-[0.3em]">Size</p>
                <p className="text-white">{formatQuantity(trade.size)}</p>
              </div>
              <div>
                <p className="uppercase tracking-[0.3em]">PnL</p>
                <p className={cn("font-semibold", pnlClass)}>{trade.pnl?.toFixed(2)}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default function TradingOpsPage() {
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  const { data: botInstancesData } = useBotInstances();
  const bots = (botInstancesData as any)?.bots || [];
  const botForExchange = bots.find((bot: any) =>
    bot.exchangeConfigs?.some((config: any) => config.exchange_account_id === exchangeAccountId)
  );
  const scopedBotId = botId || botForExchange?.id || undefined;
  const { data, isFetching } = useTradingOpsData({
    exchangeAccountId: scopeLevel !== "fleet" ? exchangeAccountId || undefined : undefined,
    botId: scopedBotId,
  });
  const fastScalper = data?.fastScalper;
  const rejections = data?.rejections;
  const trading = data?.trading;

  const metrics = (trading?.metrics as Record<string, number | undefined>) ?? {};
  const positions = trading?.positions ?? [];
  const pendingOrders = trading?.pendingOrders ?? [];
  const recentTrades = trading?.recentTrades ?? [];
  const execution = (trading?.execution as Record<string, any>) ?? {};
  const risk = (trading?.risk as Record<string, any>) ?? {};

  const timingBadge =
    fastScalper?.status === "online"
      ? "success"
      : fastScalper?.status === "stopped"
      ? "warning"
      : fastScalper?.status === "error"
      ? "warning"
      : "outline";

  const rejectionCounts = Object.entries(rejections?.counts ?? {}).sort((a, b) => b[1] - a[1]);
  const accountBalance = metrics.account_balance;
  const totalExposure = metrics.total_exposure;
  const portfolioHeat = risk.portfolio_heat;

  return (
    <div className="space-y-6">
      {/* System Status - Warmup, Connections, Services */}
      <SystemStatus data={fastScalper} isLoading={isFetching} />

      <Card className="border-white/5 bg-black/40">
        <CardHeader className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Trading Engine Control
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Mirrors the terminal ops panel with live PM2 + WAL stats.
            </p>
          </div>
          <Badge variant={timingBadge}>{fastScalper?.status ?? "unknown"}</Badge>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Positions</p>
            <p className="text-3xl font-semibold text-white">
              {fastScalper?.metrics
                ? `${fastScalper.metrics.positions}/${fastScalper.metrics.maxPositions}`
                : isFetching
                ? "…"
                : "0/0"}
            </p>
            <p className="text-xs text-muted-foreground">Active / Capacity</p>
          </div>
          <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Daily PnL</p>
            <p className="text-3xl font-semibold text-white">{formatUsd(fastScalper?.metrics?.dailyPnl)}</p>
            <p className="text-xs text-muted-foreground">Completed trades: {fastScalper?.metrics?.completedTrades ?? 0}</p>
          </div>
          <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Decisions / sec</p>
            <p className="text-3xl font-semibold text-white">
              {fastScalper?.metrics?.decisionsPerSec?.toFixed(2) ?? (isFetching ? "…" : "0.00")}
            </p>
            <p className="text-xs text-muted-foreground">
              WebSocket {fastScalper?.metrics?.webSocketStatus ?? "unknown"}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card className="border-white/5 bg-black/40">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Risk & Exposure</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Account Balance</p>
            <p className="text-2xl font-semibold text-white">{formatUsd(accountBalance)}</p>
            <p className="text-xs text-muted-foreground">State manager balance</p>
          </div>
          <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Exposure</p>
            <p className="text-2xl font-semibold text-white">{formatUsd(totalExposure)}</p>
            <p className="text-xs text-muted-foreground">Across all open legs</p>
          </div>
          <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Portfolio Heat</p>
            <p className="text-2xl font-semibold text-white">
              {portfolioHeat !== undefined ? `${portfolioHeat.toFixed(1)}%` : "—"}
            </p>
            <p className="text-xs text-muted-foreground">Exposure vs. capital</p>
            </div>
        </CardContent>
      </Card>

      <section className="grid gap-6 lg:grid-cols-2">
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Active Positions</CardTitle>
          </CardHeader>
          <CardContent>
            <PositionsTable positions={positions} />
          </CardContent>
        </Card>

        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Orders In Flight</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            {pendingOrders.length === 0 ? (
              <p>No pending orders.</p>
            ) : (
              pendingOrders.slice(0, 6).map((order) => (
                <div key={order.order_id} className="rounded-2xl border border-white/5 bg-white/5 px-4 py-3">
                  <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em]">
                    <span>{order.symbol}</span>
                    <Badge variant={order.status === "open" ? "outline" : "warning"}>{order.status}</Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.3em]">Side</p>
                      <p className="text-white">{order.side}</p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.3em]">Size @ Price</p>
                      <p className="text-white">
                        {formatQuantity(order.size)} @ {order.price?.toFixed?.(2) ?? order.price}
                      </p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Recent Trades</CardTitle>
          </CardHeader>
          <CardContent>
            <RecentTradesList trades={recentTrades} />
          </CardContent>
        </Card>

        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Execution Quality</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <ExecutionStatsCard title="Fill Stats" stats={execution?.fill} />
            <QualityStatsCard quality={execution?.quality} />
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Rejection Statistics
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            {rejectionCounts.length === 0 ? (
              <p>No rejection reasons recorded in Redis.</p>
            ) : (
              rejectionCounts.map(([reason, count]) => (
                <div
                  key={reason}
                  className="flex items-center justify-between rounded-xl border border-white/5 bg-white/5 px-4 py-2"
                >
                  <span className="font-semibold text-white">{reason}</span>
                  <Badge variant="outline">{count}</Badge>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Recent Rejections
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RejectionList records={rejections?.recent ?? []} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
