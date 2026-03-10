import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const AuditLog = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/audit-logs?limit=100')
      .then((res) => { if (mounted) { setLogs(res || []); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  return (
    <>
      <div className="page-header">
        <h2>Audit Log</h2>
        <p>Tamper-evident record of all system actions for accountability and compliance.</p>
      </div>

      <div className="card">
        {/* keep filter row static for now */}
        <div className="filter-row">
          <input className="input" placeholder="Search log entries..." style={{ flex: 2, minWidth: '120px' }} />
          <input className="input" placeholder="Entity type" style={{ minWidth: '100px' }} />
          <input className="input" placeholder="Action type" style={{ minWidth: '120px' }} />
          <input className="input" type="date" style={{ minWidth: '130px' }} />
          <input className="input" type="date" style={{ minWidth: '130px' }} />
          <button className="btn btn-primary">Apply</button>
          <button className="btn btn-outline">Export</button>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Entity ID</th>
                <th>Details</th>
                <th>Result</th>
                <th>IP Address</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((a) => (
                <tr key={a.log_id}>
                  <td style={{ fontSize: '10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                  </td>
                  <td><span className="badge b-blue" style={{ fontSize: '9px' }}>{a.actor_type}</span></td>
                  <td><span className="badge b-green" style={{ fontSize: '9px' }}>{a.action_type}</span></td>
                  <td style={{ fontSize: '11px' }}>{a.entity_type || '—'}</td>
                  <td style={{ fontSize: '10px', fontFamily: 'monospace', color: 'var(--muted)' }}>{a.entity_id || '—'}</td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                    {a.action_details ? JSON.stringify(a.action_details) : '—'}
                  </td>
                  <td>
                    <span className={`badge ${a.success ? 'b-green' : 'b-red'}`} style={{ fontSize: '9px' }}>
                      {a.success ? 'Success' : 'Failed'}
                    </span>
                  </td>
                  <td style={{ fontSize: '10px', fontFamily: 'monospace', color: 'var(--muted)' }}>{a.ip_address || '—'}</td>
                </tr>
              ))}
              {(!logs.length && !loading) && (
                <tr>
                  <td colSpan={8} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No audit entries.
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

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>Showing {logs.length} entries</div>
          <div className="pagination">
            <div className="page-btn">‹</div>
            <div className="page-btn current">1</div>
            <div className="page-btn">2</div>
            <div className="page-btn">›</div>
          </div>
        </div>
      </div>
    </>
  );
};

export default AuditLog;