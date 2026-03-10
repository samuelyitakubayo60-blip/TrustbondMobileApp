import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const DeviceTrust = () => {
  const [devices, setDevices] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/devices?limit=50&offset=0')
      .then((res) => {
        if (!mounted) return;
        setDevices(res.items || []);
        setStats(res.stats || null);
        setLoading(false);
      })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const active = stats?.active_30d ?? 0;
  const high = stats?.high_trust ?? 0;
  const medium = stats?.medium_trust ?? 0;
  const low = stats?.low_trust ?? 0;
  const banned = stats?.banned ?? 0;

  return (
    <>
      <div className="page-header">
        <h2>Device Trust Management</h2>
        <p>Pseudonymous device profiles — track reporting patterns, trust scores, and spam behavior without exposing user identity.</p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>Device identifiers are one-way SHA-256 hashes. No personally identifiable information is stored.</div>
      </div>

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">Active Devices</div>
          <div className="stat-value sv-blue">{active}</div>
          <div className="stat-change">Last 30 days</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">High Trust</div>
          <div className="stat-value sv-green">{high}</div>
          <div className="stat-change">Score ≥ 70</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Medium Trust</div>
          <div className="stat-value sv-orange">{medium}</div>
          <div className="stat-change">Score 40–69</div>
        </div>
        <div className="stat-card c-red">
          <div className="stat-label">Low / Banned</div>
          <div className="stat-value sv-red">{low + banned}</div>
          <div className="stat-change">Low trust or banned</div>
        </div>
      </div>

      <div className="g31">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Device Registry</div>
            <div style={{ display: 'flex', gap: '6px' }}>
              <select className="select" style={{ width: 'auto', fontSize: '11px', padding: '4px 8px' }}>
                <option>All Trust Levels</option>
                <option>High</option>
                <option>Medium</option>
                <option>Low</option>
                <option>Banned</option>
              </select>
              <button className="btn btn-outline btn-sm">Export</button>
            </div>
          </div>

          <div className="filter-row">
            <input className="input" placeholder="Search by device hash..." style={{ flex: 2 }} />
            <select className="select">
              <option>All Sectors</option>
              <option>Muhoza</option>
              <option>Kinigi</option>
              <option>Cyuve</option>
            </select>
          </div>

          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Device Hash</th>
                  <th>Trust Score</th>
                  <th>Total Reports</th>
                  <th>Confirmed</th>
                  <th>Rejected</th>
                  <th>Spam Flags</th>
                  <th>Last Active</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {devices.map((d) => {
                  const score = d.device_trust_score ?? 0;
                  const width = Math.max(0, Math.min(100, Number(score)));
                  const shortHash = d.device_hash_short || d.device_hash?.slice(0, 8) || 'device';
                  const statusBadge =
                    score < 10 ? 'b-red' :
                    score < 40 ? 'b-orange' :
                    'b-green';
                  const statusLabel =
                    score < 10 ? 'Banned' :
                    score < 40 ? 'Flagged' :
                    'Active';

                  return (
                    <tr key={d.device_id}>
                      <td style={{ fontFamily: 'monospace', fontSize: '10px' }}>{shortHash}</td>
                      <td>
                        <div className="trust-wrap">
                          <div className="trust-track">
                            <div className="trust-fill" style={{ width: `${width}%`, background: score >= 70 ? 'var(--success)' : score >= 40 ? 'var(--warning)' : 'var(--danger)' }}></div>
                          </div>
                          <div className="trust-val">{Math.round(score)}</div>
                        </div>
                      </td>
                      <td>{d.total_reports}</td>
                      <td style={{ color: 'var(--success)' }}>{d.trusted_reports}</td>
                      <td style={{ color: 'var(--danger)' }}>{d.flagged_reports}</td>
                      <td>—</td>
                      <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                        {d.first_seen_at ? new Date(d.first_seen_at).toLocaleDateString() : '—'}
                      </td>
                      <td><span className={`badge ${statusBadge}`}>{statusLabel}</span></td>
                      <td><button className="btn btn-outline btn-sm">Profile</button></td>
                    </tr>
                  );
                })}
                {(!devices.length && !loading) && (
                  <tr>
                    <td colSpan={9} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      No devices yet.
                    </td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td colSpan={9} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      Loading...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
              Showing {devices.length} of {stats?.active_30d ?? devices.length} devices
            </div>
            <div className="pagination">
              <div className="page-btn">‹</div>
              <div className="page-btn current">1</div>
              <div className="page-btn">2</div>
              <div className="page-btn">3</div>
              <div className="page-btn">›</div>
            </div>
          </div>
        </div>

        {/* Right-hand explanatory cards can remain as your existing static JSX */}
      </div>
    </>
  );
};

export default DeviceTrust;