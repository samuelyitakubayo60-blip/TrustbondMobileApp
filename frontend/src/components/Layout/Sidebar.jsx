import React from 'react';

const Sidebar = ({ isOpen, currentScreen, onNavigate, sidebarCounts = {}, user }) => {
  const {
    reports: reportsBadge = 0,
    cases: casesBadge = 0,
    notifications: notificationsBadge = 0,
  } = sidebarCounts;

  const role = user?.role || 'officer';

  const navItems = [
    { section: 'Overview', items: [
      { id: 'dashboard', idx: 0, label: 'Dashboard', icon: 'ni-db' }
    ]},
    { section: 'Operations', items: [
      { id: 'reports', idx: 1, label: 'Reports', icon: 'ni-rp', badge: reportsBadge },
      { id: 'report-detail', idx: 2, label: 'Report Detail', icon: 'ni-rd' },
      { id: 'case-management', idx: 3, label: 'Case Management', icon: 'ni-cm', badge: casesBadge },
      { id: 'hotspots', idx: 4, label: 'Hotspots', icon: 'ni-hs' },
      { id: 'safety-map', idx: 5, label: 'Safety Map', icon: 'ni-mp' }
    ]},
    { section: 'Intelligence', items: [
      // Device trust analytics – mostly for admin / analysts; keep visible for all for now
      { id: 'device-trust', idx: 6, label: 'Device Trust', icon: 'ni-dt' }
    ]},
    { section: 'Management', items: [
      ...(role === 'admin'
        ? [
            { id: 'users', idx: 7, label: 'Users', icon: 'ni-us' },
            { id: 'incident-types', idx: 8, label: 'Incident Types', icon: 'ni-it' },
            { id: 'stations', idx: 9, label: 'Stations', icon: 'ni-it' },
            { id: 'system-config', idx: 10, label: 'System Config', icon: 'ni-dt' },
            { id: 'audit-log', idx: 11, label: 'Audit Log', icon: 'ni-al' },
          ]
        : role === 'supervisor'
          ? [
              { id: 'users', idx: 7, label: 'Users', icon: 'ni-us' },
              { id: 'stations', idx: 9, label: 'Stations', icon: 'ni-it' },
            ]
          : []),
    ]},
    { section: 'Account', items: [
      { id: 'change-password', idx: 11, label: 'Change Password', icon: 'ni-cp' },
      { id: 'notifications', idx: 12, label: 'Notifications', icon: 'ni-nt', badge: notificationsBadge }
    ]}
  ];

  return (
    <aside id="sidebar" className={isOpen ? 'open' : ''}>
      <div className="sidebar-logo">
        <div className="logo-icon">TB</div>
        <div>
          <div className="logo-text">TrustBond</div>
          <div className="logo-sub">Police Portal</div>
        </div>
      </div>
      
      <nav>
        {navItems.map((section, idx) => (
          <div className="nav-section" key={idx}>
            <div className="nav-label">{section.section}</div>
            {section.items.map(item => (
              <div
                key={item.id}
                className={`nav-item ${currentScreen === item.id ? 'active' : ''}`}
                id={`nav-${item.idx}`}
                onClick={() => onNavigate(item.id, item.idx)}
              >
                <span className={`nav-icon ${item.icon}`}></span>
                <span className="nav-text">{item.label}</span>
                {item.badge && <span className="nav-badge">{item.badge}</span>}
              </div>
            ))}
          </div>
        ))}
      </nav>
      
      <div className="sidebar-footer">
        <div className="user-card">
          <div className="avatar">
            {user?.first_name?.[0]?.toUpperCase() || 'U'}
          </div>
          <div style={{ overflow: 'hidden' }}>
            <div className="user-name">
              {user ? `${user.first_name} ${user.last_name}` : 'User'}
            </div>
            <div className="user-role">
              {role === 'admin' ? 'Administrator' : role === 'supervisor' ? 'Supervisor' : 'Officer'}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;