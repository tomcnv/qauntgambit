/**
 * Market Context Page - Quant-Grade Market Fit / Opportunity Dashboard
 * 
 * Answers: "Should I be running right now, on what symbols, with what profile, and what's blocking trades?"
 * 
 * Sections:
 * 1. TruthBar - Scope, bot state, gates, safety (replaces RunBar)
 * 2. TradingStatusPanel - Why not trading + rejection breakdown
 * 3. RegimeScorecards - Enhanced cards with sparklines and p50/p95
 * 4. SymbolOpportunityBoard - Ranked table with quant columns
 * 5. GatesListPanel - Threshold vs actual values
 * 6. RegimeTimeline - Regime shifts with click-to-filter
 * 7. BotFitPanel - Market conditions fit score breakdown
 * 8. ProfileRoutingPanel - Real-time profile routing status
 */

import { useCallback, useMemo, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Separator } from "../../components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../components/ui/tooltip";

// Market Context Components
import { TruthBar } from "../../components/market-context/TruthBar";
import { TradingStatusPanel } from "../../components/market-context/TradingStatusPanel";
import { RegimeScorecards } from "../../components/market-context/TradabilityScorecard";
import { SymbolOpportunityBoard } from "../../components/market-context/SymbolOpportunityBoard";
import { GatesListPanel } from "../../components/market-context/GatesListPanel";
import { RegimeTimeline } from "../../components/market-context/RegimeTimeline";
import { BotFitPanel } from "../../components/market-context/BotFitPanel";
import { ProfileRoutingPanel } from "../../components/market-context/ProfileRoutingPanel";
import { ProfileScorePanel } from "../../components/market-context/ProfileScorePanel";
import { ProfileRejectionPanel } from "../../components/market-context/ProfileRejectionPanel";
import { SymbolDrawer } from "../../components/market-context/SymbolDrawer";
import { OrderbookModelPanel } from "../../components/orderbook-model/OrderbookModelPanel";
import type { SymbolRow, MarketContextFilters, RegimeEvent } from "../../components/market-context/types";

// Data hooks
import { useMarketFitData, useRegimeSparklineData } from "../../lib/api/market-fit-hooks";
import { useProfileMetrics, useProfileRouter } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";

// ============================================================================
// FILTERS BAR - Workflow-oriented toggles with proper Button components
// ============================================================================

