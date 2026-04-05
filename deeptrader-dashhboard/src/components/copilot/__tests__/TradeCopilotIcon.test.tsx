import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TradeCopilotIcon } from "../TradeCopilotIcon";
import { useCopilotStore, type QuantTrade } from "@/store/copilot-store";

const sampleTrade: QuantTrade = {
  id: "trade-123",
  symbol: "BTCUSDT",
  side: "buy",
  entry_price: 42000,
  exit_price: 43500,
  pnl: 150,
  holdingDuration: 3600000,
  decisionTrace: "trace-abc",
  size: 0.1,
  timestamp: 1700000000000,
};

beforeEach(() => {
  useCopilotStore.setState({
    isOpen: false,
    conversationId: null,
    messages: [],
    isLoading: false,
    error: null,
    tradeContext: null,
    conversationHistory: [],
    searchQuery: "",
  });
});

describe("TradeCopilotIcon", () => {
  it("renders the icon button", () => {
    render(<TradeCopilotIcon trade={sampleTrade} />);
    expect(screen.getByTestId("trade-copilot-icon")).toBeInTheDocument();
  });

  it("calls openWithTradeContext with the trade on click", () => {
    render(<TradeCopilotIcon trade={sampleTrade} />);
    fireEvent.click(screen.getByTestId("trade-copilot-icon"));

    const state = useCopilotStore.getState();
    expect(state.isOpen).toBe(true);
    expect(state.tradeContext).toEqual({
      tradeId: "trade-123",
      symbol: "BTCUSDT",
      side: "buy",
      entryPrice: 42000,
      exitPrice: 43500,
      pnl: 150,
      holdTimeSeconds: 3600,
      decisionTraceId: "trace-abc",
      quantity: 0.1,
      entryTime: 1700000000000,
    });
  });

  it("has accessible label", () => {
    render(<TradeCopilotIcon trade={sampleTrade} />);
    expect(screen.getByLabelText("Ask Copilot about this trade")).toBeInTheDocument();
  });
});
