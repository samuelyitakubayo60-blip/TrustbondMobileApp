import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Hotspots = () => {
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/hotspots')
      .then((res) => { if (mounted) { setHotspots(res || []); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const crit = hotspots.filter(h => h.risk_level === 'high').length;
  const warn = hotspots.filter(h => h.risk_level === 'medium').length;
  const normal = hotspots.filter(h => h.risk_level === 'low').length;

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
            <select className="select" style={{ width: 'auto', fontSize: '11px', padding: '4px 8px' }}>
              <option>All Risk Levels</option>
              <option>Critical</option>
              <option>Warning</option>
              <option>Normal</option>
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

        {/* Right-hand parameter + breakdown cards can stay as your static JSX */}
      </div>
    </>
  );
};

export default Hotspots;