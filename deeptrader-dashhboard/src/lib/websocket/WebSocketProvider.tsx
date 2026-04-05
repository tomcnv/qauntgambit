import { createContext, useContext, ReactNode } from "react";
import { useWebSocket } from "./useWebSocket";

type WebSocketContextType = ReturnType<typeof useWebSocket>;

const WebSocketContext = createContext<WebSocketContextType | null>(null);

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const ws = useWebSocket();

  return <WebSocketContext.Provider value={ws}>{children}</WebSocketContext.Provider>;
}

export function useWebSocketContext() {
  const context = useContext(WebSocketContext);
  if (!context) {
    // Return a safe fallback instead of throwing - allows dashboard to load without WebSocket
    console.warn("useWebSocketContext used outside WebSocketProvider, returning fallback");
    return {
      status: "disconnected" as const,
      lastMessage: null,
      connect: () => {},
      disconnect: () => {},
      reconnect: () => {},
      send: () => false,
      subscribe: () => () => {},
      isConnected: false,
    };
  }
  return context;
}

