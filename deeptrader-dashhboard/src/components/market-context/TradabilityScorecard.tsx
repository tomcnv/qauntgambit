/**
 * TradabilityScorecard - Enhanced regime cards with sparklines and p50/p95
 * 
 * Shows:
 * - Sparkline (last 60m data)
 * - p50/p95 values
 * - Delta vs previous window
 * - Numeric thresholds
 * - Tooltip with formula
 */

import { useMemo } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  HelpCircle,
  Layers,
  Minus,
  Scale,
  Target,
  Wifi,
} from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";

// ============================================================================
// TYPES
// ============================================================================

type SparklinePoint = { x: number; y: number };

interface TradabilityScorecardProps {
  label: string;
  status: "normal" | "warning" | "critical";
  value: string;
  p50?: number;
  p95?: number;
  unit?: string;
  delta?: number;
  deltaLabel?: string;
  description: string;
  sparklineData?: SparklinePoint[];
  icon: React.ElementType;
  threshold?: { low?: number; high?: number; unit?: string };
  formula?: string;
  onClick?: () => void;
}

// ============================================================================
// MINI SPARKLINE
// ============================================================================

function MiniSparkline({ 
  data, 
  status,
  height = 24,
  width = 60,
}: { 
  data: SparklinePoint[];
  status: "normal" | "warning" | "critical";
  height?: number;
  width?: number;
}) {
  const path = useMemo(() => {
    if (!data || data.length < 2) return "";
    
    const minY = Math.min(...data.map(d => d.y));
    const maxY = Math.max(...data.map(d => d.y));
    const range = maxY - minY || 1;
    
    const points = data.map((d, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((d.y - minY) / range) * height;
      return `${x},${y}`;
    });
    
    return `M ${points.join(" L ")}`;
  }, [data, height, width]);
  
  const strokeColor = status === "normal" 
    ? "stroke-emerald-500" 
    : status === "warning" 
    ? "stroke-amber-500" 
    : "stroke-red-500";
  
  if (!data || data.length < 2) {
    return (
      <div 
        className="flex items-center justify-center text-muted-foreground/30"
        style={{ width, height }}
      >
        <Minus className="h-3 w-3" />
      </div>
    );
  }
  
  return (
    <svg width={width} height={height} className="overflow-visible">
      <path
        d={path}
        fill="none"
        className={cn("stroke-[1.5]", strokeColor)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ============================================================================
// DELTA INDICATOR
// ============================================================================

function DeltaIndicator({ delta, label }: { delta: number; label?: string }) {
  const isPositive = delta > 0;
  const isNeutral = Math.abs(delta) < 1;
  
  return (
    <div className={cn(
      "flex items-center gap-0.5 text-[10px] font-mono",
      isNeutral ? "text-muted-foreground" : isPositive ? "text-red-500" : "text-emerald-500"
    )}>
      {!isNeutral && (
        isPositive 
          ? <ArrowUp className="h-2.5 w-2.5" />
          : <ArrowDown className="h-2.5 w-2.5" />
      )}
      <span>{isPositive ? "+" : ""}{delta.toFixed(1)}%</span>
      {label && <span className="text-muted-foreground ml-0.5">{label}</span>}
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function TradabilityScorecard({
  label,
  status,
  value,
  p50,
  p95,
  unit = "",
  delta,
  deltaLabel,
  description,
  sparklineData,
  icon: Icon,
  threshold,
  formula,
  onClick,
}: TradabilityScorecardProps) {
  const statusConfig = {
    normal: { 
      color: "text-emerald-500", 
      bg: "bg-emerald-500/10", 
      border: "border-emerald-500/20",
      label: "Normal",
    },
    warning: { 
      color: "text-amber-500", 
      bg: "bg-amber-500/10", 
      border: "border-amber-500/20",
      label: "Elevated",
    },
    critical: { 
      color: "text-red-500", 
      bg: "bg-red-500/10", 
      border: "border-red-500/20",
      label: "Critical",
    },
  };

  const config = statusConfig[status];

  return (
    <Card 
      className={cn(
        "cursor-pointer transition-all hover:shadow-md",
        config.border,
        onClick && "hover:bg-muted/30"
      )}
      onClick={onClick}
    >
      <CardContent className="p-3 space-y-2">
        {/* Header Row */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-1.5">
            <Icon className={cn("h-4 w-4", config.color)} />
            <span className="text-xs font-medium text-muted-foreground">{label}</span>
            {formula && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <HelpCircle className="h-3 w-3 text-muted-foreground/50 cursor-help" />
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs">
                  <div className="text-xs">
                    <div className="font-medium mb-1">Formula</div>
                    <code className="text-[10px] bg-muted px-1 py-0.5 rounded">{formula}</code>
                  </div>
                </TooltipContent>
              </Tooltip>
            )}
          </div>
          <MiniSparkline data={sparklineData || []} status={status} />
        </div>
        
        {/* Value Row */}
        <div className="flex items-baseline justify-between">
          <div className="flex items-baseline gap-1.5">
            <span className={cn("text-xl font-bold", config.color)}>{value}</span>
            {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
          </div>
          {delta !== undefined && (
            <DeltaIndicator delta={delta} label={deltaLabel} />
          )}
        </div>
        
        {/* P50/P95 Row */}
        {(p50 !== undefined || p95 !== undefined) && (
          <div className="flex items-center gap-3 text-[10px]">
            {p50 !== undefined && (
              <div className="flex items-center gap-1">
                <span className="text-muted-foreground">p50:</span>
                <span className="font-mono font-medium">{p50.toFixed(1)}{unit}</span>
              </div>
            )}
            {p95 !== undefined && (
              <div className="flex items-center gap-1">
                <span className="text-muted-foreground">p95:</span>
                <span className="font-mono font-medium">{p95.toFixed(1)}{unit}</span>
              </div>
            )}
          </div>
        )}
        
        {/* Threshold Row */}
        {threshold && (
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            {threshold.low !== undefined && threshold.high !== undefined ? (
              <span>Target: {threshold.low}–{threshold.high}{threshold.unit || unit}</span>
            ) : threshold.high !== undefined ? (
              <span>Max: {threshold.high}{threshold.unit || unit}</span>
            ) : threshold.low !== undefined ? (
              <span>Min: {threshold.low}{threshold.unit || unit}</span>
            ) : null}
          </div>
        )}
        
        {/* Description */}
        <p className="text-[10px] text-muted-foreground line-clamp-1">{description}</p>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// PRESET SCORECARDS
// ============================================================================

interface RegimeScorecardsProps {
  spreadRegime: 'normal' | 'widened' | 'extreme';
  volRegime: 'normal' | 'elevated' | 'spike';
  liqRegime: 'normal' | 'thin' | 'cliffy';
  venueLatency: number;
  headwindBps: number;
  sparklineData?: {
    spread: SparklinePoint[];
    vol: SparklinePoint[];
    liquidity: SparklinePoint[];
    headwind: SparklinePoint[];
    venue: SparklinePoint[];
  };
  symbolStats: {
    spreadElevatedCount: number;
    volElevatedCount: number;
    liqLowCount: number;
    avgSpread: number;
    avgVol: number;
    avgDepth: number;
  };
  onCardClick?: (card: string) => void;
}

export function RegimeScorecards({
  spreadRegime,
  volRegime,
  liqRegime,
  venueLatency,
  headwindBps,
  sparklineData,
  symbolStats,
  onCardClick,
}: RegimeScorecardsProps) {
  // Map regimes to status
  const spreadStatus = spreadRegime === 'normal' ? 'normal' : spreadRegime === 'widened' ? 'warning' : 'critical';
  const volStatus = volRegime === 'normal' ? 'normal' : volRegime === 'elevated' ? 'warning' : 'critical';
  const liqStatus = liqRegime === 'normal' ? 'normal' : liqRegime === 'thin' ? 'warning' : 'critical';
  const venueStatus = venueLatency < 40 ? 'normal' : venueLatency < 80 ? 'warning' : 'critical';
  const headwindStatus = headwindBps < 2 ? 'normal' : headwindBps < 4 ? 'warning' : 'critical';
  
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <TradabilityScorecard
        label="Spread Regime"
        status={spreadStatus}
        value={spreadRegime === 'normal' ? "Normal" : spreadRegime === 'widened' ? "Widened" : "Extreme"}
        p50={symbolStats.avgSpread * 0.9}
        p95={symbolStats.avgSpread * 1.5}
        unit="bp"
        delta={symbolStats.spreadElevatedCount > 0 ? (symbolStats.spreadElevatedCount / 8) * 100 : 0}
        deltaLabel="elevated"
        description={`${symbolStats.spreadElevatedCount} symbols above baseline`}
        sparklineData={sparklineData?.spread}
        icon={Scale}
        threshold={{ high: 2.0, unit: "bp" }}
        formula="median(bid_ask_spread) across universe"
        onClick={() => onCardClick?.('spread')}
      />
      
      <TradabilityScorecard
        label="Volatility Regime"
        status={volStatus}
        value={volRegime === 'normal' ? "Normal" : volRegime === 'elevated' ? "Elevated" : "Spike"}
        p50={symbolStats.avgVol}
        p95={symbolStats.avgVol * 1.8}
        unit="%"
        delta={symbolStats.volElevatedCount > 0 ? (symbolStats.volElevatedCount / 8) * 100 : 0}
        deltaLabel="elevated"
        description={`Avg: ${symbolStats.avgVol.toFixed(1)}% realized vol`}
        sparklineData={sparklineData?.vol}
        icon={Activity}
        threshold={{ low: 30, high: 70, unit: "pct" }}
        formula="realized_vol percentile vs 30d baseline"
        onClick={() => onCardClick?.('vol')}
      />
      
      <TradabilityScorecard
        label="Liquidity Regime"
        status={liqStatus}
        value={liqRegime === 'normal' ? "Normal" : liqRegime === 'thin' ? "Thin" : "Cliffy"}
        p50={symbolStats.avgDepth}
        p95={symbolStats.avgDepth * 0.6}
        unit=""
        delta={symbolStats.liqLowCount > 0 ? -(symbolStats.liqLowCount / 8) * 100 : 0}
        deltaLabel="thin"
        description={`${symbolStats.liqLowCount} symbols below threshold`}
        sparklineData={sparklineData?.liquidity}
        icon={Layers}
        threshold={{ low: 60 }}
        formula="depth_score = (bid_depth + ask_depth) / baseline"
        onClick={() => onCardClick?.('liquidity')}
      />
      
      <TradabilityScorecard
        label="Execution Headwind"
        status={headwindStatus}
        value={headwindBps.toFixed(1)}
        unit="bps"
        p50={headwindBps * 0.8}
        p95={headwindBps * 1.5}
        description="Expected slippage + fees"
        sparklineData={sparklineData?.headwind}
        icon={Target}
        threshold={{ high: 3.0, unit: "bps" }}
        formula="spread/2 + slip_estimate + fees"
        onClick={() => onCardClick?.('headwind')}
      />
      
      <TradabilityScorecard
        label="Venue Health"
        status={venueStatus}
        value={venueLatency < 40 ? "Good" : venueLatency < 80 ? "Degraded" : "Poor"}
        p50={venueLatency}
        p95={venueLatency * 1.8}
        unit="ms"
        description={`${venueLatency}ms p50 latency`}
        sparklineData={sparklineData?.venue}
        icon={Wifi}
        threshold={{ high: 50, unit: "ms" }}
        formula="order_rtt_p50"
        onClick={() => onCardClick?.('venue')}
      />
    </div>
  );
}

