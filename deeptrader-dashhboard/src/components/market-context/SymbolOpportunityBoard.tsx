/**
 * SymbolOpportunityBoard - Ranked table of tradable universe
 * 
 * Columns:
 * - Symbol (with pinned indicator)
 * - Tradable? (Yes/No + gate reason)
 * - Expected Edge (bps)
 * - Headwind (bps)
 * - Net Edge (bps)
 * - Vol percentile
 * - Spread (p50/p95)
 * - Liquidity score
 * - Funding/basis
 * - Anomaly flags
 * - Allocation state
 */

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CheckCircle2,
  ChevronDown,
  Grid3X3,
  List,
  Star,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { SymbolRow } from "./types";

// ============================================================================
// TYPES
// ============================================================================

type SortKey = 'symbol' | 'netEdge' | 'spread' | 'vol' | 'liquidity' | 'funding';
type SortDir = 'asc' | 'desc';
type ViewMode = 'table' | 'heatmap';
type FilterView = 'all' | 'tradable' | 'blocked';

interface SymbolOpportunityBoardProps {
  symbols: SymbolRow[];
  onSymbolClick: (symbol: SymbolRow) => void;
  className?: string;
}

// ============================================================================
// SORT HEADER
// ============================================================================

function SortHeader({ 
  label, 
  sortKey, 
  currentSort, 
  currentDir, 
  onSort,
  align = 'right',
}: { 
  label: string;
  sortKey: SortKey;
  currentSort: SortKey;
  currentDir: SortDir;
  onSort: (key: SortKey) => void;
  align?: 'left' | 'right';
}) {
  const isActive = currentSort === sortKey;
  
  return (
    <th 
      className={cn(
        "py-2 px-2 font-medium text-muted-foreground cursor-pointer hover:text-foreground transition-colors",
        align === 'left' ? "text-left" : "text-right"
      )}
      onClick={() => onSort(sortKey)}
    >
      <div className={cn(
        "flex items-center gap-1",
        align === 'right' && "justify-end"
      )}>
        <span className="text-[11px]">{label}</span>
        {isActive ? (
          currentDir === 'asc' 
            ? <ArrowUp className="h-3 w-3" />
            : <ArrowDown className="h-3 w-3" />
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </div>
    </th>
  );
}

// ============================================================================
// STATUS BADGE
// ============================================================================

function TradableStatus({ symbol }: { symbol: SymbolRow }) {
  if (symbol.tradable) {
    return (
      <Badge 
        variant="outline" 
        className="text-[10px] px-1.5 py-0 border-emerald-500/50 text-emerald-500 gap-1"
      >
        <CheckCircle2 className="h-2.5 w-2.5" />
        OK
      </Badge>
    );
  }
  
  return (
    <Tooltip>
      <TooltipTrigger>
        <Badge 
          variant="outline" 
          className="text-[10px] px-1.5 py-0 border-red-500/50 text-red-500 gap-1"
        >
          <XCircle className="h-2.5 w-2.5" />
          Blocked
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="right" className="text-xs">
        {symbol.blockedReason || "Gate conditions not met"}
      </TooltipContent>
    </Tooltip>
  );
}

// ============================================================================
// ALLOCATION STATE BADGE
// ============================================================================

function AllocationBadge({ state }: { state: SymbolRow['allocationState'] }) {
  if (state === 'allowed') {
    return (
      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-emerald-500/30 text-emerald-500">
        Allowed
      </Badge>
    );
  }
  if (state === 'throttled') {
    return (
      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-amber-500/30 text-amber-500">
        Throttled
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-red-500/30 text-red-500">
      Blocked
    </Badge>
  );
}

// ============================================================================
// ANOMALY FLAGS
// ============================================================================

function AnomalyFlags({ flags }: { flags: string[] }) {
  if (flags.length === 0) return <span className="text-muted-foreground">—</span>;
  
  return (
    <div className="flex gap-1">
      {flags.slice(0, 2).map((flag, idx) => (
        <Tooltip key={idx}>
          <TooltipTrigger>
            <Badge 
              variant="outline" 
              className="text-[9px] px-1 py-0 border-amber-500/30 text-amber-500"
            >
              <AlertTriangle className="h-2 w-2" />
            </Badge>
          </TooltipTrigger>
          <TooltipContent>{flag.replace(/_/g, ' ')}</TooltipContent>
        </Tooltip>
      ))}
      {flags.length > 2 && (
        <span className="text-[9px] text-muted-foreground">+{flags.length - 2}</span>
      )}
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function SymbolOpportunityBoard({ 
  symbols, 
  onSymbolClick,
  className,
}: SymbolOpportunityBoardProps) {
  const [sortKey, setSortKey] = useState<SortKey>('netEdge');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [viewMode, setViewMode] = useState<ViewMode>('table');
  const [filterView, setFilterView] = useState<FilterView>('all');
  
  // Handle sort
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };
  
  // Filter and sort symbols
  const filteredSymbols = useMemo(() => {
    let result = [...symbols];
    
    // Apply filter
    if (filterView === 'tradable') {
      result = result.filter(s => s.tradable);
    } else if (filterView === 'blocked') {
      result = result.filter(s => !s.tradable);
    }
    
    // Apply sort
    result.sort((a, b) => {
      let aVal: number, bVal: number;
      
      switch (sortKey) {
        case 'symbol':
          return sortDir === 'asc' 
            ? a.symbol.localeCompare(b.symbol)
            : b.symbol.localeCompare(a.symbol);
        case 'netEdge':
          aVal = a.netEdge;
          bVal = b.netEdge;
          break;
        case 'spread':
          aVal = a.spread;
          bVal = b.spread;
          break;
        case 'vol':
          aVal = a.volPercentile;
          bVal = b.volPercentile;
          break;
        case 'liquidity':
          aVal = a.liquidityScore;
          bVal = b.liquidityScore;
          break;
        case 'funding':
          aVal = Math.abs(a.funding);
          bVal = Math.abs(b.funding);
          break;
        default:
          return 0;
      }
      
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
    });
    
    // Pin pinned symbols to top
    const pinned = result.filter(s => s.pinned);
    const unpinned = result.filter(s => !s.pinned);
    return [...pinned, ...unpinned];
  }, [symbols, sortKey, sortDir, filterView]);
  
  // Stats
  const tradableCount = symbols.filter(s => s.tradable).length;
  const blockedCount = symbols.filter(s => !s.tradable).length;
  
  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Symbol Opportunity Board</CardTitle>
            <Badge variant="outline" className="text-[10px]">
              {filteredSymbols.length} symbols
            </Badge>
          </div>
          
          <div className="flex items-center gap-2">
            {/* Filter Buttons */}
            <div className="flex rounded-lg border bg-muted/50 p-0.5">
              <Button
                variant={filterView === 'all' ? 'default' : 'ghost'}
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => setFilterView('all')}
              >
                All ({symbols.length})
              </Button>
              <Button
                variant={filterView === 'tradable' ? 'default' : 'ghost'}
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => setFilterView('tradable')}
              >
                Tradable ({tradableCount})
              </Button>
              <Button
                variant={filterView === 'blocked' ? 'default' : 'ghost'}
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => setFilterView('blocked')}
              >
                Blocked ({blockedCount})
              </Button>
            </div>
            
            {/* View Toggle */}
            <div className="flex rounded-lg border bg-muted/50 p-0.5">
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => setViewMode('table')}
              >
                <List className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant={viewMode === 'heatmap' ? 'default' : 'ghost'}
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => setViewMode('heatmap')}
              >
                <Grid3X3 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="p-0">
        {filteredSymbols.length === 0 ? (
          <div className="text-center py-8 text-sm text-muted-foreground">
            No symbols match the current filter
          </div>
        ) : viewMode === 'table' ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-y bg-muted/30">
                <tr>
                  <SortHeader 
                    label="Symbol" 
                    sortKey="symbol" 
                    currentSort={sortKey} 
                    currentDir={sortDir} 
                    onSort={handleSort}
                    align="left"
                  />
                  <th className="py-2 px-2 text-left text-[11px] font-medium text-muted-foreground">
                    Status
                  </th>
                  <SortHeader 
                    label="Edge" 
                    sortKey="netEdge" 
                    currentSort={sortKey} 
                    currentDir={sortDir} 
                    onSort={handleSort}
                  />
                  <th className="py-2 px-2 text-right text-[11px] font-medium text-muted-foreground">
                    Headwind
                  </th>
                  <th className="py-2 px-2 text-right text-[11px] font-medium text-muted-foreground">
                    Net
                  </th>
                  <SortHeader 
                    label="Vol%" 
                    sortKey="vol" 
                    currentSort={sortKey} 
                    currentDir={sortDir} 
                    onSort={handleSort}
                  />
                  <SortHeader 
                    label="Spread" 
                    sortKey="spread" 
                    currentSort={sortKey} 
                    currentDir={sortDir} 
                    onSort={handleSort}
                  />
                  <SortHeader 
                    label="Liq" 
                    sortKey="liquidity" 
                    currentSort={sortKey} 
                    currentDir={sortDir} 
                    onSort={handleSort}
                  />
                  <SortHeader 
                    label="Fund" 
                    sortKey="funding" 
                    currentSort={sortKey} 
                    currentDir={sortDir} 
                    onSort={handleSort}
                  />
                  <th className="py-2 px-2 text-center text-[11px] font-medium text-muted-foreground">
                    Flags
                  </th>
                  <th className="py-2 px-2 text-center text-[11px] font-medium text-muted-foreground">
                    Alloc
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredSymbols.map((sym) => (
                  <tr
                    key={sym.symbol}
                    className={cn(
                      "border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors",
                      !sym.tradable && "opacity-60"
                    )}
                    onClick={() => onSymbolClick(sym)}
                  >
                    {/* Symbol */}
                    <td className="py-2 px-2">
                      <div className="flex items-center gap-1.5">
                        {sym.pinned && <Star className="h-3 w-3 text-amber-500 fill-amber-500" />}
                        <span className="font-medium">{sym.symbol}</span>
                      </div>
                    </td>
                    
                    {/* Status */}
                    <td className="py-2 px-2">
                      <TradableStatus symbol={sym} />
                    </td>
                    
                    {/* Expected Edge */}
                    <td className="py-2 px-2 text-right font-mono">
                      <span className={sym.expectedEdge > 0 ? "text-emerald-500" : "text-muted-foreground"}>
                        {sym.expectedEdge > 0 ? "+" : ""}{sym.expectedEdge.toFixed(1)}
                      </span>
                    </td>
                    
                    {/* Headwind */}
                    <td className="py-2 px-2 text-right font-mono text-red-500">
                      -{sym.headwind.toFixed(1)}
                    </td>
                    
                    {/* Net Edge */}
                    <td className="py-2 px-2 text-right font-mono">
                      <span className={cn(
                        "font-medium",
                        sym.netEdge > 0 ? "text-emerald-500" : "text-red-500"
                      )}>
                        {sym.netEdge > 0 ? "+" : ""}{sym.netEdge.toFixed(1)}
                      </span>
                    </td>
                    
                    {/* Vol Percentile */}
                    <td className={cn(
                      "py-2 px-2 text-right font-mono",
                      sym.volPercentile > 80 ? "text-red-500" : 
                      sym.volPercentile > 60 ? "text-amber-500" : ""
                    )}>
                      {sym.volPercentile.toFixed(0)}
                    </td>
                    
                    {/* Spread */}
                    <td className="py-2 px-2 text-right">
                      <div className="flex flex-col items-end">
                        <span className={cn(
                          "font-mono",
                          sym.spread > 2 ? "text-red-500" : 
                          sym.spread > 1.5 ? "text-amber-500" : ""
                        )}>
                          {sym.spread.toFixed(1)}
                        </span>
                        <span className="text-[9px] text-muted-foreground">
                          {sym.spreadP50.toFixed(1)}/{sym.spreadP95.toFixed(1)}
                        </span>
                      </div>
                    </td>
                    
                    {/* Liquidity */}
                    <td className={cn(
                      "py-2 px-2 text-right font-mono",
                      sym.liquidityScore < 50 ? "text-red-500" : 
                      sym.liquidityScore < 70 ? "text-amber-500" : ""
                    )}>
                      {sym.liquidityScore.toFixed(0)}
                    </td>
                    
                    {/* Funding */}
                    <td className="py-2 px-2 text-right">
                      <span className={cn(
                        "font-mono",
                        sym.fundingSpike && "text-amber-500"
                      )}>
                        {(sym.funding * 100).toFixed(2)}%
                      </span>
                    </td>
                    
                    {/* Anomaly Flags */}
                    <td className="py-2 px-2 text-center">
                      <AnomalyFlags flags={sym.anomalyFlags} />
                    </td>
                    
                    {/* Allocation State */}
                    <td className="py-2 px-2 text-center">
                      <AllocationBadge state={sym.allocationState} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          // Heatmap view - simplified grid
          <div className="p-4 grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 gap-2">
            {filteredSymbols.map((sym) => (
              <Tooltip key={sym.symbol}>
                <TooltipTrigger asChild>
                  <div
                    className={cn(
                      "p-2 rounded-lg border cursor-pointer transition-all hover:scale-105",
                      sym.tradable 
                        ? "bg-emerald-500/10 border-emerald-500/30 hover:bg-emerald-500/20"
                        : "bg-red-500/10 border-red-500/30 hover:bg-red-500/20 opacity-60"
                    )}
                    onClick={() => onSymbolClick(sym)}
                  >
                    <div className="flex items-center gap-1">
                      {sym.pinned && <Star className="h-2.5 w-2.5 text-amber-500 fill-amber-500" />}
                      <span className="text-[10px] font-medium truncate">{sym.symbol}</span>
                    </div>
                    <div className={cn(
                      "text-xs font-mono font-medium mt-0.5",
                      sym.netEdge > 0 ? "text-emerald-500" : "text-red-500"
                    )}>
                      {sym.netEdge > 0 ? "+" : ""}{sym.netEdge.toFixed(1)}bp
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="text-xs">
                  <div className="space-y-1">
                    <div className="font-medium">{sym.symbol}</div>
                    <div>Edge: {sym.expectedEdge.toFixed(1)}bp</div>
                    <div>Headwind: {sym.headwind.toFixed(1)}bp</div>
                    <div>Spread: {sym.spread.toFixed(1)}bp</div>
                    <div>Vol: {sym.volPercentile.toFixed(0)}%</div>
                    {!sym.tradable && <div className="text-red-400">{sym.blockedReason}</div>}
                  </div>
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

