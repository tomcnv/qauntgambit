import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Loader2, Save, TrendingUp, TrendingDown, AlertCircle, Clock, DollarSign } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Label } from "../../components/ui/label";
import { Input } from "../../components/ui/input";
import { Switch } from "../../components/ui/switch";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { useAllocatorConfig, useSignalLabData } from "../../lib/api/hooks";
import { updateAllocatorConfig } from "../../lib/api/client";
import type { AllocatorConfig, AllocatorSnapshot, AllocatorPositionScore } from "../../lib/api/types";
import { cn } from "../../lib/utils";

const formatAction = (action: string) => {
  const actions: Record<string, string> = {
    accept: "Accept",
    reject: "Reject",
    preempt: "Preempt",
    defer: "Defer",
    hold: "Hold",
  };
  return actions[action.toLowerCase()] || action;
};

const getActionColor = (action: string) => {
  switch (action.toLowerCase()) {
    case "accept":
      return "bg-emerald-500/20 text-emerald-300 border-emerald-400/30";
    case "preempt":
      return "bg-amber-500/20 text-amber-300 border-amber-400/30";
    case "reject":
      return "bg-rose-500/20 text-rose-300 border-rose-400/30";
    case "defer":
      return "bg-blue-500/20 text-blue-300 border-blue-400/30";
    case "hold":
      return "bg-gray-500/20 text-gray-300 border-gray-400/30";
    default:
      return "bg-gray-500/20 text-gray-300 border-gray-400/30";
  }
};

