import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";

interface SentimentEntry {
  symbol?: string;
  score: number;
  summary: string;
  timestamp: number;
}

interface SentimentPanelProps {
  sentiment: Record<string, SentimentEntry>;
  className?: string;
}

function scoreColor(score: number) {
  if (score >= 0.3) return "text-emerald-500";
  if (score >= 0.1) return "text-emerald-400";
  if (score > -0.1) return "text-muted-foreground";
  if (score > -0.3) return "text-orange-400";
  return "text-red-500";
}

function scoreLabel(score: number) {
  if (score >= 0.5) return "Strong Bull";
  if (score >= 0.2) return "Bullish";
  if (score > -0.2) return "Neutral";
  if (score > -0.5) return "Bearish";
  return "Strong Bear";
}

function scoreBadgeVariant(score: number): "default" | "secondary" | "destructive" | "outline" {
  if (score >= 0.2) return "default";
  if (score > -0.2) return "secondary";
  return "destructive";
}

function ScoreBar({ score }: { score: number }) {
  // Map -1..+1 to 0..100%
  const pct = ((score + 1) / 2) * 100;
  return (
    <div className="relative h-2 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={cn(
          "absolute top-0 left-0 h-full rounded-full transition-all",
          score >= 0.2 ? "bg-emerald-500" : score > -0.2 ? "bg-yellow-500" : "bg-red-500"
        )}
        style={{ width: `${pct}%` }}
      />
      {/* Center marker */}
      <div className="absolute top-0 left-1/2 h-full w-px bg-foreground/30" />
    </div>
  );
}

function timeAgo(ts: number) {
  const sec = Math.floor(Date.now() / 1000 - ts);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

export function SentimentPanel({ sentiment, className }: SentimentPanelProps) {
  const hasData = sentiment && Object.keys(sentiment).length > 0;

  if (!hasData) {
    return (
      <Card className={cn("p-4", className)}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-sm font-semibold">AI Sentiment</span>
          <Badge variant="outline">Waiting for data…</Badge>
        </div>
        <p className="text-xs text-muted-foreground">Sentiment analysis will appear here once available.</p>
      </Card>
    );
  }

  const global = sentiment.global;
  const symbols = Object.entries(sentiment).filter(([k]) => k !== "global");

  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">AI Sentiment</span>
          {global && (
            <Badge variant={scoreBadgeVariant(global.score)}>
              Market: {global.score > 0 ? "+" : ""}{global.score.toFixed(1)} · {scoreLabel(global.score)}
            </Badge>
          )}
        </div>
        {global && (
          <span className="text-xs text-muted-foreground">{timeAgo(global.timestamp)}</span>
        )}
      </div>

      {global?.summary && (
        <p className="text-xs text-muted-foreground mb-3 leading-relaxed">{global.summary}</p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {symbols.map(([sym, data]) => (
          <Tooltip key={sym}>
            <TooltipTrigger asChild>
              <div className="flex flex-col gap-1.5 p-2 rounded-md bg-muted/50">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{sym}</span>
                  <span className={cn("text-sm font-bold tabular-nums", scoreColor(data.score))}>
                    {data.score > 0 ? "+" : ""}{data.score.toFixed(1)}
                  </span>
                </div>
                <ScoreBar score={data.score} />
                <span className="text-[10px] text-muted-foreground truncate">{data.summary}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              <p className="text-xs">{data.summary}</p>
              <p className="text-[10px] text-muted-foreground mt-1">{timeAgo(data.timestamp)}</p>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </Card>
  );
}
