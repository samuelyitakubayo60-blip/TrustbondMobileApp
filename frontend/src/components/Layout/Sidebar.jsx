import React, { useEffect, useState } from "react";

const Sidebar = ({
  isOpen,
  currentScreen,
  onNavigate,
  sidebarCounts = {},
  user,
  onLogout,
}) => {
  const renderNavIcon = (icon) => {
    switch (icon) {
      case "ni-db":
        return (
          <svg viewBox="0 0 24 24">
            <rect x="3" y="3" width="7" height="7" />
            <rect x="14" y="3" width="7" height="7" />
            <rect x="14" y="14" width="7" height="7" />
            <rect x="3" y="14" width="7" height="7" />
          </svg>
        );
      case "ni-rp":
        return (
          <svg viewBox="0 0 24 24">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
        );
      case "ni-cm":
        return (
          <svg viewBox="0 0 24 24">
            <rect x="2" y="7" width="20" height="14" rx="2" />
            <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
          </svg>
        );
      case "ni-hs":
        return (
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4l3 3" />
          </svg>
        );
      case "ni-mp":
        return (
          <svg viewBox="0 0 24 24">
            <polygon points="3 11 22 2 13 21 11 13 3 11" />
          </svg>
        );
      case "ni-dt":
        return (
          <svg viewBox="0 0 24 24">
            <rect x="5" y="2" width="14" height="20" rx="2" />
            <path d="M12 18h.01" />
          </svg>
        );
      case "ni-us":
        return (
          <svg viewBox="0 0 24 24">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        );
      case "ni-it":
        return (
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </svg>
        );
      case "ni-st":
        return (
          <svg viewBox="0 0 24 24">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            <polyline points="9 22 9 12 15 12 15 22" />
          </svg>
        );
      case "ni-sc":
        return (
          <svg viewBox="0 0 24 24">
            <rect x="2" y="3" width="20" height="14" rx="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        );
      case "ni-al":
        return (
          <svg viewBox="0 0 24 24">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        );
      case "ni-as":
        return (
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        );
      case "ni-cp":
        return (
          <svg viewBox="0 0 24 24">
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        );
      case "ni-nt":
        return (
          <svg viewBox="0 0 24 24">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
        );
      case "ni-gi":
        return (
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" />
            <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
        );
      default:
        return (
          <svg viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="2" />
          </svg>
        );
    }
  };

  // Map detail screens back to their parent nav item for highlighting.
  const sidebarActiveScreen =
    currentScreen === "report-detail"
      ? "reports"
      : currentScreen === "hotspot-details"
        ? "safety-map"
        : currentScreen;

  const {
    reports: reportsBadge = 0,
    cases: casesBadge = 0,
    notifications: notificationsBadge = 0,
  } = sidebarCounts;

  const role = user?.role || "officer";

  const getNavigationItems = (role, reportsBadge, casesBadge) => {
    return [
      {
        section: "Overview",
        items: [
          { id: "dashboard", idx: 0, label: "Dashboard", icon: "ni-db" },
        ],
      },
      {
        section: "Operations",
        items: [
          {
            id: "reports",
            idx: 1,
            label: "Reports",
            icon: "ni-rp",
            badge: reportsBadge,
          },
          // Case Management - visible to all roles (admin, supervisor, officer)
          {
            id: "case-management",
            idx: 3,
            label: "Case Management",
            icon: "ni-cm",
            badge: casesBadge,
          },
          { id: "safety-map", idx: 5, label: "Safety Map", icon: "ni-mp" },
        ],
      },
      {
        section: "Intelligence",
        items: [
          {
            id: "device-trust",
            idx: 6,
            label: "Device Trust",
            icon: "ni-dt",
          },
        ],
      },
      {
        section: "Management",
        items: [
          ...(role === "admin"
            ? [
                { id: "users", idx: 8, label: "Users", icon: "ni-us" },
                {
                  id: "incident-types",
                  idx: 9,
                  label: "Incident Types",
                  icon: "ni-it",
                },
                { id: "stations", idx: 10, label: "Stations", icon: "ni-st" },
                {
                  id: "system-config",
                  idx: 11,
                  label: "System Config",
                  icon: "ni-sc",
                },
                { id: "audit-log", idx: 12, label: "Audit Log", icon: "ni-al" },
                {
                  id: "active-sessions",
                  idx: 14,
                  label: "Active Sessions",
                  icon: "ni-as",
                },
              ]
            : role === "supervisor"
            ? [
                { id: "users", idx: 8, label: "Users", icon: "ni-us" },
                { id: "stations", idx: 10, label: "Stations", icon: "ni-st" },
              ]
            : []),
        ],
      },
      {
        section: "Account",
      items: [
        {
          id: "change-password",
          idx: 13,
          label: "Change Password",
          icon: "ni-cp",
        },
        {
          id: "notifications",
          idx: 15,
          label: "Notifications",
          icon: "ni-nt",
          badge: notificationsBadge,
        },
      ],
    },
  ];
  };

  const allNavItems = getNavigationItems(role, reportsBadge, casesBadge);

  // Filter out sections that should be hidden from officers
  const navItems = allNavItems.filter(section => {
    if (role === "officer") {
      // Hide Management section from officers, but show Intelligence section
      return section.section !== "Management";
    }
    return true;
  });

  const activeSection = navItems.find((section) =>
    section.items.some((it) => it.id === sidebarActiveScreen),
  )?.section;

  const defaultOpenSection =
    activeSection && activeSection !== "Overview"
      ? activeSection
      : "Operations";

  const [openSection, setOpenSection] = useState(
    role === "admin" || role === "supervisor" ? ["Operations", "Intelligence"] : [defaultOpenSection]
  );

  useEffect(() => {
    setOpenSection(defaultOpenSection);
  }, [defaultOpenSection]);

  const toggleSection = (sectionName) => {
    setOpenSection(prev => {
      if (Array.isArray(prev)) {
        return prev.includes(sectionName) 
          ? prev.filter(s => s !== sectionName)
          : [...prev, sectionName];
      }
      return prev === sectionName ? null : sectionName;
    });
  };

  return (
    <aside id="sidebar" className={isOpen ? "open" : ""}>
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon" aria-hidden="true">
          <img src="/logo.jpeg" alt="TrustBond logo" />
        </div>
        <div className="sidebar-brand-copy">
          <div className="sidebar-brand-name">TrustBond</div>
          <div className="sidebar-brand-sub">Police Portal</div>
        </div>
      </div>

      <nav>
        <div
          className={`nav-item ${sidebarActiveScreen === "dashboard" ? "active" : ""}`}
          id="nav-0"
          onClick={() => onNavigate("dashboard", 0)}
        >
          <span className="nav-icon ni-db">{renderNavIcon("ni-db")}</span>
          <span className="nav-text">Dashboard</span>
        </div>

        <div className="nav-divider" />

        {navItems
          .filter((section) => section.section !== "Overview")
          .map((section, idx) => (
            <div className="nav-section" key={idx}>
              {section.section === "Account" && <div className="nav-divider" />}
              <div
                className={`nav-label nav-section-toggle ${
                  Array.isArray(openSection) 
                    ? openSection.includes(section.section) 
                    : openSection === section.section ? "open" : ""
                }`}
                role="button"
                tabIndex={0}
                onClick={() => {
                  if (section.items.length > 1 || section.section === "Intelligence") toggleSection(section.section);
                }}
                onKeyDown={(e) => {
                  if (section.items.length <= 1 && section.section !== "Intelligence") return;
                  if (e.key === "Enter" || e.key === " ")
                    toggleSection(section.section);
                }}
                aria-expanded={
                  section.items.length <= 1
                    ? true
                    : Array.isArray(openSection) 
                      ? openSection.includes(section.section)
                      : openSection === section.section
                }
              >
                <span>{section.section}</span>
                {(section.items.length > 1 || section.section === "Intelligence") && (
                  <span className="nav-chevron" aria-hidden="true">
                    {Array.isArray(openSection) 
                      ? (openSection.includes(section.section) ? "▾" : "▸")
                      : (openSection === section.section ? "▾" : "▸")
                    }
                  </span>
                )}
              </div>

              {(section.items.length <= 1 || 
                (Array.isArray(openSection) 
                  ? openSection.includes(section.section) 
                  : openSection === section.section)) &&
                section.items.map((item) => (
                  <div
                    key={item.id}
                    className={`nav-item ${sidebarActiveScreen === item.id ? "active" : ""}`}
                    id={`nav-${item.idx}`}
                    onClick={() => onNavigate(item.id, item.idx)}
                  >
                    <span className={`nav-icon ${item.icon}`}>
                      {renderNavIcon(item.icon)}
                    </span>
                    <span className="nav-text">{item.label}</span>
                    {item.badge && (
                      <span className="nav-badge">{item.badge}</span>
                    )}
                  </div>
                ))}
            </div>
          ))}
      </nav>

      <div className="sidebar-footer">
        <div className="user-card">
          <div className="avatar">
            {user?.first_name?.[0]?.toUpperCase() || "U"}
          </div>
          <div style={{ overflow: "hidden" }}>
            <div className="user-name">
              {user ? `${user.first_name} ${user.last_name}` : "User"}
            </div>
            <div className="user-role">
              {role === "admin"
                ? "Administrator"
                : role === "supervisor"
                  ? "Supervisor"
                  : "Officer"}
            </div>
          </div>
        </div>
        <button type="button" className="sidebar-signout" onClick={onLogout}>
          <i className="fa fa-sign-out" aria-hidden="true"></i>
          Sign out
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
