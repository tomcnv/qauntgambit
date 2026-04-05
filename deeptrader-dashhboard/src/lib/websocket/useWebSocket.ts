import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { usePriceStore, PriceUpdate } from "../../store/price-store";
import { useScopeStore } from "../../store/scope-store";
import { shouldProcessMessage } from "./filter";
import { wsBaseUrl } from "../quantgambit-url";
import { showTradeEventToast } from "./tradeToasts";

const AUTH_TOKEN_KEY = "deeptrader_token";

type WebSocketEvent = {
  event: string;
  data: unknown;
  meta?: {
    tenantId?: string;
    botId?: string;
    exchange?: string;
    symbol?: string;
  };
};

type WebSocketStatus = "connecting" | "connected" | "disconnected" | "error";

// Determine WebSocket URL - use wss:// for HTTPS, ws:// for HTTP
const getWebSocketUrl = () => {
  const envUrl = import.meta.env.VITE_WS_URL;
  let baseUrl: string;
  
  if (envUrl) {
    // Remove trailing slash if present
    baseUrl = envUrl.replace(/\/$/, '');
  } else {
    baseUrl = wsBaseUrl();
  }
  
  // Append auth token if available for user-scoped WebSocket
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    return `${baseUrl}?token=${encodeURIComponent(token)}`;
  }
  
  return baseUrl;
};

// Don't use a const because token may change after login
const getWsUrl = () => typeof window !== 'undefined' ? getWebSocketUrl() : 'ws://localhost:3002';

