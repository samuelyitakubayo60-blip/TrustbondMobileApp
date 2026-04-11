import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { formatRelativeTime } from '../../utils/dateTime';

const friendlyFlagReason = (text) => {
  if (!text) return '';
  const replacements = {
    evidence_time_mismatch: 'Evidence captured too long before submission',
    stale_live_capture_timestamp: 'Live-capture timestamp is too old',
    incident_description_mismatch: 'Description does not match selected incident type',
    ai_suspicious_review: 'AI marked report as suspicious',
    ai_uncertain_review: 'AI result is uncertain; manual review needed',
    ai_detected_fake: 'AI detected possible fake evidence',
    device_burst_reporting: 'Too many reports from same device in a short time',
    duplicate_description_recent: 'Repeated description from same device (possible spam)',
  };
  let out = String(text);
  Object.entries(replacements).forEach(([code, label]) => {
    out = out.replaceAll(code, label);
  });
  return out;
};

const Notifications = ({ goToScreen, onOpenReport, wsRefreshKey }) => {
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
  }, [wsRefreshKey]);

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

  const openNotificationTarget = async (n) => {
    const entityType = (n.related_entity_type || '').toLowerCase();
    const entityId = n.related_entity_id;

    try {
      if (!n.is_read) {
        await api.patch(`/api/v1/notifications/${n.notification_id}/read`);
        setItems((prev) =>
          prev.map((x) =>
            x.notification_id === n.notification_id ? { ...x, is_read: true } : x,
          ),
        );
      }
    } catch {
      // ignore read update failures; still attempt navigation
    }

    // Navigate based on entity type or notification type
    if (entityType === 'report' && entityId) {
      onOpenReport?.(entityId);
      return;
    }
    if (entityType === 'case' && entityId) {
      goToScreen?.('case-management', 3);
      return;
    }
    if (entityType === 'hotspot' && entityId) {
      goToScreen?.('hotspots', 4);
      return;
    }
    
    // If no specific entity, navigate based on notification type
    if (n.type === 'hotspot') {
      goToScreen?.('hotspots', 4);
      return;
    }
    if (n.type === 'assignment') {
      goToScreen?.('reports', 1);
      return;
    }
    if (n.type === 'system') {
      goToScreen?.('system-config', 10);
      return;
    }
    
    // Default fallback - go to reports
    goToScreen?.('reports', 1);
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

          {filtered.map((n) => {
            // All notifications are now clickable
            return (
            <div
              className="notif-item"
              key={n.notification_id}
              onClick={() => openNotificationTarget(n)}
              style={{ cursor: 'pointer' }}
            >
              <div className="notif-icon" style={{ background: 'rgba(79, 142, 247, 0.18)' }}>
                {n.type?.toUpperCase().slice(0, 4) || 'INFO'}
              </div>
              <div className="notif-body">
                <div className="notif-title">{n.title}</div>
                <div className="notif-desc">{friendlyFlagReason(n.message)}</div>
                <div className="notif-time">
                  {formatRelativeTime(n.created_at)} · {n.is_read ? 'Read' : 'Unread'}
                  {' · Click to open'}
                </div>
              </div>
              <div style={{ flexShrink: 0 }}>
                <span className={`badge ${n.is_read ? 'b-blue' : 'b-red'}`}>
                  {n.type || 'info'}
                </span>
              </div>
            </div>
          )})}
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