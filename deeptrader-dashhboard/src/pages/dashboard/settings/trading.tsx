import { useEffect, useMemo, useState } from "react";
import { Activity, DollarSign, TrendingUp, Plus, Save, Loader2, Shield, Zap } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Switch } from "../../../components/ui/switch";
import { Badge } from "../../../components/ui/badge";
import { Separator } from "../../../components/ui/separator";
import SettingsPageLayout from "./layout";
import { useTradingSettings, useUpdateTradingSettings, useResetTradingSettings } from "../../../lib/api/hooks";
import toast from "react-hot-toast";

const TIMEFRAMES = [
  { value: "1m", label: "1 minute" },
  { value: "5m", label: "5 minutes" },
  { value: "15m", label: "15 minutes" },
  { value: "1h", label: "1 hour" },
  { value: "4h", label: "4 hours" },
];

export default function TradingSettingsPage() {
  const { data: tradingSettings, isLoading } = useTradingSettings();
  const updateSettings = useUpdateTradingSettings();
  const resetSettings = useResetTradingSettings();
  const [isSaving, setIsSaving] = useState(false);
  const [settings, setSettings] = useState({
    defaultTimeframe: "5m",
    makerPreference: true,
    postOnly: false,
    reduceOnlyExits: true,
    defaultPositionSizePct: 5,
    defaultMinNotional: 100,
    preferredSymbols: ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"],
    riskProfile: "moderate",
    leverageEnabled: false,
    leverageMode: "isolated",
    maxLeverage: 1,
    perTokenSettings: {} as Record<string, { enabled?: boolean; positionSizePct?: number; leverage?: number }>,
  });
  const [newSymbol, setNewSymbol] = useState("");

  // Map backend trading settings into this simplified UI
  useEffect(() => {
    if (!tradingSettings) return;
    const intervalToTf = (intervalMs: number | undefined) => {
      if (!intervalMs) return "5m";
      if (intervalMs <= 60_000) return "1m";
      if (intervalMs <= 300_000) return "5m";
      if (intervalMs <= 900_000) return "15m";
      if (intervalMs <= 3_600_000) return "1h";
      return "4h";
    };
    const limitSettings = tradingSettings.orderTypeSettings?.limit || {};
    setSettings({
      defaultTimeframe: intervalToTf(tradingSettings.tradingInterval),
      makerPreference: limitSettings.enabled ?? true,
      postOnly: limitSettings.postOnly ?? false,
      reduceOnlyExits: tradingSettings.orderTypeSettings?.stop_loss?.reduceOnly ?? true,
      defaultPositionSizePct: tradingSettings.maxPositionSizePercent ?? 5,
      defaultMinNotional: limitSettings.minNotional ?? 100,
      preferredSymbols: tradingSettings.enabledTokens || ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"],
      riskProfile: tradingSettings.riskProfile || "moderate",
      leverageEnabled: tradingSettings.leverageEnabled ?? false,
      leverageMode: tradingSettings.leverageMode || "isolated",
      maxLeverage: tradingSettings.maxLeverage ?? 1,
      perTokenSettings: tradingSettings.perTokenSettings || {},
    });
  }, [tradingSettings]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const timeframeToInterval = (tf: string) => {
        switch (tf) {
          case "1m":
            return 60_000;
          case "5m":
            return 300_000;
          case "15m":
            return 900_000;
          case "1h":
            return 3_600_000;
          case "4h":
            return 14_400_000;
          default:
            return 300_000;
        }
      };

      const payload = {
        tradingInterval: timeframeToInterval(settings.defaultTimeframe),
        maxPositionSizePercent: settings.defaultPositionSizePct,
        enabledTokens: settings.preferredSymbols,
        riskProfile: settings.riskProfile,
        leverageEnabled: settings.leverageEnabled,
        leverageMode: settings.leverageMode,
        maxLeverage: settings.maxLeverage,
        perTokenSettings: settings.perTokenSettings,
        orderTypeSettings: {
          ...(tradingSettings?.orderTypeSettings || {}),
          limit: {
            ...(tradingSettings?.orderTypeSettings?.limit || {}),
            enabled: settings.makerPreference,
            postOnly: settings.postOnly,
            minNotional: settings.defaultMinNotional,
          },
          stop_loss: {
            ...(tradingSettings?.orderTypeSettings?.stop_loss || {}),
            reduceOnly: settings.reduceOnlyExits,
          },
          take_profit: {
            ...(tradingSettings?.orderTypeSettings?.take_profit || {}),
            reduceOnly: settings.reduceOnlyExits,
          },
        },
      };

      await updateSettings.mutateAsync(payload);
      toast.success("Trading defaults saved");
    } catch (err: any) {
      toast.error(err?.message || "Failed to save trading defaults");
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    setIsSaving(true);
    try {
      const defaults = await resetSettings.mutateAsync();
      const limitSettings = defaults.orderTypeSettings?.limit || {};
      const intervalToTf = (intervalMs: number | undefined) => {
        if (!intervalMs) return "5m";
        if (intervalMs <= 60_000) return "1m";
        if (intervalMs <= 300_000) return "5m";
        if (intervalMs <= 900_000) return "15m";
        if (intervalMs <= 3_600_000) return "1h";
        return "4h";
      };
      setSettings({
        defaultTimeframe: intervalToTf(defaults.tradingInterval),
        makerPreference: limitSettings.enabled ?? true,
        postOnly: limitSettings.postOnly ?? false,
        reduceOnlyExits: defaults.orderTypeSettings?.stop_loss?.reduceOnly ?? true,
        defaultPositionSizePct: defaults.maxPositionSizePercent ?? 5,
        defaultMinNotional: limitSettings.minNotional ?? 100,
        preferredSymbols: defaults.enabledTokens || ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"],
        riskProfile: defaults.riskProfile || "moderate",
        leverageEnabled: defaults.leverageEnabled ?? false,
        leverageMode: defaults.leverageMode || "isolated",
        maxLeverage: defaults.maxLeverage ?? 1,
        perTokenSettings: defaults.perTokenSettings || {},
      });
      toast.success("Trading settings reset to defaults");
    } catch (err: any) {
      toast.error(err?.message || "Failed to reset settings");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <SettingsPageLayout
      title="Trading Defaults"
      description="Default execution behavior, sizing, and symbol universe"
      actions={
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleReset} disabled={isSaving || isLoading}>
            Reset to defaults
          </Button>
          <Button onClick={handleSave} disabled={isSaving || isLoading}>
          {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
          Save Changes
        </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Execution Defaults
            </CardTitle>
            <CardDescription>Default behavior applied to new bots and configurations</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Default Timeframe</Label>
                <Select
                  value={settings.defaultTimeframe}
                  onChange={(e) => setSettings({ ...settings, defaultTimeframe: e.target.value })}
                  options={TIMEFRAMES}
                />
              </div>
            </div>

            <Separator />

            <div className="space-y-4">
              <Label className="text-base">Order Behavior</Label>
              <div className="grid gap-3 md:grid-cols-3">
                <ToggleCard
                  label="Maker Preference"
                  description="Prefer limit orders over market"
                  checked={settings.makerPreference}
                  onChange={(v) => setSettings({ ...settings, makerPreference: v })}
                />
                <ToggleCard
                  label="Post-Only Default"
                  description="Orders fail if would take"
                  checked={settings.postOnly}
                  onChange={(v) => setSettings({ ...settings, postOnly: v })}
                />
                <ToggleCard
                  label="Reduce-Only Exits"
                  description="Exit orders are reduce-only"
                  checked={settings.reduceOnlyExits}
                  onChange={(v) => setSettings({ ...settings, reduceOnlyExits: v })}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <DollarSign className="h-5 w-5" />
              Capital & Sizing Defaults
            </CardTitle>
            <CardDescription>Default position sizing for new configurations</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Default Position Size (%)</Label>
                <Input
                  type="number"
                  min={0.1}
                  max={100}
                  step={0.1}
                  value={settings.defaultPositionSizePct}
                  onChange={(e) =>
                    setSettings({ ...settings, defaultPositionSizePct: parseFloat(e.target.value) })
                  }
                />
                <p className="text-xs text-muted-foreground">Percentage of allocated capital per trade</p>
              </div>
              <div className="space-y-2">
                <Label>Default Min Notional (USD)</Label>
                <Input
                  type="number"
                  min={1}
                  step={1}
                  value={settings.defaultMinNotional}
                  onChange={(e) =>
                    setSettings({ ...settings, defaultMinNotional: parseFloat(e.target.value) })
                  }
                />
                <p className="text-xs text-muted-foreground">Minimum order size in USD equivalent</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              Risk Profile & Leverage
            </CardTitle>
            <CardDescription>Risk posture applied to new configs</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Risk Profile</Label>
                <Select
                  value={settings.riskProfile}
                  onChange={(e) => setSettings({ ...settings, riskProfile: e.target.value })}
                  options={[
                    { value: "conservative", label: "Conservative" },
                    { value: "moderate", label: "Moderate" },
                    { value: "aggressive", label: "Aggressive" },
                  ]}
                />
                <p className="text-xs text-muted-foreground">Guides sizing & protections</p>
              </div>
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <span>Leverage Enabled</span>
                </Label>
                <Switch
                  checked={settings.leverageEnabled}
                  onChange={(e) => setSettings({ ...settings, leverageEnabled: e.target.checked })}
                />
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <div className="space-y-1">
                    <Label>Max Leverage</Label>
                    <Input
                      type="number"
                      min={1}
                      max={125}
                      step={1}
                      value={settings.maxLeverage}
                      onChange={(e) => setSettings({ ...settings, maxLeverage: parseFloat(e.target.value) })}
                      disabled={!settings.leverageEnabled}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label>Leverage Mode</Label>
                    <Select
                      value={settings.leverageMode}
                      onChange={(e) => setSettings({ ...settings, leverageMode: e.target.value })}
                      options={[
                        { value: "isolated", label: "Isolated" },
                        { value: "cross", label: "Cross" },
                      ]}
                      disabled={!settings.leverageEnabled}
                    />
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Symbol Universe Defaults
            </CardTitle>
            <CardDescription>Default symbols for new bot configurations</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {settings.preferredSymbols.map((symbol: string) => (
                <Badge key={symbol} variant="outline" className="text-sm py-1 px-3">
                  {symbol}
                  <button
                    onClick={() =>
                      setSettings({
                        ...settings,
                        preferredSymbols: settings.preferredSymbols.filter((s: string) => s !== symbol),
                      })
                    }
                    className="ml-2 text-muted-foreground hover:text-foreground"
                  >
                    ×
                  </button>
                </Badge>
              ))}
              <div className="flex items-center gap-2">
                <Input
                  placeholder="Add symbol (e.g., BTC-USDT-SWAP)"
                  value={newSymbol}
                  onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                  className="w-56"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (!newSymbol.trim()) return;
                    const sym = newSymbol.trim().toUpperCase();
                    if (!settings.preferredSymbols.includes(sym)) {
                      setSettings({
                        ...settings,
                        preferredSymbols: [...settings.preferredSymbols, sym],
                        perTokenSettings: {
                          ...settings.perTokenSettings,
                          [sym]: settings.perTokenSettings[sym] || { enabled: true, positionSizePct: settings.defaultPositionSizePct, leverage: settings.maxLeverage },
                        },
                      });
                    }
                    setNewSymbol("");
                  }}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Symbol
                </Button>
              </div>
            </div>

            <ToggleCard
              label="Allow New Symbols"
              description="Bots can trade symbols not in the preferred list"
              checked={settings.allowNewSymbols}
              onChange={(v) => setSettings({ ...settings, allowNewSymbols: v })}
            />

            <Separator />

            <div className="space-y-3">
              <Label className="text-sm">Per-Symbol Overrides</Label>
              <div className="space-y-2">
                {settings.preferredSymbols.map((symbol) => {
                  const cfg = settings.perTokenSettings[symbol] || {};
                  return (
                    <div key={symbol} className="p-3 border border-border rounded-lg flex flex-col gap-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-medium">{symbol}</div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">Enabled</span>
                          <Switch
                            checked={cfg.enabled ?? true}
                            onChange={(e) =>
                              setSettings({
                                ...settings,
                                perTokenSettings: {
                                  ...settings.perTokenSettings,
                                  [symbol]: { ...cfg, enabled: e.target.checked },
                                },
                              })
                            }
                          />
                        </div>
                      </div>
                      <div className="grid gap-3 md:grid-cols-3">
                        <div className="space-y-1">
                          <Label>Position Size (%)</Label>
                          <Input
                            type="number"
                            min={0.1}
                            max={100}
                            step={0.1}
                            value={cfg.positionSizePct ?? settings.defaultPositionSizePct}
                            onChange={(e) =>
                              setSettings({
                                ...settings,
                                perTokenSettings: {
                                  ...settings.perTokenSettings,
                                  [symbol]: { ...cfg, positionSizePct: parseFloat(e.target.value) },
                                },
                              })
                            }
                          />
                        </div>
                        <div className="space-y-1">
                          <Label>Leverage</Label>
                          <Input
                            type="number"
                            min={1}
                            max={settings.maxLeverage || 125}
                            step={1}
                            value={cfg.leverage ?? settings.maxLeverage ?? 1}
                            onChange={(e) =>
                              setSettings({
                                ...settings,
                                perTokenSettings: {
                                  ...settings.perTokenSettings,
                                  [symbol]: { ...cfg, leverage: parseFloat(e.target.value) },
                                },
                              })
                            }
                            disabled={!settings.leverageEnabled}
                          />
                        </div>
                        <div className="space-y-1">
                          <Label>Remove</Label>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setSettings({
                                ...settings,
                                preferredSymbols: settings.preferredSymbols.filter((s) => s !== symbol),
                                perTokenSettings: Object.fromEntries(
                                  Object.entries(settings.perTokenSettings).filter(([k]) => k !== symbol)
                                ),
                              });
                            }}
                          >
                            Remove
                          </Button>
                        </div>
                      </div>
                    </div>
                  );
                })}
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

