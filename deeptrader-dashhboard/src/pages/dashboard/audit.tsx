import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  useAuditLog,
  useDecisionTrace,
  useDecisionTraces,
} from "../../lib/api/hooks";
import { exportAuditLog } from "../../lib/api/client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "../../lib/utils";
import {
  FileText,
  Download,
  Search,
  Filter,
  Loader2,
  Eye,
  AlertCircle,
  CheckCircle,
  XCircle,
  Info,
} from "lucide-react";
import toast from "react-hot-toast";
import { DashBar } from "../../components/DashBar";

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "critical":
      return "border-red-400/30 bg-red-500/10 text-red-300";
    case "error":
      return "border-orange-400/30 bg-orange-500/10 text-orange-300";
    case "warning":
      return "border-yellow-400/30 bg-yellow-500/10 text-yellow-300";
    default:
      return "border-blue-400/30 bg-blue-500/10 text-blue-300";
  }
};

const getSeverityIcon = (severity: string) => {
  switch (severity) {
    case "critical":
    case "error":
      return <XCircle className="h-4 w-4" />;
    case "warning":
      return <AlertCircle className="h-4 w-4" />;
    default:
      return <Info className="h-4 w-4" />;
  }
};

export default function AuditLogPage() {
  const [filters, setFilters] = useState({
    actionType: "",
    actionCategory: "",
    severity: "",
    startDate: "",
    endDate: "",
    limit: 100,
  });

  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [traceSearch, setTraceSearch] = useState("");

  const queryClient = useQueryClient();

  const { data: auditData, isLoading } = useAuditLog(filters);
  const { data: traceData } = useDecisionTrace(selectedTraceId || "");
  const { data: tracesData } = useDecisionTraces({
    tradeId: traceSearch || undefined,
    limit: 10,
  });

  const auditEntries = auditData?.data || [];
  const traces = tracesData?.data || [];

  const exportMutation = useMutation({
    mutationFn: exportAuditLog,
    onSuccess: (data) => {
      toast.success(`Export completed: ${data.export.fileName}`);
      // In a real app, you'd trigger a download here
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to export audit log");
    },
  });

  const handleExport = () => {
    exportMutation.mutate({
      format: "json",
      startDate: filters.startDate || undefined,
      endDate: filters.endDate || undefined,
      actionType: filters.actionType || undefined,
      actionCategory: filters.actionCategory || undefined,
      severity: filters.severity || undefined,
    });
  };

  if (selectedTraceId && traceData?.trace) {
    const trace = traceData.trace;
    return (
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <Button variant="ghost" size="sm" onClick={() => setSelectedTraceId(null)} className="mb-2">
              ← Back to Audit Log
            </Button>
            <h1 className="text-2xl font-bold tracking-tight">Decision Trace</h1>
            <p className="text-sm text-muted-foreground">
              Detailed inspection of trading decision
            </p>
          </div>
        </div>

        <Card className="border-border">
          <CardHeader>
            <CardTitle>Trade ID: {String(trace.trade_id || "—")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Symbol</p>
                <p className="mt-1 text-white">{String(trace.symbol || "—")}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Decision Type</p>
                <p className="mt-1 text-white">{String(trace.decision_type || "—")}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Outcome</p>
                <Badge className={trace.decision_outcome === "approved" ? "bg-emerald-500/10 text-emerald-300" : "bg-red-500/10 text-red-300"}>
                  {String(trace.decision_outcome || "—")}
                </Badge>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Timestamp</p>
                <p className="mt-1 text-white">{new Date(trace.timestamp).toLocaleString()}</p>
              </div>
            </div>

            {trace.stage_results && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">Stage Results</p>
                <pre className="rounded-lg border border-border bg-muted p-4 text-xs text-white overflow-auto">
                  {typeof trace.stage_results === 'string' 
                    ? trace.stage_results 
                    : JSON.stringify(trace.stage_results, null, 2)}
                </pre>
              </div>
            )}

            {trace.rejection_reasons && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">Rejection Reasons</p>
                <pre className="rounded-lg border border-border bg-muted p-4 text-xs text-white overflow-auto">
                  {typeof trace.rejection_reasons === 'string'
                    ? trace.rejection_reasons
                    : JSON.stringify(trace.rejection_reasons, null, 2)}
                </pre>
              </div>
            )}

            {trace.signal_data && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">Signal Data</p>
                <pre className="rounded-lg border border-border bg-muted p-4 text-xs text-white overflow-auto">
                  {typeof trace.signal_data === 'string'
                    ? trace.signal_data
                    : JSON.stringify(trace.signal_data, null, 2)}
                </pre>
              </div>
            )}

            {trace.market_context && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">Market Context</p>
                <pre className="rounded-lg border border-border bg-muted p-4 text-xs text-white overflow-auto">
                  {typeof trace.market_context === 'string'
                    ? trace.market_context
                    : JSON.stringify(trace.market_context, null, 2)}
                </pre>
              </div>
            )}

            {trace.final_decision && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">Final Decision</p>
                <pre className="rounded-lg border border-border bg-muted p-4 text-xs text-white overflow-auto">
                  {typeof trace.final_decision === 'string'
                    ? trace.final_decision
                    : JSON.stringify(trace.final_decision, null, 2)}
                </pre>
              </div>
            )}

            {trace.execution_result && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">Execution Result</p>
                <pre className="rounded-lg border border-border bg-muted p-4 text-xs text-white overflow-auto">
                  {typeof trace.execution_result === 'string'
                    ? trace.execution_result
                    : JSON.stringify(trace.execution_result, null, 2)}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <>
      <DashBar />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Audit Log</h1>
          <p className="text-sm text-muted-foreground">
            Comprehensive audit trail and decision traces
          </p>
        </div>
        <Button onClick={handleExport} disabled={exportMutation.isPending}>
          {exportMutation.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Download className="mr-2 h-4 w-4" />
          )}
          Export
        </Button>
      </div>

      {/* Filters */}
      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-5">
            <div className="space-y-2">
              <Label htmlFor="actionType">Action Type</Label>
              <Input
                id="actionType"
                placeholder="e.g., config_change"
                value={filters.actionType}
                onChange={(e) => setFilters({ ...filters, actionType: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="actionCategory">Category</Label>
              <Select
                options={[
                  { value: "", label: "All" },
                  { value: "config", label: "Config" },
                  { value: "trading", label: "Trading" },
                  { value: "risk", label: "Risk" },
                  { value: "promotion", label: "Promotion" },
                  { value: "system", label: "System" },
                ]}
                value={filters.actionCategory}
                onChange={(e) => setFilters({ ...filters, actionCategory: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="severity">Severity</Label>
              <Select
                options={[
                  { value: "", label: "All" },
                  { value: "info", label: "Info" },
                  { value: "warning", label: "Warning" },
                  { value: "error", label: "Error" },
                  { value: "critical", label: "Critical" },
                ]}
                value={filters.severity}
                onChange={(e) => setFilters({ ...filters, severity: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="startDate">Start Date</Label>
              <Input
                id="startDate"
                type="date"
                value={filters.startDate}
                onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="endDate">End Date</Label>
              <Input
                id="endDate"
                type="date"
                value={filters.endDate}
                onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Decision Trace Search */}
      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Decision Traces
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <Input
              placeholder="Search by trade ID..."
              value={traceSearch}
              onChange={(e) => setTraceSearch(e.target.value)}
              className="flex-1"
            />
          </div>
          {traces.length > 0 && (
            <div className="mt-4 space-y-2">
              {traces.map((trace) => (
                <div
                  key={trace.id}
                  className="flex items-center justify-between rounded-lg border border-border bg-muted/50 p-3 hover:bg-muted cursor-pointer"
                  onClick={() => setSelectedTraceId(trace.trade_id)}
                >
                  <div>
                    <p className="font-semibold text-white">{String(trace.trade_id || "—")}</p>
                    <p className="text-sm text-muted-foreground">
                      {String(trace.symbol || "—")} • {String(trace.decision_type || "—")} • {String(trace.decision_outcome || "—")}
                    </p>
                  </div>
                  <Button variant="ghost" size="sm">
                    <Eye className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Audit Log Entries */}
      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Audit Log Entries ({auditEntries.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex h-64 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : auditEntries.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-sm text-muted-foreground">No audit log entries found</p>
            </div>
          ) : (
            <div className="space-y-3">
              {auditEntries.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded-xl border border-border bg-muted/50 p-4 hover:bg-muted"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-start gap-3 flex-1">
                      <div className={cn("rounded-lg p-2", getSeverityColor(entry.severity))}>
                        {getSeverityIcon(entry.severity)}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-white">{String(entry.action_description || "—")}</p>
                          <Badge variant="outline" className="text-xs">
                            {String(entry.action_type || "—")}
                          </Badge>
                          <Badge className={getSeverityColor(entry.severity)}>{String(entry.severity || "info")}</Badge>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {String(entry.action_category || "—")} • {entry.resource_type ? String(entry.resource_type) : "N/A"} • {entry.resource_id ? String(entry.resource_id) : "N/A"}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {new Date(entry.created_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      </div>
    </>
  );
}

