import React, { useEffect, useState, useCallback } from 'react';
import api from '../../api/client';

const PAGE_SIZE = 10;

const ActiveSessions = ({ wsRefreshKey }) => {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const loadSessions = useCallback(() => {
    let mounted = true;
    setLoading(true);
    
    const params = new URLSearchParams();
    params.set("limit", String(100)); // Get more data for client-side pagination
    
    api.get(`/api/v1/police-users/sessions?${params.toString()}`)
      .then((res) => {
        if (!mounted) return;
        setSessions(res || []);
        setTotal(res?.length || 0);
        setLoading(false);
      })
      .catch(() => {
        if (!mounted) return;
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []); // No dependencies since we always get all data

  useEffect(() => {
    loadSessions();
  }, [loadSessions, wsRefreshKey]);

  // Client-side filtering
  const filteredSessions = sessions.filter((s) => {
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const userName = (s.user_name || '').toLowerCase();
      if (!userName.includes(q)) {
        return false;
      }
    }
    if (statusFilter !== "all") {
      const isRevoked = statusFilter === "revoked";
      const hasRevoked = !!s.revoked_at;
      if (hasRevoked !== isRevoked) {
        return false;
      }
    }
    return true;
  });

  // Client-side pagination
  const paginatedSessions = filteredSessions.slice(offset, offset + pageSize);

  const revokeSession = async (userId) => {
    if (!window.confirm('Are you sure you want to revoke all sessions for this user?')) {
      return;
    }
    
    try {
      await api.post(`/api/v1/police-users/${userId}/revoke-sessions`);
      // Refresh the sessions list
      loadSessions();
    } catch (error) {
      console.error('Failed to revoke sessions:', error);
      alert('Failed to revoke sessions');
    }
  };

  const activeCount  = sessions.filter(s => !s.revoked_at).length;
  const revokedCount = sessions.filter(s =>  s.revoked_at).length;

  return (
    <>
      {/* ── Header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Active Sessions</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Recent login sessions, IP addresses, and user agents for security review.
            </p>
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Total sessions', value: sessions.length,  cls: 'sb-blue'   },
            { label: 'Active',         value: activeCount,       cls: 'sb-green'  },
            { label: 'Revoked',        value: revokedCount,      cls: 'sb-red'    },
            { label: 'Filtered',       value: filteredSessions.length, cls: 'sb-blue' },
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
            placeholder="Search by user name..."
            style={{ flex: 2 }}
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setOffset(0); }}
          />
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="revoked">Revoked</option>
          </select>
          <input
            className="input"
            type="number"
            min="10"
            max="100"
            placeholder="Rows"
            style={{ minWidth: '70px' }}
            value={pageSize}
            onChange={(e) => {
              const newSize = Math.max(10, Math.min(100, parseInt(e.target.value) || 25));
              setPageSize(newSize);
              setOffset(0);
            }}
          />
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>User</th>
                <th>IP Address</th>
                <th>User Agent</th>
                <th>Created</th>
                <th>Expires</th>
                <th>Revoked</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedSessions.map((s, index) => (
                <tr key={s.session_id}>
                  <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                    {offset + index + 1}
                  </td>
                  <td style={{ fontSize: '11px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span>{s.user_name || `User #${s.police_user_id}`}</span>
                      <span className={`badge ${s.revoked_at ? 'b-red' : 'b-green'}`} style={{ fontSize: 9 }}>
                        {s.revoked_at ? 'revoked' : 'active'}
                      </span>
                    </div>
                  </td>
                  <td
                    style={{
                      fontSize: '10px',
                      fontFamily: 'monospace',
                      color: 'var(--muted)',
                    }}
                  >
                    {s.ip_address || '—'}
                  </td>
                  <td
                    style={{
                      fontSize: '9px',
                      color: 'var(--muted)',
                      maxWidth: '260px',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                    title={s.user_agent || ''}
                  >
                    {s.user_agent || '—'}
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {s.created_at
                      ? new Date(s.created_at).toLocaleString()
                      : '—'}
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {s.expires_at
                      ? new Date(s.expires_at).toLocaleString()
                      : '—'}
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {s.revoked_at
                      ? new Date(s.revoked_at).toLocaleString()
                      : '—'}
                  </td>
                  <td>
                    {!s.revoked_at ? (
                      <button
                        className="btn btn-sm"
                        onClick={() => revokeSession(s.police_user_id)}
                        style={{ background: 'var(--c-danger-dim)', color: 'var(--danger)', border: '1px solid var(--c-danger-ring)', cursor: 'pointer' }}
                      >
                        Revoke
                      </button>
                    ) : (
                      <span className="badge b-gray" style={{ fontSize: 10 }}>Revoked</span>
                    )}
                  </td>
                </tr>
              ))}
              {!paginatedSessions.length && !loading && (
                <tr>
                  <td
                    colSpan={8}
                    style={{
                      fontSize: '12px',
                      color: 'var(--muted)',
                      textAlign: 'center',
                    }}
                  >
                    No active sessions.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td
                    colSpan={8}
                    style={{
                      fontSize: '12px',
                      color: 'var(--muted)',
                      textAlign: 'center',
                    }}
                  >
                    Loading…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Showing {Math.min(offset + 1, filteredSessions.length)}-{Math.min(offset + pageSize, filteredSessions.length)} of {filteredSessions.length} sessions
          </div>
          <div className="pagination">
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredSessions.length / pageSize)) }, (_, i) => {
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
              onClick={() => setOffset(Math.min(filteredSessions.length - pageSize, offset + pageSize))}
              disabled={offset + pageSize >= filteredSessions.length}
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default ActiveSessions;

