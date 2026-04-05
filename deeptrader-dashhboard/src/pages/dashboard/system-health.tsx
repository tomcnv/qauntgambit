import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { useHealthSnapshot, useFastScalperLogs } from "../../lib/api/hooks";
import { ServiceHealthSnapshot, ResourceUsageSnapshot, ComponentDiagnosticsSnapshot } from "../../lib/api/types";
import { cn } from "../../lib/utils";
import { Activity, Cpu, HardDrive, AlertCircle, CheckCircle, XCircle, Search, Filter } from "lucide-react";
import { RunBar } from "../../components/run-bar";

const formatBytes = (bytes?: number) => {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
};

const formatUptime = (ms?: number) => {
  if (!ms) return "—";
  const seconds = Math.floor(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
};

const ServiceStatusCard = ({ name, healthy, details }: { name: string; healthy: boolean; details?: string }) => (
  <div className="rounded-xl border border-white/5 bg-white/5 p-4">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        {healthy ? (
          <CheckCircle className="h-5 w-5 text-emerald-400" />
        ) : (
          <XCircle className="h-5 w-5 text-red-400" />
        )}
        <div>
          <p className="font-semibold text-white">{name}</p>
          {details && <p className="text-xs text-muted-foreground">{details}</p>}
        </div>
      </div>
      <Badge variant={healthy ? "success" : "warning"}>{healthy ? "Healthy" : "Unhealthy"}</Badge>
    </div>
  </div>
);

export default function SystemHealthPage() {
  const { data: health, isFetching: healthLoading } = useHealthSnapshot();
  const { data: logs, isFetching: logsLoading } = useFastScalperLogs();
  const [logFilter, setLogFilter] = useState("");
  const [logLevel, setLogLevel] = useState<"all" | "error" | "warning" | "info">("all");

  // Extract health data
  const snapshot = health as any;
  const serviceHealth: ServiceHealthSnapshot | null = snapshot?.serviceHealth ?? null;
  const resourceUsage: ResourceUsageSnapshot | null = snapshot?.resourceUsage ?? null;
  const componentDiagnostics: ComponentDiagnosticsSnapshot | null = snapshot?.componentDiagnostics ?? null;

  // Filter logs
  const filteredLogs = useMemo(() => {
    if (!logs?.logs) return [];
    return logs.logs.filter((log) => {
      const matchesFilter = !logFilter || log.toLowerCase().includes(logFilter.toLowerCase());
      const matchesLevel =
        logLevel === "all" ||
        (logLevel === "error" && (log.includes("ERROR") || log.includes("❌") || log.includes("error"))) ||
        (logLevel === "warning" && (log.includes("WARNING") || log.includes("⚠️") || log.includes("warning"))) ||
        (logLevel === "info" && !log.includes("ERROR") && !log.includes("WARNING"));
      return matchesFilter && matchesLevel;
    });
  }, [logs, logFilter, logLevel]);

  return (
    <>
      <RunBar variant="compact" />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Observability</h1>
          <p className="text-sm text-muted-foreground">System health and logs monitoring</p>
        </div>

      {/* Service Health */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Service Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          {healthLoading ? (
            <p className="text-sm text-muted-foreground">Loading health data...</p>
          ) : serviceHealth ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Overall Status</p>
                  <Badge variant={serviceHealth.all_ready ? "success" : "warning"} className="mt-1">
                    {serviceHealth.all_ready ? "All Services Ready" : "Some Services Down"}
                  </Badge>
                </div>
                {serviceHealth.missing && serviceHealth.missing.length > 0 && (
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Missing Services</p>
                    <p className="text-sm text-red-400">{serviceHealth.missing.length}</p>
                  </div>
                )}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {Object.entries(serviceHealth.services || {}).map(([service, healthy]) => (
                  <ServiceStatusCard
                    key={service}
                    name={service.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
                    healthy={healthy as boolean}
                  />
                ))}
              </div>

              {serviceHealth.missing && serviceHealth.missing.length > 0 && (
                <div className="rounded-xl border border-red-400/30 bg-red-500/10 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle className="h-4 w-4 text-red-400" />
                    <p className="text-sm font-semibold text-red-400">Missing Services</p>
                  </div>
                  <ul className="list-disc list-inside text-sm text-red-300 space-y-1">
                    {serviceHealth.missing.map((service) => (
                      <li key={service}>{service.replace(/_/g, " ")}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No service health data available</p>
          )}
        </CardContent>
      </Card>

      {/* Resource Usage */}
      {resourceUsage && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card className="border-white/5 bg-black/30">
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
                <Cpu className="h-4 w-4" />
                CPU Usage
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {resourceUsage.process_cpu_percent !== undefined && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-muted-foreground">Process CPU</span>
                      <span className="text-lg font-semibold text-white">
                        {resourceUsage.process_cpu_percent.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-blue-500 to-cyan-500 transition-all"
                        style={{ width: `${Math.min(resourceUsage.process_cpu_percent, 100)}%` }}
                      />
                    </div>
                  </div>
                )}
                {resourceUsage.system_cpu_percent !== undefined && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-muted-foreground">System CPU</span>
                      <span className="text-lg font-semibold text-white">
                        {resourceUsage.system_cpu_percent.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all"
                        style={{ width: `${Math.min(resourceUsage.system_cpu_percent, 100)}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="border-white/5 bg-black/30">
            <CardHeader>
              <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
                <HardDrive className="h-4 w-4" />
                Memory Usage
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {resourceUsage.process_memory_mb !== undefined && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-muted-foreground">Process Memory</span>
                      <span className="text-lg font-semibold text-white">
                        {formatBytes(resourceUsage.process_memory_mb * 1024 * 1024)}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-emerald-500 to-teal-500 transition-all"
                        style={{
                          width: resourceUsage.system_memory_total_gb
                            ? `${Math.min((resourceUsage.process_memory_mb / (resourceUsage.system_memory_total_gb * 1024)) * 100, 100)}%`
                            : "0%",
                        }}
                      />
                    </div>
                  </div>
                )}
                {resourceUsage.system_memory_percent !== undefined && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-muted-foreground">System Memory</span>
                      <span className="text-lg font-semibold text-white">
                        {resourceUsage.system_memory_percent.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all"
                        style={{ width: `${Math.min(resourceUsage.system_memory_percent, 100)}%` }}
                      />
                    </div>
                    {resourceUsage.system_memory_used_gb && resourceUsage.system_memory_total_gb && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {resourceUsage.system_memory_used_gb.toFixed(2)} GB /{" "}
                        {resourceUsage.system_memory_total_gb.toFixed(2)} GB
                      </p>
                    )}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Component Diagnostics */}
      {componentDiagnostics && Object.keys(componentDiagnostics).length > 0 && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Component Diagnostics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {Object.entries(componentDiagnostics).map(([component, diagnostics]) => (
                <div key={component} className="rounded-xl border border-white/5 bg-white/5 p-4">
                  <p className="font-semibold text-white mb-3">{component.replace(/_/g, " ")}</p>
                  <div className="space-y-2 text-sm">
                    {diagnostics.call_count !== undefined && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Calls</span>
                        <span className="text-white">{diagnostics.call_count.toLocaleString()}</span>
                      </div>
                    )}
                    {diagnostics.error_count !== undefined && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Errors</span>
                        <span className={cn(diagnostics.error_count > 0 ? "text-red-400" : "text-white")}>
                          {diagnostics.error_count}
                        </span>
                      </div>
                    )}
                    {diagnostics.last_error && (
                      <div className="mt-2 pt-2 border-t border-white/5">
                        <p className="text-xs text-muted-foreground mb-1">Last Error</p>
                        <p className="text-xs text-red-400 break-words">{diagnostics.last_error}</p>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Log Viewer */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Log Viewer</CardTitle>
        </CardHeader>
        <CardContent>
          {logsLoading ? (
            <p className="text-sm text-muted-foreground">Loading logs...</p>
          ) : (
            <div className="space-y-4">
              {/* Log Filters */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex-1 min-w-[200px]">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search logs..."
                      value={logFilter}
                      onChange={(e) => setLogFilter(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  <select
                    value={logLevel}
                    onChange={(e) => setLogLevel(e.target.value as any)}
                    className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-primary/60"
                  >
                    <option value="all">All Levels</option>
                    <option value="error">Errors Only</option>
                    <option value="warning">Warnings Only</option>
                    <option value="info">Info Only</option>
                  </select>
                </div>
              </div>

              {/* Logs */}
              <div className="space-y-1 font-mono text-xs max-h-96 overflow-y-auto">
                {filteredLogs.length > 0 ? (
                  filteredLogs.slice(-100).map((log, idx) => {
                    const isError = log.includes("ERROR") || log.includes("❌") || log.includes("error");
                    const isWarning = log.includes("WARNING") || log.includes("⚠️") || log.includes("warning");
                    return (
                      <div
                        key={idx}
                        className={cn(
                          "rounded border p-2 break-words",
                          isError
                            ? "border-red-400/30 bg-red-500/10 text-red-300"
                            : isWarning
                              ? "border-amber-400/30 bg-amber-500/10 text-amber-300"
                              : "border-white/5 bg-white/5 text-muted-foreground"
                        )}
                      >
                        {log}
                      </div>
                    );
                  })
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">No logs found</p>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      </div>
    </>
  );
}

