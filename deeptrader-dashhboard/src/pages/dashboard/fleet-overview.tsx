import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import { Search, Bot, Pin, ExternalLink, Activity, AlertTriangle, ListOrdered } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import {
  useActiveConfig,
  useActivateBotExchangeConfig,
  useBotInstances,
  useOverviewData,
  useHealthSnapshot,
  useExchangePositions,
} from "../../lib/api/hooks";

type FleetBotRow = {
  id: string;
  name: string;
  exchange?: string;
  environment?: string;
  is_testnet?: boolean;
  market?: string;
  exchangeConfigs?: any[];
  tradingModeLabel?: string;
};

export default function FleetOverviewPage() {
  const { data: botInstances, isLoading: botsLoading } = useBotInstances();
  const { data: activeConfigData } = useActiveConfig();
  const activateConfigMutation = useActivateBotExchangeConfig();
  const { data: overviewData } = useOverviewData();
  const { data: healthSnapshot } = useHealthSnapshot();
  const { data: positionsData } = useExchangePositions();
  const [q, setQ] = useState("");

  // Helper function to determine display label for trading mode
  const getTradingModeLabel = (config: any): string => {
    if (!config) return "—";
    
    // If testnet, it's LIVE trading (not paper)
    if (config.is_testnet) {
      return "Live (Testnet)";
    }
    
    // Otherwise use the environment field
    const env = config.environment || "paper";
    if (env === "paper") {
      return "Paper";
    } else if (env === "live") {
      return "Live";
    } else {
      return env.charAt(0).toUpperCase() + env.slice(1);
    }
  };

  const bots: FleetBotRow[] = useMemo(() => {
    const list = (botInstances as any)?.bots || [];
    return list.map((b: any) => {
      const activeConfig = b.exchangeConfigs?.find?.((c: any) => c?.is_active) || b.exchangeConfigs?.[0];
      return {
        id: b.id,
        name: b.name,
        exchangeConfigs: Array.isArray(b.exchangeConfigs) ? b.exchangeConfigs : [],
        exchange: activeConfig?.exchange || b.exchange || b.exchange_name,
        environment: activeConfig?.environment || b.environment,
        is_testnet: activeConfig?.is_testnet || false,
        market: activeConfig?.market_type || b.market_type || b.market,
        tradingModeLabel: getTradingModeLabel(activeConfig),
      };
    });
  }, [botInstances]);

  const filtered = useMemo(() => {
    const qq = q.trim().toLowerCase();
    if (!qq) return bots;
    return bots.filter((b) => b.name?.toLowerCase().includes(qq) || b.exchange?.toLowerCase().includes(qq));
  }, [bots, q]);

  const pinnedBotId = (activeConfigData as any)?.active?.bot_instance_id || null;
  const pinnedBotName = (activeConfigData as any)?.active?.bot_name || null;

  const runningBots = bots.filter(
    (b) => (b.exchangeConfigs || []).some((c: any) => c?.is_active)
  );
  const activeConfigsCount = runningBots.reduce(
    (sum, b) => sum + (b.exchangeConfigs || []).filter((c: any) => c?.is_active).length,
    0
  );
  const openPositionsCount = (positionsData as any)?.positions?.length || 0;
  const alertsCount = (overviewData as any)?.alerts?.items?.length || 0;
  const serviceHealth = (overviewData as any)?.serviceHealth || (healthSnapshot as any)?.serviceHealth;
  const positionGuardian = (healthSnapshot as any)?.position_guardian;
  const executionReadiness = (healthSnapshot as any)?.execution_readiness;
  const tradingActivity = (healthSnapshot as any)?.trading_activity;
  const guardianMisconfigured = positionGuardian?.status === "misconfigured";
  const runtimeBlocked = executionReadiness?.execution_ready === false;
  const topRejectedSymbol = tradingActivity?.top_rejected_symbol;
  const topRejectedReason = tradingActivity?.top_rejected_symbol_reason;

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">Fleet Overview</h1>
          <p className="text-sm text-muted-foreground">
            Fleet-scoped status and navigation. Use the pinned bot chip for bot drill-in; start/stop lives on bot pages.
          </p>
        </div>
        {pinnedBotId && (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              Pinned bot
            </Badge>
            <Link to={`/dashboard/bots/${pinnedBotId}/operate`}>
              <Button variant="outline" size="sm" className="gap-2">
                <Bot className="h-4 w-4" />
                {pinnedBotName || "Open"}
                <ExternalLink className="h-3.5 w-3.5" />
              </Button>
            </Link>
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Running bots</p>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </div>
            <p className="text-2xl font-bold">{runningBots.length}</p>
            <p className="text-xs text-muted-foreground">With an active exchange config</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Active configs</p>
              <ListOrdered className="h-4 w-4 text-muted-foreground" />
            </div>
            <p className="text-2xl font-bold">{activeConfigsCount}</p>
            <p className="text-xs text-muted-foreground">Pinned/active runtime configs</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Open positions</p>
              <Bot className="h-4 w-4 text-muted-foreground" />
            </div>
            <p className="text-2xl font-bold">{openPositionsCount}</p>
            <p className="text-xs text-muted-foreground">Across all bots</p>
          </CardContent>
        </Card>
        <Card className={alertsCount > 0 ? "border-amber-500/40 bg-amber-500/5" : ""}>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Alerts</p>
              <AlertTriangle className={cn("h-4 w-4", alertsCount > 0 ? "text-amber-500" : "text-muted-foreground")} />
            </div>
            <p className={cn("text-2xl font-bold", alertsCount > 0 ? "text-amber-500" : "")}>{alertsCount}</p>
            <p className="text-xs text-muted-foreground">Active alerts</p>
          </CardContent>
        </Card>
        <Card className={guardianMisconfigured ? "border-red-500/40 bg-red-500/5" : ""}>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Position guard</p>
              <AlertTriangle className={cn("h-4 w-4", guardianMisconfigured ? "text-red-500" : "text-muted-foreground")} />
            </div>
            <p className={cn("text-2xl font-bold", guardianMisconfigured ? "text-red-500" : "")}>
              {guardianMisconfigured ? "Misconfigured" : positionGuardian?.status || "Unknown"}
            </p>
            <p className="text-xs text-muted-foreground">
              {guardianMisconfigured ? positionGuardian?.reason || "invalid_guard_policy" : "Runtime protection status"}
            </p>
          </CardContent>
        </Card>
        <Card className={runtimeBlocked ? "border-amber-500/40 bg-amber-500/5" : ""}>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Execution readiness</p>
              <AlertTriangle className={cn("h-4 w-4", runtimeBlocked ? "text-amber-500" : "text-muted-foreground")} />
            </div>
            <p className={cn("text-2xl font-bold", runtimeBlocked ? "text-amber-500" : "")}>
              {runtimeBlocked ? "Blocked" : "Ready"}
            </p>
            <p className="text-xs text-muted-foreground">
              {runtimeBlocked ? executionReadiness?.execution_block_reason || "execution_not_ready" : "Runtime can place orders"}
            </p>
          </CardContent>
        </Card>
        <Card className={topRejectedSymbol ? "border-amber-500/40 bg-amber-500/5" : ""}>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-muted-foreground">Top blocked symbol</p>
              <AlertTriangle className={cn("h-4 w-4", topRejectedSymbol ? "text-amber-500" : "text-muted-foreground")} />
            </div>
            <p className={cn("text-2xl font-bold", topRejectedSymbol ? "text-amber-500" : "")}>
              {topRejectedSymbol || "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {topRejectedSymbol ? topRejectedReason || "rejection_only" : "No dominant symbol blocker"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Optional service health */}
      {serviceHealth && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Service Health</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <pre className="text-xs whitespace-pre-wrap break-words">
              {JSON.stringify(serviceHealth, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <CardTitle className="text-base font-medium">Bots</CardTitle>
            <div className="relative w-full md:w-[360px]">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search bots (name, exchange)"
                className="pl-9"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {botsLoading ? (
            <div className="py-8 text-sm text-muted-foreground">Loading bots…</div>
          ) : filtered.length === 0 ? (
            <div className="py-8 text-sm text-muted-foreground">No bots found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50">
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Bot</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Exchange</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Env</th>
                    <th className="text-left font-medium text-muted-foreground py-2 pr-4">Market</th>
                    <th className="text-right font-medium text-muted-foreground py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((b) => {
                    const isPinned = pinnedBotId === b.id;
                    const config =
                      (b.exchangeConfigs || []).find((c: any) => c?.is_active) || (b.exchangeConfigs || [])[0] || null;
                    return (
                      <tr key={b.id} className="border-b border-border/30 last:border-0">
                        <td className="py-2.5 pr-4">
                          <div className="flex items-center gap-2">
                            <div className={cn("h-7 w-7 rounded-lg flex items-center justify-center", isPinned ? "bg-primary/15" : "bg-muted")}>
                              <Bot className={cn("h-4 w-4", isPinned ? "text-primary" : "text-muted-foreground")} />
                            </div>
                            <div className="min-w-0">
                              <div className="font-medium truncate">{b.name}</div>
                              {isPinned && <div className="text-xs text-muted-foreground">Pinned</div>}
                            </div>
                          </div>
                        </td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{b.exchange || "—"}</td>
                        <td className="py-2.5 pr-4">
                          <Badge 
                            variant="outline" 
                            className={cn(
                              "text-xs",
                              b.is_testnet 
                                ? "border-emerald-500/50 text-emerald-500 bg-emerald-500/10"
                                : b.environment === "paper"
                                ? "border-blue-500/50 text-blue-500 bg-blue-500/10"
                                : "border-emerald-500/50 text-emerald-500 bg-emerald-500/10"
                            )}
                          >
                            {b.tradingModeLabel || b.environment || "—"}
                          </Badge>
                        </td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{b.market || "—"}</td>
                        <td className="py-2.5 text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              className="gap-2"
                              disabled={activateConfigMutation.isPending || isPinned || !config?.id}
                              onClick={() => {
                                if (!config?.id) return;
                                activateConfigMutation.mutate({ botId: b.id, configId: config.id });
                              }}
                              title="Pin as active bot"
                            >
                              <Pin className="h-4 w-4" />
                              Pin
                            </Button>
                            <Link to={`/dashboard/bots/${b.id}/operate`}>
                              <Button size="sm" className="gap-2">
                                Open
                                <ExternalLink className="h-3.5 w-3.5" />
                              </Button>
                            </Link>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
