/**
 * ChartWidget — Inline candlestick chart rendered within copilot messages.
 *
 * Uses lightweight-charts (TradingView) to render OHLCV candle data.
 * Displays "No data available" when the candles array is empty.
 * Cleans up the chart instance on unmount to prevent memory leaks.
 */

import { useEffect, useRef } from "react";
import { createChart, CandlestickSeries, ColorType, CrosshairMode } from "lightweight-charts";
import type { UTCTimestamp } from "lightweight-charts";
import type { CandleData } from "@/lib/api/copilot";

export interface ChartWidgetProps {
  symbol: string;
  timeframeSec: number;
  candles: CandleData[];
}

export function ChartWidget({ symbol, timeframeSec, candles }: ChartWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 250,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9ca3af",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: timeframeSec < 60,
        borderColor: "rgba(255,255,255,0.1)",
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.1)",
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    // Sort ascending by time (backend returns DESC) and filter non-finite values
    const sorted = [...candles]
      .filter(
        (c) =>
          Number.isFinite(c.time) &&
          Number.isFinite(c.open) &&
          Number.isFinite(c.high) &&
          Number.isFinite(c.low) &&
          Number.isFinite(c.close),
      )
      .sort((a, b) => a.time - b.time)
      .map((c) => ({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

    series.setData(sorted);
    chart.timeScale().fitContent();

    // Handle container resize
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [candles, timeframeSec]);

  if (candles.length === 0) {
    return (
      <div
        className="w-full flex items-center justify-center rounded-md border border-border bg-muted/20 text-muted-foreground text-xs"
        style={{ height: 250 }}
        data-testid="chart-no-data"
      >
        No data available
      </div>
    );
  }

  return (
    <div className="my-2">
      <p className="text-[11px] text-muted-foreground mb-1">
        {symbol} · {timeframeSec >= 3600 ? `${timeframeSec / 3600}h` : timeframeSec >= 60 ? `${timeframeSec / 60}m` : `${timeframeSec}s`}
      </p>
      <div
        ref={containerRef}
        className="w-full rounded-md border border-border overflow-hidden"
        style={{ height: 250 }}
        data-testid="chart-container"
      />
    </div>
  );
}
