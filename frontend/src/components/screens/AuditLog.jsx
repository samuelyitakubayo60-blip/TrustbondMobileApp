import React, { useEffect, useState, useCallback } from 'react';
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
    params.set("limit", String(500)); // Get all data for client-side pagination
    
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
            onChange={(e) => {
              setSearchText(e.target.value);
              setOffset(0);
            }}
          />
          <input
            className="input"
            placeholder="Entity type"
            style={{ minWidth: '100px' }}
            value={entityFilter}
            onChange={(e) => {
              setEntityFilter(e.target.value);
              setOffset(0);
            }}
          />
          <input
            className="input"
            placeholder="Action type"
            style={{ minWidth: '120px' }}
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setOffset(0);
            }}
          />
          <select
            className="select"
            value={resultFilter}
            onChange={(e) => {
              setResultFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">All Results</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
          <input
            type="number"
            min="10"
            max="100"
            placeholder="Rows"
            style={{ minWidth: "80px" }}
            value={pageSize}
            onChange={(e) => {
              const newSize = Math.max(10, Math.min(100, parseInt(e.target.value) || 50));
              setPageSize(newSize);
              setOffset(0);
            }}
          />
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
                  a.actor_name,
                  a.action_type,
                  a.entity_type,
                  a.entity_id,
                  a.details,
                  a.result,
                ].join(' ');
                return blob.toLowerCase().includes(q);
              });
              const header = [
                "created_at",
                "actor_type",
                "actor_name",
                "action_type",
                "entity_type",
                "entity_id",
                "details",
                "result",
                "ip_address",
                "user_agent",
              ];
              const rows = filtered.map((a) => [
                a.created_at || "",
                a.actor_type || "",
                a.actor_name || "",
                a.action_type || "",
                a.entity_type || "",
                a.entity_id || "",
                a.details ? JSON.stringify(a.details) : "",
                a.success ? "Success" : "Failed",
                a.ip_address || "",
                a.user_agent || "",
              ]);
              const csv = [header.join(","), ...rows.map((row) =>
                row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")
              )].join("\n");
              const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "audit_log.csv";
              a.click();
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
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      {a.actor_type === 'police_user' ? (
                        <>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <span className="badge b-blue" style={{ fontSize: '9px' }}>
                              {a.actor_badge || 'BADGE'}
                            </span>
                            <span style={{ fontSize: '11px', fontWeight: '500' }}>
                              {a.actor_name || 'Unknown Officer'}
                            </span>
                          </div>
                          <div style={{ fontSize: '9px', color: 'var(--muted)' }}>
                            Police User
                          </div>
                        </>
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <span className="badge b-gray" style={{ fontSize: '9px' }}>
                            {a.actor_type || 'SYSTEM'}
                          </span>
                          <span style={{ fontSize: '10px', color: 'var(--muted)' }}>
                            {a.actor_name || 'System'}
                          </span>
                        </div>
                      )}
                    </div>
                  </td>
                  <td>
                    {a.actor_role && (
                      <span className={`badge ${
                        a.actor_role === 'admin' ? 'b-purple' : 
                        a.actor_role === 'supervisor' ? 'b-orange' : 
                        'b-blue'
                      }`} style={{ fontSize: '8px' }}>
                        {a.actor_role}
                      </span>
                    )}
                  </td>
                  <td style={{ fontSize: '11px' }}>
                    <div>
                      <span className="badge b-green" style={{ fontSize: '9px', marginRight: '6px' }}>{a.action_type}</span>
                      {a.entity_type && (
                        <span style={{ fontSize: '10px', color: 'var(--muted)' }}>
                          {a.entity_type}{a.entity_id ? ` (${a.entity_id})` : ''}
                        </span>
                      )}
                      {a.details && (
                        <div style={{ fontSize: '10px', color: 'var(--muted)', marginTop: '2px', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
              {loading && (
                <tr>
                  <td colSpan={5} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    Loading...
                  </td>
                </tr>
              )}
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