import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Loader2, Save, Info, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Label } from "../../components/ui/label";
import { Input } from "../../components/ui/input";
import { Switch } from "../../components/ui/switch";
import { Separator } from "../../components/ui/separator";
import { useSignalConfig, useSignalLabData } from "../../lib/api/hooks";
import { updateSignalConfig } from "../../lib/api/client";
import { SignalConfig } from "../../lib/api/types";
import { Badge } from "../../components/ui/badge";
import { cn } from "../../lib/utils";

const formatReason = (reason: string) => reason.replace(/_/g, " ");

export default function SignalCustomizationPage() {
  const queryClient = useQueryClient();
  const { data: signalLabData } = useSignalLabData();
  const { data: signalConfigData, isLoading } = useSignalConfig();
  const [formConfig, setFormConfig] = useState<SignalConfig | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    if (signalConfigData?.config && !formConfig) {
      setFormConfig(signalConfigData.config);
    }
  }, [signalConfigData, formConfig]);

  useEffect(() => {
    if (formConfig && signalConfigData?.config) {
      setHasChanges(JSON.stringify(formConfig) !== JSON.stringify(signalConfigData.config));
    }
  }, [formConfig, signalConfigData]);

  const updateConfigMutation = useMutation({
    mutationFn: updateSignalConfig,
    onSuccess: (data) => {
      toast.success("Signal configuration updated successfully!");
      queryClient.invalidateQueries({ queryKey: ["signal-config"] });
      setFormConfig(data.config);
    },
    onError: (error: Error) => {
      toast.error(`Failed to update configuration: ${error.message}`);
    },
  });

  const handleChange = (key: keyof SignalConfig, value: any) => {
    setFormConfig((prev: SignalConfig | null) => (prev ? { ...prev, [key]: value } : null));
  };

  const handleNumberChange = (key: keyof SignalConfig, value: string) => {
    const numValue = parseFloat(value);
    if (!isNaN(numValue)) {
      setFormConfig((prev: SignalConfig | null) => (prev ? { ...prev, [key]: numValue } : null));
    }
  };

  const handleStageChange = (stageKey: string, field: string, value: any) => {
    setFormConfig((prev: SignalConfig | null) => {
      if (!prev) return null;
      const stages: Record<string, any> = { ...(prev.stages as any) };
      stages[stageKey] = { ...stages[stageKey], [field]: value };
      return { ...prev, stages };
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (formConfig && hasChanges) {
      updateConfigMutation.mutate(formConfig);
    }
  };

  const stageRejections = signalLabData?.snapshot?.stageRejections ?? {};
  const rejectionCounts = Object.entries(stageRejections).reduce((acc, [stage, reasons]) => {
    const total = Object.values(reasons as Record<string, number>).reduce((sum, count) => sum + count, 0);
    acc[stage] = total;
    return acc;
  }, {} as Record<string, number>);

  if (isLoading || !formConfig) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="ml-3 text-muted-foreground">Loading signal configuration...</p>
      </div>
    );
  }

  const isBusy = updateConfigMutation.isPending;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Signal Customization</h1>
          <p className="text-sm text-muted-foreground">
            Configure signal generation parameters, filters, and stage settings
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

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Signal Generation Parameters */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Signal Generation
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="minConfirmations">Minimum Confirmations</Label>
              <Input
                id="minConfirmations"
                type="number"
                value={formConfig.minConfirmations}
                onChange={(e) => handleNumberChange("minConfirmations", e.target.value)}
                min={1}
                max={10}
                step={1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">
                Minimum number of confirmations required for a signal (1-10)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="minRiskReward">Minimum Risk/Reward Ratio</Label>
              <Input
                id="minRiskReward"
                type="number"
                value={formConfig.minRiskReward}
                onChange={(e) => handleNumberChange("minRiskReward", e.target.value)}
                min={1.0}
                max={10.0}
                step={0.1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">
                Minimum risk/reward ratio (e.g., 1.5 = 1.5x reward for 1x risk)
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Cooldown Settings */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Cooldown Settings
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-6 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="standardCooldownSec">Standard Cooldown (seconds)</Label>
              <Input
                id="standardCooldownSec"
                type="number"
                value={formConfig.standardCooldownSec}
                onChange={(e) => handleNumberChange("standardCooldownSec", e.target.value)}
                min={0}
                max={300}
                step={1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">Cooldown after normal signal</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="lossCooldownSec">Loss Cooldown (seconds)</Label>
              <Input
                id="lossCooldownSec"
                type="number"
                value={formConfig.lossCooldownSec}
                onChange={(e) => handleNumberChange("lossCooldownSec", e.target.value)}
                min={0}
                max={600}
                step={1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">Extended cooldown after a loss</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="chopCooldownSec">Chop Cooldown (seconds)</Label>
              <Input
                id="chopCooldownSec"
                type="number"
                value={formConfig.chopCooldownSec}
                onChange={(e) => handleNumberChange("chopCooldownSec", e.target.value)}
                min={0}
                max={600}
                step={1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">Cooldown during choppy market conditions</p>
            </div>
          </CardContent>
        </Card>

        {/* User Filters */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              User Filters
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="minConfidenceThreshold">Minimum Confidence Threshold</Label>
              <Input
                id="minConfidenceThreshold"
                type="number"
                value={formConfig.minConfidenceThreshold}
                onChange={(e) => handleNumberChange("minConfidenceThreshold", e.target.value)}
                min={0}
                max={10}
                step={0.1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">Minimum AI confidence (0-10 scale)</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="minDataCompleteness">Minimum Data Completeness</Label>
              <Input
                id="minDataCompleteness"
                type="number"
                value={formConfig.minDataCompleteness}
                onChange={(e) => handleNumberChange("minDataCompleteness", e.target.value)}
                min={0}
                max={1}
                step={0.01}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">Minimum data completeness (0.0-1.0)</p>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-4">
              <Label htmlFor="requireDataQuality" className="!text-sm">
                Require Data Quality
                <p className="text-xs text-muted-foreground">Reject signals if data quality is poor</p>
              </Label>
              <Switch
                id="requireDataQuality"
                checked={formConfig.requireDataQuality}
                onChange={(e) => handleChange("requireDataQuality", e.target.checked)}
                disabled={isBusy}
              />
            </div>
          </CardContent>
        </Card>

        {/* Stage Configuration */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Stage Configuration
            </CardTitle>
            <p className="mt-2 text-xs text-muted-foreground">
              Enable or disable decision pipeline stages and configure their parameters
            </p>
          </CardHeader>
          <CardContent className="space-y-6">
            {Object.entries((formConfig.stages as Record<string, any>) || {}).map(([stageKey, stageConfig]) => {
              const stageCfg: any = stageConfig || {};
              const rejectionCount = rejectionCounts[stageKey] || 0;
              return (
                <div key={stageKey} className="space-y-4 rounded-lg border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Label htmlFor={`stage-${stageKey}-enabled`} className="text-base font-semibold">
                        {formatReason(stageKey)}
                      </Label>
                      {rejectionCount > 0 && (
                        <Badge variant="outline" className="text-xs">
                          {rejectionCount} rejections
                        </Badge>
                      )}
                    </div>
                    <Switch
                      id={`stage-${stageKey}-enabled`}
                      checked={stageCfg?.enabled !== false}
                      onChange={(e) => handleStageChange(stageKey, "enabled", e.target.checked)}
                      disabled={isBusy}
                    />
                  </div>

                  {stageCfg?.enabled !== false && (
                    <div className="grid gap-4 md:grid-cols-2">
                      {stageCfg.minConfirmations !== undefined && (
                        <div className="space-y-2">
                          <Label htmlFor={`stage-${stageKey}-minConfirmations`}>Min Confirmations</Label>
                          <Input
                            id={`stage-${stageKey}-minConfirmations`}
                            type="number"
                            value={stageCfg.minConfirmations}
                            onChange={(e) =>
                              handleStageChange(stageKey, "minConfirmations", parseFloat(e.target.value))
                            }
                            min={1}
                            max={10}
                            step={1}
                            disabled={isBusy}
                          />
                        </div>
                      )}

                      {stageCfg.minRiskReward !== undefined && (
                        <div className="space-y-2">
                          <Label htmlFor={`stage-${stageKey}-minRiskReward`}>Min Risk/Reward</Label>
                          <Input
                            id={`stage-${stageKey}-minRiskReward`}
                            type="number"
                            value={stageCfg.minRiskReward}
                            onChange={(e) =>
                              handleStageChange(stageKey, "minRiskReward", parseFloat(e.target.value))
                            }
                            min={1.0}
                            max={10.0}
                            step={0.1}
                            disabled={isBusy}
                          />
                        </div>
                      )}

                      {stageCfg.minConfidence !== undefined && (
                        <div className="space-y-2">
                          <Label htmlFor={`stage-${stageKey}-minConfidence`}>Min Confidence</Label>
                          <Input
                            id={`stage-${stageKey}-minConfidence`}
                            type="number"
                            value={stageCfg.minConfidence}
                            onChange={(e) =>
                              handleStageChange(stageKey, "minConfidence", parseFloat(e.target.value))
                            }
                            min={0}
                            max={1}
                            step={0.01}
                            disabled={isBusy}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Rejection Thresholds */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Rejection Thresholds
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="maxRejectionsPerSymbol">Max Rejections Per Symbol</Label>
              <Input
                id="maxRejectionsPerSymbol"
                type="number"
                value={formConfig.maxRejectionsPerSymbol || 10}
                onChange={(e) => handleNumberChange("maxRejectionsPerSymbol", e.target.value)}
                min={1}
                max={100}
                step={1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">
                Maximum rejections per symbol before pausing that symbol
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="maxRejectionsPerStage">Max Rejections Per Stage</Label>
              <Input
                id="maxRejectionsPerStage"
                type="number"
                value={formConfig.maxRejectionsPerStage || 50}
                onChange={(e) => handleNumberChange("maxRejectionsPerStage", e.target.value)}
                min={1}
                max={500}
                step={1}
                disabled={isBusy}
              />
              <p className="text-xs text-muted-foreground">
                Maximum rejections per stage before triggering alert
              </p>
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  );
}

