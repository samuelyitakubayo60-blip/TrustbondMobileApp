import React, { useEffect, useState } from 'react';
import api, { cacheBust } from '../../api/client';
import { formatRelativeTime } from '../../utils/dateTime';
import { isHotspotNotification, notificationCategory } from '../../utils/notificationHelpers';

const LIST_LIMIT = 50;

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
  const [summary, setSummary] = useState({
    unread_count: 0,
    total_count: 0,
    reports: 0,
    hotspots: 0,
    assignments: 0,
    system: 0,
  });
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState('all');
  const [searchText, setSearchText] = useState('');

  const loadNotifications = async () => {
    setLoading(true);
    cacheBust('/api/v1/notifications');
    try {
      const [list, sum] = await Promise.all([
        api.get(`/api/v1/notifications/?limit=${LIST_LIMIT}`),
        api.get('/api/v1/notifications/summary'),
      ]);
      setItems(Array.isArray(list) ? list : []);
      setSummary({
        unread_count: sum?.unread_count ?? 0,
        total_count: sum?.total_count ?? 0,
        reports: sum?.reports ?? 0,
        hotspots: sum?.hotspots ?? 0,
        assignments: sum?.assignments ?? 0,
        system: sum?.system ?? 0,
      });
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadNotifications();
  }, [wsRefreshKey]);

  const filtered = items.filter((n) => {
    if (filterType !== 'all' && notificationCategory(n) !== filterType) return false;
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
      await api.post('/api/v1/notifications/mark-all-read');
      await loadNotifications();
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
      goToScreen?.('security-situation', 3);
      return;
    }
    if (entityType === 'hotspot' && entityId) {
      // For hotspot notifications, try to get location data and show navigation options
      try {
        const hotspotData = await api.get(`/api/v1/hotspots/${entityId}`);
        if (hotspotData && hotspotData.latitude && hotspotData.longitude) {
          const lat = parseFloat(hotspotData.latitude);
          const lon = parseFloat(hotspotData.longitude);
          
          // Show navigation options
          const navigateToHotspot = window.confirm(
            `Navigate to hotspot location?\n\nLocation: ${hotspotData.village_name || 'Unknown'}\nCoords: ${lat.toFixed(6)}, ${lon.toFixed(6)}\n\nClick OK for navigation, Cancel for hotspot details.`
          );
          
          if (navigateToHotspot) {
            window.open(
              `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`,
              '_blank'
            );
            return;
          }
        }
      } catch (error) {
        // If hotspot data fetch fails, fall back to hotspot details
        console.log('Could not fetch hotspot location data, navigating to details');
      }
      goToScreen?.('safety-map', 4);
      return;
    }
    
    // If no specific entity, navigate based on notification type
    if (isHotspotNotification(n)) {
      goToScreen?.('safety-map', 4);
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

  const typeColor = (n) => {
    const cat = notificationCategory(n);
    if (cat === 'report')     return 'sb-blue';
    if (cat === 'hotspot')    return 'sb-orange';
    if (cat === 'assignment') return 'sb-green';
    if (cat === 'system')     return 'sb-purple';
    return 'sb-blue';
  };

  return (
    <>
      {/* ── Notifications header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Notifications</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              System alerts, hotspot escalations, and high-priority report notifications.
            </p>
          </div>
          <button className="btn btn-outline btn-sm" style={{ alignSelf: 'center' }} type="button" onClick={markAllRead}>
            Mark all read
          </button>
        </div>

        {/* Summary stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Unread',      value: summary.unread_count,  cls: 'sb-red'    },
            { label: 'Total',       value: summary.total_count,   cls: 'sb-blue'   },
            { label: 'Reports',     value: summary.reports,       cls: 'sb-blue'   },
            { label: 'Hotspots',    value: summary.hotspots,      cls: 'sb-orange' },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Notifications list ── */}
      <div className="card">
        {summary.total_count > items.length && (
          <div style={{ padding: '10px 14px', fontSize: 12, color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>
            Showing latest {items.length} of {summary.total_count} notifications.
            {summary.unread_count > items.filter((n) => !n.is_read).length
              ? ` ${summary.unread_count} unread in your inbox (sidebar badge matches this).`
              : ''}
          </div>
        )}

        {/* Filters */}
        <div className="filter-row" style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)' }}>
          <input
            className="input"
            placeholder="Search title, message, or entity..."
            style={{ flex: 2, minWidth: '140px' }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <select className="select" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="all">All Types</option>
            <option value="report">Report</option>
            <option value="assignment">Assignment</option>
            <option value="hotspot">Hotspot</option>
            <option value="system">System</option>
          </select>
        </div>

        {/* List */}
        {filtered.map((n) => (
          <div
            className="notif-item"
            key={n.notification_id}
            onClick={() => openNotificationTarget(n)}
            style={{
              cursor: 'pointer',
              borderLeft: n.is_read ? 'none' : '3px solid var(--accent)',
              background: n.is_read ? 'transparent' : 'var(--c-accent-dim)',
            }}
          >
            <div
              className="notif-icon"
              style={{ background: 'var(--c-accent-dim)', color: 'var(--accent)', fontWeight: 700 }}
            >
              {(isHotspotNotification(n) ? 'HSP' : n.type?.toUpperCase().slice(0, 4)) || 'INFO'}
            </div>
            <div className="notif-body">
              <div className="notif-title">{n.title}</div>
              <div className="notif-desc">{friendlyFlagReason(n.message)}</div>
              <div className="notif-time">
                {formatRelativeTime(n.created_at)} · {n.is_read ? 'Read' : <strong style={{ color: 'var(--accent)' }}>Unread</strong>}
                {' · Click to open'}
              </div>
            </div>
            <div style={{ flexShrink: 0 }}>
              <span className={`badge ${n.is_read ? 'b-gray' : 'b-blue'}`}>
                {notificationCategory(n)}
              </span>
            </div>
          </div>
        ))}
        {(!filtered.length && !loading) && (
          <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '14px' }}>No notifications.</div>
        )}
        {loading && (
          <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '14px' }}>Loading...</div>
        )}
      </div>
    </>
  );
};

export default Notifications;