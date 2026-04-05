/**
 * TruthBar - Compact truth bar showing scope, bot state, gates, and safety
 * 
 * Displays at-a-glance:
 * - Trading Mode: Paper/Live + Exchange
 * - Bot: Name + Running status
 * - Gates status: Data Ready / Spread Gate / Risk Gate
 * - Safety: Daily loss budget (USD), exposure (USD)
 * - Bot Controls button
 */

import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock,
  DollarSign,
  Gauge,
  Play,
  Shield,
  Square,
  XCircle,
} from "lucide-react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Separator } from "../ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { Progress } from "../ui/progress";
import { cn } from "../../lib/utils";
import type { GateStatus, SafetyMetrics, VenueHealth } from "./types";
import { ExchangeLogo } from "../scope-selector";
import { useScopeStore } from "../../store/scope-store";
import { useExchangeAccounts } from "../../lib/api/exchange-accounts-hooks";

// ============================================================================
// TYPES
// ============================================================================

interface TruthBarProps {
  botName: string | null;
  botRunning: boolean;
  botRunningSince: string | null;
  profileName: string | null;  // Kept for backwards compatibility but not displayed
  profileVersion: string | null;  // Kept for backwards compatibility but not displayed
  gates: GateStatus[];
  safety: SafetyMetrics;
  venueHealth: VenueHealth;
}

// ============================================================================
// HELPER: Format duration
// ============================================================================

function formatDuration(since: string | null): string {
  if (!since) return "";
  const start = new Date(since).getTime();
  const now = Date.now();
  const diffMs = now - start;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  
  if (diffDays > 0) return `${diffDays}d ${diffHours % 24}h`;
  if (diffHours > 0) return `${diffHours}h ${diffMins % 60}m`;
  return `${diffMins}m`;
}

// ============================================================================
// GATE INDICATOR
// ============================================================================

