/**
 * Copilot Store
 *
 * Manages the copilot chat panel UI state: messages, conversations,
 * streaming, trade context, and conversation history/search.
 * No persistence — conversation state resets on page reload.
 */

import { create } from "zustand";
import {
  sendCopilotMessage,
  listConversations,
  getConversationMessages,
  type AgentEvent,
  type CopilotMessage,
  type TradeContext,
  type ConversationSummary,
  type ContentSegment,
} from "../lib/api/copilot";

/** Generate a UUID, falling back to a manual implementation for non-secure contexts (plain HTTP). */
function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for non-secure contexts (http:// on non-localhost)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// Minimal QuantTrade shape needed to extract TradeContext
export interface QuantTrade {
  id: string;
  symbol: string;
  side: string;
  entry_price?: number;
  exit_price?: number;
  pnl?: number;
  holdingDuration?: number; // milliseconds
  decisionTrace?: string;
  size?: number;
  timestamp?: number;
}

export interface CopilotState {
  isOpen: boolean;
  conversationId: string | null;
  messages: CopilotMessage[];
  isLoading: boolean;
  error: string | null;
  tradeContext: TradeContext | null;
  conversationHistory: ConversationSummary[];
  searchQuery: string;
  currentPagePath: string;

  toggle: () => void;
  setCurrentPagePath: (path: string) => void;
  openWithTradeContext: (trade: QuantTrade) => void;
  sendMessage: (content: string) => Promise<void>;
  newConversation: () => void;
  clearError: () => void;
  searchConversations: (query: string) => Promise<void>;
  loadConversation: (conversationId: string) => Promise<void>;
}

function extractTradeContext(trade: QuantTrade): TradeContext {
  return {
    tradeId: trade.id,
    symbol: trade.symbol,
    side: trade.side,
    entryPrice: trade.entry_price ?? 0,
    exitPrice: trade.exit_price ?? 0,
    pnl: trade.pnl ?? 0,
    holdTimeSeconds: trade.holdingDuration != null ? trade.holdingDuration / 1000 : 0,
    decisionTraceId: trade.decisionTrace ?? undefined,
    quantity: trade.size ?? undefined,
    entryTime: trade.timestamp ?? undefined,
  };
}

export const useCopilotStore = create<CopilotState>()((set, get) => ({
  // --- State ---
  isOpen: false,
  conversationId: null,
  messages: [],
  isLoading: false,
  error: null,
  tradeContext: null,
  conversationHistory: [],
  searchQuery: "",
  currentPagePath: "",

  // --- Actions ---

  toggle: () => set((s) => ({ isOpen: !s.isOpen })),

  setCurrentPagePath: (path) => set({ currentPagePath: path }),

  openWithTradeContext: (trade) => {
    const tradeContext = extractTradeContext(trade);
    set({
      isOpen: true,
      tradeContext,
      conversationId: null,
      messages: [],
      error: null,
    });
  },

  sendMessage: async (content) => {
    const { conversationId, tradeContext, currentPagePath } = get();

    // Add user message immediately
    const userMessage: CopilotMessage = {
      id: generateUUID(),
      role: "user",
      content,
      timestamp: Date.now(),
    };

    // Create placeholder assistant message for streaming
    const assistantId = generateUUID();
    const assistantMessage: CopilotMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      timestamp: Date.now(),
      isStreaming: true,
    };

    set((s) => ({
      messages: [...s.messages, userMessage, assistantMessage],
      isLoading: true,
      error: null,
    }));

    const onDelta = (event: AgentEvent) => {
      switch (event.type) {
        case "conversation_id":
          set({ conversationId: event.conversationId });
          break;

        case "text_delta":
          set((s) => ({
            messages: s.messages.map((m) => {
              if (m.id !== assistantId) return m;
              const segments = [...(m.segments ?? [])];
              const last = segments[segments.length - 1];
              if (last && last.type === "text") {
                // Append to existing text segment
                segments[segments.length - 1] = { type: "text", content: last.content + event.content };
              } else {
                // Start a new text segment (first text, or text after a tool call)
                segments.push({ type: "text", content: event.content });
              }
              return { ...m, content: m.content + event.content, segments };
            }),
          }));
          break;

        case "tool_call_start":
          set((s) => ({
            messages: s.messages.map((m) => {
              if (m.id !== assistantId) return m;
              const newTool = {
                id: generateUUID(),
                toolName: event.toolName,
                parameters: event.parameters,
                success: true,
              };
              const segments: ContentSegment[] = [...(m.segments ?? []), { type: "tool_call", tool: newTool }];
              return {
                ...m,
                toolCalls: [...(m.toolCalls ?? []), newTool],
                segments,
              };
            }),
          }));
          break;

        case "tool_call_result": {
          set((s) => ({
            messages: s.messages.map((m) => {
              if (m.id !== assistantId || !m.toolCalls?.length) return m;
              // Update the last tool call with the result
              const calls = [...m.toolCalls];
              const lastIdx = calls.length - 1;
              const updatedTool = {
                ...calls[lastIdx],
                result: event.result,
                durationMs: event.durationMs,
                success: event.success,
              };
              calls[lastIdx] = updatedTool;
              // Also update the matching segment
              const segments = (m.segments ?? []).map((seg) =>
                seg.type === "tool_call" && seg.tool.id === updatedTool.id
                  ? { ...seg, tool: updatedTool }
                  : seg,
              );
              return { ...m, toolCalls: calls, segments };
            }),
          }));
          break;
        }

        case "settings_mutation_proposal":
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    settingsMutation: event.mutation,
                    segments: [...(m.segments ?? []), { type: "settings_mutation" as const, mutation: event.mutation }],
                  }
                : m,
            ),
          }));
          break;

        case "chart_data":
          set((s) => ({
            messages: s.messages.map((m) => {
              if (m.id !== assistantId) return m;
              const segments = [...(m.segments ?? [])];
              segments.push({
                type: "chart",
                symbol: event.symbol,
                timeframeSec: event.timeframeSec,
                candles: event.candles,
              });
              return { ...m, segments };
            }),
          }));
          break;

        case "error":
          set({ error: event.message });
          break;

        case "done":
          set((s) => ({
            isLoading: false,
            messages: s.messages.map((m) =>
              m.id === assistantId ? { ...m, isStreaming: false } : m,
            ),
          }));
          break;
      }
    };

    try {
      await sendCopilotMessage(content, conversationId, tradeContext, onDelta, currentPagePath);
    } catch (err) {
      set((s) => ({
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to send message",
        messages: s.messages.map((m) =>
          m.id === assistantId ? { ...m, isStreaming: false } : m,
        ),
      }));
    }
  },

  newConversation: () =>
    set({
      conversationId: null,
      messages: [],
      tradeContext: null,
      error: null,
    }),

  clearError: () => set({ error: null }),

  searchConversations: async (query) => {
    set({ searchQuery: query });
    try {
      const { conversations } = await listConversations({
        search: query || undefined,
      });
      set({ conversationHistory: conversations });
    } catch (err) {
      set({
        error:
          err instanceof Error ? err.message : "Failed to search conversations",
      });
    }
  },

  loadConversation: async (conversationId) => {
    set({ isLoading: true, error: null });
    try {
      const messages = await getConversationMessages(conversationId);
      set({
        conversationId,
        messages,
        isLoading: false,
        tradeContext: null,
      });
    } catch (err) {
      set({
        isLoading: false,
        error:
          err instanceof Error
            ? err.message
            : "Failed to load conversation",
      });
    }
  },
}));
