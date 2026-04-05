/**
 * ProfileRoutingPanel - Real-time profile routing status
 * 
 * Shows actual data from the ProfileRouter:
 * - Active profiles count and states
 * - Top profile selections per symbol
 * - Profile performance (win rate, PnL)
 * - Current best match for each symbol
 */

import { useMemo } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Info,
  Layers,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { ProfileMetricsResponse, ProfileInstance } from "../../lib/api/types";

// ============================================================================
// TYPES
// ============================================================================

interface ProfileRoutingPanelProps {
  profileMetrics: ProfileMetricsResponse | null | undefined;
  isLoading?: boolean;
  className?: string;
}

// ============================================================================
// STATE BADGE
// ============================================================================

function StateBadge({ state }: { state: ProfileInstance['state'] }) {
  const config = {
    active: { label: "Active", color: "text-emerald-500 bg-emerald-500/10 border-emerald-500/30" },
    warming: { label: "Warming", color: "text-amber-500 bg-amber-500/10 border-amber-500/30" },
    cooling: { label: "Cooling", color: "text-blue-500 bg-blue-500/10 border-blue-500/30" },
    disabled: { label: "Disabled", color: "text-muted-foreground bg-muted border-border" },
    error: { label: "Error", color: "text-red-500 bg-red-500/10 border-red-500/30" },
  };
  
  const { label, color } = config[state] || config.disabled;
  
  return (
    <Badge variant="outline" className={cn("text-[9px] px-1.5", color)}>
      {label}
    </Badge>
  );
}

// ============================================================================
// PROFILE ROW
// ============================================================================

