/**
 * OrderbookModelPanel - Main orchestrator for the microstructure prediction model dashboard
 * 
 * Layout:
 * Row 0: ScopeBar (sticky controls)
 * Row 1: PulseTiles (4 KPIs)
 * Row 2: RollingAccuracyChart | SymbolScoreboardTable
 * Row 3: ReliabilityCurveChart | PredVsActualScatter
 * Row 4: FilterEffectivenessMatrix | BlockedCandidatesTable
 * Row 5: AdvancedSection (collapsible)
 */

import { useState, useMemo } from "react";
import { Loader2 } from "lucide-react";
import { Card } from "../ui/card";
import type { TimeWindow } from "../../types/orderbookModel";

// Components
import { ScopeBar } from "./ScopeBar";
import { PulseTiles } from "./PulseTiles";
import { RollingAccuracyChart } from "./RollingAccuracyChart";
import { SymbolScoreboardTable } from "./SymbolScoreboardTable";
import { ReliabilityCurveChart } from "./ReliabilityCurveChart";
import { PredVsActualScatter } from "./PredVsActualScatter";
import { FilterEffectivenessMatrix } from "./FilterEffectivenessMatrix";
import { BlockedCandidatesTable } from "./BlockedCandidatesTable";
import { AdvancedSection } from "./AdvancedSection";

// Hooks
import {
  useOrderbookModelPulse,
  useOrderbookModelAccuracySeries,
  useOrderbookModelScoreboard,
  useOrderbookModelReliability,
  useOrderbookModelPredVsActual,
  useOrderbookModelErrorDist,
  useOrderbookModelFilterEffectiveness,
  useOrderbookModelBlockedCandidates,
  useOrderbookModelThresholdSweep,
} from "../../lib/api/orderbook-model-hooks";

interface OrderbookModelPanelProps {
  botId: string | null | undefined;
}

export function OrderbookModelPanel({ botId }: OrderbookModelPanelProps) {
  // Scope controls
  const [window, setWindow] = useState<TimeWindow>("15m");
  const [symbol, setSymbol] = useState<string>("ALL");
  const [minConfidence, setMinConfidence] = useState(0.65);
  const [minMove, setMinMove] = useState(3.0);

  // Data fetching
  const { data: pulse, isLoading: pulseLoading } = useOrderbookModelPulse(botId, window, symbol);
  const { data: accuracySeries, isLoading: accuracyLoading } = useOrderbookModelAccuracySeries(
    botId,
    window,
    symbol
  );
  const { data: scoreboard, isLoading: scoreboardLoading } = useOrderbookModelScoreboard(
    botId,
    window
  );
  const { data: reliability, isLoading: reliabilityLoading } = useOrderbookModelReliability(
    botId,
    window,
    symbol,
    0.5
  );
  const { data: predActual, isLoading: predActualLoading } = useOrderbookModelPredVsActual(
    botId,
    window,
    symbol === "ALL" ? undefined : symbol,
    minConfidence,
    minMove
  );
  const { data: errorDist, isLoading: errorDistLoading } = useOrderbookModelErrorDist(
    botId,
    window,
    symbol,
    minConfidence
  );
  const { data: filterEffectiveness, isLoading: filterLoading } =
    useOrderbookModelFilterEffectiveness(botId, window, symbol);
  const { data: blockedCandidates, isLoading: blockedLoading } =
    useOrderbookModelBlockedCandidates(botId, window, symbol === "ALL" ? undefined : symbol, 200);
  const { data: thresholdSweep, isLoading: sweepLoading } = useOrderbookModelThresholdSweep(
    botId,
    "24h",
    symbol
  );

  // Extract available symbols from scoreboard
  const availableSymbols = useMemo(
    () => scoreboard?.map((s) => s.symbol) ?? [],
    [scoreboard]
  );

  // Determine data health
  const dataHealth = useMemo(() => {
    if (!pulse) return "stale";
    const p95Age = pulse.freshness?.p95_prediction_age_ms ?? 10000;
    if (p95Age < 1000) return "fresh";
    if (p95Age < 3000) return "degraded";
    return "stale";
  }, [pulse]);

  // Format last update time
  const lastUpdate = useMemo(() => {
    if (!pulse?.updated_at) return undefined;
    const date = new Date(pulse.updated_at);
    return date.toLocaleTimeString();
  }, [pulse?.updated_at]);

  // Loading state
  const isLoading = pulseLoading && !pulse;

  if (!botId) {
    return (
      <Card className="p-8 text-center">
        <p className="text-muted-foreground">
          Select a bot to view microstructure model metrics
        </p>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-3 text-muted-foreground">Loading model metrics...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Row 0: Scope Bar */}
      <ScopeBar
        window={window}
        onWindowChange={setWindow}
        symbol={symbol}
        onSymbolChange={setSymbol}
        availableSymbols={availableSymbols}
        minConfidence={minConfidence}
        onMinConfidenceChange={setMinConfidence}
        minMove={minMove}
        onMinMoveChange={setMinMove}
        dataHealth={dataHealth}
        lastUpdate={lastUpdate}
      />

      {/* Row 1: Pulse Tiles */}
      <PulseTiles
        pulse={pulse}
        accuracySeries={accuracySeries}
        isLoading={pulseLoading && accuracyLoading}
      />

      {/* Row 2: Accuracy Chart + Scoreboard */}
      <div className="grid gap-4 lg:grid-cols-2">
        <RollingAccuracyChart data={accuracySeries} isLoading={accuracyLoading} />
        <SymbolScoreboardTable
          data={scoreboard}
          isLoading={scoreboardLoading}
          onSymbolClick={(s) => setSymbol(s)}
        />
      </div>

      {/* Row 3: Calibration Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <ReliabilityCurveChart data={reliability} isLoading={reliabilityLoading} />
        <PredVsActualScatter data={predActual} isLoading={predActualLoading} />
      </div>

      {/* Row 4: Filter Effectiveness */}
      <div className="grid gap-4 lg:grid-cols-2">
        <FilterEffectivenessMatrix data={filterEffectiveness} isLoading={filterLoading} />
        <BlockedCandidatesTable data={blockedCandidates} isLoading={blockedLoading} />
      </div>

      {/* Row 5: Advanced (Collapsible) */}
      <AdvancedSection
        sweepData={thresholdSweep}
        errorDistData={errorDist}
        isLoading={sweepLoading || errorDistLoading}
      />
    </div>
  );
}

