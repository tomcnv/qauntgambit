import { apiFetch } from "./client";

// --- Types ---

export interface ToolCallInfo {
  id: string;
  toolName: string;
  parameters: Record<string, unknown>;
  result?: unknown;
  durationMs?: number;
  success: boolean;
}

export interface TradeContext {
  tradeId: string;
  symbol: string;
  side: string;
  entryPrice: number;
  exitPrice: number;
  pnl: number;
  holdTimeSeconds: number;
  decisionTraceId?: string;
  quantity?: number;
  entryTime?: number;
  exitTime?: number;
}

export interface SettingsMutationInfo {
  id: string;
  changes: Record<string, { old: unknown; new: unknown }>;
  rationale: string;
  status: "proposed" | "approved" | "applied" | "rejected";
  constraintViolations: string[];
}

export interface CandleData {
  time: number; // Unix timestamp in seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SettingsSnapshot {
  id: string;
  version: number;
  settings: Record<string, unknown>;
  actor: "copilot" | "user";
  conversationId?: string;
  createdAt: number;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
}

/** A segment of an assistant message — either text or a tool call, rendered in order. */
export type ContentSegment =
  | { type: "text"; content: string }
  | { type: "tool_call"; tool: ToolCallInfo }
  | { type: "settings_mutation"; mutation: SettingsMutationInfo }
  | { type: "chart"; symbol: string; timeframeSec: number; candles: CandleData[] };

export interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallInfo[];
  /** Ordered segments for inline rendering (text interleaved with tool calls). */
  segments?: ContentSegment[];
  settingsMutation?: SettingsMutationInfo;
  timestamp: number;
  isStreaming?: boolean;
}

export type AgentEvent =
  | { type: "text_delta"; content: string }
  | { type: "conversation_id"; conversationId: string }
  | { type: "tool_call_start"; toolName: string; parameters: Record<string, unknown> }
  | { type: "tool_call_result"; toolName: string; result: unknown; durationMs: number; success: boolean }
  | { type: "settings_mutation_proposal"; mutation: SettingsMutationInfo }
  | { type: "chart_data"; symbol: string; timeframeSec: number; candles: CandleData[] }
  | { type: "error"; message: string }
  | { type: "done" };

// --- SSE Parsing ---

/**
 * Parse a single SSE `data:` payload into a typed AgentEvent.
 * Returns `null` for unrecognised or malformed payloads.
 */
