import { useEffect, useRef } from "react";
import { createChart, IChartApi, ISeriesApi, ColorType, CrosshairMode, CandlestickSeries, UTCTimestamp, SeriesMarker, Time } from "lightweight-charts";

export interface CandlestickData {
  time: number; // Unix timestamp in seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface ExecutionMarker {
  time: number;
  price: number;
  side: "buy" | "sell";
  size: number;
}

interface CandlestickChartProps {
  data: CandlestickData[];
  executionMarkers?: ExecutionMarker[];
  height?: number;
  className?: string;
}

export function CandlestickChart({
  data,
  executionMarkers = [],
  height = 400,
  className,
}: CandlestickChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    if (!data || data.length === 0) return;

    try {
      // Defensive cleanup for hot reload / strict mode double-mount.
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
      chartContainerRef.current.innerHTML = "";

      // Create chart
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "rgba(255, 255, 255, 0.7)",
        },
        grid: {
          vertLines: { color: "rgba(255, 255, 255, 0.1)" },
          horzLines: { color: "rgba(255, 255, 255, 0.1)" },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
        },
        rightPriceScale: {
          borderColor: "rgba(255, 255, 255, 0.1)",
          scaleMargins: {
            top: 0.1,
            bottom: 0.2,
          },
        },
        timeScale: {
          borderColor: "rgba(255, 255, 255, 0.1)",
          timeVisible: true,
          secondsVisible: false,
        },
        width: chartContainerRef.current.clientWidth,
        height: height,
      });

      chartRef.current = chart;

      // Add candlestick series (v5 API uses class-based addSeries)
      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
      });
      candlestickSeriesRef.current = candlestickSeries as ISeriesApi<"Candlestick">;

      // NOTE: Trade inspector intentionally renders pure OHLC only.
      // Volume panel previously caused visual distortion in this compact layout.
      volumeSeriesRef.current = null;

      // Set data - ensure data is sorted and time format is correct
      // Lightweight-charts v5 accepts Unix timestamp (seconds) or UTC timestamp
      const dedupedByTime = new Map<number, CandlestickData>();
      for (const item of data) {
        if (
          !Number.isFinite(item.time) ||
          !Number.isFinite(item.open) ||
          !Number.isFinite(item.high) ||
          !Number.isFinite(item.low) ||
          !Number.isFinite(item.close)
        ) {
          continue;
        }
        const high = Math.max(item.high, item.open, item.close);
        const low = Math.min(item.low, item.open, item.close);
        if (high <= 0 || low <= 0 || high < low) continue;
        dedupedByTime.set(item.time, {
          ...item,
          high,
          low,
        });
      }

      let sortedData = Array.from(dedupedByTime.values()).sort((a, b) => a.time - b.time);

      // Drop extreme outliers that can destroy the y-scale (e.g., occasional malformed candles).
      const rangePcts = sortedData
        .map((d) => (d.close > 0 ? (d.high - d.low) / d.close : 0))
        .filter((v) => Number.isFinite(v) && v >= 0)
        .sort((a, b) => a - b);
      if (rangePcts.length > 10) {
        const median = rangePcts[Math.floor(rangePcts.length / 2)];
        const maxAllowedRangePct = Math.max(median * 8, 0.03);
        sortedData = sortedData.filter((d) => {
          const rangePct = d.close > 0 ? (d.high - d.low) / d.close : Infinity;
          return Number.isFinite(rangePct) && rangePct <= maxAllowedRangePct;
        });
      }

      const formattedData = sortedData.map((d) => ({
        time: d.time as UTCTimestamp, // Unix timestamp in seconds - lightweight-charts handles this
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));
      
      candlestickSeries.setData(formattedData);

      chart.timeScale().fitContent();

      // Add execution markers using the series markers API
      // In lightweight-charts v5, markers are set via series.setMarkers()
      if (executionMarkers.length > 0) {
        try {
          const markers: SeriesMarker<Time>[] = executionMarkers.map((marker) => ({
            time: marker.time as UTCTimestamp,
            position: marker.side === "buy" ? "belowBar" : "aboveBar",
            color: marker.side === "buy" ? "#10b981" : "#ef4444",
            shape: marker.side === "buy" ? "arrowUp" : "arrowDown",
            size: 2,
            text: `${marker.side.toUpperCase()} ${marker.size.toFixed(4)}`,
          }));
          // Sort markers by time as required by the API
          markers.sort((a, b) => (a.time as number) - (b.time as number));
          // setMarkers may not be available in all versions of lightweight-charts
          if ('setMarkers' in candlestickSeries && typeof (candlestickSeries as any).setMarkers === 'function') {
            (candlestickSeries as any).setMarkers(markers);
          }
        } catch (markerError) {
          // Markers API may not be available in all versions - log but don't crash
          console.warn("Failed to set markers on candlestick series:", markerError);
        }
      }

      // Handle resize
      const handleResize = () => {
        if (chartContainerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width: chartContainerRef.current.clientWidth,
          });
        }
      };

      window.addEventListener("resize", handleResize);

      return () => {
        window.removeEventListener("resize", handleResize);
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }
      };
    } catch (error) {
      console.error("Failed to create candlestick chart:", error);
    }
  }, [data, executionMarkers, height]);

  return <div ref={chartContainerRef} className={className} style={{ width: "100%", height: `${height}px` }} />;
}

