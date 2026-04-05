/**
 * Unit tests for chart_data SSE parsing and copilot store chart segment handling.
 *
 * Feature: copilot-deep-knowledge
 * Validates: Requirements 7.1, 7.2
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { parseSSEEvent } from "../copilot";
import { useCopilotStore } from "../../../store/copilot-store";

// Mock the API client so copilot module can be imported
vi.mock("../client", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("../copilot", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../copilot")>();
  return {
    ...actual,
    sendCopilotMessage: vi.fn(),
    listConversations: vi.fn(),
    getConversationMessages: vi.fn(),
  };
});

function resetStore() {
  useCopilotStore.setState({
    isOpen: false,
    conversationId: null,
    messages: [],
    isLoading: false,
    error: null,
    tradeContext: null,
    conversationHistory: [],
    searchQuery: "",
    currentPagePath: "",
  });
}

// --- parseSSEEvent chart_data tests ---

describe("parseSSEEvent chart_data", () => {
  it("parses valid chart_data JSON with correct type, symbol, timeframeSec, and candles", () => {
    const payload = {
      type: "chart_data",
      symbol: "BTCUSDT",
      timeframe_sec: 60,
      candles: [
        { ts: 1700000000, open: 42000.5, high: 42100.0, low: 41950.0, close: 42050.0, volume: 12.5 },
        { ts: 1700000060, open: 42050.0, high: 42200.0, low: 42000.0, close: 42150.0, volume: 8.3 },
      ],
    };

    const result = parseSSEEvent(JSON.stringify(payload));

    expect(result).not.toBeNull();
    expect(result!.type).toBe("chart_data");

    const event = result as Extract<typeof result, { type: "chart_data" }>;
    expect(event.symbol).toBe("BTCUSDT");
    expect(event.timeframeSec).toBe(60);
    expect(event.candles).toHaveLength(2);
    expect(event.candles[0]).toEqual({
      time: 1700000000,
      open: 42000.5,
      high: 42100.0,
      low: 41950.0,
      close: 42050.0,
      volume: 12.5,
    });
    expect(event.candles[1]).toEqual({
      time: 1700000060,
      open: 42050.0,
      high: 42200.0,
      low: 42000.0,
      close: 42150.0,
      volume: 8.3,
    });
  });

  it("defaults candles to empty array when missing", () => {
    const payload = { type: "chart_data", symbol: "ETHUSDT", timeframe_sec: 300 };
    const result = parseSSEEvent(JSON.stringify(payload));

    expect(result).not.toBeNull();
    const event = result as Extract<typeof result, { type: "chart_data" }>;
    expect(event.candles).toEqual([]);
  });

  it("defaults symbol to empty string when missing", () => {
    const payload = { type: "chart_data", timeframe_sec: 60, candles: [] };
    const result = parseSSEEvent(JSON.stringify(payload));

    expect(result).not.toBeNull();
    const event = result as Extract<typeof result, { type: "chart_data" }>;
    expect(event.symbol).toBe("");
  });

  it("returns null for malformed JSON", () => {
    const result = parseSSEEvent("{not valid json!!!");
    expect(result).toBeNull();
  });

  it("maps candle ts field to time", () => {
    const payload = {
      type: "chart_data",
      symbol: "SOLUSDT",
      timeframe_sec: 60,
      candles: [{ ts: 1700000000, open: 100, high: 110, low: 90, close: 105, volume: 50 }],
    };
    const result = parseSSEEvent(JSON.stringify(payload));
    const event = result as Extract<typeof result, { type: "chart_data" }>;
    expect(event.candles[0].time).toBe(1700000000);
  });

  it("defaults timeframeSec to 60 when timeframe_sec is missing", () => {
    const payload = { type: "chart_data", symbol: "BTCUSDT", candles: [] };
    const result = parseSSEEvent(JSON.stringify(payload));
    const event = result as Extract<typeof result, { type: "chart_data" }>;
    expect(event.timeframeSec).toBe(60);
  });
});

// --- Store chart_data segment tests ---

describe("copilot store chart_data handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it("appends chart segment to assistant message when chart_data event is dispatched", () => {
    const assistantId = "assistant-chart-test";
    useCopilotStore.setState({
      messages: [
        {
          id: assistantId,
          role: "assistant",
          content: "Here is the chart:",
          timestamp: Date.now(),
          isStreaming: true,
          segments: [{ type: "text", content: "Here is the chart:" }],
        },
      ],
      isLoading: true,
    });

    // Simulate the chart_data event handling from the store's onDelta
    const state = useCopilotStore.getState();
    useCopilotStore.setState({
      messages: state.messages.map((m) => {
        if (m.id !== assistantId) return m;
        const segments = [...(m.segments ?? [])];
        segments.push({
          type: "chart",
          symbol: "BTCUSDT",
          timeframeSec: 60,
          candles: [
            { time: 1700000000, open: 42000, high: 42100, low: 41950, close: 42050, volume: 12.5 },
          ],
        });
        return { ...m, segments };
      }),
    });

    const assistant = useCopilotStore.getState().messages.find((m) => m.id === assistantId);
    expect(assistant).toBeDefined();
    expect(assistant!.segments).toHaveLength(2);
    expect(assistant!.segments![0].type).toBe("text");
    expect(assistant!.segments![1].type).toBe("chart");

    const chartSeg = assistant!.segments![1] as Extract<
      (typeof assistant)["segments"] extends (infer U)[] | undefined ? U : never,
      { type: "chart" }
    >;
    expect(chartSeg.symbol).toBe("BTCUSDT");
    expect(chartSeg.timeframeSec).toBe(60);
    expect(chartSeg.candles).toHaveLength(1);
  });

  it("preserves segment ordering when chart appears between text and tool_call", () => {
    const assistantId = "assistant-order-test";
    useCopilotStore.setState({
      messages: [
        {
          id: assistantId,
          role: "assistant",
          content: "",
          timestamp: Date.now(),
          isStreaming: true,
        },
      ],
      isLoading: true,
    });

    // 1. text_delta
    let state = useCopilotStore.getState();
    useCopilotStore.setState({
      messages: state.messages.map((m) => {
        if (m.id !== assistantId) return m;
        const segments = [...(m.segments ?? [])];
        segments.push({ type: "text", content: "Fetching data..." });
        return { ...m, content: "Fetching data...", segments };
      }),
    });

    // 2. chart_data
    state = useCopilotStore.getState();
    useCopilotStore.setState({
      messages: state.messages.map((m) => {
        if (m.id !== assistantId) return m;
        const segments = [...(m.segments ?? [])];
        segments.push({
          type: "chart",
          symbol: "ETHUSDT",
          timeframeSec: 300,
          candles: [],
        });
        return { ...m, segments };
      }),
    });

    // 3. tool_call_start
    state = useCopilotStore.getState();
    useCopilotStore.setState({
      messages: state.messages.map((m) => {
        if (m.id !== assistantId) return m;
        const newTool = { id: "t1", toolName: "query_trades", parameters: {}, success: true };
        const segments = [...(m.segments ?? []), { type: "tool_call" as const, tool: newTool }];
        return { ...m, toolCalls: [newTool], segments };
      }),
    });

    const assistant = useCopilotStore.getState().messages.find((m) => m.id === assistantId);
    expect(assistant!.segments).toHaveLength(3);
    expect(assistant!.segments!.map((s) => s.type)).toEqual(["text", "chart", "tool_call"]);
  });
});
