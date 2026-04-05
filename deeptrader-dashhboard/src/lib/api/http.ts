function getCoreApiBaseUrl(): string {
  if (import.meta.env.VITE_CORE_API_BASE_URL) {
    return import.meta.env.VITE_CORE_API_BASE_URL;
  }
  // Dynamic detection for remote access
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    const port = window.location.port;
    const portSuffix = port ? `:${port}` : "";
    
    // Handle quantgambit.local domains (via nginx proxy)
    if (hostname.endsWith('quantgambit.local')) {
      return `${protocol}//api.quantgambit.local${portSuffix}/api`;
    }

    // Production domains should always use the proxied API host, not browser-visible service ports.
    if (hostname.endsWith('quantgambit.com')) {
      return `${protocol}//api.quantgambit.com/api`;
    }
    
    // Handle IP-based access (remote machines) or any non-localhost hostname
    if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
      return `${protocol}//${hostname}:3001/api`;
    }
  }
  return "http://localhost:3001/api";
}

// Use getter to ensure dynamic resolution
const getApiBaseUrl = () => getCoreApiBaseUrl();
const API_BASE_URL = getCoreApiBaseUrl();

type RequestOptions = {
  method?: string;
  data?: unknown;
  headers?: Record<string, string>;
  token?: string | null;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", data, headers = {}, token } = options;

  const requestHeaders: Record<string, string> = {
    ...headers,
  };

  const init: RequestInit = {
    method,
    headers: requestHeaders,
  };

  if (data !== undefined) {
    init.body = JSON.stringify(data);
    requestHeaders["Content-Type"] = requestHeaders["Content-Type"] ?? "application/json";
  }

  if (token) {
    requestHeaders.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, init);

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      message = payload?.error || payload?.message || message;
    } catch {
      // ignore JSON parse failure
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export { API_BASE_URL };




