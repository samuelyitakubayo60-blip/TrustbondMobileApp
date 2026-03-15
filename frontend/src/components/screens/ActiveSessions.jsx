import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const ActiveSessions = () => {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    api
      .get('/api/v1/police-users/sessions')
      .then((res) => {
        if (!mounted) return;
        setSessions(res || []);
        setLoading(false);
      })
      .catch(() => {
        if (!mounted) return;
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <>
      <div className="page-header">
        <h2>Active Sessions</h2>
        <p>Recent login sessions, IP addresses, and user agents for security review.</p>
      </div>

      <div className="card">
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>IP Address</th>
                <th>User Agent</th>
                <th>Created</th>
                <th>Expires</th>
                <th>Revoked</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.session_id}>
                  <td style={{ fontSize: '11px' }}>
                    {s.user_name || `User #${s.police_user_id}`}
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
                </tr>
              ))}
              {!sessions.length && !loading && (
                <tr>
                  <td
                    colSpan={6}
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
                    colSpan={6}
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
      </div>
    </>
  );
};

export default ActiveSessions;