const AllocationSnapshot = ({ snapshot }: { snapshot: AllocatorSnapshot }) => {
  const positionScores = snapshot.position_scores || [];
  const stats = snapshot.stats || {};
  const metrics = snapshot.metrics || {};

  if (positionScores.length === 0) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/5 p-8 text-center">
        <p className="text-muted-foreground">No active positions to allocate</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Active Positions</p>
            <p className="mt-2 text-3xl font-semibold">{positionScores.length}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Total Evaluations</p>
            <p className="mt-2 text-3xl font-semibold">{stats.evaluations || 0}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Preemptions</p>
            <p className="mt-2 text-3xl font-semibold">{stats.preempts || 0}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Accept Rate</p>
            <p className="mt-2 text-3xl font-semibold">
              {(() => {
                const evals = Number(stats.evaluations ?? 0);
                const accepts = Number(stats.accepts ?? 0);
                return evals > 0 ? ((accepts / evals) * 100).toFixed(1) : "0.0";
              })()}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Position Scores */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">
          Position Scores
        </h3>
        {positionScores.map((position, idx) => (
          <div
            key={`${position.symbol}-${idx}`}
            className="rounded-lg border border-white/10 bg-white/5 p-4"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div>
                  <p className="font-semibold text-white">{position.symbol}</p>
                  <p className="text-xs text-muted-foreground">
                    {position.profile_id || "unassigned"} • {position.side}
                  </p>
                </div>
                <Badge
                  variant={position.side === "long" ? "success" : "warning"}
                  className="rounded-full"
                >
                  {position.side}
                </Badge>
              </div>
              <div className="flex items-center gap-4 text-sm">
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">Score</p>
                  <p className="font-semibold text-white">{position.score.toFixed(3)}</p>
                </div>
                {position.momentum_score !== undefined && (
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Momentum</p>
                    <p className="font-semibold text-white">{position.momentum_score.toFixed(3)}</p>
                  </div>
                )}
                {position.unrealized_pnl !== undefined && (
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">PnL</p>
                    <p
                      className={cn(
                        "font-semibold",
                        position.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"
                      )}
                    >
                      {position.unrealized_pnl >= 0 ? "+" : ""}
                      {position.unrealized_pnl.toFixed(2)}
                    </p>
                  </div>
                )}
                {position.age_sec !== undefined && (
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Age</p>
                    <p className="font-semibold text-white">
                      {position.age_sec < 60
                        ? `${Math.floor(position.age_sec)}s`
                        : `${Math.floor(position.age_sec / 60)}m`}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const ActivityLog = ({ snapshot }: { snapshot: AllocatorSnapshot }) => {
  const lastDecision = snapshot.last_decision;
  const stats = snapshot.stats || {};

  if (!lastDecision) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/5 p-8 text-center">
        <p className="text-muted-foreground">No recent allocator decisions</p>
      </div>
    );
  }

  const action = String(lastDecision.action_type ?? lastDecision.action ?? "unknown");
  const symbolText = lastDecision.symbol ? String(lastDecision.symbol) : "N/A";
  const reasonText =
    lastDecision.reason !== undefined && lastDecision.reason !== null
      ? String(lastDecision.reason).replace(/_/g, " ")
      : null;
  const scoreVal = Number(lastDecision.score);
  const timestampRaw = lastDecision.timestamp ?? Date.now();
  const timestampNum = Number(timestampRaw);
  const safeTimestamp = Number.isFinite(timestampNum) ? timestampNum : Date.now();
  const timestampMs = safeTimestamp > 1e12 ? safeTimestamp : safeTimestamp * 1000;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">
        Recent Decisions
      </h3>
      <div className="rounded-lg border border-white/10 bg-white/5 p-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <Badge className={cn("rounded-full px-3 py-1", getActionColor(action))}>
                {formatAction(action)}
              </Badge>
              <p className="font-semibold text-white">{symbolText}</p>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {new Date(Number(timestampMs)).toLocaleString()}
            </p>
            {reasonText && (
              <p className="mt-2 text-sm text-muted-foreground">
                Reason: {reasonText}
              </p>
            )}
          </div>
          {Number.isFinite(scoreVal) && (
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Score</p>
              <p className="text-lg font-semibold text-white">{scoreVal.toFixed(3)}</p>
            </div>
          )}
        </div>
      </div>

      {/* Decision Statistics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-white/10 bg-white/5 p-3">
          <p className="text-xs text-muted-foreground">Accepts</p>
          <p className="mt-1 text-xl font-semibold text-emerald-400">{stats.accepts || 0}</p>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/5 p-3">
          <p className="text-xs text-muted-foreground">Rejects</p>
          <p className="mt-1 text-xl font-semibold text-rose-400">{stats.rejects || 0}</p>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/5 p-3">
          <p className="text-xs text-muted-foreground">Preempts</p>
          <p className="mt-1 text-xl font-semibold text-amber-400">{stats.preempts || 0}</p>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/5 p-3">
          <p className="text-xs text-muted-foreground">Defers</p>
          <p className="mt-1 text-xl font-semibold text-blue-400">{stats.defers || 0}</p>
        </div>
      </div>
    </div>
  );
};

export default function PortfolioAllocatorPage() {
  const queryClient = useQueryClient();
  const { data: signalLabData } = useSignalLabData();
  const { data: allocatorConfigData, isLoading } = useAllocatorConfig();
  const [formConfig, setFormConfig] = useState<AllocatorConfig | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  const allocatorSnapshot = signalLabData?.snapshot?.allocator as AllocatorSnapshot | undefined;

  useEffect(() => {
    if (allocatorConfigData?.config && !formConfig) {
      setFormConfig(allocatorConfigData.config);
    }
  }, [allocatorConfigData, formConfig]);

  useEffect(() => {
    if (formConfig && allocatorConfigData?.config) {
      setHasChanges(JSON.stringify(formConfig) !== JSON.stringify(allocatorConfigData.config));
    }
  }, [formConfig, allocatorConfigData]);

  const updateConfigMutation = useMutation({
    mutationFn: updateAllocatorConfig,
    onSuccess: (data) => {
      toast.success("Allocator configuration updated successfully!");
      queryClient.invalidateQueries({ queryKey: ["allocator-config"] });
      setFormConfig(data.config);
    },
    onError: (error: Error) => {
      toast.error(`Failed to update configuration: ${error.message}`);
    },
  });

  const handleChange = (key: keyof AllocatorConfig, value: any) => {
    setFormConfig((prev) => (prev ? { ...prev, [key]: value } : null));
  };

  const handleNumberChange = (key: keyof AllocatorConfig, value: string) => {
    const numValue = parseFloat(value);
    if (!isNaN(numValue)) {
      setFormConfig((prev) => (prev ? { ...prev, [key]: numValue } : null));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (formConfig && hasChanges) {
      updateConfigMutation.mutate(formConfig);
    }
  };

  if (isLoading || !formConfig) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="ml-3 text-muted-foreground">Loading allocator configuration...</p>
      </div>
    );
  }

  const isBusy = updateConfigMutation.isPending;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Capital Allocation</h1>
          <p className="text-sm text-muted-foreground">
            Manage capital allocation, preemption decisions, and portfolio optimization
          </p>
        </div>
        <div className="flex gap-3">
          {hasChanges && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
              <AlertCircle className="h-4 w-4 text-amber-400" />
              <span className="text-xs text-amber-300">Unsaved changes</span>
            </div>
          )}
          <Button onClick={handleSubmit} disabled={!hasChanges || isBusy}>
            {updateConfigMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Save Changes
          </Button>
        </div>
      </div>

      {/* Allocation Snapshot */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Allocation Snapshot
          </CardTitle>
        </CardHeader>
        <CardContent>
          {allocatorSnapshot ? (
            <AllocationSnapshot snapshot={allocatorSnapshot} />
          ) : (
            <p className="text-sm text-muted-foreground">No allocator data available</p>
          )}
        </CardContent>
      </Card>

      {/* Activity Log */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Activity Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          {allocatorSnapshot ? (
            <ActivityLog snapshot={allocatorSnapshot} />
          ) : (
            <p className="text-sm text-muted-foreground">No activity data available</p>
          )}
        </CardContent>
      </Card>

      {/* Settings */}
      <form onSubmit={handleSubmit} className="space-y-8">
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Allocator Settings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-8">
            {/* Feature Toggle */}
            <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-4">
              <div>
                <Label htmlFor="enabled" className="text-base font-semibold">
                  Enable Portfolio Allocator
                </Label>
                <p className="text-xs text-muted-foreground">
                  Enable capital allocation and preemption decisions
                </p>
              </div>
              <Switch
                id="enabled"
                checked={formConfig.enabled}
                onChange={(e) => handleChange("enabled", e.target.checked)}
                disabled={isBusy}
              />
            </div>

            <Separator className="bg-white/10" />

            {/* Preemption Thresholds */}
            <div>
              <h3 className="mb-4 text-lg font-semibold text-white">Preemption Thresholds</h3>
              <div className="grid gap-6 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="scoreUpgradeFactor">Score Upgrade Factor</Label>
                  <Input
                    id="scoreUpgradeFactor"
                    type="number"
                    value={formConfig.scoreUpgradeFactor}
                    onChange={(e) => handleNumberChange("scoreUpgradeFactor", e.target.value)}
                    min={1.0}
                    max={3.0}
                    step={0.05}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Candidate must be this much better to preempt (e.g., 1.25 = 25% better)
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="minScoreToPreempt">Minimum Score to Preempt</Label>
                  <Input
                    id="minScoreToPreempt"
                    type="number"
                    value={formConfig.minScoreToPreempt}
                    onChange={(e) => handleNumberChange("minScoreToPreempt", e.target.value)}
                    min={0}
                    max={1}
                    step={0.05}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Candidate must score at least this to be eligible for preemption
                  </p>
                </div>
              </div>
            </div>

            <Separator className="bg-white/10" />

            {/* Guardrails */}
            <div>
              <h3 className="mb-4 text-lg font-semibold text-white">Guardrails</h3>
              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="minHoldTimeSec">Minimum Hold Time (seconds)</Label>
                  <Input
                    id="minHoldTimeSec"
                    type="number"
                    value={formConfig.minHoldTimeSec}
                    onChange={(e) => handleNumberChange("minHoldTimeSec", e.target.value)}
                    min={0}
                    max={600}
                    step={1}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Minimum time before position can be preempted
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="maxPreemptionsPerSymbolPerMin">
                    Max Preemptions Per Symbol/Min
                  </Label>
                  <Input
                    id="maxPreemptionsPerSymbolPerMin"
                    type="number"
                    value={formConfig.maxPreemptionsPerSymbolPerMin}
                    onChange={(e) =>
                      handleNumberChange("maxPreemptionsPerSymbolPerMin", e.target.value)
                    }
                    min={1}
                    max={10}
                    step={1}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Rate limit per symbol to prevent churn
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="maxPreemptionsPerMin">Max Preemptions Global/Min</Label>
                  <Input
                    id="maxPreemptionsPerMin"
                    type="number"
                    value={formConfig.maxPreemptionsPerMin}
                    onChange={(e) => handleNumberChange("maxPreemptionsPerMin", e.target.value)}
                    min={1}
                    max={20}
                    step={1}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">Global rate limit across all symbols</p>
                </div>
              </div>
            </div>

            <Separator className="bg-white/10" />

            {/* Stale Slot Configuration */}
            <div>
              <h3 className="mb-4 text-lg font-semibold text-white">Stale Slot Detection</h3>
              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="staleSlotAgeSec">Stale Slot Age (seconds)</Label>
                  <Input
                    id="staleSlotAgeSec"
                    type="number"
                    value={formConfig.staleSlotAgeSec}
                    onChange={(e) => handleNumberChange("staleSlotAgeSec", e.target.value)}
                    min={0}
                    max={600}
                    step={1}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Consider slot stale after this age
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="staleSlotMomentumThreshold">Momentum Threshold</Label>
                  <Input
                    id="staleSlotMomentumThreshold"
                    type="number"
                    value={formConfig.staleSlotMomentumThreshold}
                    onChange={(e) =>
                      handleNumberChange("staleSlotMomentumThreshold", e.target.value)
                    }
                    min={0}
                    max={1}
                    step={0.05}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Momentum score below this = stale
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="staleSlotUpgradeFactor">Stale Slot Upgrade Factor</Label>
                  <Input
                    id="staleSlotUpgradeFactor"
                    type="number"
                    value={formConfig.staleSlotUpgradeFactor}
                    onChange={(e) => handleNumberChange("staleSlotUpgradeFactor", e.target.value)}
                    min={1.0}
                    max={2.0}
                    step={0.05}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Relaxed upgrade factor for stale slots
                  </p>
                </div>

                <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-4 md:col-span-3">
                  <Label htmlFor="staleSlotAllowNegativePnl" className="!text-sm">
                    Allow Negative PnL for Stale Slots
                    <p className="text-xs text-muted-foreground">
                      Require ≤0 PnL to treat position as stale
                    </p>
                  </Label>
                  <Switch
                    id="staleSlotAllowNegativePnl"
                    checked={formConfig.staleSlotAllowNegativePnl}
                      onChange={(e) => handleChange("staleSlotAllowNegativePnl", e.target.checked)}
                    disabled={isBusy}
                  />
                </div>
              </div>
            </div>

            <Separator className="bg-white/10" />

            {/* Transaction Cost Awareness */}
            <div>
              <h3 className="mb-4 text-lg font-semibold text-white">Transaction Cost Awareness</h3>
              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="minExpectedGainUsd">Minimum Expected Gain (USD)</Label>
                  <Input
                    id="minExpectedGainUsd"
                    type="number"
                    value={formConfig.minExpectedGainUsd}
                    onChange={(e) => handleNumberChange("minExpectedGainUsd", e.target.value)}
                    min={0}
                    max={100}
                    step={0.5}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Minimum expected improvement after costs
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="expectedGainMultiplier">Expected Gain Multiplier</Label>
                  <Input
                    id="expectedGainMultiplier"
                    type="number"
                    value={formConfig.expectedGainMultiplier}
                    onChange={(e) => handleNumberChange("expectedGainMultiplier", e.target.value)}
                    min={0}
                    max={1}
                    step={0.01}
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Converts score delta into USD edge estimate
                  </p>
                </div>

                <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-4">
                  <Label htmlFor="requirePositiveExpectedGain" className="!text-sm">
                    Require Positive Expected Gain
                    <p className="text-xs text-muted-foreground">
                      Only preempt if expected gain is positive after costs
                    </p>
                  </Label>
                  <Switch
                    id="requirePositiveExpectedGain"
                    checked={formConfig.requirePositiveExpectedGain}
                      onChange={(e) => handleChange("requirePositiveExpectedGain", e.target.checked)}
                    disabled={isBusy}
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  );
}
