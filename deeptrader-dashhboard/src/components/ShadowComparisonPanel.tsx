import { useQuery } from "@tanstack/react-query";
import { Brain, Gauge, Loader2, AlertTriangle, Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "./ui/tooltip";
import { fetchPredictionScore, PredictionScoreResponse } from "../lib/api/client";
import { cn } from "../lib/utils";

export const usePredictionScore = (provider: "shadow" | "live" = "live") =>
  useQuery<PredictionScoreResponse>({
    queryKey: ["prediction-score", provider],
    queryFn: () => fetchPredictionScore({ provider, lookback_hours: 6, horizon_sec: 60 }),
    refetchInterval: 10000,
    staleTime: 5000,
  });

interface ShadowComparisonPanelProps {
  compact?: boolean;
  provider?: "shadow" | "live";
}

function scoreColor(score: number): string {
  if (score >= 70) return "text-emerald-600";
  if (score >= 55) return "text-amber-600";
  return "text-red-600";
}

export function ShadowComparisonPanel({ compact = false, provider = "live" }: ShadowComparisonPanelProps) {
  const { data, isLoading, error } = usePredictionScore(provider);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading prediction quality...</span>
        </CardContent>
      </Card>
    );
  }

  if (error || !data?.enabled || !data.metrics) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <span className="ml-2 text-muted-foreground">Prediction quality unavailable</span>
        </CardContent>
      </Card>
    );
  }

  const m = data.metrics;
  const quality = m.ml_score;
  const abstainRate = m.abstain_rate_pct ?? 0;
  const directionalAccuracyNonFlat = m.directional_accuracy_nonflat_pct ?? m.directional_accuracy_pct;
  const directionalCoverage = m.directional_coverage_pct ?? 100;

  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2 cursor-pointer">
              <Brain className="h-4 w-4 text-muted-foreground" />
              <Badge variant="outline" className={cn("font-mono", scoreColor(quality))}>
                ML {quality.toFixed(1)}
              </Badge>
              <Badge variant="outline" className="font-mono">
                Acc {m.exact_accuracy_pct.toFixed(1)}%
              </Badge>
              <Badge variant="outline" className="font-mono">
                Abst {abstainRate.toFixed(0)}%
              </Badge>
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs">
            <p className="font-medium">Prediction Quality</p>
            <p className="text-xs mt-1">
              Exact accuracy: {m.exact_accuracy_pct.toFixed(1)}% over {m.samples} samples. Abstain:{" "}
              {abstainRate.toFixed(1)}% ({m.abstain_count}/{m.predictions_total}).
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <Gauge className="h-4 w-4" />
            Prediction ML Score
          </CardTitle>
          <Badge variant="outline" className={cn("font-mono", scoreColor(quality))}>
            <Activity className="h-3 w-3 mr-1" />
            {quality.toFixed(1)} / 100
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Realized Prediction Accuracy</span>
            <span className="text-2xl font-bold font-mono">{m.exact_accuracy_pct.toFixed(1)}%</span>
          </div>
          <Progress value={m.exact_accuracy_pct} className="h-2" />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Directional Accuracy (non-flat only)</p>
            <p className="text-lg font-semibold font-mono">{directionalAccuracyNonFlat.toFixed(1)}%</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Directional Coverage</p>
            <p className="text-lg font-semibold font-mono">{directionalCoverage.toFixed(1)}%</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Avg Confidence</p>
            <p className="text-lg font-semibold font-mono">{m.avg_confidence_pct.toFixed(1)}%</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Samples</p>
            <p className="text-lg font-semibold font-mono">{m.samples.toLocaleString()}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">ECE / Brier</p>
            <p className="text-lg font-semibold font-mono">
              {m.ece_top1_pct === null ? "—" : `${m.ece_top1_pct.toFixed(1)}%`} /{" "}
              {m.multiclass_brier === null ? "—" : m.multiclass_brier.toFixed(3)}
            </p>
          </div>
          <div className="rounded-md border p-3 col-span-2">
            <p className="text-xs text-muted-foreground">Abstain Rate</p>
            <p className="text-lg font-semibold font-mono">
              {abstainRate.toFixed(1)}% ({m.abstain_count.toLocaleString()}/{m.predictions_total.toLocaleString()})
            </p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Provider: {m.provider} · Lookback: {m.lookback_hours}h · Horizon: {m.horizon_sec}s · Flat threshold:{" "}
          {m.flat_threshold_bps}bps
        </p>
      </CardContent>
    </Card>
  );
}

export default ShadowComparisonPanel;
