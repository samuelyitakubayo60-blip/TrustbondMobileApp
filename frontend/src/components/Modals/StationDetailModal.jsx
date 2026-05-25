import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const TYPE_BADGE = {
  headquarters: 'b-purple',
  police_station: 'b-blue',
  post: 'b-green',
  outpost: 'b-orange',
};

const TYPE_LABEL = {
  headquarters: 'Headquarters',
  police_station: 'Police Station',
  post: 'Police Post',
  outpost: 'Outpost',
};

const StationDetailModal = ({ isOpen, onClose, station }) => {
  const [officers, setOfficers] = useState([]);
  const [stats, setStats]       = useState(null);
  const [loading, setLoading]   = useState(false);
  const [tab, setTab]           = useState('info');

  useEffect(() => {
    if (!isOpen || !station) return;
    setTab('info');
    setLoading(true);
    const fetchData = async () => {
      try {
        const officersRes = await api.get(`/api/v1/police-users/?station_id=${station.station_id}`);
        setOfficers(Array.isArray(officersRes) ? officersRes : (officersRes?.items || []));

        let statsRes;
        try {
          statsRes = await api.get(`/api/v1/stats/station/${station.station_id}`);
        } catch (err) {
          if (err.response?.status === 404 || err.status === 404) {
            statsRes = await api.get('/api/v1/stats/dashboard');
          } else {
            throw err;
          }
        }
        setStats(statsRes);
      } catch (err) {
        console.error('Failed to fetch station details:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [isOpen, station]);

  if (!isOpen || !station) return null;

  const fmt = (d) => d ? new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
  const fmtCoords = (lat, lng) => (lat && lng) ? `${parseFloat(lat).toFixed(5)}, ${parseFloat(lng).toFixed(5)}` : '—';

  const TABS = [
    { id: 'info',      label: 'Info'                           },
    { id: 'officers',  label: `Officers (${officers.length})`  },
    { id: 'stats',     label: 'Statistics'                     },
  ];

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 720, width: '92%' }}>

        {/* ── Modal header ── */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span className="badge b-blue" style={{ fontFamily: 'monospace', fontSize: 11, letterSpacing: '0.05em' }}>
              {station.station_code}
            </span>
            <span style={{ fontWeight: 700, fontSize: 16 }}>{station.station_name}</span>
            <span className={`badge ${TYPE_BADGE[station.station_type] || 'b-gray'}`} style={{ fontSize: 10 }}>
              {TYPE_LABEL[station.station_type] || station.station_type}
            </span>
            <span className={`badge ${station.is_active ? 'b-green' : 'b-red'}`} style={{ fontSize: 10 }}>
              {station.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {/* ── Tabs ── */}
        <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', paddingLeft: 20 }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                background: 'none',
                border: 'none',
                borderBottom: tab === t.id ? '2px solid var(--primary)' : '2px solid transparent',
                color: tab === t.id ? 'var(--primary)' : 'var(--muted)',
                fontWeight: tab === t.id ? 600 : 400,
                fontSize: 13,
                padding: '10px 16px',
                cursor: 'pointer',
                marginBottom: -1,
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Content ── */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--muted)', fontSize: 13 }}>
            Loading station details…
          </div>
        ) : (
          <div style={{ maxHeight: '65vh', overflowY: 'auto', padding: '20px 20px 4px' }}>

            {/* INFO tab */}
            {tab === 'info' && (
              <div style={{ display: 'grid', gap: 20 }}>
                {/* Key details row */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                  {[
                    { label: 'Station Code', value: <span style={{ fontFamily: 'monospace', fontWeight: 700 }}>{station.station_code}</span> },
                    { label: 'Type',         value: <span className={`badge ${TYPE_BADGE[station.station_type] || 'b-gray'}`} style={{ fontSize: 11 }}>{TYPE_LABEL[station.station_type] || station.station_type || '—'}</span> },
                    { label: 'Coordinates',  value: fmtCoords(station.latitude, station.longitude) },
                    { label: 'Created',      value: fmt(station.created_at) },
                  ].map((f) => (
                    <div key={f.label} style={{ background: 'var(--bg)', borderRadius: 6, padding: '10px 14px', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{f.label}</div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{f.value}</div>
                    </div>
                  ))}
                </div>

                {/* Contact */}
                <div style={{ background: 'var(--bg)', borderRadius: 6, padding: '14px 16px', border: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Contact Information</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Phone</div>
                      <div style={{ fontSize: 13 }}>{station.phone_number || '—'}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Email</div>
                      <div style={{ fontSize: 13 }}>{station.email || '—'}</div>
                    </div>
                    {station.address_text && (
                      <div style={{ gridColumn: '1 / -1' }}>
                        <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Address</div>
                        <div style={{ fontSize: 13 }}>{station.address_text}</div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Coverage */}
                <div style={{ background: 'var(--bg)', borderRadius: 6, padding: '14px 16px', border: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Geographic Coverage</div>
                    <span className="badge b-blue" style={{ fontSize: 10 }}>
                      {station.covered_cell_names?.length || 0} cell{station.covered_cell_names?.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  {station.covered_cell_names?.length > 0 ? (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {station.covered_cell_names.map((cell) => (
                        <span key={cell} className="badge b-gray" style={{ fontSize: 11 }}>{cell}</span>
                      ))}
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: 'var(--muted)', fontStyle: 'italic' }}>No cell coverage configured.</div>
                  )}
                </div>
              </div>
            )}

            {/* OFFICERS tab */}
            {tab === 'officers' && (
              <div>
                {officers.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--muted)', fontSize: 13 }}>
                    No officers assigned to this station.
                  </div>
                ) : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {officers.map((o) => (
                      <div key={o.police_user_id} style={{ padding: '10px 14px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                          <div>
                            <span style={{ fontWeight: 600, fontSize: 13 }}>{o.first_name} {o.last_name}</span>
                            {o.badge_number && (
                              <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--muted)', fontFamily: 'monospace' }}>#{o.badge_number}</span>
                            )}
                          </div>
                          <div style={{ display: 'flex', gap: 4 }}>
                            <span className={`badge ${o.role === 'admin' ? 'b-purple' : o.role === 'supervisor' ? 'b-blue' : 'b-green'}`} style={{ fontSize: 10 }}>
                              {o.role}
                            </span>
                            <span className={`badge ${o.is_active ? 'b-green' : 'b-red'}`} style={{ fontSize: 10 }}>
                              {o.is_active ? 'Active' : 'Inactive'}
                            </span>
                          </div>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                          {o.email && <span>{o.email}</span>}
                          {o.phone_number && <span>{o.phone_number}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* STATS tab */}
            {tab === 'stats' && (
              <div style={{ display: 'grid', gap: 20 }}>
                {!stats ? (
                  <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--muted)', fontSize: 13 }}>
                    Statistics not available.
                  </div>
                ) : (
                  <>
                    {/* Overview row */}
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Overview</div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10 }}>
                        {[
                          { label: 'Total Reports',  value: stats.total_reports  || 0, color: 'var(--primary)'  },
                          { label: 'Verified',        value: stats.verified_reports || 0, color: 'var(--success)'  },
                          { label: 'Pending',         value: stats.pending_reports  || 0, color: 'var(--warning)'  },
                          { label: 'Rejected',        value: stats.rejected_reports || 0, color: 'var(--danger)'   },
                          { label: 'Active Cases',    value: stats.active_cases     || 0, color: 'var(--info)'     },
                        ].map((s) => (
                          <div key={s.label} style={{ textAlign: 'center', padding: '12px 8px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }}>
                            <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
                            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{s.label}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Verification details */}
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Verification Breakdown</div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10 }}>
                        {[
                          { label: 'Flagged',           value: stats.flagged_reports           || 0, color: '#F97316' },
                          { label: 'Auto-Confirmed',    value: stats.auto_confirmed_reports    || 0, color: '#10B981' },
                          { label: 'Officer Confirmed', value: stats.officer_confirmed_reports || 0, color: '#3B82F6' },
                          { label: 'Auto Rejected',     value: stats.auto_rejected_reports     || 0, color: '#EF4444' },
                          { label: 'Manually Rejected', value: stats.manually_rejected_reports || 0, color: '#8B5CF6' },
                        ].map((s) => (
                          <div key={s.label} style={{ textAlign: 'center', padding: '12px 8px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }}>
                            <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
                            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{s.label}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '16px 20px 20px' }}>
          <button className="btn btn-outline" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
};

export default StationDetailModal;
