import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Progress } from "../../components/ui/progress";
import { useDecisionFunnel } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { Loader2, TrendingDown, ArrowRight } from "lucide-react";
import { cn } from "../../lib/utils";

interface DecisionFunnelProps {
  timeWindow?: string;
  onTimeWindowChange?: (window: string) => void;
}

export function DecisionFunnel({ timeWindow, onTimeWindowChange }: DecisionFunnelProps) {
  const { botId, exchangeAccountId } = useScopeStore();
  const [internalTimeWindow, setInternalTimeWindow] = useState("15m");
  const activeWindow = timeWindow ?? internalTimeWindow;
  const { data, isLoading } = useDecisionFunnel({ 
    timeWindow: activeWindow, 
    botId: botId || undefined, 
    exchangeAccountId: exchangeAccountId || undefined 
  });

  const handleTimeWindowChange = (window: string) => {
    if (timeWindow === undefined) {
      setInternalTimeWindow(window);
    }
    onTimeWindowChange?.(window);
  };

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Decision Funnel</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return null;
  }

  const { stages, conversionRates } = data;

  const funnelStages = [
    { key: "marketTicks", label: "Market Ticks", count: stages.marketTicks, conversion: 100 },
    { key: "predictionsProduced", label: "Predictions", count: stages.predictionsProduced, conversion: conversionRates.predictions },
    { key: "signalsTriggered", label: "Signals", count: stages.signalsTriggered, conversion: conversionRates.signals },
    { key: "passedFilters", label: "Passed Filters", count: stages.passedFilters, conversion: conversionRates.filters },
    { key: "passedRiskGates", label: "Passed Risk", count: stages.passedRiskGates, conversion: conversionRates.risk },
    { key: "ordersSent", label: "Orders Sent", count: stages.ordersSent, conversion: conversionRates.orders },
    { key: "fills", label: "Fills", count: stages.fills, conversion: conversionRates.fills },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Decision Funnel ({activeWindow})</CardTitle>
          <div className="flex rounded-lg border bg-muted/50 p-0.5">
            {["15m", "1h", "24h"].map((w) => (
              <Button
                key={w}
                variant={activeWindow === w ? "default" : "ghost"}
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={() => handleTimeWindowChange(w)}
              >
                {w}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-3">
          {funnelStages.map((stage, index) => {
            const isBottleneck = stage.conversion < 50 && stage.count > 0;
            const isBlocked = stage.conversion === 0 && stage.count === 0 && index > 0 && funnelStages[index - 1].count > 0;
            
            return (
              <div key={stage.key} className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{stage.label}</span>
                    {isBottleneck && <TrendingDown className="h-3 w-3 text-amber-500" />}
                    {isBlocked && <span className="text-red-500 text-[10px]">BLOCKED</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground">{stage.conversion.toFixed(1)}%</span>
                    <span className="font-mono font-medium">{stage.count.toLocaleString()}</span>
                  </div>
                </div>
                <div className="relative">
                  <Progress 
                    value={stage.conversion} 
                    className={cn(
                      "h-2",
                      isBottleneck && "bg-amber-500/20",
                      isBlocked && "bg-red-500/20"
                    )}
                  />
                  {index < funnelStages.length - 1 && (
                    <div className="flex justify-center mt-1">
                      <ArrowRight className="h-3 w-3 text-muted-foreground" />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}





