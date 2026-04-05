import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Progress } from "../ui/progress";
import type { SymbolRow } from "./types";

type Props = { symbols: SymbolRow[] };

export function TradingConditionsVsBot({ symbols }: Props) {
  const sample = symbols[0];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">Trading Conditions vs Bot</CardTitle>
          </div>
          <CardDescription className="text-xs">Signal fit to venue microstructure</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="compatibility" className="space-y-4">
          <TabsList className="grid grid-cols-3">
            <TabsTrigger value="compatibility">Compatibility</TabsTrigger>
            <TabsTrigger value="anomalies">Anomalies</TabsTrigger>
            <TabsTrigger value="latency">Latency</TabsTrigger>
          </TabsList>

          <TabsContent value="compatibility" className="space-y-4">
            <div className="flex items-center gap-3">
              <Progress value={sample ? Math.max(0, Math.min(100, 100 - sample.spreadChange)) : 0} className="h-2" />
              <span className="text-xs text-muted-foreground">Edge vs spread</span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-lg border p-3">
                <p className="text-muted-foreground">Market Fit</p>
                <p className="text-lg font-bold">Medium</p>
                <p className="text-[11px] text-muted-foreground">Spread/vol within tolerances</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-muted-foreground">Venue Safety</p>
                <p className="text-lg font-bold text-emerald-500">Good</p>
                <p className="text-[11px] text-muted-foreground">No incidents reported</p>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="anomalies" className="space-y-3 text-xs">
            <div className="rounded-lg border p-3 bg-amber-500/5 border-amber-500/30">
              <p className="text-amber-600 dark:text-amber-400 font-medium">Funding spike watchlist</p>
              <p className="text-muted-foreground mt-1">Monitor funding impact on long bias.</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-muted-foreground">Data Quality</p>
              <p className="text-sm font-medium text-emerald-500">OK</p>
            </div>
          </TabsContent>

          <TabsContent value="latency" className="space-y-3 text-xs">
            <div className="rounded-lg border p-3">
              <p className="text-muted-foreground">Order RTT (p50)</p>
              <p className="text-lg font-bold">28 ms</p>
              <p className="text-[11px] text-muted-foreground">No recent drops</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-muted-foreground">Expected Slippage (avg)</p>
              <p className="text-lg font-bold">1.8 bps</p>
              <p className="text-[11px] text-muted-foreground text-emerald-500">✓ Conditions favorable for scalping</p>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}







