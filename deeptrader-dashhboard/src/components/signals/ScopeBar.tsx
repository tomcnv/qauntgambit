import { useMemo } from "react";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { cn } from "../../lib/utils";
import { useScopeStore } from "../../store/scope-store";
import { useExchangeAccounts } from "../../lib/api/exchange-accounts-hooks";
import { useActiveBot, useHealthSnapshot } from "../../lib/api/hooks";
import { useOverviewData } from "../../lib/api/hooks";
import { CheckCircle2, XCircle, Clock, Activity, Wifi, WifiOff } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../components/ui/tooltip";

export function ScopeBar() {
  const { exchangeAccountId, exchangeAccountName, botId, botName } = useScopeStore();
  const { data: exchangeAccounts = [] } = useExchangeAccounts();
  const { data: activeBotData } = useActiveBot();
  const { data: healthData } = useHealthSnapshot({ botId });
  const { data: overviewData } = useOverviewData({
    exchangeAccountId: exchangeAccountId || null,
    botId: botId || null,
  });

  const selectedAccount = (exchangeAccounts as any[]).find((a: any) => a.id === exchangeAccountId);
  
  // Get bot info
  const activeBot = (activeBotData as any)?.bot;
  const displayBotName = botName || activeBot?.name || "No bot running";
  
  // Determine combined trading mode (API type + trading mode)
  const isDemo = selectedAccount?.is_demo || false;
  const environment = selectedAccount?.environment || 'paper';
  
  // Combined trading mode label
  const getTradingModeLabel = (): string => {
    if (isDemo && environment === 'live') return '🧪 Demo Trading';
    if (isDemo && environment === 'paper') return '🧪 Demo Paper';
    if (!isDemo && environment === 'live') return '🔥 Live Trading';
    if (!isDemo && environment === 'paper') return '📝 Paper Mode';
    return '🔧 Dev Mode';
  };
  
  const getTradingModeBadgeClass = (): string => {
    if (isDemo && environment === 'live') return 'border-amber-500/50 text-amber-400 bg-amber-500/10';
    if (isDemo && environment === 'paper') return 'border-amber-500/30 text-amber-300 bg-amber-500/10';
    if (!isDemo && environment === 'live') return 'border-red-500/50 text-red-400 bg-red-500/10';
    if (!isDemo && environment === 'paper') return 'border-blue-500/50 text-blue-400 bg-blue-500/10';
    return 'border-purple-500/50 text-purple-400 bg-purple-500/10';
  };
  
  // Parse exchange from account name
  const getExchangeFromName = (name: string | null): string | null => {
    if (!name) return null;
    const match = name.match(/\(([^)]+)\)/);
    return match ? match[1].toLowerCase() : null;
  };
  
  const exchange = selectedAccount?.venue || getExchangeFromName(exchangeAccountName);
  const accountLabel = exchangeAccountName?.replace(/\s*\([^)]+\)$/, '') || selectedAccount?.label || "No Account";
  
  // Get bot state
  const botStatus = (overviewData as any)?.botStatus;
  const fastScalper = (overviewData as any)?.fastScalper;
  const platformStatus = botStatus?.platform?.status || fastScalper?.status || "offline";
  const tradingInfo = botStatus?.trading;
  const isTradingActive = tradingInfo?.isActive ?? false;
  
  let botState = "Offline";
  if (platformStatus === "running" && isTradingActive) {
    botState = "Running";
  } else if (platformStatus === "running" && !isTradingActive) {
    botState = "Paused";
  } else if (platformStatus === "warming") {
    botState = "Warming";
  } else if (platformStatus === "ready") {
    botState = "Data Ready";
  }
  
  // Data health indicators
  const wsStatus = healthData?.websocket?.connected || false;
  const orderbookP95 = healthData?.orderbook?.p95_age_ms;
  const clockSkew = healthData?.clock_skew_ms;
  const modelWarmup = healthData?.model?.warmup_percent || 0;
  
  const wsStatusDisplay = wsStatus ? "Connected" : "Disconnected";
  const orderbookDisplay = orderbookP95 ? `${orderbookP95}ms` : "—";
  const clockSkewDisplay = clockSkew !== undefined ? `${Math.abs(clockSkew)}ms` : "—";
  const modelWarmupDisplay = `${modelWarmup}%`;
  
  // Health status colors
  const wsColor = wsStatus ? "text-emerald-500" : "text-red-500";
  const orderbookColor = orderbookP95 && orderbookP95 < 200 ? "text-emerald-500" : orderbookP95 && orderbookP95 < 500 ? "text-amber-500" : "text-red-500";
  const clockSkewColor = clockSkew !== undefined && Math.abs(clockSkew) < 100 ? "text-emerald-500" : clockSkew !== undefined && Math.abs(clockSkew) < 500 ? "text-amber-500" : "text-red-500";
  const modelColor = modelWarmup >= 100 ? "text-emerald-500" : modelWarmup >= 50 ? "text-amber-500" : "text-red-500";
  
  return (
    <div className="sticky top-0 z-50 bg-card/95 backdrop-blur-sm border-b">
      <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-xs">
        {/* Exchange Account */}
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Exchange Account:</span>
          <Badge variant="outline" className="text-xs px-2 py-0.5">
            {accountLabel}
          </Badge>
        </div>
        
        <Separator orientation="vertical" className="h-4" />
        
        {/* Active Bot */}
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Active Bot:</span>
          <Badge variant="outline" className="text-xs px-2 py-0.5">
            {displayBotName}
          </Badge>
        </div>
        
        <Separator orientation="vertical" className="h-4" />
        
        {/* Mode */}
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Mode:</span>
          <Badge 
            variant="outline" 
            className={cn("text-xs px-2 py-0.5", getTradingModeBadgeClass())}
          >
            {getTradingModeLabel()}
          </Badge>
        </div>
        
        <Separator orientation="vertical" className="h-4" />
        
        {/* State */}
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">State:</span>
          <Badge 
            variant="outline" 
            className={cn(
              "text-xs px-2 py-0.5",
              botState === "Running" 
                ? "border-emerald-500/50 text-emerald-500 bg-emerald-500/10"
                : botState === "Paused"
                ? "border-amber-500/50 text-amber-500 bg-amber-500/10"
                : "border-muted-foreground/50 text-muted-foreground"
            )}
          >
            {botState}
          </Badge>
        </div>
        
        <Separator orientation="vertical" className="h-4" />
        
        {/* Data Health */}
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Data Health:</span>
          
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className={cn("flex items-center gap-1", wsColor)}>
                  {wsStatus ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
                  <span className="text-xs">{wsStatusDisplay}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p>WebSocket Status</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className={cn("flex items-center gap-1", orderbookColor)}>
                  <Clock className="h-3 w-3" />
                  <span className="text-xs">OB p95: {orderbookDisplay}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p>Orderbook freshness (p95)</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          
          {clockSkew !== undefined && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className={cn("flex items-center gap-1", clockSkewColor)}>
                    <Activity className="h-3 w-3" />
                    <span className="text-xs">Skew: {clockSkewDisplay}</span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Clock skew</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
          
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className={cn("flex items-center gap-1", modelColor)}>
                  <Activity className="h-3 w-3" />
                  <span className="text-xs">Model: {modelWarmupDisplay}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p>Model warmup percentage</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    </div>
  );
}
