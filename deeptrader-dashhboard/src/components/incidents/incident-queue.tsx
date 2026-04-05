import { useMemo } from "react";
import { format, formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  XCircle,
  Info,
  CheckCircle2,
  Clock,
  ChevronRight,
  Loader2,
  User,
  Zap,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { ScrollArea } from "../ui/scroll-area";
import { cn } from "../../lib/utils";

const severityConfig = {
  critical: {
    icon: XCircle,
    color: "text-red-500",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
  },
  high: {
    icon: AlertTriangle,
    color: "text-orange-500",
    bg: "bg-orange-500/10",
    border: "border-orange-500/30",
  },
  medium: {
    icon: AlertTriangle,
    color: "text-amber-500",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
  },
  low: {
    icon: Info,
    color: "text-blue-500",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
  },
};

const statusConfig = {
  open: { label: "Open", color: "text-red-500", bg: "bg-red-500/10" },
  acknowledged: { label: "Ack'd", color: "text-amber-500", bg: "bg-amber-500/10" },
  investigating: { label: "Investigating", color: "text-blue-500", bg: "bg-blue-500/10" },
  mitigated: { label: "Mitigated", color: "text-cyan-500", bg: "bg-cyan-500/10" },
  resolved: { label: "Resolved", color: "text-emerald-500", bg: "bg-emerald-500/10" },
  closed: { label: "Closed", color: "text-muted-foreground", bg: "bg-muted/50" },
};

const actionConfig = {
  auto_pause: { label: "Paused", icon: Zap, color: "text-red-500" },
  throttle: { label: "Throttled", icon: Clock, color: "text-amber-500" },
  limit_clamp: { label: "Clamped", icon: AlertTriangle, color: "text-orange-500" },
  cancel_orders: { label: "Cancelled", icon: XCircle, color: "text-red-500" },
  close_positions: { label: "Closed", icon: CheckCircle2, color: "text-emerald-500" },
  none: { label: "None", icon: Info, color: "text-muted-foreground" },
};

interface Incident {
  id: string;
  incident_type: string;
  severity: string;
  status: string;
  title: string;
  description?: string;
  start_time: string;
  end_time?: string;
  affected_symbols?: string[];
  trigger_rule?: string;
  trigger_threshold?: number;
  trigger_actual?: number;
  action_taken?: string;
  pnl_impact?: number;
  owner_id?: string;
  acknowledged_by?: string;
}

interface IncidentQueueProps {
  incidents: Incident[];
  isLoading?: boolean;
  selectedId?: string | null;
  onSelect: (incident: Incident) => void;
}

export function IncidentQueue({
  incidents,
  isLoading,
  selectedId,
  onSelect,
}: IncidentQueueProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (incidents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <CheckCircle2 className="h-12 w-12 text-emerald-500/50 mb-4" />
        <p className="text-lg font-medium">No Incidents</p>
        <p className="text-sm text-muted-foreground">
          All clear! No incidents match the current filters.
        </p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-[calc(100vh-380px)]">
      {/* Added p-1 padding so the ring-2 selection highlight doesn't get clipped */}
      <div className="space-y-2 p-1 pr-4">
        {incidents.map((incident) => {
          const severity =
            severityConfig[incident.severity as keyof typeof severityConfig] ||
            severityConfig.medium;
          const status =
            statusConfig[incident.status as keyof typeof statusConfig] ||
            statusConfig.open;
          const action =
            actionConfig[incident.action_taken as keyof typeof actionConfig] ||
            actionConfig.none;
          const SeverityIcon = severity.icon;
          const ActionIcon = action.icon;

          const isSelected = selectedId === incident.id;
          const isOngoing = !incident.end_time || incident.status === "open";
          const duration = incident.start_time
            ? formatDistanceToNow(new Date(incident.start_time), { addSuffix: true })
            : "";

          return (
            <div
              key={incident.id}
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3 cursor-pointer transition-all",
                severity.border,
                isSelected
                  ? "ring-2 ring-primary bg-muted/50"
                  : "hover:bg-muted/30"
              )}
              onClick={() => onSelect(incident)}
            >
              {/* Severity Icon */}
              <div className={cn("rounded-lg p-2 shrink-0", severity.bg)}>
                <SeverityIcon className={cn("h-4 w-4", severity.color)} />
              </div>

              {/* Main Content */}
              <div className="flex-1 min-w-0">
                {/* Header Row */}
                <div className="flex items-center gap-2 mb-1">
                  <Badge
                    variant="outline"
                    className={cn("text-[10px] px-1.5 py-0", status.bg, status.color)}
                  >
                    {status.label}
                  </Badge>
                  {incident.action_taken && incident.action_taken !== "none" && (
                    <Badge
                      variant="outline"
                      className={cn("text-[10px] px-1.5 py-0 gap-1", action.color)}
                    >
                      <ActionIcon className="h-3 w-3" />
                      {action.label}
                    </Badge>
                  )}
                  {isOngoing && (
                    <span className="flex items-center gap-1 text-[10px] text-amber-500">
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                      Ongoing
                    </span>
                  )}
                </div>

                {/* Title */}
                <h4 className="font-medium text-sm truncate">{incident.title}</h4>

                {/* Metadata Row */}
                <div className="flex items-center gap-3 mt-1.5 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {duration}
                  </span>

                  {incident.trigger_rule && (
                    <span className="font-mono text-[10px] bg-muted px-1 rounded">
                      {incident.trigger_rule}
                    </span>
                  )}

                  {incident.pnl_impact !== undefined && incident.pnl_impact !== 0 && (
                    <span
                      className={cn(
                        "font-mono",
                        incident.pnl_impact < 0 ? "text-red-500" : "text-emerald-500"
                      )}
                    >
                      {incident.pnl_impact < 0 ? "-" : "+"}$
                      {Math.abs(incident.pnl_impact).toFixed(2)}
                    </span>
                  )}

                  {incident.owner_id && (
                    <span className="flex items-center gap-1">
                      <User className="h-3 w-3" />
                      {incident.owner_id.slice(0, 8)}
                    </span>
                  )}
                </div>

                {/* Symbols */}
                {incident.affected_symbols && incident.affected_symbols.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {incident.affected_symbols.slice(0, 3).map((symbol) => (
                      <Badge
                        key={symbol}
                        variant="outline"
                        className="text-[10px] px-1 py-0"
                      >
                        {symbol}
                      </Badge>
                    ))}
                    {incident.affected_symbols.length > 3 && (
                      <Badge
                        variant="outline"
                        className="text-[10px] px-1 py-0"
                      >
                        +{incident.affected_symbols.length - 3}
                      </Badge>
                    )}
                  </div>
                )}

                {/* Threshold vs Actual (on hover preview) */}
                {incident.trigger_threshold !== undefined &&
                  incident.trigger_actual !== undefined && (
                    <div className="mt-1.5 text-[10px] text-muted-foreground">
                      Threshold:{" "}
                      <span className="font-mono">
                        {incident.trigger_threshold}
                      </span>{" "}
                      vs Actual:{" "}
                      <span
                        className={cn(
                          "font-mono",
                          Math.abs(incident.trigger_actual) >
                            Math.abs(incident.trigger_threshold)
                            ? "text-red-500"
                            : "text-emerald-500"
                        )}
                      >
                        {incident.trigger_actual}
                      </span>
                    </div>
                  )}
              </div>

              {/* Chevron */}
              <ChevronRight
                className={cn(
                  "h-5 w-5 shrink-0 text-muted-foreground transition-colors",
                  isSelected && "text-primary"
                )}
              />
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}

export default IncidentQueue;

