import { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import './Layout.css';

export default function Layout({ children }) {
  const { user, logout, isAdmin, canManageUsers, canSeeHotspots, canSeeAudit, isOfficer } = useAuth();
  const canManageIncidentTypes = isAdmin;
  const location = useLocation();
  const navigate = useNavigate();
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const notifRef = useRef(null);

  useEffect(() => {
    apiService.getUnreadNotificationCount().then((r) => setUnreadCount(r.unread_count ?? 0)).catch(() => {});
  }, []);

  useEffect(() => {
    if (notifOpen) {
      apiService.getNotifications({ limit: 20 }).then((list) => setNotifications(Array.isArray(list) ? list : [])).catch(() => setNotifications([]));
    }
  }, [notifOpen]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (notifRef.current && !notifRef.current.contains(e.target)) setNotifOpen(false);
    }
    if (notifOpen) document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, [notifOpen]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleMarkRead = async (id) => {
    try {
      await apiService.markNotificationRead(id);
      setUnreadCount((c) => Math.max(0, c - 1));
      setNotifications((prev) => prev.map((n) => (n.notification_id === id ? { ...n, is_read: true } : n)));
    } catch (_) {}
  };

  function formatDate(s) {
    if (!s) return '';
    return new Date(s).toLocaleString();
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <img src="/logo.jpeg" alt="TrustBond" className="logo-img" />
            <h2>TrustBond</h2>
          </div>
          <p className="user-info">{user?.first_name} {user?.last_name}</p>
          <p className="user-role">{user?.role}</p>
        </div>
        <nav className="sidebar-nav">
          <Link
            to="/dashboard"
            className={location.pathname === '/dashboard' ? 'active' : ''}
          >
            Dashboard
          </Link>
          <Link
            to="/reports"
            className={location.pathname.startsWith('/reports') ? 'active' : ''}
          >
            {isOfficer ? 'My assignments' : 'Reports'}
          </Link>
          {canManageUsers && (
            <Link
              to="/users"
              className={location.pathname.startsWith('/users') ? 'active' : ''}
            >
              Users
            </Link>
          )}
          {canManageIncidentTypes && (
            <Link
              to="/incident-types"
              className={location.pathname.startsWith('/incident-types') ? 'active' : ''}
            >
              Incident types
            </Link>
          )}
          {canSeeHotspots && (
            <Link
              to="/hotspots"
              className={location.pathname.startsWith('/hotspots') ? 'active' : ''}
            >
              Hotspots
            </Link>
          )}
          {canSeeAudit && (
            <Link
              to="/audit"
              className={location.pathname.startsWith('/audit') ? 'active' : ''}
            >
              Audit log
            </Link>
          )}
          <Link
            to="/change-password"
            className={location.pathname === '/change-password' ? 'active' : ''}
          >
            Change password
          </Link>
        </nav>
      </aside>
      <main className="main-content">
        <header className="top-bar">
          <h1>Police Dashboard</h1>
          <div className="top-bar-actions" ref={notifRef}>
            <button
              type="button"
              className="notif-button"
              onClick={() => setNotifOpen((o) => !o)}
              aria-label="Notifications"
            >
              <span className="notif-icon">🔔</span>
              {unreadCount > 0 && <span className="notif-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>}
            </button>
            {notifOpen && (
              <div className="notif-dropdown">
                <div className="notif-dropdown-header">Notifications</div>
                {notifications.length === 0 ? (
                  <div className="notif-empty">No notifications</div>
                ) : (
                  <ul className="notif-list">
                    {notifications.map((n) => (
                      <li
                        key={n.notification_id}
                        className={n.is_read ? 'notif-item read' : 'notif-item'}
                        onClick={() => {
                          if (!n.is_read) handleMarkRead(n.notification_id);
                          if (n.related_entity_type === 'report' && n.related_entity_id) {
                            navigate(`/reports/${n.related_entity_id}`);
                            setNotifOpen(false);
                          }
                        }}
                      >
                        <span className="notif-title">{n.title}</span>
                        {n.message && <span className="notif-message">{n.message}</span>}
                        <span className="notif-date">{formatDate(n.created_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <button onClick={handleLogout} className="topbar-logout-button">
              Logout
            </button>
          </div>
        </header>
        <div className="content">{children}</div>
      </main>
    </div>
  );
}
