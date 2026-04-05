// Feature: copilot-tools-and-compact-ui, Property 7: Expanded ToolCallCard contains all ToolCallInfo fields

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import fc from "fast-check";
import { ToolCallCard } from "../CopilotPanel";
import type { ToolCallInfo } from "@/lib/api/copilot";

/**
 * Arbitrary for ToolCallInfo objects with all fields populated.
 *
 * - toolName: non-empty alphanumeric string (avoids regex-special chars in assertions)
 * - parameters: a JSON-serializable dictionary
 * - result: either a plain string or a JSON-serializable object
 * - durationMs: positive integer
 * - success: boolean
 * - id: non-empty string
 */
const arbToolCallInfo: fc.Arbitrary<ToolCallInfo> = fc.record({
  id: fc.string({ minLength: 1, maxLength: 20 }),
  toolName: fc.stringMatching(/^[a-z][a-z0-9_]{0,29}$/),
  parameters: fc.dictionary(
    fc.stringMatching(/^[a-zA-Z_][a-zA-Z0-9_]{0,9}$/),
    fc.oneof(
      fc.string({ maxLength: 30 }),
      fc.integer(),
      fc.boolean(),
      fc.double({ min: -1e6, max: 1e6, noNaN: true }),
    ),
    { minKeys: 1, maxKeys: 5 },
  ),
  result: fc.oneof(
    fc.string({ minLength: 1, maxLength: 50 }),
    fc.dictionary(
      fc.stringMatching(/^[a-zA-Z_][a-zA-Z0-9_]{0,9}$/),
      fc.oneof(fc.string({ maxLength: 20 }), fc.integer(), fc.boolean()),
      { minKeys: 1, maxKeys: 4 },
    ),
  ),
  durationMs: fc.integer({ min: 1, max: 99999 }),
  success: fc.boolean(),
});

describe("Property 7: Expanded ToolCallCard contains all ToolCallInfo fields", () => {
  // **Validates: Requirements 5.5**
  it("expanded card contains toolName, status badge, duration, parameters JSON, and result", () => {
    fc.assert(
      fc.property(arbToolCallInfo, (tool) => {
        const { container, unmount } = render(<ToolCallCard tool={tool} />);

        // --- Collapsed state: toolName, badge, duration visible ---
        expect(screen.getByText(tool.toolName)).toBeInTheDocument();
        expect(
          screen.getByText(tool.success ? "ok" : "fail"),
        ).toBeInTheDocument();
        expect(
          screen.getByText(`${tool.durationMs!.toFixed(0)}ms`, {
            exact: false,
          }),
        ).toBeInTheDocument();

        // --- Expand the card ---
        fireEvent.click(screen.getByTestId("tool-call-trigger"));

        // --- Parameters JSON present ---
        const preElements = container.querySelectorAll("pre");
        const paramsText = preElements[0]?.textContent ?? "";
        expect(paramsText).toBe(JSON.stringify(tool.parameters, null, 2));

        // --- Result present ---
        const resultText = preElements[1]?.textContent ?? "";
        if (typeof tool.result === "string") {
          expect(resultText).toBe(tool.result);
        } else {
          expect(resultText).toBe(JSON.stringify(tool.result, null, 2));
        }

        // --- Success status badge ---
        const expectedBadge = tool.success ? "ok" : "fail";
        expect(screen.getByText(expectedBadge)).toBeInTheDocument();

        unmount();
      }),
      { numRuns: 100 },
    );
  });
});