function ProfileRow({ instance }: { instance: ProfileInstance }) {
  const pnlPositive = instance.total_pnl >= 0;
  
  return (
    <div className="flex items-center gap-3 py-1.5 text-xs">
      {/* Profile ID */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{instance.profile_id}</span>
          <StateBadge state={instance.state} />
        </div>
        <span className="text-[10px] text-muted-foreground">{instance.symbol}</span>
      </div>
      
      {/* Stats */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Win Rate */}
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="text-right cursor-default">
              <span className={cn(
                "font-mono font-medium",
                instance.win_rate >= 50 ? "text-emerald-500" : "text-muted-foreground"
              )}>
                {instance.win_rate.toFixed(0)}%
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            Win Rate: {instance.wins}W / {instance.losses}L ({instance.trades_count} trades)
          </TooltipContent>
        </Tooltip>
        
        {/* PnL */}
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-1 cursor-default min-w-[60px] justify-end">
              {pnlPositive ? (
                <TrendingUp className="h-3 w-3 text-emerald-500" />
              ) : (
                <TrendingDown className="h-3 w-3 text-red-500" />
              )}
              <span className={cn(
                "font-mono font-medium",
                pnlPositive ? "text-emerald-500" : "text-red-500"
              )}>
                ${Math.abs(instance.total_pnl).toFixed(0)}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            Total PnL: ${instance.total_pnl.toFixed(2)}
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function ProfileRoutingPanel({ 
  profileMetrics, 
  isLoading,
  className 
}: ProfileRoutingPanelProps) {
  // Group instances by symbol for "best match" view
  const bestMatchBySymbol = useMemo(() => {
    if (!profileMetrics?.instances?.length) return {};
    
    const bySymbol: Record<string, ProfileInstance> = {};
    
    // For each symbol, find the active instance with best performance
    profileMetrics.instances
      .filter(i => i.state === 'active')
      .forEach(instance => {
        const existing = bySymbol[instance.symbol];
        if (!existing || instance.win_rate > existing.win_rate) {
          bySymbol[instance.symbol] = instance;
        }
      });
    
    return bySymbol;
  }, [profileMetrics?.instances]);
  
  // Top performers across all symbols
  const topPerformers = useMemo(() => {
    if (!profileMetrics?.instances?.length) return [];
    
    return [...profileMetrics.instances]
      .filter(i => i.trades_count > 0)
      .sort((a, b) => b.total_pnl - a.total_pnl)
      .slice(0, 5);
  }, [profileMetrics?.instances]);
  
  const hasData = profileMetrics && profileMetrics.total_instances > 0;
  
  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Profile Routing</CardTitle>
          {hasData && (
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-[10px]">
                {profileMetrics.active_instances} active
              </Badge>
              {profileMetrics.warming_instances > 0 && (
                <Badge variant="outline" className="text-[10px] border-amber-500/30 text-amber-500">
                  {profileMetrics.warming_instances} warming
                </Badge>
              )}
            </div>
          )}
        </div>
      </CardHeader>
      
      <CardContent>
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Activity className="h-5 w-5 animate-pulse text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading profiles...</span>
          </div>
        ) : !hasData ? (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <Info className="h-6 w-6 text-muted-foreground/50 mb-2" />
            <p className="text-sm text-muted-foreground">No profile routing data</p>
            <p className="text-[10px] text-muted-foreground/70 mt-1">
              Bot may not be running or profiles not registered
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 gap-2 text-center">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="p-2 rounded-lg bg-muted/30 cursor-default">
                    <p className="text-lg font-bold">{profileMetrics.total_profiles}</p>
                    <p className="text-[10px] text-muted-foreground">Available Profiles</p>
                  </div>
                </TooltipTrigger>
                <TooltipContent className="max-w-[250px]">
                  <p className="font-medium">Chess Moves Available</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    All {profileMetrics.total_profiles} profiles are evaluated on every decision. 
                    The router selects the best match for current market conditions.
                  </p>
                </TooltipContent>
              </Tooltip>
              
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="p-2 rounded-lg bg-emerald-500/10 cursor-default">
                    <p className="text-lg font-bold text-emerald-500">{profileMetrics.active_instances}</p>
                    <p className="text-[10px] text-muted-foreground">Selected Now</p>
                  </div>
                </TooltipTrigger>
                <TooltipContent className="max-w-[250px]">
                  <p className="font-medium">Currently Selected</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {profileMetrics.active_instances} profile(s) currently selected as best match 
                    for {Object.keys(bestMatchBySymbol).length} symbol(s). Selection changes dynamically 
                    as market conditions change.
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
            
            {/* Inactive stats (smaller) */}
            {(profileMetrics.warming_instances > 0 || profileMetrics.cooling_instances > 0 || profileMetrics.disabled_instances > 0) && (
              <div className="flex items-center justify-center gap-3 text-[10px] text-muted-foreground">
                {profileMetrics.warming_instances > 0 && (
                  <span className="text-amber-500">{profileMetrics.warming_instances} warming</span>
                )}
                {profileMetrics.cooling_instances > 0 && (
                  <span className="text-blue-500">{profileMetrics.cooling_instances} cooling</span>
                )}
                {profileMetrics.disabled_instances > 0 && (
                  <span>{profileMetrics.disabled_instances} disabled</span>
                )}
              </div>
            )}
            
            {/* Best Match by Symbol */}
            {Object.keys(bestMatchBySymbol).length > 0 && (
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">
                  Current Best Match
                </p>
                <div className="space-y-1 max-h-[120px] overflow-y-auto">
                  {Object.entries(bestMatchBySymbol).map(([symbol, instance]) => (
                    <div key={symbol} className="flex items-center justify-between text-xs py-1">
                      <span className="font-medium">{symbol.replace('-USDT-SWAP', '')}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-muted-foreground truncate max-w-[100px]">
                          {instance.profile_id}
                        </span>
                        <span className={cn(
                          "font-mono",
                          instance.win_rate >= 50 ? "text-emerald-500" : "text-muted-foreground"
                        )}>
                          {instance.win_rate.toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {/* Top Performers */}
            {topPerformers.length > 0 && (
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">
                  Top Performers
                </p>
                <div className="space-y-0.5">
                  {topPerformers.map((instance, idx) => (
                    <ProfileRow key={`${instance.profile_id}-${instance.symbol}`} instance={instance} />
                  ))}
                </div>
              </div>
            )}
            
            {/* Error instances warning */}
            {profileMetrics.error_instances > 0 && (
              <div className="flex items-center gap-2 p-2 rounded-lg bg-red-500/10 text-xs">
                <AlertCircle className="h-4 w-4 text-red-500 shrink-0" />
                <span className="text-red-600 dark:text-red-400">
                  {profileMetrics.error_instances} profile(s) in error state
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

