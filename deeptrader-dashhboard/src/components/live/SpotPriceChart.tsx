/**
 * Spot Price Chart — Live candlestick chart with position overlays.
 * Token tabs for quick switching, SL/TP lines, entry markers.
 * Only shown for spot trading bots.
 */

import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { cn } from "@/lib/utils";

// ─── Bybit public kline API (no auth, no storage) ───────────────────────────

const BYBIT_INTERVALS: Record<string, string> = {
  "1m": "1", "5m": "5", "15m": "15", "1h": "60",
};

function useBybitKlines(symbol: string, timeframe: string, limit: number) {
  const [candles, setCandles] = useState<{ time: number; open: number; high: number; low: number; close: number }[]>([]);

  useEffect(() => {
    let cancelled = false;
    const interval = BYBIT_INTERVALS[timeframe] || "5";

    const fetchKlines = async () => {
      try {
        const res = await fetch(
          `https://api.bybit.com/v5/market/kline?category=spot&symbol=${symbol}&interval=${interval}&limit=${limit}`
        );
        const json = await res.json();
        if (cancelled || json.retCode !== 0) return;
        // Bybit returns newest first: [startTime, open, high, low, close, volume, turnover]
        const rows = (json.result?.list || []) as string[][];
        const parsed = rows
          .map((r) => ({
            time: Math.floor(Number(r[0]) / 1000),
            open: Number(r[1]),
            high: Number(r[2]),
            low: Number(r[3]),
            close: Number(r[4]),
          }))
          .filter((c) => Number.isFinite(c.time) && c.time > 0)
          .reverse(); // oldest first
        setCandles(parsed);
      } catch { /* silent */ }
    };

    fetchKlines();
    const id = setInterval(fetchKlines, 15_000); // refresh every 15s
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, timeframe, limit]);

  return candles;
}

// ─── Types ───────────────────────────────────────────────────────────────────

interface Position {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  stop_loss?: number;
  take_profit?: number;
  opened_at?: number;
  unrealized_pnl?: number;
  strategy_id?: string;
}

interface SpotPriceChartProps {
  symbols: string[];
  positions: Position[];
  className?: string;
  defaultSymbol?: string;
  onSymbolChange?: (symbol: string) => void;
}

const TIMEFRAMES = [
  { label: "1m", value: "1m", limit: 120 },
  { label: "5m", value: "5m", limit: 144 },
  { label: "15m", value: "15m", limit: 96 },
  { label: "1h", value: "1h", limit: 72 },
] as const;

// ─── Component ───────────────────────────────────────────────────────────────

