import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Notifications = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState('all');
  const [searchText, setSearchText] = useState('');

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/notifications?limit=50')
      .then((res) => { if (mounted) { setItems(res || []); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const unread = items.filter(n => !n.is_read).length;
  const filtered = items.filter((n) => {
    if (filterType !== 'all' && n.type !== filterType) return false;
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const blob = [
        n.title,
        n.message,
        n.type,
        n.related_entity_type,
        n.related_entity_id,
      ]
        .join(' ')
        .toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  });

  const markAllRead = async () => {
    try {
      const unreadItems = items.filter((n) => !n.is_read);
      await Promise.all(
        unreadItems.map((n) =>
          api.patch(`/api/v1/notifications/${n.notification_id}/read`)
        )
      );
      const refreshed = await api.get('/api/v1/notifications?limit=50');
      setItems(refreshed || []);
    } catch {
      // ignore
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>Notifications</h2>
        <p>System alerts, hotspot escalations, and high-priority report notifications.</p>
      </div>

      <div className="g2-fixed">
        <div className="card">
          <div className="card-header">
            <div className="card-title">All Notifications</div>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button
                className="btn btn-outline btn-sm"
                type="button"
                onClick={markAllRead}
              >
                Mark all read
              </button>
            </div>
          </div>

          <div className="filter-row" style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)' }}>
            <input
              className="input"
              placeholder="Search title, message, or entity..."
              style={{ flex: 2, minWidth: '140px' }}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
            <select
              className="select"
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
            >
              <option value="all">All Types</option>
              <option value="report">Report</option>
              <option value="assignment">Assignment</option>
              <option value="hotspot">Hotspot</option>
              <option value="system">System</option>
            </select>
          </div>

          {filtered.map((n) => (
            <div className="notif-item" key={n.notification_id}>
              <div className="notif-icon" style={{ background: 'rgba(79, 142, 247, 0.18)' }}>
                {n.type?.toUpperCase().slice(0, 4) || 'INFO'}
              </div>
              <div className="notif-body">
                <div className="notif-title">{n.title}</div>
                <div className="notif-desc">{n.message}</div>
                <div className="notif-time">
                  {n.created_at ? new Date(n.created_at).toLocaleString() : '—'} · {n.is_read ? 'Read' : 'Unread'}
                </div>
              </div>
              <div style={{ flexShrink: 0 }}>
                <span className={`badge ${n.is_read ? 'b-blue' : 'b-red'}`}>
                  {n.type || 'info'}
                </span>
              </div>
            </div>
          ))}
          {(!filtered.length && !loading) && (
            <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '10px 14px' }}>
              No notifications.
            </div>
          )}
          {loading && (
            <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '10px 14px' }}>
              Loading...
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {/* Keep settings static */}
          {/* ...your existing Notification Settings card... */}

          <div className="card">
            <div className="card-header">
              <div className="card-title">Notification Summary</div>
            </div>
            <div className="status-row">
              <span>Unread</span>
              <strong style={{ color: 'var(--danger)' }}>{unread}</strong>
            </div>
            <div className="status-row">
              <span>Total loaded</span><strong>{items.length}</strong>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default Notifications;