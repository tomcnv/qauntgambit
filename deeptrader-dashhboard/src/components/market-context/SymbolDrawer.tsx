/**
 * SymbolDrawer - Enhanced symbol detail drawer
 * 
 * Shows:
 * - Mini price chart
 * - Microstructure snapshot
 * - Which gates are failing (with thresholds)
 * - What the bot would do if enabled
 * - Link to Replay Studio
 */

import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  Gauge,
  History,
  Layers,
  Play,
  Scale,
  Shield,
  Star,
  Target,
  TrendingUp,
  XCircle,
  Zap,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent } from "../ui/card";
import { Progress } from "../ui/progress";
import { Separator } from "../ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "../ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { SymbolRow, GateStatus } from "./types";

// ============================================================================
// TYPES
// ============================================================================

type Props = {
  symbol: SymbolRow | null;
  onClose: () => void;
};

// ============================================================================
// MINI CHART PLACEHOLDER
// ============================================================================

function MiniChart({ symbol }: { symbol: string }) {
  // Generate placeholder chart data
  const bars = useMemo(() => {
    return Array.from({ length: 30 }, (_, i) => ({
      height: 20 + Math.random() * 60,
      isGreen: Math.random() > 0.5,
    }));
  }, [symbol]);
  
  return (
    <div className="h-24 flex items-end gap-0.5 bg-muted/30 rounded-lg p-2">
      {bars.map((bar, i) => (
        <div
          key={i}
          className={cn(
            "flex-1 rounded-t-sm transition-all",
            bar.isGreen ? "bg-emerald-500/60" : "bg-red-500/60"
          )}
          style={{ height: `${bar.height}%` }}
        />
      ))}
    </div>
  );
}

// ============================================================================
// METRIC CARD
// ============================================================================

function MetricCard({ 
  label, 
  value, 
  baseline, 
  unit = "",
  icon: Icon,
  status = 'neutral',
}: { 
  label: string;
  value: number;
  baseline?: number;
  unit?: string;
  icon: React.ElementType;
  status?: 'good' | 'warning' | 'bad' | 'neutral';
}) {
  const statusColors = {
    good: "text-emerald-500",
    warning: "text-amber-500",
    bad: "text-red-500",
    neutral: "text-foreground",
  };
  
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <p className={cn("text-lg font-bold", statusColors[status])}>
        {value.toFixed(1)}{unit}
      </p>
      {baseline !== undefined && (
        <p className="text-[10px] text-muted-foreground">
          Baseline: {baseline.toFixed(1)}{unit}
        </p>
      )}
    </div>
  );
}

// ============================================================================
// GATE STATUS ROW
// ============================================================================

function GateStatusRow({ gate }: { gate: GateStatus }) {
  const Icon = gate.passed ? CheckCircle2 : gate.severity === 'warning' ? AlertTriangle : XCircle;
  const color = gate.passed ? "text-emerald-500" : gate.severity === 'warning' ? "text-amber-500" : "text-red-500";
  
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2">
        <Icon className={cn("h-3.5 w-3.5", color)} />
        <span className="text-xs">{gate.name}</span>
      </div>
      <div className="flex items-center gap-2 text-xs font-mono">
        <span className="text-muted-foreground">{gate.threshold}{gate.unit}</span>
        <span className="text-muted-foreground">vs</span>
        <span className={color}>{gate.actual}{gate.unit}</span>
      </div>
    </div>
  );
}

// ============================================================================
// BOT ACTION CARD
// ============================================================================