export function parseSSEEvent(data: string): AgentEvent | null {
  if (data === "[DONE]") {
    return { type: "done" };
  }

  try {
    const parsed = JSON.parse(data);
    const type = parsed.type as string | undefined;

    switch (type) {
      case "text_delta":
        return { type: "text_delta", content: parsed.content ?? "" };
      case "tool_call_start":
        return {
          type: "tool_call_start",
          toolName: parsed.tool_name ?? parsed.toolName ?? "",
          parameters: parsed.parameters ?? {},
        };
      case "tool_call_result":
        return {
          type: "tool_call_result",
          toolName: parsed.tool_name ?? parsed.toolName ?? "",
          result: parsed.result ?? null,
          durationMs: parsed.duration_ms ?? parsed.durationMs ?? 0,
          success: parsed.success ?? true,
        };
      case "settings_mutation_proposal":
        return {
          type: "settings_mutation_proposal",
          mutation: normalizeSettingsMutation(parsed.mutation),
        };
      case "conversation_id":
        return { type: "conversation_id", conversationId: parsed.conversation_id ?? "" };
      case "error":
        return { type: "error", message: parsed.message ?? "Unknown error" };
      case "done":
        return { type: "done" };
      case "chart_data":
        return {
          type: "chart_data",
          symbol: parsed.symbol ?? "",
          timeframeSec: parsed.timeframe_sec ?? 60,
          candles: (parsed.candles ?? []).map((c: any) => ({
            time: c.ts ?? c.time ?? 0,
            open: c.open ?? 0,
            high: c.high ?? 0,
            low: c.low ?? 0,
            close: c.close ?? 0,
            volume: c.volume ?? 0,
          })),
        };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

function normalizeSettingsMutation(raw: Record<string, unknown> | undefined): SettingsMutationInfo {
  if (!raw) {
    return { id: "", changes: {}, rationale: "", status: "proposed", constraintViolations: [] };
  }
  return {
    id: (raw.id as string) ?? "",
    changes: (raw.changes as Record<string, { old: unknown; new: unknown }>) ?? {},
    rationale: (raw.rationale as string) ?? "",
    status: (raw.status as SettingsMutationInfo["status"]) ?? "proposed",
    constraintViolations:
      (raw.constraint_violations as string[]) ?? (raw.constraintViolations as string[]) ?? [],
  };
}

// --- API Functions ---

/**
 * Send a message to the copilot and stream the response via SSE.
 * Calls `onDelta` for each parsed AgentEvent.
 */
export async function sendCopilotMessage(
  message: string,
  conversationId: string | null,
  tradeContext: TradeContext | null,
  onDelta: (event: AgentEvent) => void,
  pagePath?: string,
): Promise<void> {
  const body: Record<string, unknown> = { message };
  if (conversationId) {
    body.conversation_id = conversationId;
  }
  if (pagePath) {
    body.page_path = pagePath;
  }
  if (tradeContext) {
    body.trade_context = {
      trade_id: tradeContext.tradeId,
      symbol: tradeContext.symbol,
      side: tradeContext.side,
      entry_price: tradeContext.entryPrice,
      exit_price: tradeContext.exitPrice,
      pnl: tradeContext.pnl,
      hold_time_seconds: tradeContext.holdTimeSeconds,
      decision_trace_id: tradeContext.decisionTraceId,
      quantity: tradeContext.quantity,
      entry_time: tradeContext.entryTime,
      exit_time: tradeContext.exitTime,
    };
  }

  // Abort controller lets us kill the connection if the backend hangs.
  const controller = new AbortController();
  // If no SSE data arrives for this long, assume the backend is stuck.
  const IDLE_TIMEOUT_MS = 90_000;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  const resetIdleTimer = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS);
  };

  const clearIdleTimer = () => {
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  };

  // Start the idle timer before the request so the initial connection
  // attempt is also covered.
  resetIdleTimer();

  let response: Response;
  try {
    response = await apiFetch("/v1/copilot/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    clearIdleTimer();
    if (controller.signal.aborted) {
      onDelta({ type: "error", message: "Request timed out — the AI service may be busy. Please try again." });
      onDelta({ type: "done" });
    } else {
      onDelta({ type: "error", message: err instanceof Error ? err.message : "Request failed" });
      onDelta({ type: "done" });
    }
    return;
  }

  if (!response.ok) {
    clearIdleTimer();
    const errorText = await response.text().catch(() => "Request failed");
    onDelta({ type: "error", message: errorText });
    onDelta({ type: "done" });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    clearIdleTimer();
    onDelta({ type: "error", message: "No response stream available" });
    onDelta({ type: "done" });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  let receivedDone = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // We got data — reset the idle timer
      resetIdleTimer();

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // Keep the last (possibly incomplete) line in the buffer
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;

        const data = trimmed.slice(6);
        if (!data) continue;

        const event = parseSSEEvent(data);
        if (event) {
          onDelta(event);
          if (event.type === "done") {
            receivedDone = true;
            return;
          }
        }
      }
    }

    // Process any remaining data in the buffer
    if (buffer.trim().startsWith("data: ")) {
      const data = buffer.trim().slice(6);
      if (data) {
        const event = parseSSEEvent(data);
        if (event) {
          onDelta(event);
          if (event.type === "done") receivedDone = true;
        }
      }
    }
  } catch (err) {
    // AbortError from the idle timer — treat as timeout
    if (controller.signal.aborted) {
      onDelta({ type: "error", message: "Connection timed out waiting for a response. Please try again." });
    }
  } finally {
    clearIdleTimer();
    reader.releaseLock();
    // If the stream ended without a done event (e.g. connection dropped mid-ReAct loop),
    // synthesize a done event so the UI doesn't get stuck in a loading state.
    if (!receivedDone) {
      onDelta({ type: "done" });
    }
  }
}

/**
 * List conversations with optional search, date range, and pagination.
 */
