/**
 * Safety Events Panel
 *
 * Combined view of kill switch and position guard events.
 * Shows recent safety-related activity for operational awareness.
 */

import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Shield,
  ShieldAlert,
  Target,
  Timer,
  TrendingDown,
  RefreshCw,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Skeleton } from "../ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { useSafetyEvents } from "../../lib/api/quant-hooks";

function formatRelativeTime(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;

  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatPnL(pnl: number | undefined): string {
  if (pnl === undefined || pnl === null) return "";
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}$${pnl.toFixed(2)}`;
}

const GUARD_ICONS: Record<string, React.ReactNode> = {
  trailing_stop_hit: <TrendingDown className="h-3.5 w-3.5 text-amber-500" />,
  stop_loss_hit: <ShieldAlert className="h-3.5 w-3.5 text-red-500" />,
  take_profit_hit: <Target className="h-3.5 w-3.5 text-emerald-500" />,
  max_age_exceeded: <Timer className="h-3.5 w-3.5 text-blue-500" />,
};

const GUARD_LABELS: Record<string, string> = {
  trailing_stop_hit: "Trailing Stop",
  stop_loss_hit: "Stop Loss",
  take_profit_hit: "Take Profit",
  max_age_exceeded: "Max Age",
  trigger: "Kill Switch Triggered",
  reset: "Kill Switch Reset",
};

interface SafetyEventsPanelProps {
  className?: string;
  limit?: number;
}

export function SafetyEventsPanel({ className, limit = 15 }: SafetyEventsPanelProps) {
  const { data, isLoading, error, refetch } = useSafetyEvents(limit);

  const events = data?.events || [];

  // Count by type for badges
  const killSwitchCount = events.filter((e) => e.type === "kill_switch").length;
  const guardCount = events.filter((e) => e.type === "guard").length;

  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-lg">Safety Events</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {killSwitchCount > 0 && (
              <Badge variant="destructive" className="text-xs">
                {killSwitchCount} kill switch
              </Badge>
            )}
            {guardCount > 0 && (
              <Badge variant="outline" className="text-xs">
                {guardCount} guards
              </Badge>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => refetch()}
                >
                  <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Refresh events</TooltipContent>
            </Tooltip>
          </div>
        </div>
        <CardDescription>Kill switch and position guard activity</CardDescription>
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : error ? (
          <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30">
            <p className="text-sm text-red-600">Failed to load safety events</p>
          </div>
        ) : events.length === 0 ? (
          <div className="py-8 text-center">
            <Shield className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">No recent safety events</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Events will appear here when guards trigger or kill switch activates
            </p>
          </div>
        ) : (
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
            {events.map((event, idx) => (
              <div
                key={idx}
                className={cn(
                  "flex items-start gap-3 p-2.5 rounded-lg transition-colors",
                  event.type === "kill_switch" && event.subtype === "trigger"
                    ? "bg-red-500/10 border border-red-500/20"
                    : event.type === "kill_switch" && event.subtype === "reset"
                      ? "bg-emerald-500/10 border border-emerald-500/20"
                      : event.subtype === "take_profit_hit"
                        ? "bg-emerald-500/5 border border-emerald-500/10"
                        : "bg-muted/30 border border-transparent"
                )}
              >
                {/* Icon */}
                <div className="shrink-0 mt-0.5">
                  {event.type === "kill_switch" ? (
                    event.subtype === "trigger" ? (
                      <AlertTriangle className="h-4 w-4 text-red-500" />
                    ) : (
                      <CheckCircle className="h-4 w-4 text-emerald-500" />
                    )
                  ) : (
                    GUARD_ICONS[event.subtype] || (
                      <Shield className="h-3.5 w-3.5 text-muted-foreground" />
                    )
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {event.type === "kill_switch" ? (
                        <>
                          <span
                            className={
                              event.subtype === "trigger" ? "text-red-600" : "text-emerald-600"
                            }
                          >
                            {GUARD_LABELS[event.subtype] || event.subtype}
                          </span>
                          {event.trigger && (
                            <span className="text-muted-foreground font-normal">
                              {" "}
                              — {event.trigger}
                            </span>
                          )}
                          {event.operator_id && (
                            <span className="text-muted-foreground font-normal">
                              {" "}
                              by {event.operator_id}
                            </span>
                          )}
                        </>
                      ) : (
                        <>
                          <span className="text-foreground">{event.symbol}</span>
                          <span className="text-muted-foreground font-normal">
                            {" "}
                            — {GUARD_LABELS[event.subtype] || event.subtype.replace(/_/g, " ")}
                          </span>
                        </>
                      )}
                    </span>

                    {/* P&L badge for guard events */}
                    {event.type === "guard" && event.realized_pnl !== undefined && (
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-xs shrink-0",
                          event.realized_pnl >= 0
                            ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/30"
                            : "bg-red-500/10 text-red-600 border-red-500/30"
                        )}
                      >
                        {formatPnL(event.realized_pnl)}
                      </Badge>
                    )}
                  </div>

                  {/* Side info for guard events */}
                  {event.type === "guard" && event.side && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {event.side} position closed
                    </p>
                  )}

                  {/* Message for kill switch */}
                  {event.type === "kill_switch" && event.message && (
                    <p className="text-xs text-muted-foreground mt-0.5 truncate">{event.message}</p>
                  )}
                </div>

                {/* Timestamp */}
                <div className="shrink-0 text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {formatRelativeTime(event.timestamp)}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default SafetyEventsPanel;