export function useWebSocket() {
  const [status, setStatus] = useState<WebSocketStatus>("disconnected");
  const [lastMessage, setLastMessage] = useState<WebSocketEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const notifiedEventsRef = useRef<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const updatePrice = usePriceStore((s) => s.updatePrice);
  const lastInvalidateAtRef = useRef<Map<string, number>>(new Map());

  const MAX_RECONNECT_ATTEMPTS = 5; // Reduced to fail faster and not spam
  const RECONNECT_DELAY = 2000; // Start with 2 seconds
  const INVALIDATE_MIN_INTERVAL_MS = 2500;

  const invalidateThrottled = useCallback(
    (queryKey: unknown[]) => {
      const key = JSON.stringify(queryKey);
      const now = Date.now();
      const last = lastInvalidateAtRef.current.get(key) ?? 0;
      if (now - last < INVALIDATE_MIN_INTERVAL_MS) {
        return;
      }
      lastInvalidateAtRef.current.set(key, now);
      queryClient.invalidateQueries({ queryKey });
    },
    [queryClient],
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return; // Already connected
    }

    setStatus("connecting");
    const wsUrl = getWsUrl();
    console.log(`🔌 Connecting to WebSocket: ${wsUrl.split('?')[0]} (auth: ${wsUrl.includes('token=') ? 'yes' : 'no'})`);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("✅ WebSocket connected");
        setStatus("connected");
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketEvent = JSON.parse(event.data);
          // Avoid forcing global context re-renders for every websocket packet.
          // Only persist messages that currently drive UI effects via `lastMessage`.
          if (message.event === "bot:execution_slippage_rollup" || message.event === "bot:error") {
            setLastMessage(message);
          }

          // Handle different event types
          // Filter by scope if meta is present
          const envTenant = import.meta.env.VITE_TENANT_ID as string | undefined;
          const currentScope = useScopeStore.getState();
          if (!shouldProcessMessage(message.meta, currentScope, envTenant)) {
            return;
          }

          switch (message.event) {
            case "bot:status":
              // Invalidate bot status queries to trigger refetch
              invalidateThrottled(["ops-snapshot"]);
              invalidateThrottled(["bot-status"]);
              break;

            case "bot:trade":
            case "bot:position_opened":
            case "bot:position_closed":
              {
                const payload =
                  message.data && typeof message.data === "object"
                    ? (message.data as Record<string, unknown>)
                    : {};
                const dedupeSeed =
                  String(payload.order_id || payload.close_order_id || payload.client_order_id || payload.trade_id || payload.id || "")
                  || String(payload.position_id || "")
                  || `${message.event}:${String(payload.symbol || message.meta?.symbol || "")}:${String(payload.timestamp || payload.ts || "")}`;
                const dedupeKey = `${message.event}:${dedupeSeed}`;
                if (!notifiedEventsRef.current.has(dedupeKey)) {
                  notifiedEventsRef.current.add(dedupeKey);
                  showTradeEventToast({
                    eventName: message.event,
                    data: message.data,
                    meta: { symbol: message.meta?.symbol },
                    dedupeKey,
                  });
                }
              }
              // Invalidate trading data
              invalidateThrottled(["fast-scalper-detail"]);
              invalidateThrottled(["ops-snapshot"]);
              invalidateThrottled(["trade-history"]);
              invalidateThrottled(["trade-history-v2"]);
              break;
            case "bot:position_update":
              // Invalidate trading data
              invalidateThrottled(["fast-scalper-detail"]);
              invalidateThrottled(["ops-snapshot"]);
              break;

            case "bot:decision":
            case "bot:signal":
              // Invalidate signal data
              invalidateThrottled(["fast-scalper-rejections"]);
              break;

            case "bot:alert":
              // Invalidate alerts
              invalidateThrottled(["monitoring-alerts"]);
              if (
                message.data &&
                typeof message.data === "object" &&
                (message.data as any).type === "execution_slippage_alert"
              ) {
                const alertData = message.data as any;
                const symbol = String(alertData.symbol || "symbol");
                const avg = Number(alertData.avg_realized_slippage_bps || 0).toFixed(2);
                const target = Number(alertData.target_slippage_bps || 0).toFixed(2);
                toast.error(`Slippage alert ${symbol}: ${avg}bps > target ${target}bps`);
              }
              break;

            case "bot:error":
              // Bot crashed - invalidate status and trigger error display
              console.error("🚨 Bot error received:", message.data);
              invalidateThrottled(["ops-snapshot"]);
              invalidateThrottled(["bot-status"]);
              // Store error for toast display - components can react via lastMessage
              break;

            case "price:update":
              // Real-time price update - update the price store for live P&L calculation
              if (message.data && typeof message.data === 'object') {
                updatePrice(message.data as PriceUpdate);
              }
              break;

            case "loss_prevention_update":
              // Loss prevention signal blocked - invalidate metrics and rejected signals
              invalidateThrottled(["loss-prevention-metrics"]);
              invalidateThrottled(["rejected-signals"]);
              break;

            case "bot:execution_slippage_rollup":
              // Execution-cost rollup update - refresh ops/trade views used for EV tuning.
              invalidateThrottled(["ops-snapshot"]);
              invalidateThrottled(["fast-scalper-detail"]);
              invalidateThrottled(["execution-slippage-rollup"]);
              break;

            default:
              // Unknown events are intentionally ignored to avoid noisy re-renders.
              break;
          }
        } catch (error) {
          console.error("❌ Failed to parse WebSocket message:", error);
        }
      };

      ws.onerror = (error) => {
        console.error("❌ WebSocket error:", error);
        console.error("❌ WebSocket URL was:", wsUrl.split('?')[0]);
        console.error("❌ Check that backend server is running and WebSocket server is initialized");
        setStatus("error");
        // Don't immediately reconnect on error - let onclose handle it
      };

      ws.onclose = (event) => {
        console.log(`🔌 WebSocket closed (code: ${event.code}, reason: ${event.reason || 'none'})`);
        setStatus("disconnected");
        wsRef.current = null;

        // Attempt to reconnect if not a normal closure and not a client-initiated disconnect
        if (event.code !== 1000 && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          const delay = Math.min(RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current), 30000); // Cap at 30s
          reconnectAttemptsRef.current++;

          console.log(`🔄 Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})...`);

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
          console.warn("⚠️ WebSocket connection failed after max attempts. Dashboard will continue without real-time updates.");
          console.warn("   To enable WebSocket: Start the backend server (cd deeptrader-backend && npm start)");
          // Don't set status to error - keep it as disconnected so UI doesn't break
          setStatus("disconnected");
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error("❌ Failed to create WebSocket:", error);
      setStatus("error");
    }
  }, [queryClient]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, "Client disconnecting");
      wsRef.current = null;
    }

    setStatus("disconnected");
  }, []);

  // Reconnect with fresh auth token (call after login)
  const reconnect = useCallback(() => {
    console.log("🔄 Reconnecting WebSocket with fresh auth...");
    reconnectAttemptsRef.current = 0;
    disconnect();
    setTimeout(() => connect(), 500);
  }, [disconnect, connect]);

  const send = useCallback((event: string, data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ event, data }));
      return true;
    }
    console.warn("⚠️ WebSocket not connected, cannot send message");
    return false;
  }, []);

  // Subscribe to specific event types
  const subscribe = useCallback(
    (eventType: string, callback: (data: unknown) => void) => {
      // This is a simple implementation - in a more complex system, you'd use an event emitter
      // For now, components can use lastMessage and check the event type
      return () => {
        // Unsubscribe (no-op for now)
      };
    },
    []
  );

  useEffect(() => {
    // Only connect if we're in the browser
    if (typeof window === 'undefined') {
      return;
    }

    // Delay connection slightly to avoid blocking initial render
    const timeoutId = setTimeout(() => {
      connect();
    }, 1000);

    return () => {
      clearTimeout(timeoutId);
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    status,
    lastMessage,
    connect,
    disconnect,
    reconnect,
    send,
    subscribe,
    isConnected: status === "connected",
  };
}
