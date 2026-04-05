/**
 * ProfileScorePanel - Live profile scores with eligibility gating.
 */

import { Activity, CheckCircle2, Info, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import type { ProfileRouterResponse, ProfileScoreEntry } from "../../lib/api/types";

interface ProfileScorePanelProps {
  routerData: ProfileRouterResponse | null | undefined;
  isLoading?: boolean;
  className?: string;
}

function EligibilityBadge({ eligible }: { eligible: boolean }) {
  if (eligible) {
    return (
      <Badge variant="outline" className="text-[10px] text-emerald-500 border-emerald-500/30">
        <CheckCircle2 className="mr-1 h-3 w-3" /> eligible
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[10px] text-rose-500 border-rose-500/30">
      <XCircle className="mr-1 h-3 w-3" /> blocked
    </Badge>
  );
}

function ScoreRow({ entry }: { entry: ProfileScoreEntry }) {
  const eligible = entry.eligible !== false;
  const reasons = entry.eligibility_reasons?.length
    ? entry.eligibility_reasons.join(", ")
    : "eligible";
  const adjustedScore = entry.adjusted_score ?? entry.score;
  const qualityScore = entry.data_quality_score;
  const riskBias = entry.risk_bias_multiplier;
  const detailParts: string[] = [`score ${entry.score.toFixed(3)}`, `conf ${entry.confidence.toFixed(3)}`];
  if (qualityScore !== undefined && qualityScore !== null) {
    detailParts.push(`quality ${qualityScore.toFixed(2)}`);
  }
  if (riskBias !== undefined && riskBias !== null) {
    detailParts.push(`risk ${riskBias.toFixed(2)}x`);
  }

  return (
    <div className="flex items-center justify-between gap-3 py-1 text-xs">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{entry.profile_id}</span>
          <EligibilityBadge eligible={eligible} />
        </div>
        <div className="text-[10px] text-muted-foreground truncate">{reasons}</div>
      </div>
      <div className="text-right font-mono">
        <div className={cn("text-xs font-medium", eligible ? "text-emerald-500" : "text-rose-500")}>
          {adjustedScore.toFixed(3)}
        </div>
        <div className="text-[10px] text-muted-foreground">
          {detailParts.join(" · ")}
        </div>
      </div>
    </div>
  );
}

export function ProfileScorePanel({ routerData, isLoading, className }: ProfileScorePanelProps) {
  const scores = routerData?.last_scores ?? [];
  const selected = routerData?.selected_profile_id;
  const symbol = routerData?.symbol;

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Profile Scores</CardTitle>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            {symbol ? <span>{symbol}</span> : null}
            {selected ? (
              <Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-500">
                selected: {selected}
              </Badge>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Activity className="h-5 w-5 animate-pulse text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading scores...</span>
          </div>
        ) : scores.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <Info className="h-6 w-6 text-muted-foreground/50 mb-2" />
            <p className="text-sm text-muted-foreground">No live profile scores yet</p>
            <p className="text-[10px] text-muted-foreground/70 mt-1">
              Router scores appear after the first decision cycle.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {scores.slice(0, 8).map((entry) => (
              <ScoreRow key={entry.profile_id} entry={entry} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
