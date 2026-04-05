/**
 * FilterEffectivenessMatrix - 2x2 confusion matrix showing filter outcomes
 */

import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { cn } from "../../lib/utils";
import { CheckCircle2, XCircle, Ban, Target } from "lucide-react";
import type { FilterEffectiveness } from "../../types/orderbookModel";

interface FilterEffectivenessMatrixProps {
  data: FilterEffectiveness | undefined;
  isLoading?: boolean;
}

function MatrixCell({
  value,
  label,
  sublabel,
  icon: Icon,
  variant,
}: {
  value: number;
  label: string;
  sublabel: string;
  icon: React.ElementType;
  variant: "good" | "bad" | "neutral";
}) {
  const colors = {
    good: "bg-emerald-500/10 border-emerald-500/30 text-emerald-600",
    bad: "bg-red-500/10 border-red-500/30 text-red-600",
    neutral: "bg-muted border-border text-muted-foreground",
  };

  return (
    <div
      className={cn(
        "p-4 rounded-lg border flex flex-col items-center justify-center text-center",
        colors[variant]
      )}
    >
      <Icon className="h-5 w-5 mb-2 opacity-70" />
      <span className="text-2xl font-bold">{value}</span>
      <span className="text-xs font-medium mt-1">{label}</span>
      <span className="text-[10px] opacity-70">{sublabel}</span>
    </div>
  );
}

function KPIBadge({
  label,
  value,
  unit,
  variant,
}: {
  label: string;
  value: string;
  unit?: string;
  variant?: "good" | "bad" | "neutral";
}) {
  const colors = {
    good: "text-emerald-600",
    bad: "text-red-600",
    neutral: "text-foreground",
  };

  return (
    <div className="flex flex-col items-center">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span className={cn("text-lg font-semibold", colors[variant ?? "neutral"])}>
        {value}
        {unit && <span className="text-xs ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}

export function FilterEffectivenessMatrix({ data, isLoading }: FilterEffectivenessMatrixProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Filter Effectiveness</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[200px] animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  const blockedBad = data?.blocked_bad ?? 0;
  const blockedGood = data?.blocked_good ?? 0;
  const allowedGood = data?.allowed_good ?? 0;
  const allowedBad = data?.allowed_bad ?? 0;

  const blockPrecision = data?.block_precision_pct ?? 0;
  const missRate = data?.miss_rate_pct ?? 0;
  const netSavings = data?.net_savings_bps ?? 0;

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium">
          Filter Effectiveness
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            ({data?.n_candidates ?? 0} candidates)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 2x2 Matrix */}
        <div className="grid grid-cols-2 gap-2">
          {/* Blocked + Bad = Good Block */}
          <MatrixCell
            value={blockedBad}
            label="Good Block"
            sublabel="Blocked bad trades"
            icon={CheckCircle2}
            variant="good"
          />
          {/* Blocked + Good = Missed Opportunity */}
          <MatrixCell
            value={blockedGood}
            label="Missed"
            sublabel="Blocked good trades"
            icon={Ban}
            variant="bad"
          />
          {/* Allowed + Good = Correct Allow */}
          <MatrixCell
            value={allowedGood}
            label="Good Allow"
            sublabel="Allowed winning trades"
            icon={Target}
            variant="good"
          />
          {/* Allowed + Bad = Should Have Blocked */}
          <MatrixCell
            value={allowedBad}
            label="Should Block"
            sublabel="Allowed losing trades"
            icon={XCircle}
            variant="bad"
          />
        </div>

        {/* KPIs */}
        <div className="flex justify-around pt-2 border-t">
          <KPIBadge
            label="Block Precision"
            value={blockPrecision.toFixed(1)}
            unit="%"
            variant={blockPrecision >= 70 ? "good" : blockPrecision < 50 ? "bad" : "neutral"}
          />
          <KPIBadge
            label="Miss Rate"
            value={missRate.toFixed(1)}
            unit="%"
            variant={missRate <= 10 ? "good" : missRate > 20 ? "bad" : "neutral"}
          />
          <KPIBadge
            label="Net Savings"
            value={netSavings >= 0 ? `+${netSavings.toFixed(1)}` : netSavings.toFixed(1)}
            unit="bps"
            variant={netSavings > 0 ? "good" : netSavings < 0 ? "bad" : "neutral"}
          />
        </div>
      </CardContent>
    </Card>
  );
}

