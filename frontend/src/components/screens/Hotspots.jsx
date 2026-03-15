import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Hotspots = () => {
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [riskFilter, setRiskFilter] = useState('all');
  const [params, setParams] = useState({
    time_window_hours: 24,
    min_incidents: 2,
    radius_meters: 500,
  });
  const [recomputing, setRecomputing] = useState(false);

  const loadHotspots = () => {
    setLoading(true);
    const path =
      riskFilter === 'all'
        ? '/api/v1/hotspots'
        : `/api/v1/hotspots?risk_level=${encodeURIComponent(
            riskFilter === 'critical'
              ? 'high'
              : riskFilter === 'warning'
              ? 'medium'
              : 'low'
          )}`;
    api
      .get(path)
      .then((res) => {
        setHotspots(res || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    loadHotspots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskFilter]);

  const crit = hotspots.filter((h) => h.risk_level === 'high').length;
  const warn = hotspots.filter((h) => h.risk_level === 'medium').length;
  const normal = hotspots.filter((h) => h.risk_level === 'low').length;

  // Load default hotspot parameters once
  useEffect(() => {
    api
      .get('/api/v1/hotspots/params')
      .then((res) => {
        if (!res) return;
        setParams((prev) => ({
          ...prev,
          ...res,
        }));
      })
      .catch(() => {});
  }, []);

  // Aggregate type breakdown from current hotspots
  const typeTotals = {};
  let totalReports = 0;
  hotspots.forEach((h) => {
    const key = h.incident_type_name || 'Other';
    typeTotals[key] = (typeTotals[key] || 0) + (h.incident_count || 0);
    totalReports += h.incident_count || 0;
  });
  const typeEntries = Object.entries(typeTotals).sort(
    (a, b) => b[1] - a[1],
  );

  return (
    <>
      <div className="page-header">
        <h2>Crime Hotspots</h2>
        <p>Trust-weighted DBSCAN clusters — auto-detected from verified reports.</p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>Hotspots are created automatically when multiple reports of the same place and type cluster in time/space.</div>
      </div>

      <div className="stats-row">
        <div className="stat-card c-red">
          <div className="stat-label">Critical</div>
          <div className="stat-value sv-red">{crit}</div>
          <div className="stat-change">High risk</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Warning</div>
          <div className="stat-value sv-orange">{warn}</div>
          <div className="stat-change">Monitor</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Normal</div>
          <div className="stat-value sv-green">{normal}</div>
          <div className="stat-change">Lower risk</div>
        </div>
      </div>

      <div className="g31">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Detected Hotspot Clusters</div>
            <select
              className="select"
              style={{ width: 'auto', fontSize: '11px', padding: '4px 8px' }}
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
            >
              <option value="all">All Risk Levels</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="normal">Normal</option>
            </select>
          </div>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Location</th>
                  <th>Reports</th>
                  <th>Type</th>
                  <th>Radius (m)</th>
                  <th>Risk Level</th>
                  <th>Window</th>
                  <th>Last Updated</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {hotspots.map((h) => (
                  <tr key={h.hotspot_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: '10px', color: 'var(--muted)' }}>
                      HS-{String(h.hotspot_id).padStart(3, '0')}
                    </td>
                    <td><strong>{h.incident_type_name || 'Cluster'}</strong></td>
                    <td style={{ fontWeight: 700 }}>{h.incident_count}</td>
                    <td style={{ fontSize: '11px' }}>{h.incident_type_name || '—'}</td>
                    <td>{Number(h.radius_meters || 0)}</td>
                    <td>
                      <span className={`risk-pill ${
                        h.risk_level === 'high' ? 'r-critical'
                          : h.risk_level === 'medium' ? 'r-warning'
                          : 'r-normal'
                      }`}>
                        {h.risk_level?.toUpperCase() || 'OK'}
                      </span>
                    </td>
                    <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                      {h.time_window_hours
                        ? `${h.time_window_hours}h`
                        : '—'}
                    </td>
                    <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                      {h.detected_at ? new Date(h.detected_at).toLocaleString() : '—'}
                    </td>
                    <td><button className="btn btn-outline btn-sm">Details</button></td>
                  </tr>
                ))}
                {(!hotspots.length && !loading) && (
                  <tr>
                    <td colSpan={8} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      No hotspots yet.
                    </td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td colSpan={8} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      Loading...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">DBSCAN Parameters</div>
          </div>
          <div style={{ padding: '10px 14px', fontSize: '12px' }}>
            <div style={{ marginBottom: '10px' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '11px',
                  marginBottom: 4,
                }}
              >
                <span>Epsilon Radius (m)</span>
                <span>{Math.round(params.radius_meters || 0)} m</span>
              </div>
              <input
                type="range"
                min="100"
                max="1000"
                step="50"
                value={params.radius_meters}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    radius_meters: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div style={{ marginBottom: '10px' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '11px',
                  marginBottom: 4,
                }}
              >
                <span>Min. Samples</span>
                <span>{params.min_incidents}</span>
              </div>
              <input
                type="range"
                min="2"
                max="10"
                step="1"
                value={params.min_incidents}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    min_incidents: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div style={{ marginBottom: '10px' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '11px',
                  marginBottom: 4,
                }}
              >
                <span>Time Window</span>
                <span>
                  {params.time_window_hours >= 24
                    ? `${Math.round(
                        params.time_window_hours / 24,
                      )} days`
                    : `${params.time_window_hours} hours`}
                </span>
              </div>
              <select
                className="select"
                value={params.time_window_hours}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    time_window_hours: Number(e.target.value),
                  }))
                }
              >
                <option value={24}>Last 24 hours</option>
                <option value={72}>Last 3 days</option>
                <option value={168}>Last 7 days</option>
              </select>
            </div>
            <button
              className="btn btn-primary btn-sm"
              type="button"
              disabled={recomputing}
              onClick={async () => {
                setRecomputing(true);
                try {
                  await api.post('/api/v1/hotspots/recompute', params);
                  loadHotspots();
                } catch {
                  // ignore
                } finally {
                  setRecomputing(false);
                }
              }}
            >
              {recomputing ? 'Recomputing…' : 'Recompute Clusters'}
            </button>
          </div>

          <div
            style={{
              padding: '10px 14px',
              borderTop: '1px solid var(--border2)',
              fontSize: '12px',
            }}
          >
            <div
              style={{
                fontSize: '11px',
                fontWeight: 700,
                marginBottom: 6,
              }}
            >
              Type Breakdown
            </div>
            {typeEntries.length === 0 && (
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                No hotspots yet.
              </div>
            )}
            {typeEntries.map(([name, count]) => {
              const pct = totalReports
                ? Math.round((count / totalReports) * 100)
                : 0;
              return (
                <div
                  key={name}
                  style={{ marginBottom: 6 }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: '11px',
                    }}
                  >
                    <span>{name}</span>
                    <span>
                      {count} ({pct}%)
                    </span>
                  </div>
                  <div className="prog-bar">
                    <div
                      className="prog-fill"
                      style={{
                        width: `${pct}%`,
                        background: 'var(--accent)',
                      }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
};

export default Hotspots;