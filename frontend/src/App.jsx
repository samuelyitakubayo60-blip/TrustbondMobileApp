import React, { useState, useEffect } from "react";
import Layout from "./components/Layout/Layout";
import Dashboard from "./components/screens/Dashboard";
import Reports from "./components/screens/Reports";
import ReportDetail from "./components/screens/ReportDetail";
import CaseManagement from "./components/screens/CaseManagement";
import HotspotDetails from "./components/screens/HotspotDetails";
import SafetyMap from "./components/screens/SafetyMap";
import DeviceTrust from "./components/screens/DeviceTrust";
import GeographicIntelligence from "./components/screens/GeographicIntelligence";
import EnhancedGeographicIntelligence from "./components/screens/EnhancedGeographicIntelligence";
import Users from "./components/screens/Users";
import IncidentTypes from "./components/screens/IncidentTypes";
import Stations from "./components/screens/Stations";
import AuditLog from "./components/screens/AuditLog";
import SystemConfig from "./components/screens/SystemConfig";
import ActiveSessions from "./components/screens/ActiveSessions";
import ChangePassword from "./components/screens/ChangePassword";
import Notifications from "./components/screens/Notifications";
import Login from "./components/screens/Login";
import ForgotPassword from "./components/screens/ForgotPassword";
import ResetPassword from "./components/screens/ResetPassword";
import { useAuth } from "./context/AuthContext";
import { useRealtime } from "./context/WebSocketContext";
import AddUserModal from "./components/Modals/AddUserModal";
import EditUserModal from "./components/Modals/EditUserModal";
import AssignModal from "./components/Modals/AssignModal";
import AddIncidentModal from "./components/Modals/AddIncidentModal";
import NewCaseModal from "./components/Modals/NewCaseModal";
import LinkCaseModal from "./components/Modals/LinkCaseModal";
import StationModal from "./components/Modals/StationModal";
import StationDetailModal from "./components/Modals/StationDetailModal";
import api from "./api/client";