export async function listConversations(params?: {
  search?: string;
  startDate?: string;
  endDate?: string;
  page?: number;
  pageSize?: number;
}): Promise<{ conversations: ConversationSummary[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.search) query.set("search", params.search);
  if (params?.startDate) query.set("start_date", params.startDate);
  if (params?.endDate) query.set("end_date", params.endDate);
  if (params?.page != null) query.set("page", String(params.page));
  if (params?.pageSize != null) query.set("page_size", String(params.pageSize));

  const qs = query.toString();
  const path = `/v1/copilot/conversations${qs ? `?${qs}` : ""}`;
  const response = await apiFetch(path);

  if (!response.ok) {
    throw new Error(`Failed to list conversations: ${response.status}`);
  }

  const data = await response.json();
  return {
    conversations: (data.conversations ?? []).map(normalizeConversationSummary),
    total: data.total ?? 0,
  };
}

/**
 * Get all messages for a conversation.
 */
export async function getConversationMessages(conversationId: string): Promise<CopilotMessage[]> {
  const response = await apiFetch(`/v1/copilot/conversations/${conversationId}/messages`);

  if (!response.ok) {
    throw new Error(`Failed to get messages: ${response.status}`);
  }

  const data = await response.json();
  return (data.messages ?? data ?? []).map(normalizeMessage);
}

/**
 * Delete a conversation and all its messages.
 */
export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await apiFetch(`/v1/copilot/conversations/${conversationId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`Failed to delete conversation: ${response.status}`);
  }
}

/**
 * List settings snapshots for the current user.
 */
export async function listSettingsSnapshots(): Promise<SettingsSnapshot[]> {
  const response = await apiFetch("/v1/copilot/settings/snapshots");

  if (!response.ok) {
    throw new Error(`Failed to list settings snapshots: ${response.status}`);
  }

  const data = await response.json();
  return (data.snapshots ?? data ?? []).map(normalizeSnapshot);
}

/**
 * Revert settings to a specific snapshot.
 */
export async function revertSettings(snapshotId: string): Promise<void> {
  const response = await apiFetch(`/v1/copilot/settings/revert/${snapshotId}`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Failed to revert settings: ${response.status}`);
  }
}

// --- Normalization helpers ---

function normalizeConversationSummary(raw: Record<string, unknown>): ConversationSummary {
  return {
    id: (raw.id as string) ?? "",
    title: (raw.title as string | null) ?? null,
    createdAt: (raw.created_at as number) ?? (raw.createdAt as number) ?? 0,
    updatedAt: (raw.updated_at as number) ?? (raw.updatedAt as number) ?? 0,
    messageCount: (raw.message_count as number) ?? (raw.messageCount as number) ?? 0,
  };
}

function normalizeMessage(raw: Record<string, unknown>): CopilotMessage {
  return {
    id: (raw.id as string) ?? "",
    role: (raw.role as CopilotMessage["role"]) ?? "assistant",
    content: (raw.content as string) ?? "",
    toolCalls: raw.tool_calls
      ? (raw.tool_calls as Record<string, unknown>[]).map(normalizeToolCall)
      : raw.toolCalls
        ? (raw.toolCalls as Record<string, unknown>[]).map(normalizeToolCall)
        : undefined,
    settingsMutation: raw.settings_mutation
      ? normalizeSettingsMutation(raw.settings_mutation as Record<string, unknown>)
      : raw.settingsMutation
        ? normalizeSettingsMutation(raw.settingsMutation as Record<string, unknown>)
        : undefined,
    timestamp: (raw.timestamp as number) ?? 0,
    isStreaming: (raw.is_streaming as boolean) ?? (raw.isStreaming as boolean) ?? false,
  };
}

function normalizeToolCall(raw: Record<string, unknown>): ToolCallInfo {
  return {
    id: (raw.id as string) ?? "",
    toolName: (raw.tool_name as string) ?? (raw.toolName as string) ?? "",
    parameters: (raw.parameters as Record<string, unknown>) ?? {},
    result: raw.result,
    durationMs: (raw.duration_ms as number) ?? (raw.durationMs as number) ?? undefined,
    success: (raw.success as boolean) ?? true,
  };
}

function normalizeSnapshot(raw: Record<string, unknown>): SettingsSnapshot {
  return {
    id: (raw.id as string) ?? "",
    version: (raw.version as number) ?? 0,
    settings: (raw.settings as Record<string, unknown>) ?? {},
    actor: (raw.actor as SettingsSnapshot["actor"]) ?? "user",
    conversationId: (raw.conversation_id as string) ?? (raw.conversationId as string) ?? undefined,
    createdAt: (raw.created_at as number) ?? (raw.createdAt as number) ?? 0,
  };
}
