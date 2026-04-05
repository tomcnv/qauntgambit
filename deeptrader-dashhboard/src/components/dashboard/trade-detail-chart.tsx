import { useMemo } from "react";
import { Loader2 } from "lucide-react";
import { useCandlestickData } from "../../lib/api/hooks";
import { CandlestickChart, ExecutionMarker } from "./candlestick-chart";

interface TradeDetailChartProps {
  symbol: string | null;
  side: string;
  entryPrice?: number;
  exitPrice?: number;
  size?: number;
  timestamp?: string | Date;
  entryTime?: string | Date;
}

export function TradeDetailChart({ 
  symbol, 
  side, 
  entryPrice, 
  exitPrice, 
  size = 0,
  timestamp,
  entryTime
}: TradeDetailChartProps) {
  // Fetch candle data for the chart
  const { data: candleData, isLoading: loadingCandles } = useCandlestickData(
    symbol,
    "1m",  // 1-minute candles for detail view
    120    // Last 2 hours of data
  );
  
  const candles = candleData?.candles || [];
  
  // Build execution markers for entry and exit
  // We need to find the nearest candle timestamps for the markers to show properly
  const executionMarkers = useMemo((): ExecutionMarker[] => {
    if (candles.length === 0) return [];
    
    const sideStr = (side || "").toLowerCase();
    const isBuy = sideStr === "buy" || sideStr === "long";
    
    const markers: ExecutionMarker[] = [];
    
    // Helper to find nearest candle time
    const findNearestCandleTime = (targetTime: number): number => {
      let nearest = candles[0].time;
      let minDiff = Math.abs(candles[0].time - targetTime);
      
      for (const candle of candles) {
        const diff = Math.abs(candle.time - targetTime);
        if (diff < minDiff) {
          minDiff = diff;
          nearest = candle.time;
        }
      }
      return nearest;
    };
    
    // Get exit time from timestamp
    const exitTimeTarget = timestamp ? Math.floor(new Date(timestamp).getTime() / 1000) : 0;
    
    // Get entry time - use provided entryTime or calculate from exit
    const entryTimeTarget = entryTime 
      ? Math.floor(new Date(entryTime).getTime() / 1000)
      : exitTimeTarget - 300; // Default to 5 minutes before exit if no entry time
    
    // Entry marker - place on a candle near the start/middle of the chart
    if (entryPrice) {
      // Use entry time or place marker at ~1/3 of chart for visual clarity
      const entryIdx = Math.max(0, Math.floor(candles.length * 0.3));
      const entryCandleTime = entryTimeTarget 
        ? findNearestCandleTime(entryTimeTarget)
        : candles[entryIdx]?.time || candles[0].time;
      
      markers.push({
        time: entryCandleTime,
        price: entryPrice,
        side: isBuy ? "buy" : "sell",
        size: size,
      });
    }
    
    // Exit marker - place at the end of the chart or at actual exit time
    if (exitPrice) {
      // Use exit time or place marker at ~2/3 of chart
      const exitIdx = Math.min(candles.length - 1, Math.floor(candles.length * 0.7));
      const exitCandleTime = exitTimeTarget 
        ? findNearestCandleTime(exitTimeTarget)
        : candles[exitIdx]?.time || candles[candles.length - 1].time;
      
      markers.push({
        time: exitCandleTime,
        price: exitPrice,
        side: isBuy ? "sell" : "buy", // Exit is opposite of entry
        size: size,
      });
    }
    
    // Ensure markers are sorted by time
    markers.sort((a, b) => a.time - b.time);
    
    return markers;
  }, [candles, side, entryPrice, exitPrice, size, timestamp, entryTime]);
  
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs uppercase tracking-widest text-muted-foreground font-medium">Price Action</p>
        {loadingCandles && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
      </div>
      {candles.length > 0 ? (
        <CandlestickChart 
          data={candles} 
          executionMarkers={executionMarkers}
          height={200}
          className="rounded-lg overflow-hidden"
        />
      ) : (
        <div className="h-[200px] flex items-center justify-center text-muted-foreground text-sm bg-muted/50 rounded-lg">
          {loadingCandles ? "Loading chart..." : "No chart data available"}
        </div>
      )}
      <div className="mt-3 flex items-center justify-center gap-6 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" /> Entry
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500" /> Exit
        </span>
      </div>
    </div>
  );
}

