import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CopilotPanel } from "../CopilotPanel";
import { useCopilotStore } from "@/store/copilot-store";

// Mock lightweight-charts to avoid canvas issues in jsdom
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

// Reset store between tests
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

describe("CopilotPanel", () => {
  it("renders toggle button when panel is closed", () => {
    render(<CopilotPanel />);
    expect(screen.getByTestId("copilot-toggle")).toBeInTheDocument();
  });

  it("opens panel when toggle button is clicked", () => {
    render(<CopilotPanel />);
    fireEvent.click(screen.getByTestId("copilot-toggle"));
    expect(screen.getByTestId("copilot-panel")).toHaveClass("translate-x-0");
  });

  it("renders welcome screen with input and example questions when no messages", () => {
    useCopilotStore.setState({ isOpen: true });
    render(<CopilotPanel />);
    expect(screen.getByTestId("welcome-screen")).toBeInTheDocument();
    expect(screen.getByTestId("welcome-input")).toBeInTheDocument();
    expect(screen.getByTestId("example-questions")).toBeInTheDocument();
    expect(screen.getAllByTestId("example-question")).toHaveLength(4);
  });

  it("renders search bar when open", () => {
    useCopilotStore.setState({ isOpen: true });
    render(<CopilotPanel />);
    expect(screen.getByTestId("conversation-search")).toBeInTheDocument();
  });

  it("renders welcome screen description when no messages", () => {
    useCopilotStore.setState({ isOpen: true });
    render(<CopilotPanel />);
    expect(screen.getByText(/Ask about your trades/)).toBeInTheDocument();
  });

  it("renders user and assistant messages", () => {
    useCopilotStore.setState({
      isOpen: true,
      messages: [
        { id: "1", role: "user", content: "Hello", timestamp: Date.now() },
        { id: "2", role: "assistant", content: "Hi there!", timestamp: Date.now() },
      ],
    });
    render(<CopilotPanel />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there!")).toBeInTheDocument();
  });

  it("sends message on Enter key from welcome input", () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined);
    useCopilotStore.setState({ isOpen: true, sendMessage });
    render(<CopilotPanel />);

    const input = screen.getByTestId("welcome-input");
    fireEvent.change(input, { target: { value: "test message" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(sendMessage).toHaveBeenCalledWith("test message");
  });

  it("sends example question on click", () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined);
    useCopilotStore.setState({ isOpen: true, sendMessage });
    render(<CopilotPanel />);

    const buttons = screen.getAllByTestId("example-question");
    fireEvent.click(buttons[0]);

    expect(sendMessage).toHaveBeenCalledWith("How are my trades performing today?");
  });

  it("sends message on send button click in chat view", () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined);
    useCopilotStore.setState({
      isOpen: true,
      sendMessage,
      messages: [{ id: "1", role: "user", content: "hi", timestamp: Date.now() }],
    });
    render(<CopilotPanel />);

    const input = screen.getByTestId("message-input");
    fireEvent.change(input, { target: { value: "test message" } });
    fireEvent.click(screen.getByTestId("send-button"));

    expect(sendMessage).toHaveBeenCalledWith("test message");
  });

  it("disables welcome send button when input is empty", () => {
    useCopilotStore.setState({ isOpen: true });
    render(<CopilotPanel />);
    expect(screen.getByTestId("welcome-send")).toBeDisabled();
  });

  it("disables input when loading in chat view", () => {
    useCopilotStore.setState({
      isOpen: true,
      isLoading: true,
      messages: [{ id: "1", role: "user", content: "hi", timestamp: Date.now() }],
    });
    render(<CopilotPanel />);
    expect(screen.getByTestId("message-input")).toBeDisabled();
  });

  it("renders error banner with retry button", () => {
    useCopilotStore.setState({
      isOpen: true,
      error: "Something went wrong",
      messages: [{ id: "1", role: "user", content: "hi", timestamp: Date.now() }],
    });
    render(<CopilotPanel />);
    expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByTestId("retry-button")).toBeInTheDocument();
  });

  it("renders tool call cards in assistant messages", () => {
    useCopilotStore.setState({
      isOpen: true,
      messages: [
        {
          id: "1",
          role: "assistant",
          content: "Here are your trades:",
          timestamp: Date.now(),
          toolCalls: [
            {
              id: "tc1",
              toolName: "query_trades",
              parameters: { symbol: "BTCUSDT" },
              result: [{ pnl: 100 }],
              durationMs: 42,
              success: true,
            },
          ],
        },
      ],
    });
    render(<CopilotPanel />);
    expect(screen.getByText("query_trades")).toBeInTheDocument();
    expect(screen.getByText("42ms")).toBeInTheDocument();
  });

  it("renders settings mutation card with approve/reject buttons", () => {
    useCopilotStore.setState({
      isOpen: true,
      messages: [
        {
          id: "1",
          role: "assistant",
          content: "I suggest changing your risk settings:",
          timestamp: Date.now(),
          settingsMutation: {
            id: "mut1",
            changes: { "risk.maxExposure": { old: 0.5, new: 0.3 } },
            rationale: "Reduce risk during volatile market",
            status: "proposed",
            constraintViolations: [],
          },
        },
      ],
    });
    render(<CopilotPanel />);
    expect(screen.getByTestId("settings-mutation-card")).toBeInTheDocument();
    expect(screen.getByText("Reduce risk during volatile market")).toBeInTheDocument();
    expect(screen.getByTestId("mutation-approve")).toBeInTheDocument();
    expect(screen.getByTestId("mutation-reject")).toBeInTheDocument();
  });

  it("closes panel when close button is clicked", () => {
    useCopilotStore.setState({ isOpen: true });
    render(<CopilotPanel />);
    fireEvent.click(screen.getByTestId("copilot-close"));
    expect(screen.getByTestId("copilot-panel")).toHaveClass("translate-x-full");
  });

  it("starts new conversation when new button is clicked", () => {
    const newConversation = vi.fn();
    useCopilotStore.setState({ isOpen: true, newConversation });
    render(<CopilotPanel />);
    fireEvent.click(screen.getByTestId("new-conversation"));
    expect(newConversation).toHaveBeenCalled();
  });

  it("shows conversation history when search is triggered", () => {
    const searchConversations = vi.fn().mockResolvedValue(undefined);
    useCopilotStore.setState({
      isOpen: true,
      searchConversations,
      conversationHistory: [
        { id: "c1", title: "Past chat", createdAt: Date.now(), updatedAt: Date.now(), messageCount: 5 },
      ],
    });
    render(<CopilotPanel />);

    const searchInput = screen.getByTestId("conversation-search");
    fireEvent.change(searchInput, { target: { value: "trades" } });
    fireEvent.click(screen.getByTestId("search-button"));

    expect(searchConversations).toHaveBeenCalledWith("trades");
  });

  it("renders ChartWidget for chart segments in assistant messages", () => {
    useCopilotStore.setState({
      isOpen: true,
      messages: [
        {
          id: "1",
          role: "assistant",
          content: "",
          timestamp: Date.now(),
          segments: [
            { type: "text" as const, content: "Here is the chart:" },
            {
              type: "chart" as const,
              symbol: "BTCUSDT",
              timeframeSec: 60,
              candles: [
                { time: 1700000000, open: 42000, high: 42100, low: 41900, close: 42050, volume: 10 },
                { time: 1700000060, open: 42050, high: 42200, low: 42000, close: 42150, volume: 15 },
              ],
            },
          ],
        },
      ],
    });
    render(<CopilotPanel />);
    expect(screen.getByTestId("chart-container")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT · 1m")).toBeInTheDocument();
  });

  it("renders 'No data available' for chart segment with empty candles", () => {
    useCopilotStore.setState({
      isOpen: true,
      messages: [
        {
          id: "1",
          role: "assistant",
          content: "",
          timestamp: Date.now(),
          segments: [
            {
              type: "chart" as const,
              symbol: "ETHUSDT",
              timeframeSec: 60,
              candles: [],
            },
          ],
        },
      ],
    });
    render(<CopilotPanel />);
    expect(screen.getByTestId("chart-no-data")).toBeInTheDocument();
    expect(screen.getByText("No data available")).toBeInTheDocument();
  });
});
