import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';

export default function AuditLog() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterEntityType, setFilterEntityType] = useState('');
  const [filterActionType, setFilterActionType] = useState('');

  useEffect(() => {
    if (!isAdmin) navigate('/dashboard', { replace: true });
  }, [isAdmin, navigate]);

  const loadLogs = useCallback(() => {
    setLoading(true);
    setError(null);
    const params = { limit: 100 };
    if (filterEntityType) params.entity_type = filterEntityType;
    if (filterActionType) params.action_type = filterActionType;
    apiService
      .getAuditLogs(params)
      .then(setLogs)
      .catch((err) => setError(err.message || 'Failed to load audit log'))
      .finally(() => setLoading(false));
  }, [filterEntityType, filterActionType]);

  useEffect(() => {
    if (isAdmin) loadLogs();
  }, [isAdmin, loadLogs]);

  function formatDate(s) {
    if (!s) return '—';
    return new Date(s).toLocaleString();
  }

  if (!isAdmin) {
    return (
      <Layout>
        <div className="page-audit">
          <p className="error-message">Admin access required to view audit log.</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="page-audit">
        <h2>Audit log</h2>
        <div className="reports-filters">
          <input
            type="text"
            placeholder="Entity type (e.g. report)"
            value={filterEntityType}
            onChange={(e) => setFilterEntityType(e.target.value)}
            className="filter-input"
          />
          <input
            type="text"
            placeholder="Action type (e.g. report_assigned)"
            value={filterActionType}
            onChange={(e) => setFilterActionType(e.target.value)}
            className="filter-input"
          />
          <button type="button" className="btn-primary" onClick={loadLogs}>Apply</button>
        </div>
        {loading && <p className="loading">Loading…</p>}
        {error && <p className="error-message">{error}</p>}
        {!loading && !error && (
          <div className="table-wrap">
            <table className="reports-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Success</th>
                </tr>
              </thead>
              <tbody>
                {(Array.isArray(logs) ? logs : []).map((log) => (
                  <tr key={log.log_id}>
                    <td>{formatDate(log.created_at)}</td>
                    <td>{log.actor_type}{log.actor_id != null ? ` #${log.actor_id}` : ''}</td>
                    <td>{log.action_type}</td>
                    <td>{log.entity_type && log.entity_id ? `${log.entity_type} ${log.entity_id}` : (log.entity_type || '—')}</td>
                    <td>{log.success ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
