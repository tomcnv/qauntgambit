import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { FastScalperStatusResponse } from "../../lib/api/types";
import { cn } from "../../lib/utils";
import { Wifi, WifiOff, Server, Database, Activity, CheckCircle2, Clock, AlertTriangle, Loader2 } from "lucide-react";

interface SystemStatusProps {
  data: FastScalperStatusResponse | null | undefined;
  isLoading?: boolean;
}

const ProgressBar = ({ progress, label }: { progress: number; label: string }) => (
  <div className="space-y-1">
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn(
        "font-mono",
        progress >= 100 ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"
      )}>
        {progress.toFixed(0)}%
      </span>
    </div>
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={cn(
          "h-full transition-all duration-500",
          progress >= 100 ? "bg-emerald-500" : "bg-amber-500"
        )}
        style={{ width: `${Math.min(100, progress)}%` }}
      />
    </div>
  </div>
);

const ServiceBadge = ({ name, active }: { name: string; active: boolean }) => (
  <div className={cn(
    "flex items-center gap-2 rounded-lg border px-2 py-1 text-xs",
    active 
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" 
      : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
  )}>
    <span className={cn(
      "h-1.5 w-1.5 rounded-full",
      active ? "bg-emerald-500" : "bg-red-500"
    )} />
    {name}
  </div>
);

export function SystemStatus({ data, isLoading }: SystemStatusProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            System Status
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            System Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No status data available</p>
        </CardContent>
      </Card>
    );
  }

  const { serviceHealth, websocket, warmup, pendingOrders } = data;
  const allServicesReady = serviceHealth?.allReady ?? false;
  const allWarmedUp = warmup?.allWarmedUp ?? false;
  const wsConnected = (websocket?.publicConnected && websocket?.privateConnected) ?? false;
  const reasonLabels: Record<string, string> = {
    warmup: "Collecting samples",
    quality_missing: "Quality score missing",
    quality_low: "Quality score below threshold",
    data_stale: "Market data stale",
    orderbook_unsynced: "Orderbook not synced",
    trade_unsynced: "Trades not synced",
    candle_unsynced: "Candles not synced",
  };
  const formatReasons = (reasons?: string[]) =>
    (reasons || []).map((reason) => reasonLabels[reason] || reason);

  // Overall system status
  const overallStatus = allServicesReady && allWarmedUp && wsConnected ? "ready" : "warming";

  return (
    <div className="space-y-4">
      {/* Overall Status Banner */}
      <Card className={cn(
        "border",
        overallStatus === "ready" 
          ? "border-emerald-500/30 bg-emerald-500/5" 
          : "border-amber-500/30 bg-amber-500/5"
      )}>
        <CardContent className="py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {overallStatus === "ready" ? (
                <CheckCircle2 className="h-6 w-6 text-emerald-500" />
              ) : (
                <Clock className="h-6 w-6 animate-pulse text-amber-500" />
              )}
              <div>
                <p className={cn(
                  "text-lg font-semibold",
                  overallStatus === "ready" ? "text-emerald-700 dark:text-emerald-300" : "text-amber-700 dark:text-amber-300"
                )}>
                  {overallStatus === "ready" ? "System Ready" : "System Warming Up"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {overallStatus === "ready" 
                    ? "All services connected, data ready" 
                    : "Collecting market data, please wait..."}
                </p>
              </div>
            </div>
            <Badge variant={overallStatus === "ready" ? "success" : "warning"}>
              {overallStatus.toUpperCase()}
            </Badge>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* Services Status */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.3em] text-muted-foreground">
              <Server className="h-4 w-4" />
              Services
            </CardTitle>
          </CardHeader>
          <CardContent>
            {serviceHealth?.services ? (
              <div className="flex flex-wrap gap-2">
                {Object.entries(serviceHealth.services).map(([name, active]) => (
                  <ServiceBadge key={name} name={name.replace(/_/g, ' ')} active={Boolean(active)} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No service data</p>
            )}
            {serviceHealth?.missing && serviceHealth.missing.length > 0 && (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-300">
                <AlertTriangle className="mr-2 inline h-3 w-3" />
                Missing: {serviceHealth.missing.join(', ')}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Exchange Connection */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.3em] text-muted-foreground">
              {wsConnected ? <Wifi className="h-4 w-4 text-emerald-500" /> : <WifiOff className="h-4 w-4 text-red-500" />}
              Exchange Connection
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Public WebSocket</span>
              <Badge variant={websocket?.publicConnected ? "success" : "warning"}>
                {websocket?.publicConnected ? "Connected" : "Disconnected"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Private WebSocket</span>
              <Badge variant={websocket?.privateConnected ? "success" : "warning"}>
                {websocket?.privateConnected ? "Connected" : "Disconnected"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Status</span>
              <Badge variant={websocket?.status === "FULL" ? "success" : "outline"}>
                {websocket?.status || "Unknown"}
              </Badge>
            </div>
            {websocket?.messagesReceived !== undefined && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Messages Received</span>
                <span className="font-mono text-foreground">{websocket.messagesReceived.toLocaleString()}</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Data Warmup Status */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.3em] text-muted-foreground">
              <Database className="h-4 w-4" />
              Data Warmup
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {warmup?.symbols && Object.keys(warmup.symbols).length > 0 ? (
              Object.entries(warmup.symbols).map(([symbol, status]) => (
                <div key={symbol} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-foreground">{symbol}</span>
                    {status.ready ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    ) : (
                      <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
                    )}
                  </div>
                  {status.amt && (
                    <ProgressBar 
                      progress={status.amt.progress} 
                      label={`AMT (${status.amt.status})`} 
                    />
                  )}
                  {status.htf && (
                    <ProgressBar 
                      progress={status.htf.progress} 
                      label={`HTF (${status.htf.candles ?? 0} candles)`} 
                    />
                  )}
                  {!status.ready && status.reasons?.length ? (
                    <div className="text-[11px] text-muted-foreground">
                      <span className="font-medium text-foreground">Reasons:</span>{" "}
                      {formatReasons(status.reasons).join(", ")}
                    </div>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No warmup data</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Pending Orders */}
      {pendingOrders && pendingOrders.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.4em] text-muted-foreground">
              <Activity className="h-4 w-4" />
              Pending Orders ({pendingOrders.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-border text-sm">
                <thead className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left">Symbol</th>
                    <th className="px-3 py-2 text-left">Side</th>
                    <th className="px-3 py-2 text-right">Price</th>
                    <th className="px-3 py-2 text-right">Size</th>
                    <th className="px-3 py-2 text-left">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {pendingOrders.map((order, idx) => (
                    <tr key={idx}>
                      <td className="px-3 py-2 text-foreground">{order.symbol}</td>
                      <td className="px-3 py-2">
                        <Badge variant={order.side === "buy" ? "success" : "warning"}>
                          {order.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-foreground">
                        ${order.price.toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-foreground">
                        {order.size.toFixed(4)}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant="outline">{order.status}</Badge>
                      </td>
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
}
