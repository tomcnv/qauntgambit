import { ReactNode, useEffect } from "react";
import { useLocation } from "react-router-dom";
import useAuthStore from "../store/auth-store";

// Landing page URL for sign-in redirects (detect dynamically)
function getLandingUrl(): string {
  if (import.meta.env.VITE_LANDING_URL) {
    return import.meta.env.VITE_LANDING_URL;
  }
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

type ProtectedRouteProps = {
  children: ReactNode;
};

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const initialized = useAuthStore((state) => state.initialized);
  const isViewer = user?.role === "viewer";
  const onViewerRoute = location.pathname.startsWith("/viewer");

  useEffect(() => {
    // Only redirect after auth state is initialized and user is not authenticated
    if (initialized && !user) {
      // Encode the current path as returnTo so landing page can redirect back after login
      // Use pathname instead of full href to avoid /dashboard prefix issues
      const returnTo = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `${LANDING_URL}/sign-in?returnTo=${returnTo}`;
    }
    if (initialized && user && isViewer && !onViewerRoute) {
      window.location.href = "/viewer";
    }
    if (initialized && user && !isViewer && onViewerRoute) {
      window.location.href = "/";
    }
  }, [initialized, user, location, isViewer, onViewerRoute]);

  // Show nothing while checking auth or redirecting
  if (!initialized || !user) {
    return null;
  }
  if ((isViewer && !onViewerRoute) || (!isViewer && onViewerRoute)) {
    return null;
  }

  return children;
}
