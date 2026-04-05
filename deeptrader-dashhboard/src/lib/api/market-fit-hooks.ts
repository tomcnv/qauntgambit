/**
 * Market Fit Hooks - Combines multiple data sources for the Market Context page
 * 
 * Data Sources:
 * - useMarketContext: Real market data (spread, vol, depth, funding) from /api/dashboard/market-context
 * - useSignalLabData: Rejections and signal data from /api/monitoring/fast-scalper/rejections + /api/dashboard/signals
 * - useHealthSnapshot: System health from /api/python/health
 * - useActiveBot: Active bot info from /api/bots/active
 * - useOverviewData: Combined dashboard data including bot status
 * - useFastScalperStatus: Real-time trading metrics
 */

import { useMemo } from "react";
import { 
  useMarketContext, 
  useSignalLabData, 
  useHealthSnapshot, 
  useActiveBot, 
  useOverviewData,
  useDashboardRisk,
} from "./hooks";
import { useScopeStore } from "../../store/scope-store";
import type { MarketContext, FastScalperStatusResponse, HealthSnapshot, SignalLabSnapshot } from "./types";
import type {
  SymbolRow,
  GateStatus,
  RegimeEvent,
  TradingStatus,
  BotFitScore,
  VenueHealth,
  SafetyMetrics,
  MarketFitData,
} from "../../components/market-context/types";

// ============================================================================
// HELPER: Transform API context to SymbolRow
// Uses REAL data from the market context API
// ============================================================================

function transformContextToSymbol(symbol: string, context: MarketContext): SymbolRow {
  // All these values come from the real API - use type assertion for optional fields
  const ctx = context as MarketContext & { 
    funding_rate?: number; 
    churn_score?: number; 
    is_stale?: boolean;
    instrument_type?: string;
    spreadBps?: number;
    depthUsd?: number;
    fundingRate?: number;
    vol?: number;
  };
  const spreadBps = ctx.spread_bps ?? ctx.spreadBps ?? 0;
  const vol = ctx.volatility_percentile ?? ctx.vol ?? 0;
  const depthUsd = ctx.depth_usd ?? ctx.depthUsd ?? 0;
  const spreadMissing = Boolean((ctx as any).spread_missing);
  const volMissing = Boolean((ctx as any).vol_missing);
  const depthMissing = Boolean((ctx as any).depth_missing);
  const bidDepth = ctx.bid_depth_usd ?? (depthUsd > 0 ? depthUsd / 2 : 0);
  const askDepth = ctx.ask_depth_usd ?? (depthUsd > 0 ? depthUsd / 2 : 0);
  const totalDepth = bidDepth + askDepth;
  const fundingRate = ctx.funding_rate ?? ctx.fundingRate ?? 0;
  const churnScore = ctx.churn_score ?? 0;
  const isStale = ctx.is_stale ?? false;
  const volRegime = ctx.volatility_regime ?? "normal";
  
  // Calculate derived metrics from real data
  const depthScore = depthMissing ? 0 : (totalDepth > 0 ? Math.min(100, (totalDepth / 500000) * 100) : 0);
  
  // Use historical baselines if available, otherwise use current as baseline
  const spreadBaseline = 1.0; // Could be fetched from historical API
  const spreadChange = spreadBaseline > 0 ? ((spreadBps - spreadBaseline) / spreadBaseline) * 100 : 0;
  
  const volBaseline = 50;
  const volChange = volBaseline > 0 ? ((vol - volBaseline) / volBaseline) * 100 : 0;
  
  // Determine regime from real volatility regime
  let regime = "Normal";
  if (volRegime === "high" && depthScore < 70) {
    regime = "Wide+HighVol";
  } else if (depthScore < 60) {
    regime = "Thin";
  } else if (volRegime === "high") {
    regime = "VolSpike";
  } else if (spreadBps > 2) {
    regime = "Widened";
  }
  
  // Determine tradability based on real thresholds
  const hasRequiredContext = !spreadMissing && !volMissing && !depthMissing;
  const tradable = hasRequiredContext && spreadBps < 3 && volRegime !== "high" && depthScore > 50;
  let blockedReason: string | null = null;
  if (!tradable) {
    if (!hasRequiredContext) blockedReason = "Missing market context data";
    else if (spreadBps >= 3) blockedReason = "Spread > 3bp threshold";
    else if (volRegime === "high") blockedReason = "High volatility regime";
    else if (depthScore <= 50) blockedReason = "Insufficient liquidity";
    else blockedReason = "Market conditions";
  }
  
  // Edge calculation based on real spread data
  // headwind = spread/2 (half spread as cost) + estimated slippage + fees
  const headwind = (spreadBps / 2) + 0.3 + 0.1; // spread cost + slip + fees
  const expectedEdge = tradable ? Math.max(0, 3.0 - spreadBps * 0.5) : 0; // Model estimate
  const netEdge = expectedEdge - headwind;
  
  // Anomaly flags based on real data
  const anomalyFlags: string[] = [];
  if (spreadChange > 100) anomalyFlags.push("spread_spike");
  if (volChange > 100) anomalyFlags.push("vol_spike");
  if (Math.abs(fundingRate) > 0.03) anomalyFlags.push("funding_extreme");
  if (isStale) anomalyFlags.push("stale_data");
  if (churnScore > 0.8) anomalyFlags.push("high_churn");
  if (!hasRequiredContext) anomalyFlags.push("data_missing");
  
  // Allocation state
  let allocationState: 'allowed' | 'throttled' | 'blocked' = 'allowed';
  if (!tradable) allocationState = 'blocked';
  else if (anomalyFlags.length > 0) allocationState = 'throttled';
  
  // Infer instrument type from symbol name
  // Prefer backend-provided instrument type when available.
  let instrumentType: 'futures' | 'perp' | 'spot' = 'perp';
  const providedType = String(ctx.instrument_type || "").toLowerCase();
  if (providedType === "futures" || providedType === "perp" || providedType === "spot") {
    instrumentType = providedType;
  }
  const upperSymbol = symbol.toUpperCase();
  if (!providedType) {
    if (upperSymbol.includes('SWAP') || upperSymbol.includes('PERP')) {
      instrumentType = 'perp';
    } else if (/\d{6}$/.test(symbol) || upperSymbol.includes('FUTURE')) {
      // Matches expiry dates like 240628 or contains FUTURE
      instrumentType = 'futures';
    } else if (!upperSymbol.includes('-') && (upperSymbol.endsWith('USDT') || upperSymbol.endsWith('USD'))) {
      // Runtime currently trades perp by default; do not classify plain USDT symbols as spot.
      instrumentType = 'perp';
    }
  }
  
  // Clean up symbol name
  const cleanSymbol = symbol.replace(/-USDT-SWAP$/, "USDT").replace(/-USDT$/, "USDT");
  
  return {
    symbol: cleanSymbol,
    pinned: ["BTCUSDT", "ETHUSDT", "SOLUSDT"].includes(cleanSymbol),
    instrumentType,
    
    spread: spreadBps,
    spreadBaseline,
    spreadChange,
    spreadP50: spreadBps * 0.95,  // Estimate from current
    spreadP95: spreadBps * 1.3,   // Estimate from current
    
    vol,
    volBaseline,
    volChange,
    volPercentile: vol,
    
    depth: depthScore,
    depthBaseline: 80,
    liquidityScore: depthScore,
    
    churn: churnScore,
    funding: fundingRate,
    fundingSpike: Math.abs(fundingRate) > 0.02,
    
    expectedEdge,
    headwind,
    netEdge,
    
    regime,
    tradable,
    blockedReason,
    anomalyFlags,
    allocationState,
    
    staleness: isStale ? 1 : 0,
  };
}

