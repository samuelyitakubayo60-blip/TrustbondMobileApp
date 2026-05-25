import React, { useCallback, useEffect, useState } from 'react';
import SkeletonTable from '../Common/SkeletonTable';
import api from '../../api/client';

const PAGE_SIZE = 10;

const AuditLog = ({ wsRefreshKey }) => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [resultFilter, setResultFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const loadLogs = useCallback(() => {
    let mounted = true;
    setLoading(true);
    
    const params = new URLSearchParams();
    params.set("limit", String(500));
    params.set("sort_by", "created_at");
    params.set("sort_order", "desc");

    if (entityFilter.trim()) {
      params.set("entity_type", entityFilter.trim());
    }
    if (actionFilter.trim()) {
      params.set("action_type", actionFilter.trim());
    }
    
    api.get(`/api/v1/audit-logs/?${params.toString()}`)
      .then((res) => { 
        if (mounted) { 
          setLogs(res || []); 
          setTotal(res?.length || 0);
          setLoading(false); 
        } 
      })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [entityFilter, actionFilter]); // Remove pageSize and offset dependencies

  useEffect(() => {
    loadLogs();
  }, [loadLogs, wsRefreshKey]);

  // Client-side filtering
  const filteredLogs = logs.filter((a) => {
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const blob = [
        a.actor_type,
        a.actor_role || '',
        a.actor_name,
        a.action_type,
        a.entity_type,
        a.entity_id,
        a.details ? JSON.stringify(a.details) : '',
        a.sensitivity_level || '',
      ].join(' ');
      if (!blob.toLowerCase().includes(q)) {
        return false;
      }
    }
    if (resultFilter !== "all") {
      const isSuccess = resultFilter === "success";
      if (a.success !== isSuccess) {
        return false;
      }
    }
    return true;
  });

  // Client-side pagination
  const displayLogs = filteredLogs.slice(offset, offset + pageSize);

  const totalEntries = filteredLogs.length;
  const successCount = filteredLogs.filter(a => a.success !== false).length;
  const failedCount  = filteredLogs.filter(a => a.success === false).length;

  const exportCsv = () => {
    if (!logs.length) return;
    const header = ['created_at','actor_type','actor_name','action_type','entity_type','entity_id','details','result','ip_address','user_agent'];
    const rows = filteredLogs.map((a) => [
      a.created_at || '', a.actor_type || '', a.actor_name || '',
      a.action_type || '', a.entity_type || '', a.entity_id || '',
      a.details ? JSON.stringify(a.details) : '',
      a.success ? 'Success' : 'Failed',
      a.ip_address || '', a.user_agent || '',
    ]);
    const csv = [header.join(','), ...rows.map((row) =>
      row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')
    )].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'audit_log.csv'; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      {/* ── Audit Log header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Audit Log</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Tamper-evident record of system actions. New logins, case updates, hotspot recompute, and user changes are recorded after deploy.
            </p>
            {logs.length > 0 && logs.every((a) => {
              const t = a.created_at ? new Date(a.created_at).getTime() : 0;
              return t < Date.now() - 7 * 24 * 60 * 60 * 1000;
            }) && (
              <p style={{ margin: '8px 0 0', color: 'var(--warning)', fontSize: 12 }}>
                Latest entry is older than 7 days — if you use the portal daily, redeploy the backend so audit logging is active.
              </p>
            )}
          </div>
          <button className="btn btn-outline btn-sm" style={{ alignSelf: 'center' }} onClick={exportCsv}>
            Export CSV
          </button>
        </div>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Total entries',  value: logs.length,   cls: 'sb-blue'   },
            { label: 'Filtered',       value: totalEntries,  cls: 'sb-blue'   },
            { label: 'Success',        value: successCount,  cls: 'sb-green'  },
            { label: 'Failed',         value: failedCount,   cls: 'sb-red'    },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search actor, entity, or details..."
            style={{ flex: 2, minWidth: '120px' }}
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setOffset(0); }}
          />
          <input
            className="input"
            placeholder="Entity type"
            style={{ minWidth: '100px' }}
            value={entityFilter}
            onChange={(e) => { setEntityFilter(e.target.value); setOffset(0); }}
          />
          <input
            className="input"
            placeholder="Action type"
            style={{ minWidth: '120px' }}
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setOffset(0); }}
          />
          <select
            className="select"
            value={resultFilter}
            onChange={(e) => { setResultFilter(e.target.value); setOffset(0); }}
          >
            <option value="all">All Results</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
          <select
            className="select"
            style={{ width: 'auto' }}
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setOffset(0); }}
          >
            <option value={10}>10 / page</option>
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
          <button className="btn btn-outline" onClick={exportCsv}>
            Export
          </button>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Time</th>
                <th>Who</th>
                <th>Role</th>
                <th>What They Did</th>
              </tr>
            </thead>
            <tbody>
              {displayLogs.map((a, index) => (
                <tr key={a.log_id}>
                  <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                    {index + 1}
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {a.actor_type === 'police_user' ? (
                        <>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <span className="badge b-blue" style={{ fontSize: 9 }}>
                              {a.actor_badge || 'BADGE'}
                            </span>
                            <span style={{ fontSize: 11, fontWeight: 500 }}>
                              {a.actor_name || 'Unknown Officer'}
                            </span>
                          </div>
                          <div style={{ fontSize: 9, color: 'var(--muted)' }}>Police User</div>
                        </>
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span className="badge b-gray" style={{ fontSize: 9 }}>
                            {a.actor_type || 'SYSTEM'}
                          </span>
                          <span style={{ fontSize: 10, color: 'var(--muted)' }}>
                            {a.actor_name || 'System'}
                          </span>
                        </div>
                      )}
                    </div>
                  </td>
                  <td>
                    {a.actor_role && (
                      <span className={`badge ${
                        a.actor_role === 'admin'      ? 'b-orange' :
                        a.actor_role === 'supervisor' ? 'b-green' : 'b-blue'
                      }`} style={{ fontSize: 9 }}>
                        {a.actor_role}
                      </span>
                    )}
                  </td>
                  <td style={{ fontSize: 11 }}>
                    <div>
                      <span className={`badge ${a.success === false ? 'b-red' : 'b-green'}`} style={{ fontSize: 9, marginRight: 6 }}>
                        {a.action_type}
                      </span>
                      {a.entity_type && (
                        <span style={{ fontSize: 10, color: 'var(--muted)' }}>
                          {a.entity_type}{a.entity_id ? ` (${String(a.entity_id).slice(0, 8)}…)` : ''}
                        </span>
                      )}
                      {a.details && (
                        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {typeof a.details === 'string' ? a.details : JSON.stringify(a.details)}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {(!displayLogs.length && !loading) && (
                <tr>
                  <td colSpan={5} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No audit entries.
                  </td>
                </tr>
              )}
              {loading && <SkeletonTable cols={5} rows={8} />}
            </tbody>
          </table>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Showing {Math.min(offset + 1, filteredLogs.length)}-{Math.min(offset + pageSize, filteredLogs.length)} of {filteredLogs.length} entries
            {filteredLogs.length > 0 && (
              <span style={{ marginLeft: '10px', color: 'var(--accent)' }}>
                (Page {Math.floor(offset / pageSize) + 1} of {Math.ceil(filteredLogs.length / pageSize)})
              </span>
            )}
          </div>
          <div className="pagination">
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {(() => {
              const totalPages = Math.ceil(filteredLogs.length / pageSize);
              const currentPage = Math.floor(offset / pageSize) + 1;
              
              // Show all page numbers if total pages <= 10, otherwise show smart pagination
              if (totalPages <= 10) {
                return Array.from({ length: totalPages }, (_, i) => {
                  const pageNum = i + 1;
                  const pageOffset = (pageNum - 1) * pageSize;
                  const isCurrent = pageNum === currentPage;
                  return (
                    <button
                      key={pageNum}
                      className={`page-btn ${isCurrent ? 'current' : ''}`}
                      onClick={() => setOffset(pageOffset)}
                    >
                      {pageNum}
                    </button>
                  );
                });
              }
              
              // Smart pagination for many pages
              const pages = [];
              const startPage = Math.max(1, currentPage - 2);
              const endPage = Math.min(totalPages, currentPage + 2);
              
              // Always show first page
              if (startPage > 1) {
                pages.push(
                  <button
                    key={1}
                    className="page-btn"
                    onClick={() => setOffset(0)}
                  >
                    1
                  </button>
                );
                if (startPage > 2) {
                  pages.push(<span key="start-ellipsis" style={{ padding: '0 8px' }}>...</span>);
                }
              }
              
              // Show pages around current page
              for (let i = startPage; i <= endPage; i++) {
                const pageOffset = (i - 1) * pageSize;
                const isCurrent = i === currentPage;
                pages.push(
                  <button
                    key={i}
                    className={`page-btn ${isCurrent ? 'current' : ''}`}
                    onClick={() => setOffset(pageOffset)}
                  >
                    {i}
                  </button>
                );
              }
              
              // Always show last page
              if (endPage < totalPages) {
                if (endPage < totalPages - 1) {
                  pages.push(<span key="end-ellipsis" style={{ padding: '0 8px' }}>...</span>);
                }
                pages.push(
                  <button
                    key={totalPages}
                    className="page-btn"
                    onClick={() => setOffset((totalPages - 1) * pageSize)}
                  >
                    {totalPages}
                  </button>
                );
              }
              
              return pages;
            })()}
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.min(filteredLogs.length - pageSize, offset + pageSize))}
              disabled={offset + pageSize >= filteredLogs.length}
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default AuditLog;