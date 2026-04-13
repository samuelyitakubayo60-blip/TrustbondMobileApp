import React, { useEffect, useState, useCallback } from 'react';
import api from '../../api/client';

const PAGE_SIZE = 50;

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
    params.set("limit", String(pageSize));
    
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
          // Backend doesn't return total count, so we'll estimate
          setTotal(res?.length || 0);
          setLoading(false); 
        } 
      })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [pageSize, entityFilter, actionFilter]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs, wsRefreshKey]);

  // Client-side filtering for search and result filter
  const filteredLogs = logs.filter((a) => {
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const blob = [
        a.actor_type,
        a.actor_name,
        a.action_type,
        a.entity_type,
        a.entity_id,
        a.details,
        a.result,
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
  const paginatedLogs = filteredLogs.slice(offset, offset + pageSize);

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
              {paginatedLogs.map((a, index) => (
                <tr key={a.log_id}>
                  <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                    {offset + index + 1}
                  </td>
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
              {(!paginatedLogs.length && !loading) && (
                <tr>
                  <td colSpan={10} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No audit entries.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={10} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
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
          </div>
          <div className="pagination">
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredLogs.length / pageSize)) }, (_, i) => {
              const pageNum = i + 1;
              const pageOffset = (pageNum - 1) * pageSize;
              const isCurrent = Math.floor(offset / pageSize) === pageNum - 1;
              return (
                <button
                  key={pageNum}
                  className={`page-btn ${isCurrent ? 'current' : ''}`}
                  onClick={() => setOffset(pageOffset)}
                >
                  {pageNum}
                </button>
              );
            })}
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