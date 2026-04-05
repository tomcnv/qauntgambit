import { useMemo, useState } from "react";
import { DashBar } from "../../components/DashBar";
import { ScopeBar } from "../../components/signals/ScopeBar";
import { DecisionFunnel } from "../../components/signals/DecisionFunnel";
import { StatusNarrative } from "../../components/signals/StatusNarrative";
import { SymbolInspector } from "../../components/signals/SymbolInspector";
import ShadowComparisonPanel from "../../components/ShadowComparisonPanel";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import { useScopeStore } from "../../store/scope-store";
import { useConfirmationReadiness, usePredictionHistory, useRuntimePrediction, useStatusNarrative, useSymbolStatus } from "../../lib/api/hooks";
import { RuntimePredictionPayload, SymbolStatus } from "../../lib/api/types";
import { usePipelineHealth } from "../../lib/api/quant-hooks";
import { Activity, AlertTriangle, CheckCircle2, Clock3, RefreshCw, Search, XCircle } from "lucide-react";

function formatTimeAgo(ts?: string | null): string {
  if (!ts) return "-";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "-";
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatConfidence(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function formatBps(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)} bps` : "—";
}

function formatPredictionTs(value?: string | number): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Date(value > 1e12 ? value : value * 1000).toLocaleTimeString();
  }
  if (typeof value === "string" && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return new Date(numeric > 1e12 ? numeric : numeric * 1000).toLocaleTimeString();
    }
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? new Date(parsed).toLocaleTimeString() : "—";
  }
  return "—";
}

function AIPredictionCard({ prediction }: { prediction: RuntimePredictionPayload | null | undefined }) {
  if (!prediction) {
    return <div className="text-sm text-muted-foreground">No live AI prediction payload yet.</div>;
  }

  return (
    <div className="space-y-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium">{String(prediction.source || "unknown")}</div>
          <div className="text-muted-foreground">
            {String(prediction.provider_version || "—")} • {formatPredictionTs(prediction.ts ?? prediction.timestamp)}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">{String(prediction.direction || "—")}</Badge>
          {prediction.fallback_used ? <Badge variant="outline" className="border-amber-500/40 text-amber-500">fallback</Badge> : null}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded border p-2">
          <div className="text-muted-foreground">Confidence</div>
          <div className="font-mono">{formatConfidence(prediction.confidence)}</div>
        </div>
        <div className="rounded border p-2">
          <div className="text-muted-foreground">Expected move</div>
          <div className="font-mono">{formatBps(prediction.expected_move_bps)}</div>
        </div>
        <div className="rounded border p-2">
          <div className="text-muted-foreground">Horizon</div>
          <div className="font-mono">{typeof prediction.horizon_sec === "number" ? `${prediction.horizon_sec}s` : "—"}</div>
        </div>
        <div className="rounded border p-2">
          <div className="text-muted-foreground">Latency</div>
          <div className="font-mono">
            {typeof prediction.provider_latency_ms === "number" ? `${prediction.provider_latency_ms.toFixed(0)}ms` : "—"}
          </div>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded border p-2">
          <div className="mb-2 text-muted-foreground">Reason codes</div>
          <div className="flex flex-wrap gap-1.5">
            {prediction.reason_codes?.length ? (
              prediction.reason_codes.map((reason) => (
                <Badge key={reason} variant="secondary">{reason}</Badge>
              ))
            ) : (
              <span className="text-muted-foreground">None</span>
            )}
          </div>
        </div>
        <div className="rounded border p-2">
          <div className="mb-2 text-muted-foreground">Risk flags</div>
          <div className="flex flex-wrap gap-1.5">
            {prediction.risk_flags?.length ? (
              prediction.risk_flags.map((flag) => (
                <Badge key={flag} variant="outline">{flag}</Badge>
              ))
            ) : (
              <span className="text-muted-foreground">None</span>
            )}
          </div>
        </div>
      </div>

      <details className="rounded border p-2">
        <summary className="cursor-pointer text-muted-foreground">Raw AI payload</summary>
        <pre className="mt-2 overflow-x-auto text-[11px]">{JSON.stringify(prediction, null, 2)}</pre>
      </details>
    </div>
  );
}

function RecentAIPredictions({ items }: { items: RuntimePredictionPayload[] }) {
  if (!items.length) {
    return <div className="text-sm text-muted-foreground">No recent AI predictions captured yet.</div>;
  }

  return (
    <div className="space-y-2">
      {items.slice(0, 8).map((item, idx) => (
        <div key={`${String(item.ts || item.timestamp || idx)}`} className="rounded border p-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="font-medium">{String(item.symbol || "—")} • {String(item.direction || "—")}</div>
              <div className="text-muted-foreground">{formatPredictionTs(item.ts ?? item.timestamp)}</div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{formatConfidence(item.confidence)}</Badge>
              {item.fallback_used ? <Badge variant="outline" className="border-amber-500/40 text-amber-500">fallback</Badge> : null}
            </div>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <div className="text-muted-foreground">Source</div>
              <div>{String(item.source || "—")}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Move</div>
              <div>{formatBps(item.expected_move_bps)}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Horizon</div>
              <div>{typeof item.horizon_sec === "number" ? `${item.horizon_sec}s` : "—"}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Latency</div>
              <div>{typeof item.provider_latency_ms === "number" ? `${item.provider_latency_ms.toFixed(0)}ms` : "—"}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

const STATUS_OPTIONS = ["all", "tradable", "blocked", "no_signal"] as const;
type StatusFilter = (typeof STATUS_OPTIONS)[number];

export default function SignalsPage() {
  const { botId, exchangeAccountId } = useScopeStore();
  const [timeWindow, setTimeWindow] = useState("15m");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolStatus | null>(null);

  const { data: symbolsData, isLoading, isFetching, refetch } = useSymbolStatus({
    botId: botId || undefined,
    exchangeAccountId: exchangeAccountId || undefined,
  });

  const { data: narrativeData } = useStatusNarrative({
    timeWindow,
    botId: botId || undefined,
    exchangeAccountId: exchangeAccountId || undefined,
  });
  const { data: readinessData, isLoading: readinessLoading } = useConfirmationReadiness({
    timeWindow,
    botId: botId || undefined,
    exchangeAccountId: exchangeAccountId || undefined,
  });
  const { data: runtimePrediction, isFetching: predictionFetching } = useRuntimePrediction({
    botId: botId || undefined,
  });
  const { data: predictionHistory, isFetching: historyFetching } = usePredictionHistory({
    botId: botId || undefined,
    limit: 25,
  });
  const { data: pipelineHealth } = usePipelineHealth(5000);

  const symbols = symbolsData?.symbols ?? [];

  const filteredSymbols = useMemo(() => {
    return symbols.filter((item) => {
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (search && !item.symbol.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [symbols, search, statusFilter]);

  const stats = useMemo(() => {
    const total = symbols.length;
    const tradable = symbols.filter((s) => s.status === "tradable").length;
    const blocked = symbols.filter((s) => s.status === "blocked").length;
    const noSignal = symbols.filter((s) => s.status === "no_signal").length;
    return { total, tradable, blocked, noSignal };
  }, [symbols]);

  const blockerBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of symbols) {
      if (item.status !== "blocked") continue;
      const key = item.blockingReason || item.blockingStage || "unknown";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()]
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 6);
  }, [symbols]);

  const narrativeMetrics = narrativeData?.metrics;
  const topRejectionReasons = narrativeMetrics?.topRejectionReasons ?? [];
  const inputHealth = pipelineHealth?.prediction?.input_feature_health;
  const featureHealthMap = useMemo(
    () => new Map((inputHealth?.features ?? []).map((f) => [f.name, f])),
    [inputHealth?.features],
  );

  return (
    <>
      <DashBar />
      <div className="flex min-h-full flex-col">
        <ScopeBar />

        <div className="mx-auto w-full max-w-[1500px] space-y-4 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold">Signals</h1>
            <Badge variant="outline">{isFetching ? "Live refresh" : "Live"}</Badge>

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <div className="flex rounded-md border p-0.5">
                {["15m", "1h", "6h", "24h"].map((window) => (
                  <Button
                    key={window}
                    size="sm"
                    variant={timeWindow === window ? "default" : "ghost"}
                    className="h-7 px-2 text-xs"
                    onClick={() => setTimeWindow(window)}
                  >
                    {window}
                  </Button>
                ))}
              </div>

              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="h-8 w-[140px] pl-7 text-xs"
                  placeholder="Search symbol"
                />
              </div>

              <select
                className="h-8 rounded border bg-background px-2 text-xs"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
              >
                <option value="all">All statuses</option>
                <option value="tradable">Tradable</option>
                <option value="blocked">Blocked</option>
                <option value="no_signal">No signal</option>
              </select>

              <Button variant="outline" size="sm" className="h-8" onClick={() => refetch()}>
                <RefreshCw className={cn("mr-1 h-3.5 w-3.5", isFetching && "animate-spin")} />
                Refresh
              </Button>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(360px,1fr)]">
            <div className="space-y-4">
              <DecisionFunnel timeWindow={timeWindow} onTimeWindowChange={setTimeWindow} />
              <StatusNarrative timeWindow={timeWindow} />
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Latest AI Prediction</CardTitle>
                </CardHeader>
                <CardContent>
                  {botId ? (
                    predictionFetching ? (
                      <div className="text-sm text-muted-foreground">Loading latest AI payload...</div>
                    ) : (
                      <AIPredictionCard prediction={runtimePrediction?.payload} />
                    )
                  ) : (
                    <div className="text-sm text-muted-foreground">Select a bot scope to inspect AI predictions.</div>
                  )}
                </CardContent>
              </Card>
            </div>
            <div className="space-y-4">
              <ShadowComparisonPanel provider="live" />
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <Clock3 className="h-4 w-4" />
                    Recent AI Decisions
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {botId ? (
                    historyFetching ? (
                      <div className="text-sm text-muted-foreground">Loading AI decision history...</div>
                    ) : (
                      <RecentAIPredictions items={predictionHistory?.items || []} />
                    )
                  ) : (
                    <div className="text-sm text-muted-foreground">Prediction history is only available at bot scope.</div>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Model Input Health</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-xs">
                  {!inputHealth ? (
                    <div className="text-muted-foreground">No model input diagnostics yet.</div>
                  ) : (
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant="outline"
                          className={cn(
                            inputHealth.status === "ok"
                              ? "border-emerald-500/40 text-emerald-500"
                              : inputHealth.status === "warning"
                                ? "border-amber-500/40 text-amber-500"
                                : "border-red-500/40 text-red-500",
                          )}
                        >
                          {inputHealth.status.toUpperCase()}
                        </Badge>
                        <span className="text-muted-foreground">Samples: {inputHealth.sample_count}</span>
                        <span className="text-muted-foreground">Features: {inputHealth.feature_count}</span>
                      </div>

                      <div className="grid gap-2 sm:grid-cols-2">
                        <div className="rounded border p-2">
                          <div className="text-muted-foreground">Critical Inputs</div>
                          <div className="font-mono">{inputHealth.critical_features?.length ?? 0}</div>
                        </div>
                        <div className="rounded border p-2">
                          <div className="text-muted-foreground">Warning Inputs</div>
                          <div className="font-mono">{inputHealth.warning_features?.length ?? 0}</div>
                        </div>
                      </div>

                      {(inputHealth.critical_features?.length || inputHealth.warning_features?.length) ? (
                        <div className="space-y-2">
                          {inputHealth.critical_features?.slice(0, 8).map((name) => {
                            const details = featureHealthMap.get(name);
                            return (
                              <div key={`crit-${name}`} className="rounded border border-red-500/30 bg-red-500/5 p-2">
                                <div className="mb-1 flex items-center justify-between">
                                  <span className="font-mono">{name}</span>
                                  <Badge variant="outline" className="border-red-500/40 text-red-500">critical</Badge>
                                </div>
                                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                                  <span>Missing: {details?.missing_pct?.toFixed(1) ?? "-"}%</span>
                                  <span>Unique: {details?.unique_values ?? "-"}</span>
                                  <span>Stddev: {details?.stddev?.toFixed(6) ?? "-"}</span>
                                  <span>Range p01-p99: {details?.range_p01_p99?.toFixed(6) ?? "-"}</span>
                                  <span>p01: {details?.p01?.toFixed(6) ?? "-"}</span>
                                  <span>p99: {details?.p99?.toFixed(6) ?? "-"}</span>
                                </div>
                              </div>
                            );
                          })}
                          {inputHealth.warning_features?.slice(0, 8).map((name) => {
                            const details = featureHealthMap.get(name);
                            return (
                              <div key={`warn-${name}`} className="rounded border border-amber-500/30 bg-amber-500/5 p-2">
                                <div className="mb-1 flex items-center justify-between">
                                  <span className="font-mono">{name}</span>
                                  <Badge variant="outline" className="border-amber-500/40 text-amber-500">warning</Badge>
                                </div>
                                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                                  <span>Missing: {details?.missing_pct?.toFixed(1) ?? "-"}%</span>
                                  <span>Unique: {details?.unique_values ?? "-"}</span>
                                  <span>Stddev: {details?.stddev?.toFixed(6) ?? "-"}</span>
                                  <span>Range p01-p99: {details?.range_p01_p99?.toFixed(6) ?? "-"}</span>
                                  <span>p01: {details?.p01?.toFixed(6) ?? "-"}</span>
                                  <span>p99: {details?.p99?.toFixed(6) ?? "-"}</span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-2 text-emerald-500">
                          All model inputs are sufficiently dynamic in the current sample window.
                        </div>
                      )}
                    </>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Confirmation Readiness</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-xs">
                  {!readinessData ? (
                    <div className="text-muted-foreground">
                      {readinessLoading ? "Loading readiness metrics..." : "No readiness data yet."}
                    </div>
                  ) : (
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant="outline"
                          className={cn(
                            readinessData.readyForEnforce
                              ? "border-emerald-500/40 text-emerald-500"
                              : "border-amber-500/40 text-amber-500",
                          )}
                        >
                          {readinessData.readyForEnforce ? "Ready For Enforce" : "Shadow Only"}
                        </Badge>
                        <span className="text-muted-foreground">
                          Window: {readinessData.timeWindow}
                        </span>
                        <Badge
                          variant="outline"
                          className={cn(
                            readinessData.recommendedReadyForEnforce
                              ? "border-emerald-500/40 text-emerald-500"
                              : "border-amber-500/40 text-amber-500",
                          )}
                        >
                          {readinessData.recommendedReadyForEnforce ? "Recommended Cutover" : "Need More Outcome Data"}
                        </Badge>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <div className="rounded border p-2">
                          <div className="text-muted-foreground">Disagreement</div>
                          <div className="font-mono">{readinessData.disagreementPct.toFixed(2)}%</div>
                        </div>
                        <div className="rounded border p-2">
                          <div className="text-muted-foreground">Comparisons</div>
                          <div className="font-mono">{readinessData.comparisonCount}</div>
                        </div>
                        <div className="rounded border p-2">
                          <div className="text-muted-foreground">Mismatches</div>
                          <div className="font-mono">{readinessData.mismatchCount}</div>
                        </div>
                        <div className="rounded border p-2">
                          <div className="text-muted-foreground">Contract Violations</div>
                          <div className="font-mono">{readinessData.contractViolations}</div>
                        </div>
                      </div>
                      <div className="grid gap-1">
                        <div className={cn("rounded border p-2", readinessData.checks.min_comparisons_met ? "border-emerald-500/30" : "border-red-500/30")}>
                          Min comparisons: {readinessData.checks.min_comparisons_met ? "pass" : "fail"}
                        </div>
                        <div className={cn("rounded border p-2", readinessData.checks.disagreement_within_limit ? "border-emerald-500/30" : "border-red-500/30")}>
                          Disagreement cap: {readinessData.checks.disagreement_within_limit ? "pass" : "fail"}
                        </div>
                        <div className={cn("rounded border p-2", readinessData.checks.contract_violations_within_limit ? "border-emerald-500/30" : "border-red-500/30")}>
                          Contract violations: {readinessData.checks.contract_violations_within_limit ? "pass" : "fail"}
                        </div>
                      </div>
                      <div className="rounded border p-2">
                        <div className="mb-1 text-muted-foreground">
                          Market outcome ({readinessData.marketOutcome.horizonMinutes}m side-adjusted {readinessData.marketOutcome.metric === "netMarkoutBps" ? "net" : "gross"} markout)
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2">
                          <div className="rounded border p-2">
                            <div className="text-muted-foreground">Unified-only mean</div>
                            <div className="font-mono">
                              {(readinessData.marketOutcome.cohorts.unified_only?.meanNetMarkoutBps ?? readinessData.marketOutcome.cohorts.unified_only?.meanMarkoutBps) ?? "-"} bps
                            </div>
                            <div className="text-[11px] text-muted-foreground">
                              n={readinessData.marketOutcome.cohorts.unified_only?.evaluated ?? 0}
                            </div>
                          </div>
                          <div className="rounded border p-2">
                            <div className="text-muted-foreground">Legacy-only mean</div>
                            <div className="font-mono">
                              {(readinessData.marketOutcome.cohorts.legacy_only?.meanNetMarkoutBps ?? readinessData.marketOutcome.cohorts.legacy_only?.meanMarkoutBps) ?? "-"} bps
                            </div>
                            <div className="text-[11px] text-muted-foreground">
                              n={readinessData.marketOutcome.cohorts.legacy_only?.evaluated ?? 0}
                            </div>
                          </div>
                        </div>
                        <div className="mt-2 grid gap-1">
                          <div className={cn("rounded border p-2", readinessData.outcomeChecks.unified_only_samples_met ? "border-emerald-500/30" : "border-red-500/30")}>
                            Unified-only samples: {readinessData.outcomeChecks.unified_only_samples_met ? "pass" : "fail"}
                          </div>
                          <div className={cn("rounded border p-2", readinessData.outcomeChecks.unified_only_mean_markout_ok ? "border-emerald-500/30" : "border-red-500/30")}>
                            Unified-only edge: {readinessData.outcomeChecks.unified_only_mean_markout_ok ? "pass" : "fail"}
                          </div>
                          <div className={cn("rounded border p-2", readinessData.outcomeChecks.unified_vs_legacy_delta_ok ? "border-emerald-500/30" : "border-red-500/30")}>
                            Unified vs legacy delta: {readinessData.outcomeChecks.unified_vs_legacy_delta_ok ? "pass" : "fail"}
                          </div>
                        </div>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardContent className="p-4">
                <div className="mb-1 text-xs text-muted-foreground">Configured Symbols</div>
                <div className="text-2xl font-semibold">{stats.total}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Tradable
                </div>
                <div className="text-2xl font-semibold text-emerald-500">{stats.tradable}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
                  <XCircle className="h-3.5 w-3.5 text-red-500" /> Blocked
                </div>
                <div className="text-2xl font-semibold text-red-500">{stats.blocked}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
                  <Activity className="h-3.5 w-3.5 text-amber-500" /> No Signal
                </div>
                <div className="text-2xl font-semibold text-amber-500">{stats.noSignal}</div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Symbol Status</CardTitle>
              </CardHeader>
              <CardContent>
                {isLoading ? (
                  <div className="py-8 text-center text-sm text-muted-foreground">Loading signals...</div>
                ) : filteredSymbols.length === 0 ? (
                  <div className="py-8 text-center text-sm text-muted-foreground">No symbols match current filters.</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b">
                          <th className="py-2 text-left font-medium text-muted-foreground">Symbol</th>
                          <th className="py-2 text-left font-medium text-muted-foreground">Status</th>
                          <th className="py-2 text-left font-medium text-muted-foreground">Signal</th>
                          <th className="py-2 text-left font-medium text-muted-foreground">Block Stage</th>
                          <th className="py-2 text-left font-medium text-muted-foreground">Block Reason</th>
                          <th className="py-2 text-right font-medium text-muted-foreground">Latency p95</th>
                          <th className="py-2 text-right font-medium text-muted-foreground">Last Decision</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredSymbols.map((item) => {
                          const statusTone =
                            item.status === "blocked"
                              ? "border-red-500/40 text-red-500"
                              : item.status === "tradable"
                                ? "border-emerald-500/40 text-emerald-500"
                                : "border-muted-foreground/40 text-muted-foreground";
                          return (
                            <tr
                              key={item.symbol}
                              className="cursor-pointer border-b hover:bg-muted/30"
                              onClick={() => setSelectedSymbol(item)}
                            >
                              <td className="py-2 font-medium">{item.symbol}</td>
                              <td className="py-2">
                                <Badge variant="outline" className={cn("text-[10px]", statusTone)}>
                                  {item.status}
                                </Badge>
                              </td>
                              <td className="py-2">
                                {item.signal.side ? (
                                  <span className={cn(item.signal.side === "long" ? "text-emerald-500" : "text-red-500")}>{item.signal.side}</span>
                                ) : (
                                  <span className="text-muted-foreground">-</span>
                                )}
                              </td>
                              <td className="py-2 text-muted-foreground">{item.blockingStage || "-"}</td>
                              <td className="max-w-[280px] truncate py-2 text-muted-foreground" title={item.blockingReason || undefined}>
                                {item.blockingReason || "-"}
                              </td>
                              <td className="py-2 text-right font-mono">{item.latencyP95 ? `${item.latencyP95}ms` : "-"}</td>
                              <td className="py-2 text-right text-muted-foreground">{formatTimeAgo(item.lastDecision)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Top Blockers</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {blockerBreakdown.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No active blockers.</p>
                  ) : (
                    blockerBreakdown.map((item) => (
                      <div key={item.reason} className="flex items-center justify-between rounded border p-2 text-xs">
                        <span className="truncate text-muted-foreground" title={item.reason}>{item.reason}</span>
                        <Badge variant="outline">{item.count}</Badge>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Window Metrics ({timeWindow})</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Signals</span>
                    <span className="font-mono">{narrativeMetrics?.signalsCount ?? 0}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Rejected</span>
                    <span className="font-mono">{narrativeMetrics?.rejectsCount ?? 0}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Fills</span>
                    <span className="font-mono">{narrativeMetrics?.tradesCount ?? 0}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Top rejection stage</span>
                    <span className="font-mono">{narrativeMetrics?.topRejectionStage || "-"}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Top stage share</span>
                    <span className="font-mono">{(narrativeMetrics?.topRejectionPct ?? 0).toFixed(1)}%</span>
                  </div>
                  {narrativeMetrics?.signalGenerationIssue && (
                    <div className="mt-2 flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-amber-500">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      Signal generation issue detected
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Top Rejection Reasons</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {topRejectionReasons.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No rejection reasons in this window.</p>
                  ) : (
                    topRejectionReasons.map((item) => (
                      <div key={item.reason} className="rounded border p-2 text-xs">
                        <div className="truncate text-muted-foreground" title={item.reason}>
                          {item.reason}
                        </div>
                        <div className="mt-1 flex items-center justify-between font-mono">
                          <span>{item.count}</span>
                          <span>{item.pct.toFixed(1)}%</span>
                        </div>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Latency Guard</CardTitle>
                </CardHeader>
                <CardContent className="text-xs text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <Clock3 className="h-3.5 w-3.5" />
                    Review symbols with latency p95 above 50ms and investigate feed or model delays.
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>

      <SymbolInspector symbol={selectedSymbol} onClose={() => setSelectedSymbol(null)} />
    </>
  );
}
