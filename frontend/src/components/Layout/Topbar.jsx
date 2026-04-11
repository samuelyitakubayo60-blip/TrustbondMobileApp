import React, { useState, useEffect } from "react";
import websocketService from "../../services/websocketService";
import api from "../../api/client";

const Topbar = ({
  currentScreen,
  titles,
  isLightMode,
  toggleMode,
  toggleSidebar,
  goToScreen,
  onLogout,
}) => {
  const [notificationCount, setNotificationCount] = useState(0);
  const [navigationPath, setNavigationPath] = useState([]);
  const [isMobile, setIsMobile] = useState(false);

  const getCurrentDate = () => {
    const date = new Date();
    return date
      .toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
      .replace(",", "");
  };

  // Check if mobile on mount and resize
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // Define navigation hierarchy
  const getNavigationHierarchy = (screenId) => {
    const hierarchy = {
      dashboard: [],
      reports: [{ id: "dashboard", label: "Home" }],
      "report-detail": [
        { id: "dashboard", label: "Home" },
        { id: "reports", label: "Reports" }
      ],
      "case-management": [{ id: "dashboard", label: "Home" }],
      "safety-map": [{ id: "dashboard", label: "Home" }],
      "hotspot-details": [
        { id: "dashboard", label: "Home" },
        { id: "safety-map", label: "Safety Map" }
      ],
      "device-trust": [{ id: "dashboard", label: "Home" }],
      users: [{ id: "dashboard", label: "Home" }],
      "incident-types": [{ id: "dashboard", label: "Home" }],
      stations: [{ id: "dashboard", label: "Home" }],
      "audit-log": [{ id: "dashboard", label: "Home" }],
      "system-config": [{ id: "dashboard", label: "Home" }],
      "active-sessions": [{ id: "dashboard", label: "Home" }],
      notifications: [{ id: "dashboard", label: "Home" }],
      "change-password": [{ id: "dashboard", label: "Home" }],
    };
    return hierarchy[screenId] || [];
  };

  // Update navigation path when screen changes
  useEffect(() => {
    const screenId = typeof currentScreen === 'string' ? currentScreen : currentScreen.id;
    const path = getNavigationHierarchy(screenId);
    setNavigationPath(path);
  }, [currentScreen]);

  // Fetch notification count from API
  const fetchNotificationCount = async () => {
    try {
      const response = await api.get("/api/v1/notifications/unread-count");
      const unreadCount = response?.unread_count || 0;
      setNotificationCount(unreadCount);
    } catch (error) {
      console.error("Failed to fetch notification count:", error);
      // Fallback to fetching all notifications if the dedicated endpoint fails
      try {
        const notifications = await api.get("/api/v1/notifications?limit=50");
        const unreadCount = (notifications || []).filter(
          (n) => !n.is_read,
        ).length;
        setNotificationCount(unreadCount);
      } catch (fallbackError) {
        console.error(
          "Failed to fetch notifications as fallback:",
          fallbackError,
        );
        setNotificationCount(0);
      }
    }
  };

  // Initialize WebSocket connection and fetch initial count
  useEffect(() => {
    // Get token from localStorage
    const token = localStorage.getItem("access_token");

    // Fetch initial count (async from effect to avoid sync state updates)
    const warmNotificationCount = async () => {
      await fetchNotificationCount();
    };
    void warmNotificationCount();

    // Connect to WebSocket for real-time updates
    if (token) {
      websocketService.connect(token);

      // Listen for notification count updates
      const handleNotificationCount = (count) => {
        setNotificationCount(count);
      };

      const handleNewNotification = () => {
        // When new notification arrives, refresh count from API
        fetchNotificationCount();
      };

      const handleCountUpdateNeeded = () => {
        // When count was updated (e.g., notification marked as read), refresh from API
        fetchNotificationCount();
      };

      websocketService.on("notificationCount", handleNotificationCount);
      websocketService.on("newNotification", handleNewNotification);
      websocketService.on("countUpdateNeeded", handleCountUpdateNeeded);

      // Cleanup on unmount
      return () => {
        websocketService.off("notificationCount", handleNotificationCount);
        websocketService.off("newNotification", handleNewNotification);
        websocketService.off("countUpdateNeeded", handleCountUpdateNeeded);
      };
    }
  }, []);

  // Refresh count when returning from notifications page
  useEffect(() => {
    if (currentScreen !== "notifications") {
      const refreshNotificationCount = async () => {
        await fetchNotificationCount();
      };
      void refreshNotificationCount();
    }
  }, [currentScreen]);

  return (
    <>
      {/* Main Topbar - shows on all screens */}
      <header id="topbar">
        <div className="topbar-main">
          <div id="hamburger" onClick={toggleSidebar}>
            ☰
          </div>

          {/* Desktop: Breadcrumbs | Mobile: Screen Name */}
          <div className="topbar-center">
            {isMobile ? (
              <div className="tb-mobile-page-title">
                {titles[typeof currentScreen === 'string' ? currentScreen : currentScreen.id] || "Dashboard"}
              </div>
            ) : (
              <div className="tb-context">
                <nav className="tb-breadcrumb" aria-label="Breadcrumb">
                  {/* Render navigation path */}
                  {navigationPath.map((item, index) => (
                    <React.Fragment key={item.id}>
                      <button
                        type="button"
                        className="tb-breadcrumb-link"
                        onClick={() => goToScreen(item.id, index)}
                      >
                        {item.label}
                      </button>
                      <span className="tb-breadcrumb-sep">›</span>
                    </React.Fragment>
                  ))}
                  
                  {/* Current page (not clickable) */}
                  <span className="tb-breadcrumb-current">
                    {titles[typeof currentScreen === 'string' ? currentScreen : currentScreen.id] || "Dashboard"}
                  </span>
                </nav>
              </div>
            )}
          </div>

          {/* Desktop: Full controls | Mobile: Minimal controls */}
          <div className="topbar-right">
            {!isMobile && (
              <>
                <div className="tb-status-pill" title="All systems operational">
                  <span className="tb-status-dot"></span>
                  Operational
                </div>

                <div className="tb-chip tb-date-chip">{getCurrentDate()}</div>

                <button id="modeToggle" onClick={toggleMode}>
                  {isLightMode ? "Dark Mode" : "Light Mode"}
                </button>
              </>
            )}

            <button
              type="button"
              className="tb-icon-btn tb-notification-btn"
              onClick={() => goToScreen("notifications", 11)}
              title="Notifications"
              aria-label="Notifications"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              {notificationCount > 0 && (
                <span className="tb-icon-btn-badge tb-icon-btn-badge--active"></span>
              )}
            </button>

            <button
              type="button"
              className="tb-icon-btn tb-theme-btn--mobile"
              onClick={toggleMode}
              title={isLightMode ? "Switch to dark mode" : "Switch to light mode"}
              aria-label={isLightMode ? "Switch to dark mode" : "Switch to light mode"}
            >
              {isLightMode ? "🌙" : "☀"}
            </button>

            <button
              type="button"
              className="tb-logout-btn tb-logout-btn--mobile"
              onClick={onLogout}
              title="Sign out"
              aria-label="Sign out"
            >
              <i className="fa fa-sign-out" aria-hidden="true"></i>
            </button>
          </div>
        </div>
      </header>

      {/* Mobile Controls Area - where page header used to be */}
      {isMobile && (
        <div className="tb-mobile-controls">
          <div className="tb-mobile-controls-content">
            <div className="tb-status-pill" title="All systems operational">
              <span className="tb-status-dot"></span>
              Operational
            </div>

            <div className="tb-chip tb-date-chip">{getCurrentDate()}</div>

            <button id="modeToggle" onClick={toggleMode}>
              {isLightMode ? "Dark Mode" : "Light Mode"}
            </button>
          </div>
        </div>
      )}
    </>
  );
};

export default Topbar;
