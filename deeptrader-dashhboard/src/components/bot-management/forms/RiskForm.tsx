/**
 * Risk Form Component
 * Risk limits and position management settings
 */

import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import type { RiskFormState } from "../types";

interface RiskFormProps {
  risk: RiskFormState;
  setRisk: (risk: RiskFormState) => void;
  compact?: boolean;
}

export function RiskForm({ risk, setRisk, compact = false }: RiskFormProps) {
  const updateField = <K extends keyof RiskFormState>(field: K, value: RiskFormState[K]) => {
    setRisk({ ...risk, [field]: value });
  };

  if (compact) {
    return (
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Max Positions</Label>
          <Input
            type="number"
            min="1"
            max="20"
            value={risk.maxPositions}
            onChange={(e) => updateField("maxPositions", Number(e.target.value))}
          />
        </div>
        <div className="space-y-2">
          <Label>Max Leverage</Label>
          <Input
            type="number"
            min="1"
            max="125"
            value={risk.maxLeverage}
            onChange={(e) => updateField("maxLeverage", Number(e.target.value))}
          />
        </div>
        <div className="space-y-2">
          <Label>Daily Loss Limit (%)</Label>
          <Input
            type="number"
            min="0.1"
            max="100"
            step="0.1"
            value={risk.maxDailyLossPct}
            onChange={(e) => updateField("maxDailyLossPct", Number(e.target.value))}
          />
        </div>
        <div className="space-y-2">
          <Label>Leverage Mode</Label>
          <Select
            value={risk.leverageMode}
            onChange={(e) => updateField("leverageMode", e.target.value as "isolated" | "cross")}
            options={[
              { value: "isolated", label: "Isolated" },
              { value: "cross", label: "Cross" },
            ]}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Max Positions</Label>
          <Input
            type="number"
            min="1"
            max="20"
            value={risk.maxPositions}
            onChange={(e) => updateField("maxPositions", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Concurrent positions limit</p>
        </div>

        <div className="space-y-2">
          <Label>Max Leverage</Label>
          <Input
            type="number"
            min="1"
            max="125"
            value={risk.maxLeverage}
            onChange={(e) => updateField("maxLeverage", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Leverage multiplier</p>
        </div>

        <div className="space-y-2">
          <Label>Leverage Mode</Label>
          <Select
            value={risk.leverageMode}
            onChange={(e) => updateField("leverageMode", e.target.value as "isolated" | "cross")}
            options={[
              { value: "isolated", label: "Isolated" },
              { value: "cross", label: "Cross" },
            ]}
          />
          <p className="text-xs text-muted-foreground">Margin mode</p>
        </div>

        <div className="space-y-2">
          <Label>Max Daily Loss (%)</Label>
          <Input
            type="number"
            min="0.1"
            max="100"
            step="0.1"
            value={risk.maxDailyLossPct}
            onChange={(e) => updateField("maxDailyLossPct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Daily loss limit</p>
        </div>

        <div className="space-y-2">
          <Label>Max Total Exposure (%)</Label>
          <Input
            type="number"
            min="10"
            max="100"
            value={risk.maxTotalExposurePct}
            onChange={(e) => updateField("maxTotalExposurePct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Total exposure cap</p>
        </div>

        <div className="space-y-2">
          <Label>Max Exposure/Symbol (%)</Label>
          <Input
            type="number"
            min="1"
            max="100"
            value={risk.maxExposurePerSymbolPct}
            onChange={(e) => updateField("maxExposurePerSymbolPct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Max per-symbol exposure (must be ≥ position size)
          </p>
        </div>

        <div className="space-y-2">
          <Label>Max Positions/Symbol</Label>
          <Input
            type="number"
            min="1"
            max="10"
            value={risk.maxPositionsPerSymbol}
            onChange={(e) => updateField("maxPositionsPerSymbol", Number(e.target.value))}
          />
        </div>

        <div className="space-y-2">
          <Label>Position Size (%)</Label>
          <Input
            type="number"
            min="0.1"
            max="100"
            step="0.1"
            value={risk.positionSizePct}
            onChange={(e) => updateField("positionSizePct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">% of capital per position</p>
        </div>

        <div className="space-y-2">
          <Label>Max Loss/Symbol (%)</Label>
          <Input
            type="number"
            min="0.1"
            max="50"
            step="0.1"
            value={risk.maxDailyLossPerSymbolPct}
            onChange={(e) => updateField("maxDailyLossPerSymbolPct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Per-symbol loss limit</p>
        </div>

        <div className="space-y-2">
          <Label>Min Position Size (USD)</Label>
          <Input
            type="number"
            min="0"
            step="1"
            value={risk.minPositionSizeUsd}
            onChange={(e) => updateField("minPositionSizeUsd", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Rejects trades below this size</p>
        </div>

        <div className="space-y-2">
          <Label>Max Position Size (USD)</Label>
          <Input
            type="number"
            min="0"
            step="1"
            value={risk.maxPositionSizeUsd}
            onChange={(e) => updateField("maxPositionSizeUsd", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">0 = no cap</p>
        </div>

        <div className="space-y-2">
          <Label>Max Positions/Strategy</Label>
          <Input
            type="number"
            min="0"
            max="20"
            value={risk.maxPositionsPerStrategy}
            onChange={(e) => updateField("maxPositionsPerStrategy", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">0 = no limit</p>
        </div>

        <div className="space-y-2">
          <Label>Max Drawdown (%)</Label>
          <Input
            type="number"
            min="0"
            max="100"
            step="0.1"
            value={risk.maxDrawdownPct}
            onChange={(e) => updateField("maxDrawdownPct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Peak-to-trough drawdown limit</p>
        </div>
      </div>
    </div>
  );
}




