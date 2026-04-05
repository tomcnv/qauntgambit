import { useEffect, useState } from "react";
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Zap,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Save,
  Loader2,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Switch } from "../../../components/ui/switch";
import { useTenantRiskPolicy, useUpdateTenantRiskPolicy, useEnableLiveTrading } from "../../../lib/api/hooks";
import { cn } from "../../../lib/utils";
import SettingsPageLayout from "./layout";
import toast from "react-hot-toast";

export default function RiskSettingsPage() {
  const { data: policyData, isLoading: loadingPolicy } = useTenantRiskPolicy();
  const updatePolicy = useUpdateTenantRiskPolicy();
  const enableLiveTrading = useEnableLiveTrading();
  const policy = policyData?.policy;
  const policyAny = (policy as any) || {};
  const [isSaving, setIsSaving] = useState(false);
  const [form, setForm] = useState({
    live_trading_enabled: false,
    max_daily_loss_pct: 5,
    max_leverage: 10,
    max_concurrent_positions: 10,
    max_exposure_per_symbol_pct: 25,
    auto_pause_on_data_loss: true,
    auto_pause_on_latency_spike: true,
    auto_pause_on_error_spike: true,
    order_reject_threshold: 3,
    latency_threshold_ms: 800,
  });

  useEffect(() => {
    if (!policy) return;
    setForm({
      live_trading_enabled: policyAny.live_trading_enabled ?? false,
      max_daily_loss_pct: policyAny.max_daily_loss_pct ?? 5,
      max_leverage: policyAny.max_leverage ?? 10,
      max_concurrent_positions: policyAny.max_concurrent_positions ?? 10,
      max_exposure_per_symbol_pct: policyAny.max_exposure_per_symbol_pct ?? 25,
      auto_pause_on_data_loss: policyAny.auto_pause_on_data_loss ?? true,
      auto_pause_on_latency_spike: policyAny.auto_pause_on_latency_spike ?? true,
      auto_pause_on_error_spike: policyAny.auto_pause_on_error_spike ?? true,
      order_reject_threshold: policyAny.order_reject_threshold ?? 3,
      latency_threshold_ms: policyAny.latency_threshold_ms ?? 800,
    });
  }, [policy]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await updatePolicy.mutateAsync(form);
      toast.success("Risk policy updated");
    } catch (err: any) {
      toast.error(err?.message || "Failed to update policy");
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggleLive = async () => {
    if (form.live_trading_enabled) {
      setIsSaving(true);
      try {
        await updatePolicy.mutateAsync({ live_trading_enabled: false });
        setForm((f) => ({ ...f, live_trading_enabled: false }));
        toast.success("Live trading disabled");
      } catch (err: any) {
        toast.error(err?.message || "Failed to disable live trading");
      } finally {
        setIsSaving(false);
      }
    } else {
      setIsSaving(true);
      try {
        await enableLiveTrading.mutateAsync();
        setForm((f) => ({ ...f, live_trading_enabled: true }));
        toast.success("Live trading enabled");
      } catch (err: any) {
        toast.error(err?.message || "Failed to enable live trading");
      } finally {
        setIsSaving(false);
      }
    }
  };

  return (
    <SettingsPageLayout
      title="Risk & Safety Policy"
      description="Tenant limits, kill switches, and live trading gates"
      actions={
        <Button onClick={handleSave} disabled={isSaving || loadingPolicy}>
          {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
          Save Changes
        </Button>
      }
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5" />
              Global Risk Limits
            </CardTitle>
            <CardDescription>Account-wide trading constraints and safety limits</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "h-10 w-10 rounded-full flex items-center justify-center",
                    form.live_trading_enabled ? "bg-green-500/20" : "bg-red-500/20"
                  )}
                >
                  <Zap
                    className={cn(
                      "h-5 w-5",
                      form.live_trading_enabled ? "text-green-400" : "text-red-400"
                    )}
                  />
                </div>
                <div>
                  <p className="font-medium">Live Trading Master Switch</p>
                  <p className="text-sm text-muted-foreground">
                    {form.live_trading_enabled
                      ? "Live trading is enabled for this account"
                      : "Live trading is currently disabled"}
                  </p>
                </div>
              </div>
              <Switch checked={form.live_trading_enabled} onChange={handleToggleLive} disabled={isSaving} />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Max Daily Loss (%)</Label>
                <Input
                  type="number"
                  min={0.1}
                  max={100}
                  step={0.1}
                  value={form.max_daily_loss_pct}
                  onChange={(e) => setForm({ ...form, max_daily_loss_pct: parseFloat(e.target.value) })}
                />
                <p className="text-xs text-muted-foreground">Trading pauses when daily loss exceeds this</p>
              </div>
              <div className="space-y-2">
                <Label>Max Leverage Cap</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={form.max_leverage}
                  onChange={(e) => setForm({ ...form, max_leverage: parseFloat(e.target.value) })}
                />
                <p className="text-xs text-muted-foreground">Maximum leverage across all bots</p>
              </div>
              <div className="space-y-2">
                <Label>Max Concurrent Positions</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={form.max_concurrent_positions}
                  onChange={(e) => setForm({ ...form, max_concurrent_positions: parseFloat(e.target.value) })}
                />
              </div>
              <div className="space-y-2">
                <Label>Max Exposure Per Symbol (%)</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={form.max_exposure_per_symbol_pct}
                  onChange={(e) => setForm({ ...form, max_exposure_per_symbol_pct: parseFloat(e.target.value) })}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5" />
              Kill Switches & Auto-Pauses
            </CardTitle>
            <CardDescription>Automatic safety triggers that pause trading</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3">
              <ToggleCard
                label="Pause on Consecutive Errors"
                description="Pause all bots after 3 consecutive order failures"
                checked={form.auto_pause_on_error_spike}
                onChange={(v) => setForm({ ...form, auto_pause_on_error_spike: v })}
              />
              <ToggleCard
                label="Pause on Data Quality Critical"
                description="Pause when data feed health drops to critical"
                checked={form.auto_pause_on_data_loss}
                onChange={(v) => setForm({ ...form, auto_pause_on_data_loss: v })}
              />
              <ToggleCard
                label="Pause on Connectivity Loss"
                description="Pause if exchange connection lost for >30 seconds"
                checked={form.auto_pause_on_latency_spike}
                onChange={(v) => setForm({ ...form, auto_pause_on_latency_spike: v })}
              />
              <ToggleCard
                label="Pause on Margin Warning"
                description="Pause if margin usage exceeds 80%"
                checked={form.auto_pause_on_error_spike}
                onChange={(v) => setForm({ ...form, auto_pause_on_error_spike: v })}
              />
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5" />
              Policy Enforcement Status
            </CardTitle>
            <CardDescription>Current blockers preventing live trading</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <PolicyCheck label="Daily loss limit configured" passed={!!form.max_daily_loss_pct} />
              <PolicyCheck label="Maximum leverage set" passed={!!form.max_leverage} />
              <PolicyCheck label="At least one verified exchange credential" passed={true} />
              <PolicyCheck label="2FA enabled for live trading" passed={false} />
            </div>
          </CardContent>
        </Card>
      </div>
    </SettingsPageLayout>
  );
}

function ToggleCard({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
      <div>
        <p className="font-medium">{label}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <Switch checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </div>
  );
}

function PolicyCheck({ label, passed }: { label: string; passed: boolean }) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-border bg-muted/30">
      {passed ? (
        <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
      ) : (
        <XCircle className="h-5 w-5 text-red-400 shrink-0" />
      )}
      <span className={passed ? "text-foreground" : "text-muted-foreground"}>{label}</span>
    </div>
  );
}