function App() {
  const { user, loading, logout } = useAuth();
  const { refreshKey: wsRefreshKey } = useRealtime();
  const initialReportId = (() => {
    if (typeof window === "undefined") return null;
    const path = window.location.pathname || "/";
    if (path.startsWith("/reports/") && path !== "/reports" && path !== "/reports/detail") {
      const parts = path.split("/");
      return parts[2] || null;
    }
    return null;
  })();
  const [currentScreen, setCurrentScreen] = useState(() => {
    if (typeof window === "undefined") return "dashboard";
    const path = window.location.pathname || "/";
    if (path.startsWith("/hotspots/")) return "hotspot-details";
    if (path.startsWith("/reports/") && path !== "/reports" && path !== "/reports/detail") {
      return "report-detail";
    }
    switch (path) {
      case "/":
        return "dashboard";
      case "/reports":
        return "reports";
      case "/reports/detail":
        return "report-detail";
      case "/cases":
        return "case-management";
      case "/hotspots":
        return "safety-map"; // Redirect to safety-map
      case "/safety-map":
        return "safety-map";
      case "/device-trust":
        return "device-trust";
      case "/geographic-intelligence":
        return "geographic-intelligence";
      case "/users":
        return "users";
      case "/incident-types":
        return "incident-types";
      case "/stations":
        return "stations";
      case "/audit-log":
        return "audit-log";
      case "/system-config":
        return "system-config";
      case "/active-sessions":
        return "active-sessions";
      case "/notifications":
        return "notifications";
      case "/change-password":
        return "change-password";
      default:
        return "dashboard";
    }
  });
  const [isLightMode, setIsLightMode] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("tb-mode") === "light";
  });
  const [selectedReportId, setSelectedReportId] = useState(initialReportId);
  const [selectedHotspotId, setSelectedHotspotId] = useState(null);
  const [selectedIncidentType, setSelectedIncidentType] = useState(null);
  const [selectedStation, setSelectedStation] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [incidentTypesRefreshKey, setIncidentTypesRefreshKey] = useState(0);
  const [usersRefreshKey, setUsersRefreshKey] = useState(0);
  const [sidebarCounts, setSidebarCounts] = useState({
    reports: 0,
    cases: 0,
    notifications: 0,
  });
  const [modals, setModals] = useState({
    addUser: false,
    editUser: false,
    assign: false,
    addIncident: false,
    editIncident: false,
    addStation: false,
    editStation: false,
    newCase: false,
    linkCase: false,
  });
  const [authScreen, setAuthScreen] = useState("login"); // login | forgot | reset
  const [resetEmail, setResetEmail] = useState("");

  // Map screen/auth IDs to URL paths so the browser bar updates.
  const screenToPath = (screenId, props = {}) => {
    switch (screenId) {
      case "dashboard":
        return "/";
      case "reports":
        return "/reports";
      case "report-detail":
        {
          const rid = props?.reportId || selectedReportId;
          return rid ? `/reports/${rid}` : "/reports";
        }
      case "case-management":
        return "/cases";
      case "hotspot-details":
        // Use the hotspotId from the new props or selectedHotspotId to construct URL
        const hotspotId = props?.hotspotId || selectedHotspotId;
        return hotspotId ? `/hotspots/${hotspotId}` : "/safety-map";
      case "safety-map":
        return "/safety-map";
      case "device-trust":
        return "/device-trust";
      case "users":
        return "/users";
      case "incident-types":
        return "/incident-types";
      case "stations":
        return "/stations";
      case "audit-log":
        return "/audit-log";
      case "system-config":
        return "/system-config";
      case "change-password":
        return "/change-password";
      case "notifications":
        return "/notifications";
      case "active-sessions":
        return "/active-sessions";
      default:
        return "/";
    }
  };

  const pathToScreen = (path) => {
    // Handle hotspot details routes first (more specific)
    if (path.startsWith("/hotspots/")) {
      const parts = path.split("/");
      if (parts.length === 3 && parts[2]) {
        setSelectedHotspotId(parts[2]);
        return "hotspot-details";
      }
    }
    if (path.startsWith("/reports/") && path !== "/reports" && path !== "/reports/detail") {
      const parts = path.split("/");
      const rid = parts[2];
      if (rid) setSelectedReportId(rid);
      return "report-detail";
    }

    switch (path) {
      case "/":
        return "dashboard";
      case "/reports":
        return "reports";
      case "/reports/detail":
        return "report-detail";
      case "/cases":
        return "case-management";
      case "/hotspots":
        return "safety-map"; // Redirect to safety-map
      case "/safety-map":
        return "safety-map";
      case "/device-trust":
        return "device-trust";
      case "/users":
        return "users";
      case "/incident-types":
        return "incident-types";
      case "/stations":
        return "stations";
      case "/audit-log":
        return "audit-log";
      case "/system-config":
        return "system-config";
      case "/active-sessions":
        return "active-sessions";
      case "/notifications":
        return "notifications";
      case "/change-password":
        return "change-password";
      default:
        return "dashboard";
    }
  };

  const authToPath = (screen) => {
    switch (screen) {
      case "forgot":
        return "/forgot-password";
      case "reset":
        return "/reset-password";
      case "login":
      default:
        return "/login";
    }
  };

  const pathToAuth = (path) => {
    switch (path) {
      case "/forgot-password":
        return "forgot";
      case "/reset-password":
        return "reset";
      case "/login":
      default:
        return "login";
    }
  };

  const titles = {
    dashboard: "Dashboard",
    reports: "Reports",
    "report-detail": selectedReportId
      ? `Report Detail — ${String(selectedReportId).slice(0, 8)}`
      : "Report Detail",
    "case-management": "Case Management",
    "hotspot-details": "Hotspot Details",
    hotspots: "Crime Hotspots",
    "safety-map": "Safety Map",
    "device-trust": "Device Trust Management",
    users: "User Management",
    "incident-types": "Incident Types",
    "audit-log": "Audit Log",
    "system-config": "System Configuration",
    "change-password": "Change Password",
    notifications: "Notifications",
    "active-sessions": "Active Sessions",
  };

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.body.classList.toggle("light-mode", isLightMode);
  }, [isLightMode]);

  // Initialise screen/auth state from the current URL.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const path = window.location.pathname || "/";
    if (user) {
      setCurrentScreen(pathToScreen(path));
    } else {
      setAuthScreen(pathToAuth(path));
    }

    const handlePopState = () => {
      const newPath = window.location.pathname || "/";
      if (user) {
        setCurrentScreen(pathToScreen(newPath));
      } else {
        setAuthScreen(pathToAuth(newPath));
      }
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [user]);

  const toggleMode = () => {
    const newMode = !isLightMode;
    setIsLightMode(newMode);
    localStorage.setItem("tb-mode", newMode ? "light" : "dark");
  };

  // Load sidebar badge counts (reports, cases, notifications)
  useEffect(() => {
    if (!user) return;

    let cancelled = false;

    const loadCounts = async () => {
      try {
        const dash = await api.get("/api/v1/stats/dashboard");
        let caseStats = null;
        let notif = null;
        try {
          caseStats = await api.get("/api/v1/cases/stats");
        } catch {
          caseStats = null;
        }
        try {
          notif = await api.get("/api/v1/notifications/unread-count");
        } catch {
          notif = null;
        }
        if (cancelled) return;
        setSidebarCounts({
          // Sidebar badges should reflect totals (matches Reports screen header).
          reports: dash?.total_reports ?? 0,
          cases: caseStats
            ? (caseStats?.open ?? 0) + (caseStats?.in_progress ?? 0) + (caseStats?.closed ?? 0)
            : (dash?.total_cases ?? dash?.open_cases ?? 0),
          notifications: notif?.unread_count ?? 0,
        });
      } catch {
        if (cancelled) return;
        setSidebarCounts((prev) => ({ ...prev }));
      }
    };

    loadCounts();
    // Optional fallback interval
    const id = setInterval(loadCounts, 60000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [user, wsRefreshKey]);

  const goToScreen = (id, idx, props = {}) => {
    // Handle both string and object formats for consistency
    const screenState = typeof id === "string" ? { id, props } : id;
    setCurrentScreen(screenState);

    if (typeof window !== "undefined") {
      const path = screenToPath(screenState.id, screenState.props);
      window.history.pushState(null, "", path);
    }
  };

  const handleOpenReport = (reportId) => {
    setSelectedReportId(reportId);
    goToScreen("report-detail", 0, { reportId });
  };

  const openModal = (modalName) => {
    if (modalName === "addIncident") setSelectedIncidentType(null);
    if (modalName === "addStation") setSelectedStation(null);
    setModals((prev) => ({ ...prev, [modalName]: true }));
  };

  const closeModal = (modalName) => {
    setModals((prev) => ({ ...prev, [modalName]: false }));
  };

  // Render current screen
  const renderScreen = () => {
    const screenId =
      typeof currentScreen === "string" ? currentScreen : currentScreen.id;

    switch (screenId) {
      case "dashboard":
        return (
          <Dashboard
            goToScreen={goToScreen}
            openModal={openModal}
            onOpenReport={handleOpenReport}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "reports":
        return (
          <Reports
            goToScreen={goToScreen}
            openModal={openModal}
            onOpenReport={handleOpenReport}
            wsRefreshKey={wsRefreshKey}
            initialStatusFilter={
              currentScreen.props?.initialStatusFilter || "all"
            }
          />
        );
      case "report-detail":
        return (
          <ReportDetail
            goToScreen={goToScreen}
            openModal={openModal}
            reportId={selectedReportId}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "case-management":
        return (
          <CaseManagement
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "hotspot-details":
        return (
          <HotspotDetails
            hotspotId={currentScreen.props?.hotspotId || selectedHotspotId}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "safety-map":
        return (
          <SafetyMap
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "device-trust":
        return (
          <DeviceTrust
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "geographic-intelligence":
        return (
          <GeographicIntelligence
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "users":
        return (
          <Users
            goToScreen={goToScreen}
            openModal={openModal}
            refreshKey={usersRefreshKey}
            wsRefreshKey={wsRefreshKey}
            onEditUser={(u) => {
              setSelectedUser(u);
              openModal("editUser");
            }}
          />
        );
      case "incident-types":
        return (
          <IncidentTypes
            goToScreen={goToScreen}
            openModal={openModal}
            refreshKey={incidentTypesRefreshKey}
            wsRefreshKey={wsRefreshKey}
            onEditIncidentType={(t) => {
              setSelectedIncidentType(t);
              openModal("editIncident");
            }}
          />
        );
      case "stations":
        return (
          <Stations
            goToScreen={goToScreen}
            wsRefreshKey={wsRefreshKey}
            openModal={(name, payload) => {
              if (name === "editStation") {
                setSelectedStation(payload || null);
              }
              openModal(name);
            }}
          />
        );
      case "audit-log":
        return (
          <AuditLog
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "system-config":
        return (
          <SystemConfig
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "change-password":
        return <ChangePassword goToScreen={goToScreen} openModal={openModal} />;
      case "notifications":
        return (
          <Notifications
            goToScreen={goToScreen}
            openModal={openModal}
            onOpenReport={handleOpenReport}
            wsRefreshKey={wsRefreshKey}
          />
        );
      case "active-sessions":
        return (
          <ActiveSessions
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
      default:
        return (
          <Dashboard
            goToScreen={goToScreen}
            openModal={openModal}
            wsRefreshKey={wsRefreshKey}
          />
        );
    }
  };

  if (loading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "var(--bg)",
          color: "var(--text)",
          fontFamily: "'DM Sans', sans-serif",
          fontSize: 14,
        }}
      >
        Loading your dashboard...
      </div>
    );
  }

  if (!user) {
    if (authScreen === "forgot") {
      return (
        <ForgotPassword
          onBack={() => {
            setAuthScreen("login");
            if (typeof window !== "undefined") {
              window.history.pushState(null, "", authToPath("login"));
            }
          }}
          onCodeSent={(email) => {
            setResetEmail(email);
            setAuthScreen("reset");
            if (typeof window !== "undefined") {
              window.history.pushState(null, "", authToPath("reset"));
            }
          }}
        />
      );
    }
    if (authScreen === "reset") {
      return (
        <ResetPassword
          email={resetEmail}
          onBackToLogin={() => {
            setAuthScreen("login");
            if (typeof window !== "undefined") {
              window.history.pushState(null, "", authToPath("login"));
            }
          }}
        />
      );
    }
    return (
      <Login
        onForgotPassword={() => {
          setAuthScreen("forgot");
          if (typeof window !== "undefined") {
            window.history.pushState(null, "", authToPath("forgot"));
          }
        }}
      />
    );
  }

  return (
    <>
      <Layout
        currentScreen={currentScreen}
        titles={titles}
        isLightMode={isLightMode}
        toggleMode={toggleMode}
        goToScreen={goToScreen}
        user={user}
        onLogout={logout}
        sidebarCounts={sidebarCounts}
      >
        {renderScreen()}
      </Layout>

      {/* Modals */}
      <AddUserModal
        isOpen={modals.addUser}
        onClose={() => closeModal("addUser")}
        onSaved={() => setUsersRefreshKey((k) => k + 1)}
      />
      <EditUserModal
        isOpen={modals.editUser}
        onClose={() => closeModal("editUser")}
        user={selectedUser}
        onSaved={() => setUsersRefreshKey((k) => k + 1)}
      />
      <AssignModal
        isOpen={modals.assign}
        onClose={() => closeModal("assign")}
        reportId={selectedReportId}
        onAssigned={() => {
          // after assignment, re-open report detail to refresh view
          if (selectedReportId) {
            setCurrentScreen("report-detail");
          }
        }}
      />
      <AddIncidentModal
        isOpen={modals.addIncident}
        onClose={() => closeModal("addIncident")}
        mode="add"
        incidentType={null}
        onSaved={() => setIncidentTypesRefreshKey((k) => k + 1)}
      />
      <AddIncidentModal
        isOpen={modals.editIncident}
        onClose={() => closeModal("editIncident")}
        mode="edit"
        incidentType={selectedIncidentType}
        onSaved={() => setIncidentTypesRefreshKey((k) => k + 1)}
      />
      <NewCaseModal
        isOpen={modals.newCase}
        onClose={() => closeModal("newCase")}
        initialReportId={selectedReportId}
        onCreated={() => {
          // simple approach: reload case list by returning to screen
          setCurrentScreen("dashboard");
          setTimeout(() => setCurrentScreen("case-management"), 0);
        }}
      />
      <LinkCaseModal
        isOpen={modals.linkCase}
        onClose={() => closeModal("linkCase")}
        reportId={selectedReportId}
        onLinked={() => {
          // stay on report detail; could add toast later
        }}
      />
      <StationModal
        isOpen={modals.addStation}
        onClose={() => closeModal("addStation")}
        mode="add"
        station={null}
        onSaved={() => {
          // force reload when coming back to Stations; simplest is full reload
          if (currentScreen === "stations") {
            setCurrentScreen("dashboard");
            setTimeout(() => setCurrentScreen("stations"), 0);
          }
        }}
      />
      <StationModal
        isOpen={modals.editStation}
        onClose={() => closeModal("editStation")}
        mode="edit"
        station={selectedStation}
        onSaved={() => {
          if (currentScreen === "stations") {
            setCurrentScreen("dashboard");
            setTimeout(() => setCurrentScreen("stations"), 0);
          }
        }}
      />
      <StationDetailModal
        isOpen={modals.viewStation}
        onClose={() => closeModal("viewStation")}
        station={selectedStation}
      />
    </>
  );
}

export default App;
