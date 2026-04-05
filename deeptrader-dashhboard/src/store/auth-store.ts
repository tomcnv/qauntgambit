import { create } from "zustand";
import { QueryClient } from "@tanstack/react-query";
import { AuthUser, getProfile, login as loginApi, logout as logoutApi, register as registerApi } from "../lib/api/auth";
import { useScopeStore } from "./scope-store";

const TOKEN_KEY = "deeptrader_token";

// Landing page URL for sign-in redirects - detect dynamically based on current hostname
function getLandingUrl(): string {
  if (import.meta.env.VITE_LANDING_URL) {
    return import.meta.env.VITE_LANDING_URL;
  }
  // Dynamic detection based on current hostname
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    const port = window.location.port;
    const portSuffix = port ? `:${port}` : "";
    
    // Handle quantgambit.local domains (via nginx proxy)
    if (hostname.includes('quantgambit.local')) {
      return `${protocol}//quantgambit.local${portSuffix}`;
    }

    if (hostname.endsWith('quantgambit.com')) {
      return `${protocol}//quantgambit.com`;
    }
    
    // Handle IP-based access (remote machines) or any non-localhost hostname
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return `${protocol}//${hostname}:3000`;
    }
  }
  return "http://localhost:3000";
}
const LANDING_URL = getLandingUrl();

// Reference to the query client for cache invalidation
let queryClientRef: QueryClient | null = null;
export const setQueryClientRef = (client: QueryClient) => {
  queryClientRef = client;
};

function resetClientSessionState() {
  useScopeStore.getState().setFleetScope();
  queryClientRef?.clear();
}

function applyUserScope(user: AuthUser | null) {
  if (!user) return;
  const effectiveTenantId = user.tenantId || user.id;
  localStorage.setItem("tenant_id", effectiveTenantId);
  if (user.role === "viewer" && user.viewerScope?.botId && user.viewerScope?.exchangeAccountId) {
    useScopeStore
      .getState()
      .setBotScope(
        user.viewerScope.exchangeAccountId,
        user.viewerScope.exchangeAccountName || null,
        user.viewerScope.botId,
        user.viewerScope.botName || null,
      );
  }
}

type SignInPayload = {
  email: string;
  password: string;
};

type SignUpPayload = {
  email: string;
  username: string;
  password: string;
  firstName?: string;
  lastName?: string;
};

type AuthStore = {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  initialized: boolean;
  error: string | null;
  initialize: () => Promise<void>;
  login: (payload: SignInPayload) => Promise<void>;
  register: (payload: SignUpPayload) => Promise<void>;
  logout: () => Promise<void>;
};

const useAuthStore = create<AuthStore>((set, get) => ({
  user: null,
  token: null,
  loading: false,
  initialized: false,
  error: null,
  initialize: async () => {
    // Check for token in URL (passed from landing page for cross-subdomain auth)
    let tokenFromUrl: string | null = null;
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      tokenFromUrl = urlParams.get("auth_token");

      if (tokenFromUrl) {
        const previousToken = localStorage.getItem(TOKEN_KEY);
        if (previousToken !== tokenFromUrl) {
          localStorage.removeItem("tenant_id");
          resetClientSessionState();
          set({ user: null, token: null, error: null });
        }
        // Store the token and clean the URL
        localStorage.setItem(TOKEN_KEY, tokenFromUrl);
        // Remove token from URL without reload
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete("auth_token");
        window.history.replaceState({}, "", cleanUrl.toString());
      }
    }

    const storedToken = tokenFromUrl || (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null);
    if (get().initialized && !tokenFromUrl && get().token === storedToken) return;
    if (!storedToken) {
      set({ initialized: true });
      return;
    }
    const previousUserId = get().user?.id || null;
    set({ loading: true });
    try {
      const { user } = await getProfile(storedToken);
      if (previousUserId && user?.id && previousUserId !== user.id) {
        resetClientSessionState();
      }
      applyUserScope(user);
      set({ user, token: storedToken, initialized: true, loading: false, error: null });
    } catch (error) {
      console.error("Auth initialization failed:", error);
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem("tenant_id");
      resetClientSessionState();
      set({ user: null, token: null, initialized: true, loading: false, error: null });
    }
  },
  login: async (payload) => {
    set({ loading: true, error: null });
    try {
      const { token, user } = await loginApi(payload);
      localStorage.setItem(TOKEN_KEY, token);
      resetClientSessionState();
      applyUserScope(user);
      set({ user, token, loading: false, initialized: true, error: null });
    } catch (error) {
      set({ loading: false, error: (error as Error).message || "Login failed" });
      throw error;
    }
  },
  register: async (payload) => {
    set({ loading: true, error: null });
    try {
      const { token, user } = await registerApi(payload);
      localStorage.setItem(TOKEN_KEY, token);
      resetClientSessionState();
      applyUserScope(user);
      set({ user, token, loading: false, initialized: true, error: null });
    } catch (error) {
      set({ loading: false, error: (error as Error).message || "Registration failed" });
      throw error;
    }
  },
  logout: async () => {
    const token = get().token;
    if (token) {
      try {
        await logoutApi(token);
      } catch (error) {
        console.warn("Logout request failed:", error);
      }
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem("tenant_id");
    set({ user: null, token: null });
    resetClientSessionState();
    // Redirect to landing page sign-in
    window.location.href = `${LANDING_URL}/sign-in`;
  },
}));

export const getAuthToken = () => useAuthStore.getState().token;
export const getAuthUser = () => useAuthStore.getState().user;

export default useAuthStore;
