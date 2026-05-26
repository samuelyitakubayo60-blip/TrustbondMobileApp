import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useAuth } from "./AuthContext";

const WebSocketContext = createContext({
  lastMessage: null,
  refreshKey: 0,
  connected: false,
  matchesEntity: () => true,
});

function resolveApiBase() {
  const raw = import.meta.env.VITE_API_BASE_URL || "";
  if (raw && /^https?:\/\//i.test(raw)) {
    return raw.replace(/\/$/, "");
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin.replace(/\/$/, "");
  }
  return "http://localhost:8000";
}

function buildWsUrl(path) {
  const apiBase = resolveApiBase();
  const protocol = apiBase.startsWith("https") ? "wss:" : "ws:";
  const host = apiBase.replace(/^https?:\/\//, "");
  return `${protocol}//${host}${path}`;
}

export const WebSocketProvider = ({ children }) => {
  const { user } = useAuth();
  const [lastMessage, setLastMessage] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [connected, setConnected] = useState(false);
  const ws = useRef(null);
  const reconnectTimeout = useRef(null);
  const pingTimer = useRef(null);

  const matchesEntity = useCallback(
    (message, entities) => {
      if (!message || message.type !== "refresh_data") return false;
      if (!entities || !entities.length) return true;
      const entity = String(message.entity || "").toLowerCase();
      return entities.some((e) => entity === String(e).toLowerCase());
    },
    [],
  );

  useEffect(() => {
    if (!user) {
      setConnected(false);
      return undefined;
    }

    let isComponentMounted = true;

    const connect = () => {
      if (!isComponentMounted) return;

      const wsUrl = buildWsUrl("/api/v1/ws");
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        if (!isComponentMounted) return;
        setConnected(true);
        if (reconnectTimeout.current) {
          clearTimeout(reconnectTimeout.current);
          reconnectTimeout.current = null;
        }
        if (pingTimer.current) clearInterval(pingTimer.current);
        pingTimer.current = setInterval(() => {
          if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "refresh_data") {
            setLastMessage(data);
            setRefreshKey((prev) => prev + 1);
          }
        } catch (e) {
          console.error("Failed to parse refresh WebSocket message", e);
        }
      };

      ws.current.onclose = () => {
        if (!isComponentMounted) return;
        setConnected(false);
        if (pingTimer.current) {
          clearInterval(pingTimer.current);
          pingTimer.current = null;
        }
        reconnectTimeout.current = setTimeout(connect, 3000);
      };

      ws.current.onerror = () => {
        ws.current?.close();
      };
    };

    connect();

    return () => {
      isComponentMounted = false;
      setConnected(false);
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
      if (pingTimer.current) {
        clearInterval(pingTimer.current);
        pingTimer.current = null;
      }
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.onerror = null;
        ws.current.close();
      }
    };
  }, [user]);

  const value = useMemo(
    () => ({ lastMessage, refreshKey, connected, matchesEntity }),
    [lastMessage, refreshKey, connected, matchesEntity],
  );

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useRealtime = () =>
  useContext(WebSocketContext) || {
    refreshKey: 0,
    lastMessage: null,
    connected: false,
    matchesEntity: () => true,
  };

/**
 * Bump refreshKey only when the WS payload matches one of the given entities.
 * Example: useEntityRefresh(['hotspot', 'report'])
 */
export function useEntityRefresh(entities, onRefresh) {
  const { refreshKey, lastMessage, matchesEntity } = useRealtime();
  const lastHandled = useRef(0);

  useEffect(() => {
    if (!onRefresh || lastHandled.current === refreshKey) return;
    if (!matchesEntity(lastMessage, entities)) return;
    lastHandled.current = refreshKey;
    onRefresh(lastMessage);
  }, [refreshKey, lastMessage, entities, onRefresh, matchesEntity]);
}