function FiltersBar({
  filters,
  onFilterChange,
  isLive,
}: {
  filters: MarketContextFilters;
  onFilterChange: (key: keyof MarketContextFilters, value: any) => void;
  isLive: boolean;
}) {
  return (
    <div className="sticky top-0 z-40 bg-card/95 backdrop-blur-sm border-b">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        {/* Universe */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Universe:</span>
          <div className="flex rounded-lg border bg-muted/50 p-0.5">
            {(["futures", "perp", "spot"] as const).map((u) => {
              const isDisabled = u !== "perp";
              const button = (
                <Button
                  key={u}
                  variant={filters.universe === u ? "default" : "ghost"}
                  size="sm"
                  className="h-6 px-2 text-[11px]"
                  onClick={() => !isDisabled && onFilterChange("universe", u)}
                  disabled={isDisabled}
                >
                  {u.charAt(0).toUpperCase() + u.slice(1)}
                </Button>
              );
              
              if (isDisabled) {
                return (
                  <Tooltip key={u}>
                    <TooltipTrigger asChild>{button}</TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-[200px]">
                      <p className="text-xs">
                        {u === "futures" 
                          ? "Dated futures not currently supported. Bot trades perpetual swaps only."
                          : "Spot trading not supported. Bot requires leverage & TP/SL order types."}
                      </p>
                    </TooltipContent>
                  </Tooltip>
                );
              }
              return button;
            })}
          </div>
        </div>

        <Separator orientation="vertical" className="h-6" />

        {/* View */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">View:</span>
          <div className="flex rounded-lg border bg-muted/50 p-0.5">
            {(["tradable", "blocked", "watchlist", "all"] as const).map((v) => (
              <Button
                key={v}
                variant={filters.view === v ? "default" : "ghost"}
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => onFilterChange("view", v)}
              >
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </Button>
            ))}
          </div>
        </div>

        <Separator orientation="vertical" className="h-6" />

        {/* Window */}
        <div className="flex items-center gap-1.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-xs text-muted-foreground cursor-help">Window:</span>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <p className="text-xs">Time window for metrics. Coming soon - currently shows live data.</p>
            </TooltipContent>
          </Tooltip>
          <div className="flex rounded-lg border bg-muted/50 p-0.5">
            {(["5m", "1h", "6h", "24h"] as const).map((w) => (
              <Button
                key={w}
                variant={filters.window === w ? "default" : "ghost"}
                size="sm"
                className="h-6 px-2 text-[11px] opacity-60"
                onClick={() => onFilterChange("window", w)}
                disabled
              >
                {w}
              </Button>
            ))}
          </div>
        </div>

        <Separator orientation="vertical" className="h-6" />

        {/* Anomalies Only */}
        <Button
          variant={filters.anomaliesOnly ? "default" : "outline"}
          size="sm"
          className="h-7 text-xs"
          onClick={() => onFilterChange("anomaliesOnly", !filters.anomaliesOnly)}
        >
          <Sparkles className="h-3.5 w-3.5 mr-1.5" />
          Anomalies Only
        </Button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Live indicator */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <RefreshCw className={cn("h-3 w-3", isLive && "animate-spin")} />
          <span>Live</span>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function MarketContextPage() {
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolRow | null>(null);
  const [filters, setFilters] = useState<MarketContextFilters>({
    universe: "perp",
    view: "all",
    window: "1h",
    anomaliesOnly: false,
    exchange: "Binance",
  });

  // Get current bot scope
  const { botId } = useScopeStore();
  
  // Fetch combined market fit data
  const marketFitData = useMarketFitData();
  const sparklineData = useRegimeSparklineData(filters.window);
  const { data: profileMetrics, isLoading: profileMetricsLoading } = useProfileMetrics(botId);
  const { data: profileRouter, isLoading: profileRouterLoading } = useProfileRouter(botId);

  const handleFilterChange = useCallback((key: keyof MarketContextFilters, value: any) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Filter symbols based on current filters
  const filteredSymbols = useMemo(() => {
    let result = [...marketFitData.symbols];
    
    // Apply universe filter (instrument type)
    // Always filter by instrument type to ensure proper universe selection
    result = result.filter(s => s.instrumentType === filters.universe);
    
    // Apply view filter
    if (filters.view === "tradable") {
      result = result.filter(s => s.tradable);
    } else if (filters.view === "blocked") {
      result = result.filter(s => !s.tradable);
    } else if (filters.view === "watchlist") {
      result = result.filter(s => s.pinned);
    }
    
    // Apply anomalies filter
    if (filters.anomaliesOnly) {
      result = result.filter(s => !s.tradable || s.anomalyFlags.length > 0 || s.regime !== "Normal");
    }
    
    return result;
  }, [marketFitData.symbols, filters.universe, filters.view, filters.anomaliesOnly]);

  // Calculate symbol stats for scorecards
  const symbolStats = useMemo(() => {
    const symbols = marketFitData.symbols;
    if (symbols.length === 0) {
      return {
        spreadElevatedCount: 0,
        volElevatedCount: 0,
        liqLowCount: 0,
        avgSpread: 1.0,
        avgVol: 50,
        avgDepth: 80,
      };
    }
    
    return {
      spreadElevatedCount: symbols.filter(s => s.spreadChange > 50).length,
      volElevatedCount: symbols.filter(s => s.volChange > 50).length,
      liqLowCount: symbols.filter(s => s.depth < 60).length,
      avgSpread: symbols.reduce((a, s) => a + s.spread, 0) / symbols.length,
      avgVol: symbols.reduce((a, s) => a + s.volPercentile, 0) / symbols.length,
      avgDepth: symbols.reduce((a, s) => a + s.depth, 0) / symbols.length,
    };
  }, [marketFitData.symbols]);

  // Handle regime event click - filter symbols
  const handleRegimeEventClick = useCallback((event: RegimeEvent) => {
    if (event.symbols.length > 0) {
      // Could implement symbol highlighting/filtering here
      console.log("Regime event clicked:", event);
    }
  }, []);

  // Handle symbol filter from timeline
  const handleSymbolFilter = useCallback((symbols: string[]) => {
    // Could implement symbol filtering here
    console.log("Filter to symbols:", symbols);
  }, []);

  // Calculate headwind from symbol data
  const avgHeadwind = useMemo(() => {
    if (marketFitData.symbols.length === 0) return 1.8;
    return marketFitData.symbols.reduce((a, s) => a + s.headwind, 0) / marketFitData.symbols.length;
  }, [marketFitData.symbols]);

  return (
    <TooltipProvider>
      {/* Truth Bar - includes trading mode, bot, profile, gates, safety */}
      <TruthBar
        botName={marketFitData.botName}
        botRunning={marketFitData.botRunning}
        botRunningSince={marketFitData.botRunningSince}
        profileName={marketFitData.profileName}
        profileVersion={marketFitData.profileVersion}
        gates={marketFitData.gates}
        safety={marketFitData.safety}
        venueHealth={marketFitData.venueHealth}
      />
      
      <div className="flex flex-col min-h-full">
        {/* Filters Bar */}
        <FiltersBar 
          filters={filters} 
          onFilterChange={handleFilterChange}
          isLive={!marketFitData.isLoading}
        />

        {/* Loading State */}
        {marketFitData.isLoading && (
          <div className="flex items-center justify-center p-8">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="ml-2 text-muted-foreground">Loading market context...</span>
          </div>
        )}

        {/* Error State */}
        {marketFitData.error && (
          <div className="p-6">
            <Card className="border-amber-500/50 bg-amber-500/10">
              <CardContent className="flex items-center gap-3 p-4">
                <AlertTriangle className="h-5 w-5 text-amber-500" />
                <span className="text-amber-600 dark:text-amber-400">
                  Failed to load market context. Please retry shortly.
                </span>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Main Content with Tabs */}
        <div className="flex-1 p-6 max-w-[1800px] mx-auto w-full">
          <Tabs defaultValue="overview" className="space-y-4">
            <TabsList className="grid w-fit grid-cols-4 gap-1">
              <TabsTrigger value="overview" className="px-4">Overview</TabsTrigger>
              <TabsTrigger value="microstructure" className="px-4">Microstructure</TabsTrigger>
              <TabsTrigger value="vol-regime" className="px-4">Vol/Regime</TabsTrigger>
              <TabsTrigger value="liquidity" className="px-4">Liquidity</TabsTrigger>
            </TabsList>

            {/* Overview Tab - Current content */}
            <TabsContent value="overview" className="space-y-4">
              {/* Trading Status Panel */}
              <TradingStatusPanel status={marketFitData.tradingStatus} />

              {/* Regime Scorecards */}
              <RegimeScorecards
                spreadRegime={marketFitData.spreadRegime}
                volRegime={marketFitData.volRegime}
                liqRegime={marketFitData.liqRegime}
                venueLatency={marketFitData.venueHealth.latencyP50}
                headwindBps={avgHeadwind}
                sparklineData={sparklineData}
                symbolStats={symbolStats}
              />

              {/* Symbol Opportunity Board */}
              <SymbolOpportunityBoard
                symbols={filteredSymbols}
                onSymbolClick={setSelectedSymbol}
              />

              {/* Bottom Grid: Gates, Timeline, Market Fit */}
              <div className="grid gap-4 lg:grid-cols-3">
                <GatesListPanel gates={marketFitData.gates} />
                <RegimeTimeline 
                  events={marketFitData.regimeEvents}
                  onEventClick={handleRegimeEventClick}
                  onSymbolFilter={handleSymbolFilter}
                />
                <BotFitPanel
                  fitScore={marketFitData.botFit}
                  botRunning={marketFitData.botRunning}
                  profileName={marketFitData.profileName}
                />
              </div>
              
              {/* Profile Routing Row */}
              <div className="grid gap-4 lg:grid-cols-3">
                <ProfileRoutingPanel
                  profileMetrics={profileMetrics}
                  isLoading={profileMetricsLoading}
                />
                <ProfileScorePanel
                  routerData={profileRouter}
                  isLoading={profileRouterLoading}
                />
                <ProfileRejectionPanel />
              </div>
            </TabsContent>

            {/* Microstructure Tab - Prediction Model Dashboard */}
            <TabsContent value="microstructure">
              <OrderbookModelPanel botId={botId} />
            </TabsContent>

            {/* Volatility/Regime tab */}
            <TabsContent value="vol-regime">
              <div className="space-y-4">
                <RegimeScorecards
                  spreadRegime={marketFitData.spreadRegime}
                  volRegime={marketFitData.volRegime}
                  liqRegime={marketFitData.liqRegime}
                  venueLatency={marketFitData.venueHealth.latencyP50}
                  headwindBps={avgHeadwind}
                  sparklineData={sparklineData}
                  symbolStats={symbolStats}
                />
                <RegimeTimeline
                  events={marketFitData.regimeEvents}
                  onEventClick={handleRegimeEventClick}
                  onSymbolFilter={handleSymbolFilter}
                />
              </div>
            </TabsContent>
            
            <TabsContent value="liquidity">
              <div className="space-y-4">
                <SymbolOpportunityBoard
                  symbols={filteredSymbols}
                  onSymbolClick={setSelectedSymbol}
                />
                <div className="grid gap-4 lg:grid-cols-2">
                  <GatesListPanel gates={marketFitData.gates} />
                  <TradingStatusPanel status={marketFitData.tradingStatus} />
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>

        {/* Symbol Drawer */}
        <SymbolDrawer 
          symbol={selectedSymbol} 
          onClose={() => setSelectedSymbol(null)} 
        />
      </div>
    </TooltipProvider>
  );
}
