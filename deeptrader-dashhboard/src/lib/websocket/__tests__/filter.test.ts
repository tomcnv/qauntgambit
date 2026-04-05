import { describe, it, expect } from "vitest";
import { shouldProcessMessage } from "../filter";

const scope = {
  level: "bot",
  exchangeAccountId: "ex-1",
  exchangeAccountName: "okx",
  botId: "bot-1",
  botName: "Test Bot",
  environment: "all",
  timeWindow: "1h",
  setFleetScope: () => {},
  setExchangeScope: () => {},
  setBotScope: () => {},
  setEnvironment: () => {},
  setTimeWindow: () => {},
  getScopeLabel: () => "Bot",
  getScopeParams: () => ({}),
};

describe("shouldProcessMessage", () => {
  it("passes when meta matches scope", () => {
    const ok = shouldProcessMessage({ tenantId: "tenant-1", botId: "bot-1", exchange: "okx" }, scope as any, "tenant-1");
    expect(ok).toBe(true);
  });

  it("filters when botId mismatches", () => {
    const ok = shouldProcessMessage({ botId: "other" }, scope as any, "tenant-1");
    expect(ok).toBe(false);
  });

  it("filters when tenant mismatches", () => {
    const ok = shouldProcessMessage({ tenantId: "other" }, scope as any, "tenant-1");
    expect(ok).toBe(false);
  });

  it("filters when exchange mismatches", () => {
    const ok = shouldProcessMessage({ exchange: "binance" }, scope as any, "tenant-1");
    expect(ok).toBe(false);
  });
});
