import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { ThemeProvider } from "./components/theme-provider";
import { Toaster } from "react-hot-toast";
import useAuthStore, { setQueryClientRef } from "./store/auth-store";
import { WebSocketProvider } from "./lib/websocket/WebSocketProvider";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

// Register queryClient with auth store for cache invalidation on login/logout
setQueryClientRef(queryClient);

function App() {
  const initialize = useAuthStore((state) => state.initialize);
  const initialized = useAuthStore((state) => state.initialized);
  const loading = useAuthStore((state) => state.loading);

  useEffect(() => {
    initialize();
  }, [initialize]);

      return (
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            {initialized ? (
              <WebSocketProvider>
                <RouterProvider router={router} />
                <Toaster
                  position="bottom-right"
                  toastOptions={{
                    style: {
                      background: "hsl(var(--card))",
                      color: "hsl(var(--foreground))",
                      border: "1px solid rgba(255,255,255,0.08)",
                    },
                  }}
                />
                <CopilotPanel />
              </WebSocketProvider>
            ) : (
              <>
                <div className="flex min-h-screen flex-col items-center justify-center bg-background text-foreground">
                  <p className="text-xs uppercase tracking-[0.4em] text-muted-foreground">Securing session</p>
                  <p className="mt-4 text-2xl font-semibold">
                    {loading ? "Validating your operator token..." : "Booting the control tower..."}
                  </p>
                </div>
                <Toaster
                  position="bottom-right"
                  toastOptions={{
                    style: {
                      background: "hsl(var(--card))",
                      color: "hsl(var(--foreground))",
                      border: "1px solid rgba(255,255,255,0.08)",
                    },
                  }}
                />
              </>
            )}
          </QueryClientProvider>
        </ThemeProvider>
      );
}

export default App;
