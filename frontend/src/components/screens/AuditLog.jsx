import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const AuditLog = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');

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
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search actor, entity, or details..."
            style={{ flex: 2, minWidth: '120px' }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <input
            className="input"
            placeholder="Entity type"
            style={{ minWidth: '100px' }}
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value)}
          />
          <input
            className="input"
            placeholder="Action type"
            style={{ minWidth: '120px' }}
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          />
          <input className="input" type="date" style={{ minWidth: '130px' }} />
          <input className="input" type="date" style={{ minWidth: '130px' }} />
          <button
            className="btn btn-primary"
            onClick={() => {
              // client-side filtering only; no-op because filters are live-bound
            }}
          >
            Apply
          </button>
          <button
            className="btn btn-outline"
            onClick={() => {
              if (!logs.length) return;
              const filtered = logs.filter((a) => {
                const q = searchText.trim().toLowerCase();
                const ent = entityFilter.trim().toLowerCase();
                const act = actionFilter.trim().toLowerCase();
                if (ent && (a.entity_type || '').toLowerCase() !== ent) return false;
                if (act && (a.action_type || '').toLowerCase() !== act) return false;
                if (!q) return true;
                const blob = [
                  a.actor_type,
                  a.entity_type,
                  a.entity_id,
                  a.action_type,
                  JSON.stringify(a.action_details || {}),
                  a.ip_address,
                  a.user_agent,
                ]
                  .join(' ')
                  .toLowerCase();
                return blob.includes(q);
              });
              const header = [
                'time',
                'actor_type',
                'action_type',
                'entity_type',
                'entity_id',
                'details',
                'success',
                'ip_address',
                'user_agent',
              ];
              const rows = filtered.map((a) => [
                a.created_at || '',
                a.actor_type || '',
                a.action_type || '',
                a.entity_type || '',
                a.entity_id || '',
                a.action_details ? JSON.stringify(a.action_details) : '',
                a.success ? '1' : '0',
                a.ip_address || '',
                a.user_agent || '',
              ]);
              const csv = [header.join(','), ...rows.map((row) =>
                row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')
              )].join('\n');
              const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
              const url = URL.createObjectURL(blob);
              const aEl = document.createElement('a');
              aEl.href = url;
              aEl.download = 'audit-log.csv';
              aEl.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export
          </button>
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
                <th>User Agent</th>
              </tr>
            </thead>
            <tbody>
              {logs
                .filter((a) => {
                  const q = searchText.trim().toLowerCase();
                  const ent = entityFilter.trim().toLowerCase();
                  const act = actionFilter.trim().toLowerCase();
                  if (ent && (a.entity_type || '').toLowerCase() !== ent) return false;
                  if (act && (a.action_type || '').toLowerCase() !== act) return false;
                  if (!q) return true;
                  const blob = [
                    a.actor_type,
                    a.entity_type,
                    a.entity_id,
                    a.action_type,
                    JSON.stringify(a.action_details || {}),
                    a.ip_address,
                    a.user_agent,
                  ]
                    .join(' ')
                    .toLowerCase();
                  return blob.includes(q);
                })
                .map((a) => (
                <tr key={a.log_id}>
                  <td style={{ fontSize: '10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                  </td>
                  <td>
                    <span className="badge b-blue" style={{ fontSize: '9px' }}>
                      {a.actor_badge || a.actor_type || 'SYSTEM'}
                    </span>
                  </td>
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
                  <td style={{ fontSize: '9px', color: 'var(--muted)', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {a.user_agent || '—'}
                  </td>
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