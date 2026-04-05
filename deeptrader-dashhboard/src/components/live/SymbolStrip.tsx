import { useMemo } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "../ui/badge";
import { ScrollArea, ScrollBar } from "../ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn, formatSymbolDisplay } from "../../lib/utils";
import { SymbolStats } from "./types";

interface SymbolStripProps {
  symbols: SymbolStats[];
  selectedSymbol?: string;
  onSymbolClick?: (symbol: string) => void;
  className?: string;
}

function SymbolPill({
  stats,
  isSelected,
  onClick,
}: {
  stats: SymbolStats;
  isSelected: boolean;
  onClick?: () => void;
}) {
  const isProfitable = stats.netPnl >= 0;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs transition-all shrink-0",
            "hover:bg-muted/50 hover:border-primary/30",
            isSelected 
              ? "bg-primary/10 border-primary/50" 
              : "bg-card border-border"
          )}
        >
          <span className="font-medium">{formatSymbolDisplay(stats.symbol)}</span>
          
          <div className="flex items-center gap-0.5">
            {isProfitable 
              ? <TrendingUp className="h-3 w-3 text-emerald-500" />
              : <TrendingDown className="h-3 w-3 text-red-500" />
            }
            <span className={cn(
              "font-mono text-[11px]",
              isProfitable ? "text-emerald-500" : "text-red-500"
            )}>
              {isProfitable ? "+" : ""}${stats.netPnl.toFixed(2)}
            </span>
          </div>

          <Badge variant="outline" className="h-4 px-1 text-[9px] font-mono">
            {stats.fillsCount}
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        <div className="space-y-1">
          <p className="font-medium">{formatSymbolDisplay(stats.symbol)}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted-foreground">
            <span>P&L:</span>
            <span className={cn("font-mono", stats.netPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
              {stats.netPnl >= 0 ? "+" : ""}${stats.netPnl.toFixed(2)}
            </span>
            <span>Fills:</span>
            <span className="font-mono">{stats.fillsCount}</span>
            <span>Avg Slip:</span>
            <span className="font-mono">{stats.avgSlippage.toFixed(2)}bp</span>
            <span>Avg Latency:</span>
            <span className="font-mono">{stats.avgLatency.toFixed(0)}ms</span>
            <span>Volume:</span>
            <span className="font-mono">${stats.volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
          </div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

export function SymbolStrip({ symbols, selectedSymbol, onSymbolClick, className }: SymbolStripProps) {
  // Sort by fills count descending
  const sortedSymbols = useMemo(() => {
    return [...symbols].sort((a, b) => b.fillsCount - a.fillsCount);
  }, [symbols]);

  if (sortedSymbols.length === 0) {
    return null;
  }

  const totalPnl = sortedSymbols.reduce((sum, s) => sum + s.netPnl, 0);
  const totalFills = sortedSymbols.reduce((sum, s) => sum + s.fillsCount, 0);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {/* Summary badge */}
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-muted/50 border text-[10px] shrink-0">
        <span className="text-muted-foreground">{sortedSymbols.length} symbols</span>
        <span className="text-muted-foreground">·</span>
        <span className="font-mono">{totalFills} fills</span>
        <span className="text-muted-foreground">·</span>
        <span className={cn("font-mono", totalPnl >= 0 ? "text-emerald-500" : "text-red-500")}>
          {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}
        </span>
      </div>

      {/* Scrollable symbol pills */}
      <ScrollArea className="flex-1">
        <div className="flex items-center gap-2 pb-2">
          {sortedSymbols.map((stats) => (
            <SymbolPill
              key={stats.symbol}
              stats={stats}
              isSelected={stats.symbol === selectedSymbol}
              onClick={() => onSymbolClick?.(stats.symbol)}
            />
          ))}
        </div>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>

      {/* Clear filter button */}
      {selectedSymbol && (
        <button
          onClick={() => onSymbolClick?.("")}
          className="text-[10px] text-muted-foreground hover:text-foreground px-2"
        >
          Clear
        </button>
      )}
    </div>
  );
}

// Hook to derive symbol stats from fills
export function useSymbolStats(fills: any[]): SymbolStats[] {
  return useMemo(() => {
    const bySymbol = new Map<string, {
      pnl: number;
      count: number;
      slippages: number[];
      latencies: number[];
      volume: number;
    }>();

    fills.forEach(fill => {
      const symbol = fill.symbol || "UNKNOWN";
      const existing = bySymbol.get(symbol) || {
        pnl: 0,
        count: 0,
        slippages: [],
        latencies: [],
        volume: 0,
      };

      // Calculate P&L: use provided pnl, or calculate from entry/exit prices
      let fillPnl = parseFloat(fill.pnl) || 0;
      if (fillPnl === 0 && fill.entryPrice && fill.exitPrice) {
        const entry = parseFloat(fill.entryPrice) || 0;
        const exit = parseFloat(fill.exitPrice) || 0;
        const qty = parseFloat(fill.quantity || fill.size || 0) || 0;
        const side = (fill.side || '').toUpperCase();
        // Only calculate P&L if entry and exit are different (meaning it's a closing trade)
        // If entry == exit, it's likely an opening trade with no realized P&L yet
        if (entry > 0 && exit > 0 && qty > 0 && Math.abs(entry - exit) > 0.0001) {
          // SELL fill closing a LONG: profit = (exit - entry) * qty
          // BUY fill closing a SHORT: profit = (entry - exit) * qty
          if (side === 'SELL') {
            fillPnl = (exit - entry) * qty;
          } else if (side === 'BUY') {
            fillPnl = (entry - exit) * qty;
          }
        }
      }
      // Subtract fees if available
      const fee = parseFloat(fill.fee || fill.fees || 0) || 0;
      fillPnl -= Math.abs(fee);

      existing.pnl += fillPnl;
      existing.count += 1;
      if (fill.slippage !== undefined && fill.slippage !== null) {
        existing.slippages.push(fill.slippage);
      }
      if (fill.latency !== undefined && fill.latency !== null) {
        existing.latencies.push(fill.latency);
      }
      existing.volume += (fill.quantity || 0) * (fill.entryPrice || fill.price || 0);

      bySymbol.set(symbol, existing);
    });

    return Array.from(bySymbol.entries()).map(([symbol, data]) => ({
      symbol,
      netPnl: data.pnl,
      fillsCount: data.count,
      avgSlippage: data.slippages.length > 0 
        ? data.slippages.reduce((a, b) => a + b, 0) / data.slippages.length 
        : 0,
      avgLatency: data.latencies.length > 0 
        ? data.latencies.reduce((a, b) => a + b, 0) / data.latencies.length 
        : 0,
      volume: data.volume,
    }));
  }, [fills]);
}

