import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Save, RotateCcw, Loader2, Key, Settings2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Select } from "../../components/ui/select";
import { Separator } from "../../components/ui/separator";
import { Badge } from "../../components/ui/badge";
import { useTradingSettings, useOrderTypes, TradingSettings } from "../../lib/api/hooks";
import { updateTradingSettings, resetTradingSettings } from "../../lib/api/client";
import ExchangeCredentials from "../../components/exchange-credentials";

const AVAILABLE_TOKENS = [
  "BTC-USDT-SWAP",
  "ETH-USDT-SWAP",
  "SOL-USDT-SWAP",
  "TAO-USDT-SWAP",
  "AVAX-USDT-SWAP",
  "MATIC-USDT-SWAP",
  "DOGE-USDT-SWAP",
  "LINK-USDT-SWAP",
];

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

type SettingsTab = "exchanges" | "trading";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useTradingSettings();
  const { data: orderTypesData } = useOrderTypes();
  const [formData, setFormData] = useState<Partial<TradingSettings>>({});
  const [activeTab, setActiveTab] = useState<SettingsTab>("exchanges");

  const updateMutation = useMutation({
    mutationFn: (data: Partial<TradingSettings>) => updateTradingSettings(data),
    onSuccess: () => {
      toast.success("Settings saved successfully");
      queryClient.invalidateQueries({ queryKey: ["trading-settings"] });
      setFormData({});
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to save settings");
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => resetTradingSettings(),
    onSuccess: () => {
      toast.success("Settings reset to defaults");
      queryClient.invalidateQueries({ queryKey: ["trading-settings"] });
      setFormData({});
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to reset settings");
    },
  });

  const currentSettings = { ...settings, ...formData } as TradingSettings;

  const updateField = (field: keyof TradingSettings, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = () => {
    if (Object.keys(formData).length === 0) {
      toast.error("No changes to save");
      return;
    }
    updateMutation.mutate(formData);
  };

  const handleReset = () => {
    if (window.confirm("Reset all settings to defaults? This cannot be undone.")) {
      resetMutation.mutate();
    }
  };

  if (isLoading || !settings) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const hasChanges = Object.keys(formData).length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.4em] text-muted-foreground">Configuration</p>
          <h1 className="text-3xl font-semibold">Settings</h1>
        </div>
        {activeTab === "trading" && (
          <div className="flex gap-3">
            <Button variant="outline" size="sm" onClick={handleReset} disabled={resetMutation.isPending}>
              {resetMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" />
              )}
              Reset to Defaults
            </Button>
            <Button size="sm" onClick={handleSave} disabled={!hasChanges || updateMutation.isPending}>
              {updateMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              Save Changes
            </Button>
          </div>
        )}
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 rounded-xl bg-white/5 p-1">
        <button
          onClick={() => setActiveTab("exchanges")}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition ${
            activeTab === "exchanges"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-white"
          }`}
        >
          <Key className="h-4 w-4" />
          Exchange Connections
        </button>
        <button
          onClick={() => setActiveTab("trading")}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition ${
            activeTab === "trading"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-white"
          }`}
        >
          <Settings2 className="h-4 w-4" />
          Trading Parameters
        </button>
      </div>

      {/* Exchange Connections Tab */}
      {activeTab === "exchanges" && <ExchangeCredentials />}

      {/* Trading Parameters Tab */}
      {activeTab === "trading" && (
        <>
          {hasChanges && (
            <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
              You have unsaved changes. Click "Save Changes" to apply them.
            </div>
          )}

      {/* Risk Profile */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Risk Profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            {["conservative", "moderate", "aggressive"].map((profile) => (
              <button
                key={profile}
                type="button"
                onClick={() => updateField("riskProfile", profile)}
                className={`rounded-2xl border p-4 text-left transition ${
                  currentSettings.riskProfile === profile
                    ? "border-primary/60 bg-primary/10"
                    : "border-white/5 bg-white/5 hover:border-white/15"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold capitalize text-white">{profile}</span>
                  {currentSettings.riskProfile === profile && (
                    <Badge variant="default" className="uppercase">
                      Active
                    </Badge>
                  )}
                </div>
                {orderTypesData?.riskProfiles[profile] && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {orderTypesData.riskProfiles[profile].description}
                  </p>
                )}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Trading Parameters */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Trading Parameters</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="maxConcurrentPositions">Max Concurrent Positions</Label>
              <Input
                id="maxConcurrentPositions"
                type="number"
                min="1"
                max="20"
                value={currentSettings.maxConcurrentPositions ?? 4}
                onChange={(e) => updateField("maxConcurrentPositions", parseInt(e.target.value, 10))}
              />
              <p className="text-xs text-muted-foreground">Maximum number of open positions at once</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="maxPositionSizePercent">Max Position Size (%)</Label>
              <Input
                id="maxPositionSizePercent"
                type="number"
                min="0.1"
                max="100"
                step="0.1"
                value={currentSettings.maxPositionSizePercent ?? 10}
                onChange={(e) => updateField("maxPositionSizePercent", parseFloat(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">Maximum position size as % of account balance</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="maxTotalExposurePercent">Max Total Exposure (%)</Label>
              <Input
                id="maxTotalExposurePercent"
                type="number"
                min="0.1"
                max="100"
                step="0.1"
                value={currentSettings.maxTotalExposurePercent ?? 40}
                onChange={(e) => updateField("maxTotalExposurePercent", parseFloat(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">Maximum total exposure across all positions</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="aiConfidenceThreshold">AI Confidence Threshold</Label>
              <Input
                id="aiConfidenceThreshold"
                type="number"
                min="0"
                max="10"
                step="0.1"
                value={currentSettings.aiConfidenceThreshold ?? 7.0}
                onChange={(e) => updateField("aiConfidenceThreshold", parseFloat(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">Minimum confidence score (0-10) required for trades</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="tradingInterval">Trading Interval (ms)</Label>
              <Input
                id="tradingInterval"
                type="number"
                min="1000"
                step="1000"
                value={currentSettings.tradingInterval ?? 300000}
                onChange={(e) => updateField("tradingInterval", parseInt(e.target.value, 10))}
              />
              <p className="text-xs text-muted-foreground">Time between trading decisions in milliseconds</p>
            </div>
          </div>

          <Separator className="bg-white/10" />

          <div className="space-y-2">
            <Label>Enabled Trading Symbols</Label>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
              {AVAILABLE_TOKENS.map((token) => (
                <label key={token} className="flex items-center gap-2 rounded-lg border border-white/5 bg-white/5 p-3">
                  <input
                    type="checkbox"
                    checked={currentSettings.enabledTokens?.includes(token) ?? false}
                    onChange={(e) => {
                      const current = currentSettings.enabledTokens ?? [];
                      const updated = e.target.checked
                        ? [...current, token]
                        : current.filter((t) => t !== token);
                      updateField("enabledTokens", updated);
                    }}
                    className="h-4 w-4 rounded border-white/20 text-primary focus:ring-primary/60"
                  />
                  <span className="text-sm text-foreground">{token}</span>
                </label>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Feature Flags */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Feature Flags</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Day Trading Mode</p>
                <p className="text-xs text-muted-foreground">Trade only during market hours</p>
              </div>
              <Switch
                checked={currentSettings.dayTradingEnabled ?? false}
                onChange={(e) => updateField("dayTradingEnabled", e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Scalping Mode</p>
                <p className="text-xs text-muted-foreground">Ultra-fast in-and-out trades</p>
              </div>
              <Switch
                checked={currentSettings.scalpingMode ?? false}
                onChange={(e) => updateField("scalpingMode", e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Trailing Stops</p>
                <p className="text-xs text-muted-foreground">Dynamically adjust stop loss</p>
              </div>
              <Switch
                checked={currentSettings.trailingStopsEnabled ?? false}
                onChange={(e) => updateField("trailingStopsEnabled", e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Partial Profit Taking</p>
                <p className="text-xs text-muted-foreground">Take profits at multiple levels</p>
              </div>
              <Switch
                checked={currentSettings.partialProfitsEnabled ?? false}
                onChange={(e) => updateField("partialProfitsEnabled", e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Time-Based Exits</p>
                <p className="text-xs text-muted-foreground">Close positions after time limit</p>
              </div>
              <Switch
                checked={currentSettings.timeBasedExitsEnabled ?? false}
                onChange={(e) => updateField("timeBasedExitsEnabled", e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Multi-Timeframe Confirmation</p>
                <p className="text-xs text-muted-foreground">Require confirmation from multiple timeframes</p>
              </div>
              <Switch
                checked={currentSettings.multiTimeframeConfirmation ?? false}
                onChange={(e) => updateField("multiTimeframeConfirmation", e.target.checked)}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/5 p-4">
              <div>
                <p className="font-semibold text-white">Leverage Trading</p>
                <p className="text-xs text-muted-foreground">Enable margin/leverage trading</p>
              </div>
              <Switch
                checked={currentSettings.leverageEnabled ?? false}
                onChange={(e) => updateField("leverageEnabled", e.target.checked)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Advanced Settings */}
      {(currentSettings.scalpingMode ||
        currentSettings.dayTradingEnabled ||
        currentSettings.trailingStopsEnabled ||
        currentSettings.partialProfitsEnabled ||
        currentSettings.timeBasedExitsEnabled ||
        currentSettings.multiTimeframeConfirmation ||
        currentSettings.leverageEnabled) && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Advanced Settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {currentSettings.scalpingMode && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-white">Scalping Settings</h3>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="scalpingTargetProfitPercent">Target Profit (%)</Label>
                    <Input
                      id="scalpingTargetProfitPercent"
                      type="number"
                      min="0.1"
                      step="0.1"
                      value={currentSettings.scalpingTargetProfitPercent ?? 0.5}
                      onChange={(e) => updateField("scalpingTargetProfitPercent", parseFloat(e.target.value))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="scalpingMaxHoldingMinutes">Max Holding (minutes)</Label>
                    <Input
                      id="scalpingMaxHoldingMinutes"
                      type="number"
                      min="1"
                      value={currentSettings.scalpingMaxHoldingMinutes ?? 15}
                      onChange={(e) => updateField("scalpingMaxHoldingMinutes", parseInt(e.target.value, 10))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="scalpingMinVolumeMultiplier">Min Volume Multiplier</Label>
                    <Input
                      id="scalpingMinVolumeMultiplier"
                      type="number"
                      min="1"
                      step="0.1"
                      value={currentSettings.scalpingMinVolumeMultiplier ?? 2.0}
                      onChange={(e) => updateField("scalpingMinVolumeMultiplier", parseFloat(e.target.value))}
                    />
                  </div>
                </div>
              </div>
            )}

            {currentSettings.dayTradingEnabled && (
              <>
                <Separator className="bg-white/10" />
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-white">Day Trading Settings</h3>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="dayTradingStartTime">Start Time</Label>
                      <Input
                        id="dayTradingStartTime"
                        type="time"
                        value={currentSettings.dayTradingStartTime ?? "09:30"}
                        onChange={(e) => updateField("dayTradingStartTime", e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="dayTradingEndTime">End Time</Label>
                      <Input
                        id="dayTradingEndTime"
                        type="time"
                        value={currentSettings.dayTradingEndTime ?? "15:30"}
                        onChange={(e) => updateField("dayTradingEndTime", e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="dayTradingMaxHoldingHours">Max Holding (hours)</Label>
                      <Input
                        id="dayTradingMaxHoldingHours"
                        type="number"
                        min="0.5"
                        step="0.5"
                        value={currentSettings.dayTradingMaxHoldingHours ?? 8.0}
                        onChange={(e) => updateField("dayTradingMaxHoldingHours", parseFloat(e.target.value))}
                      />
                    </div>
                    <div className="flex items-center gap-2 pt-8">
                      <Switch
                        checked={currentSettings.dayTradingDaysOnly ?? false}
                        onChange={(e) => updateField("dayTradingDaysOnly", e.target.checked)}
                        label="Weekdays Only"
                      />
                    </div>
                  </div>
                </div>
              </>
            )}

            {currentSettings.trailingStopsEnabled && (
              <>
                <Separator className="bg-white/10" />
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-white">Trailing Stop Settings</h3>
                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="space-y-2">
                      <Label htmlFor="trailingStopActivationPercent">Activation (%)</Label>
                      <Input
                        id="trailingStopActivationPercent"
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={currentSettings.trailingStopActivationPercent ?? 2.0}
                        onChange={(e) => updateField("trailingStopActivationPercent", parseFloat(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="trailingStopCallbackPercent">Callback (%)</Label>
                      <Input
                        id="trailingStopCallbackPercent"
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={currentSettings.trailingStopCallbackPercent ?? 1.0}
                        onChange={(e) => updateField("trailingStopCallbackPercent", parseFloat(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="trailingStopStepPercent">Step (%)</Label>
                      <Input
                        id="trailingStopStepPercent"
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={currentSettings.trailingStopStepPercent ?? 0.5}
                        onChange={(e) => updateField("trailingStopStepPercent", parseFloat(e.target.value))}
                      />
                    </div>
                  </div>
                </div>
              </>
            )}

            {currentSettings.leverageEnabled && (
              <>
                <Separator className="bg-white/10" />
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-white">Leverage Settings</h3>
                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="space-y-2">
                      <Label htmlFor="maxLeverage">Max Leverage</Label>
                      <Input
                        id="maxLeverage"
                        type="number"
                        min="1"
                        max="100"
                        value={currentSettings.maxLeverage ?? 1.0}
                        onChange={(e) => updateField("maxLeverage", parseFloat(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="liquidationBufferPercent">Liquidation Buffer (%)</Label>
                      <Input
                        id="liquidationBufferPercent"
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={currentSettings.liquidationBufferPercent ?? 5.0}
                        onChange={(e) => updateField("liquidationBufferPercent", parseFloat(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="marginCallThresholdPercent">Margin Call Threshold (%)</Label>
                      <Input
                        id="marginCallThresholdPercent"
                        type="number"
                        min="0.1"
                        step="0.1"
                        value={currentSettings.marginCallThresholdPercent ?? 20.0}
                        onChange={(e) => updateField("marginCallThresholdPercent", parseFloat(e.target.value))}
                      />
                    </div>
                  </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      )}
        </>
      )}
    </div>
  );
}