export function SpotPriceChart({
  symbols,
  positions,
  className,
  defaultSymbol,
  onSymbolChange,
}: SpotPriceChartProps) {
  const [activeSymbol, setActiveSymbol] = useState(defaultSymbol || symbols[0] || "BTCUSDT");
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>(TIMEFRAMES[1]); // 5m default
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const slLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const tpLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const entryLineRef = useRef<ISeriesApi<"Line"> | null>(null);

  const candles = useBybitKlines(activeSymbol, timeframe.value, timeframe.limit);

  // Positions for active symbol
  const symbolPositions = useMemo(
    () => positions.filter((p) => p.symbol === activeSymbol),
    [positions, activeSymbol]
  );

  const handleSymbolChange = useCallback(
    (sym: string) => {
      setActiveSymbol(sym);
      onSymbolChange?.(sym);
    },
    [onSymbolChange]
  );

  // Click position row → switch chart
  useEffect(() => {
    if (defaultSymbol && symbols.includes(defaultSymbol)) {
      setActiveSymbol(defaultSymbol);
    }
  }, [defaultSymbol, symbols]);

  // ─── Chart lifecycle ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    // Cleanup previous
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }
    containerRef.current.innerHTML = "";

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(255,255,255,0.55)",
        fontFamily: "'Inter', system-ui, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(255,255,255,0.15)", width: 1, style: 3, labelBackgroundColor: "rgba(30,30,40,0.9)" },
        horzLine: { color: "rgba(255,255,255,0.15)", width: 1, style: 3, labelBackgroundColor: "rgba(30,30,40,0.9)" },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        barSpacing: 8,
      },
      width: containerRef.current.clientWidth,
      height: 360,
    });
    chartRef.current = chart;

    // Candles
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });
    candleSeriesRef.current = series as ISeriesApi<"Candlestick">;

    // Dedupe + sort + shift to local time
    const tzOffsetSec = new Date().getTimezoneOffset() * -60;
    const seen = new Map<number, (typeof candles)[0]>();
    for (const c of candles) {
      if (!Number.isFinite(c.time) || !Number.isFinite(c.close)) continue;
      seen.set(c.time, c);
    }
    const sorted = Array.from(seen.values()).sort((a, b) => a.time - b.time);
    series.setData(
      sorted.map((c) => ({
        time: (c.time + tzOffsetSec) as UTCTimestamp,
        open: c.open,
        high: Math.max(c.high, c.open, c.close),
        low: Math.min(c.low, c.open, c.close),
        close: c.close,
      }))
    );

    // Position overlays
    if (symbolPositions.length > 0 && sorted.length > 1) {
      const firstTime = (sorted[0].time + tzOffsetSec) as UTCTimestamp;
      const lastTime = (sorted[sorted.length - 1].time + tzOffsetSec) as UTCTimestamp;

      // Aggregate: use first position's levels (most relevant)
      const pos = symbolPositions[0];

      if (pos.entry_price) {
        const line = chart.addSeries(LineSeries, {
          color: "rgba(99,102,241,0.7)",
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        line.setData([
          { time: firstTime, value: pos.entry_price },
          { time: lastTime, value: pos.entry_price },
        ]);
        entryLineRef.current = line as ISeriesApi<"Line">;
      }

      if (pos.stop_loss) {
        const line = chart.addSeries(LineSeries, {
          color: "rgba(239,68,68,0.5)",
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        line.setData([
          { time: firstTime, value: pos.stop_loss },
          { time: lastTime, value: pos.stop_loss },
        ]);
        slLineRef.current = line as ISeriesApi<"Line">;
      }

      if (pos.take_profit) {
        const line = chart.addSeries(LineSeries, {
          color: "rgba(16,185,129,0.5)",
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        line.setData([
          { time: firstTime, value: pos.take_profit },
          { time: lastTime, value: pos.take_profit },
        ]);
        tpLineRef.current = line as ISeriesApi<"Line">;
      }

      // Entry markers
      try {
        const markers: SeriesMarker<Time>[] = symbolPositions
          .filter((p) => p.opened_at)
          .map((p) => ({
            time: ((p.opened_at || 0) + tzOffsetSec) as unknown as UTCTimestamp,
            position: "belowBar" as const,
            color: "#6366f1",
            shape: "arrowUp" as const,
            size: 1.5,
            text: `${p.strategy_id?.replace("spot_", "") || "entry"} ${p.size.toFixed(4)}`,
          }))
          .sort((a, b) => (a.time as number) - (b.time as number));

        if (markers.length && "setMarkers" in series) {
          (series as any).setMarkers(markers);
        }
      } catch {
        /* markers optional */
      }
    }

    chart.timeScale().fitContent();

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chartRef.current?.remove();
      chartRef.current = null;
    };
  }, [candles, symbolPositions]);

  // ─── Price info ──────────────────────────────────────────────────────────

  const lastPrice = candles.length > 0 ? candles[candles.length - 1].close : null;
  const prevClose = candles.length > 1 ? candles[candles.length - 2].close : null;
  const changePct = lastPrice && prevClose ? ((lastPrice - prevClose) / prevClose) * 100 : null;

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div
      className={cn(
        "rounded-xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-sm overflow-hidden",
        className
      )}
    >
      {/* Header: token tabs + timeframe + price */}
      <div className="flex items-center justify-between px-4 pt-3 pb-2">
        {/* Token tabs */}
        <div className="flex items-center gap-1">
          {symbols.map((sym) => {
            const isActive = sym === activeSymbol;
            const hasPosition = positions.some((p) => p.symbol === sym);
            const ticker = sym.replace("USDT", "");
            return (
              <button
                key={sym}
                onClick={() => handleSymbolChange(sym)}
                className={cn(
                  "relative px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                  isActive
                    ? "bg-white/[0.1] text-white shadow-sm"
                    : "text-white/40 hover:text-white/70 hover:bg-white/[0.05]"
                )}
              >
                {ticker}
                {hasPosition && (
                  <span
                    className={cn(
                      "absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full",
                      isActive ? "bg-emerald-400" : "bg-emerald-400/60"
                    )}
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* Price + change */}
        <div className="flex items-center gap-4">
          {lastPrice != null && (
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-semibold tabular-nums tracking-tight">
                {lastPrice < 1 ? lastPrice.toFixed(4) : lastPrice < 100 ? lastPrice.toFixed(2) : lastPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
              {changePct != null && (
                <span
                  className={cn(
                    "text-xs font-medium tabular-nums",
                    changePct >= 0 ? "text-emerald-400" : "text-red-400"
                  )}
                >
                  {changePct >= 0 ? "+" : ""}
                  {changePct.toFixed(2)}%
                </span>
              )}
            </div>
          )}

          {/* Timeframe selector */}
          <div className="flex items-center gap-0.5 bg-white/[0.04] rounded-lg p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf)}
                className={cn(
                  "px-2 py-1 rounded-md text-[10px] font-medium transition-all",
                  tf.value === timeframe.value
                    ? "bg-white/[0.1] text-white"
                    : "text-white/35 hover:text-white/60"
                )}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Position info strip */}
      {symbolPositions.length > 0 && (
        <div className="flex items-center gap-4 px-4 pb-2 text-[11px]">
          {symbolPositions.map((pos, i) => {
            const pnlBps = pos.entry_price ? ((pos.unrealized_pnl || 0) / (pos.size * pos.entry_price)) * 10000 : 0;
            return (
              <div key={i} className="flex items-center gap-2 text-white/50">
                <span className="text-indigo-400 font-medium">
                  {pos.strategy_id?.replace("spot_", "") || "position"}
                </span>
                <span>
                  {pos.size.toFixed(4)} @ {pos.entry_price.toFixed(2)}
                </span>
                <span className={cn("font-medium", pnlBps >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {pnlBps >= 0 ? "+" : ""}{pnlBps.toFixed(1)}bps
                </span>
                {pos.stop_loss && (
                  <span className="text-red-400/60">SL {pos.stop_loss.toFixed(2)}</span>
                )}
                {pos.take_profit && (
                  <span className="text-emerald-400/60">TP {pos.take_profit.toFixed(2)}</span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Chart */}
      <div ref={containerRef} className="w-full" style={{ height: 360 }} />

      {/* Legend */}
      {symbolPositions.length > 0 && (
        <div className="flex items-center gap-4 px-4 py-2 border-t border-white/[0.05] text-[10px] text-white/30">
          <span className="flex items-center gap-1">
            <span className="w-3 h-px bg-indigo-400 inline-block" /> Entry
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-px bg-red-400/50 inline-block" style={{ borderTop: "1px dashed" }} /> Stop Loss
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-px bg-emerald-400/50 inline-block" style={{ borderTop: "1px dashed" }} /> Take Profit
          </span>
        </div>
      )}
    </div>
  );
}
