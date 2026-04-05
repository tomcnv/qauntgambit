import { useMemo, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  FileCode2,
  FlaskConical,
  Play,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Switch } from "../../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Separator } from "../../components/ui/separator";
import { cn } from "../../lib/utils";
import {
  useActiveModelInfo,
  useModelTrainingJob,
  useModelTrainingJobs,
  usePromoteModelTrainingJob,
  useStartModelTraining,
} from "../../lib/api/hooks";
import toast from "react-hot-toast";

const statusMeta: Record<string, { color: string; icon: any }> = {
  queued: { color: "text-amber-500", icon: Clock },
  running: { color: "text-blue-500", icon: Activity },
  completed: { color: "text-emerald-500", icon: CheckCircle2 },
  blocked: { color: "text-amber-500", icon: Clock },
  failed: { color: "text-red-500", icon: XCircle },
};

export default function ModelTrainingPage() {
  const [labelSource, setLabelSource] = useState<"future_return" | "tp_sl" | "policy_replay">("future_return");
  const [hours, setHours] = useState("24");
  const [limit, setLimit] = useState("100000");
  const [folds, setFolds] = useState("3");
  const [driftCheck, setDriftCheck] = useState(false);
  const [allowRegression, setAllowRegression] = useState(false);
  const [useV4Pipeline, setUseV4Pipeline] = useState(true);
  const [horizonSec, setHorizonSec] = useState("120");
  const [tpBps, setTpBps] = useState("8");
  const [slBps, setSlBps] = useState("8");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const jobsQuery = useModelTrainingJobs(30);
  const activeModelQuery = useActiveModelInfo();
  const startMutation = useStartModelTraining();
  const promoteMutation = usePromoteModelTrainingJob();
  const detailQuery = useModelTrainingJob(selectedJobId);

  const jobs = jobsQuery.data ?? [];
  const activeModel = activeModelQuery.data;
  const selectedJob = detailQuery.data?.job;

  const handleStart = () => {
    startMutation.mutate(
      {
        label_source: labelSource,
        hours: Number(hours),
        limit: Number(limit),
        walk_forward_folds: Number(folds),
        drift_check: driftCheck,
        allow_regression: allowRegression,
        keep_dataset: true,
        use_v4_pipeline: useV4Pipeline,
        horizon_sec: Number(horizonSec),
        tp_bps: Number(tpBps),
        sl_bps: Number(slBps),
      },
      {
        onSuccess: (res) => {
          setSelectedJobId(res.job.id);
          toast.success(`Training queued: ${res.job.id.slice(0, 8)}`);
        },
        onError: (err: any) => toast.error(err?.message || "Failed to start training"),
      },
    );
  };

  const metricRows = useMemo(() => {
    const summary = (selectedJob?.summary ?? {}) as Record<string, any>;
    const ordered = [
      "promotion_status",
      "promotion_reason",
      "candidate_f1",
      "latest_f1",
      "candidate_ev",
      "latest_ev",
      "directional_f1_macro",
      "ev_after_costs_mean",
      "accuracy",
      "candidate_directional_f1_macro",
      "baseline_directional_f1_macro",
      "candidate_ev_after_costs_mean",
      "baseline_ev_after_costs_mean",
    ];
    return ordered.filter((k) => Object.prototype.hasOwnProperty.call(summary, k)).map((k) => [k, summary[k]]);
  }, [selectedJob]);

  const summaryWarnings = useMemo(() => {
    const warnings = (selectedJob?.summary?.warnings ?? []) as string[];
    return warnings.filter((w) => typeof w === "string" && w.trim().length > 0);
  }, [selectedJob]);

  const promotionAssessment = useMemo(() => {
    if (!selectedJob) {
      return {
        verdict: "no_job",
        label: "No Job Selected",
        tone: "text-muted-foreground",
        reasons: ["Select a completed job to assess promotion readiness."],
      };
    }

    const summary = (selectedJob.summary ?? {}) as Record<string, any>;
    const reasons: string[] = [];
    const checks: Array<{ name: string; pass: boolean; detail: string }> = [];

    const candidateF1 = Number(summary.candidate_f1 ?? Number.NaN);
    const latestF1 = Number(summary.latest_f1 ?? Number.NaN);
    const candidateEv = Number(summary.candidate_ev ?? Number.NaN);
    const latestEv = Number(summary.latest_ev ?? Number.NaN);
    const promotionStatus = String(summary.promotion_status ?? selectedJob.promotion_status ?? "").toLowerCase();

    if (selectedJob.status === "failed") {
      return {
        verdict: "reject",
        label: "Reject",
        tone: "text-red-400",
        reasons: ["Training failed. Resolve data/gate errors before promotion."],
        checks: [],
      };
    }
    if (selectedJob.status === "blocked" || promotionStatus === "blocked") {
      const reason = String(summary.promotion_reason ?? "Promotion gate blocked the candidate.");
      return {
        verdict: "hold",
        label: "Hold",
        tone: "text-amber-400",
        reasons: [reason],
        checks: [],
      };
    }
    if (selectedJob.status !== "completed") {
      return {
        verdict: "hold",
        label: "Hold",
        tone: "text-amber-400",
        reasons: ["Job is not completed yet."],
        checks: [],
      };
    }

    if (Number.isFinite(candidateF1) && Number.isFinite(latestF1)) {
      const delta = candidateF1 - latestF1;
      checks.push({
        name: "Directional F1 delta",
        pass: delta >= 0,
        detail: `${delta >= 0 ? "+" : ""}${delta.toFixed(4)}`,
      });
    }
    if (Number.isFinite(candidateEv) && Number.isFinite(latestEv)) {
      const delta = candidateEv - latestEv;
      checks.push({
        name: "EV-after-costs delta",
        pass: delta >= 0,
        detail: `${delta >= 0 ? "+" : ""}${delta.toFixed(4)}`,
      });
    }

    if (promotionStatus === "passed") {
      reasons.push("Promotion gates passed.");
    } else if (!promotionStatus) {
      reasons.push("No explicit promotion status in summary; review metrics before manual promote.");
    }

    const failedChecks = checks.filter((c) => !c.pass);
    if (failedChecks.length > 0) {
      reasons.push(`Failed ${failedChecks.length} baseline comparison check(s).`);
      return {
        verdict: "hold",
        label: "Hold",
        tone: "text-amber-400",
        reasons,
        checks,
      };
    }

    if (promotionStatus === "passed" || checks.length > 0) {
      return {
        verdict: "promote",
        label: "Promote",
        tone: "text-emerald-400",
        reasons,
        checks,
      };
    }

    return {
      verdict: "hold",
      label: "Hold",
      tone: "text-amber-400",
      reasons: reasons.length ? reasons : ["Insufficient comparison metrics. Run another job and compare candidate vs latest."],
      checks,
    };
  }, [selectedJob]);

  const stdoutTail = (selectedJob?.stdout_tail ?? []) as string[];
  const stderrTail = (selectedJob?.stderr_tail ?? []) as string[];
  const artifacts = (selectedJob?.artifacts ?? []) as any[];
  const canPromoteSelectedJob = useMemo(() => {
    if (!selectedJob) return false;
    if (selectedJob.status === "running" || selectedJob.status === "queued" || selectedJob.status === "failed") {
      return false;
    }
    return artifacts.some((a) => {
      const name = String(a?.name || "");
      return name.startsWith("prediction_baseline_") && (name.endsWith(".json") || name.endsWith(".onnx"));
    });
  }, [selectedJob, artifacts]);

  const handlePromote = () => {
    if (!selectedJobId) return;
    promoteMutation.mutate(
      { jobId: selectedJobId },
      {
        onSuccess: (res) => {
          toast.success(`Promoted ${res.source_model_file} -> latest`);
        },
        onError: (err: any) => {
          toast.error(err?.message || "Promotion failed");
        },
      },
    );
  };

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full pb-24">
      <Card className="border-slate-700/30 bg-gradient-to-br from-slate-900/80 via-slate-900/60 to-emerald-950/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-xl">
            <FlaskConical className="h-5 w-5 text-emerald-400" />
            ONNX Training Studio
          </CardTitle>
          <CardDescription>
            Launch retraining jobs, inspect promotion gates, and review produced model files.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <div className="space-y-2">
            <Label>Label Source</Label>
            <Select value={labelSource} onValueChange={(v: any) => setLabelSource(v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="tp_sl">tp_sl</SelectItem>
                <SelectItem value="future_return">future_return</SelectItem>
                <SelectItem value="policy_replay">policy_replay</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Window (hours)</Label>
            <Input value={hours} onChange={(e) => setHours(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Max Samples</Label>
            <Input value={limit} onChange={(e) => setLimit(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Walk-forward Folds</Label>
            <Input value={folds} onChange={(e) => setFolds(e.target.value)} />
          </div>
          <div className="flex items-center justify-between rounded-md border border-slate-700/40 p-3">
            <Label>V4 Pipeline</Label>
            <Switch checked={useV4Pipeline} onCheckedChange={setUseV4Pipeline} />
          </div>
          {useV4Pipeline && (
            <>
              <div className="space-y-2">
                <Label>Horizon (sec)</Label>
                <Input value={horizonSec} onChange={(e) => setHorizonSec(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>TP (bps)</Label>
                <Input value={tpBps} onChange={(e) => setTpBps(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>SL (bps)</Label>
                <Input value={slBps} onChange={(e) => setSlBps(e.target.value)} />
              </div>
            </>
          )}
          <div className="flex items-center justify-between rounded-md border border-slate-700/40 p-3">
            <Label>Drift Check</Label>
            <Switch checked={driftCheck} onCheckedChange={setDriftCheck} />
          </div>
          <div className="flex items-center justify-between rounded-md border border-slate-700/40 p-3">
            <Label>Allow Regression</Label>
            <Switch checked={allowRegression} onCheckedChange={setAllowRegression} />
          </div>
          <div className="md:col-span-2 flex items-end">
            <Button onClick={handleStart} disabled={startMutation.isPending} className="w-full">
              <Play className="mr-2 h-4 w-4" />
              {startMutation.isPending ? "Starting..." : "Start Training"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4 text-emerald-400" />
            Active Model
          </CardTitle>
          <CardDescription>Model currently pointed to by runtime registry latest pointer</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <div><span className="text-muted-foreground">Model:</span> <span className="font-mono">{activeModel?.model_file || "-"}</span></div>
          <div><span className="text-muted-foreground">Config:</span> <span className="font-mono">{activeModel?.config_file || "-"}</span></div>
          <div><span className="text-muted-foreground">Source model:</span> <span className="font-mono">{activeModel?.source_model_file || "-"}</span></div>
          <div><span className="text-muted-foreground">Source config:</span> <span className="font-mono">{activeModel?.source_config_file || "-"}</span></div>
          <div><span className="text-muted-foreground">Promoted at:</span> <span className="font-mono">{activeModel?.promoted_at || "-"}</span></div>
          <div><span className="text-muted-foreground">Promoted from job:</span> <span className="font-mono">{activeModel?.promoted_from_job_id || "-"}</span></div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent Jobs</CardTitle>
            <CardDescription>Newest first, auto-refresh every 5s</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[560px] space-y-2 overflow-y-auto pr-1">
            {jobs.map((job) => {
              const meta = statusMeta[job.status] ?? statusMeta.queued;
              const Icon = meta.icon;
              return (
                <button
                  key={job.id}
                  className={cn(
                    "w-full rounded-md border p-3 text-left transition-colors",
                    selectedJobId === job.id ? "border-emerald-500/50 bg-emerald-500/10" : "border-border hover:bg-muted/40",
                  )}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Icon className={cn("h-4 w-4", meta.color)} />
                      <span className="font-mono text-xs">{job.id.slice(0, 12)}</span>
                    </div>
                    <Badge variant="outline">{job.status}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {job.label_source} • folds={job.stream?.includes("features") ? "streamed" : "custom"} • started {job.started_at}
                  </div>
                </button>
              );
            })}
            {!jobs.length && <div className="text-sm text-muted-foreground">No training jobs yet.</div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Job Detail</CardTitle>
            <CardDescription>
              {selectedJobId ? `Job ${selectedJobId}` : "Select a job"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selectedJob && <div className="text-sm text-muted-foreground">No job selected.</div>}
            {selectedJob && (
              <>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div><span className="text-muted-foreground">Status:</span> {selectedJob.status}</div>
                  <div><span className="text-muted-foreground">Exit:</span> {selectedJob.exit_code ?? "-"}</div>
                  <div><span className="text-muted-foreground">Started:</span> {selectedJob.started_at}</div>
                  <div><span className="text-muted-foreground">Finished:</span> {selectedJob.finished_at ?? "-"}</div>
                </div>
                <div>
                  <Button
                    variant="secondary"
                    onClick={handlePromote}
                    disabled={!canPromoteSelectedJob || promoteMutation.isPending}
                  >
                    {promoteMutation.isPending ? "Promoting..." : "Promote Selected Job"}
                  </Button>
                </div>
                <Separator />
                <div className="space-y-2 rounded-md border border-slate-700/40 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">Promotion Assessment</div>
                    <Badge variant="outline" className={promotionAssessment.tone}>
                      {promotionAssessment.label}
                    </Badge>
                  </div>
                  <div className="space-y-1 text-xs">
                    {(promotionAssessment.reasons ?? []).map((reason: string, idx: number) => (
                      <div key={`${reason}-${idx}`} className="text-muted-foreground">{reason}</div>
                    ))}
                    {Array.isArray((promotionAssessment as any).checks) && (promotionAssessment as any).checks.length > 0 && (
                      <div className="space-y-1 pt-1">
                        {(promotionAssessment as any).checks.map((check: any) => (
                          <div key={check.name} className="flex items-center justify-between">
                            <span className="text-muted-foreground">{check.name}</span>
                            <span className={check.pass ? "text-emerald-400 font-mono" : "text-red-400 font-mono"}>
                              {check.pass ? "pass" : "fail"} ({check.detail})
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <Separator />
                <div className="space-y-2">
                  <div className="text-sm font-medium">Summary</div>
                  {!metricRows.length && <div className="text-sm text-muted-foreground">No summary metrics yet.</div>}
                  {metricRows.map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{k}</span>
                      <span className="font-mono">{typeof v === "number" ? v.toFixed(6) : String(v)}</span>
                    </div>
                  ))}
                  {!!summaryWarnings.length && (
                    <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-100">
                      {summaryWarnings.join(" | ")}
                    </div>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><FileCode2 className="h-4 w-4" /> Produced Files</CardTitle>
            <CardDescription>Artifacts emitted by the selected training run</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {!artifacts.length && <div className="text-sm text-muted-foreground">No artifacts captured yet.</div>}
            {artifacts.map((a, idx) => (
              <div key={`${a.name || a.line}-${idx}`} className="rounded border p-2 text-xs">
                {a.path ? (
                  <>
                    <div className="font-mono">{a.name}</div>
                    <div className="text-muted-foreground">{a.path}</div>
                    <div className="text-muted-foreground">size={a.size_bytes} updated={a.updated_at}</div>
                  </>
                ) : (
                  <div className="font-mono">{a.line}</div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Execution Logs</CardTitle>
            <CardDescription>Tail output from retrain pipeline</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded bg-slate-950 p-3 font-mono text-[11px] text-slate-200 max-h-56 overflow-auto">
              {(stdoutTail.length ? stdoutTail : ["(no stdout)"]).join("\n")}
            </div>
            <div className="rounded bg-rose-950/40 p-3 font-mono text-[11px] text-rose-200 max-h-40 overflow-auto">
              {(stderrTail.length ? stderrTail : ["(no stderr)"]).join("\n")}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
