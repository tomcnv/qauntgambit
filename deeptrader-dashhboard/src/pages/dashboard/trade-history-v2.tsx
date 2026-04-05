/**
 * Quant-Grade Trade History Page
 * 
 * Features:
 * - 3-pane layout with filters, summary, table, and inspector
 * - Cohort builder with time range, symbols, strategies, outcome/side
 * - Advanced filters for execution, risk, and market regime
 * - Virtualized table with quant columns and column presets
 * - Trade inspector drawer with 5 tabs
 * - Saved views with localStorage persistence
 * - Blocked decisions toggle
 * - Export CSV/JSON
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { Card } from '../../components/ui/card';
import { Switch } from '../../components/ui/switch';
import { Label } from '../../components/ui/label';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../../components/ui/dropdown-menu';
import { cn } from '../../lib/utils';
import {
  Download,
  FileText,
  ChevronDown,
  RefreshCw,
  EyeOff,
  Loader2,
} from 'lucide-react';
import { RunBar } from '../../components/run-bar';

// Trade History Components
import { CohortFilterBar } from '../../components/trade-history/CohortFilterBar';
import { AdvancedFiltersSheet } from '../../components/trade-history/AdvancedFiltersSheet';
import { SavedViewsDropdown } from '../../components/trade-history/SavedViewsDropdown';
import { CohortSummaryStrip } from '../../components/trade-history/CohortSummaryStrip';
import { TradesTable } from '../../components/trade-history/TradesTable';
import { TradeInspectorDrawer } from '../../components/trade-history/TradeInspectorDrawer';

// Types and Hooks
import {
  CohortFilters,
  AdvancedFilters,
  SavedView,
  QuantTrade,
  DEFAULT_COHORT_FILTERS,
  DEFAULT_ADVANCED_FILTERS,
} from '../../components/trade-history/types';
import {
  useFilteredTrades,
  useCohortStats,
  useSavedViews,
  useBlockedDecisions,
} from '../../components/trade-history/hooks';
import { useScopeStore, Environment } from '../../store/scope-store';

// Blocked Decisions Panel
function BlockedDecisionsPanel({ 
  startDate,
  endDate,
  symbols,
}: { 
  startDate?: string;
  endDate?: string;
  symbols?: string[];
}) {
  const { traces, stats, isLoading, error } = useBlockedDecisions({
    startDate,
    endDate,
    symbol: symbols?.[0],
    limit: 100,
  });
  
  if (isLoading) {
    return (
      <Card className="p-8 text-center">
        <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">Loading blocked decisions...</p>
      </Card>
    );
  }
  
  if (error || traces.length === 0) {
    return (
      <Card className="p-8 text-center">
        <EyeOff className="h-8 w-8 mx-auto text-muted-foreground/30 mb-2" />
        <p className="text-sm text-muted-foreground">No blocked decisions in this period</p>
        <p className="text-xs text-muted-foreground/60 mt-1">
          All signals passed through the decision pipeline
        </p>
      </Card>
    );
  }
  
  // Group by reason
  const byReason = traces.reduce((acc: Record<string, number>, trace: any) => {
    const reason = trace.primaryReason || trace.reason || 'Unknown';
    acc[reason] = (acc[reason] || 0) + 1;
    return acc;
  }, {});
  
  const sortedReasons = Object.entries(byReason).sort((a, b) => (b[1] as number) - (a[1] as number));
  
  return (
    <Card className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Blocked Decisions</h3>
        <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/30">
          {traces.length} blocked
        </Badge>
      </div>
      
      {/* Rejection Funnel */}
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground uppercase tracking-wider">Top Block Reasons</p>
        {sortedReasons.slice(0, 5).map(([reason, count]) => (
          <div key={reason} className="flex items-center justify-between">
            <span className="text-sm truncate max-w-[200px]">{reason}</span>
            <div className="flex items-center gap-2">
              <div className="w-20 h-2 bg-muted rounded-full overflow-hidden">
                <div 
                  className="h-full bg-red-500/50 rounded-full"
                  style={{ width: `${((count as number) / traces.length) * 100}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground w-8 text-right">{count as number}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function TradeHistoryV2Page() {
  const [searchParams, setSearchParams] = useSearchParams();
  const setExchangeScope = useScopeStore((s) => s.setExchangeScope);
  const setBotScope = useScopeStore((s) => s.setBotScope);
  const setEnvironment = useScopeStore((s) => s.setEnvironment);

  // Filter state
  const [filters, setFilters] = useState<CohortFilters>(DEFAULT_COHORT_FILTERS);
  const [advancedFilters, setAdvancedFilters] = useState<AdvancedFilters>(DEFAULT_ADVANCED_FILTERS);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  
  // View state
  const [showBlockedDecisions, setShowBlockedDecisions] = useState(false);
  
  // Selection state
  const [selectedTrade, setSelectedTrade] = useState<QuantTrade | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  
  // Pagination
  const [offset, setOffset] = useState(0);
  const limit = 100;
  
  // Saved views
  const {
    views,
    saveView,
    deleteView,
    setDefaultView,
  } = useSavedViews();
  
  // Check if advanced filters are active
  const hasAdvancedFilters = useMemo(() => {
    return Object.entries(advancedFilters).some(([key, value]) => {
      if (value === undefined) return false;
      if (typeof value === 'string' && value === 'all') return false;
      return true;
    });
  }, [advancedFilters]);
  
  // Fetch trades
  const { 
    trades, 
    isLoading, 
    isFetching,
    pagination,
    refetch,
  } = useFilteredTrades({
    filters,
    advancedFilters: hasAdvancedFilters ? advancedFilters : undefined,
    limit,
    offset,
  });
  
  // Calculate stats
  const stats = useCohortStats(trades);
  
  // Get unique symbols for filter dropdown
  const availableSymbols = useMemo(() => {
    const symbols = new Set(trades.map(t => t.symbol));
    return Array.from(symbols).sort();
  }, [trades]);
  
  // Handlers
  const handleSelectTrade = useCallback((trade: QuantTrade) => {
    setSelectedTrade(trade);
    setInspectorOpen(true);
  }, []);

  useEffect(() => {
    const exchangeAccountId = searchParams.get('exchangeAccountId');
    const botId = searchParams.get('botId');
    const environment = searchParams.get('environment');

    if (exchangeAccountId && botId) {
      setBotScope(exchangeAccountId, null, botId);
    } else if (exchangeAccountId) {
      setExchangeScope(exchangeAccountId);
    }

    const allowedEnvironments: Environment[] = ['all', 'live', 'paper', 'dev'];
    if (environment && allowedEnvironments.includes(environment as Environment)) {
      setEnvironment(environment as Environment);
    }
  }, [searchParams, setBotScope, setEnvironment, setExchangeScope]);

  useEffect(() => {
    const openTradeId = searchParams.get('openTradeId');
    if (!openTradeId || trades.length === 0) return;
    const matched = trades.find((trade) => trade.id === openTradeId);
    if (!matched) return;
    setSelectedTrade(matched);
    setInspectorOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete('openTradeId');
    next.delete('exchangeAccountId');
    next.delete('botId');
    next.delete('environment');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, trades]);
  
  const handleApplyView = useCallback((view: SavedView) => {
    setFilters(view.filters);
    if (view.advancedFilters) {
      setAdvancedFilters(view.advancedFilters);
    }
    setOffset(0);
  }, []);
  
  const handleExportCSV = useCallback(() => {
    const headers = [
      'Timestamp', 'Symbol', 'Side', 'Quantity', 'Entry', 'Exit', 
      'Gross PnL', 'Fees', 'Net PnL', 'Slippage (bps)', 'Latency (ms)'
    ];
    
    const rows = trades.map(t => [
      new Date(t.timestamp).toISOString(),
      t.symbol,
      t.side,
      t.quantity,
      t.entryPrice,
      t.exitPrice,
      t.realizedPnl,
      t.fees,
      t.netPnl,
      t.slippageBps || '',
      t.latencyMs || '',
    ]);
    
    const csv = [headers, ...rows].map(row => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trades_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [trades]);
  
  const handleExportJSON = useCallback(() => {
    const data = {
      exportedAt: new Date().toISOString(),
      filters,
      advancedFilters: hasAdvancedFilters ? advancedFilters : undefined,
      stats,
      trades,
    };
    
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trades_${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [trades, filters, advancedFilters, hasAdvancedFilters, stats]);
  
  const handleReplayTrade = useCallback((trade: QuantTrade) => {
    // Navigate to Replay Studio with trade context
    // Pass symbol, timestamp, and trade ID so the replay page can center on this trade
    const params = new URLSearchParams();
    params.set("symbol", trade.symbol);
    // Convert timestamp to ISO string if it's a number
    const timeStr = typeof trade.timestamp === "number" 
      ? new Date(trade.timestamp).toISOString() 
      : trade.timestamp;
    params.set("time", timeStr);
    if (trade.id) params.set("tradeId", trade.id);
    window.open(`/analysis/replay?${params.toString()}`, '_blank');
  }, []);
  
  const handleExportTrade = useCallback((trade: QuantTrade) => {
    const blob = new Blob([JSON.stringify(trade, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trade_${trade.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);
  
  return (
    <>
      {/* Sticky Run Bar */}
      <RunBar />
      
      <div className="flex-1 space-y-6 p-6 max-w-[1600px] mx-auto w-full">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Trade History</h1>
            <p className="text-sm text-muted-foreground">
              Analyze trades with full decision details and execution quality metrics
            </p>
          </div>
        
        <div className="flex items-center gap-3">
          {/* Blocked Decisions Toggle */}
          <div className="flex items-center gap-2 mr-2">
            <Switch
              id="blocked-toggle"
              checked={showBlockedDecisions}
              onCheckedChange={setShowBlockedDecisions}
            />
            <Label htmlFor="blocked-toggle" className="text-xs cursor-pointer">
              Show Blocked
            </Label>
          </div>
          
          {/* Saved Views */}
          <SavedViewsDropdown
            views={views}
            currentFilters={filters}
            currentAdvancedFilters={hasAdvancedFilters ? advancedFilters : undefined}
            currentColumnPreset="all"
            onApplyView={handleApplyView}
            onSaveView={saveView}
            onDeleteView={deleteView}
            onSetDefault={setDefaultView}
          />
          
          {/* Export Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-2">
                <Download className="h-3.5 w-3.5" />
                Export
                <ChevronDown className="h-3 w-3 opacity-50" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleExportCSV}>
                <FileText className="h-3.5 w-3.5 mr-2" />
                Export as CSV
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleExportJSON}>
                <Download className="h-3.5 w-3.5 mr-2" />
                Export as JSON
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          
          {/* Refresh */}
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          </Button>
        </div>
      </div>
      
      {/* Filters Row */}
      <CohortFilterBar
        filters={filters}
        onChange={(newFilters) => {
          setFilters(newFilters);
          setOffset(0);
        }}
        onOpenAdvanced={() => setAdvancedOpen(true)}
        availableSymbols={availableSymbols}
        hasAdvancedFilters={hasAdvancedFilters}
      />
      
      {/* Summary Strip */}
      <CohortSummaryStrip stats={stats} isLoading={isLoading} />
      
      {/* Main Content */}
      <div className={cn(
        "grid gap-6",
        showBlockedDecisions ? "grid-cols-[1fr_300px]" : "grid-cols-1"
      )}>
        {/* Trades Table - header, columns, pagination all inside */}
        <TradesTable
          trades={trades}
          onSelectTrade={handleSelectTrade}
          onReplayTrade={handleReplayTrade}
          onExportTrade={handleExportTrade}
          selectedTradeId={selectedTrade?.id}
          isLoading={isLoading}
          isFetching={isFetching}
          total={pagination.total}
          offset={offset}
          limit={limit}
          onOffsetChange={setOffset}
        />
        
        {/* Blocked Decisions Panel */}
        {showBlockedDecisions && (
          <BlockedDecisionsPanel
            startDate={filters.startDate}
            endDate={filters.endDate}
            symbols={filters.symbols}
          />
        )}
      </div>
      
      {/* Advanced Filters Sheet */}
      <AdvancedFiltersSheet
        open={advancedOpen}
        onOpenChange={setAdvancedOpen}
        filters={advancedFilters}
        onChange={(newFilters) => {
          setAdvancedFilters(newFilters);
          setOffset(0);
        }}
        onSaveAsView={() => {
          // Prompt for view name handled in SavedViewsDropdown
          setAdvancedOpen(false);
        }}
      />
      
        {/* Trade Inspector Drawer */}
        <TradeInspectorDrawer
          open={inspectorOpen}
          onOpenChange={setInspectorOpen}
          trade={selectedTrade}
          onReplay={handleReplayTrade}
          onExport={handleExportTrade}
        />
      </div>
    </>
  );
}

