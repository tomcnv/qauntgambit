import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  parseSSEEvent,
  sendCopilotMessage,
  listConversations,
  getConversationMessages,
  deleteConversation,
  listSettingsSnapshots,
  revertSettings,
  type AgentEvent,
} from "../copilot";

// Mock apiFetch
vi.mock("../client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "../client";
const mockApiFetch = vi.mocked(apiFetch);

// --- parseSSEEvent tests ---

describe("parseSSEEvent", () => {
  it("parses text_delta events", () => {
    const event = parseSSEEvent(JSON.stringify({ type: "text_delta", content: "hello" }));
    expect(event).toEqual({ type: "text_delta", content: "hello" });
  });

  it("parses tool_call_start events with snake_case", () => {
    const event = parseSSEEvent(
      JSON.stringify({ type: "tool_call_start", tool_name: "query_trades", parameters: { symbol: "BTC" } }),
    );
    expect(event).toEqual({ type: "tool_call_start", toolName: "query_trades", parameters: { symbol: "BTC" } });
  });

  it("parses tool_call_result events", () => {
    const event = parseSSEEvent(
      JSON.stringify({ type: "tool_call_result", tool_name: "query_trades", result: [1, 2], duration_ms: 42, success: true }),
    );
    expect(event).toEqual({ type: "tool_call_result", toolName: "query_trades", result: [1, 2], durationMs: 42, success: true });
  });

  it("parses settings_mutation_proposal events", () => {
    const event = parseSSEEvent(
      JSON.stringify({
        type: "settings_mutation_proposal",
        mutation: {
          id: "m1",
          changes: { risk: { old: 0.1, new: 0.2 } },
          rationale: "Increase risk",
          status: "proposed",
          constraint_violations: [],
        },
      }),
    );
    expect(event).toEqual({
      type: "settings_mutation_proposal",
      mutation: {
        id: "m1",
        changes: { risk: { old: 0.1, new: 0.2 } },
        rationale: "Increase risk",
        status: "proposed",
        constraintViolations: [],
      },
    });
  });

  it("parses error events", () => {
    const event = parseSSEEvent(JSON.stringify({ type: "error", message: "Something broke" }));
    expect(event).toEqual({ type: "error", message: "Something broke" });
  });

  it("parses done events from JSON", () => {
    const event = parseSSEEvent(JSON.stringify({ type: "done" }));
    expect(event).toEqual({ type: "done" });
  });

  it("parses [DONE] sentinel", () => {
    const event = parseSSEEvent("[DONE]");
    expect(event).toEqual({ type: "done" });
  });

  it("returns null for invalid JSON", () => {
    expect(parseSSEEvent("not json")).toBeNull();
  });

  it("returns null for unknown event type", () => {
    expect(parseSSEEvent(JSON.stringify({ type: "unknown_type" }))).toBeNull();
  });

  it("defaults missing content in text_delta to empty string", () => {
    const event = parseSSEEvent(JSON.stringify({ type: "text_delta" }));
    expect(event).toEqual({ type: "text_delta", content: "" });
  });
});

// --- sendCopilotMessage tests ---

describe("sendCopilotMessage", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  function createSSEStream(lines: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    const text = lines.join("\n") + "\n";
    return new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(text));
        controller.close();
      },
    });
  }

  it("streams SSE events and calls onDelta", async () => {
    const events: AgentEvent[] = [];
    mockApiFetch.mockResolvedValue(
      new Response(
        createSSEStream([
          'data: {"type":"text_delta","content":"Hi"}',
          'data: {"type":"done"}',
        ]),
        { status: 200 },
      ),
    );

    await sendCopilotMessage("hello", null, null, (e) => events.push(e));

    expect(events).toEqual([
      { type: "text_delta", content: "Hi" },
      { type: "done" },
    ]);
  });

  it("sends conversation_id and trade_context in the body", async () => {
    mockApiFetch.mockResolvedValue(
      new Response(createSSEStream(['data: {"type":"done"}']), { status: 200 }),
    );

    await sendCopilotMessage(
      "analyze",
      "conv-1",
      { tradeId: "t1", symbol: "BTC", side: "buy", entryPrice: 100, exitPrice: 110, pnl: 10, holdTimeSeconds: 60 },
      () => {},
    );

    expect(mockApiFetch).toHaveBeenCalledWith("/v1/copilot/chat", expect.objectContaining({ method: "POST" }));
    const body = JSON.parse((mockApiFetch.mock.calls[0][1] as RequestInit).body as string);
    expect(body.conversation_id).toBe("conv-1");
    expect(body.trade_context.trade_id).toBe("t1");
    expect(body.trade_context.symbol).toBe("BTC");
  });

  it("calls onDelta with error when response is not ok", async () => {
    const events: AgentEvent[] = [];
    mockApiFetch.mockResolvedValue(new Response("Bad request", { status: 400 }));

    await sendCopilotMessage("hello", null, null, (e) => events.push(e));

    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("error");
    expect(events[1].type).toBe("done");
  });

  it("calls onDelta with error when no body stream", async () => {
    const events: AgentEvent[] = [];
    // Response with null body
    const resp = new Response(null, { status: 200 });
    Object.defineProperty(resp, "body", { value: null });
    mockApiFetch.mockResolvedValue(resp);

    await sendCopilotMessage("hello", null, null, (e) => events.push(e));

    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("error");
    expect(events[1].type).toBe("done");
  });
});

