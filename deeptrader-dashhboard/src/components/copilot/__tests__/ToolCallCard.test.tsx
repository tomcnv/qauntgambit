import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ToolCallCard } from "../CopilotPanel";
import type { ToolCallInfo } from "@/lib/api/copilot";

const baseTool: ToolCallInfo = {
  id: "tc1",
  toolName: "query_market_price",
  parameters: { symbol: "BTCUSDT" },
  result: { mid_price: 67000.75, spread_bps: 0.746 },
  durationMs: 123,
  success: true,
};

describe("ToolCallCard", () => {
  // --- Collapsed state: no Card wrapper (Req 5.1) ---
  it("renders without Card wrapper elements", () => {
    const { container } = render(<ToolCallCard tool={baseTool} />);
    expect(container.querySelector("[data-slot='card']")).toBeNull();
    expect(container.querySelector("[data-slot='card-content']")).toBeNull();
  });

  // --- Collapsed state: shows tool name, badge, duration (Req 5.1) ---
  it("shows tool name in collapsed state", () => {
    render(<ToolCallCard tool={baseTool} />);
    expect(screen.getByText("query_market_price")).toBeInTheDocument();
  });

  it("shows success badge in collapsed state", () => {
    render(<ToolCallCard tool={baseTool} />);
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("shows fail badge when tool failed", () => {
    render(<ToolCallCard tool={{ ...baseTool, success: false }} />);
    expect(screen.getByText("fail")).toBeInTheDocument();
  });

  it("shows duration in collapsed state", () => {
    render(<ToolCallCard tool={baseTool} />);
    expect(screen.getByText("123ms", { exact: false })).toBeInTheDocument();
  });

  it("does not show duration when durationMs is undefined", () => {
    const { durationMs: _, ...noDuration } = baseTool;
    render(<ToolCallCard tool={noDuration as ToolCallInfo} />);
    expect(screen.queryByText(/\d+ms/)).toBeNull();
  });

  // --- Collapsed state: parameters and result hidden (Req 5.2) ---
  it("does not show parameters or result in collapsed state", () => {
    render(<ToolCallCard tool={baseTool} />);
    expect(screen.queryByText("Parameters")).toBeNull();
    expect(screen.queryByText("Result")).toBeNull();
  });

  // --- Click expands to show parameters and result JSON (Req 5.2) ---
  it("expands on click to show parameters JSON", () => {
    const { container } = render(<ToolCallCard tool={baseTool} />);
    fireEvent.click(screen.getByTestId("tool-call-trigger"));
    expect(screen.getByText("Parameters")).toBeInTheDocument();
    const preElements = container.querySelectorAll("pre");
    expect(preElements[0]?.textContent).toContain('"symbol": "BTCUSDT"');
  });

  it("expands on click to show result JSON", () => {
    const { container } = render(<ToolCallCard tool={baseTool} />);
    fireEvent.click(screen.getByTestId("tool-call-trigger"));
    expect(screen.getByText("Result")).toBeInTheDocument();
    const preElements = container.querySelectorAll("pre");
    expect(preElements[1]?.textContent).toContain('"mid_price": 67000.75');
    expect(preElements[1]?.textContent).toContain('"spread_bps": 0.746');
  });

  it("renders string result as-is when result is a string", () => {
    const stringResultTool = { ...baseTool, result: "No data available" };
    render(<ToolCallCard tool={stringResultTool} />);
    fireEvent.click(screen.getByTestId("tool-call-trigger"));
    expect(screen.getByText("No data available")).toBeInTheDocument();
  });

  it("does not show Result section when result is undefined", () => {
    const { result: _, ...noResult } = baseTool;
    render(<ToolCallCard tool={noResult as ToolCallInfo} />);
    fireEvent.click(screen.getByTestId("tool-call-trigger"));
    expect(screen.getByText("Parameters")).toBeInTheDocument();
    expect(screen.queryByText("Result")).toBeNull();
  });

  // --- All ToolCallInfo fields accessible in expanded view (Req 5.5) ---
  it("shows all ToolCallInfo fields in expanded view", () => {
    const fullTool: ToolCallInfo = {
      id: "tc-full",
      toolName: "query_positions",
      parameters: { symbol: "ETHUSDT", limit: 5 },
      result: [{ symbol: "ETHUSDT", size: 1.5 }],
      durationMs: 87,
      success: true,
    };
    const { container } = render(<ToolCallCard tool={fullTool} />);

    // Collapsed: name, badge, duration visible
    expect(screen.getByText("query_positions")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("87ms", { exact: false })).toBeInTheDocument();

    // Expand
    fireEvent.click(screen.getByTestId("tool-call-trigger"));

    // Parameters and result visible in pre elements
    const preElements = container.querySelectorAll("pre");
    expect(preElements[0]?.textContent).toContain('"symbol": "ETHUSDT"');
    expect(preElements[0]?.textContent).toContain('"limit": 5');
    expect(preElements[1]?.textContent).toContain('"symbol": "ETHUSDT"');
    expect(preElements[1]?.textContent).toContain('"size": 1.5');
  });
});
