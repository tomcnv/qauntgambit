import { useEffect, useMemo, useState } from "react";
import { Database, RotateCcw, Activity, Save, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Switch } from "../../../components/ui/switch";
import SettingsPageLayout from "./layout";
import { useDataSettings, useUpdateDataSettings } from "../../../lib/api/hooks";
import type { DataSettings } from "../../../lib/api/types";
import toast from "react-hot-toast";

export default function DataSettingsPage() {
  const [isSaving, setIsSaving] = useState(false);
  const tenantId = useMemo(
    () => import.meta.env.VITE_TENANT_ID || localStorage.getItem("tenant_id") || "default",
    []
  );
  const { data: serverSettings, isLoading } = useDataSettings(tenantId);
  const updateSettings = useUpdateDataSettings();
  const [settings, setSettings] = useState<DataSettings>({
    tenant_id: tenantId,
    trade_history_retention_days: 365,
    replay_snapshot_retention_days: 30,
    backtest_equity_sample_every: 1,
    backtest_max_equity_points: 2000,
    backtest_max_symbol_equity_points: 2000,
    backtest_max_decision_snapshots: 2000,
    backtest_max_position_snapshots: 2000,
    capture_decision_traces: true,
    capture_feature_values: true,
    capture_orderbook: false,
  });

  useEffect(() => {
    if (!serverSettings) return;
    setSettings(serverSettings);
  }, [serverSettings]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await updateSettings.mutateAsync(settings);
      toast.success("Data settings updated");
    } catch (err: any) {
      toast.error(err?.message || "Failed to update data settings");
    } finally {
      setIsSaving(false);
    }
  };

  const toSelectValue = (value: number | null) => (value === null ? "unlimited" : String(value));
  const fromSelectValue = (value: string) => (value === "unlimited" ? null : parseInt(value, 10));

  return (
    <SettingsPageLayout
      title="Data & Storage"
      description="Retention policies, replay capture, and backtest defaults"
      actions={
        <Button onClick={handleSave} disabled={isSaving || isLoading}>
          {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
          Save Changes
        </Button>
      }
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Retention Policies
            </CardTitle>
            <CardDescription>How long data is kept before archiving or deletion</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Trade History Retention</Label>
                <Select
                  value={toSelectValue(settings.trade_history_retention_days)}
                  onChange={(e) =>
                    setSettings({ ...settings, trade_history_retention_days: fromSelectValue(e.target.value) })
                  }
                  options={[
                    { value: "90", label: "90 days" },
                    { value: "180", label: "180 days" },
                    { value: "365", label: "1 year" },
                    { value: "unlimited", label: "Unlimited" },
                  ]}
                />
              </div>
              <div className="space-y-2">
                <Label>Replay Snapshots Retention</Label>
                <Select
                  value={toSelectValue(settings.replay_snapshot_retention_days)}
                  onChange={(e) =>
                    setSettings({ ...settings, replay_snapshot_retention_days: fromSelectValue(e.target.value) })
                  }
                  options={[
                    { value: "7", label: "7 days" },
                    { value: "14", label: "14 days" },
                    { value: "30", label: "30 days" },
                    { value: "90", label: "90 days" },
                  ]}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <RotateCcw className="h-5 w-5" />
              Replay Capture Settings
            </CardTitle>
            <CardDescription>What data is captured for incident replay</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3">
              <ToggleCard
                label="Capture Decision Traces"
                description="Full decision pipeline snapshots"
                checked={settings.capture_decision_traces}
                onChange={(value) => setSettings({ ...settings, capture_decision_traces: value })}
              />
              <ToggleCard
                label="Capture Feature Values"
                description="Signal and indicator values at each decision"
                checked={settings.capture_feature_values}
                onChange={(value) => setSettings({ ...settings, capture_feature_values: value })}
              />
              <ToggleCard
                label="Capture Order Book (L2)"
                description="Top 10 levels of order book"
                checked={settings.capture_orderbook}
                onChange={(value) => setSettings({ ...settings, capture_orderbook: value })}
              />
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Backtesting Defaults
            </CardTitle>
            <CardDescription>Default parameters for new backtest runs</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Equity Sample Every (ticks)</Label>
                <Input
                  type="number"
                  min={1}
                  value={settings.backtest_equity_sample_every}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      backtest_equity_sample_every: Math.max(1, Number(e.target.value || 1)),
                    })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Max Equity Points</Label>
                <Input
                  type="number"
                  min={100}
                  value={settings.backtest_max_equity_points}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      backtest_max_equity_points: Math.max(100, Number(e.target.value || 100)),
                    })
                  }
                />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Max Symbol Equity Points</Label>
                <Input
                  type="number"
                  min={100}
                  value={settings.backtest_max_symbol_equity_points}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      backtest_max_symbol_equity_points: Math.max(100, Number(e.target.value || 100)),
                    })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Max Decision Snapshots</Label>
                <Input
                  type="number"
                  min={100}
                  value={settings.backtest_max_decision_snapshots}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      backtest_max_decision_snapshots: Math.max(100, Number(e.target.value || 100)),
                    })
                  }
                />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Max Position Snapshots</Label>
                <Input
                  type="number"
                  min={100}
                  value={settings.backtest_max_position_snapshots}
                  onChange={(e) =>
                    setSettings({
                      ...settings,
                      backtest_max_position_snapshots: Math.max(100, Number(e.target.value || 100)),
                    })
                  }
                />
              </div>
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
