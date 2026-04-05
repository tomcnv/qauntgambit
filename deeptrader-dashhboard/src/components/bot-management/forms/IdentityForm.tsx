/**
 * Identity Form Component
 * Bot name, description, role, trading mode, and template selection
 */

import { Loader2, FileText, DollarSign, AlertTriangle } from "lucide-react";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Textarea } from "../../../components/ui/textarea";
import { cn } from "../../../lib/utils";
import { ALLOCATOR_ROLES, TRADING_MODES, type TradingMode } from "../types";
import type { StrategyTemplate } from "../../../lib/api/types";

interface IdentityFormProps {
  name: string;
  setName: (name: string) => void;
  description: string;
  setDescription: (description: string) => void;
  allocatorRole: string;
  setAllocatorRole: (role: string) => void;
  tradingMode: TradingMode;
  setTradingMode: (mode: TradingMode) => void;
  templateId: string;
  setTemplateId: (id: string) => void;
  templates?: StrategyTemplate[];
  isLoadingTemplates?: boolean;
  notes?: string;
  setNotes?: (notes: string) => void;
  showNotes?: boolean;
}

export function IdentityForm({
  name,
  setName,
  description,
  setDescription,
  allocatorRole,
  setAllocatorRole,
  tradingMode,
  setTradingMode,
  templateId,
  setTemplateId,
  templates,
  isLoadingTemplates,
  notes,
  setNotes,
  showNotes = true,
}: IdentityFormProps) {
  return (
    <div className="space-y-4">
      {/* Bot Name */}
      <div className="space-y-2">
        <Label>Bot Name *</Label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., Scalper Alpha"
        />
      </div>

      {/* Description */}
      <div className="space-y-2">
        <Label>Description</Label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional description"
        />
      </div>

      {/* Trading Mode - NEW */}
      <div className="space-y-2">
        <Label>Trading Mode</Label>
        <div className="grid grid-cols-2 gap-2">
          {TRADING_MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              onClick={() => setTradingMode(mode.value as TradingMode)}
              className={cn(
                "rounded-lg border p-3 text-left transition-all relative",
                tradingMode === mode.value
                  ? mode.value === "live" 
                    ? "border-green-500 bg-green-500/10"
                    : "border-cyan-500 bg-cyan-500/10"
                  : "border-border hover:border-primary/50"
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-lg">{mode.icon}</span>
                <span className="font-medium text-sm">{mode.label}</span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">{mode.description}</p>
              {mode.value === "live" && (
                <div className="absolute top-2 right-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                </div>
              )}
            </button>
          ))}
        </div>
        {tradingMode === "live" && (
          <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 mt-2">
            <p className="text-xs text-amber-400 flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              Live trading uses real money. Ensure you understand the risks.
            </p>
          </div>
        )}
      </div>

      {/* Allocator Role */}
      <div className="space-y-2">
        <Label>Allocator Role</Label>
        <div className="grid grid-cols-2 gap-2">
          {ALLOCATOR_ROLES.map((role) => (
            <button
              key={role.value}
              type="button"
              onClick={() => setAllocatorRole(role.value)}
              className={cn(
                "rounded-lg border p-3 text-left transition-all",
                allocatorRole === role.value
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-primary/50"
              )}
            >
              <span className="font-medium text-sm">{role.label}</span>
              <p className="text-xs text-muted-foreground mt-1">{role.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Strategy Template */}
      <div className="space-y-2">
        <Label>Strategy Template</Label>
        {isLoadingTemplates ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground p-2 border rounded-lg">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading templates...
          </div>
        ) : !templates || templates.length === 0 ? (
          <div className="text-sm text-muted-foreground p-2 border rounded-lg">
            No strategy templates available
          </div>
        ) : (
          <>
            <Select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              options={[
                { value: "", label: "Custom (no template)" },
                ...templates.map((t) => ({
                  value: t.id,
                  label: `${t.name} (${t.strategy_family || "custom"})`,
                })),
              ]}
            />
            <p className="text-xs text-muted-foreground">
              {templates.length} template{templates.length !== 1 ? "s" : ""} available
            </p>
          </>
        )}
      </div>

      {/* Notes */}
      {showNotes && setNotes && (
        <div className="space-y-2">
          <Label>Notes</Label>
          <Textarea
            value={notes || ""}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional notes about this bot"
            rows={2}
            className="resize-none"
          />
        </div>
      )}
    </div>
  );
}





