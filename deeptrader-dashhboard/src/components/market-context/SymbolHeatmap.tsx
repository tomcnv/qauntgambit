import { useMemo, useState } from "react";
import { AlertTriangle, Grid3X3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { SymbolRow } from "./types";

type Props = {
  symbols: SymbolRow[];
  onSymbolClick: (symbol: SymbolRow) => void;
};

export function SymbolHeatmap({ symbols, onSymbolClick }: Props) {
  const [sortKey, setSortKey] = useState<string>("spread");
  const [showPinnedOnly, setShowPinnedOnly] = useState(false);

  const sortedSymbols = useMemo(() => {
    const filtered = showPinnedOnly ? symbols.filter((s) => s.pinned) : symbols;
    return [...filtered].sort((a, b) => {
      const aVal = a[sortKey as keyof typeof a] as number;
      const bVal = b[sortKey as keyof typeof b] as number;
      return bVal - aVal; // Worst first
    });
  }, [symbols, sortKey, showPinnedOnly]);

  const pinnedSymbols = symbols.filter((s) => s.pinned);

  const getHeatColor = (value: number, baseline: number, invert = false) => {
    const ratio = baseline === 0 ? 0 : value / baseline;
    if (invert) {
      if (ratio < 0.7) return "bg-red-500/20 text-red-500";
      if (ratio < 0.9) return "bg-amber-500/20 text-amber-500";
      return "";
    }
    if (ratio > 1.5) return "bg-red-500/20 text-red-500";
    if (ratio > 1.2) return "bg-amber-500/20 text-amber-500";
    return "";
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Grid3X3 className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">Symbol Heatmap</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={showPinnedOnly ? "default" : "outline"}
              size="sm"
              className="h-6 text-[11px]"
              onClick={() => setShowPinnedOnly(!showPinnedOnly)}
            >
              Pinned ({pinnedSymbols.length})
            </Button>
            <select
              className="h-6 px-2 text-[11px] rounded border bg-background"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value)}
            >
              <option value="spread">Sort: Spread</option>
              <option value="vol">Sort: Volatility</option>
              <option value="depth">Sort: Depth</option>
              <option value="funding">Sort: Funding</option>
            </select>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {!symbols.length && (
          <div className="text-xs text-muted-foreground py-6 text-center">No symbols available yet.</div>
        )}
        {symbols.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b">
                  <th className="text-left font-medium text-muted-foreground py-2 pr-3">Symbol</th>
                  <th className="text-right font-medium text-muted-foreground py-2 pr-3">Spread</th>
                  <th className="text-right font-medium text-muted-foreground py-2 pr-3">Δ</th>
                  <th className="text-right font-medium text-muted-foreground py-2 pr-3">Vol</th>
                  <th className="text-right font-medium text-muted-foreground py-2 pr-3">Δ</th>
                  <th className="text-right font-medium text-muted-foreground py-2 pr-3">Depth</th>
                  <th className="text-right font-medium text-muted-foreground py-2 pr-3">Funding</th>
                  <th className="text-left font-medium text-muted-foreground py-2 pr-3">Regime</th>
                  <th className="text-center font-medium text-muted-foreground py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {sortedSymbols.map((sym) => (
                  <tr
                    key={sym.symbol}
                    className={cn(
                      "border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors",
                      !sym.tradable && "opacity-60"
                    )}
                    onClick={() => onSymbolClick(sym)}
                  >
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-1.5">
                        {sym.pinned && <span className="text-primary">★</span>}
                        <span className="font-medium">{sym.symbol}</span>
                      </div>
                    </td>
                    <td className={cn("py-2 pr-3 text-right font-mono", getHeatColor(sym.spread, sym.spreadBaseline))}>
                      {sym.spread.toFixed(1)}bp
                    </td>
                    <td
                      className={cn(
                        "py-2 pr-3 text-right font-mono text-[11px]",
                        sym.spreadChange > 50
                          ? "text-red-500"
                          : sym.spreadChange > 20
                          ? "text-amber-500"
                          : "text-muted-foreground"
                      )}
                    >
                      +{sym.spreadChange}%
                    </td>
                    <td className={cn("py-2 pr-3 text-right font-mono", getHeatColor(sym.vol, sym.volBaseline))}>
                      {sym.vol.toFixed(1)}%
                    </td>
                    <td
                      className={cn(
                        "py-2 pr-3 text-right font-mono text-[11px]",
                        sym.volChange > 50
                          ? "text-red-500"
                          : sym.volChange > 20
                          ? "text-amber-500"
                          : "text-muted-foreground"
                      )}
                    >
                      +{sym.volChange}%
                    </td>
                    <td
                      className={cn(
                        "py-2 pr-3 text-right font-mono",
                        getHeatColor(sym.depth, sym.depthBaseline, true)
                      )}
                    >
                      {sym.depth}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <span className="font-mono">{sym.funding.toFixed(3)}%</span>
                        {sym.fundingSpike && <AlertTriangle className="h-3 w-3 text-amber-500" />}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px] px-1.5",
                          sym.regime === "Normal" && "border-emerald-500/50 text-emerald-500",
                          sym.regime === "Widened" && "border-amber-500/50 text-amber-500",
                          (sym.regime === "Wide+HighVol" || sym.regime === "Thin+Spike") &&
                            "border-red-500/50 text-red-500",
                          sym.regime === "Extreme" && "border-red-500/50 text-red-500 bg-red-500/10"
                        )}
                      >
                        {sym.regime}
                      </Badge>
                    </td>
                    <td className="py-2 text-center">
                      {sym.tradable ? (
                        <Badge
                          variant="outline"
                          className="text-[10px] px-1.5 border-emerald-500/50 text-emerald-500"
                        >
                          OK
                        </Badge>
                      ) : (
                        <Tooltip>
                          <TooltipTrigger>
                            <Badge
                              variant="outline"
                              className="text-[10px] px-1.5 border-red-500/50 text-red-500"
                            >
                              Blocked
                            </Badge>
                          </TooltipTrigger>
                          <TooltipContent>{sym.blockedReason}</TooltipContent>
                        </Tooltip>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}







