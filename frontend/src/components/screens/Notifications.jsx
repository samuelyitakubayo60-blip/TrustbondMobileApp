import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Notifications = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/notifications?limit=50')
      .then((res) => { if (mounted) { setItems(res || []); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const unread = items.filter(n => !n.is_read).length;

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
              <button className="btn btn-outline btn-sm">Mark all read</button>
              <button className="btn btn-outline btn-sm">Clear all</button>
            </div>
          </div>

          {items.map((n) => (
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
          {(!items.length && !loading) && (
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