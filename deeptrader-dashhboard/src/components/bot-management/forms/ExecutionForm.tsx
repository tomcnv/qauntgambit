/**
 * Execution Form Component
 * Order execution settings, stops, and filters
 */

import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Switch } from "../../../components/ui/switch";
import { Separator } from "../../../components/ui/separator";
import type { ExecutionFormState, ThrottleMode } from "../types";
import { THROTTLE_MODES } from "../types";

interface ExecutionFormProps {
  execution: ExecutionFormState;
  setExecution: (execution: ExecutionFormState) => void;
  compact?: boolean;
}

export function ExecutionForm({ execution, setExecution, compact = false }: ExecutionFormProps) {
  const updateField = <K extends keyof ExecutionFormState>(field: K, value: ExecutionFormState[K]) => {
    setExecution({ ...execution, [field]: value });
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Order Type</Label>
          <Select
            value={execution.defaultOrderType}
            onChange={(e) => updateField("defaultOrderType", e.target.value as "market" | "limit")}
            options={[
              { value: "market", label: "Market" },
              { value: "limit", label: "Limit" },
            ]}
          />
        </div>

        <div className="space-y-2">
          <Label>Stop Loss (%)</Label>
          <Input
            type="number"
            min="0.1"
            max="50"
            step="0.1"
            value={execution.stopLossPct}
            onChange={(e) => updateField("stopLossPct", Number(e.target.value))}
          />
        </div>

        <div className="space-y-2">
          <Label>Take Profit (%)</Label>
          <Input
            type="number"
            min="0.1"
            max="100"
            step="0.1"
            value={execution.takeProfitPct}
            onChange={(e) => updateField("takeProfitPct", Number(e.target.value))}
          />
        </div>

        <div className="space-y-2">
          <Label>Max Hold Time (hours)</Label>
          <Input
            type="number"
            min="0.1"
            max="168"
            step="0.1"
            value={execution.maxHoldTimeHours}
            onChange={(e) => updateField("maxHoldTimeHours", Number(e.target.value))}
          />
        </div>

        {!compact && (
          <>
            <div className="space-y-2">
              <Label>Trade Interval (sec)</Label>
              <Input
                type="number"
                min="0"
                max="60"
                value={execution.minTradeIntervalSec}
                onChange={(e) => updateField("minTradeIntervalSec", Number(e.target.value))}
              />
            </div>

            <div className="space-y-2">
              <Label>Execution Timeout (sec)</Label>
              <Input
                type="number"
                min="1"
                max="60"
                value={execution.executionTimeoutSec}
                onChange={(e) => updateField("executionTimeoutSec", Number(e.target.value))}
              />
            </div>

            <div className="space-y-2">
              <Label>Order Intent Max Age (sec)</Label>
              <Input
                type="number"
                min="0"
                max="3600"
                value={execution.orderIntentMaxAgeSec}
                onChange={(e) => updateField("orderIntentMaxAgeSec", Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">0 = disable intent age guard</p>
            </div>
          </>
        )}
      </div>

      <Separator />

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <Label>Trailing Stop</Label>
            <p className="text-xs text-muted-foreground">Enable trailing stop loss</p>
          </div>
          <Switch
            checked={execution.trailingStopEnabled}
            onCheckedChange={(checked) => updateField("trailingStopEnabled", checked)}
          />
        </div>

        {execution.trailingStopEnabled && (
          <div className="space-y-2 pl-4 border-l-2 border-primary/30">
            <Label>Trailing Stop (%)</Label>
            <Input
              type="number"
              min="0.1"
              max="20"
              step="0.1"
              value={execution.trailingStopPct}
              onChange={(e) => updateField("trailingStopPct", Number(e.target.value))}
              className="max-w-32"
            />
          </div>
        )}

        <div className="flex items-center justify-between">
          <div>
            <Label>Volatility Filter</Label>
            <p className="text-xs text-muted-foreground">Pause trading during high volatility</p>
          </div>
          <Switch
            checked={execution.enableVolatilityFilter}
            onCheckedChange={(checked) => updateField("enableVolatilityFilter", checked)}
          />
        </div>
      </div>

      <Separator />

      <div className="space-y-3">
        <div>
          <Label>Throttle Mode</Label>
          <p className="text-xs text-muted-foreground mb-2">Controls trading frequency and cooldown behavior</p>
        </div>
        <div className="grid grid-cols-1 gap-2">
          {THROTTLE_MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              onClick={() => updateField("throttleMode", mode.value as ThrottleMode)}
              className={`flex items-center gap-3 p-3 rounded-lg border transition-colors text-left ${
                execution.throttleMode === mode.value
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-primary/50"
              }`}
            >
              <span className="text-xl">{mode.icon}</span>
              <div className="flex-1">
                <div className="font-medium text-sm">{mode.label}</div>
                <div className="text-xs text-muted-foreground">{mode.description}</div>
              </div>
              {execution.throttleMode === mode.value && (
                <div className="w-2 h-2 rounded-full bg-primary" />
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}




