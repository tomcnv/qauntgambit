import { useState, useMemo } from "react";
import { format, subDays } from "date-fns";
import {
  Siren,
  Settings,
  Download,
  Plus,
  RefreshCw,
  ExternalLink,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Separator } from "../../components/ui/separator";
import { TooltipProvider } from "../../components/ui/tooltip";
import { cn } from "../../lib/utils";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import { RunBar } from "../../components/run-bar";
import { OperationalSnapshot } from "../../components/incidents/operational-snapshot";
import { IncidentQueue } from "../../components/incidents/incident-queue";
import { IncidentFilters, IncidentFiltersState } from "../../components/incidents/incident-filters";
import { IncidentDetail } from "../../components/incidents/incident-detail";
import { useScopeStore } from "../../store/scope-store";
import {
  useIncidents,
  useIncidentSnapshot,
  useCreateIncident,
  useOverviewData,
} from "../../lib/api/hooks";

const INCIDENT_TYPES = [
  { value: "daily_loss_breach", label: "Daily Loss Breach" },
  { value: "drawdown_breach", label: "Drawdown Breach" },
  { value: "exposure_breach", label: "Exposure Breach" },
  { value: "leverage_breach", label: "Leverage Breach" },
  { value: "rapid_loss", label: "Rapid Loss" },
  { value: "connectivity_loss", label: "Connectivity Loss" },
  { value: "slippage_spike", label: "Slippage Spike" },
  { value: "manual_pause", label: "Manual Pause" },
  { value: "kill_switch", label: "Kill Switch" },
];

