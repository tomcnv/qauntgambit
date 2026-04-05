/**
 * Symbols Form Component
 * Symbol selection and quick-add functionality
 */

import { Plus, Check, X } from "lucide-react";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Badge } from "../../../components/ui/badge";
import { cn } from "../../../lib/utils";
import { QUICK_ADD_SYMBOLS } from "../types";

interface SymbolsFormProps {
  enabledSymbols: string[];
  setEnabledSymbols: (symbols: string[]) => void;
  compact?: boolean;
}

export function SymbolsForm({ enabledSymbols, setEnabledSymbols, compact = false }: SymbolsFormProps) {
  const toggleSymbol = (symbol: string) => {
    if (enabledSymbols.includes(symbol)) {
      setEnabledSymbols(enabledSymbols.filter((s) => s !== symbol));
    } else {
      setEnabledSymbols([...enabledSymbols, symbol]);
    }
  };

  const removeSymbol = (symbol: string) => {
    setEnabledSymbols(enabledSymbols.filter((s) => s !== symbol));
  };

  const addCustomSymbol = (input: HTMLInputElement) => {
    const value = input.value.trim().toUpperCase();
    if (value && !enabledSymbols.includes(value)) {
      setEnabledSymbols([...enabledSymbols, value]);
      input.value = "";
    }
  };

  return (
    <div className="space-y-4">
      {/* Current Symbols */}
      <div className="space-y-2">
        <Label>Enabled Symbols ({enabledSymbols.length})</Label>
        <p className="text-xs text-muted-foreground">Symbols this bot is allowed to trade</p>

        <div className="flex flex-wrap gap-2 mt-2 min-h-[32px] p-2 rounded-lg border border-border bg-muted/30">
          {enabledSymbols.length === 0 ? (
            <span className="text-xs text-muted-foreground">No symbols enabled</span>
          ) : (
            enabledSymbols.map((symbol) => (
              <Badge key={symbol} variant="outline" className="gap-1 pr-1">
                {symbol.replace("-USDT-SWAP", "")}
                <button
                  type="button"
                  onClick={() => removeSymbol(symbol)}
                  className="ml-1 hover:text-destructive rounded-full p-0.5 hover:bg-destructive/10"
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))
          )}
        </div>
      </div>

      {/* Quick Add Buttons */}
      <div className="space-y-2">
        <Label className="text-xs text-muted-foreground">Quick Add</Label>
        <div className="flex flex-wrap gap-2">
          {QUICK_ADD_SYMBOLS.map((sym) => {
            const isAdded = enabledSymbols.includes(sym);
            return (
              <button
                key={sym}
                type="button"
                onClick={() => toggleSymbol(sym)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium rounded-lg border transition-all",
                  isAdded
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border hover:border-primary/50 text-muted-foreground hover:text-foreground"
                )}
              >
                {isAdded ? (
                  <Check className="h-3 w-3 inline mr-1" />
                ) : (
                  <Plus className="h-3 w-3 inline mr-1" />
                )}
                {sym.replace("-USDT-SWAP", "")}
              </button>
            );
          })}
        </div>
      </div>

      {/* Custom Symbol Input */}
      {!compact && (
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Add Custom Symbol</Label>
          <Input
            placeholder="e.g., ARB-USDT-SWAP"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustomSymbol(e.currentTarget);
              }
            }}
          />
          <p className="text-xs text-muted-foreground">Press Enter to add</p>
        </div>
      )}
    </div>
  );
}





