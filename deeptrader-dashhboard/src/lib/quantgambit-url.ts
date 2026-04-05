// Centralized URL construction for quantgambit.local reverse-proxy setups.
//
// Important: In local dev we run nginx unprivileged (usually on :8080). Many
// browser URL-based heuristics accidentally drop the port and break login.

type QuantGambitSubdomain = "api" | "bot";

function getPortSuffix(): string {
  if (typeof window === "undefined") return "";
  const port = window.location.port;
  if (!port) return "";
  if (port === "80" || port === "443") return "";
  return `:${port}`;
}

function isLocalhost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function isQuantgambitLocal(hostname: string): boolean {
  return hostname.endsWith("quantgambit.local");
}

function isQuantgambitProd(hostname: string): boolean {
  return hostname.endsWith("quantgambit.com");
}

export function isDashboardHost(hostname?: string): boolean {
  if (typeof window === "undefined") return true;
  const host = (hostname ?? window.location.hostname).toLowerCase();
  if (host === "localhost" || host === "127.0.0.1") return true;
  if (host.startsWith("dashboard.")) return true;
  if (host === "dashboard.quantgambit.local") return true;
  return false;
}

export function landingOrigin(): string {
  if (import.meta.env.VITE_LANDING_URL) {
    return import.meta.env.VITE_LANDING_URL;
  }
  if (typeof window === "undefined") return "https://quantgambit.com";
  const protocol = window.location.protocol;
  const hostname = window.location.hostname;
  const portSuffix = getPortSuffix();
  if (isQuantgambitLocal(hostname)) {
    return `${protocol}//quantgambit.local${portSuffix}`;
  }
  if (hostname.endsWith("quantgambit.com")) {
    return `${protocol}//quantgambit.com`;
  }
  return `${protocol}//${hostname}${portSuffix}`;
}

export function dashboardOrigin(): string {
  if (import.meta.env.VITE_DASHBOARD_URL) {
    return import.meta.env.VITE_DASHBOARD_URL;
  }
  if (typeof window === "undefined") return "https://dashboard.quantgambit.com";
  const protocol = window.location.protocol;
  const hostname = window.location.hostname;
  const portSuffix = getPortSuffix();
  if (isQuantgambitLocal(hostname)) {
    return `${protocol}//dashboard.quantgambit.local${portSuffix}`;
  }
  if (hostname.endsWith("quantgambit.com")) {
    return `${protocol}//dashboard.quantgambit.com`;
  }
  // Fallback: same host (useful for ad-hoc environments)
  return `${protocol}//${hostname}${portSuffix}`;
}

export function quantgambitOrigin(subdomain: QuantGambitSubdomain): string {
  if (typeof window === "undefined") return `http://${subdomain}.quantgambit.local`;
  const protocol = window.location.protocol;
  const hostname = window.location.hostname;
  const portSuffix = getPortSuffix();

  // If accessed via *.quantgambit.local, use the nginx proxy domain and KEEP the port.
  if (isQuantgambitLocal(hostname)) {
    return `${protocol}//${subdomain}.quantgambit.local${portSuffix}`;
  }

  if (isQuantgambitProd(hostname)) {
    return `${protocol}//${subdomain}.quantgambit.com`;
  }

  // Remote access via IP/hostname (not localhost): keep current host and use fixed service ports.
  if (!isLocalhost(hostname)) {
    // Prefer explicit env overrides in non-local environments.
    // This avoids accidentally targeting dashboard.quantgambit.com:3001, etc.
    if (subdomain === "api" && import.meta.env.VITE_CORE_API_BASE_URL) {
      return import.meta.env.VITE_CORE_API_BASE_URL.replace(/\/api\/?$/, "");
    }
    if (subdomain === "bot" && import.meta.env.VITE_BOT_API_BASE_URL) {
      return import.meta.env.VITE_BOT_API_BASE_URL.replace(/\/api\/?$/, "");
    }
    const port = subdomain === "api" ? "3001" : "3002";
    return `${protocol}//${hostname}:${port}`;
  }

  // Local development (localhost): use env overrides when available.
  const port =
    subdomain === "api"
      ? (import.meta.env.VITE_API_PORT || "3001")
      : (import.meta.env.VITE_BOT_API_PORT || "3002");
  return `${protocol}//${hostname}:${port}`;
}

export function coreApiBaseUrl(): string {
  if (import.meta.env.VITE_CORE_API_BASE_URL) {
    return import.meta.env.VITE_CORE_API_BASE_URL;
  }
  return `${quantgambitOrigin("api")}/api`;
}

export function botApiBaseUrl(): string {
  if (import.meta.env.VITE_BOT_API_BASE_URL) {
    return import.meta.env.VITE_BOT_API_BASE_URL;
  }
  return `${quantgambitOrigin("bot")}/api`;
}

export function wsBaseUrl(): string {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL;
  }
  if (typeof window === "undefined") return "ws://localhost:3002";
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const hostname = window.location.hostname;

  if (isQuantgambitLocal(hostname)) {
    // The websocket bridge lives on the core API host.
    return `${wsProtocol}//api.quantgambit.local`;
  }
  if (isQuantgambitProd(hostname)) {
    return `${wsProtocol}//api.quantgambit.com`;
  }
  if (!isLocalhost(hostname)) {
    return `${wsProtocol}//${hostname}:3001`;
  }

  const port = import.meta.env.VITE_CORE_API_PORT || "3001";
  return `${wsProtocol}//${hostname}:${port}`;
}
