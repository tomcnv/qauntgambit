import { describe, it, expect } from "vitest";
import { buildScopedParams } from "../params";

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

describe("buildScopedParams", () => {
  it("injects tenant, bot, and exchange account ids when missing", () => {
    const params = buildScopedParams({}, scope as any, "tenant-1");
    expect(params.tenant_id).toBe("tenant-1");
    expect(params.bot_id).toBe("bot-1");
    expect(params.exchange_account_id).toBe("ex-1");
  });

  it("does not override existing params", () => {
    const params = buildScopedParams(
      { tenant_id: "t-existing", bot_id: "b-existing", exchange_account_id: "ex-existing" },
      scope as any,
      "tenant-1"
    );
    expect(params.tenant_id).toBe("t-existing");
    expect(params.bot_id).toBe("b-existing");
    expect(params.exchange_account_id).toBe("ex-existing");
  });

  it("preserves explicit camelCase scope params without duplicating aliases", () => {
    const params = buildScopedParams(
      { botId: "b-camel", exchangeAccountId: "ex-camel" },
      scope as any,
      "tenant-1"
    );
    expect(params.botId).toBe("b-camel");
    expect(params.exchangeAccountId).toBe("ex-camel");
    expect("bot_id" in params).toBe(false);
    expect("exchange_account_id" in params).toBe(false);
  });
});
