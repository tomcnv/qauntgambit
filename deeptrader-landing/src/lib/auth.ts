import axios, { AxiosError } from "axios";

// Dynamically determine API URL based on current hostname
function getApiBaseUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    
    // Handle quantgambit.local domains (via nginx proxy)
    if (hostname.endsWith('quantgambit.local')) {
      return `${protocol}//api.quantgambit.local/api`;
    }

    // Handle production/staging-style subdomains behind Cloudflare/nginx.
    if (hostname === 'quantgambit.com' || hostname.endsWith('.quantgambit.com')) {
      return `${protocol}//api.quantgambit.com/api`;
    }
    
    // Handle IP-based access (remote machines) or any non-localhost hostname
    // This covers: 192.168.x.x, 10.x.x.x, custom hostnames, etc.
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return `${protocol}//${hostname}:3001/api`;
    }
  }
  return "http://localhost:3001/api";
}

// Dynamically determine Dashboard URL
function getDashboardBaseUrl(): string {
  if (import.meta.env.VITE_DASHBOARD_URL) {
    return import.meta.env.VITE_DASHBOARD_URL;
  }
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    
    // Handle quantgambit.local domains (via nginx proxy)
    if (hostname.endsWith('quantgambit.local')) {
      return `${protocol}//dashboard.quantgambit.local`;
    }

    if (hostname === 'quantgambit.com' || hostname.endsWith('.quantgambit.com')) {
      return `${protocol}//dashboard.quantgambit.com`;
    }
    
    // Handle IP-based access (remote machines) or any non-localhost hostname
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return `${protocol}//${hostname}:5173`;
    }
  }
  return "http://localhost:5173";
}

// Lazy-evaluated to ensure window is available
let _apiBaseUrl: string | null = null;
let _dashboardUrl: string | null = null;

function getApiUrl(): string {
  if (!_apiBaseUrl) {
    _apiBaseUrl = getApiBaseUrl();
  }
  return _apiBaseUrl;
}

export function getDashboardUrl(): string {
  if (!_dashboardUrl) {
    _dashboardUrl = getDashboardBaseUrl();
  }
  return _dashboardUrl;
}

// Keep DASHBOARD_URL as a getter for backwards compatibility
export const DASHBOARD_URL = typeof window !== 'undefined' ? getDashboardBaseUrl() : "http://dashboard.quantgambit.local";

// Token storage key (shared with dashboard)
const TOKEN_KEY = "deeptrader_token";

export type AuthUser = {
  id: string;
  email: string;
  username: string;
  firstName?: string | null;
  lastName?: string | null;
  role?: string | null;
  createdAt?: string;
  lastLogin?: string | null;
};

type AuthResponse = {
  message?: string;
  user: AuthUser;
  token: string;
};

type ApiError = {
  error: string;
  message?: string;
};

/**
 * Login with email and password
 */
export async function login(email: string, password: string): Promise<AuthResponse> {
  try {
    const response = await axios.post<AuthResponse>(`${getApiUrl()}/auth/login`, {
      email,
      password,
    });
    
    // Store token
    localStorage.setItem(TOKEN_KEY, response.data.token);
    
    return response.data;
  } catch (error) {
    const axiosError = error as AxiosError<ApiError>;
    throw new Error(axiosError.response?.data?.error || "Login failed");
  }
}

/**
 * Register a new user with enterprise fields stored in metadata
 */
export async function register(payload: {
  email: string;
  username: string;
  password: string;
  firstName?: string;
  lastName?: string;
  metadata?: {
    company?: string;
    firmType?: string;
    aum?: string;
    message?: string;
    intent?: string;
    registrationSource?: string;
    requiresApproval?: boolean;
  };
}): Promise<AuthResponse> {
  try {
    const response = await axios.post<AuthResponse>(`${getApiUrl()}/auth/register`, payload);
    
    // Store token
    localStorage.setItem(TOKEN_KEY, response.data.token);
    
    return response.data;
  } catch (error) {
    const axiosError = error as AxiosError<ApiError>;
    throw new Error(axiosError.response?.data?.error || "Registration failed");
  }
}

/**
 * Get stored auth token
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Clear auth token
 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
  return !!getToken();
}

/**
 * Redirect to dashboard with token
 * Since localStorage is not shared across subdomains, we pass the token via URL
 */
export function redirectToDashboard(returnTo?: string): void {
  const token = getToken();
  if (token) {
    // Pass token via URL hash (not query param to avoid server logging)
    // Dashboard will capture this and store in its localStorage
    const destination = returnTo || `${DASHBOARD_URL}/dashboard`;
    const url = new URL(destination);
    url.searchParams.set("auth_token", token);
    window.location.href = url.toString();
  }
}

/**
 * Get the dashboard URL with token for redirect
 */
export function getDashboardUrlWithToken(path: string = "/dashboard"): string {
  const token = getToken();
  if (token) {
    const url = new URL(path, DASHBOARD_URL);
    url.searchParams.set("auth_token", token);
    return url.toString();
  }
  return `${DASHBOARD_URL}${path}`;
}

/**
 * Redirect to sign in page
 */
export function redirectToSignIn(returnTo?: string): void {
  const params = returnTo ? `?returnTo=${encodeURIComponent(returnTo)}` : "";
  window.location.href = `/sign-in${params}`;
}
