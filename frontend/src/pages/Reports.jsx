import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';

const PAGE_SIZE = 20;

export default function Reports() {
  const { isOfficer } = useAuth();
  const [data, setData] = useState({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterFrom, setFilterFrom] = useState('');
  const [filterTo, setFilterTo] = useState('');

  const loadReports = useCallback((offset = 0) => {
    setLoading(true);
    setError(null);
    const params = { limit: PAGE_SIZE, offset };
    if (filterStatus) params.rule_status = filterStatus;
    if (filterFrom) params.from_date = new Date(filterFrom).toISOString();
    if (filterTo) params.to_date = new Date(filterTo + 'T23:59:59.999Z').toISOString();
    apiService
      .getReports(params)
      .then((res) => {
        if (res.items !== undefined) {
          setData({ items: res.items || [], total: res.total ?? 0, limit: res.limit ?? PAGE_SIZE, offset: res.offset ?? 0 });
        } else {
          setData({ items: Array.isArray(res) ? res : [], total: (Array.isArray(res) ? res.length : 0), limit: PAGE_SIZE, offset: 0 });
        }
      })
      .catch((err) => setError(err.message || 'Failed to load reports'))
      .finally(() => setLoading(false));
  }, [filterStatus, filterFrom, filterTo]);

  useEffect(() => {
    loadReports(0);
  }, [loadReports]);

  const applyFilters = () => loadReports(0);
  const reports = data.items || [];
  const total = data.total ?? 0;
  const offset = data.offset ?? 0;
  const hasMore = offset + reports.length < total;
  const hasPrev = offset > 0;

  function formatDate(s) {
    if (!s) return '—';
    const d = new Date(s);
    return d.toLocaleString();
  }

  function statusColor(status) {
    switch (String(status).toLowerCase()) {
      case 'passed': return '#16a34a';
      case 'flagged': return '#ea580c';
      case 'rejected': return '#dc2626';
      default: return 'var(--nav-blue, #2563eb)';
    }
  }

  return (
    <Layout>
      <div className="page-reports">
        <h2>{isOfficer ? 'My assignments' : 'Reports'}</h2>
        <div className="reports-filters">
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="filter-select">
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="passed">Passed</option>
            <option value="flagged">Flagged</option>
            <option value="rejected">Rejected</option>
          </select>
          <input type="date" value={filterFrom} onChange={(e) => setFilterFrom(e.target.value)} className="filter-date" placeholder="From" />
          <input type="date" value={filterTo} onChange={(e) => setFilterTo(e.target.value)} className="filter-date" placeholder="To" />
          <button type="button" className="btn-primary" onClick={applyFilters}>Apply</button>
        </div>
        {loading && <p className="loading">Loading reports…</p>}
        {error && <p className="error-message">{error}</p>}
        {!loading && !error && reports.length === 0 && (
          <p className="empty">No reports yet.</p>
        )}
        {!loading && !error && reports.length > 0 && (
          <>
            <p className="reports-count">Showing {reports.length} of {total}</p>
            <div className="table-wrap">
              <table className="reports-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Location</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.report_id}>
                      <td>{formatDate(r.reported_at)}</td>
                      <td>{r.incident_type_name || `Type ${r.incident_type_id}`}</td>
                      <td>
                        <span className="status-badge" style={{ color: statusColor(r.rule_status) }}>
                          {r.rule_status}
                        </span>
                      </td>
                      <td>
                        {r.village_name ? (
                          <span className="location-village" title={r.latitude != null && r.longitude != null ? `${Number(r.latitude).toFixed(4)}, ${Number(r.longitude).toFixed(4)}` : ''}>
                            {r.village_name}
                          </span>
                        ) : r.latitude != null && r.longitude != null ? (
                          `${Number(r.latitude).toFixed(4)}, ${Number(r.longitude).toFixed(4)}`
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        <Link to={`/reports/${r.report_id}`} className="link-detail">View</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <button type="button" disabled={!hasPrev || loading} onClick={() => loadReports(Math.max(0, offset - PAGE_SIZE))}>
                Previous
              </button>
              <span className="pagination-info">{offset + 1}–{offset + reports.length} of {total}</span>
              <button type="button" disabled={!hasMore || loading} onClick={() => loadReports(offset + PAGE_SIZE)}>
                Next
              </button>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
