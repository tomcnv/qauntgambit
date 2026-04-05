/**
 * ProfileRejectionPanel - Shows why profiles are NOT being selected
 * 
 * Helps diagnose:
 * - Misconfigured profiles
 * - Non-orthogonal profiles (overlapping conditions)
 * - Market conditions that don't match any profiles
 */

import { useMemo } from "react";
import {
  AlertTriangle,
  Ban,
  ChevronDown,
  ChevronRight,
  Filter,
  HelpCircle,
  Info,
  TrendingDown,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { useProfileRouter } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import type { ProfileRouterResponse } from "../../lib/api/types";

// ============================================================================
// REJECTION REASON EXPLANATIONS
// ============================================================================

const REJECTION_EXPLANATIONS: Record<string, { label: string; description: string; severity: 'info' | 'warning' | 'error' }> = {
  // Trend filters
  'trend_mismatch': { 
    label: 'Trend Mismatch', 
    description: 'Profile requires a specific trend direction (up/down/neutral) that doesn\'t match current market',
    severity: 'info'
  },
  'trend_too_weak': { 
    label: 'Trend Too Weak', 
    description: 'Market trend strength is below the minimum required by this profile',
    severity: 'info'
  },
  'trend_too_strong': { 
    label: 'Trend Too Strong', 
    description: 'Market trend is stronger than the maximum allowed by this profile',
    severity: 'info'
  },
  // Volatility filters
  'vol_mismatch': { 
    label: 'Volatility Mismatch', 
    description: 'Profile requires a specific volatility regime (low/medium/high) that doesn\'t match',
    severity: 'info'
  },
  'vol_too_low': { 
    label: 'Volatility Too Low', 
    description: 'Market volatility is below the minimum required for this profile\'s strategy',
    severity: 'info'
  },
  'vol_too_high': { 
    label: 'Volatility Too High', 
    description: 'Market volatility exceeds the maximum safe level for this profile',
    severity: 'warning'
  },
  // Value area filters
  'value_mismatch': { 
    label: 'Value Location Mismatch', 
    description: 'Price is not in the required value area location (above/below/inside)',
    severity: 'info'
  },
  // Session filters
  'session_mismatch': { 
    label: 'Session Mismatch', 
    description: 'Profile is designed for a different trading session (Asia/Europe/US)',
    severity: 'info'
  },
  'session_not_allowed': { 
    label: 'Session Not Allowed', 
    description: 'Current session is not in the list of allowed sessions for this profile',
    severity: 'info'
  },
  // Risk mode filters
  'risk_mode_mismatch': { 
    label: 'Risk Mode Mismatch', 
    description: 'Profile requires a different risk mode than currently active',
    severity: 'warning'
  },
  // Microstructure filters
  'spread_too_wide': { 
    label: 'Spread Too Wide', 
    description: 'Current bid-ask spread exceeds the maximum allowed for profitable execution',
    severity: 'warning'
  },
  'tps_too_low': { 
    label: 'Trade Velocity Too Low', 
    description: 'Not enough trades per second for this profile\'s liquidity requirements',
    severity: 'info'
  },
  // Rotation filters
  'rotation_too_low': { 
    label: 'Rotation Too Low', 
    description: 'Market rotation factor is below the minimum for this profile\'s strategy',
    severity: 'info'
  },
  'rotation_too_high': { 
    label: 'Rotation Too High', 
    description: 'Market rotation is too high for this profile\'s strategy',
    severity: 'info'
  },
  // Lifecycle states
  'lifecycle_state': { 
    label: 'Lifecycle State', 
    description: 'Profile instance is not in ACTIVE state (may be warming, cooling, or disabled)',
    severity: 'warning'
  },
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function ProfileRejectionPanel({ className }: { className?: string }) {
  const { botId } = useScopeStore();
  const { data: routerData, isLoading } = useProfileRouter(botId);
  
  // Process rejection reasons into a more useful format
  const rejectionAnalysis = useMemo(() => {
    if (!routerData?.top_rejection_reasons?.length) return null;
    
    const totalRejections = routerData.top_rejection_reasons.reduce((sum, [, count]) => sum + count, 0);
    
    // Categorize rejections
    const categories: Record<string, { reasons: Array<{ reason: string; count: number; pct: number }>; total: number }> = {
      'Market Conditions': { reasons: [], total: 0 },
      'Microstructure': { reasons: [], total: 0 },
      'Session/Time': { reasons: [], total: 0 },
      'Lifecycle': { reasons: [], total: 0 },
      'Other': { reasons: [], total: 0 },
    };
    
    for (const [reason, count] of routerData.top_rejection_reasons) {
      const pct = (count / totalRejections) * 100;
      const entry = { reason, count, pct };
      
      if (reason.includes('trend') || reason.includes('vol')) {
        categories['Market Conditions'].reasons.push(entry);
        categories['Market Conditions'].total += count;
      } else if (reason.includes('spread') || reason.includes('tps') || reason.includes('rotation')) {
        categories['Microstructure'].reasons.push(entry);
        categories['Microstructure'].total += count;
      } else if (reason.includes('session')) {
        categories['Session/Time'].reasons.push(entry);
        categories['Session/Time'].total += count;
      } else if (reason.includes('lifecycle')) {
        categories['Lifecycle'].reasons.push(entry);
        categories['Lifecycle'].total += count;
      } else {
        categories['Other'].reasons.push(entry);
        categories['Other'].total += count;
      }
    }
    
    return {
      totalRejections,
      categories,
      topReasons: routerData.top_rejection_reasons.slice(0, 5),
    };
  }, [routerData?.top_rejection_reasons]);
  
  // Get rejection details per symbol
  const symbolRejections = useMemo(() => {
    if (!routerData?.rejection_summary) return {};
    return routerData.rejection_summary;
  }, [routerData?.rejection_summary]);
  
  const hasData = rejectionAnalysis && rejectionAnalysis.totalRejections > 0;
  
  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Why Profiles Aren't Selected</CardTitle>
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle className="h-4 w-4 text-muted-foreground cursor-help" />
            </TooltipTrigger>
            <TooltipContent className="max-w-[300px]">
              <p className="font-medium mb-1">Profile Selection Analysis</p>
              <p className="text-xs text-muted-foreground">
                Shows why profiles are being rejected during selection. 
                This helps identify misconfigured profiles or market conditions 
                that don't match any profile's requirements.
              </p>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      
      <CardContent>
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Filter className="h-5 w-5 animate-pulse text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Analyzing rejections...</span>
          </div>
        ) : !hasData ? (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <Info className="h-6 w-6 text-muted-foreground/50 mb-2" />
            <p className="text-sm text-muted-foreground">No rejection data yet</p>
            <p className="text-[10px] text-muted-foreground/70 mt-1">
              Data appears after profiles are evaluated
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Top Rejection Reasons */}
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">
                Top Rejection Reasons
              </p>
              <div className="space-y-2">
                {rejectionAnalysis.topReasons.map(([reason, count]) => {
                  const explanation = REJECTION_EXPLANATIONS[reason] || {
                    label: reason.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
                    description: 'Profile condition not met',
                    severity: 'info' as const
                  };
                  const pct = (count / rejectionAnalysis.totalRejections) * 100;
                  
                  return (
                    <Tooltip key={reason}>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-2 cursor-default">
                          {/* Severity icon */}
                          {explanation.severity === 'error' ? (
                            <XCircle className="h-3 w-3 text-red-500 shrink-0" />
                          ) : explanation.severity === 'warning' ? (
                            <AlertTriangle className="h-3 w-3 text-amber-500 shrink-0" />
                          ) : (
                            <Ban className="h-3 w-3 text-muted-foreground shrink-0" />
                          )}
                          
                          {/* Reason label */}
                          <span className="text-xs flex-1 truncate">{explanation.label}</span>
                          
                          {/* Count & percentage */}
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-[10px] text-muted-foreground">
                              {count.toLocaleString()}
                            </span>
                            <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                              <div 
                                className={cn(
                                  "h-full rounded-full",
                                  explanation.severity === 'error' ? "bg-red-500" :
                                  explanation.severity === 'warning' ? "bg-amber-500" :
                                  "bg-muted-foreground/50"
                                )}
                                style={{ width: `${Math.min(pct, 100)}%` }}
                              />
                            </div>
                            <span className="text-[10px] font-mono w-10 text-right">
                              {pct.toFixed(0)}%
                            </span>
                          </div>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-[250px]">
                        <p className="font-medium">{explanation.label}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {explanation.description}
                        </p>
                        <p className="text-[10px] text-muted-foreground/70 mt-2">
                          Rejected {count.toLocaleString()} times
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            </div>
            
            {/* Category Breakdown */}
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">
                By Category
              </p>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(rejectionAnalysis.categories)
                  .filter(([, data]) => data.total > 0)
                  .sort((a, b) => b[1].total - a[1].total)
                  .slice(0, 4)
                  .map(([category, data]) => {
                    const pct = (data.total / rejectionAnalysis.totalRejections) * 100;
                    return (
                      <Tooltip key={category}>
                        <TooltipTrigger asChild>
                          <div className="p-2 rounded-lg bg-muted/30 cursor-default">
                            <p className="text-[10px] text-muted-foreground truncate">{category}</p>
                            <p className="text-sm font-bold">{pct.toFixed(0)}%</p>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="font-medium">{category}</p>
                          <p className="text-xs text-muted-foreground">
                            {data.total.toLocaleString()} rejections ({pct.toFixed(1)}%)
                          </p>
                          <div className="mt-1 text-[10px]">
                            {data.reasons.slice(0, 3).map(r => (
                              <div key={r.reason} className="text-muted-foreground">
                                • {r.reason}: {r.count}
                              </div>
                            ))}
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
              </div>
            </div>
            
            {/* Insight */}
            {rejectionAnalysis.topReasons.length > 0 && (
              <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                <div className="flex items-start gap-2">
                  <Info className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                  <div className="text-xs">
                    <p className="font-medium text-blue-600 dark:text-blue-400">
                      Profile Selection Insight
                    </p>
                    <p className="text-muted-foreground mt-1">
                      {getInsightMessage(rejectionAnalysis)}
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Type for rejection analysis
interface RejectionAnalysis {
  totalRejections: number;
  categories: Record<string, { reasons: Array<{ reason: string; count: number; pct: number }>; total: number }>;
  topReasons: Array<[string, number]>;
}

// Generate insight message based on rejection patterns
function getInsightMessage(analysis: RejectionAnalysis): string {
  if (!analysis) return '';
  
  const topCategory = Object.entries(analysis.categories)
    .filter(([, data]) => data.total > 0)
    .sort((a, b) => b[1].total - a[1].total)[0];
  
  if (!topCategory) return 'All profiles are being evaluated correctly.';
  
  const [category, data] = topCategory;
  const pct = (data.total / analysis.totalRejections) * 100;
  
  if (category === 'Market Conditions' && pct > 50) {
    return `${pct.toFixed(0)}% of rejections are due to market conditions. This is normal - profiles are designed for specific market states.`;
  }
  
  if (category === 'Session/Time' && pct > 30) {
    return `Many profiles are session-specific. Consider adding more profiles for the current trading session.`;
  }
  
  if (category === 'Microstructure' && pct > 30) {
    return `Microstructure conditions (spread, liquidity) are blocking many profiles. Market may be thin.`;
  }
  
  if (category === 'Lifecycle' && pct > 20) {
    return `Some profiles are in warming/cooling states. They will become available shortly.`;
  }
  
  return `Most rejections (${pct.toFixed(0)}%) are from ${category.toLowerCase()} filters.`;
}