export default function RiskIncidentsPage() {
  const queryClient = useQueryClient();
  const { scopeLevel, exchangeAccountId, botId } = useScopeStore();

  // State
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [filters, setFilters] = useState<IncidentFiltersState>({
    startDate: format(subDays(new Date(), 7), "yyyy-MM-dd"),
    endDate: format(new Date(), "yyyy-MM-dd"),
  });
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [newIncident, setNewIncident] = useState({
    title: "",
    description: "",
    incidentType: "",
    severity: "medium",
  });

  // Data fetching
  const { data: overviewData } = useOverviewData({
    exchangeAccountId: scopeLevel === "exchange" ? exchangeAccountId : null,
    botId: scopeLevel === "bot" ? botId : null,
  });
  const { data: snapshotData } = useIncidentSnapshot({
    exchangeAccountId: scopeLevel === "exchange" ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel === "bot" ? botId ?? undefined : undefined,
  });

  const { data: incidentsData, isLoading, refetch } = useIncidents({
    exchangeAccountId: scopeLevel === "exchange" ? exchangeAccountId ?? undefined : undefined,
    botId: scopeLevel === "bot" ? botId ?? undefined : undefined,
    severity: filters.severity?.join(","),
    status: filters.status?.join(","),
    incidentType: filters.incidentType?.join(","),
    triggerRule: filters.triggerRule,
    search: filters.search,
    startDate: filters.startDate,
    endDate: filters.endDate,
    causedPause: filters.causedPause,
    limit: 100,
  });

  const createIncident = useCreateIncident();

  // Derived state
  const incidents = incidentsData?.incidents || [];
  const snapshot = snapshotData?.snapshot;
  const fastScalper = overviewData?.fastScalper as any;
  const tradingPaused = fastScalper?.trading_paused ?? fastScalper?.tradingPaused ?? false;
  const botRunning = fastScalper?.status === "running" || fastScalper?.isActive;

  // Get status display
  const statusDisplay = useMemo(() => {
    if (!botRunning) return { label: "Stopped", variant: "secondary" as const };
    if (tradingPaused) return { label: "Auto-Paused", variant: "destructive" as const };
    return { label: "Running", variant: "default" as const };
  }, [botRunning, tradingPaused]);

  // Handle incident selection from snapshot tiles
  const handleSnapshotFilterChange = (filter: { severity?: string; type?: string; causedPause?: boolean }) => {
    if (filter.causedPause) {
      setFilters((prev) => ({ ...prev, causedPause: true }));
    } else if (filter.severity) {
      setFilters((prev) => ({ ...prev, severity: [filter.severity!] }));
    } else if (filter.type) {
      setFilters((prev) => ({ ...prev, incidentType: [filter.type!] }));
    }
  };

  // Handle create incident
  const handleCreateIncident = async () => {
    if (!newIncident.title || !newIncident.incidentType) {
      toast.error("Title and type are required");
      return;
    }

    try {
      await createIncident.mutateAsync({
        title: newIncident.title,
        description: newIncident.description,
        incidentType: newIncident.incidentType,
        severity: newIncident.severity,
        exchangeAccountId: scopeLevel === "exchange" ? exchangeAccountId ?? undefined : undefined,
        botId: scopeLevel === "bot" ? botId ?? undefined : undefined,
      });
      toast.success("Incident created");
      setIsCreateDialogOpen(false);
      setNewIncident({ title: "", description: "", incidentType: "", severity: "medium" });
    } catch (error) {
      toast.error("Failed to create incident");
    }
  };

  // Handle refresh
  const handleRefresh = () => {
    refetch();
    queryClient.invalidateQueries({ queryKey: ["incident-snapshot"] });
    toast.success("Refreshed");
  };

  return (
    <TooltipProvider>
      <RunBar variant="full" />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="flex items-center gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold tracking-tight">Risk Incidents</h1>
                <Badge variant={statusDisplay.variant}>{statusDisplay.label}</Badge>
                {snapshot?.activeIncidents?.total > 0 && (
                  <Badge variant="destructive" className="gap-1">
                    <Siren className="h-3 w-3" />
                    {snapshot.activeIncidents.total} Active
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                Detect, triage, and resolve trading incidents. View breaches, auto-pauses, and post-mortems.
              </p>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleRefresh}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Refresh
            </Button>

            <Button variant="outline" size="sm" onClick={() => setIsCreateDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-1" />
              Create Incident
            </Button>

            <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Create Manual Incident</DialogTitle>
                  <DialogDescription>
                    Create an incident for post-mortem analysis or to track an issue.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label>Title</Label>
                    <Input
                      placeholder="Brief description of the incident..."
                      value={newIncident.title}
                      onChange={(e) => setNewIncident((p) => ({ ...p, title: e.target.value }))}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Type</Label>
                      <Select
                        value={newIncident.incidentType}
                        onValueChange={(v) => setNewIncident((p) => ({ ...p, incidentType: v }))}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select type..." />
                        </SelectTrigger>
                        <SelectContent>
                          {INCIDENT_TYPES.map((type) => (
                            <SelectItem key={type.value} value={type.value}>
                              {type.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Severity</Label>
                      <Select
                        value={newIncident.severity}
                        onValueChange={(v) => setNewIncident((p) => ({ ...p, severity: v }))}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="low">Low</SelectItem>
                          <SelectItem value="medium">Medium</SelectItem>
                          <SelectItem value="high">High</SelectItem>
                          <SelectItem value="critical">Critical</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>Description</Label>
                    <Textarea
                      placeholder="Detailed description of what happened..."
                      value={newIncident.description}
                      onChange={(e) => setNewIncident((p) => ({ ...p, description: e.target.value }))}
                    />
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleCreateIncident} disabled={createIncident.isPending}>
                    Create Incident
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            <Link to="/dashboard/risk/limits">
              <Button variant="outline" size="sm">
                <Settings className="h-4 w-4 mr-1" />
                Configure Guardrails
              </Button>
            </Link>
          </div>
        </div>

        {/* Operational Snapshot Strip */}
        <OperationalSnapshot
          onFilterChange={handleSnapshotFilterChange}
          activeFilter={{
            severity: filters.severity?.[0],
            type: filters.incidentType?.[0],
          }}
        />

        {/* Filters Bar */}
        <div className="flex items-center justify-between gap-4">
          <IncidentFilters filters={filters} onFiltersChange={setFilters} />
          <div className="text-sm text-muted-foreground">
            {incidents.length} incident{incidents.length !== 1 ? "s" : ""}
            {filters.search && ` matching "${filters.search}"`}
          </div>
        </div>

        {/* Main Split View */}
        <div className="grid gap-6 lg:grid-cols-5">
          {/* Left Panel: Incident Queue (40%) */}
          <div className="lg:col-span-2 space-y-4">
            <Card className="h-[calc(100vh-480px)] min-h-[400px] flex flex-col">
              <CardHeader className="pb-3 flex-shrink-0">
                <CardTitle className="text-base font-medium">Incident Queue</CardTitle>
              </CardHeader>
              <Separator />
              <CardContent className="flex-1 overflow-hidden pt-4">
                <IncidentQueue
                  incidents={incidents}
                  isLoading={isLoading}
                  selectedId={selectedIncidentId}
                  onSelect={(incident) => setSelectedIncidentId(incident.id)}
                />
              </CardContent>
            </Card>
          </div>

          {/* Right Panel: Incident Detail (60%) */}
          <div className="lg:col-span-3">
            <Card className="h-[calc(100vh-480px)] min-h-[400px]">
              <IncidentDetail
                incidentId={selectedIncidentId}
                onClose={() => setSelectedIncidentId(null)}
              />
            </Card>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