// ============================================================================
// HELPER: Extract rejection reasons from REAL signal data
// ============================================================================

function extractRejectionReasons(
  signalData: { rejections?: any; snapshot?: SignalLabSnapshot } | undefined,
  fastScalperData: FastScalperStatusResponse | undefined
): TradingStatus {
  // Get rejections from signal data
  const rejectionEvents = signalData?.rejections?.recent || [];
  const rejectionCounts = signalData?.rejections?.counts || {};
  const snapshot = signalData?.snapshot;
  
  // Get metrics from fast scalper
  const metrics = fastScalperData?.metrics;
  
  // Helper to normalize reason keys for deduplication
  // Normalizes "Signal Generation:No Clear Direction" and "Signal Generation: No Clear Direction" to same key
  const normalizeKey = (key: string): string => {
    return key
      .replace(/:\s*/g, ': ')  // Normalize colon spacing to ": "
      .replace(/_/g, ' ')       // Replace underscores with spaces
      .trim();
  };
  
  // Build normalized reason counts - use normalized keys to avoid duplicates
  const normalizedCounts: Record<string, number> = {};
  
  // First, add from rejectionCounts (from rejections API)
  Object.entries(rejectionCounts).forEach(([reason, count]) => {
    const key = normalizeKey(reason);
    const countNum = typeof count === 'number' ? count : 0;
    normalizedCounts[key] = (normalizedCounts[key] || 0) + countNum;
  });
  
  // Also count from recent events if rejectionCounts is empty
  if (Object.keys(normalizedCounts).length === 0 && rejectionEvents.length > 0) {
    rejectionEvents.forEach((r: any) => {
      const reason = r.blocking_reason || r.reason || r.stage || "Unknown";
      const key = normalizeKey(reason);
      normalizedCounts[key] = (normalizedCounts[key] || 0) + 1;
    });
  }
  
  // If we still have no data, try stageRejections (Record<stage, Record<reason, count>>)
  const stageRejections = snapshot?.stageRejections;
  if (Object.keys(normalizedCounts).length === 0 && stageRejections && typeof stageRejections === 'object') {
    Object.entries(stageRejections).forEach(([stage, reasons]) => {
      if (reasons && typeof reasons === 'object') {
        Object.entries(reasons).forEach(([reason, count]) => {
          const countNum = typeof count === 'number' ? count : 0;
          if (countNum > 0) {
            const key = normalizeKey(`${stage}: ${reason}`);
            normalizedCounts[key] = (normalizedCounts[key] || 0) + countNum;
          }
        });
      }
    });
  }
  
  // Calculate total rejected
  const totalRejected = Object.values(normalizedCounts).reduce((a, b) => a + b, 0);
  
  // Sort by count and format for display
  const sortedReasons = Object.entries(normalizedCounts)
    .map(([reason, count]) => ({
      // Format reason: capitalize first letter of each word
      reason: reason.replace(/\b\w/g, l => l.toUpperCase()),
      count,
      percentage: totalRejected > 0 ? (count / totalRejected) * 100 : 0,
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  
  // Get real metrics from fast scalper - try multiple sources
  // Priority: direct metric > orchestrator stats calculation > 0
  // Note: Fast scalper typically runs at 500-2000 decisions/sec
  let decisionsPerSecond = metrics?.decisionsPerSec ?? (metrics as any)?.decisions_per_sec ?? 0;
  
  // Sanity check: decisionsPerSec should be reasonable (0-10000 range)
  // The bot can legitimately run at 500-2000+ decisions/sec
  if (decisionsPerSecond > 10000 || decisionsPerSecond < 0) {
    decisionsPerSecond = 0; // Invalid, reset
  }
  
  // If no direct metric, try orchestrator stats (same approach as overview page)
  if (decisionsPerSecond === 0) {
    const fsData = fastScalperData as any;
    const orchestratorStats = fsData?.orchestratorStats ?? fsData?.orchestrator_stats;
    if (orchestratorStats?.avg_latency_ms && orchestratorStats.avg_latency_ms > 0) {
      // decisions_per_sec = 1000 / avg_latency_ms (how many decisions fit in 1 second)
      decisionsPerSecond = 1000 / orchestratorStats.avg_latency_ms;
    }
  }
  
  // Get recent decisions for pass rate calculation (not for decisions/sec estimation)
  const recentDecisions = snapshot?.recentDecisions || [];
  
  const tradesToday = metrics?.completedTrades ?? 0;
  
  // Calculate pass rate from recent decisions
  let approvedCount = 0;
  let decidedCount = recentDecisions.length;
  
  if (recentDecisions.length > 0) {
    approvedCount = recentDecisions.filter((d: any) => 
      d.passed === true || d.action === 'trade' || d.result === 'approved'
    ).length;
  }
  
  // If we have rejection counts but no decisions, estimate approved from pass rate
  if (decidedCount === 0 && totalRejected > 0) {
    // Assume some baseline pass rate if we're seeing rejections
    decidedCount = totalRejected;
    approvedCount = 0; // No trades means 0 approved
  }
  
  const totalDecisions = Math.max(approvedCount + totalRejected, decidedCount);
  const passRate = totalDecisions > 0 
    ? (approvedCount / totalDecisions) * 100 
    : 0;
  
  // Build status summary based on real data
  let statusSummary = "System ready";
  const isTrading = tradesToday > 0 || (metrics?.positions ?? 0) > 0;
  
  if (isTrading) {
    statusSummary = `Trading: ${tradesToday} trades, ${metrics?.positions || 0} positions`;
  } else if (totalRejected > 0) {
    const topReason = sortedReasons[0]?.reason || "conditions";
    statusSummary = `Not trading: ${topReason}`;
  } else if (fastScalperData?.status !== 'running') {
    statusSummary = `Bot ${fastScalperData?.status || 'not running'}`;
  }
  
  return {
    tradesToday,
    decisionsPerSecond,
    approvedCount,
    rejectedCount: totalRejected,
    passRate,
    topRejectionReasons: sortedReasons,
    statusSummary,
    isTrading,
    blockedSymbolCount: 0, // Will be calculated from symbols
    totalSymbolCount: 0,
  };
}

// ============================================================================
// HELPER: Extract gates from REAL health/config data
// ============================================================================

function extractGates(
  healthData: HealthSnapshot | undefined,
  overviewData: any,
  fastScalperData: FastScalperStatusResponse | undefined,
  symbols: SymbolRow[]
): GateStatus[] {
  const gates: GateStatus[] = [];
  const evaluableSymbols = symbols.filter((s) => !s.anomalyFlags.includes("data_missing"));
  
  // Data readiness gate - from real service health
  const serviceHealth = healthData?.serviceHealth || fastScalperData?.serviceHealth;
  const hasDataSignal =
    serviceHealth?.services?.data_collector !== undefined ||
    fastScalperData?.websocket?.publicConnected !== undefined;
  const dataReady = serviceHealth?.services?.data_collector === true ||
                    fastScalperData?.websocket?.publicConnected === true;
  gates.push({
    name: "Data Ready",
    key: "data_ready",
    threshold: "Connected",
    actual: !hasDataSignal ? "Unknown" : dataReady ? "Connected" : "Disconnected",
    unit: "",
    passed: !hasDataSignal ? true : dataReady,
    severity: !hasDataSignal ? 'warning' : dataReady ? 'ok' : 'critical',
    blocking: hasDataSignal ? !dataReady : false,
    unknown: !hasDataSignal,
    description: !hasDataSignal
      ? "Feed status telemetry unavailable"
      : "Market data feed connection status",
  });
  
  // Websocket gate
  const hasWsSignal =
    fastScalperData?.websocket?.publicConnected !== undefined ||
    fastScalperData?.websocket?.privateConnected !== undefined;
  const wsConnected = Boolean(
    fastScalperData?.websocket?.publicConnected &&
    fastScalperData?.websocket?.privateConnected
  );
  gates.push({
    name: "WebSocket",
    key: "websocket",
    threshold: "Connected",
    actual: !hasWsSignal ? "Unknown" : wsConnected ? "Connected" : "Partial/Disconnected",
    unit: "",
    passed: !hasWsSignal ? true : wsConnected,
    severity: !hasWsSignal ? 'warning' : wsConnected ? 'ok' : 'warning',
    blocking: false,
    unknown: !hasWsSignal,
    description: !hasWsSignal
      ? "WebSocket telemetry unavailable"
      : "Exchange WebSocket connection status",
  });
  
  // Spread gate - calculated from real symbol data
  const avgSpread = evaluableSymbols.length > 0
    ? evaluableSymbols.reduce((a, s) => a + s.spread, 0) / evaluableSymbols.length
    : 0;
  const spreadCap = 2.0; // bps threshold
  gates.push({
    name: "Avg Spread",
    key: "spread_cap",
    threshold: spreadCap,
    actual: evaluableSymbols.length === 0 ? "Unknown" : Number(avgSpread.toFixed(2)),
    unit: "bp",
    passed: evaluableSymbols.length === 0 ? true : avgSpread <= spreadCap,
    severity: evaluableSymbols.length === 0
      ? 'warning'
      : avgSpread <= spreadCap
      ? 'ok'
      : avgSpread <= spreadCap * 1.5
      ? 'warning'
      : 'critical',
    blocking: evaluableSymbols.length === 0 ? false : avgSpread > spreadCap * 1.5,
    unknown: evaluableSymbols.length === 0,
    description: evaluableSymbols.length === 0
      ? "Spread telemetry unavailable"
      : "Average spread across tradable symbols",
  });
  
  // Volatility gate - from real symbol data
  const avgVol = evaluableSymbols.length > 0
    ? evaluableSymbols.reduce((a, s) => a + s.volPercentile, 0) / evaluableSymbols.length
    : 50;
  const volLow = 20;
  const volHigh = 80;
  const volInBand = avgVol >= volLow && avgVol <= volHigh;
  gates.push({
    name: "Vol Band",
    key: "vol_band",
    threshold: `${volLow}-${volHigh}`,
    actual: evaluableSymbols.length === 0 ? "Unknown" : `${avgVol.toFixed(0)}`,
    unit: "pct",
    passed: evaluableSymbols.length === 0 ? true : volInBand,
    severity: evaluableSymbols.length === 0 ? 'warning' : volInBand ? 'ok' : 'warning',
    blocking: false,
    unknown: evaluableSymbols.length === 0,
    description: evaluableSymbols.length === 0
      ? "Volatility telemetry unavailable"
      : "Average volatility percentile",
  });
  
  // Warmup gate - from real warmup status
  const hasWarmupSignal = fastScalperData?.warmup?.allWarmedUp !== undefined;
  const warmupReady = fastScalperData?.warmup?.allWarmedUp ?? true;
  gates.push({
    name: "Warmup",
    key: "warmup",
    threshold: "Ready",
    actual: !hasWarmupSignal ? "Unknown" : warmupReady ? "Ready" : "Warming",
    unit: "",
    passed: !hasWarmupSignal ? true : warmupReady,
    severity: !hasWarmupSignal ? 'warning' : warmupReady ? 'ok' : 'warning',
    blocking: false,
    unknown: !hasWarmupSignal,
    description: !hasWarmupSignal
      ? "Warmup telemetry unavailable"
      : "Historical data warmup status",
  });
  
  // Position limit gate - from real metrics
  const hasPositionSignal =
    fastScalperData?.metrics?.positions !== undefined ||
    fastScalperData?.metrics?.maxPositions !== undefined;
  const positions = fastScalperData?.metrics?.positions ?? 0;
  const maxPositions = fastScalperData?.metrics?.maxPositions ?? 10;
  const positionOk = positions < maxPositions;
  gates.push({
    name: "Position Limit",
    key: "position_limit",
    threshold: maxPositions,
    actual: hasPositionSignal ? positions : "Unknown",
    unit: "",
    passed: !hasPositionSignal ? true : positionOk,
    severity: !hasPositionSignal ? 'warning' : positionOk ? 'ok' : positions === maxPositions ? 'warning' : 'critical',
    blocking: hasPositionSignal ? !positionOk : false,
    unknown: !hasPositionSignal,
    description: !hasPositionSignal
      ? "Position telemetry unavailable"
      : "Current positions vs maximum allowed",
  });
  
  return gates;
}

// ============================================================================
// HELPER: Extract regime events from REAL data
// ============================================================================

function extractRegimeEvents(
  healthData: HealthSnapshot | undefined,
  signalData: { rejections?: any; snapshot?: SignalLabSnapshot } | undefined,
  symbols: SymbolRow[]
): RegimeEvent[] {
  const events: RegimeEvent[] = [];
  const now = Date.now();
  
  // 1. Generate events from rejection reasons (most important)
  // The rejections API returns { recent: [], counts: {}, timestamp: "" }
  const rejectionsData = signalData?.rejections;
  const recentRejections = Array.isArray(rejectionsData) 
    ? rejectionsData 
    : (rejectionsData?.recent || []);
  const preAggregatedCounts = rejectionsData?.counts || {};
  
  // If we have pre-aggregated counts, use those directly
  if (Object.keys(preAggregatedCounts).length > 0) {
    Object.entries(preAggregatedCounts)
      .sort((a, b) => (b[1] as number) - (a[1] as number))
      .slice(0, 5)
      .forEach(([reason, count], idx) => {
        // Determine event type based on reason
        let type: RegimeEvent['type'] = 'anomaly';
        const reasonLower = reason.toLowerCase();
        if (reasonLower.includes('spread')) type = 'spread';
        else if (reasonLower.includes('vol')) type = 'volatility';
        else if (reasonLower.includes('liquid') || reasonLower.includes('depth')) type = 'liquidity';
        else if (reasonLower.includes('fund') || reasonLower.includes('basis')) type = 'funding';
        else if (reasonLower.includes('latency') || reasonLower.includes('ws') || reasonLower.includes('connect')) type = 'venue';
        
        const countNum = count as number;
        events.push({
          id: `rejection-${idx}`,
          timestamp: now - (idx * 60000),
          time: new Date(now - (idx * 60000)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          type,
          title: reason,
          message: `${countNum} rejections`,
          severity: countNum > 50 ? 'critical' : countNum > 10 ? 'warning' : 'info',
          symbols: [],
        });
      });
  } else if (Array.isArray(recentRejections) && recentRejections.length > 0) {
    // Fall back to processing individual rejections
    const rejectionCounts: Record<string, { count: number; symbols: string[] }> = {};
    
    recentRejections.forEach((r: any) => {
      const reason = r.reason || r.blocking_reason || 'Unknown';
      if (!rejectionCounts[reason]) {
        rejectionCounts[reason] = { count: 0, symbols: [] };
      }
      rejectionCounts[reason].count++;
      if (r.symbol && !rejectionCounts[reason].symbols.includes(r.symbol)) {
        rejectionCounts[reason].symbols.push(r.symbol);
      }
    });
    
    // Create events for top rejection reasons
    Object.entries(rejectionCounts)
      .sort((a, b) => b[1].count - a[1].count)
      .slice(0, 5)
      .forEach(([reason, data], idx) => {
        // Determine event type based on reason
        let type: RegimeEvent['type'] = 'anomaly';
        const reasonLower = reason.toLowerCase();
        if (reasonLower.includes('spread')) type = 'spread';
        else if (reasonLower.includes('vol')) type = 'volatility';
        else if (reasonLower.includes('liquid') || reasonLower.includes('depth')) type = 'liquidity';
        else if (reasonLower.includes('fund') || reasonLower.includes('basis')) type = 'funding';
        else if (reasonLower.includes('latency') || reasonLower.includes('ws') || reasonLower.includes('connect')) type = 'venue';
        
        events.push({
          id: `rejection-${idx}`,
          timestamp: now - (idx * 60000),
          time: new Date(now - (idx * 60000)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          type,
          title: reason,
          message: `${data.count} rejections across ${data.symbols.length} symbol${data.symbols.length !== 1 ? 's' : ''}`,
          severity: data.count > 50 ? 'critical' : data.count > 10 ? 'warning' : 'info',
          symbols: data.symbols.slice(0, 5),
        });
      });
  }
  
  // 2. Generate events from symbols with anomalies
  const anomalySymbols = symbols.filter(s => s.anomalyFlags && s.anomalyFlags.length > 0);
  if (anomalySymbols.length > 0) {
    // Group by anomaly type
    const anomalyGroups: Record<string, string[]> = {};
    anomalySymbols.forEach(s => {
      s.anomalyFlags?.forEach(flag => {
        if (!anomalyGroups[flag]) anomalyGroups[flag] = [];
        anomalyGroups[flag].push(s.symbol);
      });
    });
    
    Object.entries(anomalyGroups).forEach(([flag, syms], idx) => {
      events.push({
        id: `anomaly-${idx}`,
        timestamp: now - 5000 - (idx * 30000),
        time: new Date(now - 5000 - (idx * 30000)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        type: 'anomaly',
        title: `${flag} detected`,
        message: `${syms.length} symbol${syms.length !== 1 ? 's' : ''} flagged`,
        severity: syms.length > 3 ? 'warning' : 'info',
        symbols: syms.slice(0, 5),
      });
    });
  }
  
  // 3. Generate events from blocked symbols (spread/vol/liquidity gates)
  const blockedBySpread = symbols.filter(s => !s.tradable && s.blockedReason?.toLowerCase().includes('spread'));
  if (blockedBySpread.length >= 3) {
    events.push({
      id: 'regime-spread',
      timestamp: now - 120000,
      time: new Date(now - 120000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      type: 'spread',
      title: 'Spread regime elevated',
      message: `${blockedBySpread.length} symbols blocked by spread gate`,
      severity: blockedBySpread.length >= 5 ? 'warning' : 'info',
      symbols: blockedBySpread.map(s => s.symbol).slice(0, 5),
    });
  }
  
  const blockedByVol = symbols.filter(s => !s.tradable && s.blockedReason?.toLowerCase().includes('vol'));
  if (blockedByVol.length >= 3) {
    events.push({
      id: 'regime-vol',
      timestamp: now - 180000,
      time: new Date(now - 180000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      type: 'volatility',
      title: 'Volatility regime shift',
      message: `${blockedByVol.length} symbols blocked by volatility gate`,
      severity: blockedByVol.length >= 5 ? 'warning' : 'info',
      symbols: blockedByVol.map(s => s.symbol).slice(0, 5),
    });
  }
  
  const blockedByLiquidity = symbols.filter(s => !s.tradable && s.blockedReason?.toLowerCase().includes('liquid'));
  if (blockedByLiquidity.length >= 3) {
    events.push({
      id: 'regime-liquidity',
      timestamp: now - 240000,
      time: new Date(now - 240000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      type: 'liquidity',
      title: 'Liquidity thinning',
      message: `${blockedByLiquidity.length} symbols blocked by liquidity gate`,
      severity: blockedByLiquidity.length >= 5 ? 'warning' : 'info',
      symbols: blockedByLiquidity.map(s => s.symbol).slice(0, 5),
    });
  }
  
  // 4. Get recent decisions that had notable outcomes
  const recentDecisions = signalData?.snapshot?.recentDecisions || [];
  recentDecisions.slice(0, 5).forEach((d: any, idx: number) => {
    if (d.blocking_reason || d.passed === false) {
      events.push({
        id: `decision-${idx}`,
        timestamp: d.timestamp || (now - 300000 - idx * 60000),
        time: new Date(d.timestamp || (now - 300000 - idx * 60000)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        type: 'anomaly',
        title: d.blocking_reason || "Decision blocked",
        message: `${d.symbol || 'Unknown'}: ${d.blocking_reason || 'Blocked'}`,
        severity: 'warning',
        symbols: d.symbol ? [d.symbol] : [],
      });
    }
  });
  
  // 5. Get feature health issues
  const featureHealth = signalData?.snapshot?.featureHealth || {};
  Object.entries(featureHealth).forEach(([feature, health]: [string, any]) => {
    if (health?.status === 'stale' || health?.status === 'error') {
      events.push({
        id: `feature-${feature}`,
        timestamp: health.timestamp || (now - 600000),
        time: new Date(health.timestamp || (now - 600000)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        type: 'venue',
        title: `Feature ${health.status}`,
        message: `${feature}: ${health.status}`,
        severity: health.status === 'error' ? 'critical' : 'warning',
        symbols: [],
      });
    }
  });
  
  // 6. Add health-based events
  if (healthData) {
    // Cast to access optional fields
    const health = healthData as HealthSnapshot & { 
      websocket_connected?: boolean; 
      api_latency_ms?: number;
    };
    
    // WebSocket health
    if (health.websocket_connected === false) {
      events.push({
        id: 'ws-disconnected',
        timestamp: now - 30000,
        time: new Date(now - 30000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        type: 'venue',
        title: 'WebSocket disconnected',
        message: 'Exchange data feed interrupted',
        severity: 'critical',
        symbols: [],
      });
    }
    
    // API health
    if (health.api_latency_ms && health.api_latency_ms > 500) {
      events.push({
        id: 'api-latency',
        timestamp: now - 60000,
        time: new Date(now - 60000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        type: 'venue',
        title: 'High API latency',
        message: `API latency: ${health.api_latency_ms}ms`,
        severity: health.api_latency_ms > 1000 ? 'critical' : 'warning',
        symbols: [],
      });
    }
  }
  
  // Sort by timestamp descending and limit
  return events.sort((a, b) => b.timestamp - a.timestamp).slice(0, 20);
}

// ============================================================================
// HELPER: Calculate bot fit score from REAL data
// ============================================================================

function calculateBotFit(
  symbols: SymbolRow[], 
  healthData: HealthSnapshot | undefined,
  fastScalperData: FastScalperStatusResponse | undefined
): BotFitScore {
  const totalCount = symbols.length || 1;
  const dataMissingCount = symbols.filter(s => s.anomalyFlags.includes("data_missing")).length;
  const evaluableSymbols = symbols.filter(s => !s.anomalyFlags.includes("data_missing"));
  const evaluableCount = evaluableSymbols.length;
  const tradableCount = evaluableSymbols.filter(s => s.tradable).length;
  
  // Microstructure fit: based on real spread and liquidity data
  const avgSpread = evaluableCount > 0 
    ? evaluableSymbols.reduce((a, s) => a + s.spread, 0) / evaluableCount 
    : 1.0;
  const avgDepth = evaluableCount > 0 
    ? evaluableSymbols.reduce((a, s) => a + s.depth, 0) / evaluableCount 
    : 60;
  const microstructureFit = Math.max(0, Math.min(100, 
    (100 - avgSpread * 15) * 0.5 + (avgDepth) * 0.5
  ));
  
  // Regime fit: based on real volatility data
  const avgVol = evaluableCount > 0
    ? evaluableSymbols.reduce((a, s) => a + s.volPercentile, 0) / evaluableCount
    : 50;
  // Optimal vol is 30-70 percentile
  let regimeFit = 100;
  if (avgVol < 20 || avgVol > 80) regimeFit = 40;
  else if (avgVol < 30 || avgVol > 70) regimeFit = 70;
  else regimeFit = 90;
  
  // Execution fit: based on real system health
  const wsStatus = fastScalperData?.websocket;
  const wsScore = ((wsStatus?.publicConnected ?? true) ? 50 : 0) + ((wsStatus?.privateConnected ?? true) ? 50 : 0);
  const warmupReady = (fastScalperData?.warmup?.allWarmedUp ?? true) ? 100 : 50;
  const executionFit = (wsScore + warmupReady) / 2;
  
  // Risk fit: based on tradable symbols and anomalies
  const anomalyCount = evaluableSymbols.reduce((a, s) => a + s.anomalyFlags.filter(f => f !== "data_missing").length, 0);
  const tradableRatio = evaluableCount > 0 ? tradableCount / evaluableCount : 0.5;
  const riskFit = Math.max(0, Math.min(100, tradableRatio * 100 - anomalyCount * 10));
  
  // Overall score - weighted average
  const overall = Math.round(
    microstructureFit * 0.3 + 
    regimeFit * 0.25 + 
    executionFit * 0.25 + 
    riskFit * 0.2
  );
  
  // Recommendations based on real conditions
  const recommendations: string[] = [];
  if (avgSpread > 2.0) {
    recommendations.push(`Wide spreads (avg ${avgSpread.toFixed(1)}bp) - reduce size or wait`);
  }
  if (evaluableCount > 0 && regimeFit < 60) {
    recommendations.push(`Vol at ${avgVol.toFixed(0)}th pct - outside optimal 30-70 range`);
  }
  if (executionFit < 60) {
    if (fastScalperData?.websocket?.publicConnected === false) {
      recommendations.push("Public WebSocket disconnected - check connection");
    }
    if (fastScalperData?.warmup?.allWarmedUp === false) {
      recommendations.push("Data warmup incomplete - wait for ready state");
    }
  }
  if (dataMissingCount > 0) {
    recommendations.push(`Market context incomplete for ${dataMissingCount}/${totalCount} symbols`);
  }
  if (riskFit < 60) {
    if (evaluableCount > 0 && tradableCount < evaluableCount * 0.5) {
      recommendations.push(`Only ${tradableCount}/${evaluableCount} symbols tradable`);
    }
    if (anomalyCount > 0) {
      recommendations.push(`${anomalyCount} anomaly flags detected`);
    }
  }
  
  return {
    overall,
    microstructureFit: Math.round(microstructureFit),
    regimeFit: Math.round(regimeFit),
    executionFit: Math.round(executionFit),
    riskFit: Math.round(riskFit),
    recommendations,
    expectedConcentration: tradableCount > 0 ? Math.round(100 / tradableCount) : 100,
  };
}

// ============================================================================
// HELPER: Extract venue health from REAL data
// ============================================================================

function extractVenueHealth(
  healthData: HealthSnapshot | undefined,
  fastScalperData: FastScalperStatusResponse | undefined
): VenueHealth {
  const wsStatus = fastScalperData?.websocket;
  const serviceHealth = healthData?.serviceHealth || fastScalperData?.serviceHealth;
  
  // Get real metrics
  const messagesReceived = wsStatus?.messagesReceived ?? 0;
  const wsConnected = wsStatus?.publicConnected && wsStatus?.privateConnected;
  
  // Estimate latency from system metrics (would need real latency tracking)
  const resourceUsage = healthData?.resourceUsage;
  const cpuPercent = resourceUsage?.process_cpu_percent ?? 0;
  // Higher CPU often correlates with higher latency
  const estimatedLatency = 20 + (cpuPercent * 0.5);
  
  // Check if all services are ready - handle both allReady and all_ready
  const allServicesReady = (serviceHealth as any)?.allReady ?? (serviceHealth as any)?.all_ready ?? true;
  
  let status: 'healthy' | 'degraded' | 'down' = 'healthy';
  if (!wsConnected) status = 'down';
  else if (!allServicesReady) status = 'degraded';
  
  let feedHealth: 'ok' | 'stale' | 'disconnected' = 'ok';
  if (!wsStatus?.publicConnected) feedHealth = 'disconnected';
  else if (messagesReceived === 0) feedHealth = 'stale';
  
  return {
    status,
    latencyP50: Math.round(estimatedLatency),
    latencyP95: Math.round(estimatedLatency * 1.5),
    rejectRate: 0, // Would need real reject tracking
    websocketGaps: feedHealth === 'stale' ? 1 : 0,
    lastHeartbeatAge: 0,
    feedHealth,
  };
}

// ============================================================================
// HELPER: Extract safety metrics from REAL data
// ============================================================================

function extractSafetyMetrics(
  overviewData: any,
  fastScalperData: FastScalperStatusResponse | undefined,
  riskData: any
): SafetyMetrics {
  // Get real metrics from fast scalper
  const metrics = fastScalperData?.metrics;
  
  // Get from scoped metrics if available
  const scopedMetrics = overviewData?.scopedMetrics;
  
  // REAL daily loss data from Redis risk endpoint
  // riskData has: daily_pnl, daily_pnl_limit, total_exposure, total_exposure_limit
  const dailyPnl = riskData?.daily_pnl ?? scopedMetrics?.daily_pnl ?? metrics?.dailyPnl ?? 0;
  const dailyLossLimit = riskData?.daily_pnl_limit ?? riskData?.limits?.max_daily_loss ?? 500;
  const dailyLossUsed = dailyPnl < 0 ? Math.abs(dailyPnl) : 0;
  
  // REAL exposure data in USD from Redis risk endpoint
  const totalExposure = riskData?.total_exposure ?? scopedMetrics?.gross_exposure ?? 0;
  const totalExposureLimit = riskData?.total_exposure_limit ?? riskData?.limits?.max_total_exposure ?? 10000;
  const exposureUsedPct = totalExposureLimit > 0 ? (totalExposure / totalExposureLimit) * 100 : 0;
  
  // Kill switch - check if trading is blocked
  const botStatus = overviewData?.botStatus;
  const killSwitchTriggered = botStatus?.trading?.killSwitchTriggered || 
                              riskData?.circuit_breakers_status === 'triggered' ||
                              false;
  
  return {
    dailyLossUsed,
    dailyLossLimit,
    dailyLossRemaining: Math.max(0, dailyLossLimit - dailyLossUsed),
    exposureUsed: totalExposure,  // Now in USD, not percentage
    exposureCap: totalExposureLimit,  // Now in USD
    exposureUsedPct,  // Percentage for display
    killSwitchStatus: killSwitchTriggered ? 'triggered' : 'armed',
  };
}

// ============================================================================
// MAIN HOOK: useMarketFitData
// ============================================================================

export function useMarketFitData(): MarketFitData {
  // Get scope info
  const { exchangeAccountId, botId, botName: scopeBotName } = useScopeStore();
  
  // Fetch all REAL data sources
  const { data: marketContextData, isLoading: contextLoading, error: contextError } = useMarketContext({ botId });
  const { data: signalData } = useSignalLabData();
  const { data: healthData } = useHealthSnapshot();
  const { data: activeBotData } = useActiveBot();
  const { data: overviewData } = useOverviewData({ exchangeAccountId, botId });
  const { data: riskData } = useDashboardRisk({ exchangeAccountId: exchangeAccountId || undefined, botId: botId || undefined });
  
  // Fast scalper data is included in overviewData
  const fastScalperData = overviewData?.fastScalper as FastScalperStatusResponse | undefined;
  
  return useMemo(() => {
    // Transform symbols from REAL market context data
    const symbols: SymbolRow[] = marketContextData?.contexts 
      ? Object.entries(marketContextData.contexts).map(([symbol, context]) =>
          transformContextToSymbol(symbol, context)
        )
      : [];
    
    // Calculate regime summaries from real data
    const spreadElevated = symbols.filter(s => s.spreadChange > 50).length;
    const volElevated = symbols.filter(s => s.volChange > 50).length;
    const liqLow = symbols.filter(s => s.depth < 60).length;
    
    const spreadRegime = spreadElevated > 2 ? (spreadElevated > 4 ? 'extreme' : 'widened') : 'normal';
    const volRegime = volElevated > 2 ? (volElevated > 4 ? 'spike' : 'elevated') : 'normal';
    const liqRegime = liqLow > 2 ? (liqLow > 4 ? 'cliffy' : 'thin') : 'normal';
    
    // Extract trading status from REAL data
    const tradingStatus = extractRejectionReasons(signalData, fastScalperData);
    tradingStatus.blockedSymbolCount = symbols.filter(s => !s.tradable).length;
    tradingStatus.totalSymbolCount = symbols.length;
    
    // Update status summary with symbol info
    if (!tradingStatus.isTrading && symbols.length > 0) {
      const blocked = tradingStatus.blockedSymbolCount;
      const total = tradingStatus.totalSymbolCount;
      if (blocked === total && total > 0) {
        tradingStatus.statusSummary = `Not trading: All ${total} symbols blocked`;
      } else if (blocked > 0) {
        tradingStatus.statusSummary = `${total - blocked}/${total} symbols tradable`;
      }
    }
    
    // Extract other data from REAL sources
    const gates = extractGates(healthData, overviewData, fastScalperData, symbols);
    const regimeEvents = extractRegimeEvents(healthData, signalData, symbols);
    const botFit = calculateBotFit(symbols, healthData, fastScalperData);
    const venueHealth = extractVenueHealth(healthData, fastScalperData);
    const safety = extractSafetyMetrics(overviewData, fastScalperData, riskData);
    
    // Bot info from REAL sources
    const botStatus = overviewData?.botStatus as any;
    const tradingInfo = botStatus?.trading;
    const dbBotStatus = botStatus?.dbBotStatus;
    
    // Get bot name from real sources
    const resolvedBotName = scopeBotName || activeBotData?.bot?.name || dbBotStatus?.name || null;
    
    // Get running status from real sources
    const isRunning = tradingInfo?.isActive || 
                      dbBotStatus?.state === 'running' || 
                      fastScalperData?.status === 'running' ||
                      false;
    const runningSince = tradingInfo?.startedAt || dbBotStatus?.started_at || null;
    
    // Get profile info from real sources - bots can use multiple profiles
    // These fields are kept for backwards compatibility but may show "Multiple" or null
    const botData = activeBotData?.bot as any;
    const profileName = botData?.profile || botData?.profile_name || dbBotStatus?.profile_name || null;
    const profileVersion = botData?.version || botData?.config_version?.toString() || dbBotStatus?.config_version?.toString() || null;
    
    return {
      symbols,
      tradingStatus,
      gates,
      regimeEvents,
      botFit,
      venueHealth,
      safety,
      
      botName: resolvedBotName,
      botRunning: isRunning,
      botRunningSince: runningSince,
      profileName,
      profileVersion,
      
      spreadRegime,
      volRegime,
      liqRegime,
      
      isLoading: contextLoading,
      error: contextError as Error | null,
    };
  }, [marketContextData, signalData, healthData, activeBotData, overviewData, riskData, contextLoading, contextError, scopeBotName]);
}

// ============================================================================
// HELPER HOOK: useRegimeSparklineData
// Returns empty arrays - sparklines will show "no data" state
// A real implementation would need a historical metrics API
// ============================================================================

export function useRegimeSparklineData(_window: '5m' | '1h' | '6h' | '24h') {
  // Return empty data - sparklines will show empty state
  // To implement real sparklines, we'd need a historical metrics endpoint
  return useMemo(() => ({
    spread: [] as { x: number; y: number }[],
    vol: [] as { x: number; y: number }[],
    liquidity: [] as { x: number; y: number }[],
    headwind: [] as { x: number; y: number }[],
    venue: [] as { x: number; y: number }[],
  }), []);
}
