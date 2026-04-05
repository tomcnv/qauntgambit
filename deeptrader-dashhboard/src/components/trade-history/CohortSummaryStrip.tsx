/**
 * CohortSummaryStrip - Compact bar showing cohort snapshot with KPI metrics
 */

import { useState, useMemo } from 'react';
import { Card } from '../ui/card';
import { Badge } from '../ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../ui/tooltip';
import { cn } from '../../lib/utils';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Percent,
  Clock,
  Zap,
  Target,
  AlertTriangle,
  Activity,
  BarChart3,
} from 'lucide-react';
import { CohortStats, EMPTY_COHORT_STATS } from './types';
import {
  BarChart,
  Bar,
  ResponsiveContainer,
  Cell,
} from 'recharts';

interface CohortSummaryStripProps {
  stats: CohortStats;
  isLoading?: boolean;
}

interface MetricChipProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  subValue?: string;
  trend?: 'up' | 'down' | 'neutral';
  distribution?: number[];
  tooltip?: string;
}

function MetricChip({ 
  icon, 
  label, 
  value, 
  subValue, 
  trend = 'neutral',
  distribution,
  tooltip,
}: MetricChipProps) {
  const [showChart, setShowChart] = useState(false);
  
  const trendColors = {
    up: 'text-emerald-500',
    down: 'text-red-500',
    neutral: 'text-foreground',
  };
  
  const chartData = useMemo(() => {
    if (!distribution || distribution.length === 0) return [];
    return distribution.map((count, i) => ({ value: count, index: i }));
  }, [distribution]);
  
  const content = (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/50 border transition-all",
        distribution && "cursor-pointer hover:bg-muted hover:border-border"
      )}
      onClick={() => distribution && setShowChart(!showChart)}
    >
      <span className="text-muted-foreground">{icon}</span>
      <div className="flex flex-col">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <div className="flex items-baseline gap-1">
          <span className={cn("text-sm font-semibold", trendColors[trend])}>
            {value}
          </span>
          {subValue && (
            <span className="text-[10px] text-muted-foreground">{subValue}</span>
          )}
        </div>
      </div>
      
      {/* Inline mini-chart */}
      {showChart && chartData.length > 0 && (
        <div className="w-16 h-6 ml-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <Bar dataKey="value" radius={[1, 1, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={trend === 'up' ? '#10b981' : trend === 'down' ? '#ef4444' : '#6b7280'} 
                    opacity={0.6}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
  
  if (tooltip) {
    return (
      <TooltipProvider>
        <Tooltip delayDuration={300}>
          <TooltipTrigger asChild>
            {content}
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p className="text-xs">{tooltip}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  
  return content;
}

function formatCurrency(value: number): string {
  if (Math.abs(value) >= 1000000) {
    return `${value >= 0 ? '+' : ''}$${(value / 1000000).toFixed(2)}M`;
  }
  if (Math.abs(value) >= 1000) {
    return `${value >= 0 ? '+' : ''}$${(value / 1000).toFixed(1)}K`;
  }
  return `${value >= 0 ? '+' : ''}$${value.toFixed(2)}`;
}

export function CohortSummaryStrip({ stats, isLoading }: CohortSummaryStripProps) {
  if (isLoading) {
    return (
      <Card className="p-4">
        <div className="flex items-center justify-center">
          <div className="animate-pulse flex items-center gap-4">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-12 w-28 rounded-lg bg-muted" />
            ))}
          </div>
        </div>
      </Card>
    );
  }
  
  if (stats.totalTrades === 0) {
    return (
      <Card className="p-4">
        <div className="flex items-center justify-center text-muted-foreground">
          <BarChart3 className="h-5 w-5 mr-2 opacity-50" />
          <span className="text-sm">No trades in this cohort</span>
        </div>
      </Card>
    );
  }
  
  const pnlTrend = stats.netPnl > 0 ? 'up' : stats.netPnl < 0 ? 'down' : 'neutral';
  const winRateTrend = stats.winRate >= 50 ? 'up' : 'down';
  
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-3">
        {/* Trade Count */}
        <MetricChip
          icon={<Target className="h-3.5 w-3.5" />}
          label="Trades"
          value={stats.totalTrades.toLocaleString()}
          subValue={`${stats.winningTrades}W / ${stats.losingTrades}L`}
          tooltip="Total trades in cohort (wins / losses)"
        />
        
        {/* Win Rate */}
        <MetricChip
          icon={<Percent className="h-3.5 w-3.5" />}
          label="Win Rate"
          value={`${stats.winRate.toFixed(1)}%`}
          trend={winRateTrend}
          tooltip="Percentage of profitable trades"
        />
        
        {/* Profit Factor */}
        <MetricChip
          icon={stats.profitFactor >= 1 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
          label="Profit Factor"
          value={stats.profitFactor === Infinity ? '∞' : stats.profitFactor.toFixed(2)}
          trend={stats.profitFactor >= 1 ? 'up' : 'down'}
          tooltip="Gross profits / Gross losses"
        />
        
        <div className="h-8 w-px bg-border" />
        
        {/* Net P&L */}
        <MetricChip
          icon={<DollarSign className="h-3.5 w-3.5" />}
          label="Net P&L"
          value={formatCurrency(stats.netPnl)}
          subValue={`-$${Math.abs(stats.totalFees).toFixed(0)} fees`}
          trend={pnlTrend}
          distribution={stats.pnlDistribution}
          tooltip="Net P&L after fees (click for distribution)"
        />
        
        {/* Avg P&L */}
        <MetricChip
          icon={<Activity className="h-3.5 w-3.5" />}
          label="Avg P&L"
          value={formatCurrency(stats.avgPnl)}
          subValue={`med: ${formatCurrency(stats.medianPnl)}`}
          trend={stats.avgPnl > 0 ? 'up' : stats.avgPnl < 0 ? 'down' : 'neutral'}
          tooltip="Average P&L per trade (median)"
        />
        
        {/* Best/Worst - stacked layout */}
        <div className="flex flex-col px-3 py-2 rounded-lg bg-muted/50 border">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Best / Worst
          </span>
          <div className="flex items-baseline gap-1">
            <span className="text-sm font-semibold text-emerald-500">{formatCurrency(stats.largestWin)}</span>
            <span className="text-muted-foreground text-xs">/</span>
            <span className="text-sm font-semibold text-red-500">{formatCurrency(stats.largestLoss)}</span>
          </div>
        </div>
        
        <div className="h-8 w-px bg-border" />
        
        {/* Avg Slippage */}
        <MetricChip
          icon={<Zap className="h-3.5 w-3.5" />}
          label="Slippage"
          value={`${stats.avgSlippageBps.toFixed(1)} bps`}
          distribution={stats.slippageDistribution}
          tooltip="Average slippage in basis points (click for distribution)"
        />
        
        {/* Avg Latency */}
        <MetricChip
          icon={<Clock className="h-3.5 w-3.5" />}
          label="Latency"
          value={`${stats.avgLatencyMs.toFixed(0)} ms`}
          tooltip="Average fill latency"
        />
        
        {/* MAE/MFE - stacked layout */}
        {(stats.avgMaeBps !== undefined || stats.avgMfeBps !== undefined) && (
          <div className="flex flex-col px-3 py-2 rounded-lg bg-muted/50 border">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              MAE / MFE
            </span>
            <div className="flex items-baseline gap-1">
              <span className="text-sm font-semibold text-red-500">
                {stats.avgMaeBps !== undefined ? `${stats.avgMaeBps.toFixed(0)}bp` : '—'}
              </span>
              <span className="text-muted-foreground text-xs">/</span>
              <span className="text-sm font-semibold text-emerald-500">
                {stats.avgMfeBps !== undefined ? `${stats.avgMfeBps.toFixed(0)}bp` : '—'}
              </span>
            </div>
          </div>
        )}
        
        {/* Reject Rate */}
        {stats.rejectRate > 0 && (
          <MetricChip
            icon={<AlertTriangle className="h-3.5 w-3.5" />}
            label="Reject Rate"
            value={`${stats.rejectRate.toFixed(1)}%`}
            trend="down"
            tooltip="Percentage of rejected decisions"
          />
        )}
        
        <div className="flex-1" />
        
        {/* Best/Worst Symbol - stacked layout */}
        {stats.bestSymbol && (
          <div className="flex flex-col px-3 py-2 rounded-lg bg-muted/50 border">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Top / Bottom Symbol
            </span>
            <div className="flex items-center gap-1.5">
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-emerald-500 bg-emerald-500/10 border-emerald-500/30">
                {stats.bestSymbol.replace('-USDT-SWAP', '').replace('-USDT', '')}
              </Badge>
              <span className="text-muted-foreground text-xs">/</span>
              {stats.worstSymbol && stats.worstSymbol !== stats.bestSymbol ? (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-red-500 bg-red-500/10 border-red-500/30">
                  {stats.worstSymbol.replace('-USDT-SWAP', '').replace('-USDT', '')}
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

export default CohortSummaryStrip;
