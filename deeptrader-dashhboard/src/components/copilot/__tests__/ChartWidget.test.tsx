import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChartWidget } from "../ChartWidget";
import type { CandleData } from "@/lib/api/copilot";

// Mock lightweight-charts — canvas APIs are not available in jsdom.
// vi.mock factory is hoisted, so all values must be inline.
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn().mockReturnValue({
    addSeries: vi.fn().mockReturnValue({ setData: vi.fn() }),
    timeScale: vi.fn().mockReturnValue({ fitContent: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
  CandlestickSeries: "CandlestickSeries",
  ColorType: { Solid: "Solid" },
  CrosshairMode: { Normal: 0 },
}));

const sampleCandles: CandleData[] = [
  { time: 1700000000, open: 42000, high: 42100, low: 41900, close: 42050, volume: 10 },
  { time: 1700000060, open: 42050, high: 42200, low: 42000, close: 42150, volume: 15 },
  { time: 1700000120, open: 42150, high: 42300, low: 42100, close: 42250, volume: 12 },
];

describe("ChartWidget", () => {
  it('renders "No data available" for empty candles', () => {
    render(<ChartWidget symbol="BTCUSDT" timeframeSec={60} candles={[]} />);
    expect(screen.getByText("No data available")).toBeInTheDocument();
    expect(screen.getByTestId("chart-no-data")).toBeInTheDocument();
  });

  it("renders chart container for valid candles", () => {
    render(<ChartWidget symbol="BTCUSDT" timeframeSec={60} candles={sampleCandles} />);
    expect(screen.getByTestId("chart-container")).toBeInTheDocument();
    expect(screen.queryByText("No data available")).not.toBeInTheDocument();
  });

  it("displays symbol and timeframe label", () => {
    render(<ChartWidget symbol="ETHUSDT" timeframeSec={300} candles={sampleCandles} />);
    expect(screen.getByText("ETHUSDT · 5m")).toBeInTheDocument();
  });

  it("formats hourly timeframe label correctly", () => {
    render(<ChartWidget symbol="BTCUSDT" timeframeSec={3600} candles={sampleCandles} />);
    expect(screen.getByText("BTCUSDT · 1h")).toBeInTheDocument();
  });

  it("formats seconds timeframe label correctly", () => {
    render(<ChartWidget symbol="BTCUSDT" timeframeSec={30} candles={sampleCandles} />);
    expect(screen.getByText("BTCUSDT · 30s")).toBeInTheDocument();
  });
});
