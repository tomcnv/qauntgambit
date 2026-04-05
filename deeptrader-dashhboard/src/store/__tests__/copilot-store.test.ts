import { describe, it, expect, vi, beforeEach } from "vitest";
import { useCopilotStore, type QuantTrade } from "../copilot-store";

// Mock the API client
vi.mock("../../lib/api/copilot", () => ({
  sendCopilotMessage: vi.fn(),
  listConversations: vi.fn(),
  getConversationMessages: vi.fn(),
}));

import {
  sendCopilotMessage,
  listConversations,
  getConversationMessages,
} from "../../lib/api/copilot";

const mockSendCopilotMessage = vi.mocked(sendCopilotMessage);
const mockListConversations = vi.mocked(listConversations);
const mockGetConversationMessages = vi.mocked(getConversationMessages);

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

const sampleTrade: QuantTrade = {
  id: "trade-1",
  symbol: "BTCUSDT",
  side: "buy",
  entry_price: 50000,
  exit_price: 51000,
  pnl: 100,
  holdingDuration: 3600000, // 1 hour in ms
  decisionTrace: "trace-abc",
  size: 0.5,
  timestamp: 1700000000,
};

describe("copilot-store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  describe("toggle", () => {
    it("toggles isOpen from false to true", () => {
      useCopilotStore.getState().toggle();
      expect(useCopilotStore.getState().isOpen).toBe(true);
    });

    it("toggles isOpen from true to false", () => {
      useCopilotStore.setState({ isOpen: true });
      useCopilotStore.getState().toggle();
      expect(useCopilotStore.getState().isOpen).toBe(false);
    });
  });

  describe("openWithTradeContext", () => {
    it("opens panel and sets trade context from QuantTrade", () => {
      useCopilotStore.getState().openWithTradeContext(sampleTrade);
      const state = useCopilotStore.getState();

      expect(state.isOpen).toBe(true);
      expect(state.tradeContext).toEqual({
        tradeId: "trade-1",
        symbol: "BTCUSDT",
        side: "buy",
        entryPrice: 50000,
        exitPrice: 51000,
        pnl: 100,
        holdTimeSeconds: 3600,
        decisionTraceId: "trace-abc",
        quantity: 0.5,
        entryTime: 1700000000,
      });
    });

    it("resets messages, conversationId, and error", () => {
      useCopilotStore.setState({
        messages: [{ id: "m1", role: "user", content: "old", timestamp: 0 }],
        conversationId: "old-conv",
        error: "old error",
      });

      useCopilotStore.getState().openWithTradeContext(sampleTrade);
      const state = useCopilotStore.getState();

      expect(state.messages).toEqual([]);
      expect(state.conversationId).toBeNull();
      expect(state.error).toBeNull();
    });

    it("handles trade with missing optional fields", () => {
      const minimalTrade: QuantTrade = { id: "t2", symbol: "ETH", side: "sell" };
      useCopilotStore.getState().openWithTradeContext(minimalTrade);
      const ctx = useCopilotStore.getState().tradeContext!;

      expect(ctx.entryPrice).toBe(0);
      expect(ctx.exitPrice).toBe(0);
      expect(ctx.pnl).toBe(0);
      expect(ctx.holdTimeSeconds).toBe(0);
      expect(ctx.decisionTraceId).toBeUndefined();
      expect(ctx.quantity).toBeUndefined();
    });
  });

  describe("sendMessage", () => {
    it("adds user and assistant messages, calls API, and processes text_delta + done", async () => {
      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "text_delta", content: "Hello " });
        onDelta({ type: "text_delta", content: "world" });
        onDelta({ type: "done" });
      });

      await useCopilotStore.getState().sendMessage("hi");
      const state = useCopilotStore.getState();

      expect(state.messages).toHaveLength(2);
      expect(state.messages[0].role).toBe("user");
      expect(state.messages[0].content).toBe("hi");
      expect(state.messages[1].role).toBe("assistant");
      expect(state.messages[1].content).toBe("Hello world");
      expect(state.messages[1].isStreaming).toBe(false);
      expect(state.isLoading).toBe(false);
    });

    it("processes tool_call_start and tool_call_result events", async () => {
      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "tool_call_start", toolName: "query_trades", parameters: { symbol: "BTC" } });
        onDelta({ type: "tool_call_result", toolName: "query_trades", result: [{ id: 1 }], durationMs: 50, success: true });
        onDelta({ type: "done" });
      });

      await useCopilotStore.getState().sendMessage("show trades");
      const assistant = useCopilotStore.getState().messages[1];

      expect(assistant.toolCalls).toHaveLength(1);
      expect(assistant.toolCalls![0].toolName).toBe("query_trades");
      expect(assistant.toolCalls![0].result).toEqual([{ id: 1 }]);
      expect(assistant.toolCalls![0].durationMs).toBe(50);
      expect(assistant.toolCalls![0].success).toBe(true);
    });

    it("processes settings_mutation_proposal events", async () => {
      const mutation = {
        id: "mut-1",
        changes: { risk: { old: 0.1, new: 0.2 } },
        rationale: "Increase risk",
        status: "proposed" as const,
        constraintViolations: [],
      };

      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "settings_mutation_proposal", mutation });
        onDelta({ type: "done" });
      });

      await useCopilotStore.getState().sendMessage("change risk");
      const assistant = useCopilotStore.getState().messages[1];

      expect(assistant.settingsMutation).toEqual(mutation);
    });

    it("sets error state on error event", async () => {
      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "error", message: "LLM unavailable" });
        onDelta({ type: "done" });
      });

      await useCopilotStore.getState().sendMessage("hello");
      expect(useCopilotStore.getState().error).toBe("LLM unavailable");
    });

    it("handles API client throwing an error", async () => {
      mockSendCopilotMessage.mockRejectedValue(new Error("Network error"));

      await useCopilotStore.getState().sendMessage("hello");
      const state = useCopilotStore.getState();

      expect(state.isLoading).toBe(false);
      expect(state.error).toBe("Network error");
      expect(state.messages[1].isStreaming).toBe(false);
    });

    it("passes conversationId and tradeContext to API", async () => {
      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "done" });
      });

      useCopilotStore.setState({ conversationId: "conv-42", tradeContext: { tradeId: "t1", symbol: "BTC", side: "buy", entryPrice: 100, exitPrice: 110, pnl: 10, holdTimeSeconds: 60 } });
      await useCopilotStore.getState().sendMessage("analyze");

      expect(mockSendCopilotMessage).toHaveBeenCalledWith(
        "analyze",
        "conv-42",
        expect.objectContaining({ tradeId: "t1" }),
        expect.any(Function),
        "",
      );
    });
  });

  describe("newConversation", () => {
    it("resets conversationId, messages, tradeContext, and error", () => {
      useCopilotStore.setState({
        conversationId: "conv-1",
        messages: [{ id: "m1", role: "user", content: "hi", timestamp: 0 }],
        tradeContext: { tradeId: "t1", symbol: "BTC", side: "buy", entryPrice: 0, exitPrice: 0, pnl: 0, holdTimeSeconds: 0 },
        error: "some error",
      });

      useCopilotStore.getState().newConversation();
      const state = useCopilotStore.getState();

      expect(state.conversationId).toBeNull();
      expect(state.messages).toEqual([]);
      expect(state.tradeContext).toBeNull();
      expect(state.error).toBeNull();
    });
  });

  describe("clearError", () => {
    it("clears the error state", () => {
      useCopilotStore.setState({ error: "something went wrong" });
      useCopilotStore.getState().clearError();
      expect(useCopilotStore.getState().error).toBeNull();
    });
  });

  describe("searchConversations", () => {
    it("calls listConversations and updates history", async () => {
      const conversations = [
        { id: "c1", title: "Test", createdAt: 1, updatedAt: 2, messageCount: 3 },
      ];
      mockListConversations.mockResolvedValue({ conversations, total: 1 });

      await useCopilotStore.getState().searchConversations("test");
      const state = useCopilotStore.getState();

      expect(state.searchQuery).toBe("test");
      expect(state.conversationHistory).toEqual(conversations);
      expect(mockListConversations).toHaveBeenCalledWith({ search: "test" });
    });

    it("passes undefined search when query is empty", async () => {
      mockListConversations.mockResolvedValue({ conversations: [], total: 0 });

      await useCopilotStore.getState().searchConversations("");

      expect(mockListConversations).toHaveBeenCalledWith({ search: undefined });
    });

    it("sets error on failure", async () => {
      mockListConversations.mockRejectedValue(new Error("Search failed"));

      await useCopilotStore.getState().searchConversations("test");
      expect(useCopilotStore.getState().error).toBe("Search failed");
    });
  });

  describe("loadConversation", () => {
    it("loads messages and sets conversationId", async () => {
      const messages = [
        { id: "m1", role: "user" as const, content: "hello", timestamp: 100 },
        { id: "m2", role: "assistant" as const, content: "hi there", timestamp: 101 },
      ];
      mockGetConversationMessages.mockResolvedValue(messages);

      await useCopilotStore.getState().loadConversation("conv-99");
      const state = useCopilotStore.getState();

      expect(state.conversationId).toBe("conv-99");
      expect(state.messages).toEqual(messages);
      expect(state.isLoading).toBe(false);
      expect(state.tradeContext).toBeNull();
    });

    it("sets error on failure", async () => {
      mockGetConversationMessages.mockRejectedValue(new Error("Not found"));

      await useCopilotStore.getState().loadConversation("bad-id");
      const state = useCopilotStore.getState();

      expect(state.isLoading).toBe(false);
      expect(state.error).toBe("Not found");
    });
  });

  describe("setCurrentPagePath", () => {
    it("updates currentPagePath in the store", () => {
      useCopilotStore.getState().setCurrentPagePath("/live");
      expect(useCopilotStore.getState().currentPagePath).toBe("/live");
    });

    it("sets currentPagePath to empty string", () => {
      useCopilotStore.getState().setCurrentPagePath("/orders");
      useCopilotStore.getState().setCurrentPagePath("");
      expect(useCopilotStore.getState().currentPagePath).toBe("");
    });
  });

  describe("sendMessage page context", () => {
    it("passes currentPagePath to the API as the 5th argument", async () => {
      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "done" });
      });

      useCopilotStore.setState({ currentPagePath: "/risk/limits" });
      await useCopilotStore.getState().sendMessage("what limits?");

      expect(mockSendCopilotMessage).toHaveBeenCalledWith(
        "what limits?",
        null,
        null,
        expect.any(Function),
        "/risk/limits",
      );
    });

    it("passes empty string when no page path is set", async () => {
      mockSendCopilotMessage.mockImplementation(async (_msg, _convId, _ctx, onDelta) => {
        onDelta({ type: "done" });
      });

      await useCopilotStore.getState().sendMessage("hello");

      expect(mockSendCopilotMessage).toHaveBeenCalledWith(
        "hello",
        null,
        null,
        expect.any(Function),
        "",
      );
    });
  });

  describe("newConversation does not reset currentPagePath", () => {
    it("preserves currentPagePath across new conversations", () => {
      useCopilotStore.setState({
        currentPagePath: "/signals",
        conversationId: "conv-1",
        messages: [{ id: "m1", role: "user", content: "hi", timestamp: 0 }],
        tradeContext: { tradeId: "t1", symbol: "BTC", side: "buy", entryPrice: 0, exitPrice: 0, pnl: 0, holdTimeSeconds: 0 },
        error: "some error",
      });

      useCopilotStore.getState().newConversation();
      const state = useCopilotStore.getState();

      expect(state.currentPagePath).toBe("/signals");
      expect(state.conversationId).toBeNull();
      expect(state.messages).toEqual([]);
    });
  });
});
