/**
 * User-scoped notification WebSocket (/api/v1/ws/notifications).
 * Live page refresh uses WebSocketContext (/api/v1/ws).
 */

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

class WebSocketService {
  constructor() {
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 8;
    this.reconnectInterval = 5000;
    this.listeners = new Map();
    this.notificationCount = 0;
    this.isConnecting = false;
    this.token = null;
    this.pingTimer = null;
  }

  connect(token) {
    if (
      this.isConnecting ||
      (this.ws && this.ws.readyState === WebSocket.OPEN)
    ) {
      return;
    }

    this.token = token;
    this.isConnecting = true;
    const wsUrl = buildWsUrl("/api/v1/ws/notifications");

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this.emit("connected");

        if (this.token) {
          this.ws.send(
            JSON.stringify({
              type: "auth",
              token: this.token,
            }),
          );
        }

        if (this.pingTimer) clearInterval(this.pingTimer);
        this.pingTimer = setInterval(() => this.ping(), 30000);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (e) {
          console.error("Notification WebSocket parse error", e);
        }
      };

      this.ws.onclose = (event) => {
        this.isConnecting = false;
        if (this.pingTimer) {
          clearInterval(this.pingTimer);
          this.pingTimer = null;
        }

        if (event.code === 4001) {
          console.error("Notification WebSocket authentication failed");
          return;
        }

        this.attemptReconnect();
      };

      this.ws.onerror = () => {
        this.isConnecting = false;
      };
    } catch (error) {
      console.error("Failed to create notification WebSocket:", error);
      this.isConnecting = false;
      this.attemptReconnect();
    }
  }

  handleMessage(data) {
    switch (data.type) {
      case "notification_count":
        this.notificationCount = data.count ?? 0;
        this.emit("notificationCount", this.notificationCount);
        break;
      case "new_notification":
        this.notificationCount += 1;
        this.emit("notificationCount", this.notificationCount);
        this.emit("newNotification", data.notification);
        break;
      case "notifications_cleared":
        this.notificationCount = 0;
        this.emit("notificationCount", 0);
        break;
      case "notification_count_updated":
        this.emit("countUpdateNeeded");
        break;
      case "refresh_data":
        this.emit("refreshData", data);
        break;
      case "connected":
      case "pong":
      case "auth_ok":
        break;
      default:
        break;
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts += 1;
      setTimeout(() => this.connect(this.token), this.reconnectInterval);
    }
  }

  disconnect() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.isConnecting = false;
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
  }

  off(event, callback) {
    if (!this.listeners.has(event)) return;
    const callbacks = this.listeners.get(event);
    const index = callbacks.indexOf(callback);
    if (index > -1) callbacks.splice(index, 1);
  }

  emit(event, data) {
    if (!this.listeners.has(event)) return;
    this.listeners.get(event).forEach((callback) => callback(data));
  }

  clearNotifications() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "clear_notifications" }));
    }
  }

  getNotificationCount() {
    return this.notificationCount;
  }

  ping() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "ping" }));
    }
  }
}

const websocketService = new WebSocketService();

export default websocketService;
