/**
 * Capital Form Component
 * Trading capital, position sizing, and budget preview
 */

import { TrendingUp, Bot, AlertTriangle, Wallet } from "lucide-react";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import type { ExchangeAccountOption, RiskFormState } from "../types";

interface BudgetInfo {
  allocatedToOthers: number;
  otherBotCount: number;
  currentBotAllocation: number;
  totalAllocated: number;
  remainingAllocatable: number | undefined;
  isOverAllocated: boolean;
  overAllocationAmount: number;
}

interface CapitalFormProps {
  tradingCapital: number | "";
  setTradingCapital: (capital: number | "") => void;
  risk: RiskFormState;
  setRisk: (risk: RiskFormState) => void;
  selectedAccount?: ExchangeAccountOption;
  budgetInfo?: BudgetInfo;
  isEditing?: boolean;
  compact?: boolean;
}

export function CapitalForm({
  tradingCapital,
  setTradingCapital,
  risk,
  setRisk,
  selectedAccount,
  budgetInfo,
  isEditing = false,
  compact = false,
}: CapitalFormProps) {
  const updateRisk = <K extends keyof RiskFormState>(field: K, value: RiskFormState[K]) => {
    setRisk({ ...risk, [field]: value });
  };

  // Calculate preview values
  const capital = typeof tradingCapital === "number" ? tradingCapital : 0;
  const previewTradeSize = (capital * risk.positionSizePct) / 100;
  const previewMaxExposure = capital * risk.maxLeverage;

  return (
    <div className="space-y-4">
      {/* Exchange Balance Context */}
      {selectedAccount && (
        <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-primary/20 p-2">
                <Wallet className="h-4 w-4 text-primary" />
              </div>
              <div>
                <span className="text-sm text-muted-foreground">
                  Exchange Balance ({selectedAccount.venue?.toUpperCase()})
                </span>
              </div>
            </div>
            <span className="font-mono font-medium">
              ${Number(selectedAccount.available_balance || 0).toLocaleString("en-US", {
                maximumFractionDigits: 2,
              })}
            </span>
          </div>

          {/* Budget breakdown */}
          {budgetInfo && selectedAccount.available_balance !== undefined && (
            <div className="mt-3 pt-3 border-t border-primary/20 space-y-2 text-sm">
              {budgetInfo.allocatedToOthers > 0 && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground flex items-center gap-1">
                    <Bot className="h-3 w-3" />
                    Other bots ({budgetInfo.otherBotCount})
                  </span>
                  <span className="font-mono text-amber-400">
                    −${budgetInfo.allocatedToOthers.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </span>
                </div>
              )}

              {budgetInfo.remainingAllocatable !== undefined && (
                <div className="flex items-center justify-between font-medium">
                  <span className={budgetInfo.remainingAllocatable <= 0 ? "text-red-400" : "text-green-400"}>
                    {isEditing ? "Available for this bot" : "Remaining for new bot"}
                  </span>
                  <span
                    className={`font-mono ${
                      budgetInfo.remainingAllocatable <= 0 ? "text-red-400" : "text-green-400"
                    }`}
                  >
                    ${budgetInfo.remainingAllocatable.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </span>
                </div>
              )}

              {budgetInfo.isOverAllocated && (
                <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 mt-2">
                  <p className="text-xs text-amber-400 flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3" />
                    Exchange is over-allocated by ${budgetInfo.overAllocationAmount.toLocaleString("en-US", {
                      maximumFractionDigits: 2,
                    })}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Form Fields */}
      <div className={compact ? "grid grid-cols-2 gap-4" : "grid grid-cols-2 gap-4"}>
        <div className="space-y-2">
          <Label>Trading Capital (USD)</Label>
          <Input
            type="number"
            min="10"
            value={tradingCapital}
            onChange={(e) => setTradingCapital(e.target.value ? Number(e.target.value) : "")}
            placeholder="1000"
          />
          <p className="text-xs text-muted-foreground">Amount allocated to this bot</p>
        </div>

        <div className="space-y-2">
          <Label>Position Size (%)</Label>
          <Input
            type="number"
            min="1"
            max="100"
            value={risk.positionSizePct}
            onChange={(e) => updateRisk("positionSizePct", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">% of capital per position</p>
        </div>

        <div className="space-y-2">
          <Label>Max Leverage</Label>
          <Input
            type="number"
            min="1"
            max="125"
            value={risk.maxLeverage}
            onChange={(e) => updateRisk("maxLeverage", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Leverage multiplier</p>
        </div>

        <div className="space-y-2">
          <Label>Max Positions</Label>
          <Input
            type="number"
            min="1"
            max="20"
            value={risk.maxPositions}
            onChange={(e) => updateRisk("maxPositions", Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">Concurrent positions limit</p>
        </div>
      </div>

      {/* Preview calculations */}
      {capital > 0 && !compact && (
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2">
          <h4 className="text-sm font-medium flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" />
            Position Impact Preview
          </h4>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Typical Trade Size</span>
              <span className="font-mono">${previewTradeSize.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Max Leveraged Exposure</span>
              <span className="font-mono">${previewMaxExposure.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}