function BotActionCard({ symbol }: { symbol: SymbolRow }) {
  // Determine what the bot would do
  const action = useMemo(() => {
    if (!symbol.tradable) {
      return {
        type: 'blocked' as const,
        title: "No Action",
        description: `Blocked: ${symbol.blockedReason}`,
        icon: XCircle,
        color: "text-red-500",
      };
    }
    
    if (symbol.netEdge > 1) {
      return {
        type: 'entry' as const,
        title: "Potential Entry",
        description: `Net edge of ${symbol.netEdge.toFixed(1)}bp exceeds threshold`,
        icon: Play,
        color: "text-emerald-500",
      };
    }
    
    if (symbol.allocationState === 'throttled') {
      return {
        type: 'throttled' as const,
        title: "Throttled",
        description: "Anomaly flags present - reduced allocation",
        icon: AlertTriangle,
        color: "text-amber-500",
      };
    }
    
    return {
      type: 'monitor' as const,
      title: "Monitoring",
      description: "Waiting for entry signal",
      icon: Activity,
      color: "text-muted-foreground",
    };
  }, [symbol]);
  
  const Icon = action.icon;
  
  return (
    <div className={cn(
      "rounded-lg border p-3",
      action.type === 'entry' && "border-emerald-500/30 bg-emerald-500/5",
      action.type === 'blocked' && "border-red-500/30 bg-red-500/5",
      action.type === 'throttled' && "border-amber-500/30 bg-amber-500/5"
    )}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className={cn("h-4 w-4", action.color)} />
        <span className={cn("text-sm font-medium", action.color)}>{action.title}</span>
      </div>
      <p className="text-xs text-muted-foreground">{action.description}</p>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function SymbolDrawer({ symbol, onClose }: Props) {
  if (!symbol) return null;
  
  // Generate symbol-specific gates
  const symbolGates: GateStatus[] = useMemo(() => [
    {
      name: "Spread Cap",
      key: "spread_cap",
      threshold: 1.5,
      actual: symbol.spread,
      unit: "bp",
      passed: symbol.spread <= 1.5,
      severity: symbol.spread <= 1.5 ? 'ok' : symbol.spread <= 2.5 ? 'warning' : 'critical',
    },
    {
      name: "Vol Band",
      key: "vol_band",
      threshold: "40-80",
      actual: symbol.volPercentile.toFixed(0),
      unit: "%",
      passed: symbol.volPercentile >= 40 && symbol.volPercentile <= 80,
      severity: symbol.volPercentile >= 40 && symbol.volPercentile <= 80 ? 'ok' : 'warning',
    },
    {
      name: "Liquidity Min",
      key: "liquidity_min",
      threshold: 60,
      actual: symbol.liquidityScore,
      unit: "",
      passed: symbol.liquidityScore >= 60,
      severity: symbol.liquidityScore >= 60 ? 'ok' : symbol.liquidityScore >= 40 ? 'warning' : 'critical',
    },
    {
      name: "Funding Cap",
      key: "funding_cap",
      threshold: 3,
      actual: (symbol.funding * 100).toFixed(2),
      unit: "%",
      passed: Math.abs(symbol.funding) <= 0.03,
      severity: Math.abs(symbol.funding) <= 0.03 ? 'ok' : 'warning',
    },
  ], [symbol]);
  
  const failedGates = symbolGates.filter(g => !g.passed);
  
  return (
    <Sheet open={!!symbol} onOpenChange={onClose}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <div className="flex items-center gap-2">
            {symbol.pinned && <Star className="h-4 w-4 text-amber-500 fill-amber-500" />}
            <SheetTitle className="text-lg">{symbol.symbol}</SheetTitle>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                symbol.regime === "Normal" && "border-emerald-500/50 text-emerald-500",
                symbol.regime !== "Normal" && "border-amber-500/50 text-amber-500"
              )}
            >
              {symbol.regime}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                symbol.tradable ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
              )}
            >
              {symbol.tradable ? "Tradable" : "Blocked"}
            </Badge>
          </div>
          <SheetDescription>Market microstructure and trading status</SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Mini Chart */}
          <div>
            <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
              <BarChart3 className="h-3.5 w-3.5" />
              Price Action (15m)
            </h3>
            <MiniChart symbol={symbol.symbol} />
          </div>
          
          {/* Edge Metrics */}
          <div>
            <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
              <Target className="h-3.5 w-3.5" />
              Edge Analysis
            </h3>
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-lg border bg-card p-2 text-center">
                <p className="text-[10px] text-muted-foreground">Expected</p>
                <p className={cn(
                  "text-sm font-bold",
                  symbol.expectedEdge > 0 ? "text-emerald-500" : "text-muted-foreground"
                )}>
                  {symbol.expectedEdge > 0 ? "+" : ""}{symbol.expectedEdge.toFixed(1)}bp
                </p>
              </div>
              <div className="rounded-lg border bg-card p-2 text-center">
                <p className="text-[10px] text-muted-foreground">Headwind</p>
                <p className="text-sm font-bold text-red-500">
                  -{symbol.headwind.toFixed(1)}bp
                </p>
              </div>
              <div className="rounded-lg border bg-card p-2 text-center">
                <p className="text-[10px] text-muted-foreground">Net Edge</p>
                <p className={cn(
                  "text-sm font-bold",
                  symbol.netEdge > 0 ? "text-emerald-500" : "text-red-500"
                )}>
                  {symbol.netEdge > 0 ? "+" : ""}{symbol.netEdge.toFixed(1)}bp
                </p>
              </div>
            </div>
          </div>
          
          {/* Key Metrics */}
          <div>
            <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
              <Gauge className="h-3.5 w-3.5" />
              Microstructure
            </h3>
            <div className="grid grid-cols-2 gap-2">
              <MetricCard
                label="Spread"
                value={symbol.spread}
                baseline={symbol.spreadBaseline}
                unit=" bp"
                icon={Scale}
                status={symbol.spread > 2 ? 'bad' : symbol.spread > 1.5 ? 'warning' : 'good'}
              />
              <MetricCard
                label="Volatility"
                value={symbol.volPercentile}
                unit="%"
                icon={Activity}
                status={symbol.volPercentile > 80 ? 'bad' : symbol.volPercentile > 60 ? 'warning' : 'good'}
              />
              <MetricCard
                label="Liquidity"
                value={symbol.liquidityScore}
                icon={Layers}
                status={symbol.liquidityScore < 50 ? 'bad' : symbol.liquidityScore < 70 ? 'warning' : 'good'}
              />
              <MetricCard
                label="Funding"
                value={symbol.funding * 100}
                unit="%"
                icon={TrendingUp}
                status={symbol.fundingSpike ? 'warning' : 'neutral'}
              />
            </div>
          </div>
          
          {/* P50/P95 Details */}
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div>
              <p className="text-muted-foreground mb-1">Spread Distribution</p>
              <div className="flex items-center gap-2">
                <span className="font-mono">p50: {symbol.spreadP50.toFixed(1)}bp</span>
                <span className="text-muted-foreground">/</span>
                <span className="font-mono">p95: {symbol.spreadP95.toFixed(1)}bp</span>
              </div>
            </div>
            <div>
              <p className="text-muted-foreground mb-1">Depth Score</p>
              <div className="flex items-center gap-2">
                <span className="font-mono">{symbol.depth.toFixed(0)}</span>
                <span className="text-muted-foreground">vs baseline</span>
                <span className="font-mono">{symbol.depthBaseline}</span>
              </div>
            </div>
          </div>
          
          <Separator />
          
          {/* Gates Status */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Shield className="h-3.5 w-3.5" />
                Trading Gates
              </h3>
              {failedGates.length > 0 && (
                <Badge variant="outline" className="text-[10px] border-red-500/50 text-red-500">
                  {failedGates.length} failing
                </Badge>
              )}
            </div>
            <div className="rounded-lg border divide-y">
              {symbolGates.map(gate => (
                <GateStatusRow key={gate.key} gate={gate} />
              ))}
            </div>
          </div>
          
          {/* Anomaly Flags */}
          {symbol.anomalyFlags.length > 0 && (
            <div>
              <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                Anomaly Flags
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {symbol.anomalyFlags.map((flag, idx) => (
                  <Badge 
                    key={idx}
                    variant="outline" 
                    className="text-[10px] border-amber-500/50 text-amber-500"
                  >
                    {flag.replace(/_/g, ' ')}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          
          <Separator />
          
          {/* Bot Action */}
          <div>
            <h3 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5" />
              Bot Action
            </h3>
            <BotActionCard symbol={symbol} />
          </div>
          
          <Separator />

          {/* Cross-page Links */}
          <div className="space-y-2">
            <h3 className="text-xs font-medium text-muted-foreground mb-2">Quick Links</h3>
            
            <Link to={`/analysis/replay?symbol=${symbol.symbol}`}>
              <Button variant="outline" size="sm" className="w-full justify-between">
                <span className="flex items-center gap-2">
                  <History className="h-4 w-4" />
                  Open in Replay Studio
                </span>
                <ExternalLink className="h-3.5 w-3.5" />
              </Button>
            </Link>
            
            <Link to={`/live?symbol=${symbol.symbol}`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
                <ExternalLink className="h-4 w-4 mr-2" />
                View orders/fills
              </Button>
            </Link>
            <Link to={`/analysis/execution?symbol=${symbol.symbol}`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
                <ExternalLink className="h-4 w-4 mr-2" />
                View execution quality
              </Button>
            </Link>
            <Link to={`/live/positions?symbol=${symbol.symbol}`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-muted-foreground">
                <ExternalLink className="h-4 w-4 mr-2" />
                View positions
              </Button>
            </Link>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
