/**
 * Component tests for the Backtesting page
 * 
 * Tests verify:
 * - Loading state is displayed when data is being fetched
 * - Error state with retry button is displayed when API fails
 * - Empty state message is displayed when no data is returned
 * 
 * Validates: Requirements 4.5, 4.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { TooltipProvider } from "../../../components/ui/tooltip";

// Mock the DashBar component to avoid its complex dependencies
vi.mock("../../../components/DashBar", () => ({
  DashBar: () => <div data-testid="mock-dashbar">DashBar</div>,
}));

// Mock the API hooks with partial mock to preserve other exports
vi.mock("../../../lib/api/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/hooks")>();
  return {
    ...actual,
    useBacktests: vi.fn(),
    useBacktestDetail: vi.fn(),
    useDatasets: vi.fn(),
    useCreateBacktest: vi.fn(),
    useRerunBacktest: vi.fn(),
    useDeleteBacktest: vi.fn(),
    useWfoRuns: vi.fn(),
    useCreateWfoRun: vi.fn(),
    useWfoRun: vi.fn(),
    useResearchStrategies: vi.fn(),
    useBacktestPreflight: vi.fn(),
  };
});

// Mock the fetchWarmStartState function
vi.mock("../../../lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api/client")>();
  return {
    ...actual,
    fetchWarmStartState: vi.fn(),
  };
});

// Import mocked modules
import {
  useBacktests,
  useBacktestDetail,
  useDatasets,
  useCreateBacktest,
  useRerunBacktest,
  useDeleteBacktest,
  useWfoRuns,
  useCreateWfoRun,
  useWfoRun,
  useResearchStrategies,
  useBacktestPreflight,
} from "../../../lib/api/hooks";
import { fetchWarmStartState } from "../../../lib/api/client";

// Import the component under test
import BacktestingPage from "../backtesting";

// Helper to create a fresh QueryClient for each test
const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });

// Wrapper component with all required providers
const TestWrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = createTestQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <TooltipProvider>{children}</TooltipProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe("Backtesting Page", () => {
  beforeEach(() => {
    // Reset all mocks before each test
    vi.clearAllMocks();

    // Default mock implementations for hooks that aren't the focus of each test
    (useBacktestDetail as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    (useDatasets as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { datasets: [] },
      isLoading: false,
      error: null,
    });

    (useCreateBacktest as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    (useRerunBacktest as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    (useDeleteBacktest as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    (useWfoRuns as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { runs: [] },
      isLoading: false,
      error: null,
    });

    (useCreateWfoRun as ReturnType<typeof vi.fn>).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });

    (useWfoRun as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    });

    (useResearchStrategies as ReturnType<typeof vi.fn>).mockReturnValue({
      data: { strategies: [] },
      isLoading: false,
      error: null,
    });

    (useBacktestPreflight as ReturnType<typeof vi.fn>).mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    // Mock fetchWarmStartState to return null by default (no live state)
    (fetchWarmStartState as ReturnType<typeof vi.fn>).mockResolvedValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Loading State", () => {
    /**
     * Test: Loading state is displayed when data is being fetched
     * Validates: Requirements 4.5, 4.6 (proper state handling)
     */
    it("displays loading state when fetching backtest runs", async () => {
      // Mock useBacktests to return loading state
      (useBacktests as ReturnType<typeof vi.fn>).mockReturnValue({
        data: undefined,
        isLoading: true,
        error: null,
        refetch: vi.fn(),
      });

      render(
        <TestWrapper>
          <BacktestingPage />
        </TestWrapper>
      );

      // Verify loading indicator is displayed
      expect(screen.getByText(/loading backtest runs/i)).toBeInTheDocument();
    });
  });

  describe("Error State", () => {
    /**
     * Test: Error state with retry button is displayed when API fails
     * Validates: Requirement 4.6 - WHEN the API request fails THEN the System SHALL display an error message with retry option
     */
    it("displays error state with retry button when API fails", async () => {
      const mockRefetch = vi.fn();
      const testError = new Error("Network error: Failed to fetch backtests");

      // Mock useBacktests to return error state
      (useBacktests as ReturnType<typeof vi.fn>).mockReturnValue({
        data: undefined,
        isLoading: false,
        error: testError,
        refetch: mockRefetch,
      });

      render(
        <TestWrapper>
          <BacktestingPage />
        </TestWrapper>
      );

      // Verify error message is displayed
      expect(screen.getByText(/failed to load backtest runs/i)).toBeInTheDocument();
      expect(screen.getByText(/network error: failed to fetch backtests/i)).toBeInTheDocument();

      // Verify retry button is present
      const retryButton = screen.getByRole("button", { name: /retry/i });
      expect(retryButton).toBeInTheDocument();

      // Click retry button and verify refetch is called
      fireEvent.click(retryButton);
      expect(mockRefetch).toHaveBeenCalledTimes(1);
    });

    it("displays generic error message when error has no message", async () => {
      const mockRefetch = vi.fn();

      // Mock useBacktests to return error state with non-Error object
      (useBacktests as ReturnType<typeof vi.fn>).mockReturnValue({
        data: undefined,
        isLoading: false,
        error: { code: "UNKNOWN" }, // Non-Error object
        refetch: mockRefetch,
      });

      render(
        <TestWrapper>
          <BacktestingPage />
        </TestWrapper>
      );

      // Verify generic error message is displayed
      expect(screen.getByText(/failed to load backtest runs/i)).toBeInTheDocument();
      expect(screen.getByText(/an unexpected error occurred/i)).toBeInTheDocument();
    });
  });

  describe("Empty State", () => {
    /**
     * Test: Empty state message is displayed when no data is returned
     * Validates: Requirement 4.5 - WHEN the API returns no data THEN the System SHALL display an appropriate empty state message
     */
    it("displays empty state message when no backtest runs exist", async () => {
      // Mock useBacktests to return empty data
      (useBacktests as ReturnType<typeof vi.fn>).mockReturnValue({
        data: { backtests: [] },
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      });

      render(
        <TestWrapper>
          <BacktestingPage />
        </TestWrapper>
      );

      // Verify empty state message is displayed
      expect(screen.getByText(/no backtest runs found/i)).toBeInTheDocument();
      expect(screen.getByText(/create your first backtest to get started/i)).toBeInTheDocument();
    });

    it("displays empty state when API returns null backtests", async () => {
      // Mock useBacktests to return null backtests
      (useBacktests as ReturnType<typeof vi.fn>).mockReturnValue({
        data: { backtests: null },
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      });

      render(
        <TestWrapper>
          <BacktestingPage />
        </TestWrapper>
      );

      // Verify empty state message is displayed
      expect(screen.getByText(/no backtest runs found/i)).toBeInTheDocument();
    });
  });

  describe("Data Display", () => {
    /**
     * Test: Backtest runs are displayed when data is available
     * Validates: Requirements 4.1, 4.2 - Real data from API is displayed
     */
    it("displays backtest runs when data is available", async () => {
      const mockBacktests = {
        backtests: [
          {
            id: "bt-001",
            name: "Test Backtest 1",
            strategy_id: "momentum-v1",
            symbol: "BTCUSDT",
            exchange: "okx",
            timeframe: "5m",
            start_date: "2024-01-01T00:00:00Z",
            end_date: "2024-01-31T23:59:59Z",
            status: "completed",
            created_at: "2024-01-15T10:00:00Z",
            completed_at: "2024-01-15T10:30:00Z",
            initial_capital: 10000,
            results: {
              return_pct: 15.5,
              max_drawdown_pct: -5.2,
              sharpe_ratio: 1.8,
              profit_factor: 2.1,
              win_rate: 65,
              total_trades: 42,
              realized_pnl: 1550,
            },
            slippage_bps: 5,
            tags: ["test"],
          },
          {
            id: "bt-002",
            name: "Test Backtest 2",
            strategy_id: "mean-reversion",
            symbol: "ETHUSDT",
            exchange: "okx",
            timeframe: "15m",
            start_date: "2024-02-01T00:00:00Z",
            end_date: "2024-02-28T23:59:59Z",
            status: "running",
            created_at: "2024-02-15T10:00:00Z",
            initial_capital: 5000,
            results: null,
            slippage_bps: 3,
            tags: [],
          },
        ],
      };

      // Mock useBacktests to return data
      (useBacktests as ReturnType<typeof vi.fn>).mockReturnValue({
        data: mockBacktests,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      });

      render(
        <TestWrapper>
          <BacktestingPage />
        </TestWrapper>
      );

      // Verify backtest runs are displayed
      expect(screen.getByText("Test Backtest 1")).toBeInTheDocument();
      expect(screen.getByText("Test Backtest 2")).toBeInTheDocument();
      // Use getAllByText since symbols appear in both table and filter dropdown
      expect(screen.getAllByText("BTCUSDT").length).toBeGreaterThan(0);
      expect(screen.getAllByText("ETHUSDT").length).toBeGreaterThan(0);
    });
  });
});