function GateIndicator({ gate }: { gate: GateStatus }) {
  const icon = gate.passed 
    ? <CheckCircle2 className="h-3 w-3 text-emerald-500" />
    : gate.severity === 'warning'
    ? <AlertTriangle className="h-3 w-3 text-amber-500" />
    : <XCircle className="h-3 w-3 text-red-500" />;
  
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={cn(
          "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium cursor-default",
          gate.passed 
            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
            : gate.severity === 'warning'
            ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
            : "bg-red-500/10 text-red-600 dark:text-red-400"
        )}>
          {icon}
          <span className="hidden sm:inline">{gate.name}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        <div className="space-y-1">
          <div className="font-medium">{gate.name}</div>
          <div className="text-muted-foreground">{gate.description}</div>
          <div className="flex items-center gap-2 pt-1 border-t border-border/50">
            <span>Threshold: {gate.threshold}{gate.unit}</span>
            <span>•</span>
            <span>Actual: {gate.actual}{gate.unit}</span>
          </div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function TruthBar({
  botName,
  botRunning,
  botRunningSince,
  profileName,
  profileVersion,
  gates,
  safety,
  venueHealth,
}: TruthBarProps) {
  const { exchangeAccountId, exchangeAccountName, botName: scopeBotName } = useScopeStore();
  
  // Get exchange accounts to determine paper/live mode
  const { data: exchangeAccountsData } = useExchangeAccounts();
  const exchangeAccounts = (exchangeAccountsData as any)?.accounts || [];
  const selectedAccount = exchangeAccounts.find((a: any) => a.id === exchangeAccountId);
  
  // Determine trading mode
  const isPaperAccount = selectedAccount?.environment === 'paper';
  const tradingMode = isPaperAccount ? 'Paper' : 'Live';
  
  // Parse exchange from account name
  const getExchangeFromName = (name: string | null): string | null => {
    if (!name) return null;
    const match = name.match(/\(([^)]+)\)/);
    return match ? match[1].toLowerCase() : null;
  };
  
  const exchange = selectedAccount?.exchange || getExchangeFromName(exchangeAccountName);
  const accountLabel = exchangeAccountName?.replace(/\s*\([^)]+\)$/, '') || 'No Account';
  
  // Use the actual bot name from scope or props
  const displayBotName = scopeBotName || botName || 'No Bot Selected';
  
  // Calculate safety percentages
  const lossUsedPct = safety.dailyLossLimit > 0 
    ? (safety.dailyLossUsed / safety.dailyLossLimit) * 100 
    : 0;
  // Use the pre-calculated percentage if available, otherwise calculate
  const exposureUsedPct = safety.exposureUsedPct ?? (safety.exposureCap > 0 
    ? (safety.exposureUsed / safety.exposureCap) * 100 
    : 0);
  
  // Key gates to show inline
  const keyGates = gates.filter(g => 
    ['data_ready', 'spread_cap', 'risk_policy'].includes(g.key)
  );
  
  // Count gate failures
  const failedGates = gates.filter(g => !g.passed && (g.blocking ?? g.severity === 'critical')).length;
  const warningGates = gates.filter(g => !g.passed && !g.unknown && g.severity === 'warning').length;
  
  return (
    <div className="border-b bg-muted/30">
      <div className="flex items-center gap-3 px-4 py-2 text-xs overflow-x-auto">
        {/* Trading Mode + Exchange */}
        <div className="flex items-center gap-2 shrink-0">
          <Badge 
            variant="outline" 
            className={cn(
              "text-[10px] px-1.5 py-0 font-medium",
              isPaperAccount 
                ? "border-blue-500/50 text-blue-500 bg-blue-500/10" 
                : "border-emerald-500/50 text-emerald-500 bg-emerald-500/10"
            )}
          >
            {tradingMode}
          </Badge>
          {exchange && <ExchangeLogo venue={exchange} className="h-4 w-4" />}
          <span className="font-medium">{accountLabel}</span>
        </div>
        
        <Separator orientation="vertical" className="h-5" />
        
        {/* Bot Name + State */}
        <div className="flex items-center gap-2 shrink-0">
          <Bot className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="font-medium">{displayBotName}</span>
          <div className={cn(
            "flex items-center gap-1.5 px-2 py-0.5 rounded-full",
            botRunning 
              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "bg-muted text-muted-foreground"
          )}>
            {botRunning ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <Play className="h-3 w-3" />
                <span className="font-medium">Running</span>
              </>
            ) : (
              <>
                <Square className="h-3 w-3" />
                <span className="font-medium">Stopped</span>
              </>
            )}
          </div>
          {botRunningSince && botRunning && (
            <span className="text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {formatDuration(botRunningSince)}
            </span>
          )}
        </div>
        
        <Separator orientation="vertical" className="h-5" />
        
        {/* Gates Status */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-muted-foreground mr-1">Gates:</span>
          {keyGates.map(gate => (
            <GateIndicator key={gate.key} gate={gate} />
          ))}
          {failedGates > 0 && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-red-500/50 text-red-500">
              {failedGates} failed
            </Badge>
          )}
          {warningGates > 0 && failedGates === 0 && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-500">
              {warningGates} warning
            </Badge>
          )}
        </div>
        
        <Separator orientation="vertical" className="h-5" />
        
        {/* Safety Metrics */}
        <div className="flex items-center gap-3 shrink-0">
          {/* Daily Loss */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                <DollarSign className={cn(
                  "h-3 w-3",
                  lossUsedPct > 80 ? "text-red-500" : lossUsedPct > 50 ? "text-amber-500" : "text-muted-foreground"
                )} />
                <div className="w-16">
                  <Progress 
                    value={lossUsedPct} 
                    className={cn(
                      "h-1.5",
                      lossUsedPct > 80 ? "[&>div]:bg-red-500" : lossUsedPct > 50 ? "[&>div]:bg-amber-500" : ""
                    )}
                  />
                </div>
                <span className={cn(
                  "font-mono",
                  lossUsedPct > 80 ? "text-red-500" : lossUsedPct > 50 ? "text-amber-500" : "text-muted-foreground"
                )}>
                  ${safety.dailyLossRemaining.toFixed(0)}
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <div className="text-xs">
                <div className="font-medium">Daily Loss Budget</div>
                <div>Used: ${safety.dailyLossUsed.toFixed(2)} / ${safety.dailyLossLimit.toFixed(2)}</div>
                <div>Remaining: ${safety.dailyLossRemaining.toFixed(2)}</div>
              </div>
            </TooltipContent>
          </Tooltip>
          
          {/* Exposure - Show USD value */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 cursor-default">
                <Gauge className={cn(
                  "h-3 w-3",
                  exposureUsedPct > 80 ? "text-red-500" : exposureUsedPct > 50 ? "text-amber-500" : "text-muted-foreground"
                )} />
                <span className={cn(
                  "font-mono",
                  exposureUsedPct > 80 ? "text-red-500" : exposureUsedPct > 50 ? "text-amber-500" : "text-muted-foreground"
                )}>
                  ${safety.exposureUsed >= 1000 
                    ? `${(safety.exposureUsed / 1000).toFixed(1)}k` 
                    : safety.exposureUsed.toFixed(0)}
                </span>
                <span className="text-[9px] text-muted-foreground">
                  ({exposureUsedPct.toFixed(0)}%)
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <div className="text-xs">
                <div className="font-medium">Total Exposure</div>
                <div>Current: ${safety.exposureUsed.toFixed(2)}</div>
                <div>Limit: ${safety.exposureCap.toFixed(2)}</div>
                <div>Used: {exposureUsedPct.toFixed(1)}%</div>
              </div>
            </TooltipContent>
          </Tooltip>
          
          {/* Kill Switch */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className={cn(
                "flex items-center gap-1 px-1.5 py-0.5 rounded cursor-default",
                safety.killSwitchStatus === 'triggered' 
                  ? "bg-red-500/10 text-red-500"
                  : "text-muted-foreground"
              )}>
                <Shield className="h-3 w-3" />
                {safety.killSwitchStatus === 'triggered' && (
                  <span className="text-[10px] font-medium">KILL</span>
                )}
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              Kill Switch: {safety.killSwitchStatus}
            </TooltipContent>
          </Tooltip>
        </div>
        
        {/* Spacer */}
        <div className="flex-1" />
        
        {/* Bot Controls Link */}
        <Link to="/live" className="shrink-0">
          <Button variant="outline" size="sm" className="h-6 text-[11px] gap-1">
            <Activity className="h-3 w-3" />
            Bot Controls
          </Button>
        </Link>
      </div>
    </div>
  );
}
