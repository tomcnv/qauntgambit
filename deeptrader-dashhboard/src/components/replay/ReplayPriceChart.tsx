/**
 * ReplayPriceChart - Theme-aware price chart for Replay Studio
 * 
 * Features:
 * - Candlestick chart (default) fetched directly from exchange API (FAST!)
 * - Line chart option for long timeframes/fast playback
 * - Trade markers that properly respond to chart zoom/pan
 * - Current time indicator
 * - Theme-aware colors for light/dark mode
 * - Smart auto-switching based on timeframe
 * - Overlay toggles for trades, decisions, rejections
 * 
 * Performance: Candle data is fetched from Binance/OKX API, NOT built from events.
 * This makes rendering ~100x faster as we get pre-aggregated OHLC data.
 */

import { useMemo, useEffect, useRef, useState, useCallback } from "react";
import { 
  createChart, 
  IChartApi, 
  ISeriesApi, 
  ColorType, 
  CrosshairMode, 
  LineSeries, 
  CandlestickSeries,
  HistogramSeries, 
  UTCTimestamp,
  CandlestickData,
  LineData,
} from "lightweight-charts";
import { cn } from "../../lib/utils";
import { ReplayEvent } from "../../lib/api/client";
import { useCandlestickData } from "../../lib/api/hooks";
import { useTheme } from "../theme-provider";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { format } from "date-fns";
import { 
  CandlestickChart as CandlestickIcon, 
  LineChart as LineChartIcon,
  Eye,
  Loader2,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "../ui/tooltip";

// Chart type options
export type ChartType = "candles" | "line";

// Overlay options
export interface ChartOverlays {
  trades: boolean;
  decisions: boolean;
  rejections: boolean;
  activity: boolean;
}

interface ReplayPriceChartProps {
  events: ReplayEvent[];
  currentTime: number;
  onTimeClick?: (time: number) => void;
  height?: number;
  className?: string;
  // Symbol for fetching candle data from exchange
  symbol?: string;
  // Time range for fetching historical candles
  startTime?: string; // ISO string
  endTime?: string;   // ISO string
  // Chart configuration
  chartType?: ChartType;
  onChartTypeChange?: (type: ChartType) => void;
  overlays?: ChartOverlays;
  onOverlaysChange?: (overlays: ChartOverlays) => void;
  // For smart auto-switching
  timeRangeMinutes?: number;
  playbackSpeed?: number;
  // When true, center the chart on currentTime (used for initial load from URL)
  centerOnCurrentTime?: boolean;
}

// Default overlays
const DEFAULT_OVERLAYS: ChartOverlays = {
  trades: true,
  decisions: true,
  rejections: false,
  activity: true,
};

// Aggregate all activity into time buckets for visualization
// Bucket size should match the candle timeframe for proper alignment
function aggregateTradeActivity(events: ReplayEvent[], bucketSeconds: number = 60) {
  const bucketMs = bucketSeconds * 1000;
  const buckets: Map<number, { count: number; trades: number }> = new Map();
  
  events.forEach(e => {
    // Round to the bucket boundary (same as candle time)
    const bucketKey = Math.floor(e.timestamp / bucketMs) * bucketMs;
    const existing = buckets.get(bucketKey) || { count: 0, trades: 0 };
    
    existing.count++;
    if (e.type === "trade") {
      existing.trades++;
    }
    
    buckets.set(bucketKey, existing);
  });
  
  return Array.from(buckets.entries())
    .map(([time, data]) => ({
      time: Math.floor(time / 1000) as UTCTimestamp, // Convert to seconds for chart
      // Show trades prominently, but also show general activity at lower intensity
      value: data.trades > 0 ? data.trades * 2 : Math.min(data.count / 10, 1),
    }))
    .sort((a, b) => a.time - b.time);
}

// Extract price data from events for line chart fallback
function extractPriceData(events: ReplayEvent[]): LineData[] {
  const pricePoints: LineData[] = [];
  
  events.forEach(e => {
    let price = 0;
    const data = e.data as Record<string, unknown>;
    
    if (e.type === "decision" || e.type === "rejection") {
      const marketContext = data?.marketContext as Record<string, unknown> | undefined;
      price = typeof marketContext?.price === 'number' ? marketContext.price : 0;
    } else if (e.type === "trade") {
      price = typeof data?.price === 'number' ? data.price : 0;
    } else if (e.type === "snapshot") {
      const marketData = data?.marketData as Record<string, unknown> | undefined;
      price = typeof marketData?.price === 'number' ? marketData.price : 
              typeof data?.price === 'number' ? data.price : 0;
    }
    
    if (price > 0) {
      pricePoints.push({
        time: Math.floor(e.timestamp / 1000) as UTCTimestamp,
        value: price,
      });
    }
  });
  
  // Remove duplicates and sort
  const seen = new Set<number>();
  return pricePoints
    .filter(p => {
      if (seen.has(p.time as number)) return false;
      seen.add(p.time as number);
      return true;
    })
    .sort((a, b) => (a.time as number) - (b.time as number));
}

// Trade data for markers
interface TradePoint {
  time: number; // Unix timestamp in seconds
  price: number;
  side: "buy" | "sell";
  eventId: string;
}

function extractTradePoints(events: ReplayEvent[]): TradePoint[] {
  const trades = events.filter(e => e.type === "trade");
  
  return trades.map(e => {
    const data = e.data as Record<string, unknown>;
    const side = data?.side as string;
    const isBuy = side === "buy" || side === "long";
    const price = typeof data?.price === 'number' ? data.price : 0;
    
    return {
      time: Math.floor(e.timestamp / 1000), // Convert to seconds for chart
      price,
      side: (isBuy ? "buy" : "sell") as "buy" | "sell",
      eventId: e.id,
    };
  }).filter(t => t.price > 0);
}

// Marker position with pixel coordinates
interface MarkerPosition {
  x: number;
  y: number;
  side: "buy" | "sell";
  visible: boolean;
}

// Calculate number of candles needed based on time range
function calculateCandleLimit(timeRangeMinutes: number, timeframe: string = "1m"): number {
  const tfMinutes = timeframe === "1m" ? 1 : timeframe === "5m" ? 5 : timeframe === "15m" ? 15 : 60;
  // Add 20% buffer and cap at 1000
  return Math.min(1000, Math.ceil((timeRangeMinutes / tfMinutes) * 1.2));
}

// Determine best timeframe based on time range
function getBestTimeframe(timeRangeMinutes: number): string {
  if (timeRangeMinutes <= 60) return "1m";      // 1 hour or less: 1m candles
  if (timeRangeMinutes <= 240) return "1m";     // 4 hours: 1m candles (240 candles)
  if (timeRangeMinutes <= 720) return "5m";     // 12 hours: 5m candles (144 candles)
  if (timeRangeMinutes <= 1440) return "5m";    // 24 hours: 5m candles (288 candles)
  if (timeRangeMinutes <= 4320) return "15m";   // 3 days: 15m candles (288 candles)
  return "1h";                                   // 7 days+: 1h candles
}

// Get timeframe in seconds for bucketing events
function getTimeframeBucketSeconds(timeframe: string): number {
  switch (timeframe) {
    case "1m": return 60;
    case "5m": return 300;
    case "15m": return 900;
    case "1h": return 3600;
    default: return 60;
  }
}

// Round timestamp to nearest bucket
function roundToTimeframeBucket(timestampSeconds: number, bucketSeconds: number): number {
  return Math.floor(timestampSeconds / bucketSeconds) * bucketSeconds;
}

export function ReplayPriceChart({
  events,
  currentTime,
  onTimeClick,
  height = 300,
  className,
  symbol,
  startTime,
  endTime,
  chartType: externalChartType,
  onChartTypeChange,
  overlays: externalOverlays,
  onOverlaysChange,
  timeRangeMinutes = 240,
  playbackSpeed = 1,
  centerOnCurrentTime = false,
}: ReplayPriceChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<"Line"> | ISeriesApi<"Candlestick"> | null>(null);
  const verticalLineRef = useRef<HTMLDivElement | null>(null);
  
  // Internal state for chart type (controlled or uncontrolled)
  const [internalChartType, setInternalChartType] = useState<ChartType>("candles");
  const chartType = externalChartType ?? internalChartType;
  const setChartType = onChartTypeChange ?? setInternalChartType;
  
  // Internal state for overlays
  const [internalOverlays, setInternalOverlays] = useState<ChartOverlays>(DEFAULT_OVERLAYS);
  const overlays = externalOverlays ?? internalOverlays;
  const setOverlays = onOverlaysChange ?? setInternalOverlays;
  
  // State for current trade marker position (only show marker for highlighted trade)
  const [currentTradeMarker, setCurrentTradeMarker] = useState<MarkerPosition | null>(null);
  const [currentTimeX, setCurrentTimeX] = useState<number | null>(null);
  
  // Tooltip state
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    time: number;
    price: number;
    event?: ReplayEvent;
  } | null>(null);
  
  // Detect theme
  const { theme } = useTheme();
  const isDark = theme === "dark";
  
  // Calculate optimal timeframe and candle limit
  const timeframe = useMemo(() => getBestTimeframe(timeRangeMinutes), [timeRangeMinutes]);
  const candleLimit = useMemo(() => calculateCandleLimit(timeRangeMinutes, timeframe), [timeRangeMinutes, timeframe]);
  
  // Normalize symbol for Binance API (remove -USDT-SWAP suffix)
  const normalizedSymbol = useMemo(() => {
    if (!symbol) return null;
    return symbol.replace(/-USDT-SWAP$/i, 'USDT').replace(/-/g, '');
  }, [symbol]);
  
  // Parse start/end times for historical candle fetching
  const startTimeMs = useMemo(() => startTime ? new Date(startTime).getTime() : undefined, [startTime]);
  const endTimeMs = useMemo(() => endTime ? new Date(endTime).getTime() : undefined, [endTime]);
  
  // Fetch candle data from exchange API (FAST!)
  // Pass start/end time to get historical candles for replay
  const { data: candleData, isLoading: loadingCandles } = useCandlestickData(
    chartType === "candles" ? normalizedSymbol : null,
    timeframe,
    candleLimit,
    startTimeMs,
    endTimeMs
  );
  
  // Process candle data for lightweight-charts
  const candlestickData = useMemo((): CandlestickData[] => {
    if (!candleData?.candles) return [];
    
    return candleData.candles.map(c => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
  }, [candleData]);
  
  // Extract line data from events (fallback for line mode)
  const priceData = useMemo(() => extractPriceData(events), [events]);
  
  // Smart auto-switch: suggest line chart for long timeframes or fast playback
  const suggestedChartType = useMemo(() => {
    // If timeframe > 4 hours, suggest line
    if (timeRangeMinutes && timeRangeMinutes > 240) return "line";
    // If playback speed >= 4x, suggest line
    if (playbackSpeed >= 4) return "line";
    // Default to candles
    return "candles";
  }, [timeRangeMinutes, playbackSpeed]);
  
  // Get bucket size in seconds to match candle timeframe
  const bucketSeconds = useMemo(() => getTimeframeBucketSeconds(timeframe), [timeframe]);
  
  // Process event data - aggregate to match candle timeframe
  const tradeActivityData = useMemo(() => aggregateTradeActivity(events, bucketSeconds), [events, bucketSeconds]);
  const tradePoints = useMemo(() => extractTradePoints(events), [events]);
  const tradeCount = useMemo(() => events.filter(e => e.type === "trade").length, [events]);
  
  // Theme colors
  const colors = useMemo(() => ({
    background: "transparent",
    text: isDark ? "rgba(255, 255, 255, 0.7)" : "rgba(0, 0, 0, 0.7)",
    grid: isDark ? "rgba(255, 255, 255, 0.06)" : "rgba(0, 0, 0, 0.06)",
    border: isDark ? "rgba(255, 255, 255, 0.1)" : "rgba(0, 0, 0, 0.1)",
    priceLine: isDark ? "#8b5cf6" : "#7c3aed",
    crosshair: isDark ? "rgba(255, 255, 255, 0.3)" : "rgba(0, 0, 0, 0.3)",
    tradeActivityBar: isDark ? "rgba(59, 130, 246, 0.5)" : "rgba(59, 130, 246, 0.4)",
    // Candlestick colors
    upColor: "#22c55e",
    downColor: "#ef4444",
    upWick: "#22c55e",
    downWick: "#ef4444",
  }), [isDark]);
  
  // Find the trade closest to current time (within 5 second window)
  const currentTrade = useMemo(() => {
    if (!currentTime || !tradePoints.length || !overlays.trades) return null;
    
    const currentTimeSeconds = Math.floor(currentTime / 1000);
    const tolerance = 5; // 5 second window
    
    // Find trade closest to current time
    let closest: TradePoint | null = null;
    let closestDiff = Infinity;
    
    for (const trade of tradePoints) {
      const diff = Math.abs(trade.time - currentTimeSeconds);
      if (diff < closestDiff && diff <= tolerance) {
        closestDiff = diff;
        closest = trade;
      }
    }
    
    return closest;
  }, [currentTime, tradePoints, overlays.trades]);
  
  // Update marker position based on chart coordinates
  const updateMarkerPosition = useCallback(() => {
    if (!chartRef.current || !priceSeriesRef.current) {
      setCurrentTradeMarker(null);
      setCurrentTimeX(null);
      return;
    }
    
    const chart = chartRef.current;
    const series = priceSeriesRef.current;
    const timeScale = chart.timeScale();
    
    // Update current time indicator
    if (currentTime) {
      const currentTimeSeconds = Math.floor(currentTime / 1000) as UTCTimestamp;
      
      // Get the data we're using
      const dataPoints = chartType === "candles" ? candlestickData : priceData;
      
      // If we have data, find the closest point to current time
      if (dataPoints.length > 0) {
        // Find closest data point
        let closestTime: number = dataPoints[0].time as number;
        let closestDiff = Math.abs(closestTime - currentTimeSeconds);
        
        for (const point of dataPoints) {
          const pointTime = point.time as number;
          const diff = Math.abs(pointTime - currentTimeSeconds);
          if (diff < closestDiff) {
            closestDiff = diff;
            closestTime = pointTime;
          }
        }
        
        // Use the closest time to position the line
        const x = timeScale.timeToCoordinate(closestTime as UTCTimestamp);
        setCurrentTimeX(x !== null && x >= 0 ? x : null);
      } else {
        // No data - try direct coordinate lookup
        const x = timeScale.timeToCoordinate(currentTimeSeconds);
        setCurrentTimeX(x !== null && x >= 0 ? x : null);
      }
    } else {
      setCurrentTimeX(null);
    }
    
    // Update current trade marker
    if (currentTrade && overlays.trades) {
      const x = timeScale.timeToCoordinate(currentTrade.time as UTCTimestamp);
      const y = series.priceToCoordinate(currentTrade.price);
      
      if (x !== null && y !== null && x >= 0 && y >= 0) {
        setCurrentTradeMarker({
          x,
          y,
          side: currentTrade.side,
          visible: true,
        });
      } else {
        setCurrentTradeMarker(null);
      }
    } else {
      setCurrentTradeMarker(null);
    }
  }, [currentTime, currentTrade, overlays.trades, chartType, candlestickData, priceData]);
  
  // Main chart setup
  useEffect(() => {
    // For candles, we need candlestick data; for line, we need price data
    const hasData = chartType === "candles" 
      ? candlestickData.length > 0 
      : priceData.length > 0;
    
    if (!chartContainerRef.current || !hasData) return;
    
    // Cleanup previous chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }
    
    try {
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: colors.background },
          textColor: colors.text,
        },
        grid: {
          vertLines: { color: colors.grid },
          horzLines: { color: colors.grid },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: { color: colors.crosshair, labelBackgroundColor: isDark ? "#1f2937" : "#f3f4f6" },
          horzLine: { color: colors.crosshair, labelBackgroundColor: isDark ? "#1f2937" : "#f3f4f6" },
        },
        rightPriceScale: {
          borderColor: colors.border,
          scaleMargins: { top: 0.1, bottom: 0.2 },
        },
        timeScale: {
          borderColor: colors.border,
          timeVisible: true,
          secondsVisible: false,
          // Use local timezone for time axis labels
          tickMarkFormatter: (time: number) => {
            const date = new Date(time * 1000);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
          },
        },
        localization: {
          // Format time labels in local timezone for crosshair and tooltips
          timeFormatter: (time: number) => {
            const date = new Date(time * 1000);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
          },
        },
        width: chartContainerRef.current.clientWidth,
        height: height,
      });
      
      chartRef.current = chart;
      
      // Add trade activity histogram (if enabled)
      if (overlays.activity && tradeActivityData.length > 0) {
        const activitySeries = chart.addSeries(HistogramSeries, {
          color: colors.tradeActivityBar,
          priceFormat: { type: "volume" },
          priceScaleId: "activity",
        });
        
        chart.priceScale("activity").applyOptions({
          scaleMargins: { top: 0.85, bottom: 0 },
          borderVisible: false,
        });
        
        activitySeries.setData(tradeActivityData);
      }
      
      // Add price series based on chart type
      if (chartType === "candles" && candlestickData.length > 0) {
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: colors.upColor,
          downColor: colors.downColor,
          borderUpColor: colors.upColor,
          borderDownColor: colors.downColor,
          wickUpColor: colors.upWick,
          wickDownColor: colors.downWick,
          priceFormat: {
            type: "price",
            precision: 2,
            minMove: 0.01,
          },
        });
        
        priceSeriesRef.current = candleSeries;
        candleSeries.setData(candlestickData);
      } else {
        const lineSeries = chart.addSeries(LineSeries, {
          color: colors.priceLine,
          lineWidth: 2,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
          priceFormat: {
            type: "price",
            precision: 2,
            minMove: 0.01,
          },
        });
        
        priceSeriesRef.current = lineSeries;
        lineSeries.setData(priceData);
      }
      
      // Subscribe to visible range changes to update marker
      chart.timeScale().subscribeVisibleTimeRangeChange(() => {
        updateMarkerPosition();
      });
      
      // Crosshair move - update marker and show tooltip
      chart.subscribeCrosshairMove((param) => {
        updateMarkerPosition();
        
        if (!param.point || !param.time) {
          setTooltip(null);
          return;
        }
        
        const timeMs = (param.time as number) * 1000;
        const seriesData = param.seriesData.get(priceSeriesRef.current!);
        let priceValue = 0;
        
        if (seriesData) {
          if ('value' in seriesData) {
            priceValue = seriesData.value;
          } else if ('close' in seriesData) {
            priceValue = seriesData.close;
          }
        }
        
        // Find closest event to this time (within 30 seconds)
        let closestEvent: ReplayEvent | undefined;
        let closestDiff = Infinity;
        for (const evt of events) {
          const diff = Math.abs(evt.timestamp - timeMs);
          if (diff < closestDiff && diff < 30000) {
            closestDiff = diff;
            closestEvent = evt;
          }
        }
        
        setTooltip({
          x: param.point.x,
          y: param.point.y,
          time: timeMs,
          price: priceValue,
          event: closestEvent,
        });
      });
      
      // Handle resize
      const handleResize = () => {
        if (chartContainerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width: chartContainerRef.current.clientWidth,
          });
          updateMarkerPosition();
        }
      };
      
      window.addEventListener("resize", handleResize);
      
      // Handle click to jump to time
      if (onTimeClick) {
        chart.subscribeClick((param) => {
          if (param.time) {
            onTimeClick((param.time as number) * 1000);
          }
        });
      }
      
      // Fit content and update marker
      chart.timeScale().fitContent();
      
      // Initial marker position update (with small delay to let chart render)
      setTimeout(updateMarkerPosition, 100);
      
      return () => {
        window.removeEventListener("resize", handleResize);
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
      };
    } catch (error) {
      console.error("Failed to create replay chart:", error);
    }
  }, [priceData, candlestickData, tradeActivityData, colors, height, isDark, onTimeClick, updateMarkerPosition, chartType, overlays.activity, events]);
  
  // Update positions when currentTime or currentTrade changes
  useEffect(() => {
    // Small delay to ensure chart is ready
    const timer = setTimeout(() => {
      updateMarkerPosition();
    }, 50);
    return () => clearTimeout(timer);
  }, [currentTime, currentTrade, updateMarkerPosition]);
  
  // Center the chart on currentTime when requested (e.g., when loading from URL)
  useEffect(() => {
    if (!centerOnCurrentTime || !chartRef.current || !currentTime) return;
    
    const chart = chartRef.current;
    const timeScale = chart.timeScale();
    const currentTimeSeconds = Math.floor(currentTime / 1000);
    
    // Get the current visible range to determine the window size
    const visibleRange = timeScale.getVisibleRange();
    if (!visibleRange) return;
    
    // Calculate window size (keep the same zoom level)
    const windowSize = (visibleRange.to as number) - (visibleRange.from as number);
    const halfWindow = windowSize / 2;
    
    // Center on the current time
    timeScale.setVisibleRange({
      from: (currentTimeSeconds - halfWindow) as UTCTimestamp,
      to: (currentTimeSeconds + halfWindow) as UTCTimestamp,
    });
    
    // Update marker position after centering
    setTimeout(updateMarkerPosition, 100);
  }, [centerOnCurrentTime, currentTime, updateMarkerPosition]);
  
  // Show loading state for candles
  if (chartType === "candles" && loadingCandles) {
    return (
      <div className={cn("flex items-center justify-center text-muted-foreground gap-2", className)} style={{ height }}>
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm">Loading candles...</span>
      </div>
    );
  }
  
  const hasData = chartType === "candles" 
    ? candlestickData.length > 0 
    : priceData.length > 0;
  
  if (!hasData) {
    return (
      <div className={cn("flex items-center justify-center text-muted-foreground", className)} style={{ height }}>
        {chartType === "candles" && !normalizedSymbol 
          ? "Select a symbol to view candles"
          : "No price data available"
        }
      </div>
    );
  }
  
  return (
    <div className={cn("relative overflow-hidden", className)}>
      <div ref={chartContainerRef} style={{ height }} />
      
      {/* Current trade marker - only show for highlighted trade */}
      {currentTradeMarker?.visible && overlays.trades && (
        <div
          className="absolute pointer-events-none z-10"
          style={{
            left: currentTradeMarker.x,
            top: currentTradeMarker.y,
            transform: 'translate(-50%, -50%)',
          }}
        >
          {currentTradeMarker.side === "buy" ? (
            <svg width="18" height="16" viewBox="0 0 18 16" className="drop-shadow-lg animate-pulse">
              <polygon points="9,0 18,16 0,16" fill="#22c55e" stroke="#166534" strokeWidth="1.5" />
            </svg>
          ) : (
            <svg width="18" height="16" viewBox="0 0 18 16" className="drop-shadow-lg animate-pulse">
              <polygon points="0,0 18,0 9,16" fill="#ef4444" stroke="#991b1b" strokeWidth="1.5" />
            </svg>
          )}
        </div>
      )}
      
      {/* Current time vertical indicator - positioned using chart coordinates */}
      {currentTimeX !== null && (
        <div 
          className="absolute top-0 bottom-0 w-0.5 bg-blue-500/80 pointer-events-none z-20"
          style={{ left: currentTimeX }}
        >
          <div className="absolute -top-0.5 -translate-x-1/2 left-1/2">
            <svg width="10" height="6" viewBox="0 0 10 6" className="fill-blue-500">
              <polygon points="0,0 10,0 5,6" />
            </svg>
          </div>
        </div>
      )}
      
      {/* Tooltip on hover */}
      {tooltip && (
        <div 
          className="absolute pointer-events-none z-30 bg-card/95 backdrop-blur-sm border rounded-lg shadow-lg p-2 text-xs min-w-[180px]"
          style={{ 
            left: Math.min(tooltip.x + 15, (chartContainerRef.current?.clientWidth || 300) - 200),
            top: Math.max(tooltip.y - 10, 10),
          }}
        >
          <div className="font-mono text-muted-foreground mb-1">
            {format(new Date(tooltip.time), "HH:mm:ss")}
          </div>
          <div className="font-mono font-medium">
            ${tooltip.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          
          {tooltip.event && (() => {
            const data = tooltip.event.data as Record<string, unknown> | undefined;
            const side = data?.side as string | undefined;
            const size = data?.size;
            const pnl = typeof data?.pnl === 'number' ? data.pnl : null;
            const outcome = data?.outcome as string | undefined;
            const reason = data?.reason as string | undefined;
            
            return (
              <div className="mt-2 pt-2 border-t space-y-1">
                <div className="flex items-center gap-2">
                  <Badge 
                    variant={
                      tooltip.event.type === "trade" ? "default" :
                      tooltip.event.type === "rejection" ? "warning" :
                      "outline"
                    }
                    className="text-[9px] h-4"
                  >
                    {tooltip.event.type}
                  </Badge>
                  <span className="text-muted-foreground">
                    {format(new Date(tooltip.event.timestamp), "HH:mm:ss")}
                  </span>
                </div>
                
                {tooltip.event.type === "trade" && (
                  <div className="space-y-0.5">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Side:</span>
                      <span className={cn(
                        "font-medium",
                        side === "buy" || side === "long" 
                          ? "text-green-500" : "text-red-500"
                      )}>
                        {side?.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Size:</span>
                      <span className="font-mono">{String(size)}</span>
                    </div>
                    {pnl !== null && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">P&L:</span>
                        <span className={cn(
                          "font-medium",
                          pnl >= 0 ? "text-green-500" : "text-red-500"
                        )}>
                          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                        </span>
                      </div>
                    )}
                  </div>
                )}
                
                {(tooltip.event.type === "decision" || tooltip.event.type === "rejection") && (
                  <div className="space-y-0.5">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Outcome:</span>
                      <span className={cn(
                        "font-medium",
                        tooltip.event.type === "decision" ? "text-green-500" : "text-red-500"
                      )}>
                        {outcome?.toUpperCase() || tooltip.event.type.toUpperCase()}
                      </span>
                    </div>
                    {reason && (
                      <div className="text-muted-foreground truncate max-w-[160px]">
                        {reason}
                      </div>
                    )}
                  </div>
                )}
                
                {tooltip.event.type === "snapshot" && (
                  <div className="text-muted-foreground">
                    Market snapshot
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

// Chart controls component - for use in chart header
interface ReplayChartControlsProps {
  chartType: ChartType;
  onChartTypeChange: (type: ChartType) => void;
  overlays: ChartOverlays;
  onOverlaysChange: (overlays: ChartOverlays) => void;
  suggestedChartType?: ChartType;
  className?: string;
}

export function ReplayChartControls({
  chartType,
  onChartTypeChange,
  overlays,
  onOverlaysChange,
  suggestedChartType,
  className,
}: ReplayChartControlsProps) {
  const showSuggestion = suggestedChartType && suggestedChartType !== chartType;
  
  return (
    <div className={cn("flex items-center gap-2", className)}>
      {/* Chart type toggle */}
      <div className="flex items-center border rounded-md overflow-hidden">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={chartType === "candles" ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2 rounded-none"
              onClick={() => onChartTypeChange("candles")}
            >
              <CandlestickIcon className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p className="font-medium">Candlesticks</p>
            <p className="text-xs text-muted-foreground">Best for microstructure analysis</p>
          </TooltipContent>
        </Tooltip>
        
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={chartType === "line" ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2 rounded-none"
              onClick={() => onChartTypeChange("line")}
            >
              <LineChartIcon className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p className="font-medium">Line</p>
            <p className="text-xs text-muted-foreground">Best for long timeframes & fast playback</p>
          </TooltipContent>
        </Tooltip>
      </div>
      
      {/* Smart suggestion badge */}
      {showSuggestion && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={() => onChartTypeChange(suggestedChartType)}
            >
              <Zap className="h-3 w-3 text-amber-500" />
              Try {suggestedChartType === "line" ? "Line" : "Candles"}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p className="text-xs">
              {suggestedChartType === "line" 
                ? "Line chart recommended for this timeframe/speed" 
                : "Candlesticks recommended for detailed analysis"}
            </p>
          </TooltipContent>
        </Tooltip>
      )}
      
      {/* Overlays dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="h-7 gap-1">
            <Eye className="h-3.5 w-3.5" />
            <span className="text-xs">Overlays</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuLabel className="text-xs">Chart Overlays</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem
            checked={overlays.trades}
            onCheckedChange={(checked) => onOverlaysChange({ ...overlays, trades: checked })}
          >
            <span className="flex items-center gap-2">
              <svg width="10" height="8" viewBox="0 0 10 8" className="fill-green-500">
                <polygon points="5,0 10,8 0,8" />
              </svg>
              Trades
            </span>
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={overlays.decisions}
            onCheckedChange={(checked) => onOverlaysChange({ ...overlays, decisions: checked })}
          >
            <span className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-blue-500" />
              Decisions
            </span>
          </DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem
            checked={overlays.rejections}
            onCheckedChange={(checked) => onOverlaysChange({ ...overlays, rejections: checked })}
          >
            <span className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-orange-500" />
              Rejections
            </span>
          </DropdownMenuCheckboxItem>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem
            checked={overlays.activity}
            onCheckedChange={(checked) => onOverlaysChange({ ...overlays, activity: checked })}
          >
            <span className="flex items-center gap-2">
              <div className="w-3 h-2 bg-blue-500/50 rounded-sm" />
              Activity Bars
            </span>
          </DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

// Zap icon for suggestions
function Zap({ className }: { className?: string }) {
  return (
    <svg 
      xmlns="http://www.w3.org/2000/svg" 
      viewBox="0 0 24 24" 
      fill="none" 
      stroke="currentColor" 
      strokeWidth="2" 
      strokeLinecap="round" 
      strokeLinejoin="round"
      className={className}
    >
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}

// Export legend component for use outside the chart (includes trade count)
interface ReplayChartLegendProps {
  className?: string;
  tradeCount?: number;
  chartType?: ChartType;
}

export function ReplayChartLegend({ className, tradeCount, chartType = "candles" }: ReplayChartLegendProps) {
  return (
    <div className={cn("flex items-center gap-4 text-xs", className)}>
      {chartType === "candles" ? (
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-0.5">
            <div className="w-1 h-3 bg-green-500 rounded-sm" />
            <div className="w-1 h-3 bg-red-500 rounded-sm" />
          </div>
          <span className="text-muted-foreground">OHLC</span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-0.5 bg-violet-500 rounded" />
          <span className="text-muted-foreground">Price</span>
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <div className="w-3 h-2 bg-blue-500/50 rounded-sm" />
        <span className="text-muted-foreground">Activity</span>
      </div>
      <div className="flex items-center gap-1.5">
        <svg width="10" height="8" viewBox="0 0 10 8" className="fill-green-500">
          <polygon points="5,0 10,8 0,8" />
        </svg>
        <span className="text-muted-foreground">Buy</span>
      </div>
      <div className="flex items-center gap-1.5">
        <svg width="10" height="8" viewBox="0 0 10 8" className="fill-red-500">
          <polygon points="0,0 10,0 5,8" />
        </svg>
        <span className="text-muted-foreground">Sell</span>
      </div>
      {tradeCount !== undefined && (
        <div className="border-l pl-3 ml-1">
          <Badge variant="outline" className="text-[10px] h-5">
            {tradeCount} trades
          </Badge>
        </div>
      )}
    </div>
  );
}
