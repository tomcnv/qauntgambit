import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";

interface Suggestion {
  param: string;
  current: string | number;
  suggested: string | number;
  reason: string;
  confidence?: number;
}

interface ParamSuggestionsProps {
  data: {
    timestamp: number;
    stats: { trade_count: number; win_rate: number; total_pnl_pct: number };
    suggestions: {
      suggestions?: Suggestion[];
      overall_assessment?: string;
      confidence?: number;
    };
  };
  className?: string;
}

function timeAgo(ts: number) {
  const sec = Math.floor(Date.now() / 1000 - ts);
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export function ParamSuggestionsPanel({ data, className }: ParamSuggestionsProps) {
  const suggestions = data?.suggestions?.suggestions || [];
  const assessment = data?.suggestions?.overall_assessment;
  const confidence = data?.suggestions?.confidence;
  const stats = data?.stats;

  if (!suggestions.length && !assessment) return null;

  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">AI Param Tuner</span>
          {stats && (
            <Badge variant="secondary">
              {stats.trade_count} trades · {((stats.win_rate || 0) * 100).toFixed(0)}% WR · {(stats.total_pnl_pct || 0).toFixed(2)}% PnL
            </Badge>
          )}
          {confidence != null && (
            <Badge variant={confidence >= 0.7 ? "default" : "outline"}>
              {(confidence * 100).toFixed(0)}% confidence
            </Badge>
          )}
        </div>
        <span className="text-xs text-muted-foreground">{timeAgo(data.timestamp)}</span>
      </div>

      {assessment && (
        <p className="text-xs text-muted-foreground mb-3 leading-relaxed">{assessment}</p>
      )}

      {suggestions.length > 0 && (
        <div className="space-y-2">
          {suggestions.map((s: Suggestion, i: number) => (
            <div key={i} className="flex items-center gap-3 p-2 rounded-md bg-muted/50 text-xs">
              <span className="font-mono font-medium min-w-[180px]">{s.param}</span>
              <span className="text-muted-foreground">{String(s.current)}</span>
              <span className="text-muted-foreground">→</span>
              <span className="font-medium text-blue-500">{String(s.suggested)}</span>
              <span className="text-muted-foreground flex-1 truncate">{s.reason}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
