import { type ScopeState } from "../../store/scope-store";
import { getAuthToken, getAuthUser } from "../../store/auth-store";

function decodeTenantFromToken(): string | undefined {
  const token = getAuthToken();
  if (!token || token.split(".").length !== 3) return undefined;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    const tenantId = payload?.tenant_id || payload?.tenantId || payload?.user_id || payload?.userId || payload?.sub;
    return typeof tenantId === "string" && tenantId.trim() ? tenantId.trim() : undefined;
  } catch {
    return undefined;
  }
}

export function buildScopedParams(
  existing: Record<string, unknown> | undefined,
  scope: ScopeState,
  envTenantId?: string
): Record<string, unknown> {
  const params = existing ? { ...existing } : {};
  const hadCamelBotId = Object.prototype.hasOwnProperty.call(params, "botId");
  const hadSnakeBotId = Object.prototype.hasOwnProperty.call(params, "bot_id");
  const hadCamelExchangeAccountId = Object.prototype.hasOwnProperty.call(params, "exchangeAccountId");
  const hadSnakeExchangeAccountId = Object.prototype.hasOwnProperty.call(params, "exchange_account_id");
  const {
    tenantId: _tenantIdCamel,
    botId: _botIdCamel,
    exchangeAccountId: _exchangeAccountIdCamel,
    ...normalizedParams
  } = params;
  // Priority: explicit param > authenticated user > env fallback.
  // The env fallback is only for unauthenticated/dev-hosted cases; it must not
  // override the logged-in user or ownership-scoped APIs will query the wrong tenant.
  const authUser = getAuthUser();
  const tokenTenantId = decodeTenantFromToken();
  const tenantId =
    (params.tenant_id as string) ||
    (_tenantIdCamel as string) ||
    authUser?.tenantId ||
    authUser?.id ||
    tokenTenantId ||
    envTenantId ||
    undefined;
  const botId = (params.bot_id as string) || (_botIdCamel as string) || scope.botId || undefined;
  const exchangeAccountId =
    (params.exchange_account_id as string) ||
    (_exchangeAccountIdCamel as string) ||
    scope.exchangeAccountId ||
    undefined;
  return {
    ...normalizedParams,
    ...(tenantId ? { tenant_id: tenantId } : {}),
    ...(botId
      ? hadCamelBotId && !hadSnakeBotId
        ? { botId }
        : { bot_id: botId }
      : {}),
    ...(exchangeAccountId
      ? hadCamelExchangeAccountId && !hadSnakeExchangeAccountId
        ? { exchangeAccountId }
        : { exchange_account_id: exchangeAccountId }
      : {}),
  };
}
