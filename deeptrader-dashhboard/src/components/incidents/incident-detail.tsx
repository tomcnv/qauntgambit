import { useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  XCircle,
  Info,
  CheckCircle2,
  Clock,
  User,
  Zap,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Download,
  Target,
  TrendingDown,
  Activity,
  Settings,
  FileText,
  Play,
  MessageSquare,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Textarea } from "../ui/textarea";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Separator } from "../ui/separator";
import { ScrollArea } from "../ui/scroll-area";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
} from "recharts";
import { cn } from "../../lib/utils";
import {
  useIncident,
  useIncidentTimeline,
  useIncidentEvidence,
  useAcknowledgeIncident,
  useResolveIncident,
  useUpdateIncidentStatus,
  useAddIncidentTimelineEvent,
  useExportIncident,
} from "../../lib/api/hooks";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";

const severityConfig = {
  critical: { icon: XCircle, color: "text-red-500", bg: "bg-red-500/10" },
  high: { icon: AlertTriangle, color: "text-orange-500", bg: "bg-orange-500/10" },
  medium: { icon: AlertTriangle, color: "text-amber-500", bg: "bg-amber-500/10" },
  low: { icon: Info, color: "text-blue-500", bg: "bg-blue-500/10" },
};

const statusConfig = {
  open: { label: "Open", color: "text-red-500", bg: "bg-red-500/10" },
  acknowledged: { label: "Acknowledged", color: "text-amber-500", bg: "bg-amber-500/10" },
  investigating: { label: "Investigating", color: "text-blue-500", bg: "bg-blue-500/10" },
  mitigated: { label: "Mitigated", color: "text-cyan-500", bg: "bg-cyan-500/10" },
  resolved: { label: "Resolved", color: "text-emerald-500", bg: "bg-emerald-500/10" },
  closed: { label: "Closed", color: "text-muted-foreground", bg: "bg-muted/50" },
};

const ROOT_CAUSE_OPTIONS = [
  { value: "market_regime", label: "Market Regime Change" },
  { value: "exchange_downtime", label: "Exchange Downtime / Issues" },
  { value: "config_change", label: "Configuration Change" },
  { value: "data_gap", label: "Data Gap / Quality Issue" },
  { value: "model_drift", label: "Model / Strategy Drift" },
  { value: "infrastructure", label: "Infrastructure Issue" },
  { value: "human_error", label: "Human Error" },
  { value: "external_event", label: "External Event" },
  { value: "unknown", label: "Unknown / Under Investigation" },
];

interface IncidentDetailProps {
  incidentId: string | null;
  onClose?: () => void;
}

