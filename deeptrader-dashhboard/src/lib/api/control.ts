import { getAuthToken } from "../../store/auth-store";
import { getAuthUser } from "../../store/auth-store";
import { api } from "./client";
import { useScopeStore } from "../../store/scope-store";

const decodeTenantFromToken = () => {
  const token = getAuthToken();
  if (!token || token.split(".").length !== 3) return undefined;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    const tenantId = payload?.tenant_id || payload?.tenantId || payload?.user_id || payload?.userId || payload?.sub;
    return typeof tenantId === "string" && tenantId.trim() ? tenantId.trim() : undefined;
  } catch {
    return undefined;
  }
};

const requireToken = () => {
  const token = getAuthToken();
  if (!token) {
    throw new Error("Authentication required");
  }
  return token;
};

// Helper: send with token if available, but don't throw in dev so stop always works
const optionalToken = () => getAuthToken() || undefined;

// ============================================================================
// Legacy bot control (uses active config)
// ============================================================================

export const startBot = (payload?: Record<string, unknown>) => {
  // Preserve old behavior: fail fast if not authenticated.
  requireToken();
  return api.post("/bot/start", payload ?? {}).then((res) => res.data);
};

export const stopBot = () => {
  // Token is optional for dev "stop always works" behavior.
  optionalToken();
  return api.post("/bot/stop").then((res) => res.data);
};

export const emergencyStopBot = () => {
  // Token is optional for dev "stop always works" behavior.
  optionalToken();
  return api.post("/bot/emergency-stop").then((res) => res.data);
};

// ============================================================================
// Mode-aware bot lifecycle (new exchange-first architecture)
// Uses botLifecycleService which respects operating modes (SOLO/TEAM/PROP)
// ============================================================================

export interface StartBotWarning {
  code: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
}

export interface StartBotResult {
  success: boolean;
  botId: string;
  state: string;
  message?: string;
  commandId?: string;
  locksAcquired?: string[];
  trading_mode?: 'live' | 'demo' | 'paper_simulation';
  warnings?: StartBotWarning[];
}

export interface StopBotResult {
  success: boolean;
  botId: string;
  state: string;
  commandId?: string;
  locksReleased?: string[];
}

export interface BotLifecycleError {
  code: string;
  scope: 'tenant' | 'exchange' | 'bot' | 'symbol' | 'venue';
  message: string;
  details?: Record<string, unknown>;
}

interface ControlCommandResponse {
  commandId: string;
  status: string;
  commandStream: string;
  resultStream: string;
}

interface ControlResultEntry {
  command_id: string;
  status: string;
  message: string;
}

const getDefaultTenant = () => {
  const authUser = getAuthUser();
  const envTenant = import.meta.env.VITE_TENANT_ID as string | undefined;
  const tokenTenant = decodeTenantFromToken();
  return authUser?.id || tokenTenant || envTenant;
};

function buildScopeParams(botId: string, tenantId?: string) {
  // Prefer explicit tenantId, fallback to env, then scope store (if available)
  const envTenant = tenantId || getDefaultTenant();
  let scopeTenant = envTenant;
  try {
    const store = useScopeStore.getState();
    // If you add tenant scoping to the store, prefer it here
    const storeTenant = (store as any).tenantId || envTenant;
    if (storeTenant) scopeTenant = storeTenant;
  } catch {
    // scope store not initialized (SSR)
  }
  if (!scopeTenant) {
    // Persist explicit requirement instead of falling back to a guessed tenant.
    throw new Error("tenant_id_required");
  }
  return { botId, tenantId: scopeTenant };
}

export const enqueueControlCommand = async (type: string, opts: { botId: string; tenantId?: string; reason?: string; payload?: Record<string, unknown>; exchangeAccountId?: string }):
  Promise<ControlCommandResponse> => {
  requireToken();
  const { botId, tenantId, reason, payload, exchangeAccountId } = opts;
  const scoped = buildScopeParams(botId, tenantId);
  const body = {
    type,
    botId: scoped.botId,
    tenantId: scoped.tenantId,
    reason,
    payload,
    exchangeAccountId,
  };
  const res = await api.post<ControlCommandResponse>("/control/command", body);
  return res.data;
};

export const fetchCommandResults = async (opts: { botId: string; tenantId?: string; commandId?: string; limit?: number }) => {
  requireToken();
  const { botId, tenantId, commandId, limit } = opts;
  const scoped = buildScopeParams(botId, tenantId);
  const res = await api.get<{ results: ControlResultEntry[] }>("/control/command-results", {
    params: {
      botId: scoped.botId,
      tenantId: scoped.tenantId,
      commandId,
      limit,
    },
  });
  return res.data.results;
};

/**
 * Start a specific bot using mode-aware lifecycle service
 * In SOLO mode: will stop any other running bot on the same exchange+env
 * In TEAM/PROP mode: will acquire symbol locks for the bot's enabled symbols
 */
export const startBotById = (
  botId: string,
  options?: {
    force?: boolean;
    exchangeAccountId?: string;
    botExchangeConfigId?: string;
    configVersion?: number;
    enabledSymbols?: string[];
    riskConfig?: Record<string, unknown>;
    executionConfig?: Record<string, unknown>;
    profileOverrides?: Record<string, unknown>;
  },
) => {
  return enqueueControlCommand("start_bot", {
    botId,
    payload: {
      ...options,
      bot_exchange_config_id: options?.botExchangeConfigId,
      config_version: options?.configVersion,
      enabled_symbols: options?.enabledSymbols,
      risk_config: options?.riskConfig,
      execution_config: options?.executionConfig,
      profile_overrides: options?.profileOverrides,
    },
    exchangeAccountId: options?.exchangeAccountId,
  }).then((res) => ({
    success: true,
    botId,
    state: "queued",
    message: `command:${res.commandId}`,
    commandId: res.commandId,
    warnings: [],
  }));
};

/**
 * Stop a specific bot using mode-aware lifecycle service
 * Releases symbol locks and updates bot state
 */
export const stopBotById = (botId: string, options?: { exchangeAccountId?: string }) => {
  return enqueueControlCommand("stop_bot", { botId, exchangeAccountId: options?.exchangeAccountId }).then((res) => ({
    success: true,
    botId,
    state: "queued",
    message: `command:${res.commandId}`,
    commandId: res.commandId,
  }));
};

/**
 * Pause a specific bot (keeps positions, stops new orders)
 */
export const pauseBotById = (botId: string) => {
  return enqueueControlCommand("pause_bot", { botId }).then((res) => ({
    success: true,
    botId,
    state: "queued",
    message: `command:${res.commandId}`,
    commandId: res.commandId,
  }));
};

/**
 * Resume a paused bot
 */
export const resumeBotById = (botId: string) => {
  return enqueueControlCommand("start_bot", { botId }).then((res) => ({
    success: true,
    botId,
    state: "queued",
    message: `command:${res.commandId}`,
    commandId: res.commandId,
    warnings: [],
  }));
};
