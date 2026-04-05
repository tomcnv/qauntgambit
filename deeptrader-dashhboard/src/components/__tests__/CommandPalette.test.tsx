import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CommandPalette } from "../CommandPalette";

// Track navigations
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

// Helper to render with router context
function renderPalette() {
  return render(
    <MemoryRouter>
      <CommandPalette />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockNavigate.mockClear();
  // Default: fetch returns empty results
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ results: [] }),
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("CommandPalette", () => {
  // ---------------------------------------------------------------
  // Requirement 3.1 — ⌘K / Ctrl+K opens the command palette
  // ---------------------------------------------------------------

  it("opens dialog on ⌘K (macOS)", () => {
    renderPalette();
    expect(screen.queryByTestId("command-palette-search")).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "k", metaKey: true });

    expect(screen.getByTestId("command-palette-search")).toBeInTheDocument();
    expect(screen.getByTestId("command-palette-input")).toBeInTheDocument();
  });

  it("opens dialog on Ctrl+K (Windows/Linux)", () => {
    renderPalette();
    expect(screen.queryByTestId("command-palette-search")).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });

    expect(screen.getByTestId("command-palette-search")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------
  // Requirement 3.1 — Documentation category in search results
  // ---------------------------------------------------------------

  it("shows Documentation category when API returns doc results", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        results: [
          { path: "/live", title: "Live Trading", section: "Widgets", snippet: "Kill switch panel", score: 1.0 },
        ],
      }),
    });

    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "kill switch" } });

    // Advance past debounce
    await vi.advanceTimersByTimeAsync(250);

    await waitFor(() => {
      expect(screen.getByTestId("documentation-category")).toBeInTheDocument();
      expect(screen.getByText("Live Trading")).toBeInTheDocument();
    });
  });

  it("shows Pages category with filtered results when typing", () => {
    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "backtest" } });

    expect(screen.getByTestId("pages-category")).toBeInTheDocument();
    expect(screen.getByText("Backtesting")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------
  // Requirement 3.3 — Navigation on selection
  // ---------------------------------------------------------------

  it("navigates to selected page on click", () => {
    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    fireEvent.click(screen.getByTestId("page-result-/live"));

    expect(mockNavigate).toHaveBeenCalledWith("/live");
  });

  it("navigates to selected doc result on click", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        results: [
          { path: "/orders", title: "Orders & Fills", section: "Widgets", snippet: "Fill rate KPI", score: 0.9 },
        ],
      }),
    });

    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "fill rate" } });

    await vi.advanceTimersByTimeAsync(250);

    await waitFor(() => {
      expect(screen.getByTestId("doc-result-/orders")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("doc-result-/orders"));
    expect(mockNavigate).toHaveBeenCalledWith("/docs?page=%2Forders");
  });

  it("closes dialog after selection", () => {
    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(screen.getByTestId("command-palette-search")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("page-result-/live"));

    expect(screen.queryByTestId("command-palette-search")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------
  // Escape key closes the dialog
  // ---------------------------------------------------------------

  it("closes dialog on Escape key", () => {
    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(screen.getByTestId("command-palette-search")).toBeInTheDocument();

    const input = screen.getByTestId("command-palette-input");
    fireEvent.keyDown(input, { key: "Escape" });

    expect(screen.queryByTestId("command-palette-search")).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------
  // Edge cases
  // ---------------------------------------------------------------

  it("shows no-results message when query matches nothing", async () => {
    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "xyznonexistent" } });

    await vi.advanceTimersByTimeAsync(250);

    await waitFor(() => {
      expect(screen.getByTestId("no-results")).toBeInTheDocument();
    });
  });

  it("resets query when dialog is reopened", () => {
    renderPalette();

    // Open and type
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "live" } });

    // Close
    fireEvent.keyDown(input, { key: "Escape" });

    // Reopen
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    const newInput = screen.getByTestId("command-palette-input");
    expect(newInput).toHaveValue("");
  });

  it("gracefully handles fetch failure for doc search", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network error"));

    renderPalette();
    fireEvent.keyDown(document, { key: "k", metaKey: true });

    const input = screen.getByTestId("command-palette-input");
    fireEvent.change(input, { target: { value: "kill" } });

    await vi.advanceTimersByTimeAsync(250);

    // Should not crash — pages still show
    await waitFor(() => {
      expect(screen.queryByTestId("documentation-category")).not.toBeInTheDocument();
    });
  });
});