export function IncidentDetail({ incidentId, onClose }: IncidentDetailProps) {
  const [activeTab, setActiveTab] = useState("summary");
  const [noteText, setNoteText] = useState("");
  const [resolutionNotes, setResolutionNotes] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [isActionsOpen, setIsActionsOpen] = useState(true);

  const { data: incidentData, isLoading } = useIncident(incidentId);
  const { data: timelineData } = useIncidentTimeline(incidentId);
  const { data: evidenceData } = useIncidentEvidence(incidentId);

  const acknowledgeIncident = useAcknowledgeIncident();
  const resolveIncident = useResolveIncident();
  const updateStatus = useUpdateIncidentStatus();
  const addTimelineEvent = useAddIncidentTimelineEvent();
  const exportIncident = useExportIncident();

  const incident = incidentData?.incident;
  const timeline = timelineData?.events || incident?.timeline || [];
  const evidence = evidenceData?.evidence;

  if (!incidentId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8">
        <FileText className="h-12 w-12 text-muted-foreground/50 mb-4" />
        <p className="text-lg font-medium">Select an Incident</p>
        <p className="text-sm text-muted-foreground">
          Choose an incident from the queue to view details
        </p>
      </div>
    );
  }

  if (isLoading || !incident) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  const severity = severityConfig[incident.severity as keyof typeof severityConfig] || severityConfig.medium;
  const status = statusConfig[incident.status as keyof typeof statusConfig] || statusConfig.open;
  const SeverityIcon = severity.icon;

  const handleAcknowledge = async () => {
    try {
      await acknowledgeIncident.mutateAsync(incident.id);
      toast.success("Incident acknowledged");
    } catch (error) {
      toast.error("Failed to acknowledge incident");
    }
  };

  const handleResolve = async () => {
    try {
      await resolveIncident.mutateAsync({
        incidentId: incident.id,
        resolutionNotes,
        rootCause,
      });
      toast.success("Incident resolved");
      setResolutionNotes("");
      setRootCause("");
    } catch (error) {
      toast.error("Failed to resolve incident");
    }
  };

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    try {
      await addTimelineEvent.mutateAsync({
        incidentId: incident.id,
        eventType: "note_added",
        eventData: { note: noteText },
      });
      toast.success("Note added");
      setNoteText("");
    } catch (error) {
      toast.error("Failed to add note");
    }
  };

  const handleExport = async (format: "json" | "csv") => {
    try {
      const data = await exportIncident.mutateAsync({ incidentId: incident.id, format });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `incident-${incident.id}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded");
    } catch (error) {
      toast.error("Failed to export incident");
    }
  };

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        {/* Summary Card */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className={cn("rounded-lg p-2", severity.bg)}>
                  <SeverityIcon className={cn("h-5 w-5", severity.color)} />
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className={cn("text-xs", status.bg, status.color)}>
                      {status.label}
                    </Badge>
                    <span className="font-mono text-xs text-muted-foreground">
                      {incident.id.slice(0, 8)}
                    </span>
                  </div>
                  <CardTitle className="text-lg">{incident.title}</CardTitle>
                </div>
              </div>
            </div>
            {incident.description && (
              <CardDescription className="mt-2">{incident.description}</CardDescription>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Time Info */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Started</p>
                <p className="text-sm font-medium">
                  {format(new Date(incident.start_time), "MMM d, HH:mm:ss")}
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatDistanceToNow(new Date(incident.start_time), { addSuffix: true })}
                </p>
              </div>
              {incident.end_time && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Ended</p>
                  <p className="text-sm font-medium">
                    {format(new Date(incident.end_time), "MMM d, HH:mm:ss")}
                  </p>
                </div>
              )}
            </div>

            {/* Trigger Details */}
            {incident.trigger_rule && (
              <div className="rounded-lg border p-3 bg-muted/30">
                <p className="text-xs text-muted-foreground mb-1">What Fired</p>
                <p className="text-sm font-medium font-mono">{incident.trigger_rule}</p>
                {incident.trigger_threshold !== undefined && incident.trigger_actual !== undefined && (
                  <p className="text-xs mt-1">
                    Threshold:{" "}
                    <span className="font-mono">{incident.trigger_threshold}</span>
                    {" → "}
                    Actual:{" "}
                    <span className={cn(
                      "font-mono",
                      Math.abs(incident.trigger_actual) > Math.abs(incident.trigger_threshold)
                        ? "text-red-500"
                        : "text-emerald-500"
                    )}>
                      {incident.trigger_actual}
                    </span>
                  </p>
                )}
              </div>
            )}

            {/* Impact Metrics */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg border p-3 text-center">
                <p className="text-xs text-muted-foreground mb-1">PnL Impact</p>
                <p className={cn(
                  "text-lg font-mono font-bold",
                  (incident.pnl_impact || 0) < 0 ? "text-red-500" : "text-emerald-500"
                )}>
                  ${(incident.pnl_impact || 0).toFixed(2)}
                </p>
              </div>
              <div className="rounded-lg border p-3 text-center">
                <p className="text-xs text-muted-foreground mb-1">Trades</p>
                <p className="text-lg font-mono font-bold">{incident.trades_affected || 0}</p>
              </div>
              <div className="rounded-lg border p-3 text-center">
                <p className="text-xs text-muted-foreground mb-1">Positions</p>
                <p className="text-lg font-mono font-bold">{incident.positions_affected || 0}</p>
              </div>
            </div>

            {/* Affected Symbols */}
            {incident.affected_symbols?.length > 0 && (
              <div>
                <p className="text-xs text-muted-foreground mb-2">Affected Symbols</p>
                <div className="flex flex-wrap gap-1">
                  {incident.affected_symbols.map((symbol: string) => (
                    <Badge key={symbol} variant="outline">
                      {symbol}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Tabs for Timeline / Evidence / Actions */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="w-full">
            <TabsTrigger value="summary" className="flex-1">Timeline</TabsTrigger>
            <TabsTrigger value="evidence" className="flex-1">Evidence</TabsTrigger>
            <TabsTrigger value="resolution" className="flex-1">Resolution</TabsTrigger>
          </TabsList>

          {/* Timeline Tab */}
          <TabsContent value="summary" className="space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Audit Timeline</CardTitle>
              </CardHeader>
              <CardContent>
                {timeline.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No events recorded yet.</p>
                ) : (
                  <div className="space-y-3">
                    {timeline.map((event: any, idx: number) => (
                      <div key={event.id || idx} className="flex gap-3">
                        <div className="flex flex-col items-center">
                          <div className="h-2 w-2 rounded-full bg-primary" />
                          {idx < timeline.length - 1 && (
                            <div className="w-px h-full bg-border" />
                          )}
                        </div>
                        <div className="flex-1 pb-3">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium capitalize">
                              {event.event_type?.replace(/_/g, " ")}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {format(new Date(event.created_at), "MMM d, HH:mm:ss")}
                            </span>
                          </div>
                          {event.actor && (
                            <p className="text-xs text-muted-foreground mt-0.5">
                              by {event.actor}
                            </p>
                          )}
                          {event.event_data?.note && (
                            <p className="text-sm mt-1 text-muted-foreground italic">
                              "{event.event_data.note}"
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Add Note */}
                <Separator className="my-4" />
                <div className="space-y-2">
                  <Label className="text-xs">Add Note</Label>
                  <Textarea
                    placeholder="Add investigation notes..."
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    className="min-h-[60px]"
                  />
                  <Button
                    size="sm"
                    onClick={handleAddNote}
                    disabled={!noteText.trim() || addTimelineEvent.isPending}
                  >
                    <MessageSquare className="h-4 w-4 mr-1" />
                    Add Note
                  </Button>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Evidence Tab */}
          <TabsContent value="evidence" className="space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">PnL During Incident</CardTitle>
              </CardHeader>
              <CardContent>
                {evidence?.pnlTimeline && evidence.pnlTimeline.length > 0 ? (
                  <div className="h-[200px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={evidence.pnlTimeline}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis
                          dataKey="timestamp"
                          tickFormatter={(t) => format(new Date(t), "HH:mm")}
                          fontSize={10}
                          stroke="hsl(var(--muted-foreground))"
                        />
                        <YAxis
                          tickFormatter={(v) => `$${v}`}
                          fontSize={10}
                          stroke="hsl(var(--muted-foreground))"
                        />
                        <RechartsTooltip
                          contentStyle={{
                            backgroundColor: "hsl(var(--card))",
                            border: "1px solid hsl(var(--border))",
                            borderRadius: "8px",
                          }}
                          formatter={(value: number) => [`$${value.toFixed(2)}`, "PnL"]}
                        />
                        <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
                        <Area
                          type="monotone"
                          dataKey="cumulativePnl"
                          stroke="hsl(var(--primary))"
                          fill="hsl(var(--primary))"
                          fillOpacity={0.2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No PnL data available for this period.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Exposure During Incident</CardTitle>
              </CardHeader>
              <CardContent>
                {evidence?.exposureTimeline && evidence.exposureTimeline.length > 0 ? (
                  <div className="h-[200px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={evidence.exposureTimeline}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis
                          dataKey="timestamp"
                          tickFormatter={(t) => format(new Date(t), "HH:mm")}
                          fontSize={10}
                          stroke="hsl(var(--muted-foreground))"
                        />
                        <YAxis
                          tickFormatter={(v) => `$${v}`}
                          fontSize={10}
                          stroke="hsl(var(--muted-foreground))"
                        />
                        <RechartsTooltip
                          contentStyle={{
                            backgroundColor: "hsl(var(--card))",
                            border: "1px solid hsl(var(--border))",
                            borderRadius: "8px",
                          }}
                          formatter={(value: number) => [`$${value.toFixed(0)}`, "Exposure"]}
                        />
                        <Line
                          type="stepAfter"
                          dataKey="exposure"
                          stroke="hsl(var(--destructive))"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No exposure data available for this period.</p>
                )}
              </CardContent>
            </Card>

            {/* Affected Objects */}
            {(incident.affectedPositions?.length > 0 || incident.affectedOrders?.length > 0) && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Affected Objects</CardTitle>
                </CardHeader>
                <CardContent>
                  {incident.affectedPositions?.length > 0 && (
                    <div className="mb-4">
                      <p className="text-xs text-muted-foreground mb-2">Positions ({incident.affectedPositions.length})</p>
                      <div className="text-xs space-y-1">
                        {incident.affectedPositions.slice(0, 5).map((pos: any) => (
                          <div key={pos.id} className="flex justify-between">
                            <span>{pos.symbol} {pos.side}</span>
                            <span className={pos.pnl_impact < 0 ? "text-red-500" : "text-emerald-500"}>
                              ${pos.pnl_impact?.toFixed(2)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {incident.affectedOrders?.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">Orders ({incident.affectedOrders.length})</p>
                      <div className="text-xs space-y-1">
                        {incident.affectedOrders.slice(0, 5).map((order: any) => (
                          <div key={order.id} className="flex justify-between">
                            <span>{order.symbol} {order.side}</span>
                            <span className="text-muted-foreground">{order.reject_reason || "Filled"}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Resolution Tab */}
          <TabsContent value="resolution" className="space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Root Cause & Resolution</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label className="text-xs">Suspected Root Cause</Label>
                  <Select value={rootCause} onValueChange={setRootCause}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select root cause..." />
                    </SelectTrigger>
                    <SelectContent>
                      {ROOT_CAUSE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label className="text-xs">Resolution Notes</Label>
                  <Textarea
                    placeholder="Describe the resolution and any follow-up actions..."
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                    className="min-h-[100px]"
                  />
                </div>

                {incident.status !== "resolved" && incident.status !== "closed" && (
                  <Button
                    onClick={handleResolve}
                    disabled={resolveIncident.isPending}
                    className="w-full"
                  >
                    <CheckCircle2 className="h-4 w-4 mr-1" />
                    Resolve Incident
                  </Button>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Actions */}
        <Collapsible open={isActionsOpen} onOpenChange={setIsActionsOpen}>
          <Card>
            <CollapsibleTrigger asChild>
              <CardHeader className="pb-2 cursor-pointer hover:bg-muted/30 transition-colors">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">Quick Actions</CardTitle>
                  {isActionsOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </div>
              </CardHeader>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <CardContent className="space-y-2">
                {incident.status === "open" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-start"
                    onClick={handleAcknowledge}
                    disabled={acknowledgeIncident.isPending}
                  >
                    <CheckCircle2 className="h-4 w-4 mr-2" />
                    Acknowledge Incident
                  </Button>
                )}

                <Link to="/analysis/replay">
                  <Button variant="outline" size="sm" className="w-full justify-start">
                    <Play className="h-4 w-4 mr-2" />
                    Create Replay Session
                  </Button>
                </Link>

                <Link to="/dashboard/risk/limits">
                  <Button variant="outline" size="sm" className="w-full justify-start">
                    <Settings className="h-4 w-4 mr-2" />
                    View Guardrail Rules
                  </Button>
                </Link>

                <Button
                  variant="outline"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => handleExport("json")}
                >
                  <Download className="h-4 w-4 mr-2" />
                  Export Incident Bundle
                </Button>
              </CardContent>
            </CollapsibleContent>
          </Card>
        </Collapsible>
      </div>
    </ScrollArea>
  );
}

export default IncidentDetail;

