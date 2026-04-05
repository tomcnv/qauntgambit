import { Link, useNavigate } from "react-router-dom";
import { Plus, Settings, TrendingUp, TrendingDown, Activity, Target, Copy, Bot, Clock3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { usePredictionHistory, useRuntimePrediction, useSignalLabData, useProfileSpecs } from "../../lib/api/hooks";
import { AllocatorPositionScore, DecisionTrace, FeatureHealthSnapshot, StageRejectionSummary, ChessboardProfileSpec, RuntimePredictionPayload } from "../../lib/api/types";
import { cn } from "../../lib/utils";
import { useScopeStore } from "../../store/scope-store";

const formatReason = (reason: string) => reason.replace(/_/g, " ");
const formatConfidence = (value?: number | null) =>
  typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
const formatBps = (value?: number | null) =>
  typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)} bps` : "—";
const formatPredictionTs = (value?: string | number) => {
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
};

const StageSummary = ({ summary }: { summary: StageRejectionSummary }) => {
  const stages = Object.entries(summary);
  if (stages.length === 0) {
    return <p className="text-sm text-muted-foreground">No stage data available.</p>;
  }

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {stages.map(([stage, reasons]) => {
        const topReasons = Object.entries(reasons).slice(0, 3);
        return (
          <div key={stage} className="rounded-3xl border border-white/5 bg-white/5 p-5 shadow-elevated">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">{formatReason(stage)}</p>
            {topReasons.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">No rejections logged.</p>
            ) : (
              <div className="mt-3 space-y-2">
                {topReasons.map(([reason, count]) => (
                  <div key={reason} className="flex items-center justify-between text-sm">
                    <span className="text-white">{formatReason(reason)}</span>
                    <Badge variant="outline">{count}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

const DecisionsTimeline = ({ traces }: { traces: DecisionTrace[] }) => {
  if (!traces.length) {
    return <p className="text-sm text-muted-foreground">No decision traces captured yet.</p>;
  }

  return (
    <div className="space-y-3">
      {traces.slice(0, 12).map((trace, idx) => {
        const rejected = trace.final_result === "reject";
        const timestampMs = trace.timestamp > 1e12 ? trace.timestamp : trace.timestamp * 1000;
        return (
          <div key={`${trace.timestamp}-${idx}`} className="rounded-2xl border border-white/5 bg-white/5 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">{String(trace.symbol || "—")}</p>
                <p className="text-xs text-muted-foreground">{new Date(timestampMs).toLocaleTimeString()}</p>
              </div>
              <Badge variant={rejected ? "warning" : "success"}>{String(trace.final_result ?? "unknown")}</Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-muted-foreground">
              <div>
                <p className="text-[10px] uppercase tracking-[0.3em]">Stage</p>
                <p className="text-white">{String(trace.rejection_stage ?? "pipeline_complete")}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.3em]">Reason</p>
                <p className="text-white">{trace.rejection_reason ? formatReason(String(trace.rejection_reason)) : "executed"}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.3em]">Latency</p>
                <p className="text-white">{trace.total_latency_ms ? Number(trace.total_latency_ms).toFixed(2) : "—"} ms</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.3em]">Profile</p>
                <p className="text-white">{trace.profile_id ? String(trace.profile_id) : "—"}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const AllocatorPanel = ({ scores }: { scores: AllocatorPositionScore[] }) => {
  if (!scores || scores.length === 0) {
    return <p className="text-sm text-muted-foreground">No allocator telemetry captured.</p>;
  }

  return (
    <div className="space-y-3">
      {scores.map((score) => (
        <div key={`${score.symbol}-${score.profile_id}`} className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-white">{score.symbol}</p>
              <p className="text-xs text-muted-foreground">{score.profile_id ?? "unassigned"}</p>
            </div>
            <Badge variant={score.side === "buy" ? "success" : "warning"}>{score.side}</Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-muted-foreground">
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Score</p>
              <p className="text-white">{score.score.toFixed(3)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Momentum</p>
              <p className="text-white">{score.momentum_score?.toFixed(3) ?? "—"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Regime</p>
              <p className="text-white">{score.regime_score?.toFixed(3) ?? "—"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">PnL</p>
              <p className={cn("text-white", score.unrealized_pnl && score.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400")}>
                {score.unrealized_pnl?.toFixed(2) ?? "—"}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

const FeatureHealthPanel = ({ snapshot }: { snapshot: FeatureHealthSnapshot }) => {
  const entries = Object.entries(snapshot);
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No feature health data.</p>;
  }

  return (
    <div className="space-y-3">
      {entries.map(([symbol, info]) => (
        <div key={symbol} className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white">{symbol}</p>
            <Badge variant={info.status === "healthy" ? "success" : "outline"}>{info.status ?? "unknown"}</Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-muted-foreground">
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Trend</p>
              <p className="text-white">{info.regime?.trend ?? "—"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Volatility</p>
              <p className="text-white">{info.regime?.volatility ?? "—"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Session</p>
              <p className="text-white">{info.regime?.session ?? "—"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Profile</p>
              <p className="text-white">{info.last_profile ?? "—"}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

const AIPredictionCard = ({ prediction }: { prediction: RuntimePredictionPayload | null | undefined }) => {
  if (!prediction) {
    return <p className="text-sm text-muted-foreground">No live AI prediction payload yet.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-white">{String(prediction.source || "unknown")}</p>
          <p className="text-xs text-muted-foreground">
            {String(prediction.provider_version || "—")} • {formatPredictionTs(prediction.ts ?? prediction.timestamp)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">{String(prediction.direction || "—")}</Badge>
          {prediction.fallback_used ? <Badge variant="warning">fallback</Badge> : null}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Confidence</p>
          <p className="mt-2 text-lg font-semibold text-white">{formatConfidence(prediction.confidence)}</p>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Expected Move</p>
          <p className="mt-2 text-lg font-semibold text-white">{formatBps(prediction.expected_move_bps)}</p>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Horizon</p>
          <p className="mt-2 text-lg font-semibold text-white">
            {typeof prediction.horizon_sec === "number" ? `${prediction.horizon_sec}s` : "—"}
          </p>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Latency</p>
          <p className="mt-2 text-lg font-semibold text-white">
            {typeof prediction.provider_latency_ms === "number" ? `${prediction.provider_latency_ms.toFixed(0)}ms` : "—"}
          </p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Reason Codes</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {prediction.reason_codes?.length ? prediction.reason_codes.map((reason) => (
              <Badge key={reason} variant="secondary">{reason}</Badge>
            )) : <span className="text-sm text-muted-foreground">None</span>}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <p className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Risk Flags</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {prediction.risk_flags?.length ? prediction.risk_flags.map((flag) => (
              <Badge key={flag} variant="outline">{flag}</Badge>
            )) : <span className="text-sm text-muted-foreground">None</span>}
          </div>
        </div>
      </div>
      <details className="rounded-2xl border border-white/5 bg-white/5 p-4">
        <summary className="cursor-pointer text-sm text-muted-foreground">Raw AI payload</summary>
        <pre className="mt-3 overflow-x-auto text-xs text-white">{JSON.stringify(prediction, null, 2)}</pre>
      </details>
    </div>
  );
};

const RecentAIPredictions = ({ items }: { items: RuntimePredictionPayload[] }) => {
  if (!items.length) {
    return <p className="text-sm text-muted-foreground">No recent AI predictions captured yet.</p>;
  }

  return (
    <div className="space-y-3">
      {items.slice(0, 8).map((item, idx) => (
        <div key={`${String(item.ts || item.timestamp || idx)}`} className="rounded-2xl border border-white/5 bg-white/5 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-white">{String(item.symbol || "—")} • {String(item.direction || "—")}</p>
              <p className="text-xs text-muted-foreground">{formatPredictionTs(item.ts ?? item.timestamp)}</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{formatConfidence(item.confidence)}</Badge>
              {item.fallback_used ? <Badge variant="warning">fallback</Badge> : null}
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-muted-foreground md:grid-cols-4">
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Source</p>
              <p className="text-white">{String(item.source || "—")}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Move</p>
              <p className="text-white">{formatBps(item.expected_move_bps)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Horizon</p>
              <p className="text-white">{typeof item.horizon_sec === "number" ? `${item.horizon_sec}s` : "—"}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em]">Latency</p>
              <p className="text-white">{typeof item.provider_latency_ms === "number" ? `${item.provider_latency_ms.toFixed(0)}ms` : "—"}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default function SignalLabPage() {
  const navigate = useNavigate();
  const { botId } = useScopeStore();
  const { data, isFetching } = useSignalLabData();
  const { data: profileSpecsData, isLoading: profileSpecsLoading } = useProfileSpecs(botId);
  const { data: runtimePrediction, isFetching: predictionFetching } = useRuntimePrediction({ botId: botId || undefined });
  const { data: predictionHistory, isFetching: historyFetching } = usePredictionHistory({ botId: botId || undefined, limit: 25 });
  
  const handleUseAsTemplate = (spec: ChessboardProfileSpec) => {
    // Navigate to profile editor with template data
    const templateData = {
      name: `${spec.name} (Custom)`,
      description: spec.description,
      conditions: spec.conditions,
      risk: spec.risk,
      lifecycle: spec.lifecycle,
      strategy_ids: spec.strategy_ids,
      strategy_params: spec.strategy_params,
      min_win_rate: spec.min_win_rate,
      min_profit_factor: spec.min_profit_factor,
      tags: spec.tags,
      template_id: spec.id,
    };
    navigate('/dashboard/profile-editor', { state: { template: templateData } });
  };
  const counts = Object.entries(data?.rejections.counts ?? {}).sort((a, b) => b[1] - a[1]);
  const recentRejections = data?.rejections.recent ?? [];
  const snapshot = data?.snapshot;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Signals & Profiles</h1>
        </div>
        <div className="flex gap-3">
          <Link to="/strategy-config">
            <Button variant="outline" size="sm">
              <Settings className="mr-2 h-4 w-4" />
              Strategies
            </Button>
          </Link>
          <Link to="/signal-customization">
            <Button variant="outline" size="sm">
              <Settings className="mr-2 h-4 w-4" />
              Customize
            </Button>
          </Link>
          <Link to="/profile-editor">
            <Button size="sm">
              <Plus className="mr-2 h-4 w-4" />
              Create Profile
            </Button>
          </Link>
        </div>
      </div>

      <section className="grid gap-6 xl:grid-cols-[1.15fr,0.85fr]">
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.4em] text-muted-foreground">
              <Bot className="h-4 w-4" />
              Latest AI Prediction
            </CardTitle>
          </CardHeader>
          <CardContent>
            {botId ? (
              predictionFetching ? <p className="text-sm text-muted-foreground">Loading latest AI payload…</p> : <AIPredictionCard prediction={runtimePrediction?.payload} />
            ) : (
              <p className="text-sm text-muted-foreground">Select a bot scope to inspect DeepSeek predictions.</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.4em] text-muted-foreground">
              <Clock3 className="h-4 w-4" />
              Recent AI Decisions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {botId ? (
              historyFetching ? <p className="text-sm text-muted-foreground">Loading AI decision history…</p> : <RecentAIPredictions items={predictionHistory?.items || []} />
            ) : (
              <p className="text-sm text-muted-foreground">Prediction history is only available at bot scope.</p>
            )}
          </CardContent>
        </Card>
      </section>

      <Card className="border-white/5 bg-black/40">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Chessboard Profiles ({profileSpecsData?.specs?.length ?? 0})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {profileSpecsData?.specs && profileSpecsData.specs.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {profileSpecsData.specs.map((spec: ChessboardProfileSpec) => (
                <div key={spec.id} className="rounded-2xl border border-white/5 bg-white/5 p-4">
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <h3 className="font-semibold text-white text-sm">{spec.name}</h3>
                      <p className="text-xs text-muted-foreground mt-1">{spec.description}</p>
                    </div>
                    <Badge variant="outline" className="text-xs">
                      {spec.id}
                    </Badge>
                  </div>
                  
                  <div className="mt-3 space-y-2">
                    {spec.tags && spec.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {spec.tags.slice(0, 3).map((tag) => (
                          <Badge key={tag} variant="outline" className="text-[10px] px-1.5 py-0.5">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    )}
                    
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-muted-foreground">Risk:</span>
                        <span className="text-white ml-1">{spec.risk.risk_per_trade_pct}%</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">SL:</span>
                        <span className="text-white ml-1">{(spec.risk.stop_loss_pct * 100).toFixed(2)}%</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Strategies:</span>
                        <span className="text-white ml-1">{spec.strategy_ids?.length ?? 0}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Version:</span>
                        <span className="text-white ml-1">{spec.version}</span>
                      </div>
                    </div>
                    
                    {spec.conditions.required_volatility && (
                      <div className="flex items-center gap-1 text-xs text-muted-foreground mt-2">
                        <Activity className="w-3 h-3" />
                        <span>Vol: {spec.conditions.required_volatility}</span>
                      </div>
                    )}
                    
                    <div className="mt-3 pt-3 border-t border-white/5">
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() => handleUseAsTemplate(spec)}
                      >
                        <Copy className="mr-2 h-3 w-3" />
                        Use as Template
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {profileSpecsLoading ? "Loading chessboard profiles…" : "No profiles registered yet. Start the bot to see profiles."}
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="border-white/5 bg-black/40">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Stage Rejection Radar
          </CardTitle>
        </CardHeader>
        <CardContent>
          {snapshot ? (
            <StageSummary summary={snapshot.stageRejections ?? {}} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {isFetching ? "Loading stage telemetry…" : "No stage data yet."}
            </p>
          )}
        </CardContent>
      </Card>

      <section className="grid gap-6 lg:grid-cols-2">
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Decision Stream
            </CardTitle>
          </CardHeader>
          <CardContent>
            {snapshot ? (
              <DecisionsTimeline traces={snapshot.recentDecisions ?? []} />
            ) : (
              <p className="text-sm text-muted-foreground">Waiting for decision traces…</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Rejection Feed
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            {recentRejections.length === 0 ? (
              <p>No recent rejections found.</p>
            ) : (
              recentRejections.slice(0, 12).map((entry, idx) => (
                <div key={`${entry.timestamp}-${idx}`} className="rounded-2xl border border-white/5 bg-white/5 px-4 py-3">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-white">{formatReason(entry.reason)}</span>
                    <Badge variant="outline">{entry.symbol ?? "n/a"}</Badge>
                  </div>
            <p className="text-xs text-muted-foreground">
                    {entry.profile ? `Profile: ${entry.profile}` : "Profile unknown"} •{" "}
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Allocator Priorities
            </CardTitle>
          </CardHeader>
          <CardContent>
            {snapshot ? (
              <AllocatorPanel scores={snapshot.allocator?.position_scores ?? []} />
            ) : (
              <p className="text-sm text-muted-foreground">Allocator snapshot unavailable.</p>
            )}
        </CardContent>
      </Card>

        <Card className="border-white/5 bg-black/40">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Feature Health
            </CardTitle>
          </CardHeader>
          <CardContent>
            {snapshot ? (
              <FeatureHealthPanel snapshot={snapshot.featureHealth ?? {}} />
            ) : (
              <p className="text-sm text-muted-foreground">Loading feature telemetry…</p>
            )}
          </CardContent>
        </Card>
      </section>

      <Card className="border-white/5 bg-black/40">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Rejection Heatmap
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          {counts.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {isFetching ? "Loading Redis counters…" : "No rejections recorded yet."}
            </p>
          )}
          {counts.map(([reason, count]) => (
            <div key={reason} className="rounded-3xl border border-white/5 bg-white/5 p-5 shadow-elevated">
              <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">{formatReason(reason)}</p>
              <p className="mt-3 text-4xl font-semibold text-white">{count}</p>
              <p className="text-xs text-muted-foreground">Events lifetime</p>
          </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
