import { type ScopeState } from "../../store/scope-store";

export function shouldProcessMessage(
  meta: { tenantId?: string; botId?: string; exchange?: string } | undefined,
  scope: ScopeState,
  envTenantId?: string
): boolean {
  if (!meta) return true;
  const { tenantId, botId } = meta;
  if (scope.botId && botId && botId !== scope.botId) {
    return false;
  }
  if (envTenantId && tenantId && tenantId !== envTenantId) {
    return false;
  }
  return true;
}