// --- listConversations tests ---

describe("listConversations", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("fetches conversations with query params", async () => {
    mockApiFetch.mockResolvedValue(
      new Response(JSON.stringify({ conversations: [{ id: "c1", title: "Test", created_at: 1, updated_at: 2, message_count: 5 }], total: 1 }), { status: 200 }),
    );

    const result = await listConversations({ search: "test", page: 2 });

    expect(mockApiFetch).toHaveBeenCalledWith(expect.stringContaining("search=test"));
    expect(mockApiFetch).toHaveBeenCalledWith(expect.stringContaining("page=2"));
    expect(result.conversations).toHaveLength(1);
    expect(result.conversations[0].id).toBe("c1");
    expect(result.conversations[0].messageCount).toBe(5);
    expect(result.total).toBe(1);
  });

  it("throws on non-ok response", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 500 }));
    await expect(listConversations()).rejects.toThrow("Failed to list conversations");
  });
});

// --- getConversationMessages tests ---

describe("getConversationMessages", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("fetches and normalizes messages", async () => {
    mockApiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          messages: [{ id: "m1", role: "user", content: "hi", timestamp: 100 }],
        }),
        { status: 200 },
      ),
    );

    const messages = await getConversationMessages("conv-1");
    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe("m1");
    expect(messages[0].role).toBe("user");
  });

  it("throws on non-ok response", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 404 }));
    await expect(getConversationMessages("bad-id")).rejects.toThrow("Failed to get messages");
  });
});

// --- deleteConversation tests ---

describe("deleteConversation", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("sends DELETE request", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 200 }));
    await deleteConversation("conv-1");
    expect(mockApiFetch).toHaveBeenCalledWith("/v1/copilot/conversations/conv-1", { method: "DELETE" });
  });

  it("throws on non-ok response", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 500 }));
    await expect(deleteConversation("conv-1")).rejects.toThrow("Failed to delete conversation");
  });
});

// --- listSettingsSnapshots tests ---

describe("listSettingsSnapshots", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("fetches and normalizes snapshots", async () => {
    mockApiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          snapshots: [{ id: "s1", version: 1, settings: { risk: 0.1 }, actor: "copilot", created_at: 100 }],
        }),
        { status: 200 },
      ),
    );

    const snapshots = await listSettingsSnapshots();
    expect(snapshots).toHaveLength(1);
    expect(snapshots[0].id).toBe("s1");
    expect(snapshots[0].actor).toBe("copilot");
    expect(snapshots[0].createdAt).toBe(100);
  });

  it("throws on non-ok response", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 500 }));
    await expect(listSettingsSnapshots()).rejects.toThrow("Failed to list settings snapshots");
  });
});

// --- revertSettings tests ---

describe("revertSettings", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("sends POST to revert endpoint", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 200 }));
    await revertSettings("snap-1");
    expect(mockApiFetch).toHaveBeenCalledWith("/v1/copilot/settings/revert/snap-1", { method: "POST" });
  });

  it("throws on non-ok response", async () => {
    mockApiFetch.mockResolvedValue(new Response("", { status: 404 }));
    await expect(revertSettings("bad-id")).rejects.toThrow("Failed to revert settings");
  });
});
