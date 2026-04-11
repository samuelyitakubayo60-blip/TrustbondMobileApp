class WebSocketService {
  constructor() {
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectInterval = 5000;
    this.listeners = new Map();
    this.notificationCount = 0;
    this.isConnecting = false;
    this.token = null;
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

    // Use the same API base URL as the REST API
    const apiBaseUrl =
      import.meta.env.VITE_API_BASE_URL ||
      "https://trustbondmobileapp.onrender.com";
    const wsProtocol = apiBaseUrl.startsWith("https") ? "wss:" : "ws:";
    const wsUrl = apiBaseUrl.replace(/^https?:/, wsProtocol) + "/api/v1/ws";

    console.log("Connecting to WebSocket:", wsUrl);

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log("WebSocket connected");
        this.isConnecting = false;
        this.reconnectAttempts = 0;

        // Send authentication token
        if (this.token) {
          this.ws.send(
            JSON.stringify({
              type: "auth",
              token: this.token,
            }),
          );
        }
      };

      this.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      };

      this.ws.onclose = (event) => {
        console.log("WebSocket disconnected:", event.code, event.reason);
        this.isConnecting = false;

        // Don't reconnect if it's an authentication error
        if (event.code === 4001) {
          console.error("WebSocket authentication failed");
          return;
        }

        this.attemptReconnect();
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        this.isConnecting = false;
      };
    } catch (error) {
      console.error("Failed to create WebSocket connection:", error);
      this.isConnecting = false;
      this.attemptReconnect();
    }
  }

  handleMessage(data) {
    switch (data.type) {
      case "notification_count":
        this.notificationCount = data.count;
        this.emit("notificationCount", data.count);
        break;
      case "new_notification":
        this.notificationCount++;
        this.emit("notificationCount", this.notificationCount);
        this.emit("newNotification", data.notification);
        break;
      case "notifications_cleared":
        this.notificationCount = 0;
        this.emit("notificationCount", 0);
        break;
      case "notification_count_updated":
        // Count was updated, fetch fresh count from API
        this.emit("countUpdateNeeded");
        break;
      case "pong":
        // Keep-alive response
        break;
      default:
        console.log("Unknown message type:", data.type);
    }
  }

  attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      console.log(
        `Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`,
      );

      setTimeout(() => {
        this.connect(this.token);
      }, this.reconnectInterval);
    } else {
      console.error("Max reconnection attempts reached");
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.isConnecting = false;
  }

  // Event listener methods
  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
  }

  off(event, callback) {
    if (this.listeners.has(event)) {
      const callbacks = this.listeners.get(event);
      const index = callbacks.indexOf(callback);
      if (index > -1) {
        callbacks.splice(index, 1);
      }
    }
  }

  emit(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach((callback) => callback(data));
    }
  }

  // Manual methods
  clearNotifications() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: "clear_notifications",
        }),
      );
    }
  }

  getNotificationCount() {
    return this.notificationCount;
  }

  // Send keep-alive ping
  ping() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "ping" }));
    }
  }
}

// Create singleton instance
const websocketService = new WebSocketService();

export default websocketService;
