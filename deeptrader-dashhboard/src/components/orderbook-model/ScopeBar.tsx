/**
 * ScopeBar - Sticky controls for the microstructure model dashboard
 * 
 * Controls:
 * - Time window toggle (5m, 15m, 1h, 24h)
 * - Symbol filter dropdown
 * - Advanced: min confidence slider, min move slider
 * - Data health badge (Fresh/Degraded/Stale)
 */

import { useState } from "react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Slider } from "../ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../ui/collapsible";
import { Separator } from "../ui/separator";
import { ChevronDown, Settings2 } from "lucide-react";
import type { TimeWindow } from "../../types/orderbookModel";

interface ScopeBarProps {
  window: TimeWindow;
  onWindowChange: (window: TimeWindow) => void;
  symbol: string;
  onSymbolChange: (symbol: string) => void;
  availableSymbols: string[];
  minConfidence: number;
  onMinConfidenceChange: (value: number) => void;
  minMove: number;
  onMinMoveChange: (value: number) => void;
  dataHealth: "fresh" | "degraded" | "stale";
  lastUpdate?: string;
}

export function ScopeBar({
  window,
  onWindowChange,
  symbol,
  onSymbolChange,
  availableSymbols,
  minConfidence,
  onMinConfidenceChange,
  minMove,
  onMinMoveChange,
  dataHealth,
  lastUpdate,
}: ScopeBarProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const healthColors = {
    fresh: "bg-emerald-500/20 text-emerald-600 border-emerald-500/30",
    degraded: "bg-amber-500/20 text-amber-600 border-amber-500/30",
    stale: "bg-red-500/20 text-red-600 border-red-500/30",
  };

  return (
    <div className="sticky top-0 z-40 bg-card/95 backdrop-blur-sm border-b">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        {/* Time Window */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Window:</span>
          <div className="flex rounded-lg border bg-muted/50 p-0.5">
            {(["5m", "15m", "1h", "24h"] as const).map((w) => (
              <Button
                key={w}
                variant={window === w ? "default" : "ghost"}
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => onWindowChange(w)}
              >
                {w}
              </Button>
            ))}
          </div>
        </div>

        <Separator orientation="vertical" className="h-6" />

        {/* Symbol Filter */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Symbol:</span>
          <Select value={symbol} onValueChange={onSymbolChange}>
            <SelectTrigger className="h-7 w-[120px] text-xs">
              <SelectValue placeholder="All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Symbols</SelectItem>
              {availableSymbols.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Separator orientation="vertical" className="h-6" />

        {/* Advanced Toggle */}
        <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">
              <Settings2 className="h-3 w-3 mr-1" />
              Advanced
              <ChevronDown
                className={`h-3 w-3 ml-1 transition-transform ${
                  showAdvanced ? "rotate-180" : ""
                }`}
              />
            </Button>
          </CollapsibleTrigger>
        </Collapsible>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Data Health Badge */}
        <Badge variant="outline" className={healthColors[dataHealth]}>
          {dataHealth === "fresh" && "● Fresh"}
          {dataHealth === "degraded" && "◐ Degraded"}
          {dataHealth === "stale" && "○ Stale"}
        </Badge>

        {lastUpdate && (
          <span className="text-[10px] text-muted-foreground">
            Updated {lastUpdate}
          </span>
        )}
      </div>

      {/* Advanced Controls */}
      <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
        <CollapsibleContent>
          <div className="flex flex-wrap items-center gap-6 px-4 py-3 border-t bg-muted/30">
            {/* Min Confidence Slider */}
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                Min Confidence:
              </span>
              <Slider
                value={[minConfidence]}
                onValueChange={([v]) => onMinConfidenceChange(v)}
                min={0.5}
                max={0.95}
                step={0.05}
                className="w-[120px]"
              />
              <span className="text-xs font-mono w-[40px]">
                {(minConfidence * 100).toFixed(0)}%
              </span>
            </div>

            {/* Min Move Slider */}
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                Min Move (bps):
              </span>
              <Slider
                value={[minMove]}
                onValueChange={([v]) => onMinMoveChange(v)}
                min={0}
                max={10}
                step={0.5}
                className="w-[120px]"
              />
              <span className="text-xs font-mono w-[40px]">{minMove.toFixed(1)}</span>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

