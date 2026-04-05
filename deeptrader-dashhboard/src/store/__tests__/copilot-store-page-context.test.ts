/**
 * Property-based tests for page context tracking.
 *
 * Property 7: Page context included in copilot messages
 * Property 9: Bot sub-page context extraction
 *
 * Validates: Requirements 4.1, 4.2, 4.4
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";
import { useCopilotStore } from "../copilot-store";
import { parseBotSubPageUrl } from "../../lib/url-utils";

// Mock the API client
vi.mock("../../lib/api/copilot", () => ({
  sendCopilotMessage: vi.fn(),
  listConversations: vi.fn(),
  getConversationMessages: vi.fn(),
}));

import { sendCopilotMessage } from "../../lib/api/copilot";

const mockSendCopilotMessage = vi.mocked(sendCopilotMessage);

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

/** Arbitrary for dashboard page paths (e.g. "/live", "/risk/limits", "/settings"). */
const dashboardPathArb = fc.oneof(
  // Top-level pages
  fc.constantFrom(
    "/", "/live", "/orders", "/positions", "/history",
    "/risk/limits", "/risk/exposure", "/risk/metrics", "/risk/incidents",
    "/pipeline-health", "/analysis/replay", "/market-context",
    "/signals", "/execution", "/backtesting", "/data-quality",
    "/exchange-accounts", "/bot-management", "/profiles",
    "/settings", "/audit",
  ),
  // Dynamic paths with a slug segment
  fc.stringMatching(/^[a-z][a-z0-9-]{0,19}$/).map((seg) => `/${seg}`),
);

/** Arbitrary for bot IDs — alphanumeric with hyphens, 1-36 chars. */
const botIdArb = fc.stringMatching(/^[a-zA-Z0-9][a-zA-Z0-9-]{0,35}$/);

/** Arbitrary for bot sub-page names. */
const botSubPageArb = fc.constantFrom("decisions", "history", "operate", "positions");

describe("Property 7: Page context included in copilot messages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  /**
   * **Validates: Requirements 4.1, 4.2**
   *
   * For any dashboard page path, setCurrentPagePath updates the store state
   * to that path.
   */
  it("setCurrentPagePath stores the current page path for any valid path", () => {
    fc.assert(
      fc.property(dashboardPathArb, (path) => {
        resetStore();
        useCopilotStore.getState().setCurrentPagePath(path);
        expect(useCopilotStore.getState().currentPagePath).toBe(path);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.1, 4.2**
   *
   * For any dashboard page path, when sendMessage is called, the API receives
   * the currentPagePath as the 5th argument (pagePath).
   */
  it("sendMessage passes currentPagePath to the API for any page path", async () => {
    await fc.assert(
      fc.asyncProperty(dashboardPathArb, async (path) => {
        resetStore();
        mockSendCopilotMessage.mockImplementation(
          async (_msg, _convId, _ctx, onDelta) => {
            onDelta({ type: "done" });
          },
        );

        useCopilotStore.getState().setCurrentPagePath(path);
        await useCopilotStore.getState().sendMessage("hello");

        expect(mockSendCopilotMessage).toHaveBeenCalledWith(
          "hello",
          null,
          null,
          expect.any(Function),
          path,
        );
      }),
      { numRuns: 100 },
    );
  });
});

describe("Property 9: Bot sub-page context extraction", () => {
  /**
   * **Validates: Requirements 4.4**
   *
   * For any bot sub-page URL of the form /bot/{bot_id}/{sub_page},
   * parseBotSubPageUrl extracts both the bot identifier and the sub-page path.
   */
  it("extracts bot ID and sub-page from any /bot/{id}/{sub_page} URL", () => {
    fc.assert(
      fc.property(botIdArb, botSubPageArb, (botId, subPage) => {
        const url = `/bot/${botId}/${subPage}`;
        const result = parseBotSubPageUrl(url);

        expect(result).not.toBeNull();
        expect(result!.botId).toBe(botId);
        expect(result!.subPage).toBe(subPage);
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.4**
   *
   * For any non-bot URL (paths that don't match /bot/{id}/{sub_page}),
   * parseBotSubPageUrl returns null.
   */
  it("returns null for non-bot URLs", () => {
    fc.assert(
      fc.property(dashboardPathArb, (path) => {
        // dashboardPathArb never generates /bot/x/y patterns
        const result = parseBotSubPageUrl(path);
        // Only /bot/{id}/{sub} should match — standard dashboard paths should not
        if (!path.match(/^\/bot\/[^/]+\/[^/]+$/)) {
          expect(result).toBeNull();
        }
      }),
      { numRuns: 100 },
    );
  });

  /**
   * **Validates: Requirements 4.4**
   *
   * Round-trip: constructing a URL from bot ID + sub-page and parsing it
   * yields the original components.
   */
  it("round-trips bot ID and sub-page through URL construction and parsing", () => {
    fc.assert(
      fc.property(botIdArb, botSubPageArb, (botId, subPage) => {
        const url = `/bot/${botId}/${subPage}`;
        const parsed = parseBotSubPageUrl(url);

        expect(parsed).not.toBeNull();
        // Reconstruct and verify
        const reconstructed = `/bot/${parsed!.botId}/${parsed!.subPage}`;
        expect(reconstructed).toBe(url);
      }),
      { numRuns: 100 },
    );
  });
});
