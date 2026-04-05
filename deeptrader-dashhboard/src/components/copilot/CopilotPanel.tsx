/**
 * CopilotPanel — Slide-out chat panel for the trading copilot.
 *
 * Self-contained component: renders a fixed toggle button (bottom-right)
 * and a slide-out panel with message list, input, search, conversation
 * history, tool call cards, settings mutation cards, and error handling.
 */

import { useEffect, useRef, useState } from "react";
import { useCopilotStore } from "@/store/copilot-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
// ScrollArea from Radix doesn't expose the scrollable viewport ref easily,
// so we use a plain overflow container for reliable programmatic scrolling.
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  MessageSquare,
  Send,
  X,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertCircle,
  RefreshCw,
  Search,
  Plus,
  Wrench,
  Settings,
  Check,
  XCircle,
  TrendingUp,
  BarChart3,
  Activity,
  Zap,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { CopilotMessage, ToolCallInfo, SettingsMutationInfo } from "@/lib/api/copilot";
import { ChartWidget } from "./ChartWidget";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

export function ToolCallCard({ tool }: { tool: ToolCallInfo }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          className="flex w-full items-center gap-1.5 px-2 py-1.5 my-1.5 text-xs text-left bg-muted/30 hover:bg-muted/50 rounded-md border border-border transition-colors"
          data-testid="tool-call-trigger"
        >
          <Wrench className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="font-medium truncate">{tool.toolName}</span>
          <Badge
            variant={tool.success ? "success" : "warning"}
            className="text-[10px] px-1 py-0 leading-none"
          >
            {tool.success ? "ok" : "fail"}
          </Badge>
          {tool.durationMs != null && (
            <span className="text-muted-foreground ml-auto">
              {tool.durationMs.toFixed(0)}ms
            </span>
          )}
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="pl-4 pb-1 text-xs">
          <p className="text-muted-foreground mb-0.5">Parameters</p>
          <pre className="bg-muted rounded p-1 overflow-x-auto whitespace-pre-wrap text-[11px]">
            {JSON.stringify(tool.parameters, null, 2)}
          </pre>
          {tool.result !== undefined && (
            <>
              <p className="text-muted-foreground mt-1 mb-0.5">Result</p>
              <pre className="bg-muted rounded p-1 overflow-x-auto whitespace-pre-wrap text-[11px] max-h-40">
                {typeof tool.result === "string"
                  ? tool.result
                  : JSON.stringify(tool.result, null, 2)}
              </pre>
            </>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function SettingsMutationCard({
  mutation,
  onApprove,
  onReject,
}: {
  mutation: SettingsMutationInfo;
  onApprove: () => void;
  onReject: () => void;
}) {
  const isPending = mutation.status === "proposed";

  return (
    <Card className="my-2 border-amber-500/40" data-testid="settings-mutation-card">
      <CardHeader className="px-3 py-2">
        <CardTitle className="text-xs flex items-center gap-1">
          <Settings className="h-3 w-3" />
          Settings Change Proposal
        </CardTitle>
      </CardHeader>
      <CardContent className="px-3 pb-2 pt-0 text-xs space-y-2">
        <p className="text-muted-foreground">{mutation.rationale}</p>

        {Object.entries(mutation.changes).map(([key, { old: oldVal, new: newVal }]) => (
          <div key={key} className="bg-muted rounded p-2">
            <p className="font-medium">{key}</p>
            <div className="flex gap-2 mt-1">
              <span className="text-red-400 line-through">{String(oldVal)}</span>
              <span>→</span>
              <span className="text-green-400">{String(newVal)}</span>
            </div>
          </div>
        ))}

        {mutation.constraintViolations.length > 0 && (
          <div className="text-red-400 text-[11px]">
            {mutation.constraintViolations.map((v, i) => (
              <p key={i}>⚠ {v}</p>
            ))}
          </div>
        )}

        {isPending && (
          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="default"
              className="h-6 text-xs px-2"
              onClick={onApprove}
              data-testid="mutation-approve"
            >
              <Check className="h-3 w-3 mr-1" /> Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-6 text-xs px-2"
              onClick={onReject}
              data-testid="mutation-reject"
            >
              <XCircle className="h-3 w-3 mr-1" /> Reject
            </Button>
          </div>
        )}

        {!isPending && (
          <Badge variant={mutation.status === "applied" ? "success" : "warning"} className="text-[10px]">
            {mutation.status}
          </Badge>
        )}
      </CardContent>
    </Card>
  );
}


function MessageBubble({
  message,
  onApproveMutation,
  onRejectMutation,
}: {
  message: CopilotMessage;
  onApproveMutation: (mutationId: string) => void;
  onRejectMutation: (mutationId: string) => void;
}) {
  const isUser = message.role === "user";

  // For assistant messages with segments, render inline (text → tool → text → …)
  const segments = message.segments;
  const hasSegments = !isUser && segments && segments.length > 0;

  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}
      data-testid={`message-${message.role}`}
    >
      <div
        className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted/50 text-foreground"
        }`}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        ) : hasSegments ? (
          /* Render segments inline: text, tool calls, and mutations in order */
          <>
            {segments.map((seg, i) => {
              if (seg.type === "text" && seg.content) {
                return (
                  <div key={i} className="prose prose-sm max-w-none break-words text-inherit [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_*]:text-inherit [&_strong]:text-inherit [&_a]:text-primary [&_code]:text-inherit [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:text-left [&_ul]:text-left [&_ol]:text-left">
                    <ReactMarkdown>{seg.content}</ReactMarkdown>
                  </div>
                );
              }
              if (seg.type === "tool_call") {
                return <ToolCallCard key={seg.tool.id} tool={seg.tool} />;
              }
              if (seg.type === "settings_mutation") {
                return (
                  <SettingsMutationCard
                    key={i}
                    mutation={seg.mutation}
                    onApprove={() => onApproveMutation(seg.mutation.id)}
                    onReject={() => onRejectMutation(seg.mutation.id)}
                  />
                );
              }
              if (seg.type === "chart") {
                return <ChartWidget key={i} symbol={seg.symbol} timeframeSec={seg.timeframeSec} candles={seg.candles} />;
              }
              return null;
            })}
          </>
        ) : (
          /* Fallback for messages without segments (e.g. loaded from history) */
          <>
            {message.content && (
              <div className="prose prose-sm max-w-none break-words text-inherit [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_*]:text-inherit [&_strong]:text-inherit [&_a]:text-primary [&_code]:text-inherit [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:text-left [&_ul]:text-left [&_ol]:text-left">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>
            )}
            {message.toolCalls?.map((tc) => (
              <ToolCallCard key={tc.id} tool={tc} />
            ))}
            {message.settingsMutation && (
              <SettingsMutationCard
                mutation={message.settingsMutation}
                onApprove={() => onApproveMutation(message.settingsMutation!.id)}
                onReject={() => onRejectMutation(message.settingsMutation!.id)}
              />
            )}
          </>
        )}

        {/* Streaming indicator — show after tool calls too */}
        {message.isStreaming && (
          (() => {
            const hasContent = !!message.content || (segments && segments.length > 0);
            const lastSegment = segments?.[segments.length - 1];
            const lastIsToolCall = lastSegment?.type === "tool_call";
            // Show "Thinking…" when no content yet, or when last segment is a completed tool call
            // (meaning we're waiting for the LLM to respond with analysis)
            if (!hasContent || lastIsToolCall) {
              return (
                <div className="flex items-center gap-1 text-muted-foreground mt-1">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span className="text-xs">{hasContent ? "Analyzing…" : "Thinking…"}</span>
                </div>
              );
            }
            return null;
          })()
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Conversation history list
// ---------------------------------------------------------------------------

function ConversationHistoryList() {
  const { conversationHistory, loadConversation, searchQuery } = useCopilotStore();

  if (conversationHistory.length === 0) {
    return (
      <p className="text-xs text-muted-foreground px-3 py-2">
        {searchQuery ? "No conversations found." : "No conversation history."}
      </p>
    );
  }

  return (
    <div className="space-y-1 px-1" data-testid="conversation-history">
      {conversationHistory.map((c) => (
        <button
          key={c.id}
          className="w-full text-left rounded px-2 py-1.5 text-xs hover:bg-muted/60 transition-colors"
          onClick={() => loadConversation(c.id)}
          data-testid="conversation-item"
        >
          <p className="font-medium truncate">{c.title ?? "Untitled"}</p>
          <p className="text-muted-foreground text-[10px]">
            {new Date(c.updatedAt).toLocaleDateString()} · {c.messageCount} msgs
          </p>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Welcome screen example questions
// ---------------------------------------------------------------------------

const EXAMPLE_QUESTIONS = [
  { icon: TrendingUp, label: "How are my trades performing today?" },
  { icon: BarChart3, label: "Show me my recent P&L breakdown" },
  { icon: Activity, label: "What's the current market context?" },
  { icon: Zap, label: "Analyze my last trade" },
];

// ---------------------------------------------------------------------------
// Main CopilotPanel
// ---------------------------------------------------------------------------

export function CopilotPanel() {
  const {
    isOpen,
    toggle,
    messages,
    isLoading,
    error,
    clearError,
    sendMessage,
    newConversation,
    searchConversations,
    searchQuery,
  } = useCopilotStore();

  const [input, setInput] = useState("");
  const [searchInput, setSearchInput] = useState(searchQuery);
  const [showHistory, setShowHistory] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Show the welcome screen when there are no messages and not loading
  const showWelcome = messages.length === 0 && !isLoading;

  // Track whether the assistant is currently streaming
  const assistantIsStreaming = messages.some((m) => m.isStreaming);

  // Scroll to bottom whenever it makes sense:
  // - Right after user sends a message (their question appears at bottom, answer below)
  // - While assistant is streaming (keep new content visible)
  useEffect(() => {
    if (!scrollContainerRef.current) return;
    const container = scrollContainerRef.current;

    if (shouldAutoScrollRef.current) {
      // Always scroll to bottom when user just sent or streaming is active
      container.scrollTop = container.scrollHeight;
    } else if (assistantIsStreaming) {
      // During streaming, auto-scroll if user is near the bottom
      const isNearBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 150;
      if (isNearBottom) {
        container.scrollTop = container.scrollHeight;
      }
    }

    // Reset the flag once streaming ends
    if (!assistantIsStreaming) {
      shouldAutoScrollRef.current = false;
    }
  });

  const handleSend = (text?: string) => {
    const trimmed = (text ?? input).trim();
    if (!trimmed || isLoading) return;
    setInput("");
    shouldAutoScrollRef.current = true;
    sendMessage(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSearch = () => {
    searchConversations(searchInput);
    setShowHistory(true);
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSearch();
    }
  };

  const handleApproveMutation = (mutationId: string) => {
    // TODO: call API to apply mutation
    console.log("Approve mutation:", mutationId);
  };

  const handleRejectMutation = (mutationId: string) => {
    // TODO: call API to reject mutation
    console.log("Reject mutation:", mutationId);
  };

  const handleRetry = () => {
    clearError();
    if (messages.length > 0) {
      const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
      if (lastUserMsg) {
        sendMessage(lastUserMsg.content);
      }
    }
  };

  return (
    <>
      {/* Toggle button */}
      {!isOpen && (
        <Button
          size="icon"
          className="fixed bottom-4 right-4 z-50 h-12 w-12 rounded-full shadow-lg"
          onClick={toggle}
          data-testid="copilot-toggle"
        >
          <MessageSquare className="h-5 w-5" />
        </Button>
      )}

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 z-50 h-full w-[520px] max-w-full bg-background border-l shadow-xl flex flex-col transition-transform duration-200 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        data-testid="copilot-panel"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4" />
            <span className="font-semibold text-sm">Copilot</span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={newConversation}
              title="New conversation"
              data-testid="new-conversation"
            >
              <Plus className="h-4 w-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={toggle}
              data-testid="copilot-close"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Search bar */}
        <div className="flex items-center gap-1 px-3 py-2 border-b shrink-0">
          <Input
            placeholder="Search conversations…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            className="h-7 text-xs"
            data-testid="conversation-search"
          />
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 shrink-0"
            onClick={handleSearch}
            data-testid="search-button"
          >
            <Search className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Conversation history (shown when searching) */}
        {showHistory && (
          <div className="border-b max-h-48 overflow-y-auto shrink-0">
            <div className="flex items-center justify-between px-3 py-1">
              <span className="text-xs font-medium text-muted-foreground">History</span>
              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5"
                onClick={() => setShowHistory(false)}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
            <Separator />
            <ConversationHistoryList />
          </div>
        )}

        {showWelcome ? (
          /* ---- Welcome screen: centered input + example questions ---- */
          <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-6" data-testid="welcome-screen">
            <MessageSquare className="h-10 w-10 text-muted-foreground/40 mb-3" />
            <p className="text-sm font-medium mb-1">Trading Copilot</p>
            <p className="text-xs text-muted-foreground mb-6 text-center">
              Ask about your trades, performance, market context, or settings.
            </p>

            {/* Centered input */}
            <div className="flex items-center gap-2 w-full max-w-sm mb-5">
              <Input
                ref={inputRef}
                placeholder="Ask anything…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                className="text-sm"
                data-testid="welcome-input"
              />
              <Button
                size="icon"
                className="h-9 w-9 shrink-0"
                onClick={() => handleSend()}
                disabled={!input.trim()}
                data-testid="welcome-send"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>

            {/* Example question buttons */}
            <div className="grid grid-cols-2 gap-2 w-full max-w-sm" data-testid="example-questions">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q.label}
                  className="flex items-start gap-2 rounded-lg border border-border px-3 py-2.5 text-left text-xs hover:bg-muted/50 transition-colors"
                  onClick={() => handleSend(q.label)}
                  data-testid="example-question"
                >
                  <q.icon className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
                  <span>{q.label}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* ---- Normal chat view ---- */
          <>
            {/* Message list */}
            <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2" ref={scrollContainerRef} data-testid="message-list">
              {messages.map((msg) => (
                <div key={msg.id}>
                  <MessageBubble
                    message={msg}
                    onApproveMutation={handleApproveMutation}
                    onRejectMutation={handleRejectMutation}
                  />
                </div>
              ))}

              {/* Loading indicator */}
              {isLoading && messages[messages.length - 1]?.role !== "assistant" && (
                <div className="flex items-center gap-2 text-muted-foreground text-xs py-2" data-testid="loading-indicator">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Processing…
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Error banner */}
            {error && (
              <div
                className="flex items-center gap-2 px-3 py-2 bg-destructive/10 text-destructive text-xs border-t shrink-0"
                data-testid="error-banner"
              >
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                <span className="flex-1 truncate">{error}</span>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 shrink-0"
                  onClick={handleRetry}
                  data-testid="retry-button"
                >
                  <RefreshCw className="h-3 w-3" />
                </Button>
              </div>
            )}

            {/* Input area */}
            <div className="flex items-center gap-2 px-3 py-2 border-t shrink-0">
              <Input
                placeholder="Type a message…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                className="text-sm"
                data-testid="message-input"
              />
              <Button
                size="icon"
                className="h-9 w-9 shrink-0"
                onClick={() => handleSend()}
                disabled={!input.trim() || isLoading}
                data-testid="send-button"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
