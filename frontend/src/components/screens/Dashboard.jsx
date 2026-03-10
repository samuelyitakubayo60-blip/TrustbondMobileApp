import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Dashboard = ({ goToScreen }) => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/stats/dashboard')
      .then((d) => { if (mounted) { setStats(d); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const total = stats?.total_reports ?? 0;
  const recent7 = stats?.reports_last_7_days ?? 0;
  const pending = stats?.pending ?? (stats?.by_status?.pending ?? 0);
  const verified = stats?.verified ?? (stats?.by_status?.passed ?? 0);
  const flagged = stats?.flagged ?? 0;
  const openCases = stats?.open_cases ?? 0;
  const recentReports = stats?.recent_reports ?? [];
  const topHotspots = stats?.top_hotspots ?? [];
  const recentActivity = stats?.recent_activity ?? [];

  return (
    <>
      <div className="page-header">
        <h2>Welcome back, System Admin</h2>
        <p>Here's what's happening in Musanze District right now.</p>
      </div>

      <div className="alert alert-warn">
        <span className="alert-icon">!</span>
        <div>
          <strong>{pending} reports pending review</strong> — view and verify.
          <span className="card-action" onClick={() => goToScreen('reports', 1)}>Review now</span>
        </div>
      </div>

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">Total Reports</div>
          <div className="stat-value sv-blue">{total}</div>
          <div className="stat-change"><span className="up">live</span></div>
        </div>
        <div className="stat-card c-cyan">
          <div className="stat-label">Last 7 Days</div>
          <div className="stat-value sv-cyan">{recent7}</div>
          <div className="stat-change"><span className="up">recent</span></div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Pending</div>
          <div className="stat-value sv-orange">{pending}</div>
          <div className="stat-change"><span className="dn">needs review</span></div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Verified</div>
          <div className="stat-value sv-green">{verified}</div>
          <div className="stat-change"><span className="up">rule \"passed\"</span></div>
        </div>
        <div className="stat-card c-red">
          <div className="stat-label">Flagged</div>
          <div className="stat-value sv-red">{flagged}</div>
          <div className="stat-change"><span className="dn">check anomalies</span></div>
        </div>
        <div className="stat-card c-purple">
          <div className="stat-label">Open Cases</div>
          <div className="stat-value sv-purple">{openCases}</div>
          <div className="stat-change"><span className="dn">case files</span></div>
        </div>
      </div>

      {/* Keep charts visually static for now */}
      {/* ... keep your existing Weekly Volume + Credibility Split JSX unchanged ... */}

      <div className="g31">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Recent Reports</div>
            <div className="card-action" onClick={() => goToScreen('reports', 1)}>View all</div>
          </div>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Location</th>
                  <th>Trust</th>
                  <th>Status</th>
                  <th>Time</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(recentReports || []).map((r) => {
                  const score = r.trust_score ?? 0;
                  const width = Math.max(0, Math.min(100, Number(score)));
                  return (
                    <tr key={r.report_id}>
                      <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                        {r.report_number || String(r.report_id).slice(0, 8)}
                      </td>
                      <td><strong>{r.incident_type_name || '—'}</strong></td>
                      <td>{r.village_name || '—'}</td>
                      <td>
                        <div className="trust-wrap">
                          <div className="trust-track">
                            <div className="trust-fill" style={{ width: `${width}%`, background: 'var(--success)' }}></div>
                          </div>
                          <div className="trust-val">{Math.round(score)}</div>
                        </div>
                      </td>
                      <td><span className="badge b-green">{r.rule_status}</span></td>
                      <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                        {r.reported_at ? new Date(r.reported_at).toLocaleString() : '—'}
                      </td>
                      <td>
                        <button className="btn btn-outline btn-sm" onClick={() => goToScreen('reports', 1)}>View</button>
                      </td>
                    </tr>
                  );
                })}
                {(!recentReports || recentReports.length === 0) && (
                  <tr>
                    <td colSpan={7} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      {loading ? 'Loading...' : 'No reports yet.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Top Hotspots</div>
            <div className="card-action" onClick={() => goToScreen('hotspots', 4)}>Full view</div>
          </div>
          {(topHotspots || []).map((h, idx) => (
            <div className="hs-item" key={h.hotspot_id}>
              <div className="hs-rank">{String(idx + 1).padStart(2, '0')}</div>
              <div className="hs-info">
                <div className="hs-name">{h.area_name || 'Area'}</div>
                <div className="hs-meta">
                  {h.incident_count} reports · {h.incident_type_name || 'Mixed'}
                </div>
              </div>
              <span className={`risk-pill ${
                h.risk_level === 'high' ? 'r-critical'
                  : h.risk_level === 'medium' ? 'r-warning'
                  : 'r-normal'
              }`}>
                {h.risk_level?.toUpperCase() || 'OK'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Audit details and system status are available elsewhere (Audit Log, System Config),
          so we keep the dashboard focused on key KPIs, recent reports, and hotspots. */}
    </>
  );
};

export default Dashboard;